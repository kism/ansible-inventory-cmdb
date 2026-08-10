"""Config model and config file loading tests."""

import logging
import os

import pytest
from pydantic import ValidationError

from ansibleinventorycmdb import create_app
from ansibleinventorycmdb.config import Config, load_config


def test_config_defaults():
    """TEST: An empty config gets the default inventory and logging settings."""
    config = Config()
    assert config.logging.level == "INFO"
    assert config.logging.path == ""
    assert config.cmdb, "Default config has no inventories"


def test_config_valid(get_test_config):
    """TEST: The test config parses into the model."""
    config = Config(**get_test_config("valid.yml"))
    assert config.cmdb["test_main"].inventory_url == "https://pytest.internal/inventory/main.yml"
    assert config.cmdb["test_main"].schema_mapping["ansible_host"] == "Hostname"


def test_config_defaults_are_not_shared():
    """TEST: Mutating one config's defaults doesn't affect the next one."""
    Config().cmdb.clear()
    assert Config().cmdb, "Default cmdb dict is shared between Config instances"


@pytest.mark.parametrize(
    "bad_config",
    [
        {"unexpected_key": True},
        {"cmdb": {"x": {"inventory_url": "", "schema_mapping": {"a": "b"}}}},
        {"cmdb": {"x": {"inventory_url": "https://a.internal/main.yml", "schema_mapping": {}}}},
        {"cmdb": {"x": {"inventory_url": "https://a.internal/main.yml"}}},
        {"logging": {"level": "INFO", "unexpected_key": True}},
    ],
)
def test_config_invalid(bad_config):
    """TEST: Unknown keys and missing/empty required inventory fields are rejected."""
    with pytest.raises(ValidationError):
        Config(**bad_config)


def test_config_file_loading(place_test_config, tmp_path, caplog: pytest.LogCaptureFixture):
    """TEST: Config is loaded from a config.yml in the instance path."""
    place_test_config("valid.yml", tmp_path)

    caplog.set_level(logging.INFO)
    config = load_config(str(tmp_path))

    assert "Loading config from:" in caplog.text
    assert config.cmdb["test_main"].inventory_url == "https://pytest.internal/inventory/main.yml"


def test_config_file_creation(tmp_path, caplog: pytest.LogCaptureFixture):
    """TEST: A default config file is created when none exists."""
    with caplog.at_level(logging.WARNING):
        create_app(instance_path=str(tmp_path))

    assert "No configuration file found, creating at default location:" in caplog.text
    assert os.path.exists(os.path.join(tmp_path, "config.yml"))


def test_config_file_created_is_loadable(tmp_path):
    """TEST: The config file we write out parses back into a Config."""
    load_config(str(tmp_path))
    assert load_config(str(tmp_path)) == Config()
