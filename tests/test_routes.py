"""Tests the HTTP endpoints."""

import time
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from ansibleinventorycmdb.cmdb import AnsibleCMDB
from ansibleinventorycmdb.config import Config

if TYPE_CHECKING:
    from fastapi import FastAPI


@pytest.fixture
def test_cmdb_object(tmp_path, mock_get_inventory_url, get_test_config, build_cmdb):
    """A built CMDB. Its own instance path, so its url cache doesn't collide with the app fixture's."""
    instance_path = tmp_path / "cmdb_fixture"
    instance_path.mkdir()

    cmdb = AnsibleCMDB(instance_path=str(instance_path), inventories=Config(**get_test_config("valid.yml")).cmdb)
    return build_cmdb(cmdb)


def test_get(client: TestClient, app: FastAPI, test_cmdb_object):
    """TEST: Every page endpoint returns OK once the CMDB is built."""
    app.state.cmdb = test_cmdb_object

    endpoints = [
        "/",
        "/inventory/test_main",
        "/inventory/test_main/host/hostone",
        "/inventory/test_main/group/groupthree",
        "/health",
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code == HTTPStatus.OK, endpoint


def test_get_json(client: TestClient, app: FastAPI, test_cmdb_object):
    """TEST: The group json endpoint returns json."""
    app.state.cmdb = test_cmdb_object

    response = client.get("/inventory/test_main/group/groupthree/json")

    assert response.status_code == HTTPStatus.OK
    assert response.headers["content-type"] == "application/json"
    assert isinstance(response.json(), dict)


def test_get_json_all(client: TestClient, app: FastAPI, test_cmdb_object):
    """TEST: The 'all' group returns every host in the inventory."""
    app.state.cmdb = test_cmdb_object

    response = client.get("/inventory/test_main/group/all/json")

    assert response.status_code == HTTPStatus.OK
    assert set(response.json()) == {"hostone", "hosttwo", "grouptwo"}


@pytest.mark.parametrize(
    "endpoint",
    [
        "/inventory/nope",
        "/inventory/test_main/host/nope",
        "/inventory/nope/group/nope/json",
        "/inventory/test_main/group/nope/json",
    ],
)
def test_get_not_found(client: TestClient, app: FastAPI, test_cmdb_object, endpoint):
    """TEST: Unknown inventories, hosts and groups return 404."""
    app.state.cmdb = test_cmdb_object

    assert client.get(endpoint).status_code == HTTPStatus.NOT_FOUND


def test_get_uninitialised(client: TestClient, app: FastAPI):
    """TEST: Every endpoint returns 500 when there is no CMDB."""
    app.state.cmdb = None

    endpoints = [
        "/",
        "/inventory/test_main",
        "/inventory/test_main/host/hostone",
        "/inventory/test_main/group/groupthree",
        "/inventory/test_main/group/groupthree/json",
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR, endpoint


def test_get_not_ready(client: TestClient, app: FastAPI, test_cmdb_object):
    """TEST: Pages render a placeholder rather than erroring while the CMDB is still building."""
    test_cmdb_object.ready = False
    app.state.cmdb = test_cmdb_object

    assert client.get("/inventory/test_main").status_code == HTTPStatus.OK
    assert client.get("/inventory/test_main/host/hostone").status_code == HTTPStatus.OK
    assert client.get("/inventory/test_main/group/groupthree").status_code == HTTPStatus.TOO_EARLY
    assert client.get("/inventory/test_main/group/groupthree/json").status_code == HTTPStatus.SERVICE_UNAVAILABLE


def test_lifespan_builds_cmdb(app: FastAPI):
    """TEST: Entering the lifespan starts the refresh thread, which builds the CMDB."""
    assert not app.state.cmdb.ready

    with TestClient(app) as client:
        deadline = time.monotonic() + 10
        while not app.state.cmdb.ready and time.monotonic() < deadline:
            time.sleep(0.05)

        # Wait for ready before leaving the context, a thread still fetching when requests_mock unpatches
        # would make real requests.
        assert app.state.cmdb.ready, "Refresh thread did not build the CMDB"
        assert client.get("/inventory/test_main").status_code == HTTPStatus.OK


def test_static(client: TestClient):
    """TEST: Static assets, including the fonts subdirectory, are served."""
    assert client.get("/static/zy.css").status_code == HTTPStatus.OK
    assert client.get("/static/fonts/fira-code-400.woff2").status_code == HTTPStatus.OK
