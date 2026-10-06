from __future__ import annotations

import asyncio
import time
import logging
from typing import Dict

logger = logging.getLogger(__name__)


class TokenBucket:
    """Thread-safe async Token Bucket rate limiter.
    
    Telegram API specifies a global limit of 30 messages/sec for bots.
    We default to 25.0 tokens/sec capacity to provide a safe buffer on shared hosting.
    """

    def __init__(self, rate: float = 25.0, capacity: float = 25.0) -> None:
        self.rate = rate  # Tokens per second
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

            if self.tokens < 1.0:
                needed = 1.0 - self.tokens
                wait_time = needed / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0.0
            else:
                self.tokens -= 1.0


class PerChatRateLimiter:
    """Per-chat message throttle manager.
    
    Telegram API limits:
    - 1 message per second per group chat.
    - 20 messages per minute per group chat.
    
    We maintain a last-sent timestamp map per chat_id to prevent hitting Telegram 429
    during rapid game notifications.
    """

    def __init__(self, min_interval_group: float = 1.0, min_interval_private: float = 0.05) -> None:
        self.min_interval_group = min_interval_group
        self.min_interval_private = min_interval_private
        self._last_sent: Dict[int, float] = {}
        self._lock = asyncio.Lock()
        self._max_entries = 10000

    async def acquire(self, chat_id: int) -> None:
        # Determine interval: negative chat_ids are Telegram groups/supergroups
        is_group = chat_id < 0
        interval = self.min_interval_group if is_group else self.min_interval_private

        async with self._lock:
            now = time.monotonic()
            last = self._last_sent.get(chat_id, 0.0)
            elapsed = now - last

            if elapsed < interval:
                wait_time = interval - elapsed
                await asyncio.sleep(wait_time)
                self._last_sent[chat_id] = time.monotonic()
            else:
                self._last_sent[chat_id] = now

            # Periodic prune to prevent memory growth on shared hosting
            if len(self._last_sent) > self._max_entries:
                cutoff = now - 3600.0
                expired = [k for k, v in self._last_sent.items() if v < cutoff]
                for k in expired:
                    self._last_sent.pop(k, None)


# Global instances
global_rate_limiter = TokenBucket(rate=25.0, capacity=25.0)
per_chat_limiter = PerChatRateLimiter()
