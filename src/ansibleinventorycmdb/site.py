"""Render the whole CMDB as a static site.

Shared by the FastAPI routes and the Cloudflare Worker, so nothing here may import FastAPI. The routes render the
same templates through Jinja2Templates; this module renders them through a plain Jinja2 environment.

Object keys match the app's URL paths exactly (`/inventory/x/host/y` -> `inventory/x/host/y`), so a static host
serves the same links the web app does. The one exception is `/`, which no object key can represent, hence the
`root_href` template variable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from jinja2 import Environment, FileSystemLoader

from .constants import PROGRAM_NAME_WITH_FULL_VERSION, PROGRAM_REPO_URL
from .logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from .config import Inventory

logger = get_logger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

HTML_CONTENT_TYPE = "text/html; charset=utf-8"
JSON_CONTENT_TYPE = "application/json"

# Only the extensions that actually live in static/. stdlib mimetypes doesn't know woff2.
CONTENT_TYPES = {".css": "text/css", ".js": "text/javascript", ".woff2": "font/woff2"}

# A static host has no index document, so every page has to be linked to by name. Naming them all index.html also
# keeps a page key from shadowing the directory its children live in (`inventory/x` vs `inventory/x/host/y`), which
# R2's flat keyspace tolerates but a filesystem — or an `rclone sync` of one — does not.
STATIC_ROOT_HREF = "/index.html"
STATIC_PAGE_SUFFIX = "/index.html"

_env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)


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


def _render(template: str, context: dict) -> bytes:
    """Render a template with the static site's link style."""
    template_obj = _env.get_template(template)
    return template_obj.render(root_href=STATIC_ROOT_HREF, page_suffix=STATIC_PAGE_SUFFIX, **context).encode()


def render_site(
    inventories: dict, cmdb_config: dict[str, Inventory], built_at: str
) -> Iterator[tuple[str, bytes, str]]:
    """Yield (object key, body, content type) for every page and static asset of the CMDB.

    Args:
        inventories: AnsibleCMDB.inventories, after a build.
        cmdb_config: Config.cmdb, for each inventory's schema_mapping.
        built_at: AnsibleCMDB.built_at, shown in the footer. Passed in rather than read from the clock here,
            so it is the time the data was built rather than the time this render happened to run.
    """
    yield (
        "index.html",
        _render(
            "home.html.j2",
            {
                "inventories": inventories,
                "program_version": PROGRAM_NAME_WITH_FULL_VERSION,
                "program_repo_url": PROGRAM_REPO_URL,
                "generated_at": built_at,
            },
        ),
        HTML_CONTENT_TYPE,
    )

    for name, inventory_dict in inventories.items():
        yield from _render_inventory(name, inventory_dict, dict(cmdb_config[name].schema_mapping))

    for path in sorted(STATIC_DIR.rglob("*")):
        if path.is_file():
            key = f"static/{path.relative_to(STATIC_DIR).as_posix()}"
            yield key, path.read_bytes(), CONTENT_TYPES.get(path.suffix, "application/octet-stream")


def _render_inventory(
    name: str, inventory_dict: dict, schema_mapping: dict[str, str]
) -> Iterator[tuple[str, bytes, str]]:
    """Yield the inventory page and every host, group and group json page under it."""
    groups = group_list(inventory_dict)

    yield (
        f"inventory/{name}/index.html",
        _render(
            "inventory.html.j2",
            {
                "inventory_name": name,
                "inventory_dict": inventory_dict,
                "schema_mapping": schema_mapping,
                "groups": groups,
            },
        ),
        HTML_CONTENT_TYPE,
    )

    for host, host_data in inventory_dict.get("hosts", {}).items():
        yield (
            f"inventory/{name}/host/{host}/index.html",
            _render(
                "vars.html.j2",
                {
                    "__inventory": name,
                    "__thing": "host_vars",
                    "__host": host,
                    "__vars": dump_vars(host_data["vars"]),
                },
            ),
            HTML_CONTENT_TYPE,
        )

    for group in inventory_dict.get("groups", {}):
        yield (
            f"inventory/{name}/group/{group}/index.html",
            _render(
                "vars.html.j2",
                {
                    "__inventory": name,
                    "__thing": "group_vars",
                    "__host": group,
                    "__vars": dump_vars(inventory_dict["groups"][group]),
                },
            ),
            HTML_CONTENT_TYPE,
        )

    # The inventory page links a json endpoint per group, plus the synthetic 'all'.
    for group in groups:
        yield (
            f"inventory/{name}/group/{group}/json",
            json.dumps(group_hosts(inventory_dict, group) or {}, indent=2).encode(),
            JSON_CONTENT_TYPE,
        )


def write_site(inventories: dict, cmdb_config: dict[str, Inventory], out_dir: Path, built_at: str) -> int:
    """Write the whole site to a directory. Returns the number of objects written."""
    count = 0
    for key, body, _ in render_site(inventories, cmdb_config, built_at):
        path = out_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        count += 1
    return count


def main() -> None:
    """Build the CMDB and render it to a directory, for the `ansibleinventorycmdb-generate` console script."""
    import asyncio  # noqa: PLC0415 Only needed by the CLI, not by the Worker

    from .cmdb import AnsibleCMDB  # noqa: PLC0415 Avoids an import cycle, site.py is the lower layer
    from .config import get_instance_path, load_config  # noqa: PLC0415
    from .logger import LoggingConfig, setup_logger  # noqa: PLC0415

    if len(sys.argv) != 2:  # noqa: PLR2004 argv[0] plus the output directory
        sys.exit(f"Usage: {Path(sys.argv[0]).name} <output directory>")

    out_dir = Path(sys.argv[1])

    setup_logger(LoggingConfig())
    instance_path = get_instance_path()
    config = load_config(instance_path)

    cmdb = AnsibleCMDB(config.cmdb, instance_path)
    asyncio.run(cmdb.build())

    count = write_site(cmdb.inventories, config.cmdb, out_dir, cmdb.built_at)
    logger.info("Wrote %s objects to %s", count, out_dir)


if __name__ == "__main__":
    main()
