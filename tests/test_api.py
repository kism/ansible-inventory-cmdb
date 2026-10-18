"""Test the API renderer, which produces the objects both hosts serve.

The failure mode here is the frontend asking for a key that was never written. Keys are built out of names that
appear in other objects, and a missing one is just a 404. test_every_reference_resolves catches that.
"""

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ansibleinventorycmdb.api import api_status, render_api
from ansibleinventorycmdb.cmdb import AnsibleCMDB
from ansibleinventorycmdb.config import Config, Inventory

# The test inventory references well over this many keys. A count below it means the walk stopped finding them.
MIN_EXPECTED_REFERENCES = 10


def test_expected_keys(api):
    """Every kind of object is rendered."""
    for key in (
        "inventories.json",
        "inventory/test_main.json",
        "inventory/test_main/host/hostone.json",
        "inventory/test_main/group/groupone.json",
        "inventory/test_main/group/all/hosts.json",
    ):
        assert key in api, f"{key} was not rendered, got: {sorted(api)}"


def test_every_object_is_json(api):
    """Every key ends in .json, so none shadows another's "directory", and every body parses."""
    for key, body in api.items():
        assert key.endswith(".json"), key
        json.loads(body)


def test_every_reference_resolves(api):
    """Every key the frontend builds out of another object's contents was actually written."""
    referenced = []
    for name in json.loads(api["inventories.json"])["inventories"]:
        key = f"inventory/{name}.json"
        referenced.append(key)
        if key not in api:
            continue

        inventory = json.loads(api[key])
        for host, host_data in inventory["hosts"].items():
            referenced.append(f"inventory/{name}/host/{host}.json")
            referenced += [f"inventory/{name}/group/{group}.json" for group in host_data["groups"]]
        referenced += [f"inventory/{name}/group/{group}/hosts.json" for group in inventory["groups"]]

    missing = [key for key in referenced if key not in api]
    assert not missing, f"Objects reference keys that were never rendered: {missing}"
    assert len(referenced) > MIN_EXPECTED_REFERENCES, f"Only found {len(referenced)} references"


def test_host_object_contains_vars(api):
    """The host object carries its vars, and the yaml the vars page shows."""
    host = json.loads(api["inventory/test_main/host/hostone.json"])
    assert host["vars"]["ansible_host"] == "hostone.pytest.internal"
    assert "ansible_host: hostone.pytest.internal" in host["vars_yaml"]


def test_group_hosts_all(api):
    """The 'all' group's hosts object has every host in the inventory."""
    assert set(json.loads(api["inventory/test_main/group/all/hosts.json"])) == {"hostone", "hosttwo", "grouptwo"}


def test_dates_serialise():
    """An unquoted date in a vars file arrives as a date, which plain json.dumps refuses."""
    inventories = {
        "x": {
            "url": "https://a.internal/inventory/main.yml",
            "base_url": "https://a.internal",
            "hosts": {"h": {"groups": ["g"], "vars": {"when": date(2024, 1, 2)}}},
            "groups": {"g": {}},
        }
    }
    config = {"x": Inventory(inventory_url="https://a.internal/inventory/main.yml", schema_mapping={"when": "When"})}

    host = json.loads(dict(render_api(inventories, config, ""))["inventory/x/host/h.json"])

    assert host["vars"]["when"] == "2024-01-02"
    assert "when: 2024-01-02" in host["vars_yaml"]


def test_api_status():
    """Not built yet, fresh and stale."""
    assert api_status(None, 60) == {"ok": False, "last_build": None, "age_seconds": None, "stale_after_seconds": 60}
    assert api_status(datetime.now(UTC), 60)["ok"]
    assert not api_status(datetime.now(UTC) - timedelta(seconds=61), 60)["ok"]


def test_build_uses_the_supplied_fetcher(get_test_config):
    """The Worker passes its own fetch, the Workers runtime's, rather than the default httpx one."""
    config = Config(**get_test_config("valid.yml"))
    fetched = []

    async def fetch_text(url: str) -> str | None:
        """Serve the inventory from disk and every var file as empty, without touching the network."""
        fetched.append(url)
        if url.endswith("/inventory/main.yml"):
            return (Path(__file__).parent / "inventories" / "main.yml").read_text()
        return ""

    cmdb = AnsibleCMDB(config.cmdb)
    asyncio.run(cmdb.build(fetch_text))

    assert cmdb.ready
    assert fetched, "the supplied fetcher was never called"
    assert cmdb.get_host("test_main", "hostone")["vars"]["ansible_host"] == "hostone.pytest.internal"


def test_unusable_inventory_is_skipped(get_test_config, caplog):
    """A failed inventory fetch becomes an error dict; walking it as an inventory would die confusingly."""
    config = Config(**get_test_config("valid.yml"))

    async def fetch_text(url: str) -> str | None:  # url unused, the signature is the fetcher contract
        return "not: an inventory"

    cmdb = AnsibleCMDB(config.cmdb)
    asyncio.run(cmdb.build(fetch_text))

    assert cmdb.get_inventory("test_main")["hosts"] == {}
    assert "is not a mapping of groups to hosts" in caplog.text
