"""Render the built CMDB as the JSON API that both hosts serve.

The web app serves these objects from memory under /api/; the Cloudflare Worker PUTs them into R2, which serves
them at the API's own domain. Same keys and same bytes, so the frontend can't tell the two apart. Nothing here
may import FastAPI: the Worker doesn't install it.

Every key ends in .json. That keeps a key from shadowing the "directory" its children live in (`inventory/x.json`
vs `inventory/x/host/y.json`), which R2's flat keyspace tolerates but a filesystem does not, and it means R2 needs
no index document or rewrite rule to serve any of them.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import yaml

from .cmdb import AnsibleCMDB
from .constants import PROGRAM_REPO_URL, version_string

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .cmdb import FetchText
    from .config import Inventory


def str_presenter(dumper: yaml.representer.SafeRepresenter, data: str) -> yaml.nodes.ScalarNode:
    """YAML string presenter, use |- block."""
    if len(data.splitlines()) > 1:  # check for multiline string
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter)  # Use with safe


def dump_vars(var_dict: dict) -> str:
    """Dump vars as yaml, alphabetically, with an empty dict rendering as just '---'."""
    alphabetical_var_dict = dict(sorted(var_dict.items(), key=lambda item: str(item[0])))
    nice_vars = yaml.dump(alphabetical_var_dict, explicit_start=True, default_flow_style=False, width=1000)
    if nice_vars.strip() == "--- {}":
        nice_vars = "---"
    return nice_vars


def group_list(inventory_dict: dict) -> list[str]:
    """List an inventory's groups, 'all' first. Empty when the inventory has no hosts."""
    if not inventory_dict.get("hosts"):
        return []
    return ["all"] + [group for group in inventory_dict.get("groups", {}) if group != "all"]


def group_hosts(inventory_dict: dict, group: str) -> dict | None:
    """Map hostname to vars for every host in a group. None means the group doesn't exist."""
    hosts_data: dict = inventory_dict.get("hosts", {})

    if group == "all":
        return {hostname: host_data["vars"] for hostname, host_data in hosts_data.items()}

    hosts = {
        hostname: host_data["vars"]
        for hostname, host_data in hosts_data.items()
        if group in host_data.get("groups", [])
    }

    if not hosts and group not in inventory_dict.get("groups", {}):
        return None

    return hosts


def _json(body: object) -> bytes:
    """Serialise one object. default=str because yaml.safe_load turns an unquoted date into a date/datetime."""
    return json.dumps(body, default=str).encode()


def render_api(inventories: dict, cmdb_config: dict[str, Inventory], built_at: str) -> Iterator[tuple[str, bytes]]:
    """Yield (object key, JSON body) for every endpoint of the API.

    Args:
        inventories: AnsibleCMDB.inventories, after a build.
        cmdb_config: Config.cmdb, for each inventory's schema_mapping.
        built_at: AnsibleCMDB.built_at, shown in the footer. Passed in rather than read from the clock here,
            so it is the time the data was built rather than the time this render happened to run.
    """
    yield (
        "inventories.json",
        _json(
            {
                "version": version_string(),
                "repo_url": PROGRAM_REPO_URL,
                "built_at": built_at,
                "inventories": {
                    name: {"url": inventory_dict["url"], "base_url": inventory_dict["base_url"]}
                    for name, inventory_dict in inventories.items()
                },
            }
        ),
    )

    for name, inventory_dict in inventories.items():
        yield from _render_inventory(name, inventory_dict, dict(cmdb_config[name].schema_mapping))


def _render_inventory(name: str, inventory_dict: dict, schema_mapping: dict[str, str]) -> Iterator[tuple[str, bytes]]:
    """Yield the inventory object and every host, group and group hosts object under it."""
    hosts: dict = inventory_dict.get("hosts", {})
    groups = group_list(inventory_dict)

    yield (
        f"inventory/{name}.json",
        _json({"schema_mapping": schema_mapping, "groups": groups, "hosts": hosts}),
    )

    for host, host_data in hosts.items():
        yield (
            f"inventory/{name}/host/{host}.json",
            _json(
                {"groups": host_data["groups"], "vars": host_data["vars"], "vars_yaml": dump_vars(host_data["vars"])}
            ),
        )

    for group, group_vars in inventory_dict.get("groups", {}).items():
        yield (
            f"inventory/{name}/group/{group}.json",
            _json({"vars": group_vars, "vars_yaml": dump_vars(group_vars)}),
        )

    # One per group the inventory object lists, which includes the synthetic 'all'.
    for group in groups:
        yield f"inventory/{name}/group/{group}/hosts.json", _json(group_hosts(inventory_dict, group) or {})


async def build_api(cmdb_config: dict[str, Inventory], fetch_text: FetchText | None = None) -> dict[str, bytes]:
    """Build the CMDB and render the whole API from it, keyed by object key. What both hosts store and serve.

    Args:
        cmdb_config: Config.cmdb, the inventories to build.
        fetch_text: Passed through to AnsibleCMDB.build, see there. The web app leaves it as httpx, the Worker
            hands over the Workers runtime's fetch.
    """
    cmdb = AnsibleCMDB(cmdb_config)
    await cmdb.build(fetch_text)
    return dict(render_api(cmdb.inventories, cmdb_config, cmdb.built_at))


def api_status(last_build: datetime | None, stale_after_seconds: int) -> dict:
    """The /status body both hosts serve: when the API was last written, and whether that was too long ago.

    A failed build writes nothing, so it shows up here as an age that keeps growing rather than as an error. Each
    host supplies its own `last_build` (the web app's clock, R2's upload time) and its own threshold, its refresh
    interval plus slack.
    """
    age = None if last_build is None else round((datetime.now(UTC) - last_build).total_seconds())
    return {
        "ok": age is not None and age < stale_after_seconds,
        "last_build": None if last_build is None else last_build.isoformat(),
        "age_seconds": age,
        "stale_after_seconds": stale_after_seconds,
    }
