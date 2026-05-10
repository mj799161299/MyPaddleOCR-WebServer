"""安全中间件：安全响应头 + 速率限制"""

import time
import threading
from collections import defaultdict
from typing import Dict, List, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from config import settings


# ---- 安全响应头中间件 ----

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """为所有 HTTP 响应添加安全头，防御常见 Web 攻击。"""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        headers = response.headers

        # 防止 MIME 类型嗅探
        headers.setdefault("X-Content-Type-Options", "nosniff")

        # 禁止被 iframe 嵌入（防点击劫持）
        headers.setdefault("X-Frame-Options", "DENY")

        # 旧版 XSS 防护（兼容 IE/旧浏览器）
        headers.setdefault("X-XSS-Protection", "1; mode=block")

        # 控制 Referer 信息发送
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")

        # 限制浏览器功能权限
        headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )

        # 禁止浏览器缓存敏感页面
        headers.setdefault("Cache-Control", "no-store, max-age=0")

        # HSTS（仅 HTTPS 启用，强制浏览器走加密连接）
        if request.url.scheme == "https":
            headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains; preload",
            )

        return response


# ---- 滑动窗口速率限制器 ----

class SlidingWindowRateLimiter:
    """基于滑动窗口的速率限制器。

    按 key（IP 或 IP+路径）统计时间窗口内的请求数，
    超限返回 False。
    """

    def __init__(self, requests_per_window: int, window_seconds: int = 60):
        """
        Args:
            requests_per_window: 窗口内最大请求数
            window_seconds:     时间窗口秒数，默认60秒
        """
        self.limit = requests_per_window
        self.window = window_seconds
        self._storage: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> Tuple[bool, int, float]:
        """检查 key 是否允许通过。

        Returns: (allowed, remaining, reset_seconds)
        """
        now = time.monotonic()
        with self._lock:
            timestamps = self._storage[key]
            # 清理过期记录
            cutoff = now - self.window
            timestamps = [t for t in timestamps if t > cutoff]
            self._storage[key] = timestamps

            if len(timestamps) >= self.limit:
                oldest = timestamps[0] if timestamps else now
                reset_in = max(0, self.window - (now - oldest))
                return False, 0, reset_in

            timestamps.append(now)
            remaining = self.limit - len(timestamps)
            reset_in = self.window - (now - timestamps[0]) if timestamps else self.window
            return True, remaining, max(0, reset_in)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """全局限速 + 按路径分级限速中间件。

    规则：
      - /api/auth/login     → 登入限速
      - /api/auth/register  → 注册限速
      - /api/upload/*       → 上传限速
      - 其他 /api/*          → 默认限速
    """

    def __init__(self, app):
        super().__init__(app)
        self._default = self._parse_limit(settings.RATE_LIMIT_DEFAULT)
        self._limits: Dict[str, SlidingWindowRateLimiter] = {
            "/api/auth/login":    self._parse_limit(settings.RATE_LIMIT_LOGIN),
            "/api/auth/register": self._parse_limit(settings.RATE_LIMIT_REGISTER),
            "/api/upload/":       self._parse_limit(settings.RATE_LIMIT_UPLOAD),
        }

    @staticmethod
    def _parse_limit(limit_str: str) -> SlidingWindowRateLimiter:
        parts = limit_str.split("/")
        count = int(parts[0])
        unit = parts[1].lower() if len(parts) > 1 else "minute"
        multipliers = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
        seconds = multipliers.get(unit, 60)
        return SlidingWindowRateLimiter(count, seconds)

    def _get_client_ip(self, request: Request) -> str:
        # X-Forwarded-For（反向代理）
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        # X-Real-IP
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip.strip()
        # 直连 IP
        if request.client:
            return request.client.host
        return "unknown"

    def _get_limiter(self, path: str) -> SlidingWindowRateLimiter:
        for prefix, limiter in self._limits.items():
            if path.startswith(prefix):
                return limiter
        return self._default

    async def dispatch(self, request: Request, call_next):
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        # 静态资源不限速
        if request.url.path.startswith("/uploads"):
            return await call_next(request)

        ip = self._get_client_ip(request)
        limiter = self._get_limiter(request.url.path)
        key = f"{ip}:{request.url.path}"

        allowed, remaining, reset_sec = limiter.is_allowed(key)
        if not allowed:
            return Response(
                content='{"detail":"请求过于频繁，请稍后重试"}',
                status_code=429,
                media_type="application/json",
                headers={
                    "Retry-After": str(int(reset_sec) + 1),
                    "X-RateLimit-Limit": str(limiter.limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(time.time() + reset_sec)),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limiter.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(time.time() + reset_sec))
        return response
