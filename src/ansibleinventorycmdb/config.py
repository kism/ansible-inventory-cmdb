"""Config models and loading."""

import os
import pwd

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .logger import LoggingConfig, get_logger

logger = get_logger(__name__)

DEFAULT_INVENTORY_URL = "https://raw.githubusercontent.com/kism/ansible-playbooks/refs/heads/main/inventory/main.yml"


class Inventory(BaseModel):
    """One ansible inventory to present as a CMDB."""

    model_config = ConfigDict(extra="forbid")

    inventory_url: str = Field(min_length=1)
    schema_mapping: dict[str, str] = Field(min_length=1)


def _default_cmdb() -> dict[str, Inventory]:
    """Example inventory, written out when no config file exists anywhere."""
    return {
        "test_main": Inventory(
            inventory_url=DEFAULT_INVENTORY_URL,
            schema_mapping={"ansible_host": "Hostname", "ansible_host_description": "Description"},
        )
    }


class Config(BaseModel):
    """Whole application config, the shape of config.yml."""

    model_config = ConfigDict(extra="forbid")

    cmdb: dict[str, Inventory] = Field(default_factory=_default_cmdb)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def get_instance_path() -> str:
    """Directory for config.yml, the cmdb dump and the url cache."""
    return os.environ.get("AIC_INSTANCE_PATH", os.path.join(os.getcwd(), "instance"))


def get_config_paths(instance_path: str) -> list[str]:
    """Config file locations, in order of precedence."""
    return [
        os.path.join(instance_path, "config.yml"),
        os.path.expanduser("~/.config/ansibleinventorycmdb/config.yml"),
        "/etc/ansibleinventorycmdb/config.yml",
    ]


def load_config(instance_path: str) -> Config:
    """Load config from the first config.yml found, creating one with defaults if none exists."""
    paths = get_config_paths(instance_path)

    for path in paths:
        if os.path.isfile(path):
            logger.info("Loading config from: %s", path)
            with open(path, encoding="utf8") as yaml_file:
                return Config(**(yaml.safe_load(yaml_file) or {}))
        logger.info("No config file found at: %s", path)

    config = Config()
    logger.warning("No configuration file found, creating at default location: %s", paths[0])
    _write_config(config, paths[0])
    return config


def _write_config(config: Config, path: str) -> None:
    """Write a config out as yaml. Only ever used to materialise the defaults."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf8") as yaml_file:
            yaml.safe_dump(config.model_dump(), yaml_file)
    except PermissionError as exc:
        user_account = pwd.getpwuid(os.getuid())[0]
        err = f"Fix permissions: chown {user_account} {path}"
        raise PermissionError(err) from exc
