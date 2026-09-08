import json
import logging

import pytest

from internal_py_lib import (
    JsonFormatter,
    LoggingConfigurator,
    configure_logging,
    get_logger,
)
from internal_py_lib.logging_config import _MANAGED_HANDLER_ATTR


@pytest.fixture(autouse=True)
def _reset_root_logger():
    """Snapshot and restore the root logger, and reset the singleton, per test."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    root.handlers = []
    LoggingConfigurator.reset()
    yield
    for h in root.handlers[:]:
        root.removeHandler(h)
        h.close()
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    LoggingConfigurator.reset()


def _managed_handlers(root):
    return [h for h in root.handlers if getattr(h, _MANAGED_HANDLER_ATTR, False)]


# --- Singleton behavior -----------------------------------------------------


def test_singleton_returns_same_instance():
    a = LoggingConfigurator()
    b = LoggingConfigurator()
    assert a is b


def test_singleton_instance_classmethod():
    assert LoggingConfigurator.instance() is None
    created = LoggingConfigurator()
    assert LoggingConfigurator.instance() is created


def test_reset_clears_singleton():
    first = LoggingConfigurator()
    LoggingConfigurator.reset()
    second = LoggingConfigurator()
    assert first is not second


def test_later_call_updates_settings_in_place():
    LoggingConfigurator(level="DEBUG", fmt="json")
    same = LoggingConfigurator(level="WARNING")  # only override level
    assert same.level == "WARNING"
    assert same.fmt == "json"  # previous setting preserved


def test_singleton_shares_one_handler():
    LoggingConfigurator().configure()
    LoggingConfigurator().configure()
    LoggingConfigurator().configure()
    root = logging.getLogger()
    assert len(_managed_handlers(root)) == 1


# --- configure() core behavior ---------------------------------------------


def test_configure_defaults():
    root = LoggingConfigurator().configure()
    assert root.level == logging.INFO
    handlers = _managed_handlers(root)
    assert len(handlers) == 1
    assert isinstance(handlers[0].formatter, logging.Formatter)
    assert not isinstance(handlers[0].formatter, JsonFormatter)


def test_level_from_string_argument():
    root = LoggingConfigurator(level="DEBUG").configure()
    assert root.level == logging.DEBUG


def test_level_from_int_argument():
    root = LoggingConfigurator(level=logging.WARNING).configure()
    assert root.level == logging.WARNING


def test_level_from_env(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    root = LoggingConfigurator().configure()
    assert root.level == logging.ERROR


def test_invalid_level_raises():
    with pytest.raises(ValueError):
        LoggingConfigurator(level="NOPE").configure()


def test_json_format_selected_via_argument():
    root = LoggingConfigurator(fmt="json").configure()
    handler = _managed_handlers(root)[0]
    assert isinstance(handler.formatter, JsonFormatter)


def test_json_format_selected_via_env(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "json")
    root = LoggingConfigurator().configure()
    handler = _managed_handlers(root)[0]
    assert isinstance(handler.formatter, JsonFormatter)


def test_invalid_format_raises():
    with pytest.raises(ValueError):
        LoggingConfigurator(fmt="xml").configure()


def test_invalid_stream_raises():
    with pytest.raises(ValueError):
        LoggingConfigurator(stream="socket").configure()


# --- configure_logging() wrapper --------------------------------------------


def test_wrapper_configures_and_is_idempotent():
    configure_logging()
    configure_logging()
    configure_logging()
    root = logging.getLogger()
    assert len(_managed_handlers(root)) == 1


def test_wrapper_uses_singleton():
    configure_logging(level="DEBUG")
    assert LoggingConfigurator.instance() is not None
    assert LoggingConfigurator.instance().level == "DEBUG"


# --- JsonFormatter ----------------------------------------------------------


def test_json_formatter_produces_valid_json():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="svc",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    out = json.loads(formatter.format(record))
    assert out["level"] == "INFO"
    assert out["logger"] == "svc"
    assert out["message"] == "hello world"
    assert "timestamp" in out


def test_json_formatter_includes_extra_fields():
    formatter = JsonFormatter()
    record = logging.LogRecord(
        name="svc",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="event",
        args=(),
        exc_info=None,
    )
    record.request_id = "abc-123"
    out = json.loads(formatter.format(record))
    assert out["request_id"] == "abc-123"


def test_json_formatter_serializes_exception():
    formatter = JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord(
            name="svc",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )
    out = json.loads(formatter.format(record))
    assert "exception" in out
    assert "ValueError: boom" in out["exception"]


# --- get_logger + end-to-end ------------------------------------------------


def test_get_logger_returns_named_logger():
    assert get_logger("my.module").name == "my.module"


def test_end_to_end_json_log_output(capsys):
    LoggingConfigurator(fmt="json", stream="stdout", level="INFO").configure()
    get_logger("integration").info("started", extra={"phase": "boot"})
    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    parsed = json.loads(line)
    assert parsed["message"] == "started"
    assert parsed["phase"] == "boot"
    assert parsed["logger"] == "integration"
