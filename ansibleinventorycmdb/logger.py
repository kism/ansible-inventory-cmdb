"""Setup the logger functionality for ansibleinventorycmdb."""

import logging
from logging.handlers import RotatingFileHandler

from flask import Flask

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]  # Valid str logging levels.
LOG_FORMAT = "%(asctime)s:%(levelname)s:%(name)s:%(message)s"  # This is the logging message format that I like.


# In flask the root logger doesn't have any handlers, its all in app.logger
# root_logger : root,
# app.logger  : root, ansibleinventorycmdb,
# logger      : root, ansibleinventorycmdb, ansibleinventorycmdb.module_name,
# The issue is that waitress, werkzeug (any any other modules that log) will log separately.
# The aim is, remove the default handler from the flask App and create one on the root logger to apply config to all.

logger = logging.getLogger(__name__)  # This is where we log to in this module, following the standard of every module.


# Pass in the whole app object to make it obvious we are configuring the logger object within the app object.
def setup_logger(app: Flask, logging_conf: dict, in_logger: logging.Logger | None = None) -> None:
    """Setup the logger, set configuration per logging_conf.

    Args:
        app: The Flask app, needed to get the app's logger object.
        logging_conf: The logging configuration {"level": "", "path": ""}
        in_logger: Logger to configure, useful for testing.
    """
    if not in_logger:  # in_logger should only exist when testing with PyTest.
        in_logger = logging.getLogger()  # Get the root logger

    # The root logger has no handlers initially in flask, app.logger does though.
    app.logger.handlers.clear()  # Remove the Flask default handlers

    # If the logger doesn't have a console handler (root logger doesn't by default)
    if not _has_console_handler(in_logger):
        _add_console_handler(in_logger)

    _set_log_level(in_logger, logging_conf["level"])

    # If we are logging to a file
    if not _has_file_handler(in_logger) and logging_conf["path"] != "":
        _add_file_handler(in_logger, logging_conf["path"])

    # Configure modules that are external and have their own loggers
    logging.getLogger("waitress").setLevel(logging.INFO)  # Prod web server, info has useful info.
    logging.getLogger("werkzeug").setLevel(logging.DEBUG)  # Only will be used in dev, debug logs incoming requests.
    logging.getLogger("urllib3").setLevel(logging.WARNING)  # Bit noisy when set to info, used by requests module.

    logger.info("Logger configuration set!")


def _has_file_handler(in_logger: logging.Logger) -> bool:
    """Check if logger has a file handler."""
    return any(isinstance(handler, logging.FileHandler) for handler in in_logger.handlers)


def _has_console_handler(in_logger: logging.Logger) -> bool:
    """Check if logger has a console handler."""
    return any(isinstance(handler, logging.StreamHandler) for handler in in_logger.handlers)


def _add_console_handler(in_logger: logging.Logger) -> None:
    """Add a console handler to the logger."""
    formatter = logging.Formatter(LOG_FORMAT)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    in_logger.addHandler(console_handler)


def _set_log_level(in_logger: logging.Logger, log_level: int | str) -> None:
    """Set the log level of the logger."""
    if isinstance(log_level, str):
        log_level = log_level.upper()
        if log_level not in LOG_LEVELS:
            in_logger.setLevel("INFO")
            logger.warning(
                "❗ Invalid logging level: %s, defaulting to INFO",
                log_level,
            )
        else:
            in_logger.setLevel(log_level)
            logger.debug("Set log level: %s", log_level)
    else:
        in_logger.setLevel(log_level)


def _add_file_handler(in_logger: logging.Logger, log_path: str) -> None:
    """Add a file handler to the logger."""
    try:
        file_handler = RotatingFileHandler(log_path, maxBytes=1000000, backupCount=5)
    except IsADirectoryError as exc:
        err = "You are trying to log to a directory, try a file"
        raise IsADirectoryError(err) from exc
    except PermissionError as exc:
        err = "The user running this does not have access to the file: " + log_path
        raise PermissionError(err) from exc

    formatter = logging.Formatter(LOG_FORMAT)
    file_handler.setFormatter(formatter)
    in_logger.addHandler(file_handler)
    logger.info("Logging to file: %s", log_path)
