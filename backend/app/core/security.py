import hashlib
import secrets
from datetime import UTC, timedelta

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db, utcnow
from app.models.api_token import ApiToken
from app.models.user import User

SESSION_USER_KEY = "user_id"
# Marks DryDock tokens, so a leaked one is easy to recognise (and to grep for).
TOKEN_PREFIX = "ddt_"
# last_used_at is only rewritten this often, so a busy script does not write on every call.
TOKEN_TOUCH_INTERVAL = timedelta(minutes=1)


def _encode(password: str) -> bytes:
    # bcrypt only considers the first 72 bytes and raises on longer input, so truncate.
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_encode(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_encode(password), hashed.encode("utf-8"))
    except ValueError:
        return False


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_user(token: str, db: Session) -> User:
    api_token = db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(token)))
    user = db.get(User, api_token.user_id) if api_token else None
    if api_token is None or user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")
    now = utcnow()
    last_used = api_token.last_used_at
    # SQLite hands datetimes back without their timezone.
    if last_used is None or now - last_used.replace(tzinfo=UTC) > TOKEN_TOUCH_INTERVAL:
        api_token.last_used_at = now
        db.commit()
    return user


def get_authenticated_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The user of the session cookie, or of an `Authorization: Bearer <token>` header.

    Also returns a user who still has to change the default password; only the
    routes that let them do so use this directly.
    """
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return _token_user(token.strip(), db)
    user_id = request.session.get(SESSION_USER_KEY)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


PASSWORD_CHANGE_REQUIRED = "Change the default password first"


def get_current_user(user: User = Depends(get_authenticated_user)) -> User:
    """The signed-in user, refused while they still use the default password."""
    if user.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=PASSWORD_CHANGE_REQUIRED)
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Administrator privileges required"
        )
    return user
