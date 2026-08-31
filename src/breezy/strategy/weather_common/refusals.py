"""Counting the orders a risk rule REFUSED, and getting that count seen.

WHY THIS MODULE EXISTS
----------------------
Closing the naked-short hole (see :mod:`breezy.strategy.weather_common.risk`)
disables a whole trading direction. ``calibration_mean_reversion`` was
SHORT_YES-only in the tested window, so with shorts disabled it can execute
**no signal at all** -- and it says so by doing nothing, which is
byte-identical to what it does when the market is fairly priced.

    A strategy producing zero trades because it is structurally disabled and
    one producing zero trades because the market is efficient are the SAME
    observation and completely different facts.

The refusal is correct in both cases. What is not acceptable is that the
operator cannot tell which one they are looking at. So every ``shorts_disabled``
refusal is counted, and the count is surfaced through the alert path that
already exists (:mod:`breezy.runtime.health`) rather than a second, private
channel: :class:`~breezy.runtime.health.AlertState` supplies the
false->true transition dedupe and the 24h re-notify, and
:func:`~breezy.runtime.health.resolve_alert_sink` picks the logging sink by
default and the webhook only when ``BREEZY_ALERT_WEBHOOK_URL`` is set.

WHY BOTH LAYERS COUNT
---------------------
A short is refused at TWO places, and only one of them is the risk manager:

* the DECISION layer (``<strategy>/decision.py``) returns ``None`` the moment
  it forms a ``SHORT_YES`` intent under ``allow_short=False``, so the order
  never reaches risk at all -- this is the path
  ``calibration_mean_reversion`` takes for every one of its signals;
* :meth:`~breezy.strategy.weather_common.risk.RiskManager.evaluate_order`
  refuses a sell that would take the SETTLED position below zero.

Counting only the second would leave the counter at zero for exactly the
strategy this module was written for. Both increment the same counter, which
the strategy owns and passes to both.

NOT A METRICS FRAMEWORK. :class:`RefusalCounter` is a dict of ints with two
methods, deliberately: it is read by an operator through an alert, not scraped.
Only reasons from a CLOSED set are recorded (``risk.py`` composes some reason
strings from float values -- e.g. ``spread_0.070`` -- and those must never
become dict keys, or the "counter" is an unbounded memory leak keyed by
market noise).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from breezy.runtime.health import (
    AlertCondition,
    AlertConditionKey,
    AlertSink,
    AlertState,
    resolve_alert_sink,
)

__all__ = [
    "SHORTS_DISABLED",
    "SHORTS_DISABLED_EVENT",
    "RefusalAlerter",
    "RefusalCounter",
]

#: The refusal reason, and simultaneously the ``RiskDecision.reason`` string
#: the risk manager returns. One spelling, shared by the guard, the decision
#: layer and the counter, so a rename cannot silently decouple them.
SHORTS_DISABLED: Final[str] = "shorts_disabled"

#: `AlertPayload.event` for the condition below. Distinct from the reason
#: string: an alert event names a CONDITION an operator acts on, not the
#: individual refusal that raised it.
SHORTS_DISABLED_EVENT: Final[str] = "SHORTS_DISABLED_REFUSALS"


@dataclass(slots=True)
class RefusalCounter:
    """How many orders each refusal reason has blocked, this process.

    In-memory and never persisted, matching `AlertState`'s own stance: a
    restart starts the count at zero and the first refusal after it is a fresh
    false->true transition that alerts again.
    """

    counts: dict[str, int] = field(default_factory=dict)

    def record(self, reason: str) -> None:
        self.counts[reason] = self.counts.get(reason, 0) + 1

    def count(self, reason: str) -> int:
        return self.counts.get(reason, 0)

    def total(self) -> int:
        return sum(self.counts.values())


class RefusalAlerter:
    """Turns a :class:`RefusalCounter` into the existing alert path's vocabulary.

    Owns one :class:`~breezy.runtime.health.AlertState`, so the caller may call
    :meth:`report` as often as it likes -- once per evaluated tick is expected
    -- and the sink still sees one payload per transition plus the standard 24h
    re-notify while the condition stands. `sink` and `state` are injectable for
    tests; the defaults are the same ones the ingest actor resolves.

    Single-threaded, for the same reason `AlertState` is: `report` is a
    read-modify-write over that state and must run on the thread that owns it
    (for a `Strategy`, its event handlers).
    """

    def __init__(
        self,
        counter: RefusalCounter,
        *,
        site: str,
        sink: AlertSink | None = None,
        state: AlertState | None = None,
    ) -> None:
        self._counter = counter
        self._site = site
        self._sink = resolve_alert_sink() if sink is None else sink
        self._state = AlertState() if state is None else state

    def report(self, *, now_ns: int) -> int:
        """Evaluate this cycle's refusal conditions and dispatch them.

        Returns the number of payloads DECIDED this cycle, exactly as
        `AlertState.dispatch` does -- never what the sink managed to deliver.
        """
        return self._state.dispatch(self._sink, self._conditions(), now_ns=now_ns)

    def _conditions(self) -> tuple[AlertCondition, ...]:
        refused = self._counter.count(SHORTS_DISABLED)
        return (
            AlertCondition(
                key=AlertConditionKey(kind=SHORTS_DISABLED_EVENT, site=self._site),
                # Passed even when inactive, so `AlertState` sees the
                # true->false edge and a later refusal alerts again rather than
                # being muted as a repeat.
                active=refused > 0,
                severity="WARN",
                event=SHORTS_DISABLED_EVENT,
                detail=(
                    f"{refused} order(s) refused as {SHORTS_DISABLED}; a strategy whose "
                    f"only signal is SHORT_YES is structurally disabled, so its "
                    f"no trades are not evidence of an efficient market"
                ),
            ),
        )
