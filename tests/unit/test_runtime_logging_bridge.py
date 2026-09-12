"""Unit tests for `breezy.runtime.logging_bridge`.

No network I/O and no hardcoded dates -- these tests exercise stdlib
`logging` plumbing and a fake Nautilus logger only.

`_installed_handler` is module-global state (the bridge attaches to the
process-wide `breezy` logger), so every test resets it via an autouse
fixture: `uninstall()` before AND after each test, so a failure mid-test
never leaks a handler into the next test.
"""

from __future__ import annotations

import io
import logging

import pytest

from breezy.runtime import logging_bridge
from breezy.runtime.logging_bridge import (
    BREEZY_LOGGER_NAME,
    NautilusLoggingBridgeHandler,
    ensure_stderr_visible,
    install,
    is_installed,
    uninstall,
)

_TEST_LOGGER_NAME = "breezy.unit_test.boot_window"


class FakeNautilusLogger:
    """Records every forwarded call, mirroring `SupportsNautilusLog`."""

    def __init__(self, *, raise_on: str | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._raise_on = raise_on

    def _record(self, level: str, message: str) -> None:
        if self._raise_on == level:
            raise RuntimeError(f"nautilus logger blew up on {level}")
        self.calls.append((level, message))

    def debug(self, message: str) -> None:
        self._record("debug", message)

    def info(self, message: str) -> None:
        self._record("info", message)

    def warning(self, message: str) -> None:
        self._record("warning", message)

    def error(self, message: str) -> None:
        self._record("error", message)


@pytest.fixture(autouse=True)
def _clean_bridge_state() -> object:
    uninstall()
    yield
    uninstall()


@pytest.fixture(autouse=True)
def _clean_boot_window_handlers() -> object:
    """``ensure_stderr_visible`` attaches to whatever logger name a caller
    passes -- unlike the bridge itself, that is not module-global state, so
    this repeats the same tear-down for the one dedicated test logger name
    used below."""
    yield
    test_logger = logging.getLogger(_TEST_LOGGER_NAME)
    for handler in list(test_logger.handlers):
        test_logger.removeHandler(handler)


def _breezy_child_logger(name: str = "breezy.unit_test") -> logging.Logger:
    return logging.getLogger(name)


def test_record_reaches_fake_nautilus_logger_with_correct_message() -> None:
    fake = FakeNautilusLogger()
    install(fake)
    logger = _breezy_child_logger()

    logger.info("hello from breezy")

    assert fake.calls == [("info", "hello from breezy")]


@pytest.mark.parametrize(
    ("stdlib_level", "expected_method"),
    [
        (logging.DEBUG, "debug"),
        (logging.INFO, "info"),
        (logging.WARNING, "warning"),
        (logging.ERROR, "error"),
        (logging.CRITICAL, "error"),
    ],
    ids=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
)
def test_level_mapping_is_explicit_and_complete(stdlib_level: int, expected_method: str) -> None:
    fake = FakeNautilusLogger()
    install(fake)
    logger = _breezy_child_logger()

    logger.log(stdlib_level, "level-mapped message")

    assert len(fake.calls) == 1
    actual_method, message = fake.calls[0]
    assert actual_method == expected_method
    assert message == "level-mapped message"


def test_double_install_forwards_one_log_call_as_exactly_one_record() -> None:
    fake = FakeNautilusLogger()
    install(fake)
    install(fake)
    logger = _breezy_child_logger()

    logger.info("only once")

    assert fake.calls == [("info", "only once")]


def test_double_install_returns_the_same_handler_instance() -> None:
    fake = FakeNautilusLogger()
    first = install(fake)
    second = install(fake)

    assert first is second


def test_uninstall_detaches_so_later_records_are_never_forwarded() -> None:
    fake = FakeNautilusLogger()
    install(fake)
    uninstall()
    logger = _breezy_child_logger()

    logger.info("should not be forwarded")

    assert fake.calls == []


def test_uninstall_is_safe_to_call_when_nothing_is_installed() -> None:
    uninstall()  # already uninstalled by the autouse fixture; must not raise

    assert logging_bridge._installed_handler is None


def test_record_logged_before_install_does_not_crash() -> None:
    """Documented behaviour: a real Nautilus `Logger` silently discards
    records when Nautilus's own logging subsystem is uninitialized -- it
    does not raise. This bridge relies on that native behaviour rather than
    reimplementing the check, so logging through a real, uninstalled bridge
    handler before `install()` -- and before Nautilus logging is
    initialized -- must never crash the caller.
    """
    handler = NautilusLoggingBridgeHandler()  # real Logger, not the fake
    record = logging.LogRecord(
        name=BREEZY_LOGGER_NAME,
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="logged before install, before Nautilus logging is initialized",
        args=(),
        exc_info=None,
    )

    handler.emit(record)  # must not raise


def test_bridge_never_propagates_an_exception_from_the_nautilus_logger() -> None:
    fake = FakeNautilusLogger(raise_on="info")
    install(fake)
    logger = _breezy_child_logger()
    original_raise_exceptions = logging.raiseExceptions
    logging.raiseExceptions = False
    try:
        logger.info("this would raise inside the fake logger")
    finally:
        logging.raiseExceptions = original_raise_exceptions

    # No exception escaped the `logger.info(...)` call above -- that is the
    # assertion. The fake never recorded the call because it raised inside
    # `_record`, and the handler swallowed it via `handleError`.
    assert fake.calls == []


def test_handler_is_attached_to_breezy_logger_not_root() -> None:
    root_logger = logging.getLogger()
    handlers_before = list(root_logger.handlers)

    fake = FakeNautilusLogger()
    handler = install(fake)

    breezy_logger = logging.getLogger(BREEZY_LOGGER_NAME)
    assert handler in breezy_logger.handlers
    assert handler not in root_logger.handlers
    assert list(root_logger.handlers) == handlers_before


# --------------------------------------------------------------------------
# A1 boot-window mechanism: is_installed / ensure_stderr_visible
# --------------------------------------------------------------------------


def test_is_installed_false_before_install() -> None:
    assert is_installed() is False


def test_is_installed_true_after_install() -> None:
    install(FakeNautilusLogger())

    assert is_installed() is True


def test_is_installed_false_after_uninstall() -> None:
    install(FakeNautilusLogger())
    uninstall()

    assert is_installed() is False


def test_ensure_stderr_visible_attaches_a_handler_when_the_bridge_is_absent() -> None:
    handler = ensure_stderr_visible(_TEST_LOGGER_NAME)

    assert handler is not None
    assert handler in logging.getLogger(_TEST_LOGGER_NAME).handlers


def test_ensure_stderr_visible_writes_an_info_record_to_the_patched_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stderr", buffer)

    ensure_stderr_visible(_TEST_LOGGER_NAME)
    logging.getLogger(_TEST_LOGGER_NAME).info("boot window record")

    assert "boot window record" in buffer.getvalue()


def test_ensure_stderr_visible_is_idempotent_one_record_not_two() -> None:
    buffer = io.StringIO()
    handler = ensure_stderr_visible(_TEST_LOGGER_NAME)
    assert isinstance(handler, logging.StreamHandler)
    handler.setStream(buffer)
    ensure_stderr_visible(_TEST_LOGGER_NAME)  # second call: no second handler

    logging.getLogger(_TEST_LOGGER_NAME).info("once only")

    assert buffer.getvalue().count("once only") == 1


def test_ensure_stderr_visible_returns_none_once_the_bridge_is_installed() -> None:
    install(FakeNautilusLogger())

    assert ensure_stderr_visible(_TEST_LOGGER_NAME) is None
    assert logging.getLogger(_TEST_LOGGER_NAME).handlers == []


def test_ensure_stderr_visible_handler_falls_silent_once_the_bridge_is_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The filter is evaluated per-record, not baked in at attach time: a
    handler attached BEFORE the bridge exists must stop emitting the
    instant the bridge is installed, so nothing is ever logged twice once
    normal ``breezy`` propagation takes over."""
    buffer = io.StringIO()
    monkeypatch.setattr("sys.stderr", buffer)
    ensure_stderr_visible(_TEST_LOGGER_NAME)

    install(FakeNautilusLogger())
    logging.getLogger(_TEST_LOGGER_NAME).info("after the bridge exists")

    assert "after the bridge exists" not in buffer.getvalue()
