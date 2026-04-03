"""Logging bootstrap with structured, production-friendly format."""

from __future__ import annotations

import logging
from logging.config import dictConfig


def configure_logging(level: str = "INFO") -> None:
    """Configure logging for console output with structured key/value fields."""
    resolved_level = getattr(logging, level.upper(), logging.INFO)

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s level=%(levelname)s logger=%(name)s message=%(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%SZ",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "level": resolved_level,
                }
            },
            "root": {
                "handlers": ["console"],
                "level": resolved_level,
            },
        }
    )