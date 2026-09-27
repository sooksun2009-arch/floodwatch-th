"""Password hashing and JWT issuing.

bcrypt is used directly rather than through passlib — passlib 1.7.4 reads
bcrypt.__about__, which bcrypt 4.1+ removed, and the resulting warning/error
is a known trap.
"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import settings

# bcrypt refuses inputs longer than 72 bytes; truncating keeps long passwords
# (and multi-byte Thai passphrases) from raising at hash time.
_BCRYPT_MAX = 72


def _prepare(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prepare(password), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_expire_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
