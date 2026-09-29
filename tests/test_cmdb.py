"""Tests the AnsibleCMDB object."""

from ansibleinventorycmdb.cmdb import AnsibleCMDB
from ansibleinventorycmdb.config import Config


def test_object_creation(get_test_config, build_cmdb):
    """TEST: The CMDB builds from a mocked inventory and exposes its hosts and groups."""
    cmdb = AnsibleCMDB(Config(**get_test_config("valid.yml")).cmdb)

    assert not cmdb.ready

    build_cmdb(cmdb)

    assert cmdb.ready

    inventory = cmdb.get_inventory("test_main")
    assert set(inventory["hosts"]) == {"hostone", "hosttwo", "grouptwo"}
    assert set(inventory["groups"]) == {"all", "groupone", "grouptwo", "groupthree"}

    assert cmdb.get_host("test_main", "hostone")["vars"] != {}
    assert cmdb.get_inventory("nope") == {}
    assert cmdb.get_host("test_main", "nope") == {}
    assert cmdb.get_group("test_main", "nope") == {}


def test_build_writes_nothing_to_disk(tmp_path, get_test_config, build_cmdb, monkeypatch):
    """TEST: A build touches no filesystem. The Worker has none, and a stale cache would outlive a restart."""
    monkeypatch.chdir(tmp_path)

    build_cmdb(AnsibleCMDB(Config(**get_test_config("valid.yml")).cmdb))

    assert list(tmp_path.iterdir()) == []
