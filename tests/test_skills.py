import copy
import json
from pathlib import Path
import unittest

from etl.skills.extract import extract
from etl.skills.run import check_dictionary, safe_file, summarize
from etl.skills.review import score


DICTIONARY = json.loads((Path(__file__).resolve().parents[1] / "etl/skills/dictionary.json").read_text("utf-8"))


def job(requirements=None, description=None, identity="1"):
    return {"source": "test", "source_job_id": identity, "batch_id": "test_batch", "requirements_raw": requirements,
            "description_raw": description, "locations_raw": ["深圳", "上海"], "category_raw": None,
            "education_raw": None, "experience_raw": None, "employment_type_raw": None}


class ExtractionTests(unittest.TestCase):
    def test_frozen_dictionary_valid(self):
        check_dictionary(DICTIONARY)

    def test_boundaries_and_longest_alias(self):
        rows = extract(job("熟悉C++、C#、JavaScript、Objective-C、React Native、TensorRT-LLM、NoSQL、Google"), DICTIONARY)
        self.assertEqual({r["skill_name"] for r in rows}, {"C++", "C#", "JavaScript", "Objective-C", "React Native", "TensorRT-LLM"})

    def test_negation_and_priority_have_local_scope(self):
        rows = extract(job("不要求Java经验，但熟悉Python者优先；熟悉SQL，包括但不限于SQL优化。"), DICTIONARY)
        self.assertTrue(all(not r["eligible_for_metric"] for r in rows if r["skill_name"] == "Java"))
        self.assertTrue(all(r["requirement_level"] == "优先" for r in rows if r["skill_name"] == "Python"))
        self.assertTrue(all(r["context_polarity"] == "positive" for r in rows if r["skill_name"] == "SQL"))

    def test_priority_does_not_leak_across_new_predicate(self):
        rows = extract(job("熟练掌握Python，熟悉PyTorch者优先。"), DICTIONARY)
        self.assertEqual([(r["skill_name"], r["requirement_level"]) for r in rows], [("Python", "必需"), ("PyTorch", "优先")])

    def test_alternative_is_not_each_mandatory(self):
        rows = extract(job("熟悉Python/Java中至少一种语言。"), DICTIONARY)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["requirement_level"] == "不确定" and not r["eligible_for_metric"] for r in rows))

    def test_description_is_mention_and_offsets_roundtrip(self):
        record = job(None, "职责：\n负责Python与SQL研发；优化Spark。")
        rows = extract(record, DICTIONARY)
        self.assertEqual(len(rows), 3)
        for row in rows:
            body = record[row["evidence_field"]]
            self.assertEqual(row["requirement_level"], "提及")
            self.assertEqual(body[row["match_start"]:row["match_end"]], row["matched_text"])
            self.assertEqual(body[row["evidence_start"]:row["evidence_end"]], row["evidence"])

    def test_empty_body(self):
        self.assertEqual(extract(job(), DICTIONARY), [])

    def test_react_reasoning_and_consumer_side_are_not_libraries(self):
        rows = extract(job("熟悉ReAct、React、react、REACT；支持C端应用；熟悉C语言。"), DICTIONARY)
        self.assertEqual([r["matched_text"] for r in rows], ["React", "react", "REACT", "C"])

    def test_plus_separated_alternatives_keep_all_named_skills(self):
        rows = extract(job("精通至少两种技术栈组合，如TypeScript+Node.js+Python+React+Go。"), DICTIONARY)
        self.assertEqual({r["skill_name"] for r in rows}, {"TypeScript", "Node.js", "Python", "React", "Go"})
        self.assertTrue(all(r["context_polarity"] == "alternative" for r in rows))

    def test_generic_script_alternative_does_not_change_cpp(self):
        for text in ("熟练掌握C++，至少掌握一门脚本语言", "精通C++和至少一种脚本语言", "精通C++和至少一种数据处理脚本语言"):
            with self.subTest(text=text):
                row = extract(job(text), DICTIONARY)[0]
                self.assertEqual((row["skill_name"], row["requirement_level"]), ("C++", "必需"))

    def test_additional_field_offsets_hash_and_priority_heading(self):
        from etl.skills.extract import BODY_HASH_VERSION
        from etl.skills.run import body_digest
        record = job("熟悉Python")
        before = body_digest(record)
        record["additional_requirements_raw"] = "😀加分项\r\n熟悉SQL者优先；无需Java经验"
        rows = [r for r in extract(record, DICTIONARY) if r["evidence_field"] == "additional_requirements_raw"]
        self.assertNotEqual(before, body_digest(record))
        self.assertEqual(BODY_HASH_VERSION, "skills-body-1.1")
        self.assertEqual(rows[0]["requirement_level"], "优先")
        self.assertEqual(rows[1]["context_polarity"], "negated")
        for row in rows:
            self.assertEqual(record[row["evidence_field"]][row["match_start"]:row["match_end"]], row["matched_text"])

    def test_years_are_not_skill_alternatives(self):
        rows = extract(job("至少2年UE4开发经验；精通C++和至少一种脚本语言"), DICTIONARY)
        self.assertTrue(all(r["requirement_level"] == "必需" for r in rows))

    def test_chinese_alternative_and_new_predicate(self):
        rows = extract(job("精通MLIR、Triton、tilelang或其他框架；能熟练使用UE，有Lua脚本经验者优先"), DICTIONARY)
        self.assertTrue(all(r["context_polarity"] == "alternative" for r in rows if r["skill_name"] in {"MLIR", "Triton", "tilelang"}))
        self.assertEqual(next(r for r in rows if r["skill_name"] == "Unreal Engine")["requirement_level"], "必需")

    def test_at_least_with_verb_and_spaced_priority_predicate(self):
        rows = extract(job("至少熟悉一门编程语言（Python / Go / Node.js）；熟悉Linux，有 Gin、Laravel 或同类框架的项目经验"), DICTIONARY)
        self.assertTrue(all(r["context_polarity"] == "alternative" for r in rows if r["skill_name"] in {"Python", "Go", "Node.js"}))
        self.assertEqual(next(r for r in rows if r["skill_name"] == "Linux")["requirement_level"], "必需")

    def test_priority_section_applies_until_required_heading(self):
        rows = extract(job("加分项\n有Python经验\n熟悉SQL\n必备条件\n掌握Java"), DICTIONARY)
        self.assertEqual([r["requirement_level"] for r in rows], ["优先", "优先", "必需"])

    def test_core_and_conflict_filters_recompute_denominator(self):
        a, b, c = job("熟悉Python"), job("未列命名工具", identity="2"), job("熟悉Java", identity="3")
        a.update(is_core=True, location_conflict=True, experience_conflict=True)
        b.update(is_core=True, confirmed_locations=["北京", "深圳"])
        c.update(is_core=False)
        rows = [row for j in (a, b, c) for row in extract(j, DICTIONARY)]
        metrics = summarize([a, b, c], rows, [])
        self.assertEqual((metrics["parseable_body_count"], metrics["skill_matched_posting_count"]), (2, 1))
        self.assertEqual(metrics["skills"][0]["share"], 0.5)
        self.assertEqual(summarize([a, b, c], rows, [], city="深圳")["parseable_body_count"], 1)
        selected = summarize([a, b, c], rows, [], experience="冲突待确认")
        self.assertEqual(selected["skills"][0]["share"], 1)
        self.assertEqual(summarize([a, b, c], rows, [], city="不存在")["skills"], [])

    def test_raw_path_cannot_escape_batch(self):
        with self.assertRaises(ValueError):
            safe_file(Path(__file__).parent, "../etl/skills/dictionary.json")

    def test_dictionary_duplicate_is_rejected(self):
        changed = copy.deepcopy(DICTIONARY)
        changed["skills"].append(changed["skills"][0])
        with self.assertRaises(ValueError):
            check_dictionary(changed)

    def test_denominator_keeps_no_match_and_deduplicates_evidence(self):
        records = [job("熟悉Python；精通Python与SQL"), job("具备自动化测试能力", identity="2")]
        rows = [r for record in records for r in extract(record, DICTIONARY)]
        metrics = summarize(records, rows, [])
        self.assertEqual(metrics["parseable_body_count"], 2)
        self.assertEqual(metrics["no_eligible_skill_count"], 1)
        self.assertEqual(metrics["skills"][0]["posting_count"], 1)
        self.assertEqual(metrics["skills"][0]["share"], 0.5)
        self.assertEqual(metrics["pairs"][0]["posting_count"], 1)
        self.assertEqual(sum(x["posting_count"] for x in metrics["city_raw"]), 4)

    def test_empty_denominator_is_null(self):
        metrics = summarize([], [], [])
        self.assertIsNone(metrics["body_coverage"])
        self.assertEqual(metrics["skills"], [])


class EnrichedInputTests(unittest.TestCase):
    def test_enriched_bytes_and_identity_are_verified(self):
        import hashlib
        import tempfile
        from etl.skills.extract import FIELDS
        from etl.skills.run import read_enriched, write_json
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            batch = root / "raw"
            handoff = root / "handoff"
            batch.mkdir()
            handoff.mkdir()
            (batch / "manifest.json").write_bytes(b"source-manifest")
            original = job("熟悉Python")
            enriched = {**original, "additional_requirements_raw": "熟悉SQL", "is_core": True, "location_conflict": False,
                        "experience_conflict": False, "confirmed_locations": ["深圳"], "scope_rule_version": "scope-test", "enrichment_version": "enrich-test"}
            body = json.dumps(enriched, ensure_ascii=False).encode("utf-8")
            (handoff / "jobs_enriched.jsonl").write_bytes(body)
            manifest = {"derived_schema_version": "cd-handoff-1.1", "batch_id": "test_batch", "next_skill_fields": list(FIELDS), "scope_version": "scope-test", "enrichment_version": "enrich-test",
                        "source_manifest_sha256": hashlib.sha256(b"source-manifest").hexdigest(), "source_postings": 1, "core_postings": 1,
                        "file": {"path": "jobs_enriched.jsonl", "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}}
            write_json(handoff / "manifest.json", manifest)
            self.assertEqual(read_enriched(batch, [original], handoff)[0][0]["additional_requirements_raw"], "熟悉SQL")
            (handoff / "jobs_enriched.jsonl").write_bytes(body + b" ")
            with self.assertRaises(ValueError):
                read_enriched(batch, [original], handoff)
            enriched["source_job_id"] = "other"
            body = json.dumps(enriched, ensure_ascii=False).encode("utf-8")
            (handoff / "jobs_enriched.jsonl").write_bytes(body)
            manifest["file"].update(bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
            write_json(handoff / "manifest.json", manifest)
            with self.assertRaises(ValueError):
                read_enriched(batch, [original], handoff)


class ReviewTests(unittest.TestCase):
    def fixture(self):
        payload = {key: "test" for key in ("schema", "batch_id", "plan_version", "rule_version", "dictionary_version", "extractor_sha256", "dictionary_sha256")}
        payload["skills"] = [{"name": "Python", "aliases": ["Python"]}]
        payload["jobs"] = []
        submission = {**payload, "reviewer": "合成测试用例", "reviews": {}}
        for index in range(20):
            identity = str(index)
            split = "development" if index < 10 else "final"
            record = job("熟悉Python", identity=identity)
            payload["jobs"].append({**record, "title": "合成测试", "location": "深圳", "raw_ref": "test", "raw_sha256": "test", "split": split,
                                    "body_sha256": "test", "normalized": record, "candidates": extract(record, DICTIONARY)})
            submission["reviews"][identity] = {"split": split, "body_sha256": "test", "locked": True, "body_check": "pass", "city_check": "same", "note": "",
                "no_skills": False, "unblinded_edit": False, "independent_confirmation": True,
                "labels": [{"skill": "python", "field": "requirements_raw", "level": "必需", "evidence": "熟悉Python"}]}
        return payload, submission

    def test_review_score_requires_complete_final_and_valid_evidence(self):
        payload, submission = self.fixture()
        result = score(payload, submission)
        self.assertEqual((result["audit_count"], result["splits"]["final"]["tp"], result["splits"]["final"]["recall"]), (20, 10, 1.0))
        submission["reviews"]["10"]["locked"] = False
        self.assertIsNone(score(payload, submission)["splits"]["final"]["precision"])
        submission["reviews"]["0"]["labels"][0]["evidence"] = "伪造证据"
        with self.assertRaises(ValueError):
            score(payload, submission)

    def test_unblinded_edit_is_excluded_and_unknown_skills_are_separate(self):
        payload, submission = self.fixture()
        submission["reviews"]["10"]["unblinded_edit"] = True
        result = score(payload, submission)
        self.assertEqual(result["excluded_final_ids"], ["10"])
        self.assertIsNone(result["splits"]["final"]["recall"])
        submission["reviews"]["0"]["labels"][0]["skill"] = "词典外技术"
        self.assertEqual(len(score(payload, submission)["out_of_dictionary_labels"]), 1)


if __name__ == "__main__":
    unittest.main()
