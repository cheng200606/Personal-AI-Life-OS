"""Measure unified search hit@5 and P95 latency on deterministic synthetic data.

Seeds a disposable database with about 10,000 timeline source items plus a
small, realistic set of weekly reviews and reminders, then runs 22 bilingual
queries through the real ``GET /api/v1/search`` endpoint using
``fastapi.testclient.TestClient``. Per-group hit@5 counts whether the record a
query was designed to find appears in the first five results of its group.

SQLite is the default backend (a temporary file). Set
``LIFEOS_BENCHMARK_POSTGRES_URL`` to a disposable PostgreSQL database to
measure that backend; the script creates and drops an isolated schema the same
way ``scripts/benchmark_mvp.py`` does, so Docker is only needed for that
optional run. No arguments are required; ``--help`` describes the script.

The report is printed as JSON. A missed performance or hit target is recorded
in ``pass`` and the process still exits 0, because the spec requires recording
measurements rather than failing the run.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
import time
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

from personal_ai_life_os.config import Settings
from personal_ai_life_os.main import create_app
from personal_ai_life_os.models import Reminder, Review, SourceItem, SyncRun
from personal_ai_life_os.services.search_index import rebuild_search_index, search_backend

SEARCH_PATH = "/api/v1/search"
HIT_K = 5
TARGET_MS = 500
TIMELINE_ROWS = 10_000
GROUPS = ("timeline", "reviews", "reminders")

# (query_id, query, slot, field, marker) — each slot becomes one marked timeline item.
TIMELINE_CASES: tuple[tuple[str, str, int, str, str], ...] = (
    ("timeline-en-title-harbor", "harbor lantern", 17, "title", "Harbor Lantern Briefing"),
    ("timeline-en-title-quarry", "quarterly quarry", 263, "title", "Quarterly Quarry Notes"),
    ("timeline-en-title-compass", "midnight compass", 1_499, "title", "Midnight Compass Log"),
    ("timeline-zh-title-camp", "山顶露营", 2_740, "title", "山顶露营复盘要点"),
    ("timeline-en-body-aurora", "northern aurora", 3_881, "body", "the northern aurora planning session"),
    ("timeline-en-body-granite", "granite ledger", 5_042, "body", "granite ledger reconciliation"),
    ("timeline-en-body-ferry", "river ferry", 6_183, "body", "river ferry timetable"),
    ("timeline-zh-body-reading", "社区读书会", 7_024, "body", "社区读书会排期确认"),
    ("timeline-zh-title-qingdao", "青岛旅行清单", 8_155, "title", "青岛旅行清单"),
    ("timeline-en-body-picnic", "sunset picnic", 9_016, "body", "sunset picnic logistics"),
    ("timeline-zh-body-piano", "钢琴课程", 4_407, "body", "钢琴课程调整"),
    ("timeline-en-title-solar", "solar inverter", 9_568, "title", "Solar Inverter Audit"),
    ("timeline-en-partial-quarry", "quart", 263, "title", "Quarterly Quarry Notes"),
    ("timeline-zh-partial-camp", "露营", 2_740, "title", "山顶露营复盘要点"),
    ("timeline-en-title-copper", "copper valley", 101, "title", "Copper Valley Survey"),
    ("timeline-zh-title-defense", "论文答辩", 1_001, "title", "论文答辩演练"),
    ("timeline-en-body-orchard", "silent orchard", 2_202, "body", "the silent orchard survey"),
    ("timeline-zh-body-feedback", "客户回访", 3_303, "body", "客户回访结论整理"),
    ("timeline-en-title-bridge", "bridge inspection", 4_404, "title", "Bridge Inspection Notes"),
    ("timeline-zh-body-mentor", "导师会议", 5_505, "body", "导师会议反馈"),
    ("timeline-en-short-ai", "ai", 6_606, "title", "AI Ethics Reading"),
)

REVIEW_SPECS: tuple[dict, ...] = (
    {
        "period_start": datetime(2026, 1, 5, tzinfo=UTC),
        "period_end": datetime(2026, 1, 11, tzinfo=UTC),
        "final_text": (
            "Confirmed the Postgres migration plan with the team and scheduled the "
            "rehearsal for next month."
        ),
        "queries": (("reviews-en-postgres", "postgres migration"),),
    },
    {
        "period_start": datetime(2026, 1, 12, tzinfo=UTC),
        "period_end": datetime(2026, 1, 18, tzinfo=UTC),
        "final_text": "复盘了下季度预算调整，决定先冻结非必要采购。",
        "queries": (("reviews-zh-budget", "季度预算"),),
    },
    {
        "period_start": datetime(2026, 1, 19, tzinfo=UTC),
        "period_end": datetime(2026, 1, 25, tzinfo=UTC),
        "final_text": "The hiking trail decision was deferred until the weather clears.",
        "queries": (("reviews-en-hiking", "hiking trail"),),
    },
    {
        "period_start": datetime(2026, 2, 2, tzinfo=UTC),
        "period_end": datetime(2026, 2, 8, tzinfo=UTC),
        "final_text": "复盘了客户反馈流程，明确每条投诉 48 小时内回复。",
        "queries": (("reviews-zh-feedback", "客户反馈"),),
    },
    {
        "period_start": datetime(2026, 2, 9, tzinfo=UTC),
        "period_end": datetime(2026, 2, 15, tzinfo=UTC),
        "final_text": "Documented the vendor contract renewal checklist for the new quarter.",
        "queries": (("reviews-en-vendor", "vendor contract"),),
    },
    {
        "period_start": datetime(2026, 2, 16, tzinfo=UTC),
        "period_end": datetime(2026, 2, 22, tzinfo=UTC),
        "final_text": "Reviewed sleep and exercise patterns; keep the evening walk habit.",
        "queries": (),
    },
)

REMINDER_SPECS: tuple[dict, ...] = (
    {
        "title": "Renew passport application",
        "notes": "Submit the renewal form before the photo expiry date.",
        "due_at": datetime(2026, 3, 2, tzinfo=UTC),
        "queries": (("reminders-en-passport", "passport"),),
    },
    {
        "title": "Dentist appointment",
        "notes": "Ask the dentist about the crown fitting.",
        "due_at": datetime(2026, 3, 4, tzinfo=UTC),
        "queries": (("reminders-en-crown", "crown fitting"),),
    },
    {
        "title": "缴纳物业费",
        "notes": "本月物业费在周五前通过银行转账缴纳。",
        "due_at": datetime(2026, 3, 6, tzinfo=UTC),
        "queries": (("reminders-zh-property", "物业费"),),
    },
    {
        "title": "车辆保养",
        "notes": "预约车辆年检在下周三之前完成。",
        "due_at": datetime(2026, 3, 9, tzinfo=UTC),
        "queries": (("reminders-zh-vehicle", "车辆年检"),),
    },
    {
        "title": "Book the conference room",
        "notes": "Reserve the small room for the architecture review.",
        "due_at": datetime(2026, 3, 11, tzinfo=UTC),
        "queries": (("reminders-en-conference", "conference room"),),
    },
    {
        "title": "Water the plants",
        "notes": "The balcony herbs need a deep watering.",
        "due_at": datetime(2026, 3, 13, tzinfo=UTC),
        "queries": (),
    },
    {
        "title": "Send weekly summary",
        "notes": "Collect notes from the shared folder first.",
        "due_at": datetime(2026, 3, 15, tzinfo=UTC),
        "queries": (),
    },
    {
        "title": "Pick up dry cleaning",
        "notes": "The winter coat should be ready after lunch.",
        "due_at": datetime(2026, 3, 17, tzinfo=UTC),
        "queries": (),
    },
)


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


@contextmanager
def _evaluation_database(root: Path):
    database_url = os.getenv("LIFEOS_BENCHMARK_POSTGRES_URL")
    if not database_url:
        yield f"sqlite+pysqlite:///{(root / 'search-eval.sqlite3').as_posix()}", "SQLite"
        return
    base_url = make_url(database_url)
    if base_url.get_backend_name() != "postgresql":
        raise ValueError(
            "LIFEOS_BENCHMARK_POSTGRES_URL must reference a disposable PostgreSQL database."
        )
    schema = "lifeos_search_eval_" + uuid4().hex
    engine = create_engine(base_url)
    try:
        with engine.begin() as connection:
            connection.execute(CreateSchema(schema))
        try:
            scoped_url = base_url.update_query_dict({"options": "-csearch_path=" + schema})
            yield scoped_url.render_as_string(hide_password=False), "PostgreSQL"
        finally:
            with engine.begin() as connection:
                connection.execute(DropSchema(schema, cascade=True))
    finally:
        engine.dispose()


def _seed(session_factory, owner_id: str, source_id: str) -> tuple[dict[int, str], list[str], list[str]]:
    run_id = str(uuid4())
    now = datetime(2026, 1, 1, tzinfo=UTC)
    marker_by_slot = {slot: (field, marker) for _, _, slot, field, marker in TIMELINE_CASES}
    item_id_by_slot: dict[int, str] = {}
    review_ids: list[str] = []
    reminder_ids: list[str] = []
    with session_factory() as session:
        session.add(
            SyncRun(
                id=run_id,
                owner_id=owner_id,
                source_id=source_id,
                status="completed",
                parser_version="synthetic-search-eval-v1",
                file_sha256="b" * 64,
                items_seen=TIMELINE_ROWS,
                items_created=TIMELINE_ROWS,
            )
        )
        session.flush()

        items = []
        for index in range(TIMELINE_ROWS):
            title = f"Synthetic timeline item {index:05d}"
            content = (
                f"Synthetic timeline evidence row {index:05d} used for unified search evaluation."
            )
            marker = marker_by_slot.get(index)
            if marker is not None:
                field, text = marker
                if field == "title":
                    title = f"{text} — synthetic timeline item {index:05d}"
                else:
                    content = f"{text} recorded in synthetic timeline row {index:05d}."
            item_id = str(uuid4())
            item_id_by_slot[index] = item_id
            items.append(
                SourceItem(
                    id=item_id,
                    owner_id=owner_id,
                    source_id=source_id,
                    sync_run_id=run_id,
                    external_id=f"search-eval-item-{index}",
                    kind="markdown",
                    title=title,
                    content_text=content,
                    occurred_at=now + timedelta(minutes=index % (31 * 24 * 60)),
                    source_timezone="UTC",
                    source_sha256=f"{index:064x}",
                    stored_sha256=f"{index:064x}",
                    parser_version="synthetic-search-eval-v1",
                    object_key=f"search-eval/{index}/source.bin",
                    source_locator={"line_start": index + 1, "line_end": index + 2},
                    metadata_json={},
                    is_current=True,
                )
            )
        session.add_all(items)

        for spec in REVIEW_SPECS:
            review_id = str(uuid4())
            review_ids.append(review_id)
            session.add(
                Review(
                    id=review_id,
                    owner_id=owner_id,
                    period_start=spec["period_start"],
                    period_end=spec["period_end"],
                    status="confirmed",
                    draft_json={},
                    final_text=spec["final_text"],
                )
            )

        for spec in REMINDER_SPECS:
            reminder_id = str(uuid4())
            reminder_ids.append(reminder_id)
            session.add(
                Reminder(
                    id=reminder_id,
                    owner_id=owner_id,
                    title=spec["title"],
                    notes=spec["notes"],
                    due_at=spec["due_at"],
                    status="pending",
                )
            )

        session.commit()
    return item_id_by_slot, review_ids, reminder_ids


def _build_queries(
    item_id_by_slot: dict[int, str], review_ids: list[str], reminder_ids: list[str]
) -> list[dict]:
    queries: list[dict] = []
    for query_id, query, slot, _field, _marker in TIMELINE_CASES:
        queries.append(
            {
                "query_id": query_id,
                "group": "timeline",
                "query": query,
                "expected_id": item_id_by_slot[slot],
            }
        )
    for spec, review_id in zip(REVIEW_SPECS, review_ids):
        for query_id, query in spec["queries"]:
            queries.append(
                {
                    "query_id": query_id,
                    "group": "reviews",
                    "query": query,
                    "expected_id": review_id,
                }
            )
    for spec, reminder_id in zip(REMINDER_SPECS, reminder_ids):
        for query_id, query in spec["queries"]:
            queries.append(
                {
                    "query_id": query_id,
                    "group": "reminders",
                    "query": query,
                    "expected_id": reminder_id,
                }
            )
    return queries


def _run_queries(
    client: TestClient,
    headers: dict[str, str],
    queries: list[dict],
    latencies: list[float] | None = None,
) -> dict[str, dict]:
    responses: dict[str, dict] = {}
    for case in queries:
        started = time.perf_counter()
        response = client.get(SEARCH_PATH, headers=headers, params={"q": case["query"]})
        elapsed_ms = (time.perf_counter() - started) * 1000
        if latencies is not None:
            latencies.append(elapsed_ms)
        if response.status_code != 200:
            raise RuntimeError(
                f"Search query {case['query_id']} failed: {response.status_code} "
                f"{response.text[:200]}"
            )
        responses[case["query_id"]] = response.json()
    return responses


def _hit_at_5(body: dict, group: str, expected_id: str) -> bool:
    return expected_id in [result["id"] for result in body[group]["results"][:HIT_K]]


def _metrics(cases: list[dict], responses: dict[str, dict], latencies: list[float]) -> dict:
    group_totals = Counter(case["group"] for case in cases)
    group_hits: Counter = Counter()
    overall_hits = 0
    for case in cases:
        if _hit_at_5(responses[case["query_id"]], case["group"], case["expected_id"]):
            group_hits[case["group"]] += 1
            overall_hits += 1
    return {
        "hit_at_5": {
            group: round(group_hits[group] / group_totals[group], 4) for group in GROUPS
        },
        "overall_hit_at_5": round(overall_hits / len(cases), 4),
        "p95_ms": round(_p95(latencies), 2),
    }


def run() -> dict:
    with (
        tempfile.TemporaryDirectory(prefix="lifeos-search-eval-") as temporary,
        _evaluation_database(Path(temporary)) as (database_url, backend),
    ):
        root = Path(temporary)
        config = Settings(
            _env_file=None,
            app_env="test",
            data_dir=root / "data",
            database_url=database_url,
            auto_create_schema=True,
            access_token_secret="synthetic-search-eval-secret-at-least-32-characters",
            registration_mode="open",
            object_store_backend="local",
            model_provider="none",
            processing_mode="inline",
        )
        with TestClient(create_app(config)) as client:
            registration = client.post(
                "/api/v1/auth/register",
                json={
                    "email": "search-eval@example.invalid",
                    "password": "synthetic search evaluation password",
                    "timezone": "UTC",
                },
            )
            if registration.status_code != 201:
                raise RuntimeError("Could not create the synthetic evaluation account.")
            token = registration.json()["access_token"]
            owner_id = registration.json()["user"]["id"]
            headers = {"Authorization": "Bearer " + token}
            source_response = client.post(
                "/api/v1/sources",
                headers=headers,
                json={
                    "kind": "memory_markdown",
                    "name": "synthetic search evaluation",
                    "selected_scope": {},
                },
            )
            if source_response.status_code != 201:
                raise RuntimeError("Could not create the synthetic evaluation source.")
            source_id = source_response.json()["id"]

            session_factory = client.app.state.session_factory
            item_id_by_slot, review_ids, reminder_ids = _seed(
                session_factory, owner_id, source_id
            )
            queries = _build_queries(item_id_by_slot, review_ids, reminder_ids)

            with session_factory() as session:
                timeline_rows = session.scalar(select(func.count()).select_from(SourceItem)) or 0
                review_rows = session.scalar(select(func.count()).select_from(Review)) or 0
                reminder_rows = session.scalar(select(func.count()).select_from(Reminder)) or 0
                indexed_backend = search_backend(session)

            _run_queries(client, headers, queries)
            indexed_latencies: list[float] = []
            indexed_responses = _run_queries(client, headers, queries, indexed_latencies)
            indexed_metrics = _metrics(queries, indexed_responses, indexed_latencies)

            with session_factory() as session:
                if backend == "SQLite":
                    for table in ("timeline_fts", "review_fts", "reminder_fts"):
                        session.execute(text(f"DROP TABLE IF EXISTS {table}"))
                    session.commit()
                elif backend == "PostgreSQL":
                    for index in ("ix_items_title_trgm", "ix_items_content_trgm", "ix_reviews_final_text_trgm", "ix_reminders_title_trgm", "ix_reminders_notes_trgm"):
                        session.execute(text(f"DROP INDEX IF EXISTS {index}"))
                    session.commit()
                baseline_backend = (
                    "postgresql-like-without-gin" if backend == "PostgreSQL" else search_backend(session)
                )

            _run_queries(client, headers, queries)
            baseline_latencies: list[float] = []
            baseline_responses = _run_queries(client, headers, queries, baseline_latencies)
            baseline_metrics = _metrics(queries, baseline_responses, baseline_latencies)

            with session_factory() as session:
                rebuild_search_index(session)
                deletion_case = queries[0]
                deleted_item = session.get(SourceItem, deletion_case["expected_id"])
                if deleted_item is None:
                    raise RuntimeError("Could not select the deletion-consistency fixture.")
                deleted_item.deleted_at = datetime.now(UTC)
                session.commit()
            deletion_body = client.get(
                SEARCH_PATH,
                headers=headers,
                params={"q": deletion_case["query"], "types": deletion_case["group"]},
            ).json()
            deletion_consistent = deletion_case["expected_id"] not in [
                result["id"] for result in deletion_body[deletion_case["group"]]["results"]
            ]

        group_not_regressed = all(
            indexed_metrics["hit_at_5"][group] >= baseline_metrics["hit_at_5"][group]
            for group in GROUPS
        )
        return {
            "environment": f"{backend} + in-process FastAPI TestClient; synthetic only",
            "timeline_rows": timeline_rows,
            "review_rows": review_rows,
            "reminder_rows": reminder_rows,
            "query_count": len(queries),
            "index_backend": indexed_backend,
            "hit_at_5": indexed_metrics["hit_at_5"],
            "overall_hit_at_5": indexed_metrics["overall_hit_at_5"],
            "p95_ms": indexed_metrics["p95_ms"],
            "baseline": {"backend": baseline_backend, **baseline_metrics},
            "comparison": {
                "hit_at_5_not_regressed": group_not_regressed,
                "overall_hit_at_5_not_regressed": indexed_metrics["overall_hit_at_5"] >= baseline_metrics["overall_hit_at_5"],
                "deletion_consistent": deletion_consistent,
            },
            "target_ms": TARGET_MS,
            "pass": (
                indexed_metrics["p95_ms"] <= TARGET_MS
                and group_not_regressed
                and indexed_metrics["overall_hit_at_5"] >= baseline_metrics["overall_hit_at_5"]
                and deletion_consistent
            ),
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure unified search hit@5 and P95 latency on synthetic data.",
        epilog=(
            "Set LIFEOS_BENCHMARK_POSTGRES_URL to a disposable PostgreSQL database to "
            "measure that backend; SQLite is used by default and needs no external services."
        ),
    )
    parser.parse_args()
    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
