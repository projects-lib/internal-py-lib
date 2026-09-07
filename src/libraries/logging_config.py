"""Centralized logging configuration for Python applications.

This module exposes :class:`LoggingConfigurator`, a singleton that configures
the root logger for the whole application. Being a singleton means every part of
the codebase shares one central logging configuration: constructing it again
returns the same instance and reconfigures logging in place instead of creating
a competing setup.

It follows the same design conventions as the rest of the library: values are
read from environment variables with sensible defaults, and every setting can be
overridden via constructor arguments (dependency injection).

Environment variables (all optional when the argument is provided):
    LOG_LEVEL   -> logging level name ("DEBUG", "INFO", "WARNING", ...) or int
    LOG_FORMAT  -> "plain" (default) or "json"
    LOG_STREAM  -> "stdout" (default) or "stderr"
    LOG_DATEFMT -> strftime pattern for timestamps

Typical usage in a consuming application::

    from dotenv import load_dotenv
    from libraries import LoggingConfigurator, ConfigServerClient

    load_dotenv()
    LoggingConfigurator().configure()       # reads LOG_* env vars
    remote = ConfigServerClient().fetch()

Or, mirroring the ``ConfigServerClient`` style, pass settings directly::

    LoggingConfigurator(level="DEBUG", fmt="json").configure()

A thin :func:`configure_logging` wrapper is kept for brevity and backwards
compatibility; it delegates to the singleton.
"""

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
_MANAGED_HANDLER_ATTR = "_libraries_managed"

# Standard LogRecord attributes that should not be treated as "extra" fields
# when serializing to JSON.
_RESERVED_RECORD_ATTRS = frozenset(
    logging.makeLogRecord({}).__dict__.keys()
) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects.

    Any custom fields passed through ``logging``'s ``extra=`` argument are
    included as top-level keys, which makes the output friendly to log
    aggregators (e.g. ELK, Loki, CloudWatch).
    """

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
    """Coerce a level name or number into a numeric logging level."""
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
    """Singleton that centralizes root-logger configuration.

    Only one instance ever exists per process. Instantiating the class again
    returns the same object, so the whole application shares a single logging
    configuration. Passing new arguments on a later call updates the stored
    settings; call :meth:`configure` to (re)apply them to the root logger.

    Args:
        level: Log level name/number. Falls back to ``LOG_LEVEL`` env var, then
            ``"INFO"``.
        fmt: ``"plain"`` or ``"json"``. Falls back to ``LOG_FORMAT`` env var,
            then ``"plain"``.
        stream: ``"stdout"`` or ``"stderr"``. Falls back to ``LOG_STREAM`` env
            var, then ``"stdout"``.
        datefmt: strftime pattern for timestamps. Falls back to ``LOG_DATEFMT``
            env var, then an ISO-8601-like default.
    """

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
        # __init__ runs on every construction even though __new__ returns the
        # same object. On the first call we record all settings; on later calls
        # we only override settings that were explicitly provided, so the shared
        # configuration is updated without being reset by defaults.
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
        """Apply the current settings to the root logger and return it.

        Idempotent: an existing handler installed by this class is replaced
        rather than duplicated, so it is safe to call at every entry point.
        """
        resolved_level = _resolve_level(self.level)
        resolved_datefmt = self.datefmt or os.getenv("LOG_DATEFMT", DEFAULT_DATEFMT)
        formatter = _build_formatter(self.fmt, resolved_datefmt)
        target_stream = _resolve_stream(self.stream)

        root = logging.getLogger()
        root.setLevel(resolved_level)

        # Remove any handler we previously installed so repeated calls do not
        # stack.
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
        """Return the existing singleton instance, or ``None`` if unset."""
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Discard the singleton instance.

        Primarily useful for tests that need a clean slate. This does not touch
        handlers already installed on the root logger.
        """
        with cls._lock:
            cls._instance = None


def configure_logging(
    level: Union[str, int, None] = None,
    fmt: Optional[str] = None,
    stream: Optional[str] = None,
    datefmt: Optional[str] = None,
) -> logging.Logger:
    """Configure the root logger via the :class:`LoggingConfigurator` singleton.

    Thin wrapper kept for brevity and backwards compatibility. Equivalent to
    ``LoggingConfigurator(...).configure()``.
    """
    return LoggingConfigurator(
        level=level, fmt=fmt, stream=stream, datefmt=datefmt
    ).configure()


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a named logger.

    Thin convenience wrapper over :func:`logging.getLogger` so applications can
    obtain loggers through a single import from this library.
    """
    return logging.getLogger(name)
