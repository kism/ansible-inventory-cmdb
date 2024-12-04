"""Ansible Inventory CMDB Object."""

import os
import pickle
import re

import requests
import yaml

from .logger import get_logger

logger = get_logger(__name__)


class AnsibleCMDB:
    """Ansible CMDB object."""

    def __init__(self, inventory_dict: dict, instance_path: str) -> None:
        """Initialise the Ansible CMDB object."""
        self._dump_file = os.path.join(instance_path, "cmdb_dump.yml")
        self._cache_file = os.path.join(instance_path, "url_cache.pkl")
        self.inventories: dict[str, dict] = {}
        self.url_cache: dict = {}
        self.ready = False
        self.refresh_required = False

        for inventory_name, inventory_in_dict in inventory_dict.items():
            self.inventories[inventory_name] = {
                "url": inventory_in_dict["inventory_url"],
                "base_url": re.sub(r"/inventory.*", "", inventory_in_dict["inventory_url"]),
            }

        self._load_url_cache()

    def _load_url_cache(self) -> None:
        """Setup the URL cache."""
        if os.path.isfile(self._cache_file):
            with open(self._cache_file, "rb") as cache_file:
                logger.info(f"Loaded URL cache file: {self._cache_file}")
                self.url_cache = pickle.load(cache_file)
                self.refresh_required = True

    def refresh(self) -> None:
        """Refresh the CMDB data."""
        logger.info("Refreshing CMDB")
        self.url_cache = {}
        self.build()
        logger.info("CMDB refresh complete")
        self.refresh_required = False

    def build(self) -> None:
        """Build the CMDB."""
        logger.info("Building CMDB")
        for inventory_tmp_dict in self.inventories.values():
            inventory_tmp_dict["hosts"] = self._build_cmdb_hosts(inventory_dict=inventory_tmp_dict)
            inventory_tmp_dict["groups"] = self._build_cmdb_groups(inventory_dict=inventory_tmp_dict)

        with open(self._dump_file, "w") as dump_file:
            yaml.dump(self.inventories, dump_file, explicit_start=True)

        logger.info("CMDB built")
        self.ready = True

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

    def _build_cmdb_groups(self, inventory_dict: dict) -> dict:
        """Build the CMDB groups from the inventory."""
        inventory_yaml = self._get_yaml(inventory_dict["url"])

        groups: dict = {}
        for group in inventory_yaml:
            groups[group] = {}

        for group in groups:
            self._set_group_vars(group, groups[group], inventory_dict["base_url"])

        return groups

    def _build_cmdb_hosts(self, inventory_dict: dict) -> dict:
        """Build the CMDB hosts from the inventory."""
        inventory_yaml = self._get_yaml(inventory_dict["url"])

        hosts: dict = {}
        for group in inventory_yaml:
            for host in inventory_yaml[group]["hosts"]:
                hosts[host] = {"groups": [], "vars": {}}

        for host in hosts:
            hosts[host]["groups"] = self._get_groups_of_host(host, inventory_yaml)

        for host in hosts:
            self._set_host_vars(host, hosts[host]["vars"], inventory_dict["base_url"])

        # Get the inline vars for each host
        for host in hosts:
            self._set_host_vars_from_inventory(host, hosts, inventory_yaml)

        return hosts

    def _set_host_vars_from_inventory(self, host: str, hosts: dict, inventory_yaml: dict) -> None:
        """Set the vars of a host from the inventory."""
        for group in inventory_yaml:
            if host in inventory_yaml[group]["hosts"] and inventory_yaml[group]["hosts"][host]:
                for key, value in inventory_yaml[group]["hosts"][host].items():
                    hosts[host]["vars"][key] = value

    def _get_groups_of_host(self, host: str, inventory_yaml: dict) -> list:
        """Get the groups of a host."""
        return [group for group in inventory_yaml if host in inventory_yaml[group]["hosts"]]

    def _set_group_vars(self, group: str, group_vars: dict, base_url: str) -> None:
        """Get the vars of a group."""
        group_var_urls = [
            f"{base_url}/group_vars/{group}.yml",
            f"{base_url}/inventory/group_vars/{group}.yml",
        ]

        for group_var_url in group_var_urls:
            group_yaml = self._get_yaml(group_var_url)

            if group_yaml:
                group_vars.update(dict(group_yaml.items()))

    def _set_host_vars(self, host: str, host_vars: dict, base_url: str) -> None:
        """Get the vars of a host."""
        host_var_urls = [
            f"{base_url}/host_vars/{host}.yml",
            f"{base_url}/inventory/host_vars/{host}.yml",
        ]

        for host_var_url in host_var_urls:
            host_yaml = self._get_yaml(host_var_url)

            if host_yaml:
                host_vars.update(dict(host_yaml.items()))

    def _get_yaml(self, url: str) -> dict:
        """Get a yaml file from a URL."""
        if url not in self.url_cache:
            logger.debug(f"Getting URL: {url}")
            try:
                response = requests.get(url, timeout=5)
                temp_text = (
                    "---" "\n" "error: true" "\n" f"message: error getting inventory, HTTP {response.status_code}"
                    if not response.ok
                    else response.text
                )
            except TimeoutError:
                temp_text = "---" "\n" "error: true" "\n" "message: Timeout error" "\n" "exception: TimeoutError"
            except Exception as e:  # noqa: BLE001 This is to prevent a big crash
                temp_text = "---" "\n" "error: true" "\n" "message: Unhandled exception" "\n" f"exception: {e}"

            temp_yaml = yaml.safe_load(temp_text)

            self.url_cache[url] = temp_yaml

            with open(self._cache_file, "wb") as cache_file:
                pickle.dump(self.url_cache, cache_file, pickle.HIGHEST_PROTOCOL)

        else:
            logger.trace(f"Using cached URL: {url}")

        return self.url_cache[url]
