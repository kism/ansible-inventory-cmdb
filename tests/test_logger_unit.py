"""Logger unit tests."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import pytest

from ansibleinventorycmdb.logger import LoggingConfig, setup_logger

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def logger() -> Generator:
    """Logger to use in unit tests, including cleanup."""
    logger = logging.getLogger("TEST_LOGGER")

    assert len(logger.handlers) == 0  # Check the logger has no handlers

    yield logger

    # Reset the test object since it will persist.
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()


def test_handler_console_added(logger):
    """Test logging console handler."""
    logging_conf = LoggingConfig(level="INFO", path="")  # Test only console handler

    # TEST: Only one handler (console), should exist when no logging path provided
    setup_logger(logging_conf, logger)
    assert len(logger.handlers) == 1

    # TEST: If a console handler exists, another one shouldn't be created
    setup_logger(logging_conf, logger)
    assert len(logger.handlers) == 1


def test_handler_file_added(logger, tmp_path):
    """Test logging file handler."""
    logging_conf = LoggingConfig(level="INFO", path=os.path.join(tmp_path, "test.log"))  # Test file handler

    # TEST: Two handlers when logging to file expected
    setup_logger(logging_conf, logger)
    assert len(logger.handlers) == 2  # noqa: PLR2004 A console and a file handler are expected

    # TEST: Two handlers when logging to file expected, another one shouldn't be created
    setup_logger(logging_conf, logger)
    assert len(logger.handlers) == 2  # noqa: PLR2004 A console and a file handler are expected


def test_logging_to_a_directory_raises(logger, tmp_path):
    """TEST: Logging to a directory fails loudly, with the stdlib's own message naming the path."""
    with pytest.raises(IsADirectoryError):
        setup_logger(LoggingConfig(level="INFO", path=str(tmp_path)), logger)


@pytest.mark.parametrize(
    ("log_level_in", "log_level_expected"),
    [
        ("INFO", 20),
        ("warning", 30),
        ("INVALID", 20),
    ],
)
def test_set_log_level(log_level_in: str, log_level_expected: int, logger):
    """TEST: A valid level is applied, in any case; an invalid one falls back to INFO."""
    setup_logger(LoggingConfig(level=log_level_in), logger)
    assert logger.getEffectiveLevel() == log_level_expected
