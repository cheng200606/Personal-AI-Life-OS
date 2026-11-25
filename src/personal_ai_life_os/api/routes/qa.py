"""Owner-scoped, evidence-grounded question threads."""

import json
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    QaAnswerResponse,
    QaAskRequest,
    QaMessageResponse,
    QaScopeRequest,
    QaScopeResponse,
    QaThreadCreateRequest,
    QaThreadListResponse,
    QaThreadResponse,
)
from personal_ai_life_os.models import QaMessage, QaThread, utcnow
from personal_ai_life_os.services.graph_qa import (
    QaError,
    answer_question,
    scope_from_dict,
)

router = APIRouter(prefix="/qa", tags=["qa"])
DEFAULT_TITLE = "新的提问"


def _error(error: QaError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    )


def _thread_or_404(session: Session, owner_id: str, thread_id: str) -> QaThread:
    thread = session.scalar(
        select(QaThread).where(QaThread.id == thread_id, QaThread.owner_id == owner_id)
    )
    if thread is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "qa_thread_not_found", "message": "The question thread was not found."},
        )
    return thread


def _message_payload(message: QaMessage) -> QaMessageResponse:
    answer = None
    if message.role == "assistant" and message.answer:
        answer = QaAnswerResponse.model_validate(message.answer)
    return QaMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        answer=answer,
        created_at=message.created_at,
    )


def _thread_payload(thread: QaThread, *, with_messages: bool) -> QaThreadResponse:
    messages = [_message_payload(message) for message in thread.messages] if with_messages else []
    return QaThreadResponse(
        id=thread.id,
        title=thread.title,
        scope=QaScopeRequest.model_validate(thread.scope or {}),
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        messages=messages,
    )


def _scope_dict(payload: QaScopeRequest | None, fallback: dict | None) -> dict:
    if payload is not None:
        return payload.model_dump(mode="json")
    return dict(fallback or {})


@router.get("/scope", response_model=QaScopeResponse)
def last_scope(user: CurrentUserDep, session: SessionDep) -> QaScopeResponse:
    thread = session.scalar(
        select(QaThread)
        .where(QaThread.owner_id == user.id)
        .order_by(QaThread.updated_at.desc(), QaThread.id)
    )
    if thread is None:
        return QaScopeResponse(thread_id=None, scope=QaScopeRequest())
    return QaScopeResponse(
        thread_id=thread.id,
        scope=QaScopeRequest.model_validate(thread.scope or {}),
    )


@router.get("/threads", response_model=QaThreadListResponse)
def list_threads(user: CurrentUserDep, session: SessionDep) -> QaThreadListResponse:
    total = session.scalar(
        select(func.count()).select_from(
            select(QaThread.id).where(QaThread.owner_id == user.id).subquery()
        )
    ) or 0
    threads = list(
        session.scalars(
            select(QaThread)
            .where(QaThread.owner_id == user.id)
            .order_by(QaThread.updated_at.desc(), QaThread.id)
            .limit(50)
        )
    )
    return QaThreadListResponse(
        total=total,
        items=[_thread_payload(thread, with_messages=False) for thread in threads],
    )


@router.post("/threads", response_model=QaThreadResponse, status_code=201)
def create_thread(
    payload: QaThreadCreateRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> QaThreadResponse:
    thread = QaThread(
        owner_id=user.id,
        title=(payload.title or DEFAULT_TITLE).strip()[:240] or DEFAULT_TITLE,
        scope=payload.scope.model_dump(mode="json"),
    )
    session.add(thread)
    session.commit()
    session.refresh(thread)
    return _thread_payload(thread, with_messages=False)


@router.get("/threads/{thread_id}", response_model=QaThreadResponse)
def get_thread(
    thread_id: str, user: CurrentUserDep, session: SessionDep
) -> QaThreadResponse:
    return _thread_payload(_thread_or_404(session, user.id, thread_id), with_messages=True)


@router.post("/threads/{thread_id}/messages", response_model=QaThreadResponse)
def ask_question(
    thread_id: str,
    payload: QaAskRequest,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
) -> QaThreadResponse:
    thread = _thread_or_404(session, user.id, thread_id)
    scope_data = _scope_dict(payload.scope, thread.scope)
    try:
        scope = scope_from_dict(scope_data)
    except QaError as error:
        raise _error(error) from error
    try:
        answer = answer_question(
            session,
            owner_id=user.id,
            question=payload.question,
            scope=scope,
            threshold=request.app.state.settings.graph_extraction_confidence_threshold,
        )
    except QaError as error:
        raise _error(error) from error

    session.add(
        QaMessage(
            owner_id=user.id,
            thread_id=thread.id,
            role="user",
            content=payload.question.strip(),
        )
    )
    session.add(
        QaMessage(
            owner_id=user.id,
            thread_id=thread.id,
            role="assistant",
            content=answer["summary"],
            answer=answer,
            citations=answer["citations"],
            confidence=answer["confidence"],
        )
    )
    thread.scope = answer["scope"]
    if thread.title == DEFAULT_TITLE:
        thread.title = payload.question.strip()[:60]
    thread.updated_at = utcnow()
    session.commit()
    session.refresh(thread)
    return _thread_payload(thread, with_messages=True)


@router.delete("/threads/{thread_id}", status_code=204)
def delete_thread(thread_id: str, user: CurrentUserDep, session: SessionDep) -> Response:
    thread = _thread_or_404(session, user.id, thread_id)
    session.delete(thread)
    session.commit()
    return Response(status_code=204)


@router.get("/threads/{thread_id}/export")
def export_thread(
    thread_id: str,
    user: CurrentUserDep,
    session: SessionDep,
    format: Annotated[str, Query(pattern="^(json|markdown)$")] = "markdown",
) -> Response:
    thread = _thread_or_404(session, user.id, thread_id)
    if format == "json":
        payload = {
            "id": thread.id,
            "title": thread.title,
            "scope": thread.scope,
            "created_at": thread.created_at.isoformat(),
            "updated_at": thread.updated_at.isoformat(),
            "messages": [
                {
                    "id": message.id,
                    "role": message.role,
                    "content": message.content,
                    "answer": message.answer,
                    "created_at": message.created_at.isoformat(),
                }
                for message in thread.messages
            ],
        }
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        media_type = "application/json; charset=utf-8"
        filename = "qa-thread-" + thread.id[:8] + ".json"
    else:
        lines = ["# " + thread.title, ""]
        scope = scope_from_dict(thread.scope)
        lines.append("检索范围：" + json.dumps(scope.as_dict(), ensure_ascii=False))
        lines.append("")
        for message in thread.messages:
            if message.role == "user":
                lines.extend(["## 问：" + message.content, ""])
                continue
            answer = message.answer or {}
            lines.extend(["### 答", str(answer.get("summary") or message.content), ""])
            facts = answer.get("facts") or []
            if facts:
                lines.append("#### 事实")
                for fact in facts:
                    lines.append(
                        f"- [{fact.get('basis')} {fact.get('confidence')}] {fact.get('label')}：{fact.get('detail')}"
                    )
                lines.append("")
            citations = answer.get("citations") or []
            if citations:
                lines.append("#### 引用")
                for citation in citations:
                    lines.append(
                        f"- {citation.get('source_name')} · {citation.get('item_title')}：{citation.get('quote')}"
                    )
                lines.append("")
            missing = answer.get("missing_info") or []
            if missing:
                lines.append("#### 缺失信息")
                lines.extend("- " + item for item in missing)
                lines.append("")
            suggestions = answer.get("suggestions") or []
            if suggestions:
                lines.append("#### 行动建议")
                lines.extend("- " + str(item.get("label")) for item in suggestions)
                lines.append("")
        body = "\n".join(lines)
        media_type = "text/markdown; charset=utf-8"
        filename = "qa-thread-" + thread.id[:8] + ".md"
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": 'attachment; filename="' + filename + '"'},
    )
