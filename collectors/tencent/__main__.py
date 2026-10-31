"""腾讯小批采集入口：从仓库根目录运行。

python -m collectors.tencent --batch-dir data/tencent/<batch_id> --target 100 --max-pages 40
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode

from .batch import Batch, sha256_file
from .client import Client, StopCollection, utc_now
from .mapping import build_job, classify, text_issues
from . import COLLECTOR_VERSION

LIST_URL = "https://careers.tencent.com/tencentcareer/api/post/Query"
DETAIL_URL = "https://careers.tencent.com/tencentcareer/api/post/ByPostId"
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


def load_issue_ids(batch):
    """重跑时不重复登记；已排除和已标记待复核的岗位不再重复报同一问题。"""
    excluded, unresolved = set(), set()
    path = batch.path / "quality_issues.jsonl"
    if not path.exists():
        return excluded, unresolved
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        job_id = row.get("source_job_id")
        if row.get("action") == "exclude":
            excluded.add(job_id)
        if row.get("rule") == "detail_failed" and row.get("action") == "retry":
            unresolved.add(job_id)
    return excluded, unresolved


def list_stats(batch):
    """从已保存的列表原始响应回算计数，保证重跑后清单计数仍可核对。"""
    listed = 0
    unique = set()
    for path in sorted((batch.path / "raw").glob("list_*.json")):
        payload = parse_json(path.read_bytes())
        if not payload:
            continue
        posts = (payload.get("Data") or {}).get("Posts") or []
        listed += len(posts)
        unique.update(str(post.get("PostId")) for post in posts)
    return listed, unique


def run(args):
    batch = Batch(args.batch_dir)
    client = Client(interval=args.interval, retries=args.retries)
    commit = git_commit()
    parser_version = f"tencent-collector-{COLLECTOR_VERSION}" + (f"+{commit}" if commit else "")
    excluded, unresolved = load_issue_ids(batch)

    error_pages = []
    stop_reason = None
    halted = False
    page = 1
    previous_ids = None

    while page <= args.max_pages and not halted:
        if len(batch.jobs) >= args.target:
            stop_reason = "pilot_limit"
            break

        name = f"list_{page:06d}.json"
        if batch.has_raw(name):
            body = batch.read_raw(name)
            response = None
            response_path = batch.raw_path(name)
        else:
            params = {"pageIndex": page, "pageSize": args.page_size, "language": "zh-cn"}
            if args.keyword:
                params["keyword"] = args.keyword
            url = LIST_URL + "?" + urlencode(params)
            try:
                response = client.get(url, params)
            except StopCollection as exc:
                # 受限请求本身也要留痕，并写入异常文件后再收尾清单。
                batch.log_attempt(exc.attempt, url, params, None, False)
                batch.add_issue(None, "access_restriction", "error", "stop", str(exc), [])
                error_pages.append({"page": page, "status": exc.attempt.status, "reason": str(exc)})
                stop_reason = "access_restricted"
                break
            for attempt in response.attempts[:-1]:
                batch.log_attempt(attempt, url, params, None, False)
            if response.error or response.body is None:
                batch.log_request(response, None, False)
                error_pages.append({"page": page, "status": response.status, "reason": response.error})
                stop_reason = "list_request_failed"
                break
            body = response.body
            response_path, _ = batch.save_raw(name, body)

        payload = parse_json(body)
        business_ok = bool(payload) and payload.get("Code") == 200
        if response is not None:
            batch.log_request(response, response_path, business_ok)
        if not business_ok:
            error_pages.append({"page": page, "status": response.status if response else 200,
                                "reason": f"业务状态 {payload.get('Code') if payload else 'JSON 解析失败'}"})
            stop_reason = "list_business_failed"
            break

        posts = payload["Data"].get("Posts") or []
        ids = [str(post.get("PostId")) for post in posts]

        # 翻页停滞校验：整页 ID 与上一页完全相同说明分页未生效。
        if previous_ids is not None and ids and ids == previous_ids:
            batch.add_issue(None, "pagination_stalled", "error", "reject",
                            f"第 {page} 页与上一页岗位完全相同", [raw_ref(batch, response_path)])
            error_pages.append({"page": page, "status": 200, "reason": "分页停滞"})
            stop_reason = "pagination_stalled"
            break
        previous_ids = ids
        if not posts:
            stop_reason = "source_exhausted"
            break

        for post in posts:
            if len(batch.jobs) >= args.target:
                break
            job_id = str(post.get("PostId"))
            if job_id in batch.jobs:
                continue
            if job_id in excluded:
                continue

            decision, reason = classify(post)
            if decision == "exclude":
                if job_id not in excluded:
                    excluded.add(job_id)
                    batch.add_issue(job_id, "scope_exclude", "info", "exclude", reason,
                                    [raw_ref(batch, response_path)])
                continue
            if decision == "review":
                batch.add_issue(job_id, "scope_review", "warning", "review", reason,
                                [raw_ref(batch, response_path)])

            detail_name = f"detail_{safe_name(job_id)}.json"
            if batch.has_raw(detail_name):
                detail_body = batch.read_raw(detail_name)
                detail_path = batch.raw_path(detail_name)
                # 观察时间必须取自当时的请求日志；日志缺失才退到列表响应时刻。
                observed_at = (batch.requested_at_for(detail_path)
                               or batch.requested_at_for(response_path)
                               or batch.first_requested_at())
                if observed_at is None:
                    observed_at = utc_now()
                    batch.add_issue(job_id, "observed_at_fallback", "warning", "review",
                                    "请求日志缺失，观察时间退化为当前时刻", [raw_ref(batch, detail_path)])
                detail_response = None
            else:
                params = {"postId": job_id, "language": "zh-cn"}
                detail_url = DETAIL_URL + "?" + urlencode(params)
                try:
                    detail_response = client.get(detail_url, params)
                except StopCollection as exc:
                    batch.log_attempt(exc.attempt, detail_url, params, None, False)
                    batch.add_issue(job_id, "access_restriction", "error", "stop", str(exc), [])
                    error_pages.append({"page": page, "status": exc.attempt.status, "reason": str(exc)})
                    stop_reason = "access_restricted"
                    halted = True
                    break
                for attempt in detail_response.attempts[:-1]:
                    batch.log_attempt(attempt, detail_url, params, None, False)
                if detail_response.error or detail_response.body is None:
                    batch.log_request(detail_response, None, False)
                    if job_id not in unresolved:
                        unresolved.add(job_id)
                        batch.add_issue(job_id, "detail_failed", "error", "retry",
                                        detail_response.error or "详情请求失败",
                                        [raw_ref(batch, response_path)])
                    continue
                detail_body = detail_response.body
                detail_path, _ = batch.save_raw(detail_name, detail_body)
                observed_at = detail_response.requested_at

            detail_payload = parse_json(detail_body)
            detail_ok = bool(detail_payload) and detail_payload.get("Code") == 200
            if detail_response is not None:
                batch.log_request(detail_response, detail_path, detail_ok)
            if not detail_ok:
                if job_id not in unresolved:
                    unresolved.add(job_id)
                    batch.add_issue(job_id, "detail_failed", "error", "retry", "详情业务状态非 200",
                                    [raw_ref(batch, detail_path)])
                continue

            detail = detail_payload["Data"] or {}
            row = build_job(post, detail, batch.batch_id, observed_at,
                            raw_ref(batch, response_path),
                            raw_ref(batch, detail_path), parser_version)
            for rule, severity, action, message in text_issues(row):
                batch.add_issue(job_id, rule, severity, action, message, row["raw_refs"])
            batch.add_job(row)

        page += 1

    if len(batch.jobs) >= args.target:
        stop_reason = "pilot_limit"
    elif stop_reason is None:
        stop_reason = "page_limit"

    list_pages = len(list((batch.path / "raw").glob("list_*.json")))
    listed_records, unique_listed = list_stats(batch)
    # 达到目标时同页剩余、既未输出也未排除的岗位：单独计数，便于逐项对账。
    unprocessed = sorted(unique_listed - set(batch.jobs) - excluded - (unresolved - set(batch.jobs)))
    counts = {
        "requests": batch.request_count,
        "failed_requests": _count_failed_requests(batch),
        "list_pages": list_pages,
        "raw_response_files": len([p for p in (batch.path / "raw").iterdir()
                                   if p.is_file() and p.name != ".gitkeep"]),
        "listed_records": listed_records,
        "unique_source_ids": len(unique_listed),
        "output_records": len(batch.jobs),
        "excluded_unique_ids": len(excluded),
        "unresolved_unique_ids": len(unresolved - batch.jobs),
        "unprocessed_unique_ids": len(unprocessed),
        "unprocessed_ids": unprocessed,
        "unidentified_records": 0,
    }
    query_spec = {
        "endpoints": [LIST_URL, DETAIL_URL],
        "parameters": ["pageIndex", "pageSize", "language", "postId"] +
                      (["keyword"] if args.keyword else []),
        "page_sequence": f"pageIndex 1..{list_pages}，pageSize={args.page_size}",
        "selection_rule": "按页面顺序采集；类目白名单+标题黑名单+海外地点排除" +
                          ("；keyword=" + args.keyword if args.keyword else "；不使用关键词筛选"),
        "pagination_basis": "接口 Data.Count 与 Posts 长度；整页 ID 与上一页相同即判定停滞",
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

    print(json.dumps({
        "batch": batch.batch_id,
        "batch_dir": str(batch.path),
        "output_records": counts["output_records"],
        "status": "ok" if counts["output_records"] >= args.target else "incomplete",
        "stop_reason": stop_reason,
        "counts": counts,
    }, ensure_ascii=False, indent=2))

    if counts["output_records"] >= args.target:
        return 0
    if stop_reason in ("list_request_failed", "list_business_failed", "pagination_stalled",
                       "access_restricted"):
        return 2
    return 3


def _count_failed_requests(batch):
    path = batch.path / "requests.jsonl"
    if not path.exists():
        return 0
    failed = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("error") or row.get("http_status") != 200 or row.get("business_success") is not True:
            failed += 1
    return failed


def main(argv=None):
    parser = argparse.ArgumentParser(description="腾讯招聘小批采集器")
    parser.add_argument("--batch-dir", required=True, help="由 scripts/new_collection_batch.py 生成的批次目录")
    parser.add_argument("--target", type=int, default=100, help="目标不同来源岗位数")
    parser.add_argument("--max-pages", type=int, default=40, help="列表最多翻页数")
    parser.add_argument("--page-size", type=int, default=10, help="每页条数，接口实测为 10")
    parser.add_argument("--interval", type=float, default=3.0, help="请求最小间隔（秒）")
    parser.add_argument("--retries", type=int, default=2, help="网络失败重试次数")
    parser.add_argument("--keyword", default="", help="可选关键词；默认不使用")
    args = parser.parse_args(argv)
    try:
        return run(args)
    except StopCollection as exc:
        print(f"已停止：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
