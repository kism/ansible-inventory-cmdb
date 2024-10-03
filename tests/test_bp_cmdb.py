"""Tests the blueprint's HTTP endpoint."""

from http import HTTPStatus

from flask.testing import FlaskClient


def test_hello(client: FlaskClient):
    """TEST: The default /hello/ response, This one uses the fixture in conftest.py."""
    response = client.get("/inventory/kism_main")
    assert response.status_code == HTTPStatus.OK
