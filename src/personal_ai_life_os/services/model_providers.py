"""Environment-backed OpenAI-compatible provider and model registry."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any
from urllib.parse import urlparse

from personal_ai_life_os.config import Settings

DEFAULT_PROVIDER_ID = "default"
DEFAULT_DISCLOSURE_DATA = (
    "Selected timeline item dates, titles, source-item IDs, and text for a requested review."
)
DEFAULT_RETENTION = "Review the configured provider's current privacy and retention terms before consenting."


class ModelProviderError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ModelProvider:
    id: str
    base_url: str
    api_key: str
    model: str
    models: tuple[str, ...]
    input_cost_per_million_usd: Decimal
    output_cost_per_million_usd: Decimal
    disclosure_version: str
    data_sent: str
    retention: str
    privacy_url: str | None
    max_output_tokens: int
    local: bool
    trust_env: bool = False
    builtin: bool = False

    @property
    def chat_completions_url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"

    @property
    def rates_configured(self) -> bool:
        return self.input_cost_per_million_usd > 0 and self.output_cost_per_million_usd > 0

    @property
    def disclosure_ready(self) -> bool:
        return bool(
            self.data_sent.strip()
            and len(self.retention.strip()) >= 20
            and (self.builtin or self.local or self.privacy_url)
        )

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "model": self.model,
            "models": list(self.models),
            "input_cost_per_million_usd": str(self.input_cost_per_million_usd),
            "output_cost_per_million_usd": str(self.output_cost_per_million_usd),
            "disclosure_version": self.disclosure_version,
            "data_sent": self.data_sent,
            "retention": self.retention,
            "privacy_url": self.privacy_url,
            "max_cost_per_call_usd": None,
            "local": self.local,
            "builtin": self.builtin,
            "available": bool(self.api_key or self.local) and self.rates_configured and self.disclosure_ready,
        }


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (TypeError, ValueError):
        return Decimal(0)


def _local_endpoint(base_url: str, declared_local: bool) -> bool:
    host = urlparse(base_url).hostname or ""
    local_host = host in {"localhost", "127.0.0.1", "::1"}
    if declared_local and not local_host:
        raise ModelProviderError(
            "model_provider_unconfigured",
            "A local provider must use a loopback base URL.",
        )
    return declared_local or local_host


def _default_provider(config: Settings) -> ModelProvider | None:
    if config.model_provider != "openai":
        return None
    return ModelProvider(
        id=DEFAULT_PROVIDER_ID,
        base_url=config.openai_base_url.strip().rstrip("/") or "https://api.openai.com/v1",
        api_key=config.openai_api_key or "",
        model=config.openai_model,
        models=(config.openai_model,),
        input_cost_per_million_usd=config.model_input_cost_per_million_usd,
        output_cost_per_million_usd=config.model_output_cost_per_million_usd,
        disclosure_version=config.model_disclosure_version,
        data_sent=config.model_disclosure_data,
        retention=config.model_disclosure_retention,
        privacy_url=config.model_privacy_url,
        max_output_tokens=config.model_max_output_tokens,
        local=_local_endpoint(config.openai_base_url, False),
        trust_env=config.model_trust_env,
        builtin=True,
    )


def list_model_providers(config: Settings) -> list[ModelProvider]:
    providers: list[ModelProvider] = []
    default = _default_provider(config)
    if default is not None:
        providers.append(default)
    if not config.model_providers:
        return providers
    try:
        entries = json.loads(config.model_providers)
    except json.JSONDecodeError as error:
        raise ModelProviderError(
            "model_provider_unconfigured",
            "MODEL_PROVIDERS must be valid JSON.",
        ) from error
    if not isinstance(entries, dict):
        raise ModelProviderError("model_provider_unconfigured", "MODEL_PROVIDERS must be a JSON object.")
    for provider_id, raw in entries.items():
        if provider_id == DEFAULT_PROVIDER_ID:
            raise ModelProviderError(
                "model_provider_unconfigured",
                "The provider ID 'default' is reserved for the built-in configuration.",
            )
        if not isinstance(provider_id, str) or not provider_id.strip() or len(provider_id) > 80:
            raise ModelProviderError("model_provider_unconfigured", "Provider IDs must be 1–80 characters.")
        if not isinstance(raw, dict):
            raise ModelProviderError("model_provider_unconfigured", f"Provider {provider_id} must be an object.")
        base_url = str(raw.get("base_url") or "").strip().rstrip("/")
        model = str(raw.get("model") or "").strip()
        api_key = str(raw.get("api_key") or "")
        if not base_url or not model:
            raise ModelProviderError(
                "model_provider_unconfigured",
                f"Provider {provider_id} requires base_url and model.",
            )
        local = _local_endpoint(base_url, bool(raw.get("local", False)))
        if not api_key and not local:
            raise ModelProviderError(
                "model_provider_unconfigured",
                f"Provider {provider_id} requires an API key unless it is a loopback local provider.",
            )
        raw_models = raw.get("models", [model])
        if not isinstance(raw_models, list) or not raw_models:
            raise ModelProviderError(
                "model_provider_unconfigured",
                f"Provider {provider_id} models must be a non-empty list.",
            )
        models = tuple(dict.fromkeys(str(value).strip() for value in raw_models if str(value).strip()))
        if model not in models:
            raise ModelProviderError(
                "model_provider_unconfigured",
                f"Provider {provider_id} default model must appear in its models list.",
            )
        providers.append(
            ModelProvider(
                id=provider_id,
                base_url=base_url,
                api_key=api_key,
                model=model,
                models=models,
                input_cost_per_million_usd=_decimal(raw.get("input_cost_per_million_usd")),
                output_cost_per_million_usd=_decimal(raw.get("output_cost_per_million_usd")),
                disclosure_version=str(raw.get("disclosure_version") or "openai-compatible-v1"),
                data_sent=str(raw.get("data_sent") or DEFAULT_DISCLOSURE_DATA),
                retention=str(raw.get("retention") or DEFAULT_RETENTION),
                privacy_url=str(raw.get("privacy_url") or "") or None,
                max_output_tokens=int(raw.get("max_output_tokens") or config.model_max_output_tokens),
                local=local,
                trust_env=bool(raw.get("trust_env", False)),
            )
        )
    return providers


def resolve_model_provider(
    config: Settings,
    provider_id: str | None = None,
    model: str | None = None,
) -> ModelProvider:
    providers = list_model_providers(config)
    selected_id = provider_id or DEFAULT_PROVIDER_ID
    provider = next((entry for entry in providers if entry.id == selected_id), None)
    if provider is None:
        raise ModelProviderError(
            "model_provider_unavailable",
            "The requested model provider is not configured.",
        )
    selected_model = model or provider.model
    if selected_model not in provider.models:
        raise ModelProviderError(
            "model_unavailable",
            "The requested model is not registered for this provider.",
        )
    if selected_model != provider.model:
        provider = replace(provider, model=selected_model)
    return provider


def provider_cost(provider: ModelProvider, input_tokens: int, output_tokens: int) -> Decimal | None:
    if not provider.rates_configured:
        return None
    return (
        Decimal(input_tokens) * provider.input_cost_per_million_usd
        + Decimal(output_tokens) * provider.output_cost_per_million_usd
    ) / Decimal(1_000_000)
