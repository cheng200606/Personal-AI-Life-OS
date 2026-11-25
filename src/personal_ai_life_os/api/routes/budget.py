"""Monthly model budget and usage summary."""

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import BudgetPurposeResponse, BudgetResponse
from personal_ai_life_os.config import Settings
from personal_ai_life_os.models import ModelRun
from personal_ai_life_os.services.graph_extraction import monthly_spend

router = APIRouter(prefix="/budget", tags=["budget"])


@router.get("", response_model=BudgetResponse)
def get_budget(
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
) -> BudgetResponse:
    config: Settings = request.app.state.settings
    now = datetime.now(UTC)
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    spent = monthly_spend(session, user.id, now)
    limit = config.model_monthly_budget_usd
    rows = session.execute(
        select(
            ModelRun.purpose,
            func.coalesce(func.sum(ModelRun.cost_usd), 0),
            func.count(ModelRun.id),
        )
        .where(ModelRun.owner_id == user.id, ModelRun.created_at >= month_start)
        .group_by(ModelRun.purpose)
        .order_by(ModelRun.purpose)
    ).all()
    remaining = max(Decimal(0), limit - spent)
    return BudgetResponse(
        month=now.strftime("%Y-%m"),
        spent_usd=spent.quantize(Decimal("0.000001")),
        limit_usd=limit,
        remaining_usd=remaining.quantize(Decimal("0.000001")),
        warning=limit > 0 and spent >= limit * Decimal("0.8"),
        over_budget=limit > 0 and spent > limit,
        by_purpose=[
            BudgetPurposeResponse(
                purpose=str(purpose),
                cost_usd=Decimal(str(cost or 0)).quantize(Decimal("0.000001")),
                runs=int(runs or 0),
            )
            for purpose, cost, runs in rows
        ],
    )
