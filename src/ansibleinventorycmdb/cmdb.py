"""Ansible Inventory CMDB Object."""

from __future__ import annotations

import asyncio
import contextlib
import os
import pickle
import re
from typing import TYPE_CHECKING

import yaml

from .logger import get_logger

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

    from .config import Inventory

    # Fetch a URL, return its body, or None if the response wasn't OK. See AnsibleCMDB.build.
    FetchText = Callable[[str], Awaitable[str | None]]

logger = get_logger(__name__)

REQUEST_TIMEOUT_SECONDS = 5
CONCURRENT_REQUEST_LIMIT = 10  # Be polite to whatever is hosting the inventory


@contextlib.asynccontextmanager
async def httpx_fetcher() -> AsyncIterator[FetchText]:
    """The default fetcher: one httpx client, wrapped as a plain `url -> body or None` callable.

    httpx is imported here rather than at module level so that importing this module doesn't require it. The
    Cloudflare Worker doesn't use this path — it passes the Workers runtime's own fetch instead, see build().

    follow_redirects is not httpx's default and the raw-file hosts an inventory lives on do redirect. A non-2xx
    response must come back as None rather than raise, so don't add raise_for_status(): a host or group with no vars
    file 404s on every build, and that's the normal case, not an error.
    """
    import httpx  # noqa: PLC0415 Deferred on purpose, see the docstring

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True) as client:

        async def fetch_text(url: str) -> str | None:
            response = await client.get(url)
            return response.text if response.is_success else None

        yield fetch_text


class AnsibleCMDB:
    """Ansible CMDB object."""

    def __init__(self, inventories: dict[str, Inventory], instance_path: str | None = None) -> None:
        """Initialise the Ansible CMDB object.

        Args:
            inventories: The inventories to build, from Config.cmdb.
            instance_path: Where to keep the URL cache and the CMDB dump. None disables both, for environments
                with no writable filesystem, such as a Cloudflare Worker.
        """
        self._instance_path = instance_path
        self._dump_file = os.path.join(instance_path, "cmdb_dump.yml") if instance_path else ""
        self._cache_file = os.path.join(instance_path, "url_cache.pkl") if instance_path else ""
        self.inventories: dict[str, dict] = {}
        self.url_cache: dict = {}
        self.ready = False
        self.refresh_required = False
        # Recreated per build, since an asyncio primitive binds to the loop that first awaits it.
        self._request_limit = asyncio.Semaphore(CONCURRENT_REQUEST_LIMIT)

        for inventory_name, inventory in inventories.items():
            self.inventories[inventory_name] = {
                "url": inventory.inventory_url,
                "base_url": re.sub(r"/inventory.*", "", inventory.inventory_url),
            }

        self._load_url_cache()

    def _load_url_cache(self) -> None:
        """Setup the URL cache."""
        if self._instance_path and os.path.isfile(self._cache_file):
            with open(self._cache_file, "rb") as cache_file:
                logger.info(f"Loaded URL cache file: {self._cache_file}")
                self.url_cache = pickle.load(cache_file)
                self.refresh_required = True

    def _write_output(self) -> None:
        """Write the URL cache and the CMDB dump to disk.

        Called once per build. Fetches run concurrently, so a per-fetch cache write would race itself.
        """
        with open(self._cache_file, "wb") as cache_file:
            pickle.dump(self.url_cache, cache_file, pickle.HIGHEST_PROTOCOL)

        with open(self._dump_file, "w") as dump_file:
            yaml.dump(self.inventories, dump_file, explicit_start=True)

    async def refresh(self, fetch_text: FetchText | None = None) -> None:
        """Refresh the CMDB data. See build() for fetch_text."""
        logger.info("Refreshing CMDB")
        self.url_cache = {}
        await self.build(fetch_text)
        logger.info("CMDB refresh complete")
        self.refresh_required = False

    async def build(self, fetch_text: FetchText | None = None) -> None:
        """Build the CMDB.

        Args:
            fetch_text: How to fetch a URL, as `url -> body or None`. Defaults to httpx. The Cloudflare Worker
                passes the Workers runtime's `fetch` instead — that's the path known to work there, and it keeps
                the Worker from depending on how Pyodide patches an HTTP client.
        """
        logger.info("Building CMDB")
        self._request_limit = asyncio.Semaphore(CONCURRENT_REQUEST_LIMIT)

        if fetch_text is None:
            async with httpx_fetcher() as default_fetch_text:
                await self._build_inventories(default_fetch_text)
        else:
            await self._build_inventories(fetch_text)

        if self._instance_path:
            await asyncio.to_thread(self._write_output)  # Blocking IO, keep it off the event loop

        logger.info("CMDB built")
        self.ready = True

    async def _build_inventories(self, fetch_text: FetchText) -> None:
        """Fetch and populate the hosts and groups of every inventory."""
        for inventory_tmp_dict in self.inventories.values():
            inventory_tmp_dict["hosts"] = await self._build_cmdb_hosts(inventory_tmp_dict, fetch_text)
            inventory_tmp_dict["groups"] = await self._build_cmdb_groups(inventory_tmp_dict, fetch_text)

    def get_inventories(self) -> dict:
        """Get the inventories."""
        return self.inventories

    def get_inventory(self, inventory: str) -> dict:
        """Get an inventory."""
        try:
            return self.inventories[inventory]
        except KeyError:
            return {}

    def get_host(self, inventory: str, host: str) -> dict:
        """Get a hosts vars."""
        try:
            return self.inventories[inventory]["hosts"][host]
        except KeyError:
            return {}

    def get_group(self, inventory: str, group: str) -> dict:
        """Get a groups vars."""
        try:
            return self.inventories[inventory]["groups"][group]
        except KeyError:
            return {}

    async def _build_cmdb_groups(self, inventory_dict: dict, fetch_text: FetchText) -> dict:
        """Build the CMDB groups from the inventory."""
        inventory_yaml = await self._get_yaml(inventory_dict["url"], fetch_text)

        if not self._usable_inventory(inventory_yaml, inventory_dict["url"]):
            return {}

        groups: dict = {group: {} for group in inventory_yaml}

        await asyncio.gather(
            *[
                self._set_group_vars(group, group_vars, inventory_dict["base_url"], fetch_text)
                for group, group_vars in groups.items()
            ]
        )

        return groups

    async def _build_cmdb_hosts(self, inventory_dict: dict, fetch_text: FetchText) -> dict:
        """Build the CMDB hosts from the inventory."""
        inventory_yaml = await self._get_yaml(inventory_dict["url"], fetch_text)

        if not self._usable_inventory(inventory_yaml, inventory_dict["url"]):
            return {}

        hosts: dict = {}
        for group in inventory_yaml:
            for host in inventory_yaml[group]["hosts"]:
                hosts[host] = {"groups": [], "vars": {}}

        for host, host_data in hosts.items():
            host_data["groups"] = self._get_groups_of_host(host, inventory_yaml)

        await asyncio.gather(
            *[self._set_host_vars(host, hosts[host]["vars"], inventory_dict["base_url"], fetch_text) for host in hosts]
        )

        # Get the inline vars for each host
        for host in hosts:
            self._set_host_vars_from_inventory(host, hosts, inventory_yaml)

        return hosts

    def _usable_inventory(self, inventory_yaml: dict, url: str) -> bool:
        """Whether a fetched inventory can be walked as `{group: {"hosts": {...}}}`.

        _get_yaml turns a failed fetch into an `{"error": True, ...}` dict, which otherwise gets walked as if it
        were an inventory and dies on `True["hosts"]` several frames away from the actual problem.
        """
        if not inventory_yaml:
            return False

        if not all(isinstance(group, dict) and "hosts" in group for group in inventory_yaml.values()):
            logger.error("Inventory at %s is not a mapping of groups to hosts, skipping it: %s", url, inventory_yaml)
            return False

        return True

    def _set_host_vars_from_inventory(self, host: str, hosts: dict, inventory_yaml: dict) -> None:
        """Set the vars of a host from the inventory."""
        for group in inventory_yaml:
            if host in inventory_yaml[group]["hosts"] and inventory_yaml[group]["hosts"][host]:
                for key, value in inventory_yaml[group]["hosts"][host].items():
                    hosts[host]["vars"][key] = value

    def _get_groups_of_host(self, host: str, inventory_yaml: dict) -> list:
        """Get the groups of a host."""
        return [group for group in inventory_yaml if host in inventory_yaml[group]["hosts"]]

    async def _set_group_vars(self, group: str, group_vars: dict, base_url: str, fetch_text: FetchText) -> None:
        """Get the vars of a group. Fetched in order, the inventory/ path overrides the top level one."""
        group_var_urls = [
            f"{base_url}/group_vars/{group}.yml",
            f"{base_url}/inventory/group_vars/{group}.yml",
        ]

        for group_var_url in group_var_urls:
            group_yaml = await self._get_yaml(group_var_url, fetch_text)

            if group_yaml:
                group_vars.update(dict(group_yaml.items()))

    async def _set_host_vars(self, host: str, host_vars: dict, base_url: str, fetch_text: FetchText) -> None:
        """Get the vars of a host. Fetched in order, the inventory/ path overrides the top level one."""
        host_var_urls = [
            f"{base_url}/host_vars/{host}.yml",
            f"{base_url}/inventory/host_vars/{host}.yml",
        ]

        for host_var_url in host_var_urls:
            host_yaml = await self._get_yaml(host_var_url, fetch_text)

            if host_yaml:
                host_vars.update(dict(host_yaml.items()))

    async def _get_yaml(self, url: str, fetch_text: FetchText) -> dict:
        """Get a yaml file from a URL."""
        if url not in self.url_cache:
            logger.debug(f"Getting URL: {url}")
            try:
                async with self._request_limit:
                    body = await fetch_text(url)

                if body is None:
                    return {}

                temp_yaml = yaml.safe_load(body)

            except TimeoutError:
                logger.warning("Timeout getting URL: %s", url)
                temp_yaml = {"error": True, "message": "Timeout error", "exception": "TimeoutError"}
            except Exception as e:  # noqa: BLE001 One bad inventory URL shouldn't take down the whole CMDB
                logger.warning("Unhandled exception getting URL %s: %s", url, e)
                temp_yaml = {"error": True, "message": "Unhandled exception", "exception": str(e)}

            self.url_cache[url] = temp_yaml

        else:
            logger.trace(f"Using cached URL: {url}")

        return self.url_cache[url]
