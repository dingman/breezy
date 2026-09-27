"""Unattended fee-schedule drift probe (AUD-12b).

NULL HYPOTHESIS, checked before this module was written: the fee-coefficient
mismatch check the strategy already runs
(``current_rung_hold/decision.py:342``,
``inputs.fee_coefficient != inputs.config.required_fee_coefficient``) only
fires when an order is actually attempted. Since 2026-09-15 zero decisions
reach pricing at all (gap G-01), so a SECOND, unrelated drift -- like the
theta 0.06 -> 0.0695 drift that silently halted the live node for three days
on 2026-09-17 -- would currently be invisible. This module closes that hole
with an independent, periodic, read-only probe. It never edits
``DOCUMENTED_TAKER_FEE_COEFFICIENT``, never auto-adopts a wire value, and
never places an order.

**Reference value defect fix (``RULING_fee_drift_probe_target_2026-09-25.md``,
2026-09-25).** The probe's ``documented_fee_coefficient`` is a plain
constructor parameter, defaulted to ``DOCUMENTED_TAKER_FEE_COEFFICIENT`` for
tests only -- the wiring site (``breezy.app.trade``) ALWAYS passes the
composed family's own REGISTERED theta (``FamilyManifest.taker_fee_coefficient``,
the exact source ``decision.py:342``'s own per-order check already uses),
never the module-level constant. A family registered at a different,
committed theta (e.g. ``pm_us_crh_v4`` at ``0.0695``) is compared against
ITS OWN registered value, not the stale documentation pin -- comparing
against the wrong constant previously produced a permanent, unresolvable
DISAGREE for that family. Repeated DISAGREEs against the SAME wire value are
deduplicated (CRITICAL once, then a single ``fee_drift_probe_mismatch_persisting``
reminder per :data:`_MISMATCH_SUPPRESSION_WINDOW_NS`); a NEW distinct wire
value always alerts immediately. The halt-set (``set_family_halted``) still
fires on EVERY DISAGREE, deduped or not -- dedup only shapes the alert
stream, never the halt.

**Native extension point, not a new mechanism.** A plain ``Actor`` with a
native ``Clock.set_timer`` (``common/component.pyx:419``), the exact shape
``breezy.ingest.nbm_forecast_actor.NbmForecastActor`` and
``breezy.ingest.nws_observation_actor`` already use for their own periodic,
read-only polls, and the same site ``POST_FORECAST_PHASE_2026-09-20.md``'s
B-4 finding names for a node-side Actor heartbeat ("B1's site must be the
node ... a Nautilus Actor"). Registered via the native ``Trader.add_actor``
(``trading/trader.py:312``), NOT through ``TradingNodeConfig.actors``
(``node_config.py``'s own "zero declared actors" note: ``ActorConfig`` is
msgspec-scalar-only and cannot carry the live injected objects below, so the
``ImportableActorConfig`` route is structurally unusable here, exactly as it
is for the ingest Actors) -- this Actor takes NO ``ActorConfig`` at all,
mirroring ``breezy.strategy.ladder_ev.forecast_subscriber.ForecastStateActor``.

**Every collaborator is injected, never constructed here** -- a PULL seam,
mirroring ``weather_common.costs.FeeCoefficientSource``:

* ``wire_fee_fetcher`` -- an async, no-argument callable returning the
  venue's currently-advertised theta or raising. The production one is
  :func:`fetch_wire_fee_coefficient` bound (via ``functools.partial``) to a
  concrete ``PolymarketUSHttpClient`` and slug at the wiring site
  (``breezy.app.trade``); this module holds no transport of its own.
* ``set_family_halted`` -- a callable, taking the observed wire fee,
  driving the SAME
  ``family_halted`` state the existing order-path refusal already uses
  (``TrialDayLatch.record_policy_halt``, reused as-is -- no new key, no new
  veto). This module never imports ``TrialDayLatch`` directly: the wiring
  site already holds the strategy's shared latch handle for the READ side of
  this state (``composition.family_halt_submit_veto``), and this is that
  same idiom for the WRITE side. May raise (e.g. the durable store's own
  write failing) -- ``probe_once`` contains that separately from the
  fetch/compare above; see its docstring.
* ``alert_sink`` -- ``runtime.health.AlertSink``, resolved once at the
  wiring site via ``resolve_alert_sink()`` (already landed, ``f97c26f``);
  this module only calls ``emit_alert``.

**The unauthenticated ``gateway_base_url`` path, never the signed one.**
:func:`fetch_wire_fee_coefficient` calls ONLY
``PolymarketUSHttpClient.get_public`` -- confirmed unauthenticated at
``docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/client.py:79-133``
(``get()`` defaults ``authenticated=False``; the authenticated path requires
``key_id``/``secret_key`` and routes to ``api_base_url``). No standing
credential is read or held by this timer loop.

**Single representative slug, an accepted, evidence-justified design
choice.** ``docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md``
captured the SAME drifted value (0.0695) across 3 different stations
(MIA/MDW/SFO) and 6 instrument rows on the same day -- the one observed drift
event to date was venue-wide, not per-instrument. **Stated residual risk:**
``feeCoefficient`` is parsed PER-MARKET (``adapters/polymarket_us/parsing.py:639``),
so a hypothetical future drift confined to one instrument other than the
probed slug would not be caught by this probe; it remains covered only by
the existing per-order ``decision.py:342`` check once any decision reaches
pricing again, which is exactly the backstop G-01 currently silences.
Extending to one slug per currently-traded station is a small, optional
strengthening left to a future item, not built here.

**Three outcomes per fire, never two -- and UNKNOWN never halts.** AGREE is
silent (no alert, no state change). DISAGREE alerts CRITICAL and calls
``set_family_halted(wire_fee)``. UNKNOWN (the wire read raised or returned
an unusable payload) alerts CRITICAL but does NOT call ``set_family_halted``
-- a DELIBERATE choice, stated here rather than left to inference: the plan
requires UNKNOWN to "fail closed" by never defaulting to "agrees" (i.e. by
never staying silent), which alerting satisfies; it does not require this
probe to halt the family on every transient network hiccup, which would
convert a probe interval's worth of ordinary read flakiness into a
family-wide trading stop the existing per-order check does not itself
impose. A confirmed DISAGREE is the only condition this probe treats as
drift. If the halt-set write itself then fails (the durable store, not the
wire read), ``probe_once`` still returns ``"DISAGREE"`` -- the drift WAS
found -- but emits a SEPARATE ``fee_drift_probe_halt_set_failed`` CRITICAL
alert, distinct from the mismatch alert, so "halted" and "found drift but
could not halt" never look the same in the alert stream. See
``probe_once``'s own docstring.

**EDGE-1 (2026-09-27): the wire read was NEVER once successful.**
:func:`fetch_wire_fee_coefficient` unwraps the ``"market"`` envelope
``GET /v1/market/slug/{slug}`` ALWAYS wraps the market object under --
the prior code read ``feeCoefficient`` directly off the top-level payload,
which never has that key, so every fire since deployment raised
``WireFeeCoefficientError`` and returned ``"UNKNOWN"``. There is NO
fallback to a flat top-level read: an absent/malformed ``"market"``
envelope is UNKNOWN, full stop -- a shape this probe has never actually
seen surfaces as "I don't know," never a guess.

**EDGE-1: sustained UNKNOWN now has a fail-closed consequence, entry-only.**
A repeated UNKNOWN (or the absence of any ``AGREE`` since process boot)
previously had no downstream effect at all -- the family kept arming NEW
entries indefinitely with its own fee schedule unverified. ``FeeDriftProbeActor``
now tracks ``_last_agree_at_ns`` (an ordinary, in-memory attribute -- no
durable key, no store write, no clear callable) and exposes
:meth:`FeeDriftProbeActor.is_fee_verified`, an in-memory, time-based
staleness check: verified iff the last ``AGREE`` was within
:data:`_FEE_VERIFIED_STALENESS_NS` (~4h, 2x the default probe cadence).
``app/trade.py`` wires this, through a late-bound holder, into
``ContinuousRungHoldStrategy``'s entry path (``_hunt_tick``) ONLY --
exits are structurally untouched. Restart cannot bypass this (a fresh
boot starts unverified, unconditionally); a stopped timer cannot either
(the check is evaluated at entry-submit time against elapsed wall time,
not driven by the timer firing).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping
from datetime import timedelta
from decimal import Decimal
from typing import Any, Final

from nautilus_trader.common.actor import Actor

from breezy.adapters.polymarket_us.fees import DOCUMENTED_TAKER_FEE_COEFFICIENT
from breezy.adapters.polymarket_us.provider import MARKET_BY_SLUG_PATH
from breezy.adapters.polymarket_us.transport import QUOTA_KEY_DISCOVERY
from breezy.runtime.health import AlertPayload, AlertSink, emit_alert

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_FEE_DRIFT_PROBE_INTERVAL_SECONDS",
    "FEE_COEFFICIENT_WIRE_KEY",
    "FeeDriftProbeActor",
    "WireFeeCoefficientError",
    "fetch_wire_fee_coefficient",
]

#: The venue's own wire field name for a market's fee coefficient
#: (``adapters/polymarket_us/parsing.py:639``, ``market.get("feeCoefficient")``)
#: -- read verbatim, never renamed.
FEE_COEFFICIENT_WIRE_KEY: Final[str] = "feeCoefficient"

#: EDGE-1 root cause fix: ``GET /v1/market/slug/{slug}`` ALWAYS wraps the
#: market object under this key (three independent sources: the venue SDK's
#: own ``GetMarketResponse`` TypedDict, two real captured payloads, and this
#: repo's own ``adapters/polymarket_us/parsing.py`` parser). There is no
#: fallback to a flat top-level read -- an absent/malformed envelope is
#: ``UNKNOWN``, never a guess.
_MARKET_ENVELOPE_KEY: Final[str] = "market"

#: No coarser than 2 hours (plan §6 item 3 / §7 step 3a).
DEFAULT_FEE_DRIFT_PROBE_INTERVAL_SECONDS: Final[int] = 2 * 60 * 60

#: EDGE-1 (r2/B2'): the in-memory "fee unverified" staleness bound -- 2x the
#: default 2h probe cadence, absorbing one missed fire without a truly-stale
#: cycle going unnoticed. Never durable, never a fire-counter: measured
#: against an externally-supplied ``now_ns`` (the STRATEGY's own clock, per
#: AM-1 -- this module never reads its own clock for this comparison).
_FEE_VERIFIED_STALENESS_NS: Final[int] = 4 * 60 * 60 * 1_000_000_000

#: 24h reminder cadence while persistently stale, mirroring
#: ``_MISMATCH_SUPPRESSION_WINDOW_NS``'s own re-arming idiom.
_FEE_UNVERIFIED_PERSISTING_WINDOW_NS: Final[int] = 24 * 60 * 60 * 1_000_000_000

#: Dedupe/re-arm window for a repeated DISAGREE against the SAME wire value
#: (``RULING_fee_drift_probe_target_2026-09-25.md``). Measured on this
#: Actor's OWN clock (``self.clock.timestamp_ns()``), never wall time, so a
#: backtest or a fast-forwarded ``TestClock`` reasons about it identically to
#: a live process.
_MISMATCH_SUPPRESSION_WINDOW_NS: Final[int] = 24 * 60 * 60 * 1_000_000_000

#: Reused, not reinvented: the same read-quota bucket
#: ``provider.py``'s own single-slug-per-session discovery reads already
#: spend against.
_DEFAULT_QUOTA_KEY: Final[str] = QUOTA_KEY_DISCOVERY


class WireFeeCoefficientError(Exception):
    """The wire fee-schedule read is missing or malformed. Never a default."""


class _PublicReadClient:
    """The one method this module calls on a `PolymarketUSHttpClient`."""

    async def get_public(
        self, path: str, *, query: Mapping[str, Any] | None = None, quota_key: str
    ) -> Mapping[str, Any]: ...


async def fetch_wire_fee_coefficient(
    client: _PublicReadClient,
    slug: str,
    *,
    quota_key: str = _DEFAULT_QUOTA_KEY,
) -> Decimal:
    """Read `slug`'s currently-advertised fee coefficient, read-only.

    Calls ONLY `client.get_public` -- see the module docstring's
    "unauthenticated gateway_base_url path" note. `GET /v1/market/slug/
    {slug}` ALWAYS wraps the market object under a `"market"` key
    (EDGE-1 root cause fix) -- this unwraps it and raises
    :class:`WireFeeCoefficientError` immediately if `"market"` is absent or
    not a mapping. There is NO fallback to a flat top-level read: an
    envelope shape this probe has never actually seen surfaces as UNKNOWN,
    never a guess. Beneath the envelope, anything other than a present,
    numeric `feeCoefficient` is likewise UNKNOWN, never silently treated as
    "agrees".
    """
    path = MARKET_BY_SLUG_PATH.format(slug=slug)
    payload = await client.get_public(path, quota_key=quota_key)
    market = payload.get(_MARKET_ENVELOPE_KEY)
    if not isinstance(market, Mapping):
        raise WireFeeCoefficientError(
            f"{path} returned no {_MARKET_ENVELOPE_KEY!r} envelope for slug {slug!r}"
        )
    raw = market.get(FEE_COEFFICIENT_WIRE_KEY)
    if raw is None:
        raise WireFeeCoefficientError(
            f"{path} returned no {FEE_COEFFICIENT_WIRE_KEY!r} under "
            f"{_MARKET_ENVELOPE_KEY!r} for slug {slug!r}"
        )
    try:
        return Decimal(str(raw))
    except (ArithmeticError, ValueError, TypeError) as exc:
        raise WireFeeCoefficientError(
            f"{path} returned an unusable {FEE_COEFFICIENT_WIRE_KEY!r}={raw!r} "
            f"for slug {slug!r}"
        ) from exc


class FeeDriftProbeActor(Actor):
    """Periodic, read-only fee-schedule drift detector. See the module docstring."""

    def __init__(
        self,
        *,
        wire_fee_fetcher: Callable[[], Awaitable[Decimal]],
        set_family_halted: Callable[[Decimal], None],
        alert_sink: AlertSink,
        documented_fee_coefficient: Decimal = DOCUMENTED_TAKER_FEE_COEFFICIENT,
        interval_seconds: int = DEFAULT_FEE_DRIFT_PROBE_INTERVAL_SECONDS,
        event_site: str = "fee_drift_probe",
    ) -> None:
        super().__init__()
        if interval_seconds <= 0:
            raise ValueError("`interval_seconds` must be positive")
        self._wire_fee_fetcher = wire_fee_fetcher
        self._set_family_halted = set_family_halted
        self._alert_sink = alert_sink
        self._documented = documented_fee_coefficient
        self._interval_seconds = interval_seconds
        self._site = event_site

        self._loop: asyncio.AbstractEventLoop | None = None
        self._timer_armed = False
        self._inflight = 0
        self._inflight_lock = threading.Lock()
        self.counters: Counter[str] = Counter()

        #: Dedupe state for the mismatch alert stream (never for the halt,
        #: which stays unconditional on every DISAGREE). ``None`` until the
        #: first DISAGREE this process has seen.
        self._last_mismatch_wire_fee: Decimal | None = None
        self._last_mismatch_alert_ts_ns: int | None = None

        #: EDGE-1 (r2/B2'): in-memory, time-based "fee unverified" staleness
        #: state. ``None`` at every process boot (restart cannot inherit a
        #: prior "last known good" -- security #1) and set ONLY on AGREE
        #: (never DISAGREE, never UNKNOWN). Not a store key: an ordinary
        #: Python attribute, gone on process exit.
        self._last_agree_at_ns: int | None = None
        #: Dedupe state for the two staleness alerts, mirroring
        #: ``_last_mismatch_*`` above but independent of it: ``True`` once
        #: the first-crossing alert has fired and not yet cleared by a
        #: later AGREE.
        self._fee_unverified_alerted = False
        self._fee_unverified_last_alert_ns: int | None = None

    # -- observability --------------------------------------------------

    @property
    def inflight(self) -> int:
        """Submitted probes not yet fully supervised (tests drain on this)."""
        with self._inflight_lock:
            return self._inflight

    @property
    def timer_armed(self) -> bool:
        return self._timer_armed

    # -- lifecycle --------------------------------------------------------

    def on_start(self) -> None:
        """Capture the loop, probe once, arm the timer.

        With no running loop (a backtest) nothing is armed and no read is
        attempted: no network I/O by construction -- the same guard
        ``NbmForecastActor.on_start`` uses.
        """
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
            logger.info("no running event loop for %s: no fee-drift polling armed", self._site)
            return
        self._submit(self.probe_once())
        self._arm_timer()

    def on_stop(self) -> None:
        if not self._timer_armed:
            return
        try:
            self.clock.cancel_timer(self._timer_name)
        except (KeyError, ValueError):  # pragma: no cover - defensive
            logger.debug("timer %s was already cancelled", self._timer_name)
        self._timer_armed = False

    def _arm_timer(self) -> None:
        if self._timer_armed:
            return
        self.clock.set_timer(
            name=self._timer_name,
            interval=timedelta(seconds=self._interval_seconds),
            callback=self._on_timer,
        )
        self._timer_armed = True

    @property
    def _timer_name(self) -> str:
        return f"{self._site}-timer"

    # -- the cross-thread bridge (mirrors NbmForecastActor's L-16 defence) --

    def _on_timer(self, event: object) -> None:
        """Timer callback: submit and return. Never raises (a `LiveClock` would swallow it)."""
        self._submit(self.probe_once())

    def _submit(self, coro: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            coro.close()
            return
        with self._inflight_lock:
            self._inflight += 1
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:  # pragma: no cover - shutdown race
            coro.close()
            self._settle()
            return
        future.add_done_callback(self._on_probe_done)

    def _settle(self) -> None:
        with self._inflight_lock:
            self._inflight -= 1

    def _on_probe_done(self, future: concurrent.futures.Future[str]) -> None:
        """Supervision, on the COMPLETING thread: marshal any death, never swallow it."""
        self._settle()
        if future.cancelled():
            return
        exc = future.exception()
        if exc is not None:  # pragma: no cover - probe_once() itself never raises
            logger.error(
                "fee-drift probe task died unexpectedly (own defect, not a wire failure): %s",
                type(exc).__name__,
            )

    # -- the probe itself ---------------------------------------------------

    async def probe_once(self) -> str:
        """Fetch, compare, alert/halt. Returns "AGREE" | "DISAGREE" | "UNKNOWN". Never raises.

        A DISAGREE's halt-set is wrapped separately from the fetch/compare
        above: ``set_family_halted`` is an injected write against a REAL
        durable store (``TrialDayLatch.record_policy_halt`` at the wiring
        site, which requires the submit-intent flock to still be held --
        see that call site's own docstring for why it always is, for the
        process's whole life, while the probe runs). A write can still fail
        for reasons a read cannot (a corrupt store, a released lock this
        probe does not itself control), and the DISAGREE finding -- the
        confirmed drift itself -- must never be swallowed by that failure:
        it is still alerted (via :meth:`_dedupe_and_alert_mismatch`, which may
        be the first-sighting ``_alert_mismatch`` or the >=24h
        ``_alert_mismatch_persisting`` reminder) and still counted and
        returned as ``"DISAGREE"``. The halt-set failure gets its OWN,
        distinct CRITICAL alert (``fee_drift_probe_halt_set_failed``) so an
        operator can tell "drift detected, family halted" apart from
        "drift detected, halt did NOT take" -- the second is materially
        worse and must not look identical to the first in the alert stream.
        """
        try:
            wire_fee = await self._wire_fee_fetcher()
        except Exception as exc:  # noqa: BLE001 - any read failure is UNKNOWN, never "agrees"
            self._alert_unknown(exc)
            self.counters["unknown"] += 1
            logger.info(
                "event=fee_drift_probe outcome=UNKNOWN wire=none registered=%s",
                self._documented,
            )
            return "UNKNOWN"
        if wire_fee == self._documented:
            # A flap is news: an AGREE means the drift this dedupe state was
            # tracking is OVER, so a LATER mismatch -- even the SAME wire
            # value -- is a new event, not a continuation, and must re-alert
            # immediately rather than being swallowed by the old window.
            self._last_mismatch_wire_fee = None
            self._last_mismatch_alert_ts_ns = None
            # EDGE-1: only AGREE ever refreshes the staleness clock.
            self._last_agree_at_ns = self.clock.timestamp_ns()
            self.counters["agree"] += 1
            logger.info(
                "event=fee_drift_probe outcome=AGREE wire=%s registered=%s",
                wire_fee,
                self._documented,
            )
            return "AGREE"
        self._dedupe_and_alert_mismatch(wire_fee)
        try:
            self._set_family_halted(wire_fee)
        except Exception as exc:  # noqa: BLE001 - a halt-set failure must never crash the probe
            self._alert_halt_set_failed(exc, wire_fee)
            self.counters["halt_set_failed"] += 1
        self.counters["disagree"] += 1
        logger.info(
            "event=fee_drift_probe outcome=DISAGREE wire=%s registered=%s",
            wire_fee,
            self._documented,
        )
        return "DISAGREE"

    def _alert_unknown(self, exc: BaseException) -> None:
        emit_alert(
            self._alert_sink,
            AlertPayload(
                severity="CRITICAL",
                event="fee_drift_probe_unknown",
                site=self._site,
                detail=f"wire fee read failed: {type(exc).__name__}",
            ),
        )

    def _dedupe_and_alert_mismatch(self, wire_fee: Decimal) -> None:
        """CRITICAL once per distinct wire value; the SAME value is
        suppressed for :data:`_MISMATCH_SUPPRESSION_WINDOW_NS`, then gets
        exactly one ``fee_drift_probe_mismatch_persisting`` reminder, which
        re-arms its own window. A NEW distinct wire value always alerts
        immediately, regardless of any prior value's window.

        Timed on ``self.clock.timestamp_ns()`` -- this Actor's own, native
        clock (a live process's real clock or a test's ``TestClock``), never
        wall time, so a fast-forwarded backtest/test reasons about the
        window identically to a live process. Never shapes the halt: the
        caller (:meth:`probe_once`) still calls ``set_family_halted`` on
        every DISAGREE this method is invoked for, deduped or not.
        """
        now_ns = self.clock.timestamp_ns()
        if wire_fee != self._last_mismatch_wire_fee:
            self._alert_mismatch(wire_fee)
            self._last_mismatch_wire_fee = wire_fee
            self._last_mismatch_alert_ts_ns = now_ns
            return
        assert self._last_mismatch_alert_ts_ns is not None  # set alongside the wire fee, above
        elapsed_ns = now_ns - self._last_mismatch_alert_ts_ns
        if elapsed_ns >= _MISMATCH_SUPPRESSION_WINDOW_NS:
            self._alert_mismatch_persisting(wire_fee, elapsed_ns)
            self._last_mismatch_alert_ts_ns = now_ns

    def _alert_mismatch(self, wire_fee: Decimal) -> None:
        emit_alert(
            self._alert_sink,
            AlertPayload(
                severity="CRITICAL",
                event="fee_drift_probe_mismatch",
                site=self._site,
                detail=f"documented={self._documented} wire={wire_fee}",
            ),
        )

    def _alert_mismatch_persisting(self, wire_fee: Decimal, elapsed_ns: int) -> None:
        """The SAME drifted wire value is still live >= the suppression
        window after it was first alerted. Distinct event name from
        ``_alert_mismatch`` so an operator scanning the alert stream can tell
        "still drifted, unresolved" apart from "a fresh drift just
        appeared"."""
        emit_alert(
            self._alert_sink,
            AlertPayload(
                severity="CRITICAL",
                event="fee_drift_probe_mismatch_persisting",
                site=self._site,
                detail=(
                    f"documented={self._documented} wire={wire_fee} "
                    f"persisting_ns={elapsed_ns}"
                ),
            ),
        )

    def _alert_halt_set_failed(self, exc: BaseException, wire_fee: Decimal) -> None:
        """A DISAGREE was found but the durable halt-set write itself failed.

        Distinct event name, distinct alert, from ``_alert_mismatch`` above
        -- this must never be silently folded into "drift detected" (the
        mismatch alert already covers that); an operator who only ever sees
        ``fee_drift_probe_mismatch`` on a run where the write actually
        failed would believe the family is halted when it is not.
        """
        emit_alert(
            self._alert_sink,
            AlertPayload(
                severity="CRITICAL",
                event="fee_drift_probe_halt_set_failed",
                site=self._site,
                detail=f"halt-set failed after DISAGREE (wire={wire_fee}): {type(exc).__name__}",
            ),
        )

    # -- EDGE-1 (r2/B2'): the in-memory "fee unverified" staleness veto -----

    def is_fee_verified(self, now_ns: int) -> bool:
        """``True`` iff the last ``AGREE`` was within the staleness bound.

        ``now_ns`` is supplied by the CALLER -- AM-1 (security, binding):
        the strategy's entry gate must pass its OWN ``self.clock.
        timestamp_ns()``, never a market-data-derived time
        (``snapshot.ts_event`` can lag wall time under feed backlog, which
        would understate elapsed time and extend the "verified" window past
        its real staleness -- a fail-open bug). This method never reads its
        own clock for the comparison, so it reasons about whatever instant
        the caller hands it, identically in a test or a live process.

        Fires the two staleness alerts on the transition into "stale" and on
        the :data:`_FEE_UNVERIFIED_PERSISTING_WINDOW_NS` reminder cadence
        while it remains stale; clearing (a later ``AGREE``) is logged INFO
        only, matching this module's existing AGREE-is-silent asymmetry.
        Never raises.
        """
        verified = (
            self._last_agree_at_ns is not None
            and now_ns - self._last_agree_at_ns <= _FEE_VERIFIED_STALENESS_NS
        )
        if verified:
            if self._fee_unverified_alerted:
                self._fee_unverified_alerted = False
                self._fee_unverified_last_alert_ns = None
                logger.info(
                    "%s: fee-verified state cleared (AGREE within the staleness bound)",
                    self._site,
                )
            return True
        if not self._fee_unverified_alerted:
            self._fee_unverified_alerted = True
            self._fee_unverified_last_alert_ns = now_ns
            self._alert_fee_unverified_stale(now_ns)
        else:
            assert self._fee_unverified_last_alert_ns is not None  # set alongside the flag, above
            elapsed_ns = now_ns - self._fee_unverified_last_alert_ns
            if elapsed_ns >= _FEE_UNVERIFIED_PERSISTING_WINDOW_NS:
                self._fee_unverified_last_alert_ns = now_ns
                self._alert_fee_unverified_stale_persisting(elapsed_ns)
        return False

    def _alert_fee_unverified_stale(self, now_ns: int) -> None:
        elapsed_s = (
            "never"
            if self._last_agree_at_ns is None
            else str((now_ns - self._last_agree_at_ns) // 1_000_000_000)
        )
        emit_alert(
            self._alert_sink,
            AlertPayload(
                severity="CRITICAL",
                event="fee_drift_probe_fee_unverified_stale",
                site=self._site,
                detail=elapsed_s,
            ),
        )

    def _alert_fee_unverified_stale_persisting(self, elapsed_ns: int) -> None:
        """A 24h reminder while still stale, mirroring
        ``_alert_mismatch_persisting``'s own re-arming idiom."""
        emit_alert(
            self._alert_sink,
            AlertPayload(
                severity="CRITICAL",
                event="fee_drift_probe_fee_unverified_stale_persisting",
                site=self._site,
                detail=f"persisting_ns={elapsed_ns}",
            ),
        )
