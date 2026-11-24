"""Tenant-scoped application data models."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from personal_ai_life_os.db import Base, UTCDateTime


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


memory_record_sources = Table(
    "memory_record_sources",
    Base.metadata,
    Column("memory_record_id", Uuid(as_uuid=False), ForeignKey("memory_records.id", ondelete="CASCADE"), primary_key=True),
    Column("source_item_id", Uuid(as_uuid=False), ForeignKey("source_items.id", ondelete="CASCADE"), primary_key=True),
)

reminder_sources = Table(
    "reminder_sources",
    Base.metadata,
    Column("reminder_id", Uuid(as_uuid=False), ForeignKey("reminders.id", ondelete="CASCADE"), primary_key=True),
    Column("source_item_id", Uuid(as_uuid=False), ForeignKey("source_items.id", ondelete="CASCADE"), primary_key=True),
)

review_sources = Table(
    "review_sources",
    Base.metadata,
    Column("review_id", Uuid(as_uuid=False), ForeignKey("reviews.id", ondelete="CASCADE"), primary_key=True),
    Column("source_item_id", Uuid(as_uuid=False), ForeignKey("source_items.id", ondelete="CASCADE"), primary_key=True),
)

reminder_records = Table(
    "reminder_records",
    Base.metadata,
    Column("reminder_id", Uuid(as_uuid=False), ForeignKey("reminders.id", ondelete="CASCADE"), primary_key=True),
    Column("memory_record_id", Uuid(as_uuid=False), ForeignKey("memory_records.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    ai_consent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    ai_consent_provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ai_consent_disclosure_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    deletion_requested_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    sources: Mapped[list["SourceConnection"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class SourceConnection(Base):
    __tablename__ = "source_connections"
    __table_args__ = (
        Index("ix_sources_owner_status", "owner_id", "status"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    consent_version: Mapped[str] = mapped_column(String(80))
    selected_scope: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    last_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    owner: Mapped[User] = relationship(back_populates="sources")
    items: Mapped[list["SourceItem"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )
    sync_runs: Mapped[list["SyncRun"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class SyncRun(Base):
    __tablename__ = "sync_runs"
    __table_args__ = (Index("ix_sync_runs_owner_created", "owner_id", "created_at"),)

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("source_connections.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="processing", index=True)
    parser_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    file_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    object_key: Mapped[str | None] = mapped_column(String(600), nullable=True)
    items_seen: Mapped[int] = mapped_column(Integer, default=0)
    items_created: Mapped[int] = mapped_column(Integer, default=0)
    items_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    items_failed: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    source: Mapped[SourceConnection] = relationship(back_populates="sync_runs")


class SourceItem(Base):
    __tablename__ = "source_items"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "source_id", "external_id", "source_sha256", name="uq_source_item_version"
        ),
        Index("ix_items_owner_occurred", "owner_id", "occurred_at"),
        Index("ix_items_owner_source", "owner_id", "source_id"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("source_connections.id", ondelete="CASCADE"), index=True
    )
    sync_run_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("sync_runs.id", ondelete="CASCADE"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(512))
    kind: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(500))
    content_text: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    source_timezone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    stored_sha256: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(80))
    object_key: Mapped[str] = mapped_column(String(600))
    source_locator: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    source: Mapped[SourceConnection] = relationship(back_populates="items")
    memory_records: Mapped[list["MemoryRecord"]] = relationship(
        secondary=memory_record_sources, back_populates="source_items"
    )
    reviews: Mapped[list["Review"]] = relationship(
        secondary=review_sources, back_populates="source_items"
    )
    reminders: Mapped[list["Reminder"]] = relationship(
        secondary=reminder_sources, back_populates="source_items"
    )


class MemoryRecord(Base):
    __tablename__ = "memory_records"
    __table_args__ = (Index("ix_memory_owner_status", "owner_id", "review_status"),)

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), default="note")
    body: Mapped[str] = mapped_column(Text)
    generated_by: Mapped[str] = mapped_column(String(32), default="user")
    review_status: Mapped[str] = mapped_column(String(24), default="confirmed", index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    source_items: Mapped[list[SourceItem]] = relationship(
        secondary=memory_record_sources, back_populates="memory_records"
    )


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("owner_id", "period_start", "period_end", name="uq_review_period"),)

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    period_start: Mapped[datetime] = mapped_column(UTCDateTime())
    period_end: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    draft_json: Mapped[dict] = mapped_column(JSON, default=dict)
    final_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    source_items: Mapped[list[SourceItem]] = relationship(
        secondary=review_sources, back_populates="reviews"
    )


class ModelRun(Base):
    __tablename__ = "model_runs"
    __table_args__ = (Index("ix_model_runs_owner_created", "owner_id", "created_at"),)

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(120))
    model: Mapped[str] = mapped_column(String(160))
    purpose: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    prompt_version: Mapped[str] = mapped_column(String(80))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class BackgroundJob(Base):
    """Durable work item whose payload contains identifiers and controls, never source content."""

    __tablename__ = "background_jobs"
    __table_args__ = (
        UniqueConstraint("owner_id", "dedupe_key", name="uq_background_job_owner_dedupe"),
        Index("ix_background_jobs_status_available", "status", "available_at"),
        Index("ix_background_jobs_owner_created", "owner_id", "created_at"),
        Index("ix_background_jobs_source_id", "source_id"),
        Index("ix_background_jobs_source_item_id", "source_item_id"),
        Index("ix_background_jobs_sync_run_id", "sync_run_id"),
        Index("ix_background_jobs_review_id", "review_id"),
    )

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("source_connections.id", ondelete="CASCADE"), nullable=True
    )
    source_item_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("source_items.id", ondelete="CASCADE"), nullable=True
    )
    sync_run_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=True
    )
    review_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("reviews.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    dedupe_key: Mapped[str] = mapped_column(String(300))
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Reminder(Base):
    __tablename__ = "reminders"
    __table_args__ = (Index("ix_reminders_owner_due", "owner_id", "due_at"),)

    id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)
    memory_records: Mapped[list[MemoryRecord]] = relationship(
        secondary=reminder_records
    )
    source_items: Mapped[list[SourceItem]] = relationship(
        secondary=reminder_sources, back_populates="reminders"
    )
