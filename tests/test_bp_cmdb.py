"""Tests the blueprint's HTTP endpoint."""

import logging
from http import HTTPStatus

from flask.testing import FlaskClient

from ansibleinventorycmdb import create_app


def test_hello(client: FlaskClient):
    """TEST: The default /hello/ response, This one uses the fixture in conftest.py."""
    response = client.get("/inventory/kism_main")
    assert response.status_code == HTTPStatus.OK
