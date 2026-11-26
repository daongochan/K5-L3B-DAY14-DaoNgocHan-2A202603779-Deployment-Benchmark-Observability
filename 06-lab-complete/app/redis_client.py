"""
Kết nối Redis dùng chung cho rate limiter, cost guard và readiness probe.
"""
import redis

from app.config import settings

# Lazy connection pool: không gọi mạng lúc import để app vẫn khởi động được khi chưa có Redis
r = redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=1.5,
    socket_timeout=1.5,
)


def redis_healthy() -> bool:
    """Kiểm tra kết nối thực tế tới Redis cho endpoint GET /ready."""
    try:
        return bool(r.ping())
    except (redis.RedisError, OSError):
        return False
