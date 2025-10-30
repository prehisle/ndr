import json
import logging
from logging.config import dictConfig


def setup_logging() -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {
                    "()": JsonFormatter,
                },
                "plain": {
                    "format": "%(levelname)s %(name)s: %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                },
                "startup_console": {
                    "class": "logging.StreamHandler",
                    "formatter": "plain",
                },
            },
            "root": {
                "level": "INFO",
                "handlers": ["console"],
            },
            "loggers": {
                "app.startup": {
                    "handlers": ["startup_console"],
                    "level": "INFO",
                    "propagate": False,
                }
            },
        }
    )


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            payload.update(record.extra)
        return json.dumps(payload, ensure_ascii=False)
