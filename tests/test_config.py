"""App testing different config behaviours."""

import logging
import os

import pytest

from ansibleinventorycmdb import create_app


def test_config_valid(tmp_path, get_test_config):
    """Test that the app can load config and the testing attribute is set."""
    # TEST: Testing attribute set
    app = create_app(get_test_config("testing_true_valid.yml"), instance_path=tmp_path)
    assert app.testing, "Flask testing config item not being set correctly."

    # TEST: Testing attribute not set.
    # The config loaded sets testing to False, do not use this config for any other test.
    app = create_app(get_test_config("testing_false_valid.yml"), instance_path=tmp_path)
    assert not app.testing, "Flask testing config item not being set correctly."


def test_config_file_loading(place_test_config, tmp_path, caplog: pytest.LogCaptureFixture):
    """Test config file loading, use tmp_path."""
    place_test_config("testing_true_valid.yml", tmp_path)

    # TEST: Config file is created when no test_config is provided.
    caplog.set_level(logging.INFO)
    create_app(test_config=None, instance_path=tmp_path)
    assert "Using this path as it's the first one that was found" in caplog.text


def test_config_file_creation(tmp_path, caplog: pytest.LogCaptureFixture):
    """TEST: that file is created when no config is provided.."""
    with caplog.at_level(logging.WARNING):
        create_app(test_config=None, instance_path=tmp_path)

    assert "No configuration file found, creating at default location:" in caplog.text
    assert os.path.exists(os.path.join(tmp_path, "config.yml"))
