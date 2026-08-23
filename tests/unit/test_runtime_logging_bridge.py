"""Unit tests for `breezy.runtime.logging_bridge`.

No network I/O and no hardcoded dates -- these tests exercise stdlib
`logging` plumbing and a fake Nautilus logger only.

`_installed_handler` is module-global state (the bridge attaches to the
process-wide `breezy` logger), so every test resets it via an autouse
fixture: `uninstall()` before AND after each test, so a failure mid-test
never leaks a handler into the next test.
"""

from __future__ import annotations

import logging

import pytest

from breezy.runtime import logging_bridge
from breezy.runtime.logging_bridge import (
    BREEZY_LOGGER_NAME,
    NautilusLoggingBridgeHandler,
    install,
    uninstall,
)


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
