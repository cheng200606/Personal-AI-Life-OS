"""Stable request and response schemas for the versioned API."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID
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
    kind: Literal["memory_markdown", "chatgpt_export", "chat_export", "document", "photo", "calendar_ics"]
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
    items_updated: int
    items_duplicate: int
    items_removed: int
    items_skipped: int
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
    provider_id: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=160)

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


class ReviewVersionResponse(BaseModel):
    id: str
    version_number: int
    status: str
    draft: dict[str, Any]
    final_text: str | None
    reason: str
    created_at: datetime


class ReviewResponse(BaseModel):
    id: str
    period_start: datetime
    period_end: datetime
    status: str
    draft: dict[str, Any]
    final_text: str | None
    source_items: list[SourceItemResponse]
    version_number: int = 1
    insights: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AIPreferenceRequest(BaseModel):
    enabled: bool
    disclosure_version: str | None = None
    provider_id: str | None = Field(default=None, max_length=80)


class ModelConsentRequest(BaseModel):
    enabled: bool
    provider_id: str = Field(min_length=1, max_length=80)
    disclosure_version: str | None = Field(default=None, max_length=120)


class ModelConsentResponse(BaseModel):
    provider_id: str
    disclosure_version: str | None
    granted_at: datetime | None
    revoked_at: datetime | None


class PhotoDescriptionConfirmRequest(BaseModel):
    description: str = Field(min_length=1, max_length=10000)


class QuickNoteCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content_text: str = Field(min_length=1, max_length=20000)
    occurred_at: datetime | None = None
    source_timezone: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized[:200] or None

    @field_validator("content_text")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Note content cannot be empty.")
        return normalized

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("occurred_at must include a timezone offset.")
        return value

    @field_validator("source_timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except Exception as error:
                raise ValueError("Enter a valid IANA timezone.") from error
        return value


class QuickNoteUpdateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    content_text: str | None = Field(default=None, min_length=1, max_length=20000)
    occurred_at: datetime | None = None
    source_timezone: str | None = Field(default=None, min_length=1, max_length=64)
    clear_occurred_at: bool = False
    clear_source_timezone: bool = False

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized[:200] or None

    @field_validator("content_text")
    @classmethod
    def normalize_content(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Note content cannot be empty.")
        return normalized

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("occurred_at must include a timezone offset.")
        return value

    @field_validator("source_timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is not None:
            try:
                ZoneInfo(value)
            except Exception as error:
                raise ValueError("Enter a valid IANA timezone.") from error
        return value

    @model_validator(mode="after")
    def require_change(self) -> "QuickNoteUpdateRequest":
        if all(
            value is None
            for value in (self.title, self.content_text, self.occurred_at, self.source_timezone)
        ) and not (self.clear_occurred_at or self.clear_source_timezone):
            raise ValueError("Provide at least one note change.")
        if self.clear_occurred_at and self.occurred_at is not None:
            raise ValueError("Provide occurred_at or clear_occurred_at, not both.")
        if self.clear_source_timezone and self.source_timezone is not None:
            raise ValueError("Provide source_timezone or clear_source_timezone, not both.")
        return self


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
    provider_id: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=160)

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
    provider_id: str
    model: str | None
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


class InsightEvidenceResponse(BaseModel):
    evidence_id: str
    quote: str
    confidence: float
    source_id: str
    source_name: str
    source_item_id: str
    item_title: str
    occurred_at: str | None


class InsightResponse(BaseModel):
    insight_key: str
    rule: str
    rule_label: str
    entity_id: str
    entity_type: str
    entity_name: str
    severity: Literal["high", "medium", "low"]
    confidence: float
    trigger: str
    evidence: list[InsightEvidenceResponse]
    suggestion: str
    dismissed: bool
    dismissed_reason: str | None


class InsightListResponse(BaseModel):
    total: int
    dismissed_total: int
    items: list[InsightResponse]


class InsightDismissRequest(BaseModel):
    insight_key: str = Field(min_length=1, max_length=240)
    rule: str = Field(min_length=1, max_length=40)
    entity_id: str | None = None
    reason: str | None = Field(default=None, max_length=500)


class AgentActionCreateRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    payload: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False


class AgentActionResponse(BaseModel):
    id: str
    kind: str
    target_type: str
    target_id: str | None
    before: dict[str, Any]
    after: dict[str, Any]
    evidence_item_ids: list[str]
    status: str
    approval: str
    error_code: str | None
    audit: dict[str, Any]
    expires_at: datetime
    undo_available: bool
    created_at: datetime
    undone_at: datetime | None


class AgentActionListResponse(BaseModel):
    total: int
    items: list[AgentActionResponse]


class AgentToolResponse(BaseModel):
    name: str
    kind: str
    permission: str
    requires_approval: bool
    red_line: bool
    description: str


class AgentToolListResponse(BaseModel):
    total: int
    items: list[AgentToolResponse]


class PluginCatalogEntryResponse(BaseModel):
    name: str
    version: str
    kind: str
    entrypoint: str
    description: str
    permissions: list[str]


class PluginCatalogResponse(BaseModel):
    total: int
    items: list[PluginCatalogEntryResponse]


class PluginResponse(BaseModel):
    id: str
    name: str
    version: str
    kind: str
    description: str
    entrypoint: str
    status: str
    permissions: list[str]
    created_at: datetime
    updated_at: datetime


class PluginListResponse(BaseModel):
    total: int
    items: list[PluginResponse]


class PluginInstallRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    permissions: list[str] | None = None


class PluginStatusRequest(BaseModel):
    status: Literal["enabled", "disabled"]


class PluginInvokeRequest(BaseModel):
    action: str = Field(min_length=1, max_length=40)
    payload: dict[str, Any] = Field(default_factory=dict)


class PluginAuditResponse(BaseModel):
    id: str
    plugin_id: str | None
    action: str
    status: str
    detail: dict[str, Any]
    created_at: datetime


class PluginAuditListResponse(BaseModel):
    total: int
    items: list[PluginAuditResponse]


class BudgetPurposeResponse(BaseModel):
    purpose: str
    cost_usd: Decimal
    runs: int


class BudgetProviderResponse(BaseModel):
    provider: str
    cost_usd: Decimal
    runs: int
    input_tokens: int
    output_tokens: int
    avg_latency_ms: int


class BudgetResponse(BaseModel):
    month: str
    period: Literal["day", "week", "month"] = "month"
    spent_usd: Decimal
    limit_usd: Decimal
    remaining_usd: Decimal
    warning: bool
    over_budget: bool
    runs: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    avg_latency_ms: int = 0
    failure_reserve_usd: Decimal = Decimal(0)
    by_purpose: list[BudgetPurposeResponse]
    by_provider: list[BudgetProviderResponse] = Field(default_factory=list)


class TagCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Tag name cannot be empty.")
        return normalized

    @field_validator("color")
    @classmethod
    def normalize_color(cls, value: str | None) -> str | None:
        return value.upper() if value else None


class TagUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    clear_color: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Tag name cannot be empty.")
        return normalized

    @field_validator("color")
    @classmethod
    def normalize_color(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @model_validator(mode="after")
    def require_change(self) -> "TagUpdateRequest":
        if self.name is None and self.color is None and not self.clear_color:
            raise ValueError("Provide a tag name, color, or clear_color.")
        if self.clear_color and self.color is not None:
            raise ValueError("Provide color or clear_color, not both.")
        return self


class TagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    color: str | None
    created_at: datetime
    updated_at: datetime


class CollectionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Collection name cannot be empty.")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class CollectionUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    clear_description: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Collection name cannot be empty.")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def require_change(self) -> "CollectionUpdateRequest":
        if self.name is None and self.description is None and not self.clear_description:
            raise ValueError("Provide a collection name, description, or clear_description.")
        if self.clear_description and self.description is not None:
            raise ValueError("Provide description or clear_description, not both.")
        return self


class CollectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class ItemOrganizationUpdateRequest(BaseModel):
    tag_ids: list[str] = Field(default_factory=list, max_length=100)
    collection_ids: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("tag_ids", "collection_ids")
    @classmethod
    def validate_ids(cls, value: list[str]) -> list[str]:
        return [str(UUID(item_id)) for item_id in value]

    @model_validator(mode="after")
    def unique_ids(self) -> "ItemOrganizationUpdateRequest":
        if len(set(self.tag_ids)) != len(self.tag_ids) or len(set(self.collection_ids)) != len(self.collection_ids):
            raise ValueError("Tag and collection IDs must be unique.")
        return self


class ItemOrganizationResponse(BaseModel):
    item_id: str
    tags: list[TagResponse]
    collections: list[CollectionResponse]


class SearchFilters(BaseModel):
    types: list[Literal["timeline", "reviews", "reminders"]] = Field(
        default_factory=lambda: ["timeline", "reviews", "reminders"], max_length=3
    )
    start: date | None = None
    end: date | None = None
    source_id: str | None = Field(default=None, max_length=64)
    status: list[str] = Field(default_factory=list, max_length=20)
    tag_id: str | None = Field(default=None, max_length=64)
    collection_id: str | None = Field(default=None, max_length=64)

    @field_validator("source_id", "tag_id", "collection_id")
    @classmethod
    def validate_uuid(cls, value: str | None) -> str | None:
        return str(UUID(value)) if value is not None else None

    @model_validator(mode="after")
    def validate_filters(self) -> "SearchFilters":
        if not self.types or len(set(self.types)) != len(self.types):
            raise ValueError("Choose unique search result types.")
        if self.start and self.end and self.end <= self.start:
            raise ValueError("end must be after start.")
        if len(set(self.status)) != len(self.status):
            raise ValueError("Status filters must be unique.")
        return self


class SavedSearchCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: str = Field(min_length=1, max_length=200)
    filters: SearchFilters = Field(default_factory=SearchFilters)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Saved search name cannot be empty.")
        return normalized

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Saved search query cannot be empty.")
        return normalized


class SavedSearchUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    filters: SearchFilters | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Saved search name cannot be empty.")
        return normalized

    @model_validator(mode="after")
    def require_change(self) -> "SavedSearchUpdateRequest":
        if self.name is None and self.filters is None:
            raise ValueError("Provide a saved search name or filters.")
        return self


class SavedSearchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    query: str
    filters: SearchFilters
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
    index_backend: str = "like"
    timeline: SearchTimelineGroup
    reviews: SearchReviewGroup
    reminders: SearchReminderGroup
