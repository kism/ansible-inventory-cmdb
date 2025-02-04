"""The conftest.py file serves as a means of providing fixtures for an entire directory.

Fixtures defined in a conftest.py can be used by any test in that package without needing to import them.
"""

import os
import shutil
import threading
from collections.abc import Callable

import pytest
import yaml
from flask import Flask
from flask.testing import FlaskClient, FlaskCliRunner

from ansibleinventorycmdb import create_app

TEST_INVENTORY_LOCATION = os.path.join(os.getcwd(), "tests", "inventories")
TEST_CONFIGS_LOCATION = os.path.join(os.getcwd(), "tests", "configs")


def pytest_configure():
    """This is a magic function for adding things to pytest?"""
    pytest.TEST_CONFIGS_LOCATION = TEST_CONFIGS_LOCATION


@pytest.fixture
def app(tmp_path, get_test_config) -> Flask:
    """This fixture uses the default config within the flask app."""
    return create_app(test_config=get_test_config("testing_true_valid.yml"), instance_path=tmp_path)


@pytest.fixture
def client(tmp_path, app: Flask) -> FlaskClient:
    """This returns a test client for the default app()."""
    return app.test_client()


@pytest.fixture
def runner(tmp_path, app: Flask) -> FlaskCliRunner:
    """TODO?????"""
    return app.test_cli_runner()


@pytest.fixture
def get_test_config() -> Callable:
    """Function returns a function, which is how it needs to be."""

    def _get_test_config(config_name: str) -> dict:
        """Load all the .yml configs into a single dict."""
        filepath = os.path.join(TEST_CONFIGS_LOCATION, config_name)

        with open(filepath) as file:
            return yaml.safe_load(file)

    return _get_test_config


@pytest.fixture
def place_test_config() -> Callable:
    """Fixture that places a config in the tmp_path.

    Returns: a function to place a config in the tmp_path.
    """

    def _place_test_config(config_name: str, path: str) -> None:
        """Place config in tmp_path by name."""
        filepath = os.path.join(TEST_CONFIGS_LOCATION, config_name)

        shutil.copyfile(filepath, os.path.join(path, "config.yml"))

    return _place_test_config


@pytest.fixture(autouse=True)
def mock_get_inventory_url(requests_mock):
    """Return a podcast definition from the config."""

    filepath = os.path.join(TEST_INVENTORY_LOCATION, "main.yml")

    with open(filepath) as file:
        inventory = file.read()

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
