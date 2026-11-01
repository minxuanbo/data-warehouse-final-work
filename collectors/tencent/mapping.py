"""腾讯字段到 v1.0 采集契约的映射，以及岗位范围判断。"""
import re

SCHEMA_VERSION = "1.0"
SOURCE = "tencent"
COMPANY = "腾讯"

# 岗位范围：只保留数字技术类。腾讯 CategoryName 目前可见值为“技术”“产品”“设计”等，
# 白名单按字面包含技术类关键词，避免把设计/产品/市场整类带入样本。
CATEGORY_WHITELIST = ("技术", "研发", "数据", "测试", "运维", "安全", "算法", "开发")
# 标题黑名单只做二次兜底；明确排除游戏美术、纯销售、纯产品和非技术项目管理。
TITLE_EXCLUDE = (
    "策划", "美术", "原画", "动画", "视觉设计", "UI设计",
    "销售", "商务", "售前", "产品经理", "项目经理",
    "招聘", "人力资源", "财务", "法务", "行政",
)
OVERSEAS_LOCATIONS = (
    "海外", "美国", "新加坡", "日本", "韩国", "德国", "英国", "法国",
    "加拿大", "澳大利亚", "马来西亚", "越南", "印度", "巴西", "香港", "台湾", "澳门",
)
LOCATION_SPLIT = re.compile(r"[、,，/|]+")
BRACKET = re.compile(r"[（(]([^（）()]{2,20})[）)]")
# 只有括号内容全部是已知城市时才判定为城市冲突，避免把（U3D方向）（TTS）等误判。
CITY_NAMES = frozenset({
    "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "西安", "重庆",
    "天津", "苏州", "长沙", "郑州", "青岛", "厦门", "福州", "济南", "合肥", "昆明",
    "大连", "沈阳", "哈尔滨", "长春", "石家庄", "太原", "南昌", "南宁", "贵阳", "兰州",
    "乌鲁木齐", "拉萨", "银川", "西宁", "呼和浩特", "海口", "三亚", "珠海", "东莞", "佛山",
    "无锡", "常州", "宁波", "温州", "嘉兴", "绍兴", "中山", "惠州", "汕头", "扬州",
    "徐州", "烟台", "潍坊", "洛阳", "宜昌", "株洲", "桂林", "泉州", "香港", "澳门", "台北",
})


def split_locations(value):
    """地点保留为字符串数组，多地点不拆成重复岗位。"""
    if not value:
        return None
    parts = [part.strip() for part in LOCATION_SPLIT.split(value)]
    parts = [part for part in parts if part]
    return parts or None


def classify(post):
    """返回 (include/exclude/review, 原因)。review 仍需输出并交 C 复核。"""
    category = (post.get("CategoryName") or "").strip()
    title = (post.get("RecruitPostName") or "").strip()
    locations = split_locations(post.get("LocationName"))

    if not category:
        return "review", "category 为空，待复核"
    if not any(word in category for word in CATEGORY_WHITELIST):
        return "exclude", f"类目不在技术范围：{category}"

    lowered = title.lower()
    for word in TITLE_EXCLUDE:
        if word.lower() in lowered:
            return "exclude", f"标题命中排除词：{word}"

    if locations and all(any(mark in loc for mark in OVERSEAS_LOCATIONS) for loc in locations):
        return "exclude", "工作地点为海外/港澳台"
    if not locations:
        return "review", "地点为空，待复核"
    return "include", None


def _text(value):
    """空串按缺失处理，保留原始文本不做清洗或 HTML 反转义。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_job(post, detail, batch_id, observed_at, list_ref, detail_ref, parser_version):
    """按契约输出一条来源岗位观察记录；详情优先，列表兜底。"""
    source = detail if detail else post
    locations = split_locations(source.get("LocationName") or post.get("LocationName"))
    employment_code = source.get("OuterPostTypeID")
    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "source_job_id": str(source.get("PostId") or post.get("PostId")),
        "batch_id": batch_id,
        "observed_at": observed_at,
        "source_url": _text(source.get("PostURL") or post.get("PostURL")),
        "title_raw": _text(source.get("RecruitPostName") or post.get("RecruitPostName")),
        "company_raw": COMPANY,
        "locations_raw": locations,
        "category_raw": _text(source.get("CategoryName") or post.get("CategoryName")),
        "education_raw": None,
        "experience_raw": _text(source.get("RequireWorkYearsName") or post.get("RequireWorkYearsName")),
        "description_raw": _text(source.get("Responsibility") or post.get("Responsibility")),
        "requirements_raw": _text(source.get("Requirement") or post.get("Requirement")),
        "employment_type_raw": str(employment_code) if employment_code not in (None, "") else None,
        "salary_raw": None,
        "headcount_raw": None,
        "source_published_at_raw": None,
        "source_updated_at_raw": _text(source.get("LastUpdateTime") or post.get("LastUpdateTime")),
        "raw_refs": [list_ref, detail_ref],
        "parser_version": parser_version,
    }


def title_city_conflicts(row):
    """标题括号内的城市与 LocationName 不一致时逐条返回冲突说明，供异常文件登记。"""
    title = row.get("title_raw") or ""
    locations = row.get("locations_raw") or []
    if not locations:
        return []
    known = {loc.strip() for loc in locations}
    conflicts = []
    for content in BRACKET.findall(title):
        tokens = [token.strip() for token in LOCATION_SPLIT.split(content) if token.strip()]
        if not tokens or not all(token in CITY_NAMES for token in tokens):
            continue
        if set(tokens) & known:
            continue
        conflicts.append(f"标题城市({content})与地点字段({','.join(locations)})不一致，保留原值待复核")
    return conflicts


def text_issues(row):
    """返回 (rule, severity, action, message) 列表，不静默修正任何字段。"""
    issues = []
    if not row["description_raw"] and not row["requirements_raw"]:
        issues.append(("missing_body", "error", "review", "职责与任职要求均为空"))
    elif not row["requirements_raw"]:
        issues.append(("missing_requirements", "warning", "review", "详情未返回任职要求"))
    if not row["locations_raw"]:
        issues.append(("missing_location", "warning", "review", "地点为空"))
    for message in title_city_conflicts(row):
        issues.append(("location_conflict", "warning", "review", message))
    return issues
