"""FastAPI application entry point and dependency wiring."""

import logging
import threading
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from time import monotonic, perf_counter

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from personal_ai_life_os.api.routes.account import router as account_router
from personal_ai_life_os.api.routes.auth import router as auth_router
from personal_ai_life_os.api.routes.health import router as health_router
from personal_ai_life_os.api.routes.imports import router as imports_router
from personal_ai_life_os.api.routes.items import router as items_router
from personal_ai_life_os.api.routes.jobs import router as jobs_router
from personal_ai_life_os.api.routes.metrics import router as metrics_router
from personal_ai_life_os.api.routes.reminders import router as reminders_router
from personal_ai_life_os.api.routes.reviews import router as reviews_router
from personal_ai_life_os.api.routes.sources import router as sources_router
from personal_ai_life_os.config import Settings, settings
from personal_ai_life_os.db import Base, create_database_engine, create_session_factory
from personal_ai_life_os.services.deletion import replay_deletion_tombstones
from personal_ai_life_os.services.jobs import worker_loop
from personal_ai_life_os.storage import ObjectStore, create_object_store

logger = logging.getLogger("personal_ai_life_os")


def create_app(
    config: Settings | None = None,
    *,
    object_store: ObjectStore | None = None,
) -> FastAPI:
    runtime_config = config or settings
    engine = create_database_engine(runtime_config)
    session_factory = create_session_factory(engine)
    store = object_store or create_object_store(runtime_config)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if runtime_config.auto_create_schema:
            Base.metadata.create_all(bind=engine)
        replay_deletion_tombstones(session_factory, store)
        stop_worker = threading.Event()
        worker_thread = None
        if runtime_config.processing_mode == "worker":
            worker_thread = threading.Thread(
                target=worker_loop,
                args=(session_factory, store, runtime_config, stop_worker),
                name="lifeos-background-worker",
                daemon=True,
            )
            worker_thread.start()
        try:
            yield
        finally:
            if worker_thread is not None:
                stop_worker.set()
                worker_thread.join(timeout=runtime_config.worker_lease_seconds + 5)
            engine.dispose()

    application = FastAPI(
        title="Personal AI Life OS",
        description="A user-controlled system for capturing and reviewing personal context.",
        version="0.1.0",
        docs_url=None if runtime_config.app_env == "production" else "/docs",
        redoc_url=None if runtime_config.app_env == "production" else "/redoc",
        lifespan=lifespan,
    )
    application.state.settings = runtime_config
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.object_store = store
    application.state.request_samples = deque(maxlen=1000)
    application.state.rate_events = defaultdict(deque)

    @application.middleware("http")
    async def observe_and_limit(request: Request, call_next):
        route = request.url.path
        key = None
        limit = 0
        window = 0
        if request.method == "POST" and route == "/api/v1/auth/login":
            key, limit, window = "login", 10, 300
        elif request.method == "POST" and route == "/api/v1/auth/register":
            key, limit, window = "register", 5, 3600
        elif request.method == "POST" and route.startswith("/api/v1/sources/") and route.endswith("/imports"):
            key, limit, window = "import", 30, 60
        client_host = request.client.host if request.client else "unknown"
        if key == "import" and not application.state.settings.imports_enabled:
            response = JSONResponse(
                status_code=503,
                content={"error": {"code": "imports_paused", "message": "Uploads are temporarily paused."}},
            )
        elif key:
            events = application.state.rate_events[(key, client_host)]
            instant = monotonic()
            while events and events[0] <= instant - window:
                events.popleft()
            if len(events) >= limit:
                response = JSONResponse(
                    status_code=429,
                    content={"error": {"code": "rate_limited", "message": "Too many requests. Wait before trying again."}},
                    headers={"Retry-After": str(window)},
                )
            else:
                events.append(instant)
                response = None
        else:
            response = None

        started = perf_counter()
        try:
            if response is None:
                response = await call_next(request)
        except Exception:
            application.state.request_samples.append((monotonic(), (perf_counter() - started) * 1000, 500))
            raise
        latency_ms = (perf_counter() - started) * 1000
        application.state.request_samples.append((monotonic(), latency_ms, response.status_code))
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        return response
    application.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_config.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    application.include_router(health_router, prefix="/api/v1")
    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(metrics_router, prefix="/api/v1")
    application.include_router(account_router, prefix="/api/v1")
    application.include_router(sources_router, prefix="/api/v1")
    application.include_router(imports_router, prefix="/api/v1")
    application.include_router(jobs_router, prefix="/api/v1")
    application.include_router(items_router, prefix="/api/v1")
    application.include_router(reviews_router, prefix="/api/v1")
    application.include_router(reminders_router, prefix="/api/v1")

    @application.exception_handler(HTTPException)
    async def http_error_handler(_: Request, error: HTTPException) -> JSONResponse:
        detail = error.detail
        if not isinstance(detail, dict) or "code" not in detail:
            detail = {"code": "request_failed", "message": str(detail)}
        return JSONResponse(
            status_code=error.status_code,
            content={"error": detail},
            headers=error.headers,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, error: RequestValidationError) -> JSONResponse:
        issues = [
            {
                "location": list(issue.get("loc", ())),
                "code": issue.get("type", "invalid"),
                "message": issue.get("msg", "Invalid value."),
            }
            for issue in error.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "issues": issues,
                }
            },
        )

    @application.exception_handler(Exception)
    async def internal_error_handler(_: Request, error: Exception) -> JSONResponse:
        logger.error("Unhandled request failure: %s", type(error).__name__)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "The request could not be completed."}},
        )

    return application


app = create_app()
