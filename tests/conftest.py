"""The conftest.py file serves as a means of providing fixtures for an entire directory.

Fixtures defined in a conftest.py can be used by any test in that package without needing to import them.

Tests must always use the tmp_path fixture as an instance_path, otherwise they pollute each other (and your real
instance folder) with config, the cmdb dump and the url cache. The `app` fixture asserts this.

Inventory fetches are served by a real local HTTP server rather than a mocking library. aiohttp mocking libraries
patch aiohttp internals and break on minor aiohttp releases; a socket does not.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING

import pytest
import yaml
from fastapi.testclient import TestClient

from ansibleinventorycmdb import create_app
from ansibleinventorycmdb.config import Config

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import FastAPI

    from ansibleinventorycmdb.cmdb import AnsibleCMDB

TEST_INVENTORY_LOCATION = Path(__file__).parent / "inventories"
TEST_CONFIGS_LOCATION = Path(__file__).parent / "configs"

# The placeholder in tests/configs/*.yml, swapped for the local server's address when a config is loaded.
CONFIG_URL_PLACEHOLDER = "https://pytest.internal"

# Paths the CMDB probes for a host/group that has no vars file. Served as an empty 200, same as a real repo would.
EMPTY_VAR_PATHS = frozenset(
    {
        f"/{scope}/{name}.yml"
        for scope in ("host_vars", "group_vars", "inventory/host_vars", "inventory/group_vars")
        for name in ("main", "all", "hostone", "hosttwo", "groupone", "grouptwo", "groupthree")
    }
)


class _InventoryHandler(BaseHTTPRequestHandler):
    """Serves the test inventory. Anything it doesn't recognise is recorded and 404'd."""

    inventory_body = b""
    unexpected_paths: list[str] = []  # noqa: RUF012 Shared with the fixture, http.server gives no other hook

    def do_GET(self) -> None:
        """Serve the inventory, an empty vars file, or a recorded 404."""
        if self.path == "/inventory/main.yml":
            body = self.inventory_body
        elif self.path in EMPTY_VAR_PATHS:
            body = b""
        else:
            self.unexpected_paths.append(self.path)
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/yaml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args) -> None:  # noqa: A002 Matches BaseHTTPRequestHandler
        """Silence the per-request stderr logging."""


@pytest.fixture(scope="session")
def inventory_server():
    """Local HTTP server serving the test inventory. Returns its base URL."""
    _InventoryHandler.inventory_body = (TEST_INVENTORY_LOCATION / "main.yml").read_bytes()

    server = ThreadingHTTPServer(("127.0.0.1", 0), _InventoryHandler)
    Thread(target=server.serve_forever, daemon=True).start()

    yield f"http://127.0.0.1:{server.server_address[1]}"

    server.shutdown()


@pytest.fixture(autouse=True)
def mock_get_inventory_url(inventory_server):
    """Fail the test if the CMDB asked for a URL the test server doesn't know about.

    AnsibleCMDB swallows fetch failures so one bad URL can't kill the CMDB, which would otherwise turn a typo'd or
    unregistered URL into a silent empty result.
    """
    _InventoryHandler.unexpected_paths.clear()
    yield inventory_server
    unexpected = list(_InventoryHandler.unexpected_paths)
    assert not unexpected, f"CMDB requested unknown paths, add them to EMPTY_VAR_PATHS: {unexpected}"


@pytest.fixture
def app(tmp_path, get_test_config) -> FastAPI:
    """This fixture uses the default config within the app."""
    assert "tmp" in str(tmp_path).lower(), "instance_path must be a tmp_path, see this module's docstring"
    return create_app(config=Config(**get_test_config("valid.yml")), instance_path=str(tmp_path))


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Test client for the default app().

    Deliberately not used as a context manager, so the lifespan (and its background refresh task) doesn't run.
    test_lifespan_builds_cmdb covers the lifespan.
    """
    return TestClient(app)


@pytest.fixture
def get_test_config(inventory_server) -> Callable:
    """Function returns a function, which is how it needs to be."""

    def _get_test_config(config_name: str) -> dict:
        """Load a .yml config into a dict, pointed at the local inventory server."""
        raw = (TEST_CONFIGS_LOCATION / config_name).read_text()
        return yaml.safe_load(raw.replace(CONFIG_URL_PLACEHOLDER, inventory_server))

    return _get_test_config


@pytest.fixture
def place_test_config() -> Callable:
    """Fixture that places a config in the tmp_path.

    Returns: a function to place a config in the tmp_path.
    """

    def _place_test_config(config_name: str, path: str) -> None:
        """Place config in tmp_path by name."""
        shutil.copyfile(TEST_CONFIGS_LOCATION / config_name, Path(path) / "config.yml")

    return _place_test_config


@pytest.fixture
def build_cmdb() -> Callable:
    """Build a CMDB from a sync test. AnsibleCMDB.build/refresh are async, the tests around them are not."""

    def _build_cmdb(cmdb: AnsibleCMDB) -> AnsibleCMDB:
        asyncio.run(cmdb.refresh())
        return cmdb

    return _build_cmdb


@pytest.fixture(autouse=True)
def error_on_unfetchable_url():
    """Fail the test if a fetch raised, since AnsibleCMDB turns those into an error dict rather than propagating."""
    failures = []

    class FailOnFetchError(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if "Unhandled exception getting URL" in record.getMessage():
                failures.append(record.getMessage())

    handler = FailOnFetchError()
    logging.getLogger("ansibleinventorycmdb.cmdb").addHandler(handler)
    yield
    logging.getLogger("ansibleinventorycmdb.cmdb").removeHandler(handler)
    assert not failures, f"URL fetch failed: {failures}"
