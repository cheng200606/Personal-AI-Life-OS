"""Model budget and usage summary by period, purpose, and provider."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Request
from sqlalchemy import case, func, select

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    BudgetProviderResponse,
    BudgetPurposeResponse,
    BudgetResponse,
)
from personal_ai_life_os.config import Settings
from personal_ai_life_os.models import ModelRun
from personal_ai_life_os.services.graph_extraction import monthly_spend

router = APIRouter(prefix="/budget", tags=["budget"])
FAILURE_STATUSES = ("fallback", "budget_fallback", "budget_exceeded", "consent_withdrawn")


def _period_start(now: datetime, period: str) -> datetime:
    if period == "day":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        return (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@router.get("", response_model=BudgetResponse)
def get_budget(
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
    period: Literal["day", "week", "month"] = "month",
) -> BudgetResponse:
    config: Settings = request.app.state.settings
    now = datetime.now(UTC)
    start_at = _period_start(now, period)
    conditions = [ModelRun.owner_id == user.id, ModelRun.created_at >= start_at]
    spent = session.scalar(
        select(func.coalesce(func.sum(ModelRun.cost_usd), 0)).where(*conditions)
    ) or Decimal(0)
    totals = session.execute(
        select(
            func.count(ModelRun.id),
            func.coalesce(func.sum(ModelRun.input_tokens), 0),
            func.coalesce(func.sum(ModelRun.output_tokens), 0),
            func.coalesce(func.avg(ModelRun.latency_ms), 0),
            func.coalesce(
                func.sum(case((ModelRun.status.in_(FAILURE_STATUSES), ModelRun.cost_usd), else_=0)),
                0,
            ),
        ).where(*conditions)
    ).one()
    purpose_rows = session.execute(
        select(
            ModelRun.purpose,
            func.coalesce(func.sum(ModelRun.cost_usd), 0),
            func.count(ModelRun.id),
        )
        .where(*conditions)
        .group_by(ModelRun.purpose)
        .order_by(ModelRun.purpose)
    ).all()
    provider_rows = session.execute(
        select(
            ModelRun.provider,
            func.coalesce(func.sum(ModelRun.cost_usd), 0),
            func.count(ModelRun.id),
            func.coalesce(func.sum(ModelRun.input_tokens), 0),
            func.coalesce(func.sum(ModelRun.output_tokens), 0),
            func.coalesce(func.avg(ModelRun.latency_ms), 0),
        )
        .where(*conditions)
        .group_by(ModelRun.provider)
        .order_by(ModelRun.provider)
    ).all()
    monthly = monthly_spend(session, user.id, now)
    limit = config.model_monthly_budget_usd
    remaining = max(Decimal(0), limit - monthly)
    return BudgetResponse(
        month=now.strftime("%Y-%m"),
        period=period,
        spent_usd=Decimal(str(spent)).quantize(Decimal("0.000001")),
        limit_usd=limit,
        remaining_usd=remaining.quantize(Decimal("0.000001")),
        warning=limit > 0 and monthly >= limit * Decimal("0.8"),
        over_budget=limit > 0 and monthly > limit,
        runs=int(totals[0] or 0),
        input_tokens=int(totals[1] or 0),
        output_tokens=int(totals[2] or 0),
        avg_latency_ms=int(totals[3] or 0),
        failure_reserve_usd=Decimal(str(totals[4] or 0)).quantize(Decimal("0.000001")),
        by_purpose=[
            BudgetPurposeResponse(
                purpose=str(purpose),
                cost_usd=Decimal(str(cost or 0)).quantize(Decimal("0.000001")),
                runs=int(runs or 0),
            )
            for purpose, cost, runs in purpose_rows
        ],
        by_provider=[
            BudgetProviderResponse(
                provider=str(provider),
                cost_usd=Decimal(str(cost or 0)).quantize(Decimal("0.000001")),
                runs=int(runs or 0),
                input_tokens=int(input_tokens or 0),
                output_tokens=int(output_tokens or 0),
                avg_latency_ms=int(latency or 0),
            )
            for provider, cost, runs, input_tokens, output_tokens, latency in provider_rows
        ],
    )
