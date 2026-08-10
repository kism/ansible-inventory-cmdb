"""Test the logger of the app."""

import logging
from typing import TYPE_CHECKING

from fastapi import FastAPI

from ansibleinventorycmdb import create_app
from ansibleinventorycmdb.config import Config

if TYPE_CHECKING:
    import pytest


def test_config_invalid_log_level(tmp_path, get_test_config, caplog: pytest.LogCaptureFixture):
    """Test that an invalid log level doesn't stop the app."""
    caplog.set_level(logging.WARNING)
    app = create_app(Config(**get_test_config("logging_invalid_log_level.yml")), instance_path=str(tmp_path))
    # TEST: App still starts
    assert isinstance(app, FastAPI)
    # TEST: Assert that the invalid logging level message gets logged
    assert "Invalid logging level" in caplog.text
