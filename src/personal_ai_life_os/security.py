"""Password hashing and signed bearer-token helpers."""

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import HashVerificationError, UnknownHashError

from personal_ai_life_os.config import Settings

password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password, password_hash)
    except (UnknownHashError, HashVerificationError, ValueError):
        return False


def create_access_token(user_id: str, config: Settings) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(hours=config.access_token_ttl_hours),
        "iss": "personal-ai-life-os",
        "aud": "personal-ai-life-os-api",
        "typ": "access",
    }
    return jwt.encode(claims, config.access_token_secret, algorithm="HS256")


def decode_access_token(token: str, config: Settings) -> str | None:
    try:
        claims = jwt.decode(
            token,
            config.access_token_secret,
            algorithms=["HS256"],
            audience="personal-ai-life-os-api",
            issuer="personal-ai-life-os",
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
    except jwt.PyJWTError:
        return None
    if claims.get("typ") != "access":
        return None
    subject = claims.get("sub")
    return subject if isinstance(subject, str) else None
