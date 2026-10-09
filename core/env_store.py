"""就地（in-place）修改 .env 的小工具。

为什么需要它
------------
`llm_config._persist_env` / `mineru_config._persist_env` 过去的做法是：
把 .env 逐行解析成 dict → 往 dict 里塞新值 → **把整个文件重新写一遍**。
结果是注释、分组、原有顺序全部丢失（只剩 k=v 列表）。

以前这没造成事故，只因为容器里根本没有 .env（`.dockerignore` 排除了它，
`/app/.env` 不存在），那些写入落在一个随容器销毁的临时文件上、等于白写。

现在为了让「改名接口」真的能改到宿主机的 .env，我们把
`../.env` bind mount 进了容器（见 docker-compose 的 x-api-volumes）。
一旦挂进来，整体覆写就会**破坏宿主机的 .env**，所以这里改成
"只替换指定键、其余行原样保留"，并且写前先备份。

另外：绑定挂载进来的是**单个文件**，对它做 os.replace() 会跨设备失败
（EXDEV: Invalid cross-device link），因此必须就地 open(path, "w") 写入。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import time

logger = logging.getLogger(__name__)

_KEY_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=")

MAX_BACKUPS = 5


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def env_path() -> str:
    """与 pydantic Settings 的 env_file=".env" 保持同一个相对位置。"""
    return os.path.join(project_root(), ".env")


def _escape(value: str) -> str:
    v = str(value)
    if "\n" in v or "\r" in v:
        raise ValueError("环境变量值不能包含换行符")
    # 首尾空格、引号、$、反引号、反斜杠、#（dotenv 里 # 起注释作用）都需要加引号
    if v != v.strip() or any(c in v for c in ('"', "'", "$", "`", "\\", "#")):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return v


def _backup_target(target: str) -> str:
    """备份尽量放到宿主机可见的卷里（/app/uploads 是 docker_uploads 卷），
    这样容器重建后备份还在；拿不到就退回到 .env 同目录。"""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for base in ("/app/uploads", os.path.join(project_root(), "uploads")):
        if os.path.isdir(base):
            d = os.path.join(base, "_env_backups")
            try:
                os.makedirs(d, exist_ok=True)
                return os.path.join(d, f".env.{stamp}.bak")
            except OSError:
                continue
    return f"{target}.bak.{stamp}"


def _prune_backups(directory: str, prefix: str) -> None:
    try:
        entries = sorted(
            (e for e in os.listdir(directory) if e.startswith(prefix)),
            reverse=True,
        )
        for name in entries[MAX_BACKUPS:]:
            os.remove(os.path.join(directory, name))
    except OSError:
        pass


def update_env_keys(updates: dict[str, str], path: str | None = None) -> dict:
    """只替换 / 追加指定键，其余行（含注释、空行、顺序）原样保留。

    返回 {path, updated, added, backup, changed}
    """
    target = path or env_path()
    wanted = {k: str(v) for k, v in (updates or {}).items() if k}
    if not wanted:
        return {"path": target, "updated": [], "added": [], "backup": None, "changed": False}

    lines: list[str] = []
    if os.path.exists(target):
        with open(target, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

    pending = dict(wanted)
    out: list[str] = []
    updated: list[str] = []
    for line in lines:
        m = _KEY_RE.match(line)
        if m and m.group(1) in pending:
            key = m.group(1)
            new_line = f"{key}={_escape(pending.pop(key))}"
            if new_line != line:
                updated.append(key)
            out.append(new_line)
        else:
            out.append(line)

    added = sorted(pending.keys())
    if added:
        if out and out[-1].strip():
            out.append("")
        if not any("品牌信息" in ln for ln in out):
            out.append("# ── 品牌信息（可用 PUT /api/app-config/config 修改）──")
        for key in added:
            out.append(f"{key}={_escape(pending[key])}")

    if not updated and not added:
        return {"path": target, "updated": [], "added": [], "backup": None, "changed": False}

    backup = None
    if os.path.exists(target):
        try:
            backup = _backup_target(target)
            shutil.copy2(target, backup)
            _prune_backups(os.path.dirname(backup), os.path.basename(backup).rsplit(".", 2)[0] or ".env")
        except OSError as e:
            logger.warning(f"[env_store] 备份 .env 失败（继续写入）: {e}")
            backup = None

    # 就地写入：target 可能是 bind mount 进来的单文件，对它做 os.replace()
    # 会跨设备失败（EXDEV），所以统一就地覆盖写；写坏了有上面的备份兜底。
    # 就地写不会改变文件原有的权限位 —— 这里刻意不 chmod：
    # 宿主机 .env 就是靠 world-writable 才让容器内的 app 用户写得进来。
    with open(target, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")

    return {
        "path": target,
        "updated": updated,
        "added": added,
        "backup": backup,
        "changed": True,
    }