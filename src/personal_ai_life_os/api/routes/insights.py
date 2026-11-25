"""Owner-scoped rule insights and false-positive dismissals."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    InsightDismissRequest,
    InsightEvidenceResponse,
    InsightListResponse,
    InsightResponse,
)
from personal_ai_life_os.config import Settings
from personal_ai_life_os.services.insights import (
    InsightError,
    dismiss_insight,
    evaluate_rules,
    restore_insight,
)

router = APIRouter(prefix="/insights", tags=["insights"])


def _error(error: InsightError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    )


@router.get("/rules", response_model=InsightListResponse)
def rule_insights(
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
    include_dismissed: Annotated[bool, Query()] = False,
) -> InsightListResponse:
    config: Settings = request.app.state.settings
    items, dismissed_total = evaluate_rules(
        session,
        owner_id=user.id,
        config=config,
        include_dismissed=include_dismissed,
    )
    return InsightListResponse(
        total=len(items),
        dismissed_total=dismissed_total,
        items=[
            InsightResponse(
                **{
                    **item,
                    "evidence": [
                        InsightEvidenceResponse(**evidence) for evidence in item["evidence"]
                    ],
                }
            )
            for item in items
        ],
    )


@router.post("/rules/dismiss", status_code=201)
def dismiss_rule(
    payload: InsightDismissRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> dict:
    try:
        dismissal = dismiss_insight(
            session,
            owner_id=user.id,
            insight_key=payload.insight_key,
            rule=payload.rule,
            entity_id=payload.entity_id,
            reason=payload.reason,
        )
    except InsightError as error:
        session.rollback()
        raise _error(error) from error
    session.commit()
    return {
        "insight_key": dismissal.insight_key,
        "rule": dismissal.rule,
        "reason": dismissal.reason,
        "dismissed": True,
    }


@router.delete("/rules/dismissals/{insight_key}", status_code=204)
def restore_rule(insight_key: str, user: CurrentUserDep, session: SessionDep) -> None:
    restore_insight(session, owner_id=user.id, insight_key=insight_key)
    session.commit()
