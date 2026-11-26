"""Per-owner, per-provider model consent with legacy default-provider support."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_ai_life_os.models import ModelConsent, User
from personal_ai_life_os.services.model_providers import (
    DEFAULT_PROVIDER_ID,
    ModelProvider,
    ModelProviderError,
)


def consent_record(session: Session, owner_id: str, provider_id: str) -> ModelConsent | None:
    return session.scalar(
        select(ModelConsent).where(
            ModelConsent.owner_id == owner_id,
            ModelConsent.provider_id == provider_id,
        )
    )


def has_consent(session: Session, user: User, provider: ModelProvider) -> bool:
    record = consent_record(session, user.id, provider.id)
    if record is not None:
        return bool(
            record.granted_at
            and record.revoked_at is None
            and record.disclosure_version == provider.disclosure_version
        )
    return bool(
        provider.id == DEFAULT_PROVIDER_ID
        and provider.builtin
        and user.ai_consent_at
        and user.ai_consent_provider in {DEFAULT_PROVIDER_ID, "openai"}
        and user.ai_consent_disclosure_version == provider.disclosure_version
    )


def consent_state(session: Session, user: User, provider: ModelProvider) -> dict:
    record = consent_record(session, user.id, provider.id)
    return {
        "provider_id": provider.id,
        "disclosure_version": provider.disclosure_version,
        "consented": has_consent(session, user, provider),
        "granted_at": record.granted_at if record else (
            user.ai_consent_at if provider.id == DEFAULT_PROVIDER_ID and has_consent(session, user, provider) else None
        ),
        "revoked_at": record.revoked_at if record else None,
    }


def set_consent(
    session: Session,
    user: User,
    provider: ModelProvider,
    *,
    enabled: bool,
    disclosure_version: str | None,
) -> ModelConsent:
    if enabled:
        if not provider.api_key and not provider.local:
            raise ModelProviderError("model_provider_unavailable", "The provider has no configured credential.")
        if not provider.rates_configured:
            raise ModelProviderError("model_cost_unconfigured", "Configure current provider pricing before consenting.")
        if not provider.disclosure_ready:
            raise ModelProviderError(
                "model_disclosure_incomplete",
                "Configure the provider privacy URL, data disclosure, and retention text before consenting.",
            )
        if disclosure_version != provider.disclosure_version:
            raise ModelProviderError(
                "disclosure_outdated",
                "Review the current provider disclosure before enabling external processing.",
            )
    record = consent_record(session, user.id, provider.id)
    now = datetime.now(UTC)
    if record is None:
        record = ModelConsent(
            owner_id=user.id,
            provider_id=provider.id,
            disclosure_version=provider.disclosure_version,
            granted_at=now if enabled else None,
            revoked_at=None if enabled else now,
        )
        session.add(record)
    else:
        record.disclosure_version = provider.disclosure_version
        if enabled:
            record.granted_at = now
            record.revoked_at = None
        else:
            record.revoked_at = now
    if provider.id == DEFAULT_PROVIDER_ID and provider.builtin:
        user.ai_consent_at = now if enabled else None
        user.ai_consent_provider = "openai" if enabled else None
        user.ai_consent_disclosure_version = provider.disclosure_version if enabled else None
    session.commit()
    session.refresh(record)
    return record
