"""Owner-scoped graph extraction runs."""

from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import ExtractionRequest, ExtractionRunResponse
from personal_ai_life_os.config import Settings
from personal_ai_life_os.models import ExtractionRun
from personal_ai_life_os.services.graph_extraction import (
    GraphExtractionError,
    extract_selected_items,
    monthly_spend,
)

router = APIRouter(prefix="/extractions", tags=["graph"])


def _response(run: ExtractionRun, session: Session, config: Settings) -> ExtractionRunResponse:
    spent = monthly_spend(session, run.owner_id)
    limit = config.model_monthly_budget_usd
    warning = limit > 0 and spent >= limit * Decimal("0.8")
    return ExtractionRunResponse(
        id=run.id,
        status=run.status,
        provider=run.provider,
        model=run.model,
        prompt_version=run.prompt_version,
        item_count=run.item_count,
        entity_count=run.entity_count,
        relation_count=run.relation_count,
        review_count=run.review_count,
        input_tokens=run.input_tokens,
        output_tokens=run.output_tokens,
        cost_usd=run.cost_usd,
        latency_ms=run.latency_ms,
        error_code=run.error_code,
        budget_used_usd=spent,
        budget_limit_usd=limit,
        budget_warning=warning,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


@router.post("", response_model=ExtractionRunResponse, status_code=201)
def create_extraction(
    payload: ExtractionRequest,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
) -> ExtractionRunResponse:
    config: Settings = request.app.state.settings
    try:
        run = extract_selected_items(
            session,
            owner_id=user.id,
            item_ids=payload.item_ids,
            config=config,
            provider_name=payload.provider,
        )
    except GraphExtractionError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        ) from error
    return _response(run, session, config)


@router.get("/{run_id}", response_model=ExtractionRunResponse)
def get_extraction(
    run_id: str,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
) -> ExtractionRunResponse:
    run = session.scalar(
        select(ExtractionRun).where(
            ExtractionRun.id == run_id,
            ExtractionRun.owner_id == user.id,
        )
    )
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "extraction_not_found", "message": "The extraction run was not found."},
        )
    return _response(run, session, request.app.state.settings)
