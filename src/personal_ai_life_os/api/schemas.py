"""Stable request and response schemas for the versioned API."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def validate_email(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 320 or normalized.count("@") != 1:
        raise ValueError("Enter a valid email address.")
    local, domain = normalized.split("@")
    if not local or "." not in domain or any(character.isspace() for character in normalized):
        raise ValueError("Enter a valid email address.")
    return normalized


class RegisterRequest(BaseModel):
    email: str = Field(min_length=5, max_length=320)
    password: str = Field(min_length=12, max_length=256)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    invite_code: str | None = Field(default=None, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return validate_email(value)


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return validate_email(value)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: str
    timezone: str
    ai_consent_at: datetime | None
    ai_consent_provider: str | None
    ai_consent_disclosure_version: str | None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserResponse


class SourceCreateRequest(BaseModel):
    kind: Literal["memory_markdown", "chatgpt_export", "photo"]
    name: str = Field(min_length=1, max_length=240)
    selected_scope: dict[str, Any] = Field(default_factory=dict)
    consent_version: str = Field(default="source-consent-v1", min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_source_scope(self) -> "SourceCreateRequest":
        if self.kind == "chatgpt_export":
            conversation_ids = self.selected_scope.get("conversation_ids")
            if (
                not isinstance(conversation_ids, list)
                or not conversation_ids
                or len(conversation_ids) > 1000
                or not all(isinstance(item, str) and item.strip() for item in conversation_ids)
            ):
                raise ValueError("Choose between 1 and 1000 conversation IDs in the local preview.")
        return self


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    kind: str
    name: str
    status: str
    consent_version: str
    selected_scope: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    last_sync_at: datetime | None


class SourceStatusRequest(BaseModel):
    status: Literal["active", "paused"]


class SourceScopeRequest(BaseModel):
    selected_scope: dict[str, Any]
    consent_version: str = Field(default="source-consent-v1", min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_chat_selection(self) -> "SourceScopeRequest":
        if "conversation_ids" in self.selected_scope:
            conversation_ids = self.selected_scope["conversation_ids"]
            if (
                not isinstance(conversation_ids, list)
                or not conversation_ids
                or len(conversation_ids) > 1000
                or not all(isinstance(item, str) and item.strip() for item in conversation_ids)
            ):
                raise ValueError("Choose between 1 and 1000 conversation IDs in the local preview.")
        return self


class SyncRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    source_id: str
    status: str
    parser_version: str | None
    items_seen: int
    items_created: int
    items_duplicate: int
    items_failed: int
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


class ImportResultResponse(BaseModel):
    sync_run: SyncRunResponse
    items: list["SourceItemResponse"]
    job_ids: list[str] = Field(default_factory=list)


class BackgroundJobResponse(BaseModel):
    id: str
    kind: str
    status: str
    attempt_count: int
    max_attempts: int
    error_code: str | None
    result_json: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class SourceItemResponse(BaseModel):
    id: str
    source_id: str
    sync_run_id: str
    kind: str
    title: str
    content_text: str
    occurred_at: datetime | None
    source_timezone: str | None
    source_locator: dict[str, Any]
    metadata: dict[str, Any]
    created_at: datetime


class TimelineResponse(BaseModel):
    items: list[SourceItemResponse]
    total: int
    next_cursor: str | None = None


class ReviewGenerateRequest(BaseModel):
    period_start: date
    period_end: date
    use_external_model: bool = False

    @model_validator(mode="after")
    def validate_period(self) -> "ReviewGenerateRequest":
        if self.period_end <= self.period_start:
            raise ValueError("period_end must be after period_start.")
        if (self.period_end - self.period_start).days > 31:
            raise ValueError("A review period cannot exceed 31 days.")
        return self


class ReviewUpdateRequest(BaseModel):
    final_text: str = Field(min_length=1, max_length=50000)


class ReviewSuggestionUpdateRequest(BaseModel):
    text: str | None = Field(default=None, max_length=1200)
    status: Literal["pending", "dismissed"] | None = None

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Suggestion text cannot be empty.")
        return normalized

    @model_validator(mode="after")
    def require_change(self) -> "ReviewSuggestionUpdateRequest":
        if self.text is None and self.status is None:
            raise ValueError("Provide suggestion text or status.")
        return self


class ReviewResponse(BaseModel):
    id: str
    period_start: datetime
    period_end: datetime
    status: str
    draft: dict[str, Any]
    final_text: str | None
    source_items: list[SourceItemResponse]
    created_at: datetime
    updated_at: datetime


class AIPreferenceRequest(BaseModel):
    enabled: bool
    disclosure_version: str | None = None


class PhotoDescriptionConfirmRequest(BaseModel):
    description: str = Field(min_length=1, max_length=10000)


class ReminderCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=10000)
    due_at: datetime | None = None
    source_item_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("due_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("due_at must include a timezone offset.")
        return value


class ReminderStatusRequest(BaseModel):
    status: Literal["pending", "completed", "snoozed", "cancelled"]


class ReminderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    notes: str | None
    due_at: datetime | None
    status: str
    created_at: datetime
    updated_at: datetime


class SearchTimelineResult(BaseModel):
    id: str
    source_id: str
    source_name: str
    title: str
    snippet: str
    occurred_at: datetime | None
    kind: str


class SearchReviewResult(BaseModel):
    id: str
    period_start: datetime
    period_end: datetime
    status: str
    snippet: str
    updated_at: datetime


class SearchReminderResult(BaseModel):
    id: str
    title: str
    snippet: str
    due_at: datetime | None
    status: str


class SearchTimelineGroup(BaseModel):
    total: int
    results: list[SearchTimelineResult]


class SearchReviewGroup(BaseModel):
    total: int
    results: list[SearchReviewResult]


class SearchReminderGroup(BaseModel):
    total: int
    results: list[SearchReminderResult]


class SearchResponse(BaseModel):
    query: str
    timeline: SearchTimelineGroup
    reviews: SearchReviewGroup
    reminders: SearchReminderGroup
