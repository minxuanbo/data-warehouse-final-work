"""对冻结正文参考计分；不把程序候选当作答案。"""
import argparse
import collections
import json
from pathlib import Path

from .extract import FIELDS, RULE_VERSION, extract
from .run import ROOT, body_digest, digest, load_json, write_json


def review_payload(jobs, rows, dictionary, reference_all, provenance):
    source = jobs[0]["source"]
    reference = reference_all["sources"][source]
    folder = Path(__file__).parent
    if digest(folder / "extract.py") != reference_all["extractor_sha256_at_freeze"] or digest(folder / "dictionary.json") != reference_all["dictionary_sha256_at_freeze"]:
        raise ValueError("冻结规则或词典已改变，需重新冻结验证计划")
    if provenance["jobs_sha256"] != reference["jobs_sha256"] or provenance.get("enriched_jobs_sha256") != reference.get("enriched_jobs_sha256"):
        raise ValueError("验证计划的输入正文版本不符")
    reviews = reference["reviews"]
    development = {k for k, v in reviews.items() if v["split"] == "development"}
    final = {k for k, v in reviews.items() if v["split"] == "final"}
    if len(development) != 10 or len(final) != 10 or development & final or final & set(reference.get("historical_ids", [])):
        raise ValueError("开发/最终样本数量、历史样本隔离不符")
    selected = []
    for job in jobs:
        key = job["source_job_id"]
        if key in reviews:
            selected.append({**job, "split": reviews[key]["split"], "normalized": job, "body_sha256": body_digest(job),
                             "title": job["title_raw"], "location": job["locations_raw"], "raw_ref": job["_raw_ref"]["path"], "raw_sha256": job["_raw_ref"]["sha256"],
                             "candidates": [r for r in rows if r["source_job_id"] == key and r["source"] == source]})
    return {"schema": "d-review-1.1", "batch_id": jobs[0]["batch_id"], "plan_version": reference_all["version"],
            "rule_version": RULE_VERSION, "dictionary_version": dictionary["version"], "extractor_sha256": reference_all["extractor_sha256_at_freeze"],
            "dictionary_sha256": reference_all["dictionary_sha256_at_freeze"], "skills": dictionary["skills"], "jobs": selected}


def score(payload, submission):
    for key in ("schema", "batch_id", "plan_version", "rule_version", "dictionary_version", "extractor_sha256", "dictionary_sha256"):
        if submission.get(key) != payload[key]:
            raise ValueError(f"人工核对版本不符：{key}")
    if not isinstance(submission.get("reviewer"), str) or not submission["reviewer"].strip():
        raise ValueError("请填写核对标识")
    expected_ids = {j["source_job_id"] for j in payload["jobs"]}
    annotations = submission.get("reviews")
    if not isinstance(annotations, dict) or set(annotations) != expected_ids:
        raise ValueError("核对岗位集合与20岗计划不符")
    aliases = {alias.casefold(): skill["name"] for skill in payload["skills"] for alias in [skill["name"], *skill["aliases"]]}
    totals = {split: collections.Counter() for split in ("development", "final")}
    errors, gaps, audits, incomplete, excluded = [], [], [], [], []
    for job in payload["jobs"]:
        identity = job["source_job_id"]
        item = annotations[identity]
        if item.get("body_sha256") != job["body_sha256"] or item.get("split") != job["split"]:
            raise ValueError(f"核对正文/分组不符：{identity}")
        ready = item.get("locked") is True and item.get("body_check") in {"pass", "issue", "uncertain"} and item.get("city_check") in {"same", "different", "uncertain"}
        if not ready:
            incomplete.append(identity)
            continue
        if not isinstance(item.get("note"), str):
            raise ValueError("核对备注必须为文本")
        audits.append({"source": job["source"], "source_job_id": identity, "batch_id": job["batch_id"],
                       "title": job["title"], "location": job["location"], "raw_ref": job["raw_ref"], "raw_sha256": job["raw_sha256"],
                       "body_check": item["body_check"], "city_check": item["city_check"], "note": item["note"], "reviewer": submission["reviewer"]})
        labels = item.get("labels")
        if not isinstance(labels, list) or (not labels and item.get("no_skills") is not True):
            raise ValueError(f"必须逐项标注技能，或明确勾选未发现命名技术：{identity}")
        if labels and item.get("no_skills"):
            raise ValueError("技能标注与未发现技能不能同时成立")
        known_labels = []
        for label in labels:
            if not isinstance(label.get("skill"), str) or not label["skill"].strip() or label.get("field") not in FIELDS or label.get("level") not in {"必需", "优先", "提及", "不确定", "否定"}:
                raise ValueError(f"技能名称/字段/强度无效：{identity}")
            evidence = label.get("evidence")
            if not isinstance(evidence, str) or not evidence.strip() or evidence not in job["normalized"][label["field"]]:
                raise ValueError(f"证据必须从原文字段逐字复制：{identity}")
            name = aliases.get(label["skill"].strip().casefold())
            if name is None:
                gaps.append({"source_job_id": identity, **label})
            else:
                known_labels.append({**label, "skill": name})
        if job["split"] == "final" and (item.get("unblinded_edit") is not False or item.get("independent_confirmation") is not True):
            excluded.append(identity)
            continue
        result = totals[job["split"]]
        result["job_count"] += 1
        expected = {x["skill"] for x in known_labels if x["level"] != "否定"}
        actual = {x["skill_name"] for x in job["candidates"] if x["context_polarity"] != "negated"}
        result.update(tp=len(expected & actual), fp=len(actual - expected), fn=len(expected - actual))
        expected_metric = {x["skill"] for x in known_labels if x["level"] in {"必需", "优先", "提及"}}
        actual_metric = {x["skill_name"] for x in job["candidates"] if x["eligible_for_metric"]}
        result.update(metric_tp=len(expected_metric & actual_metric), metric_fp=len(actual_metric - expected_metric), metric_fn=len(expected_metric - actual_metric))
        for kind, skills in (("metric_false_positive", actual_metric - expected_metric), ("metric_false_negative", expected_metric - actual_metric)):
            errors.extend({"source_job_id": identity, "split": job["split"], "skill_name": value, "kind": kind} for value in sorted(skills))
        for kind, skills in (("false_positive", actual - expected), ("false_negative", expected - actual)):
            errors.extend({"source_job_id": identity, "split": job["split"], "skill_name": s, "kind": kind} for s in sorted(skills))
        for label in known_labels:
            correct = any(r["skill_name"] == label["skill"] and r["evidence_field"] == label["field"] and label["evidence"] in r["evidence"] and ("evidence_start" not in label or r["evidence_start"] <= label["evidence_start"] < label["evidence_end"] <= r["evidence_end"]) and
                          ((label["level"] == "否定" and r["context_polarity"] == "negated") or (label["level"] == r["requirement_level"] and r["context_polarity"] != "negated")) for r in job["candidates"])
            result.update(level_total=1, level_correct=int(correct))
            if not correct:
                errors.append({"source_job_id": identity, "split": job["split"], "kind": "level_or_evidence_mismatch", "expected": label})
    results = {}
    for split, counts in totals.items():
        result = {key: counts[key] for key in ("job_count", "tp", "fp", "fn", "metric_tp", "metric_fp", "metric_fn", "level_total", "level_correct")}
        ready = split != "final" or counts["job_count"] == 10
        result.update(status="complete" if counts["job_count"] == 10 else "incomplete",
            precision=counts["tp"] / (counts["tp"] + counts["fp"]) if ready and counts["tp"] + counts["fp"] else None,
            recall=counts["tp"] / (counts["tp"] + counts["fn"]) if ready and counts["tp"] + counts["fn"] else None,
            level_accuracy=counts["level_correct"] / counts["level_total"] if ready and counts["level_total"] else None)
        for metric, denominator in (("metric_precision", counts["metric_tp"] + counts["metric_fp"]), ("metric_recall", counts["metric_tp"] + counts["metric_fn"])):
            result[metric] = counts["metric_tp"] / denominator if ready and denominator else None
        results[split] = result
    return {"reviewer": submission["reviewer"], "rule_version": payload["rule_version"], "dictionary_version": payload["dictionary_version"],
            "audit_count": len(audits), "audit_records": audits, "splits": results, "incomplete_ids": incomplete, "excluded_final_ids": excluded,
            "errors": errors, "out_of_dictionary_labels": gaps,
            "review_method": submission.get("method", "先读正文录入参考，再对照冻结规则"),
            "limits": "每来源10岗留出小样本；词典内非否定候选按岗位×技能计分，含不确定候选。词典外技术单报范围缺口。交叉核对指原始响应、交接字段与证据位置的对照，组内验收仍待C对账。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("score",))
    parser.add_argument("--source", choices=("tencent", "netease"), default="tencent")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    from .run import BATCHES, REFERENCE_PATH, audit, load_inputs, prepare_netease
    batch = ROOT / "data" / args.source / BATCHES[args.source]
    jobs, manifest, provenance = load_inputs(args.source, batch)
    reference_all = load_json(REFERENCE_PATH)
    reference = reference_all["sources"][args.source]
    if args.source == "netease":
        prepare_netease(jobs, reference)
    audit(batch, jobs)
    dictionary = load_json(Path(__file__).with_name("dictionary.json"))
    rows = [row for job in jobs for row in extract(job, dictionary)]
    payload = review_payload(jobs, rows, dictionary, reference_all, provenance)
    submission = {**{k: payload[k] for k in ("schema", "batch_id", "plan_version", "rule_version", "dictionary_version", "extractor_sha256", "dictionary_sha256")},
                  "reviewer": "D正文核对", "reviews": reference["reviews"]}
    if args.output.resolve().is_relative_to(batch.resolve()) or args.output.resolve() == REFERENCE_PATH.resolve():
        raise ValueError("计分输出不能覆盖输入")
    result = score(payload, submission)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, result)
    print(json.dumps({"audit_count": result["audit_count"], "splits": result["splits"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
