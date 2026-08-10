"""The conftest.py file serves as a means of providing fixtures for an entire directory.

Fixtures defined in a conftest.py can be used by any test in that package without needing to import them.

Tests must always use the tmp_path fixture as an instance_path, otherwise they pollute each other (and your real
instance folder) with config, the cmdb dump and the url cache. The `app` fixture asserts this.
"""

import logging
import shutil
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml
from fastapi.testclient import TestClient

from ansibleinventorycmdb import create_app
from ansibleinventorycmdb.config import Config

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import FastAPI

TEST_INVENTORY_LOCATION = Path(__file__).parent / "inventories"
TEST_CONFIGS_LOCATION = Path(__file__).parent / "configs"


@pytest.fixture
def app(tmp_path, get_test_config) -> FastAPI:
    """This fixture uses the default config within the app."""
    assert "tmp" in str(tmp_path).lower(), "instance_path must be a tmp_path, see this module's docstring"
    return create_app(config=Config(**get_test_config("valid.yml")), instance_path=str(tmp_path))


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Test client for the default app().

    Deliberately not used as a context manager, so the lifespan (and its background refresh thread) doesn't run.
    A thread still building when requests_mock unpatches at teardown makes real requests and flakes other tests.
    test_lifespan_builds_cmdb covers the lifespan, and waits for the build to finish before leaving the context.
    """
    return TestClient(app)


@pytest.fixture
def get_test_config() -> Callable:
    """Function returns a function, which is how it needs to be."""

    def _get_test_config(config_name: str) -> dict:
        """Load a .yml config into a dict."""
        with (TEST_CONFIGS_LOCATION / config_name).open() as file:
            return yaml.safe_load(file)

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


@pytest.fixture(autouse=True)
def mock_get_inventory_url(requests_mock):
    """Every URL the test inventory causes the CMDB to fetch."""
    inventory = (TEST_INVENTORY_LOCATION / "main.yml").read_text()

    return (  # This is silly
        requests_mock.get("https://pytest.internal/inventory/main.yml", text=inventory),
        requests_mock.get("https://pytest.internal/host_vars/hostone.yml", text=""),
        requests_mock.get("https://pytest.internal/host_vars/hosttwo.yml", text=""),
        requests_mock.get("https://pytest.internal/host_vars/groupone.yml", text=""),
        requests_mock.get("https://pytest.internal/host_vars/grouptwo.yml", text=""),
        requests_mock.get("https://pytest.internal/group_vars/all.yml", text=""),
        requests_mock.get("https://pytest.internal/group_vars/groupone.yml", text=""),
        requests_mock.get("https://pytest.internal/group_vars/grouptwo.yml", text=""),
        requests_mock.get("https://pytest.internal/group_vars/groupthree.yml", text=""),
        requests_mock.get("https://pytest.internal/inventory/host_vars/main.yml", text=""),
        requests_mock.get("https://pytest.internal/inventory/host_vars/hostone.yml", text=""),
        requests_mock.get("https://pytest.internal/inventory/host_vars/hosttwo.yml", text=""),
        requests_mock.get("https://pytest.internal/inventory/host_vars/groupone.yml", text=""),
        requests_mock.get("https://pytest.internal/inventory/host_vars/grouptwo.yml", text=""),
        requests_mock.get("https://pytest.internal/inventory/group_vars/all.yml", text=""),
        requests_mock.get("https://pytest.internal/inventory/group_vars/groupone.yml", text=""),
        requests_mock.get("https://pytest.internal/inventory/group_vars/grouptwo.yml", text=""),
        requests_mock.get("https://pytest.internal/inventory/group_vars/groupthree.yml", text=""),
        requests_mock.get(
            "https://raw.githubusercontent.com/kism/ansible-playbooks/refs/heads/main/inventory/main.yml", text=""
        ),
    )


@pytest.fixture(autouse=True)
def error_on_unfetchable_url():
    """AnsibleCMDB swallows fetch failures so one bad URL can't kill the CMDB, which hides unmocked URLs in tests.

    This fails the test instead, so forgetting to add a URL to mock_get_inventory_url isn't a silent empty result.
    """
    failures = []

    class FailOnFetchError(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if "Unhandled exception getting URL" in record.getMessage():
                failures.append(record.getMessage())

    handler = FailOnFetchError()
    logging.getLogger("ansibleinventorycmdb.cmdb").addHandler(handler)
    yield
    logging.getLogger("ansibleinventorycmdb.cmdb").removeHandler(handler)
    assert not failures, f"URL fetch failed, is it mocked in conftest.py? {failures}"


@pytest.fixture(autouse=True)
def error_on_raise_in_thread(monkeypatch):
    """Replaces Thread with a a wrapper to record any exceptions and re-raise them after test execution.

    In case multiple threads raise exceptions only one will be raised.
    """
    last_exception = None

    class ThreadWrapper(threading.Thread):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

        def run(self):
            """Mocked thread.run() method to capture exceptions."""
            try:
                super().run()
            except BaseException as e:
                nonlocal last_exception
                last_exception = e

    monkeypatch.setattr("threading.Thread", ThreadWrapper)
    yield
    if last_exception:
        raise last_exception
