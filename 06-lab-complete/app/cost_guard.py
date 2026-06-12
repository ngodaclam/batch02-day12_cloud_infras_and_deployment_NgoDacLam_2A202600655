"""
Cost guard module — tracks and limits monthly spending per user.
Uses Redis to persist cost data.
"""

from datetime import datetime

import redis
from fastapi import HTTPException, status

from .config import settings

r = redis.from_url(settings.REDIS_URL, decode_responses=True)


def check_budget(user_id: str, estimated_cost: float = 0.01):
    """
    Check if user is within monthly budget.
    Raises 402 (Payment Required) if budget exceeded.
    
    Each user has a monthly budget defined by MONTHLY_BUDGET_USD.
    Spending is tracked in Redis and resets at the start of each month.
    """
    month_key = datetime.now().strftime("%Y-%m")
    key = f"budget:{user_id}:{month_key}"

    current = float(r.get(key) or 0)
    if current + estimated_cost > settings.MONTHLY_BUDGET_USD:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Monthly budget of ${settings.MONTHLY_BUDGET_USD} exceeded.",
        )

    # Record spending
    r.incrbyfloat(key, estimated_cost)
    r.expire(key, 32 * 24 * 3600)  # Auto-expire after 32 days
