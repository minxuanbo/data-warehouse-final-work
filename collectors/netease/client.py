"""网易公开接口访问层：单并发、请求间隔至少 3 秒、失败有限重试、每次尝试留痕。"""
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone

USER_AGENT = "CourseDataWarehouse/1.0 (course project; single-threaded public data collection)"
# 这些状态码代表访问被限制，必须立即停止而不是继续重试。
RESTRICTION_STATUS = {401, 403, 418, 429}
RESTRICTION_TEXT = ("登录", "验证码", "访问受限", "访问过于频繁")


class StopCollection(Exception):
    """遇到登录、验证码或访问限制，立即停止采集；携带本次调用的全部尝试。"""

    def __init__(self, reason, attempts):
        super().__init__(reason)
        self.attempts = attempts
        self.attempt = attempts[-1] if attempts else None


def utc_now():
    """返回带时区的 UTC 时间字符串（Z 结尾）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class Attempt:
    """一次实际发出的 HTTP 请求；重试的每一次都单独记录，失败尝试同样留痕。"""
    request_id: str
    requested_at: str
    status: int | None
    encoding: str | None
    elapsed_ms: int
    attempt: int
    error: str | None = None


@dataclass
class Response:
    request_id: str
    requested_at: str
    method: str
    url: str
    params: dict
    status: int | None
    body: bytes | None
    encoding: str | None
    elapsed_ms: int
    attempt: int
    error: str | None = None
    attempts: list = field(default_factory=list)


def _looks_html(body):
    head = body[:200].lstrip()
    return head.startswith(b"<")


def _has_restriction_text(body):
    """只对非 JSON 响应（如错误页）检查登录/验证码提示，避免误判岗位正文。"""
    if not body or not _looks_html(body):
        return False
    text = body[:2000].decode("utf-8", errors="ignore")
    return any(word in text for word in RESTRICTION_TEXT)


@dataclass
class Client:
    interval: float = 3.0
    retries: int = 2
    timeout: int = 30
    backoff: float = 4.0
    seq_start: int = 0
    _last_request_at: float = field(default=0.0, init=False)
    _seq: int = field(default=0, init=False)

    def __post_init__(self):
        # 同一批次多次运行时从已有日志的最大编号继续，request_id 不重复。
        self._seq = self.seq_start

    def _wait(self):
        gap = time.monotonic() - self._last_request_at
        if gap < self.interval:
            time.sleep(self.interval - gap)
        self._last_request_at = time.monotonic()

    def get(self, url, params):
        return self._request("GET", url, params)

    def post_json(self, url, payload):
        return self._request("POST", url, payload)

    def _request(self, method, url, payload):
        """执行一次请求，网络错误按退避重试；访问限制抛 StopCollection。

        返回的 Response.attempts 包含本次调用的全部尝试（含失败尝试），
        调用方必须把 attempts 逐条写入运行日志。
        """
        attempts = []
        attempt = 0
        while True:
            attempt += 1
            self._wait()
            self._seq += 1
            request_id = f"req_{self._seq:04d}"
            started = time.monotonic()
            status = None
            body = None
            encoding = None
            error = None
            data = None
            headers = {"User-Agent": USER_AGENT}
            if method != "GET":
                data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
                headers["Content-Type"] = "application/json;charset=UTF-8"
            try:
                request = urllib.request.Request(url, data=data, headers=headers, method=method)
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    status = response.status
                    encoding = response.headers.get_content_charset() or "utf-8"
                    body = response.read()
            except urllib.error.HTTPError as exc:
                status = exc.code
                encoding = exc.headers.get_content_charset() if exc.headers else None
                body = exc.read()
                error = f"HTTP {exc.code}"
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                error = f"{type(exc).__name__}: {exc}"

            elapsed_ms = int((time.monotonic() - started) * 1000)
            current = Attempt(
                request_id=request_id,
                requested_at=utc_now(),
                status=status,
                encoding=encoding,
                elapsed_ms=elapsed_ms,
                attempt=attempt,
                error=error,
            )
            attempts.append(current)

            if status in RESTRICTION_STATUS:
                raise StopCollection(f"HTTP {status} 访问受限，停止采集", attempts)
            if _has_restriction_text(body):
                raise StopCollection("响应中出现登录/验证码提示，停止采集", attempts)
            if error is None:
                return Response(
                    request_id=request_id,
                    requested_at=current.requested_at,
                    method=method,
                    url=url,
                    params=dict(payload or {}),
                    status=status,
                    body=body,
                    encoding=encoding,
                    elapsed_ms=elapsed_ms,
                    attempt=attempt,
                    attempts=attempts,
                )
            if attempt > self.retries:
                return Response(
                    request_id=request_id,
                    requested_at=current.requested_at,
                    method=method,
                    url=url,
                    params=dict(payload or {}),
                    status=status,
                    body=body,
                    encoding=encoding,
                    elapsed_ms=elapsed_ms,
                    attempt=attempt,
                    error=error,
                    attempts=attempts,
                )
            time.sleep(self.backoff * attempt)
