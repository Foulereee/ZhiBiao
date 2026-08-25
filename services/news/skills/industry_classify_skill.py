"""行业自动分类 Skill (借鉴 article-generation-skill 的关键词分类思路)

- 基于 services/news/classify.py 的行业字典
- 通过标题+内容的关键词匹配为热点打上 industry_code
- 提供纯本地规则分类,无需 LLM 调用,速度快、可解释
"""
from __future__ import annotations

import re
import logging
from typing import Any

from core.skill_engine.base import Skill, SkillContext, SkillResult
from services.news.classify import (
    BIDDING_INDUSTRIES,
    get_industry_name,
    get_industry_icon,
)

logger = logging.getLogger(__name__)


# 行业关键词映射 (与 BIDDING_INDUSTRIES 子分类对应)
INDUSTRY_KEYWORDS: dict[str, list[str]] = {
    "0101": ["房屋建筑", "住宅楼", "办公楼", "教学楼", "厂房", "房建", "土建", "施工总承包"],
    "0102": ["市政", "道路", "桥梁", "隧道", "管网", "供水", "排水", "燃气管道"],
    "0103": ["交通", "高速", "公路", "城际", "轨道", "地铁", "轻轨", "BRT"],
    "0104": ["水利", "水库", "河道", "堤防", "泵站", "灌区", "水电枢纽"],
    "0105": ["电力工程", "变电站", "输电", "配电", "电缆敷设"],
    "0106": ["通信工程", "基站", "线路施工", "通信管道"],
    "0107": ["装饰", "装修", "幕墙", "精装修"],
    "0108": ["园林", "绿化", "景观", "苗木"],

    "0201": ["设备", "机械", "机床", "起重机", "锅炉"],
    "0202": ["钢材", "水泥", "建材", "砂石", "混凝土"],
    "0203": ["信息化", "软件", "信息系统", "数据中心", "服务器", "云计算", "SaaS"],
    "0204": ["医疗", "CT", "核磁", "监护仪", "手术室"],
    "0205": ["办公用品", "文具", "耗材", "打印"],

    "0301": ["咨询", "顾问", "可行性研究", "方案设计"],
    "0302": ["运维", "运营维护", "驻场", "IT服务"],
    "0303": ["勘察", "设计", "测绘", "勘测"],
    "0304": ["监理", "工程监理", "项目监理"],
    "0305": ["物业", "保洁", "保安", "物业服务"],

    "0401": ["中央", "部委", "国务院", "国家机关"],
    "0402": ["省级", "省本级"],
    "0403": ["市级", "地级市", "市本级"],
    "0404": ["区县", "县级", "区级", "乡镇"],

    "0501": ["电网", "供电", "电力", "智能电网"],
    "0502": ["石油", "石化", "中石油", "中石化", "中海油"],
    "0503": ["煤炭", "矿山", "矿井", "采煤"],
    "0504": ["新能源", "光伏", "风电", "储能", "充电桩", "氢能"],

    "0601": ["医院", "卫生院", "疾控", "急救中心"],
    "0602": ["药品", "药剂", "疫苗"],
    "0603": ["医疗设备", "医疗器械"],

    "0701": ["高校", "大学", "学院", "研究所"],
    "0702": ["中小学", "义务教育", "幼儿园"],

    "0801": ["银行", "人民银行", "工商银行", "建设银行", "农业银行"],
    "0802": ["证券", "保险", "期货", "基金"],

    "0901": ["铁路", "高铁", "动车", "客运专线"],
    "0902": ["公路", "高速公路", "国道", "省道"],
    "0903": ["航空", "机场", "航站楼", "空管"],
    "0904": ["水运", "港口", "码头", "航道"],

    "1001": ["移动", "联通", "电信", "运营商", "5G"],
    "1002": ["软件开发", "APP", "小程序", "系统开发", "AI", "人工智能", "大模型", "LLM", "GPT", "深度学习", "机器学习", "ChatGPT", "Claude", "通义", "文心", "智谱", "Kimi", "豆包"],
    "1003": ["系统集成", "智能化", "物联网", "IoT", "芯片", "半导体", "嵌入式"],

    "1101": ["环境治理", "污水处理", "垃圾处理", "大气治理", "VOC"],
    "1102": ["园林", "绿化"],

    "1201": [],
}

# 行政区划关键词,用于 region 字段提取
REGION_KEYWORDS = [
    "北京市", "上海市", "天津市", "重庆市",
    "河北省", "山西省", "辽宁省", "吉林省", "黑龙江省",
    "江苏省", "浙江省", "安徽省", "福建省", "江西省", "山东省",
    "河南省", "湖北省", "湖南省", "广东省", "海南省",
    "四川省", "贵州省", "云南省", "陕西省", "甘肃省", "青海省",
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "台湾",
    "香港", "澳门",
]
RE_REGION = re.compile("|".join(re.escape(r) for r in REGION_KEYWORDS))

# 金额匹配 (支持 万元 / 亿元)
RE_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*(万元|亿元|元|亿|万)")


class IndustryClassifySkill(Skill):
    """行业自动分类 Skill

    输入: items: List[dict] (每项需有 title/content 字段)
    输出: 同一列表,但每项多出 industry_code / industry_name / region / amount
    """

    name = "industry_classify"
    description = "行业自动分类 (基于本地关键词,无需 LLM)"
    category = "news"
    version = "1.0.0"
    triggers = ["分类", "行业识别", "industry"]

    async def execute(self, ctx: SkillContext) -> SkillResult:
        items = ctx.parameters.get("items", []) or []
        if not items:
            return SkillResult(
                success=True,
                data={"items": [], "total": 0, "classified": 0},
            )

        classified = 0
        for item in items:
            try:
                self._classify_one(item)
                if item.get("industry_code"):
                    classified += 1
            except Exception as e:
                logger.warning(f"分类失败: {e}")

        return SkillResult(
            success=True,
            data={
                "items": items,
                "total": len(items),
                "classified": classified,
            },
        )

    def _classify_one(self, item: dict) -> None:
        """对单条资讯做行业识别 + 地域/金额提取"""
        title = item.get("title", "") or ""
        content = (item.get("content", "") or "")[:1000]
        text = f"{title} {content}"

        # 1. 行业识别 (按子分类)
        best_code = item.get("industry_code", "") or ""
        best_score = 0

        for code, keywords in INDUSTRY_KEYWORDS.items():
            if not keywords:
                continue
            hit = sum(1 for kw in keywords if kw in text)
            if hit > best_score:
                best_score = hit
                best_code = code

        if not best_code or best_score == 0:
            best_code = "1201"  # 默认其他

        item["industry_code"] = best_code
        item["industry_name"] = get_industry_name(best_code)
        item["industry_icon"] = get_industry_icon(best_code[:2])

        # 2. 地域提取
        if not item.get("region"):
            region_match = RE_REGION.search(text)
            if region_match:
                item["region"] = region_match.group(0)

        # 3. 金额提取 (转换为元)
        if not item.get("amount"):
            amount_match = RE_AMOUNT.search(text)
            if amount_match:
                value = float(amount_match.group(1))
                unit = amount_match.group(2)
                if unit == "亿元" or unit == "亿":
                    value *= 1e8
                elif unit == "万元" or unit == "万":
                    value *= 1e4
                item["amount"] = value

    @staticmethod
    def list_industries() -> list[dict]:
        """暴露给前端选择器的行业列表"""
        return [
            {
                "code": cat["code"],
                "name": cat["name"],
                "icon": cat["icon"],
                "weight": cat["weight"],
                "children": cat["children"],
            }
            for cat in BIDDING_INDUSTRIES
        ]
