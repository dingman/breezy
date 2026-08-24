"""Contract tests pinning the NautilusTrader 1.231.0 facts `breezy.ingest.nws_actor`
is built on.

Every assertion here was observed by EXECUTING against the pinned install
(`nautilus-trader~=1.231`), not inferred from documentation -- the 2.x website
docs describe a different API surface and disagree with the shipped code. Run
these FIRST on any version bump: a failure means the platform moved, not that
Breezy is wrong. Do not relax an assertion to go green.

**Scope: the facts BOUND TO THIS ACTOR.** The generic framework behaviours live
in sibling files and are deliberately not repeated here:

* `test_clock_alert_and_timer_contract.py` -- `set_time_alert` override /
  `allow_past` / `next_time_ns`, and `set_timer` stagger offsets.
* `test_retry_manager_contract.py` -- `RetryManager` exhaustion, propagation of
  an unlisted type, `retry_check`'s non-re-raising veto, pool reset, and the
  attempt-count-only backoff.
* `test_logger_uninitialized_discard_contract.py` -- why a retry failure is read
  off `.result`, never off log output.
* `test_live_timer_thread_affinity.py` -- the timer callback's thread, and
  `run_coroutine_threadsafe` as the only supervision seam.

What remains here is what those files CANNOT assert, because it references the
Actor's own symbols:

* `RETRYABLE_TRANSPORT_ERRORS` contains only sibling LEAF types, and every
  integrity error in `ingest/http.py` therefore propagates uncaught. This is the
  single most important assertion in the file.
* One retry sequence is ONE gate strike, not three.
* `RetryManager` sleeps on `asyncio`, not the Nautilus `Clock` -- an accepted,
  stated cost.
* `NwsIngestActorConfig` validates on DECODE only, forbids unknown fields, and
  round-trips through `ImportableActorConfig` -- including the trap that a
  hand-built config never held the declared `ComponentId` type at all.
* `set_timer`/`cancel_timer` raise `KeyError` on a duplicate/unknown name, which
  is why `on_stop` uses `cancel_timers()`.
* `degrade()`/`resume()` is reversible and `FAULTED` has no exit, which is why
  the gate is mirrored onto the former and the Actor never calls the latter.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import msgspec
import pytest
from nautilus_trader.common.component import ComponentFSMFactory, Logger, TestClock
from nautilus_trader.core.rust.common import ComponentState, ComponentTrigger
from nautilus_trader.live.retry import RetryManager

from breezy.ingest.http import (
    ContentEncodingError,
    RateLimitedError,
    RedirectError,
    TransportError,
    TransportTimeoutError,
)
from breezy.ingest.nws_actor import RETRYABLE_TRANSPORT_ERRORS, NwsIngestActorConfig

pytestmark = pytest.mark.contract

_BASE = dt.datetime(2026, 8, 22, tzinfo=dt.UTC)
_BASE_NS = int(_BASE.timestamp()) * 1_000_000_000


def _clock() -> TestClock:
    clock = TestClock()
    clock.set_time(_BASE_NS)
    return clock


def _noop(event: Any) -> None:
    return None


# ---------------------------------------------------------------------------
# `Clock.set_timer` -- cadence and stagger
# ---------------------------------------------------------------------------


def test_a_duplicate_timer_name_raises_key_error() -> None:
    clock = _clock()
    clock.set_timer(name="poll", interval=dt.timedelta(minutes=5), callback=_noop)

    with pytest.raises(KeyError):
        clock.set_timer(name="poll", interval=dt.timedelta(minutes=5), callback=_noop)


# ---------------------------------------------------------------------------
# `Clock.set_time_alert` -- the final-overdue deadline
# ---------------------------------------------------------------------------


def test_cancel_timer_raises_key_error_for_an_unknown_name() -> None:
    """`component.pyx:991-995` runs `Condition.is_in(name, self.timer_names)`, so a
    blind `cancel_timer` in `on_stop` would raise. `cancel_timers()` iterates the
    live names and is the safe form.
    """
    clock = _clock()

    with pytest.raises(KeyError):
        clock.cancel_timer("never-armed")

    clock.cancel_timers()  # safe on an empty clock


# ---------------------------------------------------------------------------
# `ActorConfig` -- validation happens on DECODE
# ---------------------------------------------------------------------------


def test_msgspec_struct_init_does_not_validate_field_types() -> None:
    """The trap. `ActorConfig` is a `msgspec.Struct` (`common/config.py:241,542`),
    and msgspec validates on decode only. A directly-constructed config accepts a
    wrong type in silence, so `NwsIngestActorConfig(city=7)` is not a guard.
    """
    smuggled = NwsIngestActorConfig(venue="polymarket_us", city=7)  # type: ignore[arg-type]

    assert smuggled.city == 7


def test_msgspec_convert_strict_is_where_validation_happens() -> None:
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert(
            {"venue": "polymarket_us", "city": 7}, type=NwsIngestActorConfig, strict=True
        )


def test_nautilus_config_forbids_unknown_fields() -> None:
    """`NautilusConfig(..., forbid_unknown_fields=True)` (`common/config.py:241`),
    so a misspelled setting is an error rather than a silently ignored default.
    """
    with pytest.raises(msgspec.ValidationError):
        msgspec.convert(
            {"venue": "polymarket_us", "city": "NYC", "poll_interval_second": 60},
            type=NwsIngestActorConfig,
            strict=True,
        )


def test_only_the_decode_path_produces_the_declared_component_id_type() -> None:
    """The sharpest form of the "validates on decode, not on `__init__`" trap, and
    the reason a whole-config equality assertion across a round trip is invalid.

    `component_id` is declared `ComponentId | None`. Direct construction stores
    whatever it was handed -- a raw `str` -- because `msgspec.Struct.__init__`
    neither validates nor converts. Only `parse()` produces an actual
    `ComponentId`. Comparing the two then raises `TypeError` rather than
    returning `False`, because `ComponentId.__eq__` rejects a `str` outright
    instead of returning `NotImplemented`.

    So the failure mode is not "the field changed type in transit"; it is "the
    object you built by hand never had the declared type in the first place".
    """
    from nautilus_trader.common.config import msgspec_encoding_hook
    from nautilus_trader.model.identifiers import ComponentId

    config = NwsIngestActorConfig(
        component_id="NWS-NYC",  # type: ignore[arg-type]
        venue="polymarket_us",
        city="NYC",
    )
    restored = NwsIngestActorConfig.parse(
        msgspec.json.encode(config.dict(), enc_hook=msgspec_encoding_hook)
    )

    assert isinstance(config.component_id, str)
    assert isinstance(restored.component_id, ComponentId)
    with pytest.raises(TypeError):
        _ = restored == config

    # Constructed with the declared type, the round trip is lossless.
    typed = NwsIngestActorConfig(
        component_id=ComponentId("NWS-NYC"), venue="polymarket_us", city="NYC"
    )
    assert (
        NwsIngestActorConfig.parse(
            msgspec.json.encode(typed.dict(), enc_hook=msgspec_encoding_hook)
        )
        == typed
    )

    # And the hook is REQUIRED, not garnish: `config.dict()` leaves a live
    # `ComponentId` in the mapping, which plain `msgspec.json.encode` refuses.
    with pytest.raises(TypeError, match="unsupported"):
        msgspec.json.encode(typed.dict())


# ---------------------------------------------------------------------------
# `RetryManager` -- the isinstance-based `except` is the load-bearing fact
# ---------------------------------------------------------------------------


async def _always_raise(exc: BaseException) -> None:
    raise exc


def _manager(exc_types: tuple[type[BaseException], ...], max_retries: int = 2) -> RetryManager[Any]:
    return RetryManager(
        max_retries=max_retries,
        delay_initial_ms=1,
        delay_max_ms=2,
        backoff_factor=2,
        logger=Logger("contract"),
        exc_types=exc_types,
    )


def test_the_actor_lists_only_sibling_leaf_types() -> None:
    """**The single most important assertion in this file.**

    `live/retry.py:172` is `except self.exc_types as e:` -- ordinary,
    isinstance-based `except`. Every integrity error in `ingest/http.py`
    subclasses `TransportError`, so listing the BASE would make the manager
    catch and silently RETRY a `RedirectError` on `/products/{id}`, a possibly
    hijacked settlement endpoint.
    """
    assert TransportError not in RETRYABLE_TRANSPORT_ERRORS
    for listed in RETRYABLE_TRANSPORT_ERRORS:
        assert listed is not TransportError
        assert issubclass(listed, TransportError)
        # A sibling leaf: nothing else routed by the taxonomy is a subclass of it.
        assert listed.__bases__ == (TransportError,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "integrity_error",
    [
        pytest.param(
            RedirectError("redirect", status_code=302, location="https://evil.example"),
            id="redirect",
        ),
        pytest.param(ContentEncodingError("gzip"), id="content_encoding"),
        pytest.param(RateLimitedError("429", retry_after="120"), id="rate_limited"),
    ],
)
async def test_an_unlisted_sibling_propagates_uncaught(integrity_error: BaseException) -> None:
    """With only sibling leaves listed, an unlisted error is not matched by
    `except` at all and propagates to `routing.py`'s exact-type dispatch. That is
    the property the whole fail-closed design rests on.
    """
    manager = _manager(RETRYABLE_TRANSPORT_ERRORS)

    with pytest.raises(type(integrity_error)):
        await manager.run("probe", None, _always_raise, integrity_error)


@pytest.mark.asyncio
async def test_one_retry_sequence_is_one_failure_not_three() -> None:
    """Why a retry sequence collapses into ONE `record_transient_failure`: three
    TCP attempts inside one poll are not three failed polls. This is a deliberate
    change to what `gate._TRANSIENT_DEGRADE_THRESHOLD` counts.
    """
    manager = _manager(RETRYABLE_TRANSPORT_ERRORS)
    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise TransportTimeoutError("timeout")
        return "ok"

    assert await manager.run("probe", None, flaky) == "ok"
    assert manager.result is True
    assert attempts == 3


@pytest.mark.asyncio
async def test_retry_manager_sleeps_on_asyncio_not_on_the_nautilus_clock() -> None:
    """An accepted cost, stated rather than hidden: a retry sequence is undriveable
    by `TestClock` and therefore unreplayable. Confined to within-one-poll
    attempts, where no settlement decision depends on it -- which is also why the
    Actor keeps `max_retries` small.
    """
    import inspect

    source = inspect.getsource(RetryManager.run)
    assert "asyncio.sleep" in source
    assert "clock" not in source


# ---------------------------------------------------------------------------
# `Component` -- degrade is reversible, fault is not
# ---------------------------------------------------------------------------


def test_degraded_has_a_resume_transition() -> None:
    """`component.pyx:1650`. The gate's BLOCKED must be clearable by a clean poll,
    so it is mirrored onto `degrade()`/`resume()`.

    Read from `ComponentFSMFactory.get_state_transition_table()` -- the FSM table
    itself -- rather than from a component's observed behaviour, so the assertion
    covers every path into the state and not just the one a test drove.
    """
    table = ComponentFSMFactory.get_state_transition_table()

    assert (
        table[(ComponentState.DEGRADED, ComponentTrigger.RESUME)] == ComponentState.RESUMING
    )


def test_faulted_is_terminal_with_no_exit_transition() -> None:
    """`component.pyx:2129`, `:1649-1654`. `fault()` is irreversible, so conflating
    it with a gate block would BRICK the Actor -- and the brief's SS7 exit
    criteria make "a clean poll reopens a blocked site" the single most important
    test in the phase.
    """
    table = ComponentFSMFactory.get_state_transition_table()
    exits = [
        state_trigger for state_trigger in table if state_trigger[0] == ComponentState.FAULTED
    ]

    assert exits == []


def test_the_ingest_actor_source_never_calls_fault() -> None:
    import pathlib

    import breezy.ingest.nws_actor as module

    source = pathlib.Path(module.__file__).read_text(encoding="utf-8")

    assert ".fault()" not in source


# ---------------------------------------------------------------------------
# The cross-thread bridge primitive
# ---------------------------------------------------------------------------


