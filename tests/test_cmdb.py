"""Tests the AnsibleCMDB object."""

from ansibleinventorycmdb.cmdb import AnsibleCMDB, resolve_vars
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


def test_resolve_vars():
    """TEST: Bare {{ var }} references resolve; anything that can't be resolved is left as written."""
    lookup = "{{ lookup('bitwarden.secrets.lookup', 'x') }}"
    context = {
        "ip": "10.42.0.1",
        "domain": "kg.lan",
        "port": 8427,
        "fqdn": "vic.{{ domain }}",
        "secret": lookup,
        "a": "{{ b }}",
        "b": "{{ a }}",
        "a_list": [1, 2],
    }
    values = {
        "plain": "{{ ip }}",
        "tight": "{{ip}}",
        "embedded": "http://vic.{{ domain }}:{{ port }}",
        "chained": "{{ fqdn }}",
        "unknown": "{{ nope }}",
        "lookup": lookup,
        "via_lookup": "/mnt/{{ secret }}",
        "cycle": "{{ a }}",
        "non_scalar": "{{ a_list }}",
        "nested": {"list": ["{{ ip }}", {"deep": "{{ domain }}"}]},
        "untouched": 5,
    }

    assert resolve_vars(values, context) == {
        "plain": "10.42.0.1",
        "tight": "10.42.0.1",
        "embedded": "http://vic.kg.lan:8427",
        "chained": "vic.kg.lan",
        "unknown": "{{ nope }}",
        "lookup": lookup,
        "via_lookup": "/mnt/{{ secret }}",
        "cycle": "{{ a }}",
        "non_scalar": "{{ a_list }}",
        "nested": {"list": ["10.42.0.1", {"deep": "kg.lan"}]},
        "untouched": 5,
    }


def test_build_resolves_inline_templates(get_test_config, build_cmdb):
    """TEST: A host var referencing another of the host's vars is resolved by the build."""
    cmdb = AnsibleCMDB(Config(**get_test_config("valid.yml")).cmdb)
    build_cmdb(cmdb)

    assert cmdb.get_host("test_main", "hostone")["vars"]["templated_var"] == "hostone.pytest.internal"
