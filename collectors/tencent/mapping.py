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


def text_issues(row):
    """返回 (rule, severity, action, message) 列表，不静默修正任何字段。"""
    issues = []
    if not row["description_raw"] and not row["requirements_raw"]:
        issues.append(("missing_body", "error", "review", "职责与任职要求均为空"))
    elif not row["requirements_raw"]:
        issues.append(("missing_requirements", "warning", "review", "详情未返回任职要求"))
    if not row["locations_raw"]:
        issues.append(("missing_location", "warning", "review", "地点为空"))
    return issues
