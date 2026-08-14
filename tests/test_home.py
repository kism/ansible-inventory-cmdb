"""Tests the app home page."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi.testclient import TestClient


def test_home(client: TestClient):
    """Test the home page. This one uses the fixture in conftest.py."""
    response = client.get("/")
    # TEST: HTTP OK
    assert response.status_code == HTTPStatus.OK
    # TEST: Content type
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    # TEST: It is a webpage that we get back
    assert "<!doctype html>" in response.text
