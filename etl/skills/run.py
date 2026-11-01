"""离线分析腾讯增强批次与网易首批；python -m etl.skills.run --source tencent|netease。"""
import argparse
import collections
import csv
import hashlib
import itertools
import json
from pathlib import Path
import re
import subprocess

from .extract import BODY_HASH_VERSION, FIELDS, RULE_VERSION, extract

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BATCH = "tencent_20261031T093102Z_366ad0a4"
BATCHES = {"tencent": DEFAULT_BATCH, "netease": "netease_20261101T044527Z_157cf969"}
HANDOFF_PATH = "data/derived/tencent/" + DEFAULT_BATCH + "/cd_v1.1"
DEFAULT_HANDOFF_REF = "e9c6ba35d3230ffc48e0181b18f3ba6f6cf77cfe"
REFERENCE_PATH = Path(__file__).with_name("reviewed_samples_v1_1.json")
CONFLICT = "冲突待确认"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def digest(path):
    return sha256(path.read_bytes())


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8", newline="\n")


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            values = {key: json.dumps(row.get(key), ensure_ascii=False) if isinstance(row.get(key), (list, dict)) else row.get(key) for key in fields}
            # JSONL 保持原文；CSV 阻止来源文本被 Excel 当作公式。
            writer.writerow({key: "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value for key, value in values.items()})


def safe_file(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"输入引用不在批次目录内或文件缺失：{relative}")
    return path


def identity(job):
    return tuple(job[key] for key in ("source", "source_job_id", "batch_id"))


def read_batch(batch):
    manifest = load_json(batch / "manifest.json")
    listed = {}
    for item in manifest["files"]:
        path = safe_file(batch, item["path"])
        if item["path"] in listed or path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            raise ValueError(f"清单校验失败：{item['path']}")
        listed[item["path"]] = item["sha256"]
    if "jobs.jsonl" not in listed:
        raise ValueError("清单未列出 jobs.jsonl")
    jobs = [json.loads(line) for line in (batch / "jobs.jsonl").read_text("utf-8").splitlines() if line.strip()]
    seen = set()
    for job in jobs:
        for key in ("source", "source_job_id", "batch_id"):
            if not isinstance(job.get(key), str) or not job[key].strip():
                raise ValueError(f"身份键必须为非空字符串：{key}")
        if job["batch_id"] != manifest["batch_id"] or job["source"] != manifest["source"] or identity(job) in seen:
            raise ValueError("岗位身份重复或与批次不符")
        seen.add(identity(job))
        for field in (*FIELDS[:2], "title_raw", "education_raw", "experience_raw", "category_raw"):
            if field not in job or (job[field] is not None and not isinstance(job[field], str)):
                raise ValueError(f"字段类型不符：{field}")
        if job.get("locations_raw") is not None and (not isinstance(job["locations_raw"], list) or not all(isinstance(x, str) for x in job["locations_raw"])):
            raise ValueError("locations_raw 必须为字符串数组或 null")
        if not isinstance(job.get("raw_refs"), list) or not job["raw_refs"]:
            raise ValueError("缺少原始响应引用")
        for ref in job["raw_refs"]:
            if listed.get(ref["path"]) != ref["sha256"]:
                raise ValueError(f"引用与清单不符：{ref['path']}")
            safe_file(batch, ref["path"])
    if len(jobs) != manifest["counts"]["output_records"]:
        raise ValueError("岗位条数与清单不符")
    return jobs, manifest


def read_enriched(batch, original, directory=None, revision=DEFAULT_HANDOFF_REF):
    if directory is not None:
        raw_manifest = safe_file(directory, "manifest.json").read_bytes()
        data = safe_file(directory, "jobs_enriched.jsonl").read_bytes()
        resolved = None
    else:
        resolved = subprocess.check_output(["git", "rev-parse", "--verify", revision], cwd=ROOT).decode().strip()
        if subprocess.check_output(["git", "cat-file", "-t", resolved], cwd=ROOT).decode().strip() != "commit":
            raise ValueError("交接版本必须指向Git提交")
        raw_manifest = subprocess.check_output(["git", "show", resolved + ":" + HANDOFF_PATH + "/manifest.json"], cwd=ROOT)
        data = subprocess.check_output(["git", "show", resolved + ":" + HANDOFF_PATH + "/jobs_enriched.jsonl"], cwd=ROOT)
    manifest = json.loads(raw_manifest)
    if not original or manifest["batch_id"] != original[0]["batch_id"]:
        raise ValueError("增强清单批次与原始输入不符")
    entry = manifest["file"]
    if manifest["derived_schema_version"] != "cd-handoff-1.1" or manifest["next_skill_fields"] != list(FIELDS):
        raise ValueError("增强契约或正文字段顺序不符")
    if entry["path"] != "jobs_enriched.jsonl" or len(data) != entry["bytes"] or sha256(data) != entry["sha256"]:
        raise ValueError("增强文件字节/哈希不符")
    if digest(batch / "manifest.json") != manifest["source_manifest_sha256"]:
        raise ValueError("增强数据引用的原始清单不符")
    jobs = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    by_key = {identity(job): job for job in jobs}
    if len(by_key) != len(jobs) or set(by_key) != {identity(job) for job in original}:
        raise ValueError("增强与原始岗位集合不符")
    for old in original:
        job = by_key[identity(old)]
        if any(job.get(key) != value for key, value in old.items()):
            raise ValueError("增强数据改变了采集原值")
        if any(type(job.get(k)) is not bool for k in ("is_core", "location_conflict", "experience_conflict")):
            raise ValueError("增强标记必须是布尔值")
        if job["additional_requirements_raw"] is not None and not isinstance(job["additional_requirements_raw"], str):
            raise ValueError("附加正文必须为文本或 null")
        if not isinstance(job.get("confirmed_locations"), list) or not all(isinstance(c, str) for c in job["confirmed_locations"]):
            raise ValueError("确认工作地必须为字符串数组")
        if job.get("scope_rule_version") != manifest["scope_version"] or job.get("enrichment_version") != manifest["enrichment_version"]:
            raise ValueError("增强岗位版本与交接清单不符")
    if len(jobs) != manifest["source_postings"] or sum(j["is_core"] for j in jobs) != manifest["core_postings"]:
        raise ValueError("增强岗位数/核心岗位数不符")
    return jobs, {"handoff_revision": resolved, "handoff_manifest_sha256": sha256(raw_manifest), "enriched_jobs_sha256": sha256(data), "handoff": manifest}


def check_dictionary(dictionary):
    names, aliases = set(), set()
    for skill in dictionary["skills"]:
        if skill["name"] in names or not skill["aliases"] or not skill["category"]:
            raise ValueError("词典包含重复技能或空字段")
        names.add(skill["name"])
        for alias in skill["aliases"]:
            if not alias or alias.casefold() in aliases:
                raise ValueError(f"词典别名重复或为空：{alias}")
            aliases.add(alias.casefold())


def body_digest(job):
    return sha256(json.dumps([job.get(field) for field in FIELDS], ensure_ascii=False).encode("utf-8"))


def city_groups(job):
    if job.get("location_conflict"):
        return [CONFLICT]
    return sorted({c.removesuffix("市") for c in (job.get("confirmed_locations") or job.get("locations_raw") or ["未知"])})


def experience_group(job):
    return CONFLICT if job.get("experience_conflict") else (job.get("experience_raw") or "未知")


def raw_record(batch, job):
    ref = next((r for r in job["raw_refs"] if Path(r["path"]).name.startswith("detail_")), job["raw_refs"][0])
    response = load_json(safe_file(batch, ref["path"]))
    if job["source"] == "tencent":
        data = response["Data"]
        if str(data["PostId"]) != job["source_job_id"]:
            raise ValueError("腾讯原始详情身份不符")
    else:
        data = response["data"]
        if "list" in data:
            matches = [d for d in data["list"] if str(d["id"]) == job["source_job_id"]]
            if len(matches) != 1:
                raise ValueError("网易原始响应内岗位不唯一")
            data = matches[0]
        if str(data["id"]) != job["source_job_id"]:
            raise ValueError("网易原始正文身份不符")
    return data, ref


def prepare_netease(jobs, reference):
    # D 的范围建议与 C 已验收的采集技术状态分别保留。
    overrides = reference.get("scope_overrides", {})
    if not set(overrides) <= {j["source_job_id"] for j in jobs}:
        raise ValueError("范围审核引用了输入中不存在的岗位")
    for job in jobs:
        override = reference.get("scope_overrides", {}).get(job["source_job_id"])
        if override and override["evidence"] not in (job.get("description_raw") or ""):
            raise ValueError("范围审核证据不在原文中")
        job.update(additional_requirements_raw=None, is_core=override is None,
                   scope_reason=override["reason"] if override else "大陆开发、测试、算法、数据或运维安全岗位",
                   scope_rule_version="d-netease-core-1.1-proposed", scope_status="pending_C_confirmation")
        known = {c.removesuffix("市") for c in job["locations_raw"] or []}
        title_cities = set(re.findall("北京|上海|广州|深圳|杭州|成都", job["title_raw"] or ""))
        job["location_conflict"] = bool(title_cities and not title_cities.intersection(known))
        # shortcut: 仅把首行明确年限与结构化“不限”的冲突标记，复杂年限表达留在审读记录。
        first = (job["requirements_raw"] or "").splitlines()[0:1]
        year = re.search(r"[1-9]\d*\s*(?:年以?上|年以上|年及以上|年)[^。；\n]{0,16}(?:经验|工作经历)", first[0]) if first else None
        job["experience_conflict"] = bool(job.get("experience_raw") == "不限" and year and not re.search("优先|加分", first[0]))


def audit(batch, jobs):
    rows = []
    text = lambda value: str(value).strip() if value is not None and str(value).strip() else None
    for job in jobs:
        raw, ref = raw_record(batch, job)
        if job["source"] == "tencent":
            mapping = {"title_raw": "RecruitPostName", "description_raw": "Responsibility", "requirements_raw": "Requirement", "additional_requirements_raw": "ImportantItem", "experience_raw": "RequireWorkYearsName", "category_raw": "CategoryName"}
            locations = [p.strip() for p in re.split(r"[、,，/|]+", raw.get("LocationName") or "") if p.strip()] or None
        else:
            mapping = {"title_raw": "name", "description_raw": "description", "requirements_raw": "requirement", "education_raw": "reqEducationName", "experience_raw": "reqWorkYearsName", "category_raw": "firstPostTypeName"}
            locations = [str(p).strip() for p in raw.get("workPlaceNameList") or [] if str(p).strip()] or None
        comparison = {field + "_equal": text(raw.get(key)) == job.get(field) for field, key in mapping.items()}
        comparison["locations_raw_equal"] = locations == job["locations_raw"]
        if not all(comparison.values()):
            raise ValueError(f"原始正文映射不符：{identity(job)} {comparison}")
        job["_raw_ref"] = ref
        job["_raw_fields"] = mapping
        rows.append({**{k: job[k] for k in ("source", "source_job_id", "batch_id", "title_raw", "locations_raw", "experience_raw")},
                     "raw_ref": ref["path"], "raw_sha256": ref["sha256"], "body_sha256": body_digest(job), "body_hash_version": BODY_HASH_VERSION, **comparison,
                     "additional_requirements_present": bool(job.get("additional_requirements_raw")),
                     "location_conflict": job["location_conflict"], "experience_conflict": job["experience_conflict"],
                     "cities_normalized": city_groups(job), "experience_normalized": experience_group(job),
                     "is_core": job["is_core"], "scope_reason": job["scope_reason"],
                     "check_result": "原始字段一致；冲突标记另行分组" if job["location_conflict"] or job["experience_conflict"] else "原始字段一致"})
    return rows


def distribution(jobs, field):
    counter = collections.Counter(job.get(field) or "未知" for job in jobs)
    return [{"name": key, "posting_count": value, "denominator": len(jobs), "share": value / len(jobs) if jobs else None} for key, value in sorted(counter.items(), key=lambda x: (-x[1], x[0]))]


def summarize(jobs, rows, audit_rows, *, city=None, experience=None, category=None):
    scope = [j for j in jobs if j.get("is_core", True) is True and (city is None or city in city_groups(j)) and
             (experience is None or experience == experience_group(j)) and (category is None or category == (j.get("category_raw") or "未知"))]
    ids = {identity(j) for j in scope}
    corpus = [j for j in scope if any((j.get(f) or "").strip() for f in FIELDS)]
    corpus_ids = {identity(j) for j in corpus}
    scoped_rows = [r for r in rows if identity(r) in ids]
    per_job = collections.defaultdict(set)
    for row in scoped_rows:
        if row["eligible_for_metric"] and identity(row) in corpus_ids:
            per_job[identity(row)].add(row["skill_name"])
    skill_jobs = collections.Counter(s for skills in per_job.values() for s in skills)
    pairs = collections.Counter(pair for skills in per_job.values() for pair in itertools.combinations(sorted(skills), 2))
    cities = collections.Counter(c for j in scope for c in city_groups(j))
    raw_cities = collections.Counter(c for j in scope for c in set(j.get("locations_raw") or ["未知"]))
    experiences = collections.Counter(experience_group(j) for j in scope)
    n = len(corpus)
    def counts(counter, denominator):
        return [{"name": k, "posting_count": v, "denominator": denominator, "share": v / denominator if denominator else None} for k, v in sorted(counter.items(), key=lambda x: (-x[1], x[0]))]
    return {"filters": {"is_core": True, "city": city, "experience": experience, "category": category},
            "total_input_posting_count": len(jobs), "core_posting_count_before_filters": sum(j.get("is_core", True) is True for j in jobs),
            "source_posting_count": len(scope), "parseable_body_count": n, "body_coverage": n / len(scope) if scope else None,
            "skill_matched_posting_count": len(per_job), "no_eligible_skill_count": n - len(per_job),
            "eligible_posting_skill_pairs": sum(len(s) for s in per_job.values()), "evidence_count": len(scoped_rows),
            "negative_evidence_count": sum(r["context_polarity"] == "negated" for r in scoped_rows),
            "uncertain_evidence_count": sum(r["requirement_level"] == "不确定" for r in scoped_rows),
            "location_conflict_count": sum(j.get("location_conflict", False) for j in scope),
            "experience_conflict_count": sum(j.get("experience_conflict", False) for j in scope),
            "additional_requirements_posting_count": sum(bool(j.get("additional_requirements_raw")) for j in scope),
            "categories_raw": distribution(scope, "category_raw"), "education_raw": distribution(scope, "education_raw"),
            "experience_raw": distribution(scope, "experience_raw"), "employment_type_raw": distribution(scope, "employment_type_raw"),
            "city_raw": counts(raw_cities, len(scope)), "city_normalized": counts(cities, len(scope)), "experience_normalized": counts(experiences, len(scope)),
            "skills": counts(skill_jobs, n),
            "pairs": [{"skills": list(p), "posting_count": v, "denominator": n, "share": v / n if n else None} for p, v in sorted(pairs.items(), key=lambda x: (-x[1], x[0]))],
            "limitations": ["小批、单来源、partial；不推断市场或趋势", "否定、备选、不确定证据排除，未命中词典的有效正文仍进入分母", "城市冲突单独分组，复核多工作地可以重叠", "网易范围为D建议待C确认；学历/经验保留来源值及冲突", "文件对账通过不等于数据库或Power BI联调通过"]}


def load_inputs(source, batch, handoff_dir=None, handoff_ref=DEFAULT_HANDOFF_REF):
    jobs, manifest = read_batch(batch)
    if manifest["source"] != source or manifest["acceptance_status"] != "accepted":
        raise ValueError("输入来源不符或尚未技术验收")
    provenance = {"jobs_sha256": digest(batch / "jobs.jsonl"), "manifest_sha256": digest(batch / "manifest.json")}
    if source == "tencent":
        jobs, enhanced = read_enriched(batch, jobs, handoff_dir, handoff_ref)
        provenance.update(enhanced)
    return jobs, manifest, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=tuple(BATCHES), default="tencent")
    parser.add_argument("--batch-dir", type=Path)
    parser.add_argument("--handoff-dir", type=Path, help="腾讯 C/D 交接目录；省略时从本地 Git 固定提交读取")
    parser.add_argument("--handoff-ref", default=DEFAULT_HANDOFF_REF)
    parser.add_argument("--output", type=Path)
    for field in ("city", "experience", "category"):
        parser.add_argument("--" + field)
    args = parser.parse_args()
    batch = (args.batch_dir or ROOT / "data" / args.source / BATCHES[args.source]).resolve()
    output = (args.output or ROOT / "reports/analysis" / BATCHES[args.source] / "v1.1").resolve()
    protected = [batch] + ([args.handoff_dir.resolve()] if args.handoff_dir else [])
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in protected):
        raise ValueError("输出目录不能覆盖输入或其父目录")
    jobs, manifest, provenance = load_inputs(args.source, batch, args.handoff_dir, args.handoff_ref)
    reference_all = load_json(REFERENCE_PATH)
    reference = reference_all["sources"][args.source]
    dictionary = load_json(Path(__file__).with_name("dictionary.json"))
    check_dictionary(dictionary)
    if args.source == "netease":
        prepare_netease(jobs, reference)
    audit_rows = audit(batch, jobs)
    rows = [{**row, "body_sha256": body_digest(job), "body_hash_version": BODY_HASH_VERSION,
             "is_core": job["is_core"], "scope_rule_version": job["scope_rule_version"],
             "raw_ref": job["_raw_ref"]["path"], "raw_sha256": job["_raw_ref"]["sha256"],
             "raw_field_name": job["_raw_fields"][row["evidence_field"]]} for job in jobs for row in extract(job, dictionary)]
    for row in rows:
        job = next(j for j in jobs if identity(j) == identity(row))
        body = job[row["evidence_field"]]
        if body[row["evidence_start"]:row["evidence_end"]] != row["evidence"] or body[row["match_start"]:row["match_end"]] != row["matched_text"]:
            raise ValueError("证据位置无法回查")
    from .review import review_payload, score
    payload = review_payload(jobs, rows, dictionary, reference_all, provenance)
    submission = {**{k: payload[k] for k in ("schema", "batch_id", "plan_version", "rule_version", "dictionary_version", "extractor_sha256", "dictionary_sha256")},
                  "reviewer": "D正文核对", "method": "先对照原始响应/增强字段审读并记录标签，冻结参考与规则后对留出集计分；不把提取候选当答案", "reviews": reference["reviews"]}
    validation = score(payload, submission)
    validation.update(body_hash_version=BODY_HASH_VERSION, reference_sha256=digest(REFERENCE_PATH), formal_acceptance="pending_C_reconciliation",
                      detection_unit="岗位×词典技能；非否定候选与指标有效集合分别计分")
    metrics = summarize(jobs, rows, audit_rows, city=args.city, experience=args.experience, category=args.category)
    provenance.update(source=args.source, batch_id=manifest["batch_id"], input_acceptance_status=manifest["acceptance_status"],
                      input_acceptance_scope=manifest.get("acceptance_scope"), coverage_status=manifest["coverage_status"],
                      source_postings=len(jobs), core_postings=sum(j["is_core"] for j in jobs), input_files_checked=len(manifest["files"]),
                      raw_checks_passed=True, body_hash_version=BODY_HASH_VERSION, body_hash_fields=list(FIELDS),
                      body_hash_definition="SHA256(UTF8(json.dumps([job.get(field) for field in body_hash_fields], ensure_ascii=False))); 默认分隔符，无换行归一化，缺失为null",
                      dictionary_version=dictionary["version"], rule_version=RULE_VERSION,
                      scope_version=jobs[0]["scope_rule_version"], scope_status="confirmed_by_C" if args.source == "tencent" else "proposed_pending_C",
                      extraction_code_sha256={name: digest(Path(__file__).with_name(name)) for name in ("extract.py", "run.py", "review.py")},
                      dictionary_sha256=digest(Path(__file__).with_name("dictionary.json")), reference_sha256=digest(REFERENCE_PATH))
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "skill_evidence.jsonl", rows)
    write_csv(output / "body_audit.csv", audit_rows, list(audit_rows[0]))
    samples = [{**row, "split": reference["reviews"][row["source_job_id"]]["split"], "direction": reference["reviews"][row["source_job_id"]]["direction"], "review_note": reference["reviews"][row["source_job_id"]]["note"]} for row in audit_rows if row["source_job_id"] in reference["reviews"]]
    write_csv(output / "cross_review_20.csv", samples, list(samples[0]))
    scope = [{**{k: j[k] for k in ("source", "source_job_id", "batch_id", "title_raw", "is_core", "scope_rule_version", "scope_reason")},
              "scope_status": provenance["scope_status"], "evidence": reference.get("scope_overrides", {}).get(j["source_job_id"], {}).get("evidence", (j.get("description_raw") or "")[:120]),
              "raw_ref": j["_raw_ref"]["path"], "raw_sha256": j["_raw_ref"]["sha256"]} for j in jobs]
    write_csv(output / "scope_review.csv", scope, list(scope[0]))
    issues = []
    for job in jobs:
        for flag, field in (("location_conflict", "title_raw"), ("experience_conflict", "requirements_raw")):
            if job[flag]:
                issues.append({"source": args.source, "source_job_id": job["source_job_id"], "kind": flag, "observed": job.get(field), "raw_ref": job["_raw_ref"]["path"], "treatment": "原值保留；规范化图归冲突待确认"})
        if args.source == "netease" and job["source_job_id"] == "71196":
            issues.append({"source": args.source, "source_job_id": "71196", "kind": "education_conflict", "observed": "education_raw=本科；正文硕士及以上", "raw_ref": job["_raw_ref"]["path"], "treatment": "保留结构化本科与正文证据，待C确认"})
    write_jsonl(output / "data_issues.jsonl", issues)
    write_json(output / "input_provenance.json", provenance)
    write_json(output / "metrics.json", metrics)
    write_json(output / "validation.json", validation)
    write_jsonl(output / "validation_errors.jsonl", validation["errors"])
    labels = [{"source": args.source, "source_job_id": key, "split": item["split"], **label} for key, item in reference["reviews"].items() for label in item["labels"]]
    write_csv(output / "review_labels.csv", labels, ["source", "source_job_id", "split", "skill", "field", "level", "evidence", "evidence_start", "evidence_end"])
    all_core = summarize(jobs, rows, audit_rows)
    core_ids = {identity(j) for j in jobs if j["is_core"]}
    current_pairs = {(identity(row), row["skill_name"]) for row in rows if identity(row) in core_ids and row["eligible_for_metric"]}
    primary_pairs = {(identity(row), row["skill_name"]) for row in rows if identity(row) in core_ids and row["eligible_for_metric"] and row["evidence_field"] != "additional_requirements_raw"}
    reconciliation = {"source": args.source, "batch_id": manifest["batch_id"], "status": "pending_C_integration", "scope_status": provenance["scope_status"],
                      "dictionary_version": dictionary["version"], "rule_version": RULE_VERSION, "body_hash_version": BODY_HASH_VERSION,
                      "input_postings": len(jobs), "core_ids": sorted(j["source_job_id"] for j in jobs if j["is_core"]),
                      "excluded_ids": sorted(j["source_job_id"] for j in jobs if not j["is_core"]),
                      "all_evidence_rows": len(rows), "additional_field_evidence_rows": sum(row["evidence_field"] == "additional_requirements_raw" for row in rows),
                      "core_effective_posting_skill_pairs": len(current_pairs), "pairs_only_in_additional_field": len(current_pairs - primary_pairs),
                      "metrics": all_core}
    if args.source == "tencent":
        baseline_file = ROOT / "reports/analysis" / manifest["batch_id"] / "skill_evidence.jsonl"
        baseline = [json.loads(line) for line in baseline_file.read_text("utf-8").splitlines() if line.strip()]
        baseline_pairs = {(identity(row), row["skill_name"]) for row in baseline if identity(row) in core_ids and row["eligible_for_metric"]}
        reconciliation["previous_same_batch_rules_0_2"] = {"evidence_rows": len(baseline), "core_effective_posting_skill_pairs": len(baseline_pairs),
                                                          "core_matched_postings": len({key for key, skill in baseline_pairs}), "file_sha256": digest(baseline_file), "note": "同批版本对照，不是时间趋势"}
    write_json(output / "reconciliation.json", reconciliation)
    template = (ROOT / "dashboards/pilot_template.html").read_text("utf-8")
    payload = {"metrics": metrics, "provenance": provenance, "validation": validation, "jobs": [{**{k: j.get(k) for k in ("source_job_id", "title_raw", "locations_raw", "category_raw", "experience_raw", "education_raw", "is_core")},
               "city_groups": city_groups(j), "experience_group": experience_group(j), "has_parseable_body": any((j.get(f) or "").strip() for f in FIELDS),
               "evidence": [row for row in rows if identity(row) == identity(j)]} for j in jobs]}
    encoded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    (output / "dashboard.html").write_text(template.replace("__PAYLOAD__", encoded), encoding="utf-8", newline="\n")
    print(json.dumps({"output": str(output), "input_postings": len(jobs), "core_postings": provenance["core_postings"], "denominator": metrics["parseable_body_count"], "dictionary_skills": len(dictionary["skills"]), "evidence_rows": len(rows), "validation": validation["splits"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
