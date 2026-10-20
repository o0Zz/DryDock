from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import DEFAULT_ADMIN_PASSWORD
from app.core.database import get_db
from app.core.security import (
    SESSION_USER_KEY,
    authenticate,
    get_authenticated_user,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.schemas.user import LoginRequest, PasswordChange, UserRead

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserRead)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> User:
    user = authenticate(db, body.username, body.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password"
        )
    # Catches installs that created the admin before this flag existed.
    if body.password == DEFAULT_ADMIN_PASSWORD and not user.must_change_password:
        user.must_change_password = True
        db.commit()
    request.session[SESSION_USER_KEY] = user.id
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request) -> None:
    request.session.clear()


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_authenticated_user)) -> User:
    return user


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChange,
    user: User = Depends(get_authenticated_user),
    db: Session = Depends(get_db),
) -> None:
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect"
        )
    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The new password must differ from the current one",
        )
    user.hashed_password = hash_password(body.new_password)
    user.must_change_password = False
    db.commit()
