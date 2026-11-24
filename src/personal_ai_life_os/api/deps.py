"""Shared authenticated dependencies."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from personal_ai_life_os.config import Settings
from personal_ai_life_os.db import get_session
from personal_ai_life_os.models import User
from personal_ai_life_os.security import decode_access_token

optional_bearer = HTTPBearer(auto_error=False)
SessionDep = Annotated[Session, Depends(get_session)]


def get_current_user(
    request: Request,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(optional_bearer)],
) -> User:
    return _authenticated_user(request, session, credentials, allow_deleting=False)


def get_user_for_account_delete(
    request: Request,
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(optional_bearer)],
) -> User:
    return _authenticated_user(request, session, credentials, allow_deleting=True)


def _authenticated_user(
    request: Request,
    session: SessionDep,
    credentials: HTTPAuthorizationCredentials | None,
    *,
    allow_deleting: bool,
) -> User:
    config: Settings = request.app.state.settings
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "auth_required", "message": "Sign in to access this resource."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = decode_access_token(credentials.credentials, config)
    user = session.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_access_token", "message": "The access token is invalid or expired."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.deletion_requested_at is not None and not allow_deleting:
        raise HTTPException(
            status_code=410,
            detail={"code": "account_deletion_pending", "message": "Account access is disabled while data cleanup completes."},
        )
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]
DeletionUserDep = Annotated[User, Depends(get_user_for_account_delete)]
