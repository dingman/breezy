"""An unattended recorder that loses its feed must EXIT NON-ZERO, not idle.

The failure this file exists to prevent, stated plainly: the markets socket's
supervisor exhausts its reconnect budget, sets ``is_degraded``, logs an ERROR
and returns. Its coroutine ends. The Nautilus node does not -- ``TradingNode``
has no notion of a data client that has stopped producing, so the process
stays up, connected to nothing, writing an empty tape. Under systemd the unit
reports ``active (running)`` for the rest of the capture window and nobody
learns anything until the window has passed. For an ATTENDED run a human
notices. For the 05:00Z unattended run there is no human.

Two things must therefore happen when the feed is declared unrecoverable, and
they must happen in this order:

1. **A NATIVE, CLEAN shutdown.** ``Component.shutdown_system(reason)``
   (``common/component.pyx:2162-2182``) publishes ``ShutdownSystem`` on
   ``commands.system.shutdown``; ``NautilusKernel._on_shutdown_system``
   (``system/kernel.py:613-638``) receives it and stops the node. Clean, not
   ``os._exit``, because ``tests/contract/test_quote_tape_unclean_shutdown.py``
   measures what an unclean death does to the day's feather file: a truncated
   trailing Arrow message makes ``convert_stream_to_data`` return ZERO rows in
   total silence. Killing the process to report a lost feed would destroy the
   tape recorded before the feed was lost.
2. **A NON-ZERO process exit status**, because a clean shutdown is
   indistinguishable from an operator SIGTERM otherwise -- both leave
   ``TradingNode.run()`` returning ``None`` and the CLI returning 0.

Only (2) is Breezy's to author. ``TradingNode.run`` (``live/node.py:283-302``)
returns ``None``; ``grep -n reason nautilus_trader/system/kernel.py`` returns
nothing, so the kernel keeps no record of WHY it stopped. The smallest
correct extension is a process-scoped latch written at the same instant the
native shutdown is requested, and read by the CLI after ``run()`` returns.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.messages import ShutdownSystem

from breezy.adapters.polymarket_us import feed_fault
from breezy.runtime.quote_tape_cli import EXIT_OK, EXIT_RUNTIME_ERROR, run
from tests.unit.test_polymarket_us_quote_tape_gap import build_client
from tests.unit.test_quote_tape_cli import BASE_ENV, RecordingNode

SHUTDOWN_TOPIC = "commands.system.shutdown"


@pytest.fixture(autouse=True)
def _clear_latch() -> Iterator[None]:
    """The latch is process-scoped; no test may inherit another's fault.

    ``RecordingNode.instances`` is cleared here too: its own autouse fixture
    lives in the module that defines it and does not follow the import.
    """
    feed_fault.clear_fatal_feed_fault()
    RecordingNode.instances.clear()
    yield
    feed_fault.clear_fatal_feed_fault()
    RecordingNode.instances.clear()


@pytest.fixture(name="loop")
def _loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


# -- the data client -------------------------------------------------------


def test_an_unrecoverable_feed_requests_a_native_system_shutdown(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """The node must be told to stop, through Nautilus's own command."""
    client, feed = build_client(loop)
    published: list[Any] = []
    client._msgbus.subscribe(SHUTDOWN_TOPIC, published.append)

    feed.restore()
    client.sample_feed_health()
    assert published == [], "a healthy feed must never request a shutdown"

    feed.give_up()
    client.sample_feed_health()

    assert len(published) == 1, "exactly one ShutdownSystem command"
    command = published[0]
    assert isinstance(command, ShutdownSystem)
    assert command.component_id == client.id
    assert command.reason is not None
    assert "feed" in command.reason.lower()


def test_an_unrecoverable_feed_latches_a_fatal_fault_for_the_exit_status(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """The reason must outlive the node, or the CLI cannot exit non-zero."""
    client, feed = build_client(loop)
    feed.restore()
    client.sample_feed_health()

    assert feed_fault.fatal_feed_fault() is None

    feed.give_up()
    client.sample_feed_health()

    fault = feed_fault.fatal_feed_fault()
    assert fault is not None
    assert fault.component == str(client.id)
    assert "feed" in fault.reason.lower()


def test_the_shutdown_is_requested_once_however_often_the_watchdog_samples(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """A repeated sample must not spray shutdown commands at the kernel.

    ``sample_feed_health`` returns False to stop the watchdog, but the method
    is public and directly callable, and a future caller must not be able to
    turn one lost feed into an unbounded command stream.
    """
    client, feed = build_client(loop)
    published: list[Any] = []
    client._msgbus.subscribe(SHUTDOWN_TOPIC, published.append)

    feed.restore()
    client.sample_feed_health()
    feed.give_up()
    for _ in range(5):
        client.sample_feed_health()

    assert len(published) == 1


def test_the_first_fault_is_the_one_reported(loop: asyncio.AbstractEventLoop) -> None:
    """A later, derivative failure must not overwrite the original cause."""
    client, feed = build_client(loop)
    feed.restore()
    client.sample_feed_health()
    feed.give_up()
    client.sample_feed_health()

    first = feed_fault.fatal_feed_fault()
    assert first is not None

    feed_fault.record_fatal_feed_fault("SOMETHING-ELSE", "a later, downstream symptom")

    assert feed_fault.fatal_feed_fault() == first


# -- the process exit status -----------------------------------------------


class FeedLostNode(RecordingNode):
    """A node whose run ends because the data client gave up on the feed.

    This is what the real process looks like from the CLI's side: the kernel
    handled ``ShutdownSystem``, stopped cleanly, and ``run()`` returned
    normally. Nothing in the return value distinguishes it from a SIGTERM.
    """

    def run(self) -> None:
        self.calls.append("run")
        feed_fault.record_fatal_feed_fault(
            "POLYMARKET_US", "markets feed lost and not recoverable"
        )


@pytest.fixture(name="complete_env")
def _complete_env(tmp_path: Path) -> dict[str, str]:
    return {
        **BASE_ENV,
        "BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG": str(tmp_path / "venue" / "polymarket_us"),
    }


def test_a_lost_feed_exits_non_zero_so_systemd_reports_a_failure(
    complete_env: dict[str, str],
) -> None:
    """The whole point: ``systemctl status`` must say failed, not active."""
    err = io.StringIO()

    code = run(env=complete_env, node_factory=FeedLostNode, stderr=err)

    assert code == EXIT_RUNTIME_ERROR
    assert code != EXIT_OK
    assert "feed" in err.getvalue().lower()


def test_a_lost_feed_still_disposes_the_node(complete_env: dict[str, str]) -> None:
    """Exiting non-zero must not skip teardown; the tape has to be closed."""
    err = io.StringIO()

    run(env=complete_env, node_factory=FeedLostNode, stderr=err)

    assert RecordingNode.instances[0].calls == ["build", "run", "dispose"]


def test_a_normal_shutdown_with_no_fault_still_exits_zero(
    complete_env: dict[str, str],
) -> None:
    """A SIGTERM at the end of the capture window is a success, not a failure."""
    err = io.StringIO()

    code = run(env=complete_env, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_OK
    assert err.getvalue() == ""


def test_a_stale_fault_from_an_earlier_run_cannot_fail_a_healthy_one(
    complete_env: dict[str, str],
) -> None:
    """The latch is cleared at entry, so it can only report THIS run."""
    feed_fault.record_fatal_feed_fault("POLYMARKET_US", "a fault from before this run")
    err = io.StringIO()

    code = run(env=complete_env, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_OK
