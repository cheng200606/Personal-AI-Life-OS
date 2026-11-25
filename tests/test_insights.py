from test_reviews_account import import_memory, token_for

from personal_ai_life_os.models import GraphEntity, GraphEvidence, GraphRelation


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + token}


def _setup(client, token: str) -> dict[str, str]:
    source_id, item_ids = import_memory(client, token)
    owner_id = client.get("/api/v1/auth/me", headers=_headers(token)).json()["id"]
    ids: dict[str, str] = {}
    with client.app.state.session_factory() as session:

        def add_entity(
            key: str,
            entity_type: str,
            name: str,
            summary: str | None,
            quote: str | None,
            item_index: int = 0,
        ) -> str:
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
            ids[key] = entity.id
            if quote is not None:
                session.add(
                    GraphEvidence(
                        owner_id=owner_id,
                        entity_id=entity.id,
                        source_id=source_id,
                        source_item_id=item_ids[item_index],
                        quote=quote,
                        locator={"section": key},
                        confidence=0.9,
                        availability="active",
                    )
                )
            return entity.id

        add_entity(
            "goal",
            "goal",
            "证据图谱问答目标",
            "截止 2026-11-20 完成",
            "截止 2026-11-20 完成证据图谱问答",
        )
        add_entity(
            "goal_no_evidence",
            "goal",
            "没有证据的目标",
            None,
            None,
        )
        add_entity(
            "commitment",
            "commitment",
            "回复评审承诺",
            "截止 2026-11-18 回复评审",
            "截止 2026-11-18 回复评审意见",
        )
        add_entity(
            "stalled",
            "project",
            "停滞项目",
            "项目停在原型阶段",
            "项目停在原型阶段",
        )
        add_entity(
            "active",
            "project",
            "活跃项目",
            "正在推进的项目",
            "正在推进的项目",
            1,
        )
        add_entity(
            "task",
            "task",
            "任务 A",
            "项目的下一步任务",
            "任务的下一步",
            1,
        )
        add_entity(
            "skill",
            "skill",
            "Python",
            "后端实现技能",
            "写了导入脚本",
        )
        session.add(
            GraphRelation(
                owner_id=owner_id,
                from_entity_id=ids["active"],
                to_entity_id=ids["task"],
                relation_type="has_task",
                confidence=0.9,
                status="active",
                created_by="model",
            )
        )
        session.commit()
    return ids


def test_four_rule_types_trigger_with_evidence(client) -> None:
    token = token_for(client, "insights-rules@example.com")
    _setup(client, token)
    response = client.get("/api/v1/insights/rules", headers=_headers(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 4
    by_rule: dict[str, list[dict]] = {}
    for insight in body["items"]:
        by_rule.setdefault(insight["rule"], []).append(insight)
        assert insight["trigger"]
        assert 0 <= insight["confidence"] <= 1
        assert insight["suggestion"]
        assert insight["severity"] in ("high", "medium", "low")
        assert insight["insight_key"].startswith(insight["rule"] + ":")
    assert "goal_delay" in by_rule
    assert "commitment_follow_up" in by_rule
    assert "project_stalled" in by_rule
    assert "skill_evidence_gap" in by_rule
    goal_no_evidence = next(
        insight
        for insight in by_rule["goal_delay"]
        if insight["entity_name"] == "没有证据的目标"
    )
    assert goal_no_evidence["evidence"] == []
    assert "没有可用的进展证据" in goal_no_evidence["trigger"]
    assert all(
        insight["entity_name"] != "活跃项目"
        for insight in by_rule.get("project_stalled", [])
    )
    for insight in by_rule["goal_delay"] + by_rule["commitment_follow_up"]:
        if insight["entity_name"] != "没有证据的目标":
            assert insight["evidence"]


def test_dismissed_insights_do_not_repeat_and_can_restore(client) -> None:
    token = token_for(client, "insights-dismiss@example.com")
    _setup(client, token)
    body = client.get("/api/v1/insights/rules", headers=_headers(token)).json()
    target = next(item for item in body["items"] if item["rule"] == "skill_evidence_gap")

    dismissed = client.post(
        "/api/v1/insights/rules/dismiss",
        headers=_headers(token),
        json={
            "insight_key": target["insight_key"],
            "rule": target["rule"],
            "entity_id": target["entity_id"],
            "reason": "已知的合成误报",
        },
    )
    assert dismissed.status_code == 201, dismissed.text
    assert dismissed.json()["dismissed"] is True

    filtered = client.get("/api/v1/insights/rules", headers=_headers(token)).json()
    assert filtered["dismissed_total"] == 1
    assert all(item["insight_key"] != target["insight_key"] for item in filtered["items"])

    repeated = client.post(
        "/api/v1/insights/rules/dismiss",
        headers=_headers(token),
        json={"insight_key": target["insight_key"], "rule": target["rule"]},
    )
    assert repeated.status_code == 201

    included = client.get(
        "/api/v1/insights/rules?include_dismissed=true", headers=_headers(token)
    ).json()
    restored_item = next(
        item for item in included["items"] if item["insight_key"] == target["insight_key"]
    )
    assert restored_item["dismissed"] is True
    assert restored_item["dismissed_reason"] == "已知的合成误报"

    restored = client.delete(
        "/api/v1/insights/rules/dismissals/" + target["insight_key"],
        headers=_headers(token),
    )
    assert restored.status_code == 204
    after = client.get("/api/v1/insights/rules", headers=_headers(token)).json()
    assert any(item["insight_key"] == target["insight_key"] for item in after["items"])


def test_insights_are_owner_scoped(client) -> None:
    token = token_for(client, "insights-owner@example.com")
    _setup(client, token)
    assert client.get("/api/v1/insights/rules", headers=_headers(token)).json()["total"] > 0
    stranger = token_for(client, "insights-stranger@example.com")
    assert client.get("/api/v1/insights/rules", headers=_headers(stranger)).json()["total"] == 0
