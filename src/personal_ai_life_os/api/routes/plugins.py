"""Local plugin catalog, manifests, invocation, and audit."""

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import func, select

from personal_ai_life_os.api.deps import CurrentUserDep, SessionDep
from personal_ai_life_os.api.schemas import (
    PluginAuditListResponse,
    PluginAuditResponse,
    PluginCatalogEntryResponse,
    PluginCatalogResponse,
    PluginInstallRequest,
    PluginInvokeRequest,
    PluginListResponse,
    PluginResponse,
    PluginStatusRequest,
)
from personal_ai_life_os.models import PluginAuditLog
from personal_ai_life_os.services.plugins import (
    PluginError,
    catalog,
    install_plugin,
    invoke_plugin,
    list_audit,
    list_plugins,
    plugin_payload,
    set_plugin_status,
    uninstall_plugin,
)
from personal_ai_life_os.storage import ObjectStore

router = APIRouter(prefix="/plugins", tags=["plugins"])


def _error(error: PluginError) -> HTTPException:
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message},
    )


@router.get("/catalog", response_model=PluginCatalogResponse)
def plugin_catalog(user: CurrentUserDep) -> PluginCatalogResponse:
    items = [PluginCatalogEntryResponse(**entry) for entry in catalog()]
    return PluginCatalogResponse(total=len(items), items=items)


@router.get("", response_model=PluginListResponse)
def plugins(user: CurrentUserDep, session: SessionDep) -> PluginListResponse:
    items = list_plugins(session, owner_id=user.id)
    return PluginListResponse(
        total=len(items),
        items=[PluginResponse(**plugin_payload(plugin)) for plugin in items],
    )


@router.post("/install", response_model=PluginResponse, status_code=201)
def install(
    payload: PluginInstallRequest,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
) -> PluginResponse:
    try:
        plugin = install_plugin(
            session,
            owner_id=user.id,
            name=payload.name,
            permissions=payload.permissions,
            config=request.app.state.settings,
        )
    except PluginError as error:
        session.rollback()
        raise _error(error) from error
    session.commit()
    session.refresh(plugin)
    return PluginResponse(**plugin_payload(plugin))


@router.post("/{plugin_id}/status", response_model=PluginResponse)
def plugin_status(
    plugin_id: str,
    payload: PluginStatusRequest,
    user: CurrentUserDep,
    session: SessionDep,
) -> PluginResponse:
    try:
        plugin = set_plugin_status(
            session, owner_id=user.id, plugin_id=plugin_id, status=payload.status
        )
    except PluginError as error:
        session.rollback()
        raise _error(error) from error
    session.commit()
    session.refresh(plugin)
    return PluginResponse(**plugin_payload(plugin))


@router.delete("/{plugin_id}", status_code=204)
def uninstall(
    plugin_id: str, user: CurrentUserDep, session: SessionDep
) -> Response:
    try:
        uninstall_plugin(session, owner_id=user.id, plugin_id=plugin_id)
    except PluginError as error:
        session.rollback()
        raise _error(error) from error
    session.commit()
    return Response(status_code=204)


@router.post("/{plugin_id}/invoke")
def invoke(
    plugin_id: str,
    payload: PluginInvokeRequest,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
) -> dict:
    store: ObjectStore = request.app.state.object_store
    try:
        return invoke_plugin(
            session,
            store=store,
            owner_id=user.id,
            plugin_id=plugin_id,
            action=payload.action,
            payload=payload.payload,
            user_timezone=user.timezone,
        )
    except PluginError as error:
        raise _error(error) from error


@router.get("/audit", response_model=PluginAuditListResponse)
def plugin_audit(
    user: CurrentUserDep,
    session: SessionDep,
) -> PluginAuditListResponse:
    total = session.scalar(
        select(func.count()).select_from(
            select(PluginAuditLog.id).where(PluginAuditLog.owner_id == user.id).subquery()
        )
    ) or 0
    return PluginAuditListResponse(
        total=total,
        items=[
            PluginAuditResponse(
                id=entry.id,
                plugin_id=entry.plugin_id,
                action=entry.action,
                status=entry.status,
                detail=entry.detail_json,
                created_at=entry.created_at,
            )
            for entry in list_audit(session, owner_id=user.id)
        ],
    )
