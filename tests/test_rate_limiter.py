import asyncio
import time
import pytest
from app.utils.rate_limiter import TokenBucket, PerChatRateLimiter


@pytest.mark.asyncio
async def test_token_bucket_acquire_rate():
    """Verify TokenBucket delays when tokens are exhausted."""
    bucket = TokenBucket(rate=10.0, capacity=2.0)
    
    # First 2 acquires should be instant
    start = time.monotonic()
    await bucket.acquire()
    await bucket.acquire()
    elapsed_initial = time.monotonic() - start
    assert elapsed_initial < 0.1

    # 3rd acquire requires token generation (1/10th of a second)
    await bucket.acquire()
    elapsed_total = time.monotonic() - start
    assert elapsed_total >= 0.08, f"Expected throttle delay >= 0.08s, got {elapsed_total:.3f}s"


@pytest.mark.asyncio
async def test_per_chat_rate_limiter_group_throttling():
    """Verify group chat messages (negative chat_id) are throttled to 1s interval."""
    limiter = PerChatRateLimiter(min_interval_group=0.1, min_interval_private=0.01)
    chat_id = -100123456789

    start = time.monotonic()
    await limiter.acquire(chat_id)
    await limiter.acquire(chat_id)
    elapsed = time.monotonic() - start

    assert elapsed >= 0.09, f"Group chat should be throttled by min_interval, got {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_per_chat_rate_limiter_isolation():
    """Verify sending to Chat A does not throttle Chat B."""
    limiter = PerChatRateLimiter(min_interval_group=0.5, min_interval_private=0.5)

    start = time.monotonic()
    await limiter.acquire(-1001)
    await limiter.acquire(-1002)  # Different chat
    elapsed = time.monotonic() - start

    assert elapsed < 0.2, f"Different chats should execute concurrently without cross-chat delay, got {elapsed:.3f}s"
