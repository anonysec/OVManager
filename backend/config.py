import os
import secrets
from pydantic_settings import BaseSettings
from typing import Optional


def _validate_jwt_secret(v: str) -> str:
    """Enforce minimum entropy on JWT secret at startup."""
    # Must be at least 32 chars (256 bits for HS256) and not a placeholder
    if len(v) < 32:
        raise ValueError("JWT_SECRET_KEY must be at least 32 characters (256 bits for HS256)")
    # Reject common placeholders
    placeholders = {"changeme", "secret", "changeme123", "supersecret", "dev", "test", "your-secret"}
    if v.lower().strip() in placeholders:
        raise ValueError("JWT_SECRET_KEY cannot be a default/placeholder value")
    # Reject low-entropy secrets (e.g. all same char, or dictionary word)
    if len(set(v)) < 8:
        raise ValueError("JWT_SECRET_KEY has low character diversity; use a cryptographically random secret")
    return v


class Setting(BaseSettings):
    ADMIN_USERNAME: str
    ADMIN_PASSWORD: str
    URLPATH: str = "dashboard"
    VITE_URLPATH: str = "dashboard"
    HOST: str = "0.0.0.0"
    PORT: int = 9000
    DEBUG: str = "WARNING"
    DOC: bool = False
    SSL_KEYFILE: Optional[str] = None
    SSL_CERTFILE: Optional[str] = None
    JWT_SECRET_KEY: str
    JWT_ACCESS_TOKEN_EXPIRES: int = 86400  # in seconds
    SUBSCRIPTION_URL_PREFIX: Optional[str] = None
    SUBSCRIPTION_PATH: str = "sub"

    model_config = {"env_file": os.path.join(os.path.dirname(__file__), "..", ".env")}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Validate JWT secret immediately on instantiation
        _validate_jwt_secret(self.JWT_SECRET_KEY)


config = Setting()
