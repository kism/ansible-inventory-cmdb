"""Routes: the API, served out of memory the same way R2 serves it for the Worker, and the refresh loop."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .api import api_status, build_api
from .constants import PROGRAM_VERSION

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)

REFRESH_INTERVAL_SECONDS = 21600  # 6 hours
# Two hours of slack past a refresh, the same as the Worker's daily cron: a refresh loop that has died shows up.
STALE_AFTER_SECONDS = REFRESH_INTERVAL_SECONDS + 2 * 60 * 60

router = APIRouter()


async def refresh_api(app: FastAPI) -> None:
    """Build the API, then rebuild it every REFRESH_INTERVAL_SECONDS.

    The result replaces app.state.api only once a build has succeeded, so a failed one keeps serving the last
    good copy, the same as the bucket does for the Worker. Runs as a background task for the life of the app, so
    it logs its own failures. Nothing awaits it, an unhandled exception here would otherwise be silent and the API
    would never update again.
    """
    try:
        while True:
            app.state.api = await build_api(app.state.config.cmdb)
            app.state.built_at = datetime.now(UTC)
            logger.info("Sleeping for %s seconds before next refresh", REFRESH_INTERVAL_SECONDS)
            await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        logger.info("Refresh task cancelled")
        raise
    except Exception:
        logger.exception("Refresh task died, the API will not update until restart")
        raise


@router.get("/health")
def health() -> dict:
    """Health check endpoint."""
    return {"version": PROGRAM_VERSION}


@router.get("/status")
def status(request: Request) -> JSONResponse:
    """When the API was last built, as JSON. 503 once that's too long ago, so an uptime monitor needs no parsing."""
    body = api_status(request.app.state.built_at, STALE_AFTER_SECONDS)
    return JSONResponse(body, status_code=HTTPStatus.OK if body["ok"] else HTTPStatus.SERVICE_UNAVAILABLE)


@router.get("/api/{key:path}")
def api_object(request: Request, key: str) -> Response:
    """Serve one object of the API by its key, exactly the bytes the Worker writes to R2 under the same key."""
    api: dict[str, bytes] | None = request.app.state.api
    if api is None:
        raise HTTPException(HTTPStatus.SERVICE_UNAVAILABLE, "CMDB not built yet")
    if key not in api:
        raise HTTPException(HTTPStatus.NOT_FOUND)
    return Response(api[key], media_type="application/json")
