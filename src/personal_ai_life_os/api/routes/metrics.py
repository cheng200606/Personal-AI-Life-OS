"""Restricted operational metrics without user content or identifiers."""

import hmac
import json
from datetime import UTC, datetime, timedelta
from math import ceil

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select

from personal_ai_life_os.api.deps import SessionDep
from personal_ai_life_os.models import ModelRun, SyncRun
from personal_ai_life_os.storage import ObjectStore

router = APIRouter(tags=["operations"])


@router.get("/metrics")
def metrics(request: Request, session: SessionDep) -> dict:
    configured_token = request.app.state.settings.metrics_token
    supplied = request.headers.get("authorization", "")
    if not configured_token:
        raise HTTPException(404, detail={"code": "metrics_disabled", "message": "Metrics are not enabled."})
    if not supplied.startswith("Bearer ") or not hmac.compare_digest(
        supplied.removeprefix("Bearer "), configured_token
    ):
        raise HTTPException(401, detail={"code": "metrics_auth_required", "message": "A metrics token is required."})

    samples = list(request.app.state.request_samples)
    latencies = sorted(sample[1] for sample in samples)
    p95_latency = latencies[min(len(latencies) - 1, ceil(len(latencies) * 0.95) - 1)] if latencies else 0
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    failed_imports = session.scalar(
        select(func.count()).select_from(SyncRun).where(SyncRun.status == "failed", SyncRun.created_at >= cutoff)
    ) or 0
    processing_imports = session.scalar(
        select(func.count()).select_from(SyncRun).where(SyncRun.status == "processing")
    ) or 0
    model_runs = list(session.scalars(select(ModelRun)))
    model_calls = len(model_runs)
    model_failures = sum(1 for run in model_runs if run.status in {"failed", "fallback"})
    model_budget_fallbacks = sum(1 for run in model_runs if run.status == "budget_fallback")
    model_budget_exceeded = sum(1 for run in model_runs if run.status == "budget_exceeded")
    review_runs = [run for run in model_runs if run.purpose == "weekly_review"]
    photo_description_runs = [run for run in model_runs if run.purpose == "photo_description"]
    review_input_tokens = sum(run.input_tokens for run in review_runs)
    review_output_tokens = sum(run.output_tokens for run in review_runs)
    model_input_tokens = sum(run.input_tokens for run in model_runs)
    model_output_tokens = sum(run.output_tokens for run in model_runs)
    estimated_model_cost = sum((run.cost_usd or 0) for run in model_runs)
    estimated_review_cost = sum((run.cost_usd or 0) for run in review_runs)
    estimated_photo_cost = sum((run.cost_usd or 0) for run in photo_description_runs)
    store: ObjectStore = request.app.state.object_store
    tombstones = [json.loads(payload) for _, payload in store.list_deletion_tombstones()]
    pending_deletions = sum(1 for item in tombstones if not item.get("completed_at"))
    durations = []
    for item in tombstones:
        if item.get("requested_at") and item.get("completed_at"):
            try:
                requested = datetime.fromisoformat(item["requested_at"])
                completed = datetime.fromisoformat(item["completed_at"])
                durations.append(max(0, (completed - requested).total_seconds()))
            except (ValueError, TypeError):
                continue
    durations.sort()
    deletion_p95 = durations[min(len(durations) - 1, ceil(len(durations) * 0.95) - 1)] if durations else 0
    return {
        "window_seconds": 600,
        "requests_sampled": len(samples),
        "http_5xx_sampled": sum(1 for sample in samples if sample[2] >= 500),
        "request_latency_p95_ms": round(p95_latency, 2),
        "imports_failed_24h": failed_imports,
        "imports_processing": processing_imports,
        "deletions_pending": pending_deletions,
        "deletion_duration_p95_seconds": round(deletion_p95, 2),
        "external_model_calls": model_calls,
        "external_review_calls": len(review_runs),
        "external_photo_description_calls": len(photo_description_runs),
        "external_model_failures": model_failures,
        "external_model_budget_fallbacks": model_budget_fallbacks,
        "external_model_budget_exceeded": model_budget_exceeded,
        "external_model_input_tokens": model_input_tokens,
        "external_model_output_tokens": model_output_tokens,
        "external_review_input_tokens": review_input_tokens,
        "external_review_output_tokens": review_output_tokens,
        "external_photo_description_estimated_cost_usd": round(float(estimated_photo_cost), 8),
        "external_review_estimated_cost_usd": round(float(estimated_review_cost), 8),
        "external_model_estimated_cost_usd": round(float(estimated_model_cost), 8),
    }
