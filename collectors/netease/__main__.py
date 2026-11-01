"""网易社会招聘小批采集入口：从仓库根目录运行。

python -m collectors.netease --batch-dir data/netease/<batch_id> --target 100 --max-pages 100
"""
import argparse
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

from .batch import Batch, sha256_file
from .client import Client, StopCollection
from .mapping import build_job, classify, compare_detail, text_issues, validate_job
from .report import verify_manifest, write_readme
from . import COLLECTOR_VERSION

LIST_URL = "https://hr.163.com/api/hr163/position/queryPage"
DETAIL_URL = "https://hr.163.com/api/hr163/position/query"
SAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def safe_name(value):
    return SAFE_NAME.sub("_", str(value))[:120]


def git_commit():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None


def parse_json(body):
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def raw_ref(batch, relative):
    """raw_refs 每项固定为 path + 64 位小写 sha256，路径相对本批次目录。"""
    return {"path": relative, "sha256": sha256_file(batch.path / relative)}


def fetch_detail(batch, client, job_id, args):
    """详情抽查：GET 详情，业务失败按退避重试；每次尝试都写入 requests.jsonl。

    返回 (data, 原始文件路径, 失败说明)；受限时抛 StopCollection（尝试已全部留痕）。
    """
    params = {"id": job_id}
    url = f"{DETAIL_URL}?{urlencode(params)}"
    name = f"detail_{safe_name(job_id)}.json"
    if batch.has_raw(name):
        payload = parse_json(batch.read_raw(name))
        path = batch.raw_path(name)
        if payload and payload.get("code") == 200 and isinstance(payload.get("data"), dict):
            return payload["data"], path, None
        code = payload.get("code") if payload else "解析失败"
        return None, path, f"复用原始响应但业务状态 {code}"

    message = "详情请求失败"
    for try_no in range(args.retries + 1):
        try:
            response = client.get(url, params)
        except StopCollection as exc:
            for attempt in exc.attempts:
                batch.log_attempt(attempt, "GET", url, params, None, False)
            raise
        for attempt in response.attempts[:-1]:
            batch.log_attempt(attempt, "GET", url, params, None, False)
        if response.error or response.body is None:
            batch.log_request(response, None, False)
            message = response.error or "详情响应为空"
        else:
            payload = parse_json(response.body)
            if payload and payload.get("code") == 200 and isinstance(payload.get("data"), dict):
                path, _ = batch.save_raw(name, response.body)
                batch.log_request(response, path, True)
                return payload["data"], path, None
            batch.log_request(response, None, False)
            code = payload.get("code") if payload else "解析失败"
            message = f"详情业务状态 {code}"
        if try_no < args.retries:
            time.sleep(client.backoff * (try_no + 1))
    return None, None, message


def list_stats(batch):
    """从已保存的列表原始响应回算计数，保证清单计数可复核。"""
    listed = 0
    unique = set()
    reported = {"pages": None, "total": None}
    for path in sorted((batch.path / "raw").glob("list_*.json")):
        payload = parse_json(path.read_bytes())
        if not payload:
            continue
        data = payload.get("data") or {}
        posts = data.get("list") or []
        listed += len(posts)
        unique.update(str(post.get("id")) for post in posts if post.get("id") is not None)
        reported["pages"] = data.get("pages", reported["pages"])
        reported["total"] = data.get("total", reported["total"])
    return listed, unique, reported


def count_failed_requests(batch):
    failed = 0
    path = batch.path / "requests.jsonl"
    if not path.exists():
        return 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("error") or row.get("http_status") != 200 \
                or row.get("business_success") is not True:
            failed += 1
    return failed


def run(args):
    batch = Batch(args.batch_dir)
    if batch.jobs:
        raise ValueError("该批次已有 jobs.jsonl，禁止重复写入；请新建批次后重跑")
    client = Client(interval=args.interval, retries=args.retries,
                    seq_start=batch.max_request_seq())
    commit = args.collector_commit or git_commit() or "pending"
    parser_version = f"netease-collector-{COLLECTOR_VERSION}"

    rows, metas = [], []
    seen, excluded, unresolved = set(), set(), set()
    detail_results = {}
    output_ids = set()
    error_pages = []
    unidentified = 0
    stop_reason = None
    page = 1
    previous_ids = None
    halt = False

    while page <= args.max_pages and not halt:
        if len(rows) >= args.target:
            stop_reason = "pilot_limit"
            break

        name = f"list_{page:06d}.json"
        if batch.has_raw(name):
            body = batch.read_raw(name)
            response = None
            response_path = batch.raw_path(name)
            observed_at = batch.requested_at_for(response_path)
            if observed_at is None:
                error_pages.append({"page": page, "status": 200,
                                    "reason": "复用原始响应但找不到请求时间"})
                stop_reason = "observed_at_missing"
                break
        else:
            payload = {"currentPage": page, "pageSize": args.page_size}
            try:
                response = client.post_json(LIST_URL, payload)
            except StopCollection as exc:
                for attempt in exc.attempts:
                    batch.log_attempt(attempt, "POST", LIST_URL, payload, None, False)
                batch.add_issue(None, "access_restriction", "error", "stop", str(exc), [])
                error_pages.append({"page": page, "status": exc.attempt.status, "reason": str(exc)})
                stop_reason = "access_restricted"
                break
            for attempt in response.attempts[:-1]:
                batch.log_attempt(attempt, "POST", LIST_URL, payload, None, False)
            if response.error or response.body is None:
                batch.log_request(response, None, False)
                error_pages.append({"page": page, "status": response.status, "reason": response.error})
                stop_reason = "list_request_failed"
                break
            body = response.body
            response_path, _ = batch.save_raw(name, body)
            observed_at = response.requested_at

        payload_obj = parse_json(body)
        business_ok = bool(payload_obj) and payload_obj.get("code") == 200 \
            and isinstance((payload_obj.get("data") or {}).get("list"), list)
        if response is not None:
            batch.log_request(response, response_path, business_ok)
        if not business_ok:
            reason = "JSON 解析失败" if payload_obj is None \
                else f"业务状态 {payload_obj.get('code')}"
            error_pages.append({"page": page, "status": response.status if response else 200,
                                "reason": reason})
            stop_reason = "list_business_failed"
            break

        posts = (payload_obj.get("data") or {}).get("list") or []
        ids = [str(post.get("id")) for post in posts if post.get("id") is not None]
        if previous_ids is not None and ids and ids == previous_ids:
            batch.add_issue(None, "pagination_stalled", "error", "reject",
                            f"第 {page} 页与上一页岗位完全相同",
                            [raw_ref(batch, response_path)])
            error_pages.append({"page": page, "status": 200, "reason": "分页停滞"})
            stop_reason = "pagination_stalled"
            break
        previous_ids = ids
        if not posts:
            stop_reason = "source_exhausted"
            break

        for index, post in enumerate(posts):
            if len(rows) >= args.target:
                break
            job_id = post.get("id")
            if job_id is None:
                unidentified += 1
                batch.add_issue(None, "unidentified_record", "error", "review",
                                f"第 {page} 页第 {index + 1} 条缺少 id，无法定位",
                                [raw_ref(batch, response_path)])
                continue
            job_id = str(job_id)
            if job_id in seen:
                batch.add_issue(job_id, "duplicate_source_id", "warning", "review",
                                f"第 {page} 页出现重复来源 ID，已跳过",
                                [raw_ref(batch, response_path)])
                continue
            seen.add(job_id)

            decision, reason = classify(post)
            if decision == "exclude":
                excluded.add(job_id)
                batch.add_issue(job_id, "scope_exclude", "info", "exclude", reason,
                                [raw_ref(batch, response_path)])
                continue
            if decision == "review":
                unresolved.add(job_id)
                batch.add_issue(job_id, "scope_review", "warning", "review", reason,
                                [raw_ref(batch, response_path)])

            row = build_job(post, None, batch.batch_id, observed_at,
                            raw_ref(batch, response_path), parser_version)
            problems = validate_job(row)
            if problems:
                raise ValueError(f"记录不符合契约：{job_id}：{problems}")
            rows.append(row)
            output_ids.add(job_id)
            metas.append({"page": page, "list_path": response_path, "index": index})

        page += 1

    if len(rows) >= args.target:
        stop_reason = "pilot_limit"
    elif stop_reason is None:
        stop_reason = "page_limit"

    # 列表已含完整正文；只抽取少量详情核对，避免为凑请求量重复下载。
    k = min(args.detail_samples, len(rows))
    rng = random.Random(args.sample_seed)
    sampled = sorted(rng.sample(range(len(rows)), k)) if k else []
    restricted = False
    for index in sampled:
        row, meta = rows[index], metas[index]
        job_id = row["source_job_id"]
        list_ref = row["raw_refs"][0]
        result = {"status": "failed", "list_path": meta["list_path"]}
        try:
            data, detail_path, message = fetch_detail(batch, client, job_id, args)
        except StopCollection as exc:
            batch.add_issue(job_id, "access_restriction", "error", "stop", str(exc), [list_ref])
            error_pages.append({"page": meta["page"], "status": exc.attempt.status,
                                "reason": f"详情抽查受限：{exc}"})
            unresolved.add(job_id)
            result.update({"path": None, "message": str(exc)})
            detail_results[job_id] = result
            restricted = True
            break
        if data is None:
            refs = [list_ref] + ([raw_ref(batch, detail_path)] if detail_path else [])
            batch.add_issue(job_id, "detail_failed", "warning", "review", message, refs)
            unresolved.add(job_id)
            result.update({"path": detail_path, "message": message})
            detail_results[job_id] = result
            continue

        detail_ref = raw_ref(batch, detail_path)
        detail_row = build_job({}, data, batch.batch_id, row["observed_at"],
                               list_ref, parser_version, detail_ref)
        mismatches = compare_detail(row, detail_row)
        row["raw_refs"].append(detail_ref)
        if mismatches:
            batch.add_issue(job_id, "detail_mismatch", "warning", "review",
                            "列表与详情字段不一致：" + "；".join(mismatches),
                            [list_ref, detail_ref])
            unresolved.add(job_id)
        result.update({"status": "ok", "path": detail_path, "mismatches": mismatches})
        detail_results[job_id] = result

    for row in rows:
        for rule, severity, action, message in text_issues(row):
            batch.add_issue(row["source_job_id"], rule, severity, action, message,
                            row["raw_refs"])
            if action == "review":
                unresolved.add(row["source_job_id"])
        batch.add_job(row)

    listed_records, unique_listed, reported = list_stats(batch)
    raw_files = [p for p in (batch.path / "raw").iterdir()
                 if p.is_file() and p.name != ".gitkeep"]
    unprocessed = sorted(unique_listed - output_ids - excluded)
    counts = {
        "requests": batch.request_count,
        "failed_requests": count_failed_requests(batch),
        "list_pages": len(list((batch.path / "raw").glob("list_*.json"))),
        "raw_response_files": len(raw_files),
        "listed_records": listed_records,
        "unique_source_ids": len(unique_listed),
        "output_records": len(rows),
        "excluded_unique_ids": len(excluded),
        "unresolved_unique_ids": len(unresolved & output_ids),
        "unprocessed_unique_ids": len(unprocessed),
        "unprocessed_ids": unprocessed,
        "unidentified_records": unidentified,
    }
    query_spec = {
        "endpoints": [LIST_URL, DETAIL_URL],
        "parameters": ["currentPage", "pageSize", "id"],
        "page_sequence": f"currentPage 1..{counts['list_pages']}，pageSize={args.page_size}",
        "selection_rule": "按页面正常顺序采集；类目白名单（技术/游戏程序/人工智能等）"
                          "+标题黑名单+海外/港澳台地点排除；不使用关键词筛选",
        "pagination_basis": f"响应 data.pages={reported['pages']}、data.total={reported['total']}；"
                            "按 currentPage 翻页，整页 ID 与上一页相同即判定停滞",
    }
    batch.finalize(
        query_spec=query_spec,
        coverage_status="partial",
        stop_reason=stop_reason,
        counts=counts,
        error_pages=error_pages,
        parser_version=parser_version,
        collector_commit=commit,
    )
    problems = verify_manifest(batch)
    if problems:
        raise RuntimeError("清单哈希复核失败：" + "；".join(problems))

    write_readme(batch, counts=counts, args=args, parser_version=parser_version,
                 commit=commit, rows=rows, metas=metas, detail_results=detail_results,
                 stop_reason=stop_reason, access_restricted=restricted)

    print(json.dumps({
        "batch": batch.batch_id,
        "batch_dir": str(batch.path),
        "output_records": counts["output_records"],
        "status": "ok" if counts["output_records"] >= args.target else "incomplete",
        "stop_reason": stop_reason,
        "detail_samples": len(detail_results),
        "counts": counts,
    }, ensure_ascii=False, indent=2))

    if counts["output_records"] >= args.target:
        return 0
    if stop_reason in ("list_request_failed", "list_business_failed",
                       "pagination_stalled", "access_restricted"):
        return 2
    return 3


def main(argv=None):
    parser = argparse.ArgumentParser(description="网易社会招聘小批采集器")
    parser.add_argument("--batch-dir", required=True,
                        help="由 scripts/new_collection_batch.py 生成的批次目录")
    parser.add_argument("--target", type=int, default=100, help="目标不同来源岗位数")
    parser.add_argument("--max-pages", type=int, default=100, help="列表最多翻页数")
    parser.add_argument("--page-size", type=int, default=10, help="每页条数，接口实测为 10")
    parser.add_argument("--interval", type=float, default=3.0, help="请求最小间隔（秒）")
    parser.add_argument("--retries", type=int, default=2, help="网络失败重试次数")
    parser.add_argument("--detail-samples", type=int, default=8, help="详情抽查条数（至少 5）")
    parser.add_argument("--sample-seed", type=int, default=20261101, help="详情与抽检固定随机种子")
    parser.add_argument("--collector-commit", default="pending",
                        help="生成数据的代码 commit；应用补丁提交后回填")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except StopCollection as exc:
        print(f"已停止：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
