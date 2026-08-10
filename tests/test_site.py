"""Test the static site renderer.

The failure mode this feature introduces is a page linking to an object that was never written, since object keys
have to match the app's URL paths exactly. test_every_link_resolves is the check that catches it.
"""

import asyncio
import json
import re
from pathlib import Path

import pytest

from ansibleinventorycmdb.cmdb import AnsibleCMDB
from ansibleinventorycmdb.config import Config
from ansibleinventorycmdb.site import STATIC_ROOT_HREF, render_site

# Root-relative hrefs only, external links are somebody else's problem.
HREF_RE = re.compile(r'href="(/[^"]*)"')

# The test inventory's pages link to well over this. A count below it means the regex stopped matching.
MIN_EXPECTED_LINKS = 10


@pytest.fixture
def site(tmp_path, get_test_config, build_cmdb) -> dict[str, tuple[bytes, str]]:
    """The whole rendered site from the test inventory, keyed by object key."""
    config = Config(**get_test_config("valid.yml"))
    cmdb = build_cmdb(AnsibleCMDB(config.cmdb, str(tmp_path)))
    return {key: (body, content_type) for key, body, content_type in render_site(cmdb.inventories, config.cmdb)}


def test_expected_keys(site):
    """Every page of the app has a corresponding object."""
    for key in (
        "index.html",
        "inventory/test_main/index.html",
        "inventory/test_main/host/hostone/index.html",
        "inventory/test_main/group/groupone/index.html",
        "inventory/test_main/group/all/json",
        "static/zy.css",
        "static/fonts/fira-code-400.woff2",
    ):
        assert key in site, f"{key} was not rendered, got: {sorted(site)}"


def test_every_link_resolves(site):
    """Every root-relative link in every rendered page points at an object that was actually written."""
    dangling = []
    checked = 0

    for key, (body, content_type) in site.items():
        if not content_type.startswith("text/html"):
            continue
        for href in HREF_RE.findall(body.decode()):
            checked += 1
            if href.lstrip("/") not in site:
                dangling.append(f"{key} -> {href}")

    assert not dangling, f"Pages link to objects that were never rendered: {dangling}"
    assert checked > MIN_EXPECTED_LINKS, f"Only checked {checked} links, the regex probably stopped matching"


def test_root_href_is_the_index_object(site):
    """A static host has no index document, so pages must link to the home page by name."""
    body = site["inventory/test_main/index.html"][0].decode()
    assert f'href="{STATIC_ROOT_HREF}"' in body
    assert 'href="/"' not in body


def test_content_types(site):
    """Extensionless HTML keys need an explicit content type, R2 can't guess one."""
    assert site["inventory/test_main/index.html"][1] == "text/html; charset=utf-8"
    assert site["inventory/test_main/group/all/json"][1] == "application/json"
    assert site["static/zy.css"][1] == "text/css"
    assert site["static/fonts/fira-code-400.woff2"][1] == "font/woff2"


def test_group_json_matches_the_route(site, client, build_cmdb, app):
    """The static json object is the same data the JSON route serves."""
    build_cmdb(app.state.cmdb)

    for group in ("all", "groupone", "groupthree"):
        static = json.loads(site[f"inventory/test_main/group/{group}/json"][0])
        served = client.get(f"/inventory/test_main/group/{group}/json").json()
        assert static == served


def test_host_page_contains_vars(site):
    """The host page renders the host's vars, not a 'not ready' placeholder."""
    body = site["inventory/test_main/host/hostone/index.html"][0].decode()
    assert "hostone.pytest.internal" in body


def test_cmdb_without_instance_path_writes_nothing(tmp_path, get_test_config, build_cmdb):
    """The Worker runs with no writable filesystem, so instance_path=None must not touch disk."""
    config = Config(**get_test_config("valid.yml"))
    cmdb = build_cmdb(AnsibleCMDB(config.cmdb))

    assert cmdb.ready
    assert list(tmp_path.iterdir()) == []


def test_build_uses_the_supplied_fetcher(tmp_path, get_test_config):
    """The Worker passes its own fetch, because aiohttp cannot make requests under Pyodide."""
    config = Config(**get_test_config("valid.yml"))
    fetched = []

    async def fetch_text(url: str) -> str | None:
        """Serve the inventory from disk and every var file as empty, without touching the network."""
        fetched.append(url)
        if url.endswith("/inventory/main.yml"):
            return (Path(__file__).parent / "inventories" / "main.yml").read_text()
        return ""

    cmdb = AnsibleCMDB(config.cmdb, str(tmp_path))
    asyncio.run(cmdb.build(fetch_text))

    assert cmdb.ready
    assert fetched, "the supplied fetcher was never called"
    assert cmdb.get_host("test_main", "hostone")["vars"]["ansible_host"] == "hostone.pytest.internal"


def test_unusable_inventory_is_skipped(tmp_path, get_test_config, caplog):
    """A failed inventory fetch becomes an error dict; walking it as an inventory would die confusingly."""
    config = Config(**get_test_config("valid.yml"))

    async def fetch_text(url: str) -> str | None:  # url unused, the signature is the fetcher contract
        return "not: an inventory"

    cmdb = AnsibleCMDB(config.cmdb, str(tmp_path))
    asyncio.run(cmdb.build(fetch_text))

    assert cmdb.get_inventory("test_main")["hosts"] == {}
    assert "is not a mapping of groups to hosts" in caplog.text
