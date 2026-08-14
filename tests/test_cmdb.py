"""Tests the AnsibleCMDB object."""

from ansibleinventorycmdb.cmdb import AnsibleCMDB
from ansibleinventorycmdb.config import Config


def test_object_creation(tmp_path, get_test_config, build_cmdb):
    """TEST: The CMDB builds from a mocked inventory and exposes its hosts and groups."""
    cmdb = AnsibleCMDB(instance_path=str(tmp_path), inventories=Config(**get_test_config("valid.yml")).cmdb)

    assert not cmdb.ready

    build_cmdb(cmdb)

    assert cmdb.ready
    assert not cmdb.refresh_required

    inventory = cmdb.get_inventory("test_main")
    assert set(inventory["hosts"]) == {"hostone", "hosttwo", "grouptwo"}
    assert set(inventory["groups"]) == {"all", "groupone", "grouptwo", "groupthree"}

    assert cmdb.get_host("test_main", "hostone")["vars"] != {}
    assert cmdb.get_inventory("nope") == {}
    assert cmdb.get_host("test_main", "nope") == {}
    assert cmdb.get_group("test_main", "nope") == {}


def test_url_cache_reload(tmp_path, get_test_config, build_cmdb):
    """TEST: A second CMDB picks up the pickled url cache written by the first and flags a refresh."""
    inventories = Config(**get_test_config("valid.yml")).cmdb

    build_cmdb(AnsibleCMDB(instance_path=str(tmp_path), inventories=inventories))

    cmdb = AnsibleCMDB(instance_path=str(tmp_path), inventories=inventories)
    assert cmdb.url_cache != {}
    assert cmdb.refresh_required
