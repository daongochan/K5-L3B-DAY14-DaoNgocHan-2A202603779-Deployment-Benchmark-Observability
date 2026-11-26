"""
API Key authentication (tiêu chí 6).
"""
import secrets

from fastapi import HTTPException, Security
from fastapi.security.api_key import APIKeyHeader

from app.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """Kiểm tra header X-API-Key; thiếu hoặc sai đều trả HTTP 401."""
    expected_key = settings.agent_api_key
    if not expected_key or not api_key or not secrets.compare_digest(api_key, expected_key):
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Provide header X-API-Key.",
        )
    return api_key
