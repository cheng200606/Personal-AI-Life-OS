"""Model provider registry and per-provider consent endpoints."""

from fastapi import APIRouter, HTTPException, Request

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import ModelConsentRequest, ModelConsentResponse
from personal_ai_life_os.config import Settings
from personal_ai_life_os.services.jobs import cancel_model_jobs_for_owner
from personal_ai_life_os.services.model_consent import consent_state, set_consent
from personal_ai_life_os.services.model_providers import (
    ModelProviderError,
    list_model_providers,
    resolve_model_provider,
)

router = APIRouter(prefix="/model-providers", tags=["model-providers"])


def _provider_or_error(config: Settings, provider_id: str | None, model: str | None):
    try:
        return resolve_model_provider(config, provider_id, model)
    except ModelProviderError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error


@router.get("")
def list_providers(request: Request, user: CurrentUserDep, session: SessionDep) -> list[dict]:
    config: Settings = request.app.state.settings
    try:
        providers = list_model_providers(config)
    except ModelProviderError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    return [
        {
            **provider.public(),
            "max_cost_per_call_usd": str(config.model_max_cost_per_call_usd),
            "consent": consent_state(session, user, provider),
        }
        for provider in providers
    ]


@router.put("/consent", response_model=ModelConsentResponse)
def update_consent(
    payload: ModelConsentRequest,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
) -> dict:
    config: Settings = request.app.state.settings
    provider = _provider_or_error(config, payload.provider_id, None)
    try:
        record = set_consent(
            session,
            user,
            provider,
            enabled=payload.enabled,
            disclosure_version=payload.disclosure_version,
        )
    except ModelProviderError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    if not payload.enabled:
        cancel_model_jobs_for_owner(session, user.id, provider_id=provider.id)
        session.commit()
    return {
        "provider_id": record.provider_id,
        "disclosure_version": record.disclosure_version,
        "granted_at": record.granted_at,
        "revoked_at": record.revoked_at,
    }
