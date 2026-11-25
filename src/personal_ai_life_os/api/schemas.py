"""Stable request and response schemas for the versioned API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

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
    kind: Literal["memory_markdown", "chatgpt_export", "chat_export", "document", "photo"]
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
    cloud_consent_at: datetime | None
    cloud_consent_version: str | None


class SourceCloudConsentRequest(BaseModel):
    enabled: bool
    consent_version: str = Field(default="graph-cloud-v1", min_length=1, max_length=80)


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


class ReviewScheduleUpdateRequest(BaseModel):
    enabled: bool
    weekday: int = Field(ge=0, le=6)
    local_hour: int = Field(ge=0, le=23)
    local_minute: int = Field(ge=0, le=59)
    timezone: str = Field(min_length=1, max_length=64)
    use_external_model: bool = False

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception as error:
            raise ValueError("Enter a valid IANA timezone.") from error
        return value


class ReviewScheduleResponse(BaseModel):
    enabled: bool
    weekday: int
    local_hour: int
    local_minute: int
    timezone: str
    use_external_model: bool
    last_run_at: datetime | None
    next_run_at: datetime | None
    last_review_id: str | None


class ExtractionRequest(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=50)
    provider: str | None = Field(default=None, max_length=64)


class ExtractionRunResponse(BaseModel):
    id: str
    status: str
    provider: str
    model: str
    prompt_version: str
    item_count: int
    entity_count: int
    relation_count: int
    review_count: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal | None
    latency_ms: int
    error_code: str | None
    budget_used_usd: Decimal
    budget_limit_usd: Decimal
    budget_warning: bool
    created_at: datetime
    completed_at: datetime | None


class GraphEvidenceResponse(BaseModel):
    id: str
    quote: str
    confidence: float
    availability: str
    source_id: str
    source_item_id: str
    locator: dict[str, Any]
    created_at: datetime


class GraphEntityResponse(BaseModel):
    id: str
    entity_type: str
    name: str
    summary: str | None
    confidence: float
    status: str
    evidence: list[GraphEvidenceResponse]
    created_at: datetime
    updated_at: datetime


class GraphEntityListResponse(BaseModel):
    total: int
    items: list[GraphEntityResponse]


class GraphRelationResponse(BaseModel):
    id: str
    from_entity_id: str
    to_entity_id: str
    relation_type: str
    confidence: float
    status: str
    evidence: list[GraphEvidenceResponse]
    created_at: datetime
    updated_at: datetime


class GraphRelationListResponse(BaseModel):
    total: int
    items: list[GraphRelationResponse]


class GraphReviewUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=500)
    entity_type: str | None = Field(default=None, max_length=64)
    relation_type: str | None = Field(default=None, max_length=64)
    summary: str | None = Field(default=None, max_length=5000)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def require_change(self) -> "GraphReviewUpdateRequest":
        if all(
            value is None
            for value in (
                self.name,
                self.entity_type,
                self.relation_type,
                self.summary,
                self.confidence,
            )
        ):
            raise ValueError("Provide at least one review change.")
        return self


class GraphReviewDecisionRequest(BaseModel):
    action: Literal["approve", "reject"]


class GraphReviewBulkRequest(BaseModel):
    item_ids: list[str] = Field(min_length=1, max_length=200)
    action: Literal["approve", "reject"]


class GraphReviewItemResponse(BaseModel):
    id: str
    kind: str
    payload: dict[str, Any]
    confidence: float
    status: str
    reason: str | None
    extraction_run_id: str | None
    created_at: datetime
    resolved_at: datetime | None


class GraphReviewListResponse(BaseModel):
    total: int
    items: list[GraphReviewItemResponse]


class GraphMergeRequest(BaseModel):
    target_entity_id: str


class GraphMergeResponse(BaseModel):
    id: str
    source_entity_id: str | None
    target_entity_id: str | None
    source_name: str | None
    target_name: str | None
    status: str
    evidence_count: int
    relation_count: int
    created_at: datetime
    undone_at: datetime | None


class GraphMergeListResponse(BaseModel):
    total: int
    items: list[GraphMergeResponse]


class OntologyTypeCreateRequest(BaseModel):
    kind: Literal["entity", "relation"]
    name: str = Field(min_length=2, max_length=64)
    description: str | None = Field(default=None, max_length=2000)


class OntologyTypeStatusRequest(BaseModel):
    status: Literal["approved", "rejected"]


class OntologyTypeResponse(BaseModel):
    id: str
    kind: str
    name: str
    description: str | None
    status: str
    source: str
    created_by: str
    version: int
    created_at: datetime
    updated_at: datetime


class OntologyTypeListResponse(BaseModel):
    total: int
    items: list[OntologyTypeResponse]


class QaScopeRequest(BaseModel):
    source_ids: list[str] = Field(default_factory=list, max_length=50)
    entity_ids: list[str] = Field(default_factory=list, max_length=50)
    start: datetime | None = None
    end: datetime | None = None


class QaThreadCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=240)
    scope: QaScopeRequest = Field(default_factory=QaScopeRequest)


class QaAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    scope: QaScopeRequest | None = None


class QaCitationResponse(BaseModel):
    evidence_id: str
    quote: str
    confidence: float
    availability: str
    source_id: str
    source_name: str
    source_item_id: str
    item_title: str
    occurred_at: str | None
    locator: dict[str, Any]


class QaFactResponse(BaseModel):
    label: str
    detail: str
    basis: Literal["fact", "inference", "uncertain"]
    confidence: float
    entity_id: str | None
    relation_id: str | None
    citation_ids: list[str]


class QaSuggestionResponse(BaseModel):
    label: str
    kind: str
    entity_id: str | None
    source_item_id: str | None


class QaTimelineMatchResponse(BaseModel):
    source_item_id: str
    source_id: str
    source_name: str
    title: str
    snippet: str
    occurred_at: str | None
    kind: str


class QaReviewMatchResponse(BaseModel):
    id: str
    period_start: str
    period_end: str
    status: str
    snippet: str


class QaAnswerResponse(BaseModel):
    status: Literal["answered", "insufficient_evidence"]
    summary: str
    facts: list[QaFactResponse]
    citations: list[QaCitationResponse]
    timeline_matches: list[QaTimelineMatchResponse]
    review_matches: list[QaReviewMatchResponse]
    missing_info: list[str]
    suggestions: list[QaSuggestionResponse]
    confidence: float
    scope: dict[str, Any]
    keywords: list[str]
    intent: str | None
    latency_ms: int
    version: str


class QaMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    answer: QaAnswerResponse | None
    created_at: datetime


class QaThreadResponse(BaseModel):
    id: str
    title: str
    scope: QaScopeRequest
    created_at: datetime
    updated_at: datetime
    messages: list[QaMessageResponse] = Field(default_factory=list)


class QaThreadListResponse(BaseModel):
    total: int
    items: list[QaThreadResponse]


class QaScopeResponse(BaseModel):
    thread_id: str | None
    scope: QaScopeRequest


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
