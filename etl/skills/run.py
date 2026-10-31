"""python -m etl.skills.run；仅标准库，不采集、不入库。"""
import argparse
import collections
import csv
import hashlib
import itertools
import json
from pathlib import Path
import re
import subprocess

from .extract import FIELDS, RULE_VERSION, extract

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BATCH = "tencent_20261031T093102Z_366ad0a4"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
            # JSONL 保持原文；CSV 用前导单引号防止 Excel 将来源文本当公式。
            writer.writerow({key: "'" + value if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")) else value for key, value in values.items()})


def safe_file(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"输入引用不在批次目录内或文件缺失：{relative}")
    return path


def read_batch(batch):
    manifest = load_json(batch / "manifest.json")
    listed = {}
    for item in manifest["files"]:
        path = safe_file(batch, item["path"])
        if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
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
        if job["batch_id"] != manifest["batch_id"] or job["source"] != manifest["source"]:
            raise ValueError("岗位身份与批次清单不符")
        identity = tuple(job[key] for key in ("source", "source_job_id", "batch_id"))
        if identity in seen:
            raise ValueError(f"重复来源岗位：{identity}")
        seen.add(identity)
        for field in FIELDS + ("title_raw", "education_raw", "experience_raw", "category_raw"):
            if field not in job or (job[field] is not None and not isinstance(job[field], str)):
                raise ValueError(f"{identity} 字段类型不符：{field}")
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


def audit(batch, jobs, reference, completed=None):
    completed = completed or {}
    reviews = {item["source_job_id"]: item for item in reference["jobs"]}
    reviews.update({item["source_job_id"]: item for item in reference.get("audit_extra", [])})
    rows = []
    for job in jobs:
        ref = next((r for r in job["raw_refs"] if Path(r["path"]).name.startswith("detail_")), None)
        if ref is None:
            raise ValueError("腾讯独立核对需要原始详情")
        raw = load_json(safe_file(batch, ref["path"]))["Data"]
        raw_locations = [part.strip() for part in re.split(r"[、,，/|]+", raw.get("LocationName") or "") if part.strip()] or None
        comparisons = {"id": str(raw["PostId"]) == job["source_job_id"],
                       "title": (raw.get("RecruitPostName") or "").strip() == job["title_raw"],
                       "description": (raw.get("Responsibility") or "").strip() == (job["description_raw"] or ""),
                       "requirements": (raw.get("Requirement") or "").strip() == (job["requirements_raw"] or ""),
                       "locations": raw_locations == job["locations_raw"]}
        # shortcut: 本批已知城市用于提示，扩展来源前换为 C 的有版本行政区划映射。
        title_cities = sorted(set(re.findall("北京|上海|广州|深圳|杭州|成都", job["title_raw"] or "")))
        conflict = bool(title_cities and not set(title_cities).intersection(job["locations_raw"] or []))
        mismatch = bool(title_cities and set(title_cities) != set(job["locations_raw"] or []))
        review = reviews.get(job["source_job_id"], {})
        checked = completed.get("reviews", {}).get(job["source_job_id"])
        supplemental = (raw.get("ImportantItem") or "").strip()
        supplement_missing = bool(supplemental and supplemental not in (job["requirements_raw"] or ""))
        rows.append({**{k: job[k] for k in ("source", "source_job_id", "batch_id", "title_raw", "locations_raw")},
                     "raw_ref": ref["path"], "raw_sha256": ref["sha256"], **{k + "_equal": v for k, v in comparisons.items()},
                     "title_exact_equal": raw.get("RecruitPostName") == job["title_raw"],
                     "description_length": len(job["description_raw"] or ""), "requirements_length": len(job["requirements_raw"] or ""),
                     "title_cities": title_cities, "location_conflict": conflict, "title_location_sets_differ": mismatch,
                     "supplemental_requirements_present": bool(supplemental), "supplemental_requirements_not_in_jobs": supplement_missing,
                     "supplemental_requirements_excerpt": supplemental,
                     "check_result": "字段不一致" if not all(comparisons.values()) else "主字段一致" + ("；城市待核" if conflict else "") + ("；附加要求待纳入" if supplement_missing else ""),
                     "semantic_review": "本轮正文审读完成" if checked else ("历史正文参考" if review else "自动字段对照"),
                     "direction": completed.get("directions", {}).get(job["source_job_id"], review.get("direction")),
                     "review_note": checked["note"] if checked else review.get("audit_note"),
                     "review_status": "reviewed" if checked else "field_checked"})
    return rows


def evaluate(jobs, rows, reference, dictionary):
    by_id = {job["source_job_id"]: job for job in jobs}
    predicted = collections.defaultdict(set)
    for row in rows:
        if row["context_polarity"] != "negated":
            predicted[row["source_job_id"]].add(row["skill_name"])
    known = {skill["name"] for skill in dictionary["skills"]}
    splits = {"dev": set(), "regression": set()}
    for item in reference["jobs"]:
        if item["source_job_id"] in set.union(*splits.values()):
            raise ValueError("开发/回归集重复")
        splits[item["split"]].add(item["source_job_id"])
    results, errors = {}, []
    for split, identities in splits.items():
        tp = fp = fn = level_correct = level_total = 0
        for item in (x for x in reference["jobs"] if x["split"] == split):
            identity = item["source_job_id"]
            if identity not in by_id or item["body_sha256"] != body_digest(by_id[identity]):
                raise ValueError(f"标注正文版本不符：{identity}")
            expected = set(item["expected_skills"])
            if not expected <= known:
                raise ValueError("标注技能不在冻结词典中")
            actual = predicted[identity]
            tp += len(actual & expected)
            fp += len(actual - expected)
            fn += len(expected - actual)
            for kind, values in (("false_positive", actual - expected), ("false_negative", expected - actual)):
                for skill in sorted(values):
                    errors.append({"split": split, "source_job_id": identity, "skill_name": skill, "kind": kind})
            for check in item.get("level_checks", []):
                level_total += 1
                match = any(r["source_job_id"] == identity and r["skill_name"] == check["skill_name"] and r["evidence_field"] == check["field"] and check["anchor"] in r["evidence"] and r["requirement_level"] == check["level"] and r["context_polarity"] == check.get("polarity", "positive") for r in rows)
                level_correct += match
                if not match:
                    errors.append({"split": split, "source_job_id": identity, "skill_name": check["skill_name"], "kind": "level_mismatch", "expected": check})
        results[split] = {"job_count": len(identities), "tp": tp, "fp": fp, "fn": fn,
                          "precision": tp / (tp + fp) if tp + fp else None,
                          "recall": tp / (tp + fn) if tp + fn else None,
                          "level_checks": level_total, "level_correct": level_correct,
                          "level_accuracy": level_correct / level_total if level_total else None}
    return {"reference_type": "历史正文参考；开发与回归检查",
            "detection_unit": "(source_job_id, skill_name), dictionary scope, non-negated candidate including uncertain",
            "rule_version": RULE_VERSION, "dictionary_version": dictionary["version"], "splits": results,
            "formal_acceptance": "pending_group_review"}, errors


def body_digest(job):
    return hashlib.sha256(json.dumps([job.get(field) for field in FIELDS], ensure_ascii=False).encode("utf-8")).hexdigest()


def distribution(jobs, field):
    counter = collections.Counter(job.get(field) or "未知" for job in jobs)
    return [{"name": key, "posting_count": value, "denominator": len(jobs), "share": value / len(jobs) if jobs else None} for key, value in counter.most_common()]


def summarize(jobs, rows, audit_rows):
    corpus = [job for job in jobs if any((job.get(field) or "").strip() for field in FIELDS)]
    n = len(corpus)
    identity = lambda j: (j["source"], j["source_job_id"], j["batch_id"])
    skill_jobs = collections.defaultdict(set)
    per_job = collections.defaultdict(set)
    for row in rows:
        if row["eligible_for_metric"]:
            skill_jobs[row["skill_name"]].add(identity(row))
            per_job[identity(row)].add(row["skill_name"])
    pairs = collections.Counter(pair for skills in per_job.values() for pair in itertools.combinations(sorted(skills), 2))
    cities = collections.Counter(city for job in jobs for city in set(job["locations_raw"] or ["未知"]))
    return {"source_posting_count": len(jobs), "parseable_body_count": n,
            "body_coverage": n / len(jobs) if jobs else None,
            "skill_matched_posting_count": len(per_job), "no_eligible_skill_count": n - len(per_job),
            "evidence_count": len(rows), "negative_evidence_count": sum(r["context_polarity"] == "negated" for r in rows),
            "uncertain_evidence_count": sum(r["requirement_level"] == "不确定" for r in rows),
            "location_conflict_count": sum(r["location_conflict"] for r in audit_rows),
            "title_location_sets_differ_count": sum(r["title_location_sets_differ"] for r in audit_rows),
            "title_trim_only_count": sum(not r["title_exact_equal"] and r["title_equal"] for r in audit_rows),
            "supplemental_requirements_not_in_jobs_count": sum(r.get("supplemental_requirements_not_in_jobs", False) for r in audit_rows),
            "categories_raw": distribution(jobs, "category_raw"), "education_raw": distribution(jobs, "education_raw"),
            "experience_raw": distribution(jobs, "experience_raw"), "employment_type_raw": distribution(jobs, "employment_type_raw"),
            "city_raw": [{"name": c, "posting_count": v, "denominator": len(jobs)} for c, v in cities.most_common()],
            "skills": [{"name": s, "posting_count": len(ids), "denominator": n, "share": len(ids) / n if n else None} for s, ids in sorted(skill_jobs.items(), key=lambda x: (-len(x[1]), x[0]))],
            "pairs": [{"skills": list(p), "posting_count": v, "denominator": n, "share": v / n if n else None} for p, v in pairs.most_common()],
            "limitations": ["单来源、单批、截取样本；不是全国市场", "保留来源原值；岗位主类别/学历正文规范化待C/D审核", "否定/不确定不进入技能占比；备选技能组默认不确定", "城市冲突未裁定；城市卡按原地点字段", "正文评分仅覆盖Responsibility/Requirement，不含ImportantItem补充要求", "单轮正文参考，未做交叉审阅或真实数仓/Power BI联调验收"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-dir", type=Path, default=ROOT / "data" / "tencent" / DEFAULT_BATCH)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    batch = args.batch_dir.resolve()
    jobs, manifest = read_batch(batch)
    if manifest["source"] != "tencent":
        raise ValueError("当前原文核对仅适配腾讯；新增来源须先补适配和标注")
    output = (args.output or ROOT / "reports" / "analysis" / manifest["batch_id"]).resolve()
    if output.is_relative_to(batch) or batch.is_relative_to(output):
        raise ValueError("输出目录不能覆盖输入批次或其父目录")
    dictionary = load_json(Path(__file__).with_name("dictionary.json"))
    reference = load_json(Path(__file__).with_name("review_reference.json"))
    check_dictionary(dictionary)
    if digest(Path(__file__).with_name("dictionary.json")) != reference["dictionary_sha256_at_freeze"] or digest(Path(__file__).with_name("extract.py")) != reference["extractor_sha256_at_freeze"]:
        raise ValueError("冻结词典/提取规则已变动；必须升版本并重新安排未看过的留出集")
    rows = [{**row, "body_sha256": body_digest(job)} for job in jobs for row in extract(job, dictionary)]
    from .review import review_payload, score
    completed_path = Path(__file__).with_name("reviewed_samples.json")
    completed = load_json(completed_path)
    audit_rows = audit(batch, jobs, reference, completed)
    regression, _ = evaluate(jobs, rows, reference, dictionary)
    validation = score(review_payload(batch), completed)
    validation.update(reference_type="原始详情正文审读参考", detection_unit="岗位×冻结词典技能；含非否定不确定候选", regression_checks=regression["splits"],
                      reference_sha256=digest(completed_path), formal_acceptance="pending_group_review")
    errors = validation["errors"]
    metrics = summarize(jobs, rows, audit_rows)
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        revision = None
    provenance = {"batch_id": manifest["batch_id"], "source": manifest["source"], "repository_revision_at_run": revision,
                  "jobs_sha256": digest(batch / "jobs.jsonl"), "manifest_sha256": digest(batch / "manifest.json"),
                  "dictionary_sha256": digest(Path(__file__).with_name("dictionary.json")), "reference_sha256": digest(Path(__file__).with_name("review_reference.json")),
                  "extractor_sha256": digest(Path(__file__).with_name("extract.py")), "runner_sha256": digest(Path(__file__)),
                  "reviewed_samples_sha256": digest(completed_path), "review_scorer_sha256": digest(Path(__file__).with_name("review.py")),
                  "dictionary_version": dictionary["version"], "rule_version": RULE_VERSION,
                  "input_acceptance_status": manifest["acceptance_status"], "input_acceptance_scope": manifest.get("acceptance_scope"),
                  "coverage_status": manifest["coverage_status"], "input_files_checked": len(manifest["files"]),
                  "raw_checks_passed": all(all(row[k + "_equal"] for k in ("id", "title", "description", "requirements", "locations")) for row in audit_rows)}
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / "skill_evidence.jsonl", rows)
    write_csv(output / "skill_evidence.csv", rows, list(rows[0]) if rows else ["source", "source_job_id", "batch_id", "skill_name"])
    write_csv(output / "body_audit.csv", audit_rows, list(audit_rows[0]) if audit_rows else ["source_job_id"])
    reviewed = [row for row in audit_rows if row["direction"]]
    write_csv(output / "independent_review.csv", reviewed, list(audit_rows[0]) if audit_rows else ["source_job_id"])
    sampled = [row for row in audit_rows if row["review_status"] == "reviewed"]
    write_csv(output / "sample_review_20.csv", sampled, list(audit_rows[0]))
    supplemental_rows = [row for row in audit_rows if row["supplemental_requirements_not_in_jobs"]]
    write_csv(output / "supplemental_requirements.csv", supplemental_rows, ["source", "source_job_id", "batch_id", "title_raw", "raw_ref", "raw_sha256", "supplemental_requirements_excerpt"])
    labels = [{"source": manifest["source"], "source_job_id": identity, "batch_id": manifest["batch_id"], "split": item["split"], **label} for identity, item in completed["reviews"].items() for label in item["labels"]]
    write_csv(output / "review_labels.csv", labels, ["source", "source_job_id", "batch_id", "split", "skill", "field", "level", "evidence"])
    write_json(output / "input_provenance.json", provenance)
    write_json(output / "metrics.json", metrics)
    write_json(output / "validation.json", validation)
    write_jsonl(output / "validation_errors.jsonl", errors)
    template = (ROOT / "dashboards" / "pilot_template.html").read_text("utf-8")
    payload = {"metrics": metrics, "provenance": provenance, "validation": validation, "jobs": [{**{k: j[k] for k in ("source_job_id", "title_raw", "locations_raw", "category_raw", "experience_raw", "education_raw")}, "has_parseable_body": any((j.get(field) or "").strip() for field in FIELDS), "evidence": [r for r in rows if r["source_job_id"] == j["source_job_id"]]} for j in jobs]}
    encoded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    (output / "dashboard.html").write_text(template.replace("__PAYLOAD__", encoded), encoding="utf-8", newline="\n")
    print(json.dumps({"output": str(output), "postings": len(jobs), "dictionary_skills": len(dictionary["skills"]), "evidence_rows": len(rows), "validation": validation["splits"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
