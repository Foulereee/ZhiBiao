"""招投标行业分类字典 (参考 AIMedia classify.py)

静态数据驱动的行业分类,所有数据源通过 industry_code 关联到具体行业。
前端展示时按一级分类聚合,后端做商机筛选/统计时按 code 过滤。
"""

# 行业一级分类 + 子分类
BIDDING_INDUSTRIES = [
    {
        "code": "01",
        "name": "工程建设",
        "icon": "🏗️",
        "weight": 1.0,
        "children": [
            {"code": "0101", "name": "房屋建筑", "weight": 1.0},
            {"code": "0102", "name": "市政工程", "weight": 0.9},
            {"code": "0103", "name": "交通工程", "weight": 0.95},
            {"code": "0104", "name": "水利工程", "weight": 0.9},
            {"code": "0105", "name": "电力工程", "weight": 0.95},
            {"code": "0106", "name": "通信工程", "weight": 0.85},
            {"code": "0107", "name": "装饰装修", "weight": 0.7},
            {"code": "0108", "name": "园林绿化", "weight": 0.7},
        ],
    },
    {
        "code": "02",
        "name": "货物采购",
        "icon": "📦",
        "weight": 1.0,
        "children": [
            {"code": "0201", "name": "设备采购", "weight": 0.95},
            {"code": "0202", "name": "材料采购", "weight": 0.9},
            {"code": "0203", "name": "信息化采购", "weight": 1.0},
            {"code": "0204", "name": "医疗器械", "weight": 0.85},
            {"code": "0205", "name": "办公用品", "weight": 0.6},
        ],
    },
    {
        "code": "03",
        "name": "服务招标",
        "icon": "💼",
        "weight": 0.9,
        "children": [
            {"code": "0301", "name": "咨询服务", "weight": 0.85},
            {"code": "0302", "name": "运维服务", "weight": 0.9},
            {"code": "0303", "name": "勘察设计", "weight": 0.85},
            {"code": "0304", "name": "监理服务", "weight": 0.8},
            {"code": "0305", "name": "物业管理", "weight": 0.7},
        ],
    },
    {
        "code": "04",
        "name": "政府采购",
        "icon": "🏛️",
        "weight": 1.0,
        "children": [
            {"code": "0401", "name": "中央采购", "weight": 1.0},
            {"code": "0402", "name": "省级采购", "weight": 0.95},
            {"code": "0403", "name": "市级采购", "weight": 0.9},
            {"code": "0404", "name": "区县级采购", "weight": 0.8},
        ],
    },
    {
        "code": "05",
        "name": "能源化工",
        "icon": "⚡",
        "weight": 0.9,
        "children": [
            {"code": "0501", "name": "电力电网", "weight": 0.95},
            {"code": "0502", "name": "石油石化", "weight": 0.9},
            {"code": "0503", "name": "煤炭矿山", "weight": 0.85},
            {"code": "0504", "name": "新能源", "weight": 1.0},
        ],
    },
    {
        "code": "06",
        "name": "医疗卫生",
        "icon": "🏥",
        "weight": 0.85,
        "children": [
            {"code": "0601", "name": "医院采购", "weight": 0.9},
            {"code": "0602", "name": "药品采购", "weight": 0.85},
            {"code": "0603", "name": "医疗设备", "weight": 0.85},
        ],
    },
    {
        "code": "07",
        "name": "教育培训",
        "icon": "🎓",
        "weight": 0.7,
        "children": [
            {"code": "0701", "name": "高校采购", "weight": 0.75},
            {"code": "0702", "name": "义务教育", "weight": 0.7},
        ],
    },
    {
        "code": "08",
        "name": "金融保险",
        "icon": "🏦",
        "weight": 0.7,
        "children": [
            {"code": "0801", "name": "银行采购", "weight": 0.75},
            {"code": "0802", "name": "证券保险", "weight": 0.7},
        ],
    },
    {
        "code": "09",
        "name": "交通运输",
        "icon": "🚄",
        "weight": 0.9,
        "children": [
            {"code": "0901", "name": "铁路工程", "weight": 0.95},
            {"code": "0902", "name": "公路工程", "weight": 0.9},
            {"code": "0903", "name": "航空机场", "weight": 0.9},
            {"code": "0904", "name": "水运港口", "weight": 0.85},
        ],
    },
    {
        "code": "10",
        "name": "通信信息",
        "icon": "📡",
        "weight": 0.95,
        "children": [
            {"code": "1001", "name": "运营商采购", "weight": 0.95},
            {"code": "1002", "name": "软件开发", "weight": 1.0},
            {"code": "1003", "name": "系统集成", "weight": 0.95},
        ],
    },
    {
        "code": "11",
        "name": "环保绿化",
        "icon": "🌳",
        "weight": 0.75,
        "children": [
            {"code": "1101", "name": "环境治理", "weight": 0.8},
            {"code": "1102", "name": "园林绿化", "weight": 0.7},
        ],
    },
    {
        "code": "12",
        "name": "其他",
        "icon": "📋",
        "weight": 0.5,
        "children": [
            {"code": "1201", "name": "综合", "weight": 0.5},
        ],
    },
]

# 扁平化 code -> name 映射,用于快速查找
INDUSTRY_NAME_MAP: dict[str, str] = {}
for _cat in BIDDING_INDUSTRIES:
    INDUSTRY_NAME_MAP[_cat["code"]] = _cat["name"]
    for _sub in _cat["children"]:
        INDUSTRY_NAME_MAP[_sub["code"]] = f"{_cat['name']}/{_sub['name']}"


def get_industry_name(code: str) -> str:
    """根据行业 code 获取名称"""
    return INDUSTRY_NAME_MAP.get(code, "未分类")


def get_industry_icon(code: str) -> str:
    """根据行业 code 获取图标"""
    for cat in BIDDING_INDUSTRIES:
        if cat["code"] == code:
            return cat["icon"]
    return "📋"


def list_industries_tree() -> list[dict]:
    """返回树形行业结构供前端展示"""
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
