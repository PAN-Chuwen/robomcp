"""FastAPI application factory (`uvicorn robomcp_platform.api.app:create_app --factory`)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine, text

from robomcp_platform.api.deps import SessionDep
from robomcp_platform.api.routes import router
from robomcp_platform.config import Settings, get_settings
from robomcp_platform.db import make_engine, make_sessionmaker
from robomcp_platform.storage import ArtifactStore, make_store


def create_app(settings: Settings | None = None, engine: Engine | None = None,
               store: ArtifactStore | None = None) -> FastAPI:
    settings = settings or get_settings()
    owns_engine = engine is None
    engine = engine or make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        if owns_engine:
            engine.dispose()

    app = FastAPI(title="RoboMCP Platform API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.store = store or make_store(settings)

    @app.get("/healthz")
    def healthz(session: SessionDep) -> dict[str, str]:
        session.execute(text("SELECT 1"))
        return {"status": "ok"}

    app.include_router(router, prefix="/v1")
    return app
