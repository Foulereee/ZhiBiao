# -*- coding: utf-8 -*-
r"""正文编排（content_plan）阶段 —— 对标易标（OpenBidKit）的 writing_focus。

## 为什么要有这个阶段

我原来的链路是「大纲 → 逐章直接生成」，全链路**没有任何一次调用能看到全书
并决定"每一节写什么、边界在哪里"**。实测成稿 220 章里：

  · 只有 2 章（1%）含"承接/前述/综上"这类章间衔接表达；
  · 27%（59/215）的章节正文开头又把项目背景复述一遍；
  · 相邻章节 8-gram 重合度均值只有 0.037 —— 不是"抄"，而是**彼此没有分工**。

易标（`D:\Windows\Downloads\OpenBidKit_Yibiao-main`）的做法是把"互相可见"
换成"上游一次决策"：正文写作模型**被刻意致盲**（`contentGenerationAgent.cjs:434-441`
的第三条 user 消息只含本节材料），连贯性由三层保证：
① 事前全局事实；② **事中编排（本模块）**；③ 事后跨节事实核对。

易标编排阶段提示词原文（`contentGenerationTask.cjs:602-623`）：

  :602 「你负责本次投标技术方案正文生成，现在先完成基础编排。程序会处理并保存
        编排，再在同一会话中交给你生效结果和正文生成要求；**本阶段不要提前生成
        正文或图片**。」
  :613 「结合知识条目、招标文件关键信息，以及**完整目录中的上下级和同级关系**
        进行整体判断；读取方式自行决定。」
  :617 「4. writing_focus 用 **1-2 句话**概括本节正文重点，**不展开成正文**，
        不编造具体参数、周期、人员、设备、品牌、型号或承诺，**并避免与相邻章节
        重复**。」

本模块按这套要求实现，并**补上易标自身的一个缝隙**（报告 §5 指出：
`createContentPlanningStage` 的文件清单里没有全局事实，导致 writing_focus 可能
与事实口径脱节）—— 我们把【全书统一口径】作为编排输入，让边界划分建立在
已定死的事实之上。

## 编排结果怎么用

产出的 `{节点id: writing_focus}` 会：
  ① 挂到大纲节点上（`node["writing_focus"]`）；
  ② 随大纲一起落库（`outlines.tree`），重启不丢、可复用；
  ③ 在生成每章时作为【本节编排重点】注入该章请求（位于消息尾部，不破坏前缀缓存）。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

logger = logging.getLogger(__name__)

# 每个一级目录子树一次调用：输出规模可控（避免一次要模型吐回 190 条），
# 但**每次调用都带上完整目录**，保证它具备全书视野（易标 :613 的要求）。
MAX_SUBTREE_NODES = 60


PLAN_SYSTEM_PROMPT = """你是本次投标文件的正文编制总负责人。现在先完成**基础编排**：
为目录里的每一个小节确定"这一节到底写什么、边界在哪里"。

【本阶段严禁写正文】只输出每节的写作重点，不要展开成段落，不要写标题，不要配图。

编排要求：
1. 结合招标文件关键信息与【全书统一口径】，以及**完整目录中的上下级和同级关系**
   进行整体判断：同一件事只能由一个最合适的小节承担，其余小节不得重复。
2. writing_focus 用 **1-2 句话**概括本节正文重点：写什么、从哪个角度写、
   与相邻小节如何划清边界。
3. **不编造**具体参数、周期、人员、设备、品牌、型号或承诺 —— 这些必须来自
   招标文件或口径表；不确定的一律不写。
4. 明确**避免与相邻章节重复**：如果某个内容更适合由上级、下级或兄弟小节承担，
   就把它指给那一节，本节点只写自己的那一块。
5. 分支节点（有下级小节）的 writing_focus 要说明"本节作为该章总述，
   只交代总体思路，具体措施由下级小节展开"，避免与下级内容重复。

输出格式（严格 JSON，不要任何解释文字）：
{"plans": [{"id": "1.1", "writing_focus": "..."}, {"id": "1.2", "writing_focus": "..."}]}
其中 id 必须与目录里给出的 id 完全一致。"""


def _iter_nodes(chapters: list, depth: int = 1):
    """深度优先遍历，产出 (节点, 层级)。顺序与导出/落库一致。"""
    for n in chapters or []:
        if not isinstance(n, dict):
            continue
        yield n, depth
        yield from _iter_nodes(n.get("children") or [], depth + 1)


def format_outline_for_plan(chapters: list) -> str:
    """把完整目录压成紧凑文本：层级缩进 + id + 标题 + 说明。

    易标对应函数 `buildContentPlanningOutline`（`contentGenerationTask.cjs:504-535`）
    对每个节点输出 id/number/title/description，叶子另带 content_mode。
    """
    lines: list[str] = []
    for n, depth in _iter_nodes(chapters):
        nid = str(n.get("id") or "")
        title = str(n.get("title") or "").strip()
        desc = str(n.get("description") or "").strip()
        if not nid or not title:
            continue
        line = f"{'  ' * (depth - 1)}- [{nid}] {title}"
        if desc:
            line += f" —— {desc[:100]}"
        lines.append(line)
    return "\n".join(lines)


def collect_subtree_ids(node: dict) -> list[str]:
    """取一个节点及其全部后代的 id（编排的输出范围）。"""
    out: list[str] = []
    for n, _d in _iter_nodes([node]):
        nid = str(n.get("id") or "")
        if nid:
            out.append(nid)
    return out


def _parse_plans(raw) -> dict[str, str]:
    """从模型返回里稳健地取出 {id: writing_focus}。

    模型可能返回 {"plans":[...]} / [...] / {"1.1":"..."} 三种形态，
    也可能把 JSON 包在解释文字或代码围栏里 —— 一律容错，取不到就算空，
    **绝不因为编排失败而让整批正文生成失败**。
    """
    data = raw
    if isinstance(data, str):
        s = data.strip()
        s = re.sub(r"^```(?:json)?|```$", "", s, flags=re.M).strip()
        try:
            data = json.loads(s)
        except Exception:
            m = re.search(r"\{.*\}|\[.*\]", s, flags=re.S)
            if not m:
                return {}
            try:
                data = json.loads(m.group(0))
            except Exception:
                return {}

    out: dict[str, str] = {}
    items = None
    if isinstance(data, dict):
        if isinstance(data.get("plans"), list):
            items = data["plans"]
        elif isinstance(data.get("data"), list):
            items = data["data"]
        else:
            # {"1.1": "……"} 形态
            for k, v in data.items():
                if isinstance(v, str) and v.strip():
                    out[str(k)] = v.strip()[:400]
            return out
    elif isinstance(data, list):
        items = data

    for it in items or []:
        if not isinstance(it, dict):
            continue
        nid = str(it.get("id") or it.get("node_id") or "").strip()
        focus = str(
            it.get("writing_focus") or it.get("focus") or it.get("writingFocus") or ""
        ).strip()
        if nid and focus:
            out[nid] = focus[:400]
    return out


async def _plan_one_subtree(
    top_node: dict,
    outline_text: str,
    key_info: str,
    gateway,
    sem: asyncio.Semaphore,
) -> dict[str, str]:
    ids = collect_subtree_ids(top_node)[:MAX_SUBTREE_NODES]
    if not ids:
        return {}
    user = (
        f"【全书统一口径】\n{key_info or '（未提供）'}\n\n"
        f"【完整目录（全书视野，用于判断分工与边界）】\n{outline_text}\n\n"
        f"【本次需要你编排的小节 id】\n{', '.join(ids)}\n\n"
        f"请为上述 {len(ids)} 个小节逐一给出 writing_focus，"
        f"按 {{\"plans\": [{{\"id\": \"...\", \"writing_focus\": \"...\"}}]}} 输出。"
        f"只输出该子树内的 id，不要输出其他节点的内容。"
    )
    async with sem:
        try:
            raw = await gateway.collect_json(
                messages=[
                    {"role": "system", "content": PLAN_SYSTEM_PROMPT},
                    {"role": "user", "content": user[:60000]},
                ],
                temperature=0.3,
                max_tokens=8192,
            )
        except Exception as e:  # 编排失败绝不能让正文生成失败
            logger.warning("[正文编排] 子树 %s 编排失败: %s", top_node.get("id"), e)
            return {}
    plans = _parse_plans(raw)
    # 只保留本次请求范围内的 id，防止模型串到别的小节
    allowed = set(ids)
    return {k: v for k, v in plans.items() if k in allowed}


async def plan_writing_focus(
    chapters: list,
    key_info: str = "",
    gateway=None,
    concurrency: int = 3,
) -> dict[str, str]:
    """执行编排阶段，返回 {节点id: writing_focus}。

    chapters: 大纲根数组（每个节点含 id/title/description/children）
    key_info: 全书统一口径（台账文本）—— 补上易标编排阶段缺事实的缝隙
    gateway:  LLM 网关（需有 collect_json）

    按一级目录切分并发编排（每个子树一次调用），**每次调用都带完整目录**，
    兼顾"全书视野"与"输出规模可控"。
    """
    if not chapters or gateway is None:
        return {}
    outline_text = format_outline_for_plan(chapters)
    if not outline_text.strip():
        return {}

    tops = [n for n in chapters if isinstance(n, dict) and str(n.get("id") or "")]
    if not tops:
        return {}

    sem = asyncio.Semaphore(max(1, int(concurrency)))
    results = await asyncio.gather(
        *[_plan_one_subtree(t, outline_text, key_info, gateway, sem) for t in tops],
        return_exceptions=True,
    )
    merged: dict[str, str] = {}
    for r in results:
        if isinstance(r, dict):
            merged.update(r)
    logger.info(
        "[正文编排] 完成：一级子树=%s，产出 writing_focus=%s 条",
        len(tops), len(merged),
    )
    return merged


def attach_plans(chapters: list, plans: dict[str, str]) -> int:
    """把编排结果挂到（内存中的）大纲节点上，返回挂载条数。"""
    if not plans:
        return 0
    n = 0
    for node, _d in _iter_nodes(chapters):
        nid = str(node.get("id") or "")
        focus = plans.get(nid)
        if focus:
            node["writing_focus"] = focus
            n += 1
    return n


def node_path(chapters: list, target_id: str) -> str:
    """祖先标题链（对标易标 `chapter_path`，`contentGenerationAgent.cjs:144`）。

    「父 > 子 > 本节」这样一个极短字符串就能让模型知道自己站在全书的哪条分支上，
    成本几乎为零，但对层级一致、术语一致收益很大。
    """
    path: list[str] = []

    def walk(nodes: list, chain: list[str]) -> bool:
        for n in nodes or []:
            if not isinstance(n, dict):
                continue
            title = str(n.get("title") or "").strip()
            if str(n.get("id") or "") == target_id:
                path.extend(chain + [title])
                return True
            if walk(n.get("children") or [], chain + [title]):
                return True
        return False

    walk(chapters, [])
    return " > ".join(x for x in path if x)