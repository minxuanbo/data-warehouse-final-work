"""生成核对页并对冻结正文参考计分；不把程序候选当作答案。"""
import argparse
import collections
import json
from pathlib import Path

from .extract import FIELDS, RULE_VERSION, extract
from .run import ROOT, DEFAULT_BATCH, body_digest, digest, load_json, read_batch, safe_file, write_json


def review_payload(batch=None):
    batch = batch or ROOT / "data/tencent" / DEFAULT_BATCH
    jobs, manifest = read_batch(batch)
    folder = Path(__file__).parent
    dictionary = load_json(folder / "dictionary.json")
    reference = load_json(folder / "review_reference.json")
    if digest(folder / "extract.py") != reference["extractor_sha256_at_freeze"] or digest(folder / "dictionary.json") != reference["dictionary_sha256_at_freeze"]:
        raise ValueError("冻结规则或词典已改变，不能继续沿用此人工留出计划")
    plan = reference["human_review_plan"]
    assert len(plan["development"]) == len(plan["final"]) == 10
    assert len(set(plan["development"] + plan["final"])) == 20
    assert not set(plan["final"]) & {x["source_job_id"] for x in reference["jobs"] + reference["audit_extra"]}
    by_id = {job["source_job_id"]: job for job in jobs}
    readings = {x["source_job_id"]: x for x in reference["jobs"] + reference["audit_extra"]}
    selected = []
    for split in ("development", "final"):
        for identity in plan[split]:
            job = by_id[identity]
            raw_ref = next(r for r in job["raw_refs"] if Path(r["path"]).name.startswith("detail_"))
            raw = load_json(safe_file(batch, raw_ref["path"]))["Data"]
            selected.append({"source": job["source"], "source_job_id": identity, "batch_id": job["batch_id"],
                "split": split, "body_sha256": body_digest(job), "title": raw["RecruitPostName"],
                "location": raw.get("LocationName"), "description_raw": raw.get("Responsibility") or "",
                "requirements_raw": raw.get("Requirement") or "", "normalized": {k: job[k] for k in ("title_raw", "locations_raw", *FIELDS)},
                "raw_ref": raw_ref["path"], "raw_sha256": raw_ref["sha256"],
                "direction": readings.get(identity, {}).get("direction"),
                "candidates": extract(job, dictionary)})
    return {"schema": "d-human-review-0.2.0", "batch_id": manifest["batch_id"], "plan_version": plan["version"],
            "rule_version": RULE_VERSION, "dictionary_version": dictionary["version"],
            "extractor_sha256": reference["extractor_sha256_at_freeze"], "dictionary_sha256": reference["dictionary_sha256_at_freeze"],
            "skills": dictionary["skills"], "jobs": selected}


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
        for kind, skills in (("false_positive", actual - expected), ("false_negative", expected - actual)):
            errors.extend({"source_job_id": identity, "split": job["split"], "skill_name": s, "kind": kind} for s in sorted(skills))
        for label in known_labels:
            correct = any(r["skill_name"] == label["skill"] and r["evidence_field"] == label["field"] and label["evidence"] in r["evidence"] and
                          ((label["level"] == "否定" and r["context_polarity"] == "negated") or (label["level"] == r["requirement_level"] and r["context_polarity"] != "negated")) for r in job["candidates"])
            result.update(level_total=1, level_correct=int(correct))
            if not correct:
                errors.append({"source_job_id": identity, "split": job["split"], "kind": "level_or_evidence_mismatch", "expected": label})
    results = {}
    for split, counts in totals.items():
        result = {key: counts[key] for key in ("job_count", "tp", "fp", "fn", "level_total", "level_correct")}
        ready = split != "final" or counts["job_count"] == 10
        result.update(status="complete" if counts["job_count"] == 10 else "incomplete",
            precision=counts["tp"] / (counts["tp"] + counts["fp"]) if ready and counts["tp"] + counts["fp"] else None,
            recall=counts["tp"] / (counts["tp"] + counts["fn"]) if ready and counts["tp"] + counts["fn"] else None,
            level_accuracy=counts["level_correct"] / counts["level_total"] if ready and counts["level_total"] else None)
        results[split] = result
    return {"reviewer": submission["reviewer"], "rule_version": payload["rule_version"], "dictionary_version": payload["dictionary_version"],
            "audit_count": len(audits), "audit_records": audits, "splits": results, "incomplete_ids": incomplete, "excluded_final_ids": excluded,
            "errors": errors, "out_of_dictionary_labels": gaps,
            "review_method": submission.get("method", "先读正文录入参考，再对照冻结规则"),
            "limits": "10岗最终小样本、87项冻结词典内按岗位×技能计分，含非否定不确定候选。词典外技术仅单报范围缺口，不称总体召回率；单轮审读未做交叉审阅，不自动等于组内验收。"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "score"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    payload = review_payload()
    if args.mode == "build":
        template = (ROOT / "dashboards/review_template.html").read_text("utf-8")
        encoded = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(template.replace("__PAYLOAD__", encoded), encoding="utf-8", newline="\n")
        print(f"已生成20岗本人核对页：{args.output}")
    else:
        if args.input is None:
            parser.error("score 需要 --input 本人导出的JSON")
        if args.output.resolve() == args.input.resolve():
            raise ValueError("计分输出不能覆盖本人标注")
        result = score(payload, load_json(args.input))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.output, result)
        print(json.dumps({"audit_count": result["audit_count"], "splits": result["splits"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
