"""Run a 30-case synthetic evidence-graph Q&A evaluation.

The evaluation seeds an isolated SQLite database with active, revoked, and
deleted evidence, then asks 30 bilingual questions through the real
``/api/v1/qa`` endpoints. It reports citation accuracy, unsupported claims,
P95 latency, and the pending review count. Results are synthetic and local;
the script records measurements instead of failing a performance target.

Run with ``uv run python scripts/evaluate_graph_qa.py``. No external services
or model provider are required.
"""

from __future__ import annotations

import json
import math
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from personal_ai_life_os.config import Settings
from personal_ai_life_os.main import create_app
from personal_ai_life_os.models import (
    GraphEntity,
    GraphEvidence,
    GraphReviewItem,
    SourceConnection,
    SourceItem,
    SyncRun,
)

TARGET_MS = 30_000
TARGET_ACCURACY = 0.9

# (case_id, intent, language, question, entity_name, entity_type, summary, quote, mode)
CASES: tuple[tuple[str, str, str, str, str, str, str, str, str], ...] = (
    (
        "qa-zh-decision-01",
        "decision",
        "zh",
        "我和 Alex 约定了什么？",
        "与 Alex 的交付承诺",
        "commitment",
        "约定在 2026-11-20 前提交评审。",
        "已与 Alex 约定在 2026-11-20 前提交评审。",
        "active",
    ),
    (
        "qa-zh-decision-02",
        "decision",
        "zh",
        "当时为什么决定使用 Postgres？",
        "使用 Postgres 的决定",
        "decision",
        "为了结构化记录与可移植 Markdown。",
        "决定使用 Postgres 保存结构化记录，并保留 Markdown 导出。",
        "active",
    ),
    (
        "qa-en-decision-03",
        "decision",
        "en",
        "What did I promise Alex?",
        "Alex delivery promise",
        "commitment",
        "Submit the review before 2026-11-20.",
        "I promised Alex to submit the review before 2026-11-20.",
        "active",
    ),
    (
        "qa-en-decision-04",
        "decision",
        "en",
        "Why did I decide to use Postgres?",
        "Postgres decision",
        "decision",
        "Structured records and portable Markdown.",
        "I decided to use Postgres for structured records and keep Markdown export.",
        "active",
    ),
    (
        "qa-zh-decision-05",
        "decision",
        "zh",
        "我答应了谁做导入评审？",
        "导入评审承诺",
        "commitment",
        "答应与团队一起评审导入流程。",
        "答应和团队一起在周五前评审导入流程。",
        "active",
    ),
    (
        "qa-en-decision-06",
        "decision",
        "en",
        "What commitment did I make about the import review?",
        "Import review commitment",
        "commitment",
        "Review the import flow with the team.",
        "I committed to review the import flow with the team on Friday.",
        "active",
    ),
    (
        "qa-zh-decision-07",
        "decision",
        "zh",
        "关于发布节奏我做了什么决定？",
        "发布节奏决定",
        "decision",
        "先小范围发布，再逐步扩大。",
        "决定先小范围发布，再根据反馈逐步扩大。",
        "active",
    ),
    (
        "qa-zh-project-08",
        "project",
        "zh",
        "Life OS 项目的目标是什么？",
        "Life OS",
        "project",
        "建立本地优先的个人记忆系统。",
        "Life OS 的目标是建立本地优先的个人记忆系统。",
        "active",
    ),
    (
        "qa-zh-project-09",
        "project",
        "zh",
        "证据图谱问答项目现在进展如何？",
        "证据图谱问答",
        "project",
        "已完成检索与问答页面。",
        "证据图谱问答项目已经完成检索与问答页面。",
        "active",
    ),
    (
        "qa-zh-project-10",
        "project",
        "zh",
        "导入预览项目下一步是什么？",
        "导入预览",
        "project",
        "补充文件类型与错误提示。",
        "导入预览项目的下一步是补充文件类型与错误提示。",
        "active",
    ),
    (
        "qa-en-project-11",
        "project",
        "en",
        "What is the status of the Life OS project?",
        "Life OS status",
        "project",
        "The local-first memory system is in active development.",
        "The Life OS project is in active development as a local-first memory system.",
        "active",
    ),
    (
        "qa-en-project-12",
        "project",
        "en",
        "What is the next step for the evidence graph project?",
        "Evidence graph project",
        "project",
        "Add review and question flows.",
        "The next step for the evidence graph project is to add review and question flows.",
        "active",
    ),
    (
        "qa-en-project-13",
        "project",
        "en",
        "What goal does the import preview project have?",
        "Import preview project",
        "project",
        "Make file selection transparent.",
        "The import preview project aims to make file selection transparent.",
        "active",
    ),
    (
        "qa-zh-project-14",
        "project",
        "zh",
        "周复盘项目有哪些任务？",
        "周复盘",
        "project",
        "生成草稿、编辑与导出。",
        "周复盘项目包括生成草稿、编辑与导出三个任务。",
        "active",
    ),
    (
        "qa-zh-growth-15",
        "growth",
        "zh",
        "我在学什么技能？",
        "Python",
        "skill",
        "用 Python 实现后端导入与检索。",
        "正在学习用 Python 实现后端导入与检索。",
        "active",
    ),
    (
        "qa-zh-growth-16",
        "growth",
        "zh",
        "我的中文写作主题有哪些证据？",
        "中文写作",
        "topic",
        "持续记录中文写作练习。",
        "中文写作主题下记录了每周的写作练习。",
        "active",
    ),
    (
        "qa-zh-growth-17",
        "growth",
        "zh",
        "我在成长记录里记了什么？",
        "时间管理成长",
        "growth_record",
        "通过周复盘改善时间安排。",
        "成长记录显示通过周复盘改善了时间安排。",
        "active",
    ),
    (
        "qa-en-growth-18",
        "growth",
        "en",
        "What skills am I learning?",
        "SQL",
        "skill",
        "Practising SQL for reporting.",
        "I am learning SQL for reporting and analysis.",
        "active",
    ),
    (
        "qa-en-growth-19",
        "growth",
        "en",
        "What evidence do I have for public speaking?",
        "Public speaking",
        "skill",
        "Two practice talks completed.",
        "Public speaking evidence includes two completed practice talks.",
        "active",
    ),
    (
        "qa-en-growth-20",
        "growth",
        "en",
        "What growth record mentions reading?",
        "Reading habit",
        "growth_record",
        "A nightly reading habit.",
        "The growth record mentions a nightly reading habit.",
        "active",
    ),
    (
        "qa-zh-timeline-21",
        "timeline",
        "zh",
        "上周发生了什么？",
        "导入评审事件",
        "event",
        "上周完成导入评审。",
        "上周完成了导入评审并记录了问题清单。",
        "active",
    ),
    (
        "qa-zh-timeline-22",
        "timeline",
        "zh",
        "最近有哪些值得复盘的事件？",
        "原型评审事件",
        "event",
        "原型评审发现了页面密度问题。",
        "最近的原型评审发现了页面密度问题。",
        "active",
    ),
    (
        "qa-zh-timeline-23",
        "timeline",
        "zh",
        "这个月的时间线有什么进展？",
        "预算评审事件",
        "event",
        "预算评审通过了本地部署方案。",
        "时间线显示预算评审通过了本地部署方案。",
        "active",
    ),
    (
        "qa-en-timeline-24",
        "timeline",
        "en",
        "What happened last week?",
        "Import review event",
        "event",
        "The import review finished last week.",
        "Last week the import review finished with an issue list.",
        "active",
    ),
    (
        "qa-en-timeline-25",
        "timeline",
        "en",
        "What recent events should I review?",
        "Prototype review event",
        "event",
        "The prototype review found density issues.",
        "A recent prototype review found page density issues.",
        "active",
    ),
    (
        "qa-en-timeline-26",
        "timeline",
        "en",
        "What happened on the timeline this month?",
        "Budget review event",
        "event",
        "The budget review approved local deployment.",
        "The timeline shows the budget review approved local deployment.",
        "active",
    ),
    (
        "qa-zh-revoked-27",
        "decision",
        "zh",
        "被撤回来源里的约定是什么？",
        "撤回来源承诺",
        "commitment",
        "这条承诺来自已撤回的来源。",
        "这条承诺来自已经撤回的来源。",
        "revoked",
    ),
    (
        "qa-en-revoked-28",
        "decision",
        "en",
        "What promise is in the revoked source?",
        "Revoked source promise",
        "commitment",
        "This promise came from a revoked source.",
        "This promise came from a source that was revoked.",
        "revoked",
    ),
    (
        "qa-zh-deleted-29",
        "project",
        "zh",
        "被删除条目里的项目进展是什么？",
        "删除条目项目",
        "project",
        "这条证据已被删除。",
        "这条项目进展证据已经被删除。",
        "deleted",
    ),
    (
        "qa-en-deleted-30",
        "project",
        "en",
        "What progress is in the deleted item?",
        "Deleted item project",
        "project",
        "This evidence was deleted.",
        "This project progress evidence was deleted.",
        "deleted",
    ),
)


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def _seed(client: TestClient, token: str) -> tuple[dict[str, str], dict[str, str]]:
    owner_id = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer " + token}
    ).json()["id"]
    session_factory = client.app.state.session_factory
    entity_by_case: dict[str, str] = {}
    item_by_case: dict[str, str] = {}
    sources: dict[str, str] = {}
    now = datetime.now(UTC)
    with session_factory() as session:
        for mode in ("active", "revoked", "deleted"):
            source = SourceConnection(
                owner_id=owner_id,
                kind="memory_markdown",
                name="synthetic-qa-eval-" + mode,
                status="revoked" if mode == "revoked" else "active",
                consent_version="source-consent-v1",
                selected_scope={},
            )
            session.add(source)
            session.flush()
            run = SyncRun(
                owner_id=owner_id,
                source_id=source.id,
                status="completed",
                parser_version="synthetic-qa-eval-v1",
                file_sha256=(mode[0] * 64),
                items_seen=30,
            )
            session.add(run)
            session.flush()
            sources[mode] = source.id
            for index, case in enumerate(CASES):
                if case[8] != mode:
                    continue
                case_id, _intent, _language, _question, name, entity_type, summary, quote, _mode = case
                occurred = now - timedelta(days=index % 10)
                item = SourceItem(
                    owner_id=owner_id,
                    source_id=source.id,
                    sync_run_id=run.id,
                    external_id="qa-eval-" + case_id,
                    kind="note",
                    title=name,
                    content_text=quote,
                    occurred_at=occurred,
                    source_timezone="UTC",
                    source_sha256=(case_id + "0" * 64)[:64],
                    stored_sha256=(case_id + "1" * 64)[:64],
                    parser_version="synthetic-qa-eval-v1",
                    object_key="qa-eval/" + case_id + "/source.bin",
                    source_locator={"section": case_id},
                    metadata_json={},
                    is_current=True,
                    deleted_at=now if mode == "deleted" else None,
                )
                session.add(item)
                session.flush()
                entity = GraphEntity(
                    owner_id=owner_id,
                    entity_type=entity_type,
                    name=name,
                    normalized_name=name.casefold(),
                    summary=summary,
                    confidence=0.9,
                    status="active",
                    created_by="model",
                )
                session.add(entity)
                session.flush()
                session.add(
                    GraphEvidence(
                        owner_id=owner_id,
                        entity_id=entity.id,
                        source_id=source.id,
                        source_item_id=item.id,
                        quote=quote,
                        locator={"section": case_id},
                        confidence=0.9,
                        availability="revoked" if mode == "revoked" else "active",
                    )
                )
                entity_by_case[case_id] = entity.id
                item_by_case[case_id] = item.id
        session.commit()
    return entity_by_case, item_by_case


def run() -> dict:
    with tempfile.TemporaryDirectory(prefix="lifeos-qa-eval-") as temporary:
        root = Path(temporary)
        config = Settings(
            _env_file=None,
            app_env="test",
            data_dir=root / "data",
            database_url="sqlite+pysqlite:///" + (root / "qa-eval.sqlite3").as_posix(),
            auto_create_schema=True,
            access_token_secret="synthetic-qa-eval-secret-at-least-32-characters",
            registration_mode="open",
            object_store_backend="local",
            model_provider="none",
            processing_mode="inline",
        )
        with TestClient(create_app(config)) as client:
            registration = client.post(
                "/api/v1/auth/register",
                json={
                    "email": "qa-eval@example.invalid",
                    "password": "synthetic qa evaluation password",
                    "timezone": "UTC",
                },
            )
            if registration.status_code != 201:
                raise RuntimeError("Could not create the synthetic evaluation account.")
            token = registration.json()["access_token"]
            headers = {"Authorization": "Bearer " + token}
            entity_by_case, item_by_case = _seed(client, token)

            thread = client.post(
                "/api/v1/qa/threads", headers=headers, json={"title": "合成问答评测"}
            )
            if thread.status_code != 201:
                raise RuntimeError("Could not create the evaluation thread.")
            thread_id = thread.json()["id"]

            latencies: list[float] = []
            supported = 0
            unsupported = 0
            errors: list[str] = []
            intents = Counter()
            for case_id, intent, _language, question, _name, _type, _summary, _quote, mode in CASES:
                intents[intent] += 1
                scope = {"entity_ids": [entity_by_case[case_id]]}
                started = time.perf_counter()
                response = client.post(
                    "/api/v1/qa/threads/" + thread_id + "/messages",
                    headers=headers,
                    json={"question": question, "scope": scope},
                )
                latencies.append((time.perf_counter() - started) * 1000)
                if response.status_code != 200:
                    errors.append(f"{case_id}: HTTP {response.status_code}")
                    continue
                answer = response.json()["messages"][-1]["answer"]
                if mode == "active":
                    citation_ids = {
                        citation["source_item_id"] for citation in answer["citations"]
                    }
                    if (
                        answer["status"] == "answered"
                        and item_by_case[case_id] in citation_ids
                        and answer["facts"]
                    ):
                        supported += 1
                    else:
                        errors.append(f"{case_id}: missing expected citation")
                    if not answer["citations"] or any(
                        not fact["citation_ids"] for fact in answer["facts"]
                    ):
                        unsupported += 1
                else:
                    if answer["status"] == "insufficient_evidence" and not answer["facts"]:
                        supported += 1
                    else:
                        errors.append(f"{case_id}: unavailable evidence was used")
                    if answer["facts"] or answer["citations"]:
                        unsupported += 1

            with client.app.state.session_factory() as session:
                pending = session.scalar(
                    select(func.count())
                    .select_from(GraphReviewItem)
                    .where(GraphReviewItem.status == "pending")
                ) or 0

        accuracy = round(supported / len(CASES), 4)
        p95_ms = round(_p95(latencies), 2)
        return {
            "environment": "SQLite + in-process FastAPI TestClient; synthetic only",
            "case_count": len(CASES),
            "intent_counts": dict(intents),
            "language_counts": {
                "zh": sum(1 for case in CASES if case[2] == "zh"),
                "en": sum(1 for case in CASES if case[2] == "en"),
            },
            "unavailable_case_count": sum(1 for case in CASES if case[8] != "active"),
            "citation_accuracy": accuracy,
            "target_accuracy": TARGET_ACCURACY,
            "unsupported_claim_count": unsupported,
            "p95_ms": p95_ms,
            "target_ms": TARGET_MS,
            "pending_review_count": pending,
            "errors": errors[:10],
            "pass": accuracy >= TARGET_ACCURACY and unsupported == 0 and p95_ms <= TARGET_MS,
        }


def main() -> int:
    report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
