"""腾讯公开接口访问层：单并发、请求间隔至少 3 秒、失败有限重试。"""
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
    """遇到登录、验证码或访问限制，立即停止采集。"""


def utc_now():
    """返回带时区的 UTC 时间字符串（Z 结尾）。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class Response:
    request_id: str
    requested_at: str
    url: str
    params: dict
    status: int | None
    body: bytes | None
    encoding: str | None
    elapsed_ms: int
    attempt: int
    error: str | None = None
    response_path: str | None = None
    business_success: bool | None = None


@dataclass
class Client:
    interval: float = 3.0
    retries: int = 2
    timeout: int = 30
    backoff: float = 4.0
    _last_request_at: float = field(default=0.0, init=False)
    _seq: int = field(default=0, init=False)

    def _wait(self):
        gap = time.monotonic() - self._last_request_at
        if gap < self.interval:
            time.sleep(self.interval - gap)
        self._last_request_at = time.monotonic()

    def get(self, url, params):
        """执行一次 GET，网络错误按退避重试；访问限制抛 StopCollection。"""
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
            try:
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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
            result = Response(
                request_id=request_id,
                requested_at=utc_now(),
                url=url,
                params=dict(params),
                status=status,
                body=body,
                encoding=encoding,
                elapsed_ms=elapsed_ms,
                attempt=attempt,
                error=error,
            )

            if status in RESTRICTION_STATUS:
                raise StopCollection(f"HTTP {status} 访问受限，停止采集")
            if body is not None:
                text = body[:2000].decode("utf-8", errors="ignore")
                if any(word in text for word in RESTRICTION_TEXT):
                    raise StopCollection("响应中出现登录/验证码提示，停止采集")
            if error is None:
                return result
            if attempt > self.retries:
                return result
            time.sleep(self.backoff * attempt)
