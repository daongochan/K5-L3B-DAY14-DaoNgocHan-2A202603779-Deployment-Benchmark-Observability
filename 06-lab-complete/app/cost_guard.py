"""
Cost guard (tiêu chí 8) — Theo dõi và bảo vệ ngân sách LLM trên Redis.
"""
from datetime import datetime, timezone

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

PRICE_INPUT_PER_1K = 0.00015
PRICE_OUTPUT_PER_1K = 0.0006

DAILY_TTL_SECONDS = 2 * 24 * 3600
MONTHLY_TTL_SECONDS = 32 * 24 * 3600


def _budget_keys() -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    return (
        f"cost:daily:{now.strftime('%Y-%m-%d')}",
        f"cost:monthly:{now.strftime('%Y-%m')}",
    )


def check_budget() -> None:
    """Kiểm tra ngân sách ngày và tháng trong Redis trước khi gọi LLM."""
    daily_key, monthly_key = _budget_keys()
    try:
        daily_raw, monthly_raw = r.mget(daily_key, monthly_key)
        daily_spent = float(daily_raw or 0.0)
        monthly_spent = float(monthly_raw or 0.0)
    except (redis.RedisError, OSError):
        return

    if daily_spent >= settings.daily_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Daily budget exceeded",
                "spent_usd": round(daily_spent, 6),
                "budget_usd": settings.daily_budget_usd,
            },
        )
    if monthly_spent >= settings.monthly_budget_usd:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Monthly budget exceeded",
                "spent_usd": round(monthly_spent, 6),
                "budget_usd": settings.monthly_budget_usd,
            },
        )


def record_cost(input_tokens: int, output_tokens: int) -> float:
    """Tính chi phí USD của lượt gọi LLM và cộng dồn nguyên tử vào Redis."""
    cost = (
        (input_tokens / 1000.0) * PRICE_INPUT_PER_1K
        + (output_tokens / 1000.0) * PRICE_OUTPUT_PER_1K
    )
    daily_key, monthly_key = _budget_keys()
    try:
        pipe = r.pipeline()
        pipe.incrbyfloat(daily_key, cost)
        pipe.expire(daily_key, DAILY_TTL_SECONDS)
        pipe.incrbyfloat(monthly_key, cost)
        pipe.expire(monthly_key, MONTHLY_TTL_SECONDS)
        pipe.execute()
    except (redis.RedisError, OSError):
        pass
    return round(cost, 8)
