import logging
import os
import pickle
import re
from pprint import pformat
from urllib.parse import urlparse

import requests
import yaml

logger = logging.getLogger(__name__)

CACHE_FILE = "instance" + os.sep + "cache.pkl"


class AnsibleCMDB:
    inventories: dict = {}

    def __init__(self, inventory_dict: dict):
        for inventory_name, inventory_in_dict in inventory_dict.items():
            self.inventories[inventory_name] = {
                "url": inventory_in_dict["inventory_url"],
                "base_url": re.sub(r"/inventory.*", "", inventory_in_dict["inventory_url"]),
            }

        self._setup_url_cache()

        for inventory_name, inventory_tmp_dict in self.inventories.items():
            inventory_tmp_dict["hosts"] = self._build_cmdb_hosts(
                inventory_name=inventory_name, inventory_dict=inventory_tmp_dict
            )
            inventory_tmp_dict["groups"] = self._build_cmdb_groups(
                inventory_name=inventory_name, inventory_dict=inventory_tmp_dict
            )

        # logger.info(f"CMDB: {pformat(self.inventories)}")

        with open("instance" + os.sep + "cmdb.yml", "w") as cmdb_file:
            yaml.dump(self.inventories, cmdb_file)

    def _setup_url_cache(self):
        """Setup the URL cache."""
        self.url_cache: dict = {}
        if os.path.isfile(CACHE_FILE):
            with open(CACHE_FILE, "rb") as cache_file:
                self.url_cache = pickle.load(cache_file)

        if not self.url_cache:
            self.url_cache = {}

    def get_inventories(self):
        return self.inventories

    def get_inventory(self, inventory: str):
        return self.inventories[inventory]

    def get_group(self, inventory: str, group: str):
        return self.inventories[inventory][group]

    def _build_cmdb_groups(self, inventory_name: str, inventory_dict: dict):
        inventory_yaml = self._get_yaml(inventory_dict["url"])

        groups: dict = {}
        for group in inventory_yaml:
            groups[group] = {}

        for group in groups:
            self._set_group_vars(group, groups[group], inventory_dict["base_url"])

        return groups

    def _build_cmdb_hosts(self, inventory_name: str, inventory_dict: dict):
        """Build the CMDB from the inventory."""

        print(pformat(inventory_name))
        print(pformat(inventory_dict))
        inventory_yaml = self._get_yaml(inventory_dict["url"])

        hosts: dict = {}
        for group in inventory_yaml:
            for host in inventory_yaml[group]["hosts"]:
                hosts[host] = {"groups": [], "vars": {}}

        for host in hosts:
            hosts[host]["groups"] = self._get_groups_of_host(host, inventory_yaml)
            assert isinstance(hosts[host]["groups"], list)

        for host in hosts:
            self._set_host_vars(host, hosts[host]["vars"], inventory_dict["base_url"])
            assert isinstance(hosts[host]["vars"], dict)

        # Get the inline vars for each host
        for host in hosts:
            self._set_host_vars_from_inventory(host, hosts, inventory_yaml)
            assert isinstance(hosts[host]["vars"], dict)

        return hosts

    def _set_host_vars_from_inventory(self, host: str, hosts: dict, inventory_yaml: dict) -> None:
        """Set the vars of a host from the inventory."""
        for group in inventory_yaml:
            if host in inventory_yaml[group]["hosts"] and inventory_yaml[group]["hosts"][host]:
                for key, value in inventory_yaml[group]["hosts"][host].items():
                    hosts[host]["vars"][key] = value

    def _get_groups_of_host(self, host: str, inventory_yaml: dict) -> list:
        """Get the groups of a host."""
        host_groups = []

        for group in inventory_yaml:
            if host in inventory_yaml[group]["hosts"]:
                host_groups.append(group)

        return host_groups

    def _set_group_vars(self, group: str, group_vars: dict, base_url: str):
        """Get the vars of a group."""

        group_var_urls = [
            f"{base_url}/group_vars/{group}.yml",
            f"{base_url}/inventory/group_vars/{group}.yml",
        ]

        for group_var_url in group_var_urls:
            group_yaml = self._get_yaml(group_var_url)

            if group_yaml:
                for key, value in group_yaml.items():
                    group_vars[key] = value

    def _set_host_vars(self, host: str, host_vars: dict, base_url: str):
        """Get the vars of a host."""
        host_var_urls = [
            f"{base_url}/host_vars/{host}.yml",
            f"{base_url}/inventory/host_vars/{host}.yml",
        ]

        for host_var_url in host_var_urls:
            host_yaml = self._get_yaml(host_var_url)

            if host_yaml:
                for key, value in host_yaml.items():
                    host_vars[key] = value

    def _get_yaml(self, url: str):
        """Get a yaml file from a URL."""
        if url not in self.url_cache:
            logger.info(f"Getting URL: {url}")
            response = requests.get(url, timeout=5)

            temp_text = "" if not response.ok else response.text

            self.url_cache[url] = yaml.safe_load(temp_text)

            with open(CACHE_FILE, "wb") as cache_file:
                pickle.dump(self.url_cache, cache_file, pickle.HIGHEST_PROTOCOL)

        else:
            logger.info(f"Using cached URL: {url}")

        return self.url_cache[url]
