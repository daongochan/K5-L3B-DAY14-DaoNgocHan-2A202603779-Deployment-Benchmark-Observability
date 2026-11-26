"""
Rate limiting (tiêu chí 7) — Sliding window 60 giây lưu trong Redis.
"""
import hashlib
import secrets
import time

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def check_rate_limit(key: str) -> None:
    """
    Giới hạn tối đa RATE_LIMIT_PER_MINUTE request / 60s cho mỗi API key.
    State lưu trên Redis sorted set để chia sẻ giữa các worker/instance và bền vững qua restart.
    """
    limit = settings.rate_limit_per_minute
    now = time.time()
    window_start = now - WINDOW_SECONDS
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    redis_key = f"ratelimit:{key_hash}"

    try:
        pipe = r.pipeline()
        pipe.zremrangebyscore(redis_key, 0, window_start)
        pipe.zcard(redis_key)
        pipe.zrange(redis_key, 0, 0, withscores=True)
        _, current_count, oldest_entries = pipe.execute()

        if current_count >= limit:
            retry_after = WINDOW_SECONDS
            if oldest_entries:
                oldest_score = float(oldest_entries[0][1])
                retry_after = max(1, int(oldest_score + WINDOW_SECONDS - now) + 1)
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded ({limit} requests per minute).",
                headers={"Retry-After": str(retry_after)},
            )

        member = f"{now:.6f}:{secrets.token_hex(4)}"
        write_pipe = r.pipeline()
        write_pipe.zadd(redis_key, {member: now})
        write_pipe.expire(redis_key, WINDOW_SECONDS + 5)
        write_pipe.execute()
    except HTTPException:
        raise
    except (redis.RedisError, OSError):
        # Nếu Redis tạm không khả dụng, không làm sập tiến trình với 500
        return
