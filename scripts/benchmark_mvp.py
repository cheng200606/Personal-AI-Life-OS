"""Measure local API timeline and 500-item import latency on synthetic data."""

from __future__ import annotations

import json
import math
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from personal_ai_life_os.config import Settings
from personal_ai_life_os.main import create_app
from personal_ai_life_os.models import SourceItem, SyncRun


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def run() -> dict:
    with tempfile.TemporaryDirectory(prefix="lifeos-benchmark-") as temporary:
        root = Path(temporary)
        config = Settings(
            _env_file=None,
            app_env="test",
            data_dir=root / "data",
            database_url=f"sqlite+pysqlite:///{(root / 'benchmark.sqlite3').as_posix()}",
            auto_create_schema=True,
            access_token_secret="synthetic-benchmark-secret-at-least-32-characters",
            registration_mode="open",
        )
        with TestClient(create_app(config)) as client:
            registration = client.post(
                "/api/v1/auth/register",
                json={
                    "email": "benchmark@example.invalid",
                    "password": "synthetic benchmark password",
                    "timezone": "UTC",
                },
            )
            if registration.status_code != 201:
                raise RuntimeError("Could not create the synthetic benchmark account.")
            token = registration.json()["access_token"]
            owner_id = registration.json()["user"]["id"]
            headers = {"Authorization": "Bearer " + token}
            source_response = client.post(
                "/api/v1/sources",
                headers=headers,
                json={"kind": "memory_markdown", "name": "synthetic benchmark", "selected_scope": {}},
            )
            if source_response.status_code != 201:
                raise RuntimeError("Could not create the synthetic benchmark source.")
            source_id = source_response.json()["id"]

            run_id = str(uuid4())
            now = datetime(2026, 1, 1, tzinfo=UTC)
            session_factory = client.app.state.session_factory
            with session_factory() as session:
                session.add(
                    SyncRun(
                        id=run_id,
                        owner_id=owner_id,
                        source_id=source_id,
                        status="completed",
                        parser_version="synthetic-benchmark-v1",
                        file_sha256="a" * 64,
                        items_seen=10_000,
                        items_created=10_000,
                    )
                )
                session.flush()
                session.add_all(
                    [
                        SourceItem(
                            id=str(uuid4()),
                            owner_id=owner_id,
                            source_id=source_id,
                            sync_run_id=run_id,
                            external_id=f"benchmark-item-{index}",
                            kind="markdown",
                            title=f"Synthetic benchmark item {index:05}",
                            content_text=f"Synthetic benchmark evidence row {index:05} for timeline search.",
                            occurred_at=now + timedelta(minutes=index % (31 * 24 * 60)),
                            source_timezone="UTC",
                            source_sha256=f"{index:064x}",
                            stored_sha256=f"{index:064x}",
                            parser_version="synthetic-benchmark-v1",
                            object_key=f"benchmark/{index}/source.bin",
                            source_locator={"line_start": index + 1, "line_end": index + 2},
                            metadata_json={},
                            is_current=True,
                        )
                        for index in range(10_000)
                    ]
                )
                session.commit()

            query_samples: dict[str, list[float]] = {
                "date_range": [],
                "source_filter": [],
                "keyword": [],
            }
            requests = {
                "date_range": {"start": "2026-01-01", "end": "2026-01-31"},
                "source_filter": {"source_id": source_id},
                "keyword": {"q": "benchmark evidence"},
            }
            for name, params in requests.items():
                for _ in range(30):
                    started = time.perf_counter()
                    response = client.get("/api/v1/timeline", headers=headers, params=params)
                    query_samples[name].append((time.perf_counter() - started) * 1000)
                    if response.status_code != 200:
                        raise RuntimeError(f"Timeline sample failed ({name}): {response.status_code}")

            markdown = "\n\n".join(
                f"## 2026-11-16 — Benchmark sample {sample:02d} item {index:03d}\n\n"
                f"- Synthetic benchmark evidence sample {sample:02d}, item {index:03d}."
                for index in range(500)
                for sample in [0]
            )
            import_samples: list[float] = []
            imported_item_counts: list[int] = []
            for sample in range(30):
                sample_markdown = markdown.replace("sample 00", f"sample {sample:02d}")
                payload = sample_markdown.encode("utf-8")
                started = time.perf_counter()
                response = client.post(
                    f"/api/v1/sources/{source_id}/imports",
                    headers=headers,
                    files={"file": (f"benchmark-{sample:02d}.md", payload, "text/markdown")},
                )
                import_samples.append((time.perf_counter() - started) * 1000)
                if response.status_code != 201:
                    raise RuntimeError(f"Import sample {sample} failed: {response.status_code} {response.text[:200]}")
                imported_item_counts.append(len(response.json()["items"]))

            query_p95 = {name: round(_p95(values), 2) for name, values in query_samples.items()}
            import_p95 = round(_p95(import_samples), 2)
            return {
                "environment": "local SQLite + FastAPI TestClient; synthetic only",
                "timeline_rows_before_imports": 10_000,
                "timeline_query_samples_each": 30,
                "timeline_p95_ms": query_p95,
                "import_samples": len(import_samples),
                "import_item_count_each": sorted(set(imported_item_counts)),
                "import_file_bytes_max": len(markdown.encode("utf-8")),
                "import_p95_ms": import_p95,
                "targets": {
                    "timeline_p95_ms_max": 500,
                    "import_p95_ms_max": 30_000,
                    "samples": 30,
                    "items_each": 500,
                },
                "pass": (
                    all(value <= 500 for value in query_p95.values())
                    and import_p95 <= 30_000
                    and set(imported_item_counts) == {500}
                ),
            }


if __name__ == "__main__":
    report = run()
    print(json.dumps(report, indent=2))
    if not report["pass"]:
        raise SystemExit(1)
