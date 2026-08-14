"""Routes, templates and the CMDB refresh loop."""

import asyncio
from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .cmdb import AnsibleCMDB
from .constants import PROGRAM_REPO_URL, PROGRAM_VERSION, version_string
from .logger import get_logger
from .site import TEMPLATES_DIR, dump_vars, group_hosts, group_list

logger = get_logger(__name__)

REFRESH_INTERVAL_SECONDS = 21600  # 6 hours

# The web app serves each page at its bare path; the static site appends /index.html to all of them. See site.py.
ROOT_HREF = "/"
PAGE_SUFFIX = ""

templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter()


class HTMLError(Exception):
    """Raised by page routes to render error.html.j2 with a status code."""

    def __init__(self, message: str, status: int) -> None:
        """Store the message shown on the error page and the status to return."""
        super().__init__(message)
        self.message = message
        self.status = status


async def html_error_handler(request: Request, exc: Exception) -> HTMLResponse:
    """Render error.html.j2 for any HTMLError raised by a page route."""
    assert isinstance(exc, HTMLError)  # noqa: S101 Only registered for HTMLError, this is for the type checker
    return templates.TemplateResponse(
        request,
        "error.html.j2",
        {"error": exc.message, "root_href": ROOT_HREF, "page_suffix": PAGE_SUFFIX},
        status_code=exc.status,
    )


def get_cmdb(request: Request) -> AnsibleCMDB:
    """Dependency, the CMDB built by the app factory."""
    cmdb = getattr(request.app.state, "cmdb", None)
    if not isinstance(cmdb, AnsibleCMDB):
        msg = "No CMDB found, please check the logs."
        raise HTMLError(msg, HTTPStatus.INTERNAL_SERVER_ERROR)
    return cmdb


def get_cmdb_json(request: Request) -> AnsibleCMDB:
    """Dependency for JSON routes, same as get_cmdb but errors as JSON."""
    cmdb = getattr(request.app.state, "cmdb", None)
    if not isinstance(cmdb, AnsibleCMDB):
        raise HTTPException(HTTPStatus.INTERNAL_SERVER_ERROR, "No CMDB found")
    return cmdb


CMDB = Annotated[AnsibleCMDB, Depends(get_cmdb)]
CMDBJson = Annotated[AnsibleCMDB, Depends(get_cmdb_json)]


async def refresh_cmdb(cmdb: AnsibleCMDB) -> None:
    """Build the CMDB, then refresh it every REFRESH_INTERVAL_SECONDS.

    Runs as a background task for the life of the app, so it logs its own failures. Nothing awaits it, an
    unhandled exception here would otherwise be silent and the CMDB would never update again.
    """
    try:
        if not cmdb.ready:
            logger.info("CMDB not ready, building...")
            await cmdb.build()

        if cmdb.refresh_required:
            logger.info("CMDB refresh required, refreshing...")
            await cmdb.refresh()

        while True:
            logger.info("Sleeping for %s seconds before next refresh", REFRESH_INTERVAL_SECONDS)
            await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
            await cmdb.refresh()
    except asyncio.CancelledError:
        logger.info("Refresh task cancelled")
        raise
    except Exception:
        logger.exception("Refresh task died, the CMDB will not update until restart")
        raise


@router.get("/", response_class=HTMLResponse)
def home(request: Request, cmdb: CMDB) -> HTMLResponse:
    """Home webpage, lists the inventories."""
    return templates.TemplateResponse(
        request,
        "home.html.j2",
        {
            "inventories": cmdb.get_inventories(),
            "root_href": ROOT_HREF,
            "page_suffix": PAGE_SUFFIX,
            "program_version": version_string(),
            "program_repo_url": PROGRAM_REPO_URL,
            "generated_at": cmdb.built_at,
        },
    )


@router.get("/inventory/{inventory}", response_class=HTMLResponse)
def inventory(request: Request, inventory: str, cmdb: CMDB) -> HTMLResponse:
    """Table of every host in an inventory."""
    if not cmdb.ready:
        inventory_dict: dict = {"hosts": {}, "groups": {}}
        schema_mapping = {"": "CMDB NOT LOADED, please wait a moment and refresh"}
    else:
        inventory_dict = cmdb.get_inventory(inventory)
        if inventory_dict == {}:
            msg = f"Inventory '{inventory}' not found"
            raise HTMLError(msg, HTTPStatus.NOT_FOUND)
        try:
            schema_mapping = dict(request.app.state.config.cmdb[inventory].schema_mapping)
        except KeyError:
            msg = f"Inventory '{inventory}' found, but inventory schema not found"
            raise HTMLError(msg, HTTPStatus.NOT_FOUND) from None

    return templates.TemplateResponse(
        request,
        "inventory.html.j2",
        {
            "inventory_name": inventory,
            "inventory_dict": inventory_dict,
            "schema_mapping": schema_mapping,
            "groups": group_list(inventory_dict),
            "root_href": ROOT_HREF,
            "page_suffix": PAGE_SUFFIX,
        },
    )


@router.get("/inventory/{inventory}/host/{host}", response_class=HTMLResponse)
def host(request: Request, inventory: str, host: str, cmdb: CMDB) -> HTMLResponse:
    """Page of a single host's vars."""
    if not cmdb.ready:
        host_nice_vars = "CMDB not ready, please wait a moment and refresh."
    else:
        host_vars = cmdb.get_host(inventory, host)
        if "vars" not in host_vars:
            msg = f"Host '{host}' not found"
            raise HTMLError(msg, HTTPStatus.NOT_FOUND)

        host_nice_vars = dump_vars(host_vars["vars"])

    return templates.TemplateResponse(
        request,
        "vars.html.j2",
        {
            "__inventory": inventory,
            "__thing": "host_vars",
            "__host": host,
            "__vars": host_nice_vars,
            "root_href": ROOT_HREF,
            "page_suffix": PAGE_SUFFIX,
        },
    )


@router.get("/inventory/{inventory}/group/{group}", response_class=HTMLResponse)
def group(request: Request, inventory: str, group: str, cmdb: CMDB) -> HTMLResponse:
    """Page of a single group's vars."""
    if not cmdb.ready:
        group_nice_vars = "CMDB not ready, please wait a moment and refresh."
        status = HTTPStatus.TOO_EARLY
    else:
        group_nice_vars = dump_vars(cmdb.get_group(inventory, group))
        status = HTTPStatus.OK

    return templates.TemplateResponse(
        request,
        "vars.html.j2",
        {
            "__inventory": inventory,
            "__thing": "group_vars",
            "__host": group,
            "__vars": group_nice_vars,
            "root_href": ROOT_HREF,
            "page_suffix": PAGE_SUFFIX,
        },
        status_code=status,
    )


@router.get("/inventory/{inventory}/group/{group}/json")
def group_json(inventory: str, group: str, cmdb: CMDBJson) -> dict:
    """Map hostnames to their vars for every host in a group."""
    if not cmdb.ready:
        raise HTTPException(HTTPStatus.SERVICE_UNAVAILABLE, "CMDB not ready")

    inventory_dict = cmdb.get_inventory(inventory)
    if inventory_dict == {}:
        raise HTTPException(HTTPStatus.NOT_FOUND, f"Inventory '{inventory}' not found")

    hosts = group_hosts(inventory_dict, group)
    if hosts is None:
        raise HTTPException(HTTPStatus.NOT_FOUND, f"Group '{group}' not found")

    return hosts


@router.get("/health")
def health() -> dict:
    """Health check endpoint."""
    return {"version": PROGRAM_VERSION}
