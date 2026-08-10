"""FastAPI webapp ansibleinventorycmdb."""

import asyncio
import contextlib
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .cmdb import AnsibleCMDB
from .config import Config, get_instance_path, load_config
from .logger import LoggingConfig, get_logger, setup_logger
from .routes import STATIC_DIR, HTMLError, html_error_handler, refresh_cmdb, router
from .version import __version__

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_logger = get_logger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run the background refresh task for the life of the server."""
    task = asyncio.create_task(refresh_cmdb(app.state.cmdb))
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

    app = FastAPI(lifespan=lifespan, title="Ansible Inventory CMDB", version=__version__)

    app.state.config = config
    app.state.instance_path = instance_path
    app.state.cmdb = AnsibleCMDB(config.cmdb, instance_path)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(router)
    app.add_exception_handler(HTMLError, html_error_handler)

    _logger.info("Starting Web Server, Ansible Inventory CMDB Version: %s", __version__)

    return app
