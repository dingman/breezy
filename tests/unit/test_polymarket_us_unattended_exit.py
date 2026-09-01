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
from breezy.adapters.polymarket_us.data import FATAL_SHUTDOWN_REQUEST_BUDGET
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


def test_the_shutdown_request_is_bounded_however_often_the_watchdog_samples(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """A repeated sample must not spray shutdown commands at the kernel.

    ``sample_feed_health`` is public and directly callable on a cadence, so
    one lost feed must never become an unbounded command stream -- that is the
    guard this test has always carried and still carries. What changed is the
    ceiling: exactly-one was wrong, because ``shutdown_system`` only PUBLISHES
    and ``NautilusKernel._on_shutdown_system`` drops the command outright when
    the kernel is not running or already stopping, telling the publisher
    nothing. A small BOUNDED budget re-asks across that window; the stream is
    still bounded, which is the invariant that matters here.
    """
    client, feed = build_client(loop)
    published: list[Any] = []
    client._msgbus.subscribe(SHUTDOWN_TOPIC, published.append)

    feed.restore()
    client.sample_feed_health()
    feed.give_up()
    for _ in range(50):
        client.sample_feed_health()

    assert len(published) == FATAL_SHUTDOWN_REQUEST_BUDGET
    assert FATAL_SHUTDOWN_REQUEST_BUDGET < 5, "the budget must stay small"


def test_the_watchdog_keeps_re_checking_until_its_request_budget_is_spent(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """The re-checker must outlive an UNCONFIRMED shutdown request.

    ``Component.shutdown_system`` (``common/component.pyx:2162-2182``) only
    publishes; ``NautilusKernel._on_shutdown_system`` (``system/kernel.py``)
    drops the command on a ``trader_id`` mismatch, when ``not _is_running``,
    or silently when ``_is_stopping``. If the watchdog ended on the first
    request, a dropped command would get no second chance from anywhere and
    the node would run on forever with a dead feed and a latched fault --
    exactly the failure the fail-closed path exists to eliminate.
    """
    client, feed = build_client(loop)
    published: list[Any] = []
    client._msgbus.subscribe(SHUTDOWN_TOPIC, published.append)

    feed.restore()
    client.sample_feed_health()
    feed.give_up()

    results = [client.sample_feed_health() for _ in range(FATAL_SHUTDOWN_REQUEST_BUDGET)]

    assert results[:-1] == [True] * (FATAL_SHUTDOWN_REQUEST_BUDGET - 1), (
        "the watchdog must keep sampling while the shutdown is unconfirmed"
    )
    assert results[-1] is False, "and stop once there is nothing left to re-ask"
    assert len(published) == FATAL_SHUTDOWN_REQUEST_BUDGET


# -- a SILENT SUBSCRIPTION IS NOT A DEAD FEED ------------------------------
#
# `is_degraded` on the markets feed has THREE producers, not two: reconnect
# exhaustion and supervisor death (both fatal -- nothing in the process
# reconnects that socket), and ONE subscribed slug outliving its 60s
# confirmation window with no inbound frame (not fatal -- the socket is alive
# and every other slug is still flowing). `_degraded` is sticky and the pool
# aggregates with `any(...)`, so at 05:00Z, with ~60 thin overnight weather
# markets subscribed, the FIRST quiet one would degrade its shard, degrade the
# pool, and end an eight-hour unattended capture in its first minute with a
# near-empty tape and a "feed lost and not recoverable" message that is false.


def test_a_silent_subscription_alone_never_shuts_the_node_down(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """One quiet overnight market must not end the whole capture."""
    client, feed = build_client(loop)
    published: list[Any] = []
    client._msgbus.subscribe(SHUTDOWN_TOPIC, published.append)

    feed.restore()
    client.sample_feed_health()
    feed.go_silent("kxhighny-26aug31-b70")

    keep_watching = client.sample_feed_health()

    assert published == [], "a silent subscription must never request a shutdown"
    assert feed_fault.fatal_feed_fault() is None, "and must never latch a fatal fault"
    assert keep_watching is True, "recording continues; the feed is alive"
    assert client.is_safe_mode is False


def test_many_silent_subscriptions_still_never_shut_the_node_down(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Not even a majority of the ladder going quiet is fatal.

    Quiet is the NORMAL overnight state of these markets. Volume, not
    fatality, is what a silent slug scales into: the run keeps recording
    whatever is flowing and reports everything that is not.
    """
    client, feed = build_client(loop)
    published: list[Any] = []
    client._msgbus.subscribe(SHUTDOWN_TOPIC, published.append)

    feed.restore()
    client.sample_feed_health()
    for index in range(60):
        feed.go_silent(f"kxhighny-26aug31-b{index}")

    assert client.sample_feed_health() is True
    assert published == []
    assert client.silent_subscription_alerts == 60


def test_a_silent_subscription_is_still_reported_loudly_once_per_slug(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Non-fatal must not mean invisible: it is a real, unbackfillable loss.

    Reported once per SLUG, not once per sample: the watchdog samples every
    few seconds for eight hours, and a per-sample report would bury the very
    signal it exists to raise.
    """
    client, feed = build_client(loop)
    feed.restore()
    client.sample_feed_health()

    feed.go_silent("kxhighny-26aug31-b70")
    client.sample_feed_health()

    assert client.silent_subscription_alerts == 1

    for _ in range(5):
        client.sample_feed_health()

    assert client.silent_subscription_alerts == 1, "one report per slug, not per sample"

    feed.go_silent("kxhighchi-26aug31-b62")
    client.sample_feed_health()

    assert client.silent_subscription_alerts == 2


@pytest.mark.parametrize(
    "fatal_producer",
    ["exhaust_reconnects", "supervisor_died"],
)
def test_a_genuinely_fatal_feed_failure_still_shuts_the_node_down(
    loop: asyncio.AbstractEventLoop,
    fatal_producer: str,
) -> None:
    """The fix must not regress what the fail-closed path exists for.

    Both fatal producers leave the socket permanently unsupervised: nothing in
    the process reconnects it and Nautilus has no notion of a data client that
    stopped producing. Both must still stop the run.
    """
    client, feed = build_client(loop)
    published: list[Any] = []
    client._msgbus.subscribe(SHUTDOWN_TOPIC, published.append)

    feed.restore()
    client.sample_feed_health()
    getattr(feed, fatal_producer)()
    client.sample_feed_health()

    assert len(published) == 1, "a fatal fault must still request a native shutdown"
    fault = feed_fault.fatal_feed_fault()
    assert fault is not None
    assert client.is_safe_mode is True


def test_a_silent_subscription_never_masks_a_later_fatal_failure(
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Downgrading producer 3 must not desensitise the fatal check."""
    client, feed = build_client(loop)
    published: list[Any] = []
    client._msgbus.subscribe(SHUTDOWN_TOPIC, published.append)

    feed.restore()
    client.sample_feed_health()
    feed.go_silent("kxhighny-26aug31-b70")
    client.sample_feed_health()
    assert published == []

    feed.exhaust_reconnects()
    client.sample_feed_health()

    assert len(published) == 1
    assert feed_fault.fatal_feed_fault() is not None


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
