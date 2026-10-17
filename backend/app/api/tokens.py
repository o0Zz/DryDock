from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import generate_token, get_current_user, hash_token
from app.models.api_token import ApiToken
from app.models.user import User
from app.schemas.api_token import ApiTokenCreate, ApiTokenCreated, ApiTokenRead

# Each user manages their own tokens. A token has the rights of its user.
router = APIRouter(prefix="/api/tokens", tags=["tokens"])


@router.get("", response_model=list[ApiTokenRead])
def list_tokens(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[ApiToken]:
    query = select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at)
    return list(db.scalars(query))


@router.post("", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED)
def create_token(
    body: ApiTokenCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> ApiTokenCreated:
    token = generate_token()
    api_token = ApiToken(
        user_id=user.id, name=body.name.strip(), token_hash=hash_token(token), prefix=token[:10]
    )
    db.add(api_token)
    db.commit()
    db.refresh(api_token)
    return ApiTokenCreated(**ApiTokenRead.model_validate(api_token).model_dump(), token=token)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_token(
    token_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> None:
    api_token = db.get(ApiToken, token_id)
    if api_token is None or api_token.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    db.delete(api_token)
    db.commit()
