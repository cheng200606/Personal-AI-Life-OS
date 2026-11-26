"""Evaluate configured review providers on the fixed 30-case synthetic suite."""

from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from personal_ai_life_os.api.routes.reviews import PROMPT_VERSION, _call_openai
from personal_ai_life_os.config import Settings
from personal_ai_life_os.services.model_providers import (
    ModelProviderError,
    list_model_providers,
    provider_cost,
    resolve_model_provider,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "synthetic" / "review-eval.json"
TARGET_CITATION_ACCURACY = 0.9
TARGET_LATENCY_MS = 30_000
EN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_-]{1,}")
ZH_CHAR = re.compile(r"[\u4e00-\u9fff]")


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
                created_at=datetime(2026, 11, 26, tzinfo=UTC),
                deleted_at=None,
            )
        )
    return values


def _tokens(text: str) -> set[str]:
    normalized = text.casefold()
    values = {match.group(0) for match in EN_WORD.finditer(normalized)}
    values.update(ZH_CHAR.findall(normalized))
    return values


def _supported(text: str, source_text: str) -> bool:
    normalized = " ".join(text.split()).casefold()
    source = " ".join(source_text.split()).casefold()
    if normalized and normalized in source:
        return True
    claim_tokens = _tokens(text)
    source_tokens = _tokens(source_text)
    if not claim_tokens:
        return False
    return len(claim_tokens & source_tokens) / len(claim_tokens) >= 0.6


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)] if ordered else 0.0


def evaluate_provider(config: Settings, provider_id: str, cases: list[dict]) -> dict:
    try:
        provider = resolve_model_provider(config, provider_id)
    except ModelProviderError as error:
        return {
            "provider_id": provider_id,
            "available": False,
            "error": error.code,
            "pass": False,
        }
    if not provider.api_key and not provider.local:
        return {"provider_id": provider_id, "available": False, "error": "credential_missing", "pass": False}
    if not provider.rates_configured:
        return {"provider_id": provider_id, "available": False, "error": "pricing_missing", "pass": False}

    facts = 0
    suggestions = 0
    located = 0
    supported = 0
    supported_facts = 0
    cited_suggestions = 0
    unsupported = 0
    latencies: list[float] = []
    input_tokens = 0
    output_tokens = 0
    errors: list[str] = []
    for case in cases:
        items = _items(case)
        item_map = {item.id: item for item in items}
        try:
            draft, latency_ms, case_input, case_output = _call_openai(items, provider)
        except Exception as error:  # noqa: BLE001 - evaluation records provider failures without stopping other cases.
            errors.append(f"{case['id']}:{type(error).__name__}")
            latencies.append(TARGET_LATENCY_MS)
            continue
        latencies.append(latency_ms)
        input_tokens += case_input
        output_tokens += case_output
        for key in ("facts", "suggestions"):
            for entry in draft.get(key, []):
                if key == "facts":
                    facts += 1
                else:
                    suggestions += 1
                source_ids = entry.get("source_ids", [])
                valid_ids = [source_id for source_id in source_ids if source_id in item_map]
                if valid_ids:
                    located += 1
                source_text = "\n".join(
                    (item_map[source_id].title + " " + item_map[source_id].content_text)
                    for source_id in valid_ids
                )
                if key == "facts":
                    if valid_ids and _supported(entry.get("text", ""), source_text):
                        supported += 1
                        supported_facts += 1
                    else:
                        unsupported += 1
                else:
                    if valid_ids:
                        supported += 1
                        cited_suggestions += 1
                    else:
                        unsupported += 1
    citation_accuracy = located / (facts + suggestions) if facts + suggestions else 0.0
    support_rate = supported / (facts + suggestions) if facts + suggestions else 0.0
    fact_support_rate = supported_facts / facts if facts else 1.0
    suggestion_citation_rate = cited_suggestions / suggestions if suggestions else 1.0
    p95_ms = round(_p95(latencies), 2)
    cost = provider_cost(provider, input_tokens, output_tokens) or 0
    return {
        "provider_id": provider.id,
        "model": provider.model,
        "prompt_version": PROMPT_VERSION,
        "available": True,
        "cases": len(cases),
        "facts": facts,
        "suggestions": suggestions,
        "citation_accuracy": round(citation_accuracy, 4),
        "evidence_support_rate": round(support_rate, 4),
        "fact_evidence_support_rate": round(fact_support_rate, 4),
        "suggestion_citation_rate": round(suggestion_citation_rate, 4),
        "unsupported_claims": unsupported,
        "p95_latency_ms": p95_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": f"{cost:.8f}",
        "errors": errors,
        "pass": (
            not errors
            and facts > 0
            and fact_support_rate >= TARGET_CITATION_ACCURACY
            and suggestion_citation_rate >= TARGET_CITATION_ACCURACY
            and unsupported == 0
            and p95_ms <= TARGET_LATENCY_MS
        ),
    }


def run(provider_ids: list[str] | None = None) -> dict:
    config = Settings()
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = fixture["cases"]
    if len(cases) < 30:
        raise ValueError("The review evaluation requires at least 30 fixed cases.")
    configured = [provider.id for provider in list_model_providers(config)]
    selected = provider_ids or configured
    unknown = [provider_id for provider_id in selected if provider_id not in configured]
    if unknown:
        raise ValueError("Unknown providers: " + ", ".join(unknown))
    started = time.perf_counter()
    results = [evaluate_provider(config, provider_id, cases) for provider_id in selected]
    return {
        "evaluation": "review-model-semantic-v1",
        "case_count": len(cases),
        "category_counts": dict(sorted(Counter(case["category"] for case in cases).items())),
        "provider_count": len(results),
        "multi_provider": len(results) > 1,
        "results": results,
        "wall_time_ms": round((time.perf_counter() - started) * 1000, 2),
        "pass": bool(results) and all(result["pass"] for result in results),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--providers", help="Comma-separated provider IDs; defaults to all configured providers.")
    parser.add_argument("--output", type=Path, help="Optional JSON report path.")
    args = parser.parse_args()
    provider_ids = [value.strip() for value in args.providers.split(",") if value.strip()] if args.providers else None
    report = run(provider_ids)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
