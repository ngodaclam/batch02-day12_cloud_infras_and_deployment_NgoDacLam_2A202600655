"""
Rate limiting module using Redis sliding window algorithm.
Limits requests per user per minute.
"""

import time

import redis
from fastapi import HTTPException, status

from .config import settings

r = redis.from_url(settings.REDIS_URL, decode_responses=True)


def check_rate_limit(user_id: str):
    """
    Sliding window rate limiter.
    Raises 429 if user exceeds RATE_LIMIT_PER_MINUTE.
    """
    now = time.time()
    window_start = now - 60  # 1-minute window
    key = f"rate_limit:{user_id}"

    pipe = r.pipeline()
    # Remove old entries outside the window
    pipe.zremrangebyscore(key, 0, window_start)
    # Count remaining entries in the window
    pipe.zcard(key)
    # Add current request
    pipe.zadd(key, {str(now): now})
    # Set expiry on the key
    pipe.expire(key, 60)
    results = pipe.execute()

    request_count = results[1]

    if request_count >= settings.RATE_LIMIT_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded. Max {settings.RATE_LIMIT_PER_MINUTE} requests per minute.",
        )
