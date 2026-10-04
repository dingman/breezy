"""The quote-tape recorder's systemd watchdog gate, pinger and ``sd_notify`` sender.

AUT-1 plan r12 section 3.10 (WP3 step 1). Three parts, none of which restarts anything:

* :func:`classify_recorder_sample`: a pure gate. Given the recent samples of the recorder it
  says whether the recorder is healthy enough to be told ``WATCHDOG=1``.
* :func:`sd_notify`: the stdlib-only sender (``NOTIFY_SOCKET``), which is a no-op returning
  ``False`` whenever the unit is not ``Type=notify`` (no socket in the environment).
* :class:`RecorderWatchdogPinger`: the task that samples, classifies and sends. It is created
  as the FIRST statement of the data client's ``_connect`` so that the long empty-listing
  discovery wait is covered by ``EXTEND_TIMEOUT_USEC`` (before ``READY=1``) and never by a
  start timeout.

The recorder's unit file is NOT changed by this module: under today's ``Type=simple`` there is
no ``NOTIFY_SOCKET`` and every send returns ``False``. This module imports the standard
library only, so ``node_config`` can read its constants without a cycle.
"""

from __future__ import annotations

import asyncio
import os
import socket
import stat
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

# ----------------------------------------------------------------- phases and verdicts

PHASE_DISCOVERING: Final = "DISCOVERING"
PHASE_CONNECTING: Final = "CONNECTING"
PHASE_STREAMING: Final = "STREAMING"
PHASE_SAFE_MODE: Final = "SAFE_MODE"

VERDICT_OK: Final = "OK"
VERDICT_OK_DEFERRED: Final = "OK_DEFERRED"
#: Set by the pinger, never by the classifier (EM2).
CAUSE_SAMPLE_ERROR: Final = "sample_error"
CAUSE_DISCOVERING_OVERRUN: Final = "discovering_overrun"
CAUSE_DISCOVERY_ATTEMPT_HUNG: Final = "discovery_attempt_hung"
CAUSE_CONNECTING_OVERRUN: Final = "connecting_overrun"
CAUSE_SAFE_MODE_OVERRUN: Final = "safe_mode_overrun"
CAUSE_STREAM_STALLED: Final = "stream_stalled"
CAUSE_WRITER_STALL: Final = "writer_stall"
CAUSE_DISCOVERY_RELOAD_OVERDUE: Final = "discovery_reload_overdue"
CAUSE_FEED_WATCH_DEAD: Final = "feed_watch_dead"

# ------------------------------------------------------- WP0-measured gate constants (D8)

#: Venue-wide silence horizon: the 14-day maximum was 461 s and no run reached 900 s.
STREAM_SILENCE_S: Final = 900
#: Quiet-hour multiplier (WP0 part b: 1, so the quiet hours add nothing today).
QUIET_HOURS_MULTIPLIER: Final = 1
#: UTC hours whose 5-minute bins carried a frame in at least 99 % of 14 days (WP0 part b).
QUIET_HOURS_UTC: Final[frozenset[int]] = frozenset({11, 22, 23})
WRITER_STALL_S: Final = 120
FLUSH_MARGIN_S: Final = 30
DISCOVERY_ATTEMPT_BUDGET_S: Final = 180

# ------------------------------------------------------------ r12 section 3.10.1 budgets

DISCOVERING_GRACE_S: Final = 300
CONNECT_BUDGET_S: Final = 300
SAFE_MODE_BUDGET_S: Final = 300
START_EXTEND_S: Final = 120
_USEC_PER_SEC: Final = 1_000_000

# ----------------------------------- constants pinned to the recorder unit (WP3 step 2)

UNIT_WATCHDOG_SEC: Final = 600
UNIT_TIMEOUT_STOP_SEC: Final = 120
UNIT_TIMEOUT_START_SEC: Final = 180
#: ``timeout -k 2 10`` on the ``ExecStopPost`` argv: ``K + T``.
STOP_HOOK_KILL_AFTER_S: Final = 2
STOP_HOOK_TIMEOUT_S: Final = 10
STOP_HOOK_BOUND_S: Final = STOP_HOOK_KILL_AFTER_S + STOP_HOOK_TIMEOUT_S
ROTATE_MARGIN_S: Final = 30
#: AUT-6 reads this read-only: the 3rd watchdog kill in a trading day is a storm.
RECORDER_WATCHDOG_STORM_KILLS: Final = 3

# ----------------------------------------------------------------- launch window (X-3)

LAUNCH_WINDOW_START_S: Final = 16 * 3600 + 30 * 60
LAUNCH_WINDOW_END_S: Final = 17 * 3600 + 10 * 60
LAUNCH_WINDOW_END_LABEL: Final = "17:10Z"
DEFERRAL_HORIZON_S: Final = UNIT_WATCHDOG_SEC + UNIT_TIMEOUT_STOP_SEC + UNIT_TIMEOUT_START_SEC
_SECONDS_PER_DAY: Final = 86_400
_NS: Final = 1_000_000_000

# ------------------------------------------------------------------------ log markers

#: Module constants AUT-6 imports read-only (X-7: it delivers the WARN).
RECORDER_WATCHDOG_DEFERRED: Final = "RECORDER_WATCHDOG_DEFERRED"
RECORDER_WATCHDOG_WITHHELD: Final = "RECORDER_WATCHDOG_WITHHELD"
RECORDER_WATCHDOG_GATE: Final = "RECORDER_WATCHDOG_GATE"
RECORDER_WATCHDOG_READY: Final = "RECORDER_WATCHDOG_READY"
RECORDER_SAMPLE_FAILED: Final = "RECORDER_SAMPLE_FAILED"
RECORDER_PINGER_DIED: Final = "RECORDER_PINGER_DIED"
WITHHELD_LOG_INTERVAL_S: Final = 3600
SAMPLE_FAILED_LOG_EVERY: Final = 60

NOTIFY_SOCKET_ENV: Final = "NOTIFY_SOCKET"


@dataclass(frozen=True, slots=True)
class RecorderSample:
    """One read of the recorder, taken from read-only accessors (r12 section 3.10.1, EM6)."""

    now_ns: int
    phase: str
    phase_started_ns: int
    discovered_slugs: int
    subscribed_count: int
    quotes_published: int
    depths_published: int
    trades_published: int
    is_tape_gap_open: bool
    safe_mode: bool
    feed_watch_alive: bool
    last_discovery_reload_ns: int
    last_scheduled_reload_delay_secs: float
    discovery_attempt_inflight_since_ns: int
    stream_bytes: int

    @property
    def events(self) -> int:
        return self.quotes_published + self.depths_published + self.trades_published


# ------------------------------------------------------------------------- the gate


def stream_silence_s(now_ns: int) -> float:
    """``STREAM_SILENCE_S(h)``: the horizon, widened by the multiplier in the quiet hours."""
    hour = (now_ns // _NS // 3600) % 24
    return STREAM_SILENCE_S * (QUIET_HOURS_MULTIPLIER if hour in QUIET_HOURS_UTC else 1)


def _age_s(now_ns: int, since_ns: int) -> float:
    return (now_ns - since_ns) / _NS


def _phase_overrun(sample: RecorderSample, now_ns: int, discovery_retry_secs: float) -> str | None:
    age = _age_s(now_ns, sample.phase_started_ns)
    phase = sample.phase
    if phase == PHASE_DISCOVERING:
        inflight = sample.discovery_attempt_inflight_since_ns
        if inflight and _age_s(now_ns, inflight) > DISCOVERY_ATTEMPT_BUDGET_S:
            return CAUSE_DISCOVERY_ATTEMPT_HUNG
        if age > discovery_retry_secs + DISCOVERING_GRACE_S:
            return CAUSE_DISCOVERING_OVERRUN
    elif phase == PHASE_CONNECTING and age > CONNECT_BUDGET_S:
        return CAUSE_CONNECTING_OVERRUN
    elif phase == PHASE_SAFE_MODE and age > SAFE_MODE_BUDGET_S:
        return CAUSE_SAFE_MODE_OVERRUN
    return None


def _streaming_tail(history: Sequence[RecorderSample]) -> list[RecorderSample]:
    """The trailing run of STREAMING samples of one phase instance (oldest first)."""
    tail: list[RecorderSample] = []
    for sample in reversed(history):
        if sample.phase != PHASE_STREAMING:
            break
        if tail and sample.phase_started_ns != tail[-1].phase_started_ns:
            break
        tail.append(sample)
    tail.reverse()
    return tail


def _stream_stalled(tail: Sequence[RecorderSample], now_ns: int) -> bool:
    latest = tail[-1]
    if latest.subscribed_count <= 0:
        return False
    cutoff_ns = now_ns - int(stream_silence_s(now_ns) * _NS)
    baseline = next(
        (index for index in range(len(tail) - 1, -1, -1) if tail[index].now_ns <= cutoff_ns),
        None,
    )
    if baseline is None:
        return False
    frozen = (latest.events, latest.stream_bytes)
    return all((s.events, s.stream_bytes) == frozen for s in tail[baseline:])


def _writer_stalled(tail: Sequence[RecorderSample]) -> bool:
    """>= 1 event published and bytes flat across ``WRITER_STALL_S``, outside the flush margin."""
    latest = tail[-1]
    margin_ns = FLUSH_MARGIN_S * _NS
    span_ns = WRITER_STALL_S * _NS
    last_outside_margin = max(
        (i for i, s in enumerate(tail) if latest.now_ns - s.now_ns >= margin_ns), default=None
    )
    if last_outside_margin is None:
        return False
    for start, anchor in enumerate(tail):
        if latest.now_ns - anchor.now_ns < span_ns or start >= last_outside_margin:
            continue
        if latest.stream_bytes != anchor.stream_bytes:
            continue
        if tail[last_outside_margin].events - anchor.events >= 1:
            return True
    return False


def _reload_overdue(latest: RecorderSample, now_ns: int) -> bool:
    if latest.discovered_slugs != 0:
        return False
    delay = latest.last_scheduled_reload_delay_secs
    if delay <= 0 or latest.last_discovery_reload_ns <= 0:
        return False
    return _age_s(now_ns, latest.last_discovery_reload_ns) > 2 * delay


def _is_ready(history: Sequence[RecorderSample], ready: bool | None) -> bool:
    if ready is not None:
        return ready
    return any(sample.phase == PHASE_STREAMING for sample in history)


def underlying_withhold_cause(
    history: Sequence[RecorderSample],
    now_ns: int,
    *,
    ready: bool | None = None,
    discovery_retry_secs: float = 3600.0,
) -> str | None:
    """The withhold cause with NO deferral applied, or ``None`` when the recorder is healthy.

    Before READY only the start-phase causes can arise. After READY the stream causes apply.
    """
    if not history:
        return None
    latest = history[-1]
    overrun = _phase_overrun(latest, now_ns, discovery_retry_secs)
    if overrun is not None:
        return overrun
    if latest.phase != PHASE_STREAMING or not _is_ready(history, ready):
        return None
    if not latest.feed_watch_alive:
        return CAUSE_FEED_WATCH_DEAD
    tail = _streaming_tail(history)
    if _stream_stalled(tail, now_ns):
        return CAUSE_STREAM_STALLED
    if _writer_stalled(tail):
        return CAUSE_WRITER_STALL
    if _reload_overdue(latest, now_ns):
        return CAUSE_DISCOVERY_RELOAD_OVERDUE
    return None


def window_meets_launch_window(now_ns: int, horizon_s: float = DEFERRAL_HORIZON_S) -> bool:
    """True iff ``[now, now + horizon]`` meets ``[16:30Z, 17:10Z)`` on any UTC day (X-3)."""
    start_s = now_ns / _NS
    end_s = start_s + horizon_s
    first_day = int(start_s // _SECONDS_PER_DAY)
    last_day = int(end_s // _SECONDS_PER_DAY)
    for day in range(first_day, last_day + 1):
        window_start = day * _SECONDS_PER_DAY + LAUNCH_WINDOW_START_S
        window_end = day * _SECONDS_PER_DAY + LAUNCH_WINDOW_END_S
        if start_s < window_end and end_s >= window_start:
            return True
    return False


def classify_recorder_sample(
    history: Sequence[RecorderSample],
    now_ns: int,
    *,
    ready: bool | None = None,
    discovery_retry_secs: float = 3600.0,
) -> str:
    """``"OK"``, ``"OK_DEFERRED"`` or a withhold cause. Pure.

    The launch-window deferral (X-3) applies AFTER READY only (r12 item 2): before READY a
    withhold cause stops the start extension exactly as it does outside the window.
    """
    cause = underlying_withhold_cause(
        history, now_ns, ready=ready, discovery_retry_secs=discovery_retry_secs
    )
    if cause is None:
        return VERDICT_OK
    if _is_ready(history, ready) and window_meets_launch_window(now_ns):
        return VERDICT_OK_DEFERRED
    return cause


# -------------------------------------------------------------------- notify decision

ACTION_NONE: Final = "none"
ACTION_PING: Final = "watchdog"
ACTION_EXTEND: Final = "extend"
#: The recorder's empty-listing retry budget (``QUOTE_TAPE_EMPTY_DISCOVERY_RETRY_SECS``; pinned
#: equal by a test, because ``node_config`` imports this module and not the reverse).
_DEFAULT_RETRY_SECS: Final = 3600.0


def extension_window_s(discovery_retry_secs: float = _DEFAULT_RETRY_SECS) -> float:
    """The most pre-READY time after the pinger's first tick that may still be extended.

    The discovering window (retry budget + grace) plus the connecting budget. ``node_config``
    derives the unit's start budget from the same parts, so an extension can never be granted
    past ``QUOTE_TAPE_MAX_START_SECS`` whatever the phase sequence does.
    """
    return discovery_retry_secs + DISCOVERING_GRACE_S + CONNECT_BUDGET_S


def decide_action(
    *,
    verdict: str,
    ready: bool,
    stop_begun: bool,
    started_ns: int,
    now_ns: int,
    discovery_retry_secs: float = _DEFAULT_RETRY_SECS,
) -> str:
    """What to send this tick. Pure.

    * After READY an ``OK``/``OK_DEFERRED`` tick sends ``WATCHDOG=1``.
    * Before READY an ``OK`` tick (never ``OK_DEFERRED``) sends ``EXTEND_TIMEOUT_USEC``, but only
      while the pre-READY window is open and never once a stop has begun: the default
      ``WatchdogSignal`` is SIGABRT and a unit whose process ignores SIGTERM while it keeps
      extending sits in ``stop-sigterm`` indefinitely (WP0 part c).
    """
    if verdict not in (VERDICT_OK, VERDICT_OK_DEFERRED):
        return ACTION_NONE
    if ready:
        return ACTION_PING
    if verdict != VERDICT_OK or stop_begun:
        return ACTION_NONE
    if _age_s(now_ns, started_ns) > extension_window_s(discovery_retry_secs):
        return ACTION_NONE
    return ACTION_EXTEND


# ------------------------------------------------------------------------ the sender


def sd_notify(message: str, *, environ: Mapping[str, str] | None = None) -> bool:
    """Send one datagram to ``$NOTIFY_SOCKET``. ``False`` when unset or on any send error.

    Stdlib only; understands the abstract-namespace ``@`` prefix. Never raises, and never blocks
    the event loop (the socket is non-blocking: a full buffer is a failed send).
    """
    env = os.environ if environ is None else environ
    address = env.get(NOTIFY_SOCKET_ENV)
    if not address:
        return False
    target = "\0" + address[1:] if address.startswith("@") else address
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as sock:
            sock.setblocking(False)
            sock.sendto(message.encode("ascii"), target)
    except (OSError, ValueError):
        return False
    return True


def stream_bytes_total(directory: str | os.PathLike[str]) -> int:
    """The ``lstat`` byte total of the recorder's own ``*.feather`` files; 0 if not created yet.

    Regular, non-hidden ``.feather`` entries only (symlinks are not followed and not counted).
    One ``scandir`` of one flat directory, cheap enough for the event loop at a 5 s cadence.
    """
    total = 0
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.name.startswith(".") or not entry.name.endswith(".feather"):
                    continue
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISREG(info.st_mode):
                    total += info.st_size
    except FileNotFoundError:
        return 0
    return total


def extend_timeout_message(extend_s: int = START_EXTEND_S) -> str:
    return f"EXTEND_TIMEOUT_USEC={extend_s * _USEC_PER_SEC}"


# ---------------------------------------------------------------------- the pinger


class WatchdogLogger(Protocol):
    def info(self, message: str) -> None: ...
    def warning(self, message: str) -> None: ...
    def error(self, message: str) -> None: ...


Notifier = Callable[[str], bool]


def deferred_line(*, stall_id: int, cause: str) -> str:
    """The exact text AUT-6 reads from the journal (once per stall, X-7)."""
    return (
        f"{RECORDER_WATCHDOG_DEFERRED} stall_id={stall_id} stall_started_ns={stall_id} "
        f"cause={cause} until={LAUNCH_WINDOW_END_LABEL}"
    )


class RecorderWatchdogPinger:
    """Samples, classifies and notifies on the event-loop thread, every ``interval_s``."""

    def __init__(
        self,
        *,
        read_sample: Callable[[], RecorderSample],
        clock_ns: Callable[[], int],
        logger: WatchdogLogger,
        interval_s: float,
        stop_begun: Callable[[], bool] = lambda: False,
        notify: Notifier = sd_notify,
        socket_present: bool | None = None,
        discovery_retry_secs: float = _DEFAULT_RETRY_SECS,
    ) -> None:
        self._read_sample = read_sample
        self._clock_ns = clock_ns
        self._log = logger
        self._interval_s = interval_s
        self._stop_begun = stop_begun
        self._notify = notify
        self._socket_present = (
            bool(os.environ.get(NOTIFY_SOCKET_ENV)) if socket_present is None else socket_present
        )
        self._discovery_retry_secs = discovery_retry_secs
        self._retention_ns = int(
            (STREAM_SILENCE_S * max(1, QUIET_HOURS_MULTIPLIER) + 3 * interval_s) * _NS
        )
        self._history: deque[RecorderSample] = deque()
        self._started_ns: int | None = None
        self._ready = False
        self._stall_started_ns: int | None = None
        self._deferral_logged = False
        self._withheld_logged_ns: dict[str, int] = {}
        self.sample_failures = 0
        self.last_verdict: str | None = None
        self.last_action: str = ACTION_NONE

    @property
    def is_ready(self) -> bool:
        return self._ready

    def mark_ready(self) -> bool:
        """Latch READY and send ``READY=1`` once per process. ``True`` only on the first call."""
        if self._ready:
            return False
        self._ready = True
        sent = self._safe_notify("READY=1")
        self._log.info(f"{RECORDER_WATCHDOG_READY} sent={sent}")
        return True

    def _safe_notify(self, message: str) -> bool:
        try:
            return bool(self._notify(message))
        except Exception:  # noqa: BLE001 - a sender must never end the pinger
            return False

    async def run(self) -> None:
        """Tick forever; only cancellation ends it normally."""
        self._log.info(f"{RECORDER_WATCHDOG_GATE} notify_socket_present={self._socket_present}")
        while True:
            self.tick()
            await asyncio.sleep(self._interval_s)

    def on_task_done(self, task: asyncio.Task[None]) -> None:
        """Done-callback: any ending but cancellation is logged at ERROR, never silent."""
        if task.cancelled():
            return
        error = task.exception()
        cause = type(error).__name__ if error is not None else "returned"
        self._log.error(f"{RECORDER_PINGER_DIED} cause={cause}")

    def tick(self) -> str:
        """One sample, classification and send. Exception-safe (EM2); returns the verdict."""
        now_ns = self._clock_ns()
        if self._started_ns is None:
            self._started_ns = now_ns
        try:
            verdict = self._evaluate(now_ns)
        except Exception as exc:  # noqa: BLE001 - one bad tick must not end the pinger
            self.sample_failures += 1
            if self.sample_failures == 1 or self.sample_failures % SAMPLE_FAILED_LOG_EVERY == 0:
                self._log.error(
                    f"{RECORDER_SAMPLE_FAILED} cause={type(exc).__name__} "
                    f"failures={self.sample_failures}"
                )
            verdict = CAUSE_SAMPLE_ERROR
            self._note_stall(verdict, None, now_ns)
            self._log_withheld(verdict, now_ns)
            self.last_action = ACTION_NONE
        self.last_verdict = verdict
        return verdict

    def _evaluate(self, now_ns: int) -> str:
        sample = self._read_sample()
        self._history.append(sample)
        floor_ns = now_ns - self._retention_ns
        while len(self._history) > 1 and self._history[1].now_ns <= floor_ns:
            self._history.popleft()
        history = tuple(self._history)
        retry = self._discovery_retry_secs
        verdict = classify_recorder_sample(
            history, now_ns, ready=self._ready, discovery_retry_secs=retry
        )
        cause = underlying_withhold_cause(
            history, now_ns, ready=self._ready, discovery_retry_secs=retry
        )
        self._note_stall(verdict, cause, now_ns)
        if verdict == VERDICT_OK_DEFERRED:
            self._log_deferral(cause)
        action = decide_action(
            verdict=verdict,
            ready=self._ready,
            stop_begun=self._stop_begun(),
            started_ns=self._started_ns if self._started_ns is not None else now_ns,
            now_ns=now_ns,
            discovery_retry_secs=retry,
        )
        self.last_action = action
        if action == ACTION_PING:
            self._safe_notify("WATCHDOG=1")
        elif action == ACTION_EXTEND:
            self._safe_notify(extend_timeout_message())
        if verdict not in (VERDICT_OK, VERDICT_OK_DEFERRED):
            self._log_withheld(verdict, now_ns)
        return verdict

    def _note_stall(self, verdict: str, cause: str | None, now_ns: int) -> None:
        """A stall is the run of non-OK samples that starts after an OK one."""
        if verdict == VERDICT_OK:
            self._stall_started_ns = None
            self._deferral_logged = False
        elif self._stall_started_ns is None:
            self._stall_started_ns = now_ns
            self._deferral_logged = False

    def _log_deferral(self, cause: str | None) -> None:
        if self._deferral_logged or self._stall_started_ns is None:
            return
        self._deferral_logged = True
        self._log.warning(deferred_line(stall_id=self._stall_started_ns, cause=cause or "unknown"))

    def _log_withheld(self, cause: str, now_ns: int) -> None:
        last = self._withheld_logged_ns.get(cause)
        if last is not None and now_ns - last < WITHHELD_LOG_INTERVAL_S * _NS:
            return
        self._withheld_logged_ns[cause] = now_ns
        self._log.warning(f"{RECORDER_WATCHDOG_WITHHELD} cause={cause}")
