"""可解释的词典提取；偏移为 Python Unicode 字符下标，end 不包含在内。"""
import re

RULE_VERSION = "skills-rules-0.3.0"
BODY_HASH_VERSION = "skills-body-1.1"
FIELDS = ("description_raw", "requirements_raw", "additional_requirements_raw")
VALID_LEVELS = {"必需", "优先", "提及"}


def alias_pattern(alias):
    left = r"(?<![A-Za-z0-9_])" if alias[0].isascii() else ""
    right = r"(?![A-Za-z0-9_#])" if alias[-1].isascii() else ""
    if alias == "C":
        right = r"(?![A-Za-z0-9_+#]|端)"
    return re.compile(left + re.escape(alias) + right, re.IGNORECASE)


def clauses(text):
    # 逗号只在新谓语或转折前切分，保留 PyTorch、TensorFlow 等技能列表。
    splitter = r"[\r\n。；;]+|[，,](?=(?:但|而|同时|熟悉|掌握|精通|具备|至少掌握|能熟练使用|深入掌握|深入理解|有[^，,。；;\r\n]{0,32}经验))"
    start = 0
    for match in re.finditer(splitter, text):
        if text[start:match.start()].strip():
            yield start, match.start(), text[start:match.start()]
        start = match.end()
    if text[start:].strip():
        yield start, len(text), text[start:]


def context(field, clause, match_start, priority_section=False):
    negative = re.search(r"不要求|不需要|无需|无须|不必|不用|不涉及|不使用|不熟悉|非必[需要须]|并非必[需要须]|不是必[需要须]|不作为硬性|无.{0,18}经验也可", clause)
    alternative = bool(re.search(r"至少(?:掌握|熟悉|精通|熟练掌握|熟练使用)?\s*[一二两三四五六七八九十1-9]\s*(?:种|门|项|类|套)|[一1](?:种|门)以上|任[一意]|其中一|之一|一种或多种|一门或多门|或其他|或同类|[A-Za-z+#]+\s*或|或\s*[A-Za-z+#]+|、[^，。；]{1,12}或", clause))
    generic = re.search(r"(?:和|以及|及)至少(?:掌握)?[一1](?:种|门)(?:数据处理)?脚本语言", clause)
    if generic and match_start < generic.start():
        alternative = False
    if negative:
        return "不确定", "negated", alternative
    if alternative:
        return "不确定", "alternative", True
    if priority_section or re.search(r"优先|加分|更佳|尤佳|更优", clause):
        return "优先", "positive", False
    if field == "description_raw":
        return "提及", "positive", False
    if re.search(r"熟悉|掌握|精通|熟练|了解|理解|使用|经验|能力|基础|具备|需", clause):
        return "必需", "positive", False
    return "不确定", "uncertain", False


def extract(job, dictionary):
    rows = []
    compiled = [(skill, alias, alias_pattern(alias)) for skill in dictionary["skills"] for alias in skill["aliases"]]
    for field in FIELDS:
        body = job.get(field) or ""
        priority_section = False
        for begin, end, clause in clauses(body):
            heading = re.sub(r"^\s*\d+[.、)）]\s*", "", clause).strip()
            if re.fullmatch(r"(?:加分项|加分条件|优先条件|优先项)\s*[：:]?", heading):
                priority_section = True
                continue
            if re.fullmatch(r"(?:必备条件|必需条件|任职要求|岗位要求)\s*[：:]?", heading):
                priority_section = False
                continue
            hits = []
            for skill, alias, pattern in compiled:
                for match in pattern.finditer(clause):
                    if skill["name"] == "React" and match.group() == "ReAct":
                        continue
                    hits.append((match.start(), match.end(), skill, alias, match.group()))
            selected = []
            for hit in sorted(hits, key=lambda h: (-(h[1] - h[0]), h[0], h[2]["name"])):
                if not any(hit[0] < old[1] and old[0] < hit[1] for old in selected):
                    selected.append(hit)
            for start, stop, skill, alias, matched in sorted(selected, key=lambda h: h[0]):
                level, polarity, alternative = context(field, clause, start, priority_section)
                rows.append({
                    **{key: job[key] for key in ("source", "source_job_id", "batch_id")},
                    "skill_name": skill["name"], "skill_category": skill["category"],
                    "requirement_level": level, "context_polarity": polarity,
                    "alternative_group": clause.strip() if alternative else None,
                    "evidence_field": field, "evidence": clause,
                    "evidence_start": begin, "evidence_end": end,
                    "match_start": begin + start, "match_end": begin + stop,
                    "matched_text": matched, "matched_alias": alias,
                    "dictionary_version": dictionary["version"], "rule_version": RULE_VERSION,
                    "eligible_for_metric": polarity == "positive" and level in VALID_LEVELS,
                })
    return rows
