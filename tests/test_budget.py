from datetime import UTC, datetime
from decimal import Decimal

from test_reviews_account import token_for

from personal_ai_life_os.models import ModelRun


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _add_run(client, token: str, purpose: str, cost: str) -> None:
    owner_id = client.get("/api/v1/auth/me", headers=_headers(token)).json()["id"]
    with client.app.state.session_factory() as session:
        session.add(
            ModelRun(
                owner_id=owner_id,
                provider="openai",
                model="synthetic-model",
                purpose=purpose,
                status="succeeded",
                prompt_version="test",
                latency_ms=1,
                input_tokens=1,
                output_tokens=1,
                cost_usd=Decimal(cost),
                created_at=datetime.now(UTC),
            )
        )
        session.commit()


def test_budget_reports_spend_warning_and_overage(client) -> None:
    token = token_for(client, "budget@example.com")
    body = client.get("/api/v1/budget", headers=_headers(token)).json()
    assert body["spent_usd"] == "0.000000"
    assert body["limit_usd"] == "5.00"
    assert body["remaining_usd"] == "5.000000"
    assert body["warning"] is False
    assert body["over_budget"] is False
    assert body["by_purpose"] == []

    _add_run(client, token, "graph_extraction", "4.00")
    warning = client.get("/api/v1/budget", headers=_headers(token)).json()
    assert warning["warning"] is True
    assert warning["over_budget"] is False
    assert warning["remaining_usd"] == "1.000000"
    assert warning["by_purpose"] == [
        {"purpose": "graph_extraction", "cost_usd": "4.000000", "runs": 1}
    ]

    _add_run(client, token, "weekly_review", "1.50")
    over = client.get("/api/v1/budget", headers=_headers(token)).json()
    assert over["warning"] is True
    assert over["over_budget"] is True
    assert over["remaining_usd"] == "0.000000"
    assert {entry["purpose"] for entry in over["by_purpose"]} == {
        "graph_extraction",
        "weekly_review",
    }

    stranger = token_for(client, "budget-stranger@example.com")
    assert client.get("/api/v1/budget", headers=_headers(stranger)).json()["spent_usd"] == "0.000000"
