"""Account registration, login, and explicit model consent."""

import hmac
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    AIPreferenceRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from personal_ai_life_os.config import Settings
from personal_ai_life_os.models import User
from personal_ai_life_os.security import create_access_token, hash_password, verify_password
from personal_ai_life_os.services.model_usage import model_rates_configured

router = APIRouter(prefix="/auth", tags=["authentication"])


def _check_registration(config: Settings, invite_code: str | None) -> None:
    if config.registration_mode == "closed":
        raise HTTPException(
            status_code=403,
            detail={"code": "registration_closed", "message": "Account registration is closed."},
        )
    if config.registration_mode == "invitation":
        expected = config.signup_invite_code or ""
        if not invite_code or not hmac.compare_digest(invite_code, expected):
            raise HTTPException(
                status_code=403,
                detail={"code": "invalid_invitation", "message": "A valid invitation code is required."},
            )


def _token_response(user: User, config: Settings) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user.id, config),
        expires_in=config.access_token_ttl_hours * 3600,
        user=UserResponse.model_validate(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    request: Request,
    session: SessionDep,
) -> TokenResponse:
    config: Settings = request.app.state.settings
    _check_registration(config, payload.invite_code)
    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_timezone", "message": "Use a valid IANA timezone name."},
        ) from error
    if session.scalar(select(User.id).where(User.email == payload.email)):
        raise HTTPException(
            status_code=409,
            detail={"code": "account_exists", "message": "An account with this email already exists."},
        )
    user = User(email=payload.email, password_hash=hash_password(payload.password), timezone=payload.timezone)
    session.add(user)
    try:
        session.commit()
    except Exception:
        session.rollback()
        if session.scalar(select(User.id).where(User.email == payload.email)):
            raise HTTPException(
                status_code=409,
                detail={"code": "account_exists", "message": "An account with this email already exists."},
            )
        raise
    session.refresh(user)
    return _token_response(user, config)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, session: SessionDep) -> TokenResponse:
    config: Settings = request.app.state.settings
    user = session.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_credentials", "message": "Email or password is incorrect."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _token_response(user, config)


@router.get("/me", response_model=UserResponse)
def get_me(user: CurrentUserDep) -> User:
    return user


@router.get("/model-disclosure")
def get_model_disclosure(request: Request) -> dict[str, str | bool | None]:
    config: Settings = request.app.state.settings
    available = (
        config.model_provider == "openai"
        and bool(config.openai_api_key)
        and model_rates_configured(config)
    )
    return {
        "available": available,
        "provider": config.model_provider if available else None,
        "model": config.openai_model if available else None,
        "disclosure_version": config.model_disclosure_version if available else None,
        "data_sent": config.model_disclosure_data,
        "retention": config.model_disclosure_retention,
        "privacy_url": config.model_privacy_url,
        "input_cost_per_million_usd": str(config.model_input_cost_per_million_usd) if available else None,
        "output_cost_per_million_usd": str(config.model_output_cost_per_million_usd) if available else None,
        "max_cost_per_call_usd": str(config.model_max_cost_per_call_usd) if available else None,
    }


@router.put("/ai-consent", response_model=UserResponse)
def set_ai_consent(
    payload: AIPreferenceRequest,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
) -> User:
    config: Settings = request.app.state.settings
    if payload.enabled:
        if config.model_provider == "none" or not config.openai_api_key or not model_rates_configured(config):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "model_provider_unavailable",
                    "message": "The external model provider, privacy disclosure, and current pricing must be configured. Template reviews remain available.",
                },
            )
        if payload.disclosure_version != config.model_disclosure_version:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "disclosure_outdated",
                    "message": "Review the current model data disclosure before enabling external processing.",
                },
            )
        user.ai_consent_at = datetime.now(UTC)
        user.ai_consent_provider = config.model_provider
        user.ai_consent_disclosure_version = config.model_disclosure_version
    else:
        user.ai_consent_at = None
        user.ai_consent_provider = None
        user.ai_consent_disclosure_version = None
    session.commit()
    session.refresh(user)
    return user
