from fastapi import Header, HTTPException, status

from . import settings


def verify_api_key(x_api_key: str | None = Header(default=None)):
    if not settings.REQUIRE_API_KEY:
        return
    if not settings.API_KEY or x_api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
