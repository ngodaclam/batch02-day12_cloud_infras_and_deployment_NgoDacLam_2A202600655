"""
API Key authentication module.
Verifies requests using X-API-Key header.
"""

from fastapi import Header, HTTPException, status

from .config import settings


def verify_api_key(x_api_key: str = Header(..., description="API Key for authentication")):
    """
    Verify the API key from request header.
    Returns a user_id derived from the key if valid.
    Raises 401 if invalid.
    """
    if x_api_key != settings.AGENT_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )
    # In production, you'd look up the user from a database
    return "authenticated-user"
