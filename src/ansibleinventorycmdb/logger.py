"""Setup the logger functionality for ansibleinventorycmdb."""

import logging
import typing
from logging.handlers import RotatingFileHandler
from typing import cast

from pydantic import BaseModel, ConfigDict

LOG_LEVELS = [
    "TRACE",
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
]  # Valid str logging levels.
LOG_FORMAT = "%(asctime)s:%(levelname)s:%(name)s:%(message)s"  # This is the logging message format that I like.
TRACE_LEVEL_NUM = 5


class CustomLogger(logging.Logger):
    """Custom logger to appease mypy."""

    def trace(self, message, *args: typing.Any, **kws: typing.Any) -> None:  # noqa: ANN001, ANN401
        """Create logger level for trace."""
        if self.isEnabledFor(TRACE_LEVEL_NUM):
            # Yes, logger takes its '*args' as 'args'.
            self._log(TRACE_LEVEL_NUM, message, args, **kws)


logging.addLevelName(TRACE_LEVEL_NUM, "TRACE")
logging.setLoggerClass(CustomLogger)


class LoggingConfig(BaseModel):
    """Logging configuration, path is a file to log to, empty means console only."""

    model_config = ConfigDict(extra="forbid")

    level: str = "INFO"
    path: str = ""


# This is where we log to in this module, following the standard of every module.
# I don't use the function so we can have this at the top
logger = cast("CustomLogger", logging.getLogger(__name__))


# We configure the root logger so that uvicorn and any other module that logs inherits our config.
# root_logger : root,
# logger      : root, ansibleinventorycmdb, ansibleinventorycmdb.module_name,


def setup_logger(logging_conf: LoggingConfig, in_logger: logging.Logger | None = None) -> None:
    """Setup the logger, set configuration per logging_conf.

    Args:
        logging_conf: The logging configuration.
        in_logger: Logger to configure, useful for testing.
    """
    if not in_logger:  # in_logger should only exist when testing with PyTest.
        in_logger = logging.getLogger()  # Get the root logger

    # If the logger doesn't have a console handler (root logger doesn't by default)
    if not _has_console_handler(in_logger):
        _add_console_handler(in_logger)

    _set_log_level(in_logger, logging_conf.level)

    # If we are logging to a file
    if not _has_file_handler(in_logger) and logging_conf.path != "":
        _add_file_handler(in_logger, logging_conf.path)

    # Configure modules that are external and have their own loggers
    logging.getLogger("uvicorn").setLevel(logging.INFO)  # Web server, info has useful info.
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)  # Logs incoming requests.
    logging.getLogger("httpx").setLevel(logging.WARNING)  # One INFO line per request, ~75 of them per build.

    logger.info("Logger configuration set!")


def get_logger(name: str) -> CustomLogger:
    """Get a logger with the name provided."""
    return cast("CustomLogger", logging.getLogger(name))


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
            logger.trace("Set log level: %s", log_level)
            logger.debug("Set log level: %s", log_level)
            logger.info("Set log level: %s", log_level)
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
