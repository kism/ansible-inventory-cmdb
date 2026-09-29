"""Logging setup: a console handler on the root logger, and optionally a rotating file handler."""

import logging
from logging.handlers import RotatingFileHandler

from pydantic import BaseModel, ConfigDict

LOG_FORMAT = "%(asctime)s:%(levelname)s:%(name)s:%(message)s"  # This is the logging message format that I like.

logger = logging.getLogger(__name__)


class LoggingConfig(BaseModel):
    """Logging configuration, path is a file to log to, empty means console only."""

    model_config = ConfigDict(extra="forbid")

    level: str = "INFO"
    path: str = ""


def setup_logger(logging_conf: LoggingConfig, in_logger: logging.Logger | None = None) -> None:
    """Setup the logger, set configuration per logging_conf. Safe to call twice, handlers aren't duplicated.

    Args:
        logging_conf: The logging configuration.
        in_logger: Logger to configure, only passed when testing. Defaults to the root logger, so that uvicorn
            and every other module inherits this config.
    """
    in_logger = in_logger or logging.getLogger()
    formatter = logging.Formatter(LOG_FORMAT)
    # Exact types, not isinstance: RotatingFileHandler *is* a StreamHandler, so a file handler would otherwise
    # be mistaken for the console one and the console would never get a handler.
    existing = {type(handler) for handler in in_logger.handlers}

    if logging.StreamHandler not in existing:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        in_logger.addHandler(console_handler)

    # getLevelNamesMapping() is the source of truth for what setLevel accepts, so there's no list to keep in sync.
    level = logging_conf.level.upper()
    if level not in logging.getLevelNamesMapping():
        logger.warning("❗ Invalid logging level: %s, defaulting to INFO", logging_conf.level)
        level = "INFO"
    in_logger.setLevel(level)

    if logging_conf.path and RotatingFileHandler not in existing:
        # The IsADirectoryError/PermissionError these raise already name the path, so don't reword them.
        file_handler = RotatingFileHandler(logging_conf.path, maxBytes=1000000, backupCount=5)
        file_handler.setFormatter(formatter)
        in_logger.addHandler(file_handler)
        logger.info("Logging to file: %s", logging_conf.path)

    # Configure modules that are external and have their own loggers
    logging.getLogger("uvicorn").setLevel(logging.INFO)  # Web server, info has useful info.
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)  # Logs incoming requests.
    logging.getLogger("httpx").setLevel(logging.WARNING)  # One INFO line per request, ~75 of them per build.

    logger.info("Logger configuration set, level %s", level)
