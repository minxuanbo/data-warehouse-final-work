"""网易字段到 v1.0 采集契约的映射、岗位范围判断与记录校验。"""
import re
from datetime import datetime

SCHEMA_VERSION = "1.0"
SOURCE = "netease"
COMPANY = "网易"

# 网易社会招聘的岗位类别（firstPostTypeName）。游戏程序、技术、人工智能属于数字技术岗；
# 游戏艺术/策划、市场、运营、产品、职能支持、项目管理不进入核心样本。
CATEGORY_WHITELIST = ("技术", "游戏程序", "人工智能", "数据", "测试", "运维", "安全", "研发", "算法", "开发")
# 标题黑名单只做二次兜底，避免类目正确但岗位实际属于美术、销售或非技术项目管理。
TITLE_EXCLUDE = (
    "策划", "美术", "原画", "动画", "视觉设计", "UI设计", "交互设计",
    "销售", "商务", "售前", "产品经理", "项目经理",
    "招聘", "人力资源", "财务", "法务", "行政",
    "市场", "营销", "运营", "品牌", "公关", "客服", "采购",
)
OVERSEAS_LOCATIONS = (
    "海外", "美国", "新加坡", "日本", "韩国", "德国", "英国", "法国",
    "加拿大", "澳大利亚", "马来西亚", "越南", "印度", "巴西", "香港", "台湾", "澳门",
)
BRACKET = re.compile(r"[（(]([^（）()]{2,20})[）)]")
CITY_NAMES = frozenset({
    "北京", "上海", "广州", "深圳", "杭州", "成都", "武汉", "南京", "西安", "重庆",
    "天津", "苏州", "长沙", "郑州", "青岛", "厦门", "福州", "济南", "合肥", "昆明",
    "大连", "沈阳", "哈尔滨", "长春", "石家庄", "太原", "南昌", "南宁", "贵阳", "兰州",
    "乌鲁木齐", "拉萨", "银川", "西宁", "呼和浩特", "海口", "三亚", "珠海", "东莞", "佛山",
    "无锡", "常州", "宁波", "温州", "嘉兴", "绍兴", "中山", "惠州", "汕头", "扬州",
    "徐州", "烟台", "潍坊", "洛阳", "宜昌", "株洲", "桂林", "泉州", "香港", "澳门", "台北",
})

JOB_KEYS = (
    "schema_version", "source", "source_job_id", "batch_id", "observed_at",
    "source_url", "title_raw", "company_raw", "locations_raw", "category_raw",
    "education_raw", "experience_raw", "description_raw", "requirements_raw",
    "employment_type_raw", "salary_raw", "headcount_raw", "source_published_at_raw",
    "source_updated_at_raw", "raw_refs", "parser_version",
)


def _text(value):
    """空串按缺失处理，保留原始文本，不做清洗、译码或 HTML 反转义。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _locations(value):
    if not value:
        return None
    if isinstance(value, str):
        parts = [part.strip() for part in re.split(r"[、,，/|]+", value)]
    else:
        parts = [str(part).strip() for part in value]
    parts = [part for part in parts if part]
    return parts or None


def classify(post):
    """返回 (include/exclude/review, 原因)。review 仍需输出并交 C 复核。"""
    category = _text(post.get("firstPostTypeName")) or ""
    title = _text(post.get("name")) or ""
    locations = _locations(post.get("workPlaceNameList"))

    if not category:
        return "review", "firstPostTypeName 为空，待复核"
    if not any(word in category for word in CATEGORY_WHITELIST):
        return "exclude", f"类目不在数字技术范围：{category}"

    lowered = title.lower()
    for word in TITLE_EXCLUDE:
        if word.lower() in lowered:
            return "exclude", f"标题命中排除词：{word}"

    if locations and all(any(mark in loc for mark in OVERSEAS_LOCATIONS) for loc in locations):
        return "exclude", "工作地点为海外/港澳台"
    if not locations:
        return "review", "地点为空，待复核"
    return "include", None


def build_job(post, detail, batch_id, observed_at, list_ref, parser_version,
              detail_ref=None):
    """按契约输出一条来源岗位观察记录；列表已含完整正文，详情仅作抽样核对。"""
    source = detail if detail else post
    job_id = _text(source.get("id")) or _text(post.get("id"))
    locations = _locations(source.get("workPlaceNameList") or post.get("workPlaceNameList"))
    headcount = source.get("recruitNum") if source.get("recruitNum") is not None \
        else post.get("recruitNum")
    updated = source.get("updateTime") if source.get("updateTime") is not None \
        else post.get("updateTime")
    work_type = source.get("workType") if source.get("workType") is not None \
        else post.get("workType")
    refs = [list_ref] + ([detail_ref] if detail_ref else [])
    return {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE,
        "source_job_id": str(job_id),
        "batch_id": batch_id,
        "observed_at": observed_at,
        "source_url": f"https://hr.163.com/api/hr163/position/query?id={job_id}",
        "title_raw": _text(source.get("name") or post.get("name")),
        "company_raw": COMPANY,
        "locations_raw": locations,
        "category_raw": _text(source.get("firstPostTypeName") or post.get("firstPostTypeName")),
        "education_raw": _text(source.get("reqEducationName") or post.get("reqEducationName")),
        "experience_raw": _text(source.get("reqWorkYearsName") or post.get("reqWorkYearsName")),
        "description_raw": _text(source.get("description") or post.get("description")),
        "requirements_raw": _text(source.get("requirement") or post.get("requirement")),
        "employment_type_raw": str(work_type) if work_type not in (None, "") else None,
        "salary_raw": None,
        "headcount_raw": str(headcount) if headcount is not None else None,
        "source_published_at_raw": None,
        "source_updated_at_raw": str(updated) if updated is not None else None,
        "raw_refs": refs,
        "parser_version": parser_version,
    }


def norm_city(value):
    """来源地点写作“杭州市”，标题括号常写“杭州”；仅去掉行政级别后缀用于比对。"""
    return value.strip().removesuffix("市") if isinstance(value, str) else value


def title_city_conflicts(row):
    """标题括号内的城市与工作地点不一致时逐条返回说明，供异常文件登记。"""
    title = row.get("title_raw") or ""
    locations = row.get("locations_raw") or []
    if not locations:
        return []
    known = {norm_city(loc) for loc in locations}
    conflicts = []
    for content in BRACKET.findall(title):
        tokens = [norm_city(token) for token in re.split(r"[、,，/|]+", content) if token.strip()]
        if not tokens or not all(token in CITY_NAMES for token in tokens):
            continue
        if set(tokens) & known:
            continue
        conflicts.append(f"标题城市({content})与地点字段({','.join(locations)})不一致，保留原值待复核")
    return conflicts


EDU_RANK = {"大专": 1, "本科": 2, "硕士": 3, "博士": 4}


def education_conflict(row):
    """结构化学历低于正文明确的“X及以上”要求时登记冲突，两个原值都保留。"""
    structured = row.get("education_raw")
    text = row.get("requirements_raw") or ""
    if structured not in EDU_RANK:
        return None
    for level in ("博士", "硕士", "本科", "大专"):
        if f"{level}及以上" in text or f"{level}以上" in text:
            if EDU_RANK[level] > EDU_RANK[structured]:
                return f"结构化学历「{structured}」低于正文要求「{level}及以上」，保留原值待复核"
            return None
    return None


def text_issues(row):
    """返回 (rule, severity, action, message) 列表，不静默修正任何字段。"""
    issues = []
    if not row["description_raw"] and not row["requirements_raw"]:
        issues.append(("missing_body", "error", "review", "职责与任职要求均为空"))
    elif not row["requirements_raw"]:
        issues.append(("missing_requirements", "warning", "review", "来源未返回任职要求"))
    if not row["locations_raw"]:
        issues.append(("missing_location", "warning", "review", "地点为空"))
    conflict = education_conflict(row)
    if conflict:
        issues.append(("education_conflict", "warning", "review", conflict))
    for message in title_city_conflicts(row):
        issues.append(("location_conflict", "warning", "review", message))
    return issues


def compare_detail(list_row, detail_row):
    """对比列表与抽查详情的关键字段，返回不一致说明列表（不覆盖原值）。"""
    fields = (
        ("title_raw", "name"),
        ("category_raw", "firstPostTypeName"),
        ("locations_raw", "locations"),
        ("education_raw", "education"),
        ("experience_raw", "experience"),
        ("description_raw", "description"),
        ("requirements_raw", "requirement"),
        ("employment_type_raw", "employment_type"),
        ("headcount_raw", "headcount"),
        ("source_updated_at_raw", "updated_at"),
    )
    mismatches = []
    for key, label in fields:
        left, right = list_row.get(key), detail_row.get(key)
        if left != right:
            if isinstance(left, str) and isinstance(right, str):
                mismatches.append(f"{label}不一致（列表 {len(left)} 字/详情 {len(right)} 字）")
            else:
                mismatches.append(f"{label}不一致（列表 {left!r}/详情 {right!r}）")
    return mismatches


def validate_job(row):
    """按 v1.0 契约检查键、类型、必填项与时区；返回问题列表。"""
    problems = []
    missing = [key for key in JOB_KEYS if key not in row]
    extra = [key for key in row if key not in JOB_KEYS]
    if missing:
        problems.append(f"缺少字段：{missing}")
    if extra:
        problems.append(f"多余字段：{extra}")
    for key in JOB_KEYS:
        if key in ("locations_raw", "raw_refs"):
            continue
        value = row.get(key)
        if value is not None and not isinstance(value, str):
            problems.append(f"{key} 不是字符串或 null：{type(value).__name__}")
    for key in ("schema_version", "source", "batch_id", "observed_at", "source_job_id",
                "title_raw", "company_raw", "parser_version"):
        if not row.get(key):
            problems.append(f"必填字段为空：{key}")
    if row.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version 不是 1.0")
    if row.get("source") != SOURCE:
        problems.append("source 不是 netease")
    if len(row.get("source_job_id") or "") > 200:
        problems.append("source_job_id 超过 200 字符")
    try:
        moment = datetime.fromisoformat(str(row.get("observed_at")).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            problems.append("observed_at 缺少时区")
    except ValueError:
        problems.append("observed_at 不是合法 ISO 8601")
    locations = row.get("locations_raw")
    if locations is not None and not (
            isinstance(locations, list) and all(isinstance(item, str) for item in locations)):
        problems.append("locations_raw 不是字符串数组或 null")
    refs = row.get("raw_refs")
    if not isinstance(refs, list) or not refs:
        problems.append("raw_refs 必须为非空数组")
    else:
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
                problems.append("raw_refs 每项必须只含 path 与 sha256")
                break
            if not str(ref["path"]).startswith("raw/") or "/../" in str(ref["path"]):
                problems.append("raw_refs path 必须相对批次目录并以 raw/ 开头")
            if not re.fullmatch(r"[0-9a-f]{64}", str(ref["sha256"])):
                problems.append("raw_refs sha256 不是 64 位小写十六进制")
    return problems
