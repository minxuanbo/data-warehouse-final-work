"""批次目录读写：保存原始响应、写 JSONL、维护清单与哈希。"""
import hashlib
import json
import re
from pathlib import Path

REQUEST_ID = re.compile(r"^req_(\d+)$")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_nonempty_lines(path):
    with Path(path).open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


class Batch:
    def __init__(self, path):
        self.path = Path(path).resolve()
        manifest_path = self.path / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"缺少批次清单：{manifest_path}")
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if self.manifest.get("source") != "netease" or self.manifest.get("owner") != "B":
            raise ValueError("该目录不是 netease/B 的批次")
        self.batch_id = self.manifest["batch_id"]
        self.jobs = self._load_ids("jobs.jsonl")
        self.issue_keys = self._load_issue_keys()
        self.request_count = count_nonempty_lines(self.path / "requests.jsonl") \
            if (self.path / "requests.jsonl").exists() else 0

    def _load_issue_keys(self):
        """已登记的问题键，重跑时不重复写同一岗位的同一规则。"""
        keys = set()
        path = self.path / "quality_issues.jsonl"
        if not path.exists():
            return keys
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                keys.add((row.get("source_job_id"), row.get("rule")))
        return keys

    def requested_at_for(self, response_path):
        """按原始请求日志取响应时刻，不使用文件修改时间。"""
        path = self.path / "requests.jsonl"
        if not path.exists():
            return None
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("response_path") == response_path and not row.get("error"):
                return row.get("requested_at")
        return None

    def max_request_seq(self):
        """已有日志的最大 request_id 编号；续跑时从它之后继续，避免 ID 重复。"""
        path = self.path / "requests.jsonl"
        if not path.exists():
            return 0
        largest = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            match = REQUEST_ID.match(str(json.loads(line).get("request_id", "")))
            if match:
                largest = max(largest, int(match.group(1)))
        return largest

    def _load_ids(self, name):
        found = set()
        path = self.path / name
        if not path.exists():
            return found
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    found.add(json.loads(line)["source_job_id"])
        return found

    def has_raw(self, name):
        return (self.path / "raw" / name).exists()

    def raw_path(self, name):
        return f"raw/{name}"

    def save_raw(self, name, body):
        """保存原始响应字节，不覆盖已有文件；返回 (相对路径, sha256)。"""
        target = self.path / "raw" / name
        if target.exists():
            raise FileExistsError(f"原始响应已存在，拒绝覆盖：{target}")
        target.write_bytes(body)
        return self.raw_path(name), sha256_bytes(body)

    def read_raw(self, name):
        return (self.path / "raw" / name).read_bytes()

    def append_jsonl(self, name, row):
        with (self.path / name).open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def add_job(self, row):
        self.append_jsonl("jobs.jsonl", row)
        self.jobs.add(row["source_job_id"])

    def add_issue(self, source_job_id, rule, severity, action, message, raw_refs):
        key = (source_job_id, rule)
        if key in self.issue_keys:
            return
        self.issue_keys.add(key)
        self.append_jsonl("quality_issues.jsonl", {
            "source_job_id": source_job_id,
            "rule": rule,
            "severity": severity,
            "action": action,
            "message": message,
            "raw_refs": raw_refs,
        })

    def log_attempt(self, attempt, method, url, payload, response_path, business_success):
        """记录一次实际请求；重试链路中的失败尝试同样落盘，不留空档。"""
        self.append_jsonl("requests.jsonl", {
            "request_id": attempt.request_id,
            "requested_at": attempt.requested_at,
            "method": method,
            "url": url,
            "params": payload,
            "http_status": attempt.status,
            "business_success": business_success,
            "response_path": response_path,
            "encoding": attempt.encoding,
            "elapsed_ms": attempt.elapsed_ms,
            "attempt": attempt.attempt,
            "error": attempt.error,
        })
        self.request_count += 1

    def log_request(self, response, response_path, business_success):
        self.append_jsonl("requests.jsonl", {
            "request_id": response.request_id,
            "requested_at": response.requested_at,
            "method": response.method,
            "url": response.url,
            "params": response.params,
            "http_status": response.status,
            "business_success": business_success,
            "response_path": response_path,
            "encoding": response.encoding,
            "elapsed_ms": response.elapsed_ms,
            "attempt": response.attempt,
            "error": response.error,
        })
        self.request_count += 1

    def file_entry(self, relative, records):
        target = self.path / relative
        return {
            "path": relative,
            "bytes": target.stat().st_size,
            "sha256": sha256_file(target),
            "records": records,
        }

    def finalize(self, *, query_spec, coverage_status, stop_reason, counts,
                 error_pages, parser_version, collector_commit):
        raw_files = sorted(
            p for p in (self.path / "raw").iterdir()
            if p.is_file() and p.name != ".gitkeep"
        )
        files = [self.file_entry(f"raw/{p.name}", None) for p in raw_files]
        for name in ("jobs.jsonl", "requests.jsonl", "quality_issues.jsonl"):
            files.append(self.file_entry(name, count_nonempty_lines(self.path / name)))

        requests = [json.loads(line) for line in
                    (self.path / "requests.jsonl").read_text(encoding="utf-8").splitlines()
                    if line.strip()]
        started = requests[0]["requested_at"] if requests else None
        finished = requests[-1]["requested_at"] if requests else None

        self.manifest.update({
            "started_at": started,
            "finished_at": finished,
            "collector_commit": collector_commit,
            "parser_version": parser_version,
            "query_spec": query_spec,
            "coverage_status": coverage_status,
            "stop_reason": stop_reason,
            "counts": counts,
            "error_pages": error_pages,
            "files": files,
        })
        (self.path / "manifest.json").write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
        return self.manifest
