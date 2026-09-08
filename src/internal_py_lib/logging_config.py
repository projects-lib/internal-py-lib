import json
import logging
import os
import sys
import threading
from typing import Any, Optional, Union

__all__ = [
    "LoggingConfigurator",
    "configure_logging",
    "get_logger",
    "JsonFormatter",
]

DEFAULT_LEVEL = "INFO"
DEFAULT_FORMAT = "plain"
DEFAULT_STREAM = "stdout"
DEFAULT_DATEFMT = "%Y-%m-%dT%H:%M:%S%z"
_PLAIN_FMT = "%(asctime)s %(levelname)s %(name)s - %(message)s"

# Marker attached to handlers created by this module so we can find and replace
# them on subsequent calls instead of stacking duplicates.
_MANAGED_HANDLER_ATTR = "_internal_py_lib_managed"

# Standard LogRecord attributes that should not be treated as "extra" fields
# when serializing to JSON.
_RESERVED_RECORD_ATTRS = frozenset(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def __init__(self, datefmt: Optional[str] = None):
        super().__init__(datefmt=datefmt)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = self.formatStack(record.stack_info)

        # Merge user-supplied `extra=` fields.
        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_ATTRS and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, default=str, ensure_ascii=False)


def _resolve_level(level: Union[str, int, None]) -> int:
    # Coerce a level name or number into a numeric logging level.
    if level is None:
        level = os.getenv("LOG_LEVEL", DEFAULT_LEVEL)
    if isinstance(level, int):
        return level
    level_str = str(level).strip().upper()
    if level_str.isdigit():
        return int(level_str)
    resolved = logging.getLevelName(level_str)
    if not isinstance(resolved, int):
        raise ValueError(f"Unknown log level: {level!r}")
    return resolved


def _resolve_stream(stream: Optional[str]):
    name = (stream or os.getenv("LOG_STREAM", DEFAULT_STREAM)).strip().lower()
    if name == "stderr":
        return sys.stderr
    if name == "stdout":
        return sys.stdout
    raise ValueError(f"Unknown log stream: {stream!r} (expected 'stdout' or 'stderr')")


def _build_formatter(fmt: Optional[str], datefmt: str) -> logging.Formatter:
    style = (fmt or os.getenv("LOG_FORMAT", DEFAULT_FORMAT)).strip().lower()
    if style == "json":
        return JsonFormatter(datefmt=datefmt)
    if style == "plain":
        return logging.Formatter(_PLAIN_FMT, datefmt=datefmt)
    raise ValueError(f"Unknown log format: {fmt!r} (expected 'plain' or 'json')")


class LoggingConfigurator:
    # Singleton that centralizes root-logger configuration.
    _instance: Optional["LoggingConfigurator"] = None
    _lock = threading.Lock()

    def __new__(
        cls,
        level: Union[str, int, None] = None,
        fmt: Optional[str] = None,
        stream: Optional[str] = None,
        datefmt: Optional[str] = None,
    ) -> "LoggingConfigurator":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(
        self,
        level: Union[str, int, None] = None,
        fmt: Optional[str] = None,
        stream: Optional[str] = None,
        datefmt: Optional[str] = None,
    ):

        if not getattr(self, "_initialized", False):
            self.level = level
            self.fmt = fmt
            self.stream = stream
            self.datefmt = datefmt
            self._initialized = True
        else:
            if level is not None:
                self.level = level
            if fmt is not None:
                self.fmt = fmt
            if stream is not None:
                self.stream = stream
            if datefmt is not None:
                self.datefmt = datefmt

    def configure(self) -> logging.Logger:
        resolved_level = _resolve_level(self.level)
        resolved_datefmt = self.datefmt or os.getenv("LOG_DATEFMT", DEFAULT_DATEFMT)
        formatter = _build_formatter(self.fmt, resolved_datefmt)
        target_stream = _resolve_stream(self.stream)

        root = logging.getLogger()
        root.setLevel(resolved_level)

        for handler in list(root.handlers):
            if getattr(handler, _MANAGED_HANDLER_ATTR, False):
                root.removeHandler(handler)
                handler.close()

        handler = logging.StreamHandler(target_stream)
        handler.setLevel(resolved_level)
        handler.setFormatter(formatter)
        setattr(handler, _MANAGED_HANDLER_ATTR, True)
        root.addHandler(handler)

        return root

    @classmethod
    def instance(cls) -> Optional["LoggingConfigurator"]:
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._instance = None


def configure_logging(
    level: Union[str, int, None] = None,
    fmt: Optional[str] = None,
    stream: Optional[str] = None,
    datefmt: Optional[str] = None,
) -> logging.Logger:
    return LoggingConfigurator(
        level=level, fmt=fmt, stream=stream, datefmt=datefmt
    ).configure()


def get_logger(name: Optional[str] = None) -> logging.Logger:
    return logging.getLogger(name)