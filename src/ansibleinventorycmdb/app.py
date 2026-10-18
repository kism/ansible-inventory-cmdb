"""The FastAPI web app: the `create_app` factory and the lifespan that owns the refresh task."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException  # What StaticFiles raises; FastAPI's is a subclass of it

from .config import Config, get_instance_path, load_config
from .constants import PROGRAM_NAME_WITH_VERSION, PROGRAM_VERSION
from .logger import LoggingConfig, setup_logger
from .routes import refresh_api, router

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from starlette.responses import Response
    from starlette.types import Scope

_logger = logging.getLogger(__name__)

# `pnpm build` writes the frontend here. It's read out of the checkout rather than shipped in the package, which is
# how the README runs the server; anywhere else, there is no frontend to serve and the API still works.
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"


class SPAStaticFiles(StaticFiles):
    """The built frontend, with index.html standing in for any path that isn't a file.

    The frontend routes on the URL path, so a reload on /inventory/x/host/y has to get the app back, the same as
    the Worker's `not_found_handling: single-page-application` does.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Serve the file at path, or index.html if there isn't one."""
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != HTTPStatus.NOT_FOUND:
                raise
            return await super().get_response("index.html", scope)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Run the background refresh task for the life of the server."""
    task = asyncio.create_task(refresh_api(app))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def create_app(config: Config | None = None, instance_path: str | None = None) -> FastAPI:
    """Create and configure an instance of the FastAPI application."""
    instance_path = instance_path or get_instance_path()

    setup_logger(LoggingConfig())  # Setup logger with defaults so config loading gets logged
    config = config or load_config(instance_path)
    setup_logger(config.logging)  # Setup logger with the real config

    _logger.debug("Instance path is: %s", instance_path)
    _logger.debug("Config: %s", config)

    app = FastAPI(lifespan=lifespan, title="Ansible Inventory CMDB", version=PROGRAM_VERSION)

    app.state.config = config
    app.state.instance_path = instance_path
    app.state.api = None  # Object key -> JSON body, set by the refresh task once the first build lands
    app.state.built_at = None

    app.include_router(router)

    if not (FRONTEND_DIR / "index.html").is_file():
        _logger.warning("No frontend at %s, run `pnpm build`. Serving the API only.", FRONTEND_DIR)
    # Mounted last, so the API routes are matched first. check_dir=False so a missing build 404s instead of
    # failing startup.
    app.mount("/", SPAStaticFiles(directory=FRONTEND_DIR, check_dir=False), name="frontend")

    _logger.info("Starting Web Server, %s", PROGRAM_NAME_WITH_VERSION)

    return app
