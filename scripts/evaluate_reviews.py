"""Run the deterministic synthetic review evidence and citation evaluation."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from personal_ai_life_os.api.routes.reviews import _local_bounds, _render_markdown, _template

FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic" / "review-eval.json"
CITATION_PATTERN = re.compile(r"\[source:([^\]]+)\]")
REQUIRED_CATEGORIES = {
    "supported_fact",
    "conflicting_sources",
    "insufficient_evidence",
    "timezone_boundary",
    "duplicate_source_items",
    "model_failure_fallback",
}


def _items(case: dict) -> list[SimpleNamespace]:
    values = []
    for raw in case["items"]:
        occurred_at = datetime.fromisoformat(raw["occurred_at"]) if raw["occurred_at"] else None
        values.append(
            SimpleNamespace(
                id=raw["id"],
                source_id="synthetic-source",
                sync_run_id="synthetic-sync-run",
                kind="synthetic",
                title=raw["title"],
                content_text=raw["content_text"],
                occurred_at=occurred_at,
                source_timezone=raw["source_timezone"],
                source_locator=raw["source_locator"],
                metadata_json={},
                created_at=datetime(2026, 11, 25, tzinfo=UTC),
                deleted_at=None,
            )
        )
    return values


def evaluate() -> dict:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = fixture["cases"]
    if len(cases) != 30:
        raise AssertionError(f"Expected exactly 30 synthetic cases, found {len(cases)}.")

    categories = Counter()
    fact_count = 0
    located_facts = 0
    supported_facts = 0
    unsupported_facts: list[str] = []
    errors: list[str] = []
    for case in cases:
        categories[case["category"]] += 1
        items = _items(case)
        draft = _template(items)
        markdown = _render_markdown(draft, items)
        item_by_id = {item.id: item for item in items}
        rendered_citations = set(CITATION_PATTERN.findall(markdown))
        facts = draft["facts"]
        if len(facts) != case["expected_fact_count"]:
            errors.append(
                f"{case['id']}: expected {case['expected_fact_count']} facts, received {len(facts)}"
            )
        for fact in facts:
            fact_count += 1
            source_ids = fact["source_ids"]
            valid_sources = [source_id for source_id in source_ids if source_id in item_by_id]
            if valid_sources and all(source_id in rendered_citations for source_id in valid_sources):
                located_facts += 1
            text = " ".join(fact["text"].split()).casefold()
            supporting_sources = [
                item_by_id[source_id]
                for source_id in valid_sources
                if source_id in item_by_id
            ]
            if text and any(
                text in " ".join((item.content_text or item.title).split()).casefold()
                for item in supporting_sources
            ):
                supported_facts += 1
            else:
                unsupported_facts.append(case["id"])

        if case["category"] == "timezone_boundary":
            start, end = _local_bounds(
                datetime.fromisoformat(case["period_start"]).date(),
                datetime.fromisoformat(case["period_end"]).date(),
                case["user_timezone"],
            )
            period_hours = (end - start).total_seconds() / 3600
            if period_hours != case["expected_period_hours"]:
                errors.append(
                    f"{case['id']}: expected {case['expected_period_hours']} local hours, got {period_hours}"
                )

    missing_categories = REQUIRED_CATEGORIES - categories.keys()
    if missing_categories:
        errors.append("Missing scenarios: " + ", ".join(sorted(missing_categories)))
    location_rate = located_facts / fact_count if fact_count else 1.0
    support_rate = supported_facts / fact_count if fact_count else 1.0
    result = {
        "evaluation": "deterministic-template-review",
        "cases": len(cases),
        "categories": dict(sorted(categories.items())),
        "facts": fact_count,
        "source_location_rate": location_rate,
        "evidence_support_rate": support_rate,
        "unsupported_claims": len(unsupported_facts),
        "errors": errors,
    }
    if location_rate < 1.0:
        errors.append("Source-location rate must be 100%.")
    if support_rate < 0.95:
        errors.append("Evidence-support rate must be at least 95%.")
    if unsupported_facts:
        errors.append("Unsupported facts: " + ", ".join(unsupported_facts))
    result["errors"] = errors
    return result


if __name__ == "__main__":
    report = evaluate()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["errors"]:
        raise SystemExit(1)
