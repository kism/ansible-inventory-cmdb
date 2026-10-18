"""Tests the web app: the API served out of memory, /status, and the frontend's SPA fallback."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from http import HTTPStatus
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from ansibleinventorycmdb.app import create_app
from ansibleinventorycmdb.config import Config

if TYPE_CHECKING:
    from fastapi import FastAPI


def test_serves_every_object(client: TestClient, app: FastAPI, api):
    """TEST: Every object comes back byte for byte at /api/<key>, as the Worker's bucket serves it at <key>."""
    app.state.api = api

    for key, body in api.items():
        response = client.get(f"/api/{key}")
        assert response.status_code == HTTPStatus.OK, key
        assert response.content == body, key
        assert response.headers["content-type"] == "application/json", key


def test_unknown_key(client: TestClient, app: FastAPI, api):
    """TEST: A key that wasn't rendered is a 404, like a missing object in the bucket."""
    app.state.api = api

    for key in ("nope.json", "inventory/nope.json", "inventory/test_main/host/nope.json"):
        assert client.get(f"/api/{key}").status_code == HTTPStatus.NOT_FOUND, key


def test_not_built(client: TestClient):
    """TEST: Before the first build lands, the API answers 503 rather than an empty 200."""
    assert client.get("/api/inventories.json").status_code == HTTPStatus.SERVICE_UNAVAILABLE


def test_status(client: TestClient, app: FastAPI, api):
    """TEST: /status is 503 until a build lands, then 200, with the same body the Worker's /status has."""
    response = client.get("/status")
    assert response.status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.json()["ok"] is False

    app.state.api = api
    app.state.built_at = datetime.now(UTC)

    response = client.get("/status")
    assert response.status_code == HTTPStatus.OK
    assert set(response.json()) == {"ok", "last_build", "age_seconds", "stale_after_seconds"}


def test_health(client: TestClient):
    """TEST: /health answers without a build."""
    assert client.get("/health").status_code == HTTPStatus.OK


def test_lifespan_builds_api(app: FastAPI):
    """TEST: Entering the lifespan starts the refresh task, which builds the API."""
    assert app.state.api is None

    with TestClient(app) as client:
        deadline = time.monotonic() + 10
        while app.state.api is None and time.monotonic() < deadline:
            time.sleep(0.05)

        # Wait for the build before leaving the context, or the task is cancelled mid-fetch.
        assert app.state.api is not None, "Refresh task did not build the API"
        assert "test_main" in client.get("/api/inventories.json").json()["inventories"]
        assert client.get("/status").status_code == HTTPStatus.OK


def test_frontend_spa_fallback(tmp_path, monkeypatch, get_test_config):
    """TEST: Files in the frontend build are served as is, and any other path gets index.html."""
    frontend = tmp_path / "dist"
    (frontend / "static").mkdir(parents=True)
    (frontend / "index.html").write_text("<!doctype html>the app")
    (frontend / "static" / "zy.css").write_text("body {}")
    monkeypatch.setattr("ansibleinventorycmdb.app.FRONTEND_DIR", frontend)

    app = create_app(config=Config(**get_test_config("valid.yml")), instance_path=str(tmp_path))
    client = TestClient(app)

    for path in ("/", "/inventory/test_main", "/inventory/test_main/host/hostone"):
        assert client.get(path).text == "<!doctype html>the app", path
    assert client.get("/static/zy.css").text == "body {}"
    # The fallback is mounted after the API, so an API miss stays an API error rather than becoming the app.
    assert json.loads(client.get("/api/nope.json").content) == {"detail": "CMDB not built yet"}
