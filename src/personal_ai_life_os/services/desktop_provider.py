"""Settings for the bundled desktop OpenAI-compatible provider."""

import hashlib
import json
import logging
import os
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, Field, SecretStr, field_validator
from win32ctypes.pywin32 import win32cred

from personal_ai_life_os.config import Settings

logger = logging.getLogger(__name__)
PROVIDER_ID = "desktop"


def _endpoint(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or (parsed.scheme != "https" and not (local and parsed.scheme == "http"))):
        raise ValueError("Use an HTTPS URL, or an HTTP loopback address for a local model.")
    return value


class DesktopProviderSettings(BaseModel):
    base_url: str = Field(max_length=512)
    model: str = Field(min_length=1, max_length=160)
    input_cost_per_million_usd: Decimal = Field(gt=0, le=10_000)
    output_cost_per_million_usd: Decimal = Field(gt=0, le=10_000)
    monthly_budget_usd: Decimal = Field(ge=0, le=100_000)
    max_cost_per_call_usd: Decimal = Field(gt=0, le=100)
    privacy_url: str = Field(max_length=512)
    retention: str = Field(min_length=20, max_length=1000)
    api_key: SecretStr | None = Field(default=None, max_length=1024)

    @field_validator("base_url", "privacy_url")
    @classmethod
    def endpoint(cls, value: str) -> str:
        return _endpoint(value)


class DesktopProviderStore:
    def __init__(self, config: Settings):
        self.config = config
        self.path = config.data_dir / "provider.json"
        self.scope = hashlib.sha256(os.path.normcase(str(config.data_dir)).encode()).hexdigest()[:16]
        self.lock = RLock()

    def _target(self, identity: str) -> str:
        return f"PersonalAILifeOS/{self.scope}/model/{identity}"

    def _read_key(self, identity: str | None) -> str:
        if not identity:
            return ""
        try:
            result = win32cred.CredRead(self._target(identity), win32cred.CRED_TYPE_GENERIC)
        except OSError as error:
            if getattr(error, "winerror", None) != 1168:
                raise
            return ""
        secret = result["CredentialBlob"]
        return secret.decode("utf-16-le") if isinstance(secret, bytes) else secret

    def _delete_key(self, identity: str | None):
        if identity:
            try:
                win32cred.CredDelete(self._target(identity), win32cred.CRED_TYPE_GENERIC)
            except OSError as error:
                if getattr(error, "winerror", None) != 1168:
                    logger.warning("An obsolete model credential could not be removed.")

    def _record(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else {}

    def _activate(self, record: dict, key: str = ""):
        if not record or (not key and urlsplit(record["base_url"]).hostname not in {"localhost", "127.0.0.1", "::1"}):
            self.config.model_providers = None
            return
        self.config.model_monthly_budget_usd = Decimal(record["monthly_budget_usd"])
        self.config.model_max_cost_per_call_usd = Decimal(record["max_cost_per_call_usd"])
        self.config.model_providers = json.dumps({PROVIDER_ID: {
            **record,
            "api_key": key,
            "data_sent": "Selected and authorized record excerpts, used to generate drafts or a requested review.",
        }})

    def load(self):
        with self.lock:
            try:
                record = self._record()
                self._activate(record, self._read_key(record.get("credential_id")))
            except (ValueError, KeyError, OSError):
                logger.warning("Desktop provider settings could not be loaded.")
                self._activate({})

    def public(self) -> dict:
        with self.lock:
            record = self._record()
            if not record:
                return {}
            return {key: value for key, value in record.items() if key != "credential_id"} | {
                "key_configured": bool(self._read_key(record.get("credential_id"))),
            }

    def save(self, settings: DesktopProviderSettings) -> dict:
        with self.lock:
            previous = self._record()
            old_identity = previous.get("credential_id")
            key = settings.api_key.get_secret_value().strip() if settings.api_key else ""
            identity = uuid4().hex if key else old_identity
            if previous.get("base_url") != settings.base_url and not key:
                identity = None
            current_key = key or self._read_key(identity)
            if not current_key and urlsplit(settings.base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
                raise ValueError("Enter an API key for this provider address.")
            record = settings.model_dump(mode="json", exclude={"api_key"}) | {
                "credential_id": identity,
                "disclosure_version": "desktop-" + uuid4().hex,
            }
            if key:
                win32cred.CredWrite({
                    "Type": win32cred.CRED_TYPE_GENERIC, "TargetName": self._target(identity),
                    "CredentialBlob": key, "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
                    "UserName": "Personal AI Life OS",
                })
            temporary_path = None
            try:
                with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as temporary:
                    temporary_path = Path(temporary.name)
                    json.dump(record, temporary, ensure_ascii=False)
                temporary_path.replace(self.path)
            except OSError:
                if key:
                    self._delete_key(identity)
                raise
            finally:
                if temporary_path:
                    temporary_path.unlink(missing_ok=True)
            self._activate(record, current_key)
            if old_identity != identity:
                self._delete_key(old_identity)
            return self.public()

    def clear(self):
        with self.lock:
            previous = self._record()
            self.path.unlink(missing_ok=True)
            self._activate({})
            self._delete_key(previous.get("credential_id"))
