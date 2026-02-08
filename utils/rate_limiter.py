"""
API 限流模块：滑动窗口 + 指数退让。
限制请求速度，超限时提醒「超速了」并给出建议等待时间。
"""
import time
from collections import deque
from threading import Lock


class RateLimiter:
    """
    限流器：核心为限制请求速度。
    - 滑动窗口：窗口内最多 max_per_minute 次请求。
    - 超限时采用指数退让：建议等待 2^连续超限次数 秒（有上限），超限时返回「超速了」提示。
    """

    def __init__(self, max_per_minute=10, window_seconds=60, max_backoff_seconds=60):
        self.max_per_minute = max_per_minute
        self.window_seconds = window_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self._timestamps = deque()
        self._consecutive_over = 0
        self._backoff_until = 0.0
        self._lock = Lock()

    def try_acquire(self):
        """
        尝试占用一个配额。在发起 AI 请求前调用。

        Returns:
            (allowed: bool, message: str):
            - allowed=True 时 message 为空，可继续请求。
            - allowed=False 时 message 为「超速了，请 X 秒后再试」，不应发起请求。
        """
        with self._lock:
            now = time.time()
            # 指数退让：若尚在退让期内，直接拒绝
            if now < self._backoff_until:
                wait = max(1, int(self._backoff_until - now))
                return (False, f"超速了，请 {wait} 秒后再试")
            # 滑动窗口：丢弃窗口外的记录
            while self._timestamps and self._timestamps[0] < now - self.window_seconds:
                self._timestamps.popleft()
            if len(self._timestamps) >= self.max_per_minute:
                self._consecutive_over += 1
                backoff = min(2 ** self._consecutive_over, self.max_backoff_seconds)
                self._backoff_until = now + backoff
                wait = max(1, int(backoff))
                return (False, f"超速了，请 {wait} 秒后再试")
            self._timestamps.append(now)
            self._consecutive_over = 0
            return (True, "")
