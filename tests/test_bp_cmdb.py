"""Tests the blueprint's HTTP endpoint."""

from http import HTTPStatus

import pytest
from flask.testing import FlaskClient

import ansibleinventorycmdb.bp_cmdb
import ansibleinventorycmdb.cmdb


@pytest.fixture
def test_cmdb_object(tmp_path, mock_get_inventory_url, get_test_config):
    test_config = get_test_config("inventory_defined_valid.yml")

    inventory_dict = test_config["cmdb"]

    cmdb = ansibleinventorycmdb.cmdb.AnsibleCMDB(instance_path=tmp_path, inventory_dict=inventory_dict)

    cmdb.refresh()

    cmdb.get_inventory("test_main")

    return cmdb


def test_get(client: FlaskClient, test_cmdb_object, tmp_path):
    """TEST: The default /hello/ response, This one uses the fixture in conftest.py."""

    ansibleinventorycmdb.bp_cmdb.cmdb = test_cmdb_object

    endpoints = [
        "/inventory/test_main",
        "/inventory/test_main/host/hostone",
        "/inventory/test_main/group/groupthree",
    ]

    for endpoint in endpoints:
        response = client.get(endpoint)
        assert response.status_code == HTTPStatus.OK

