"""Discovery and factory units for ``current_rung_hold`` composition."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol, TraderId, Venue
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
)
from breezy.adapters.polymarket_us.safety import issue_live_trading_permit
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
    WEATHER_FACTS_STATUS_UNKNOWN,
)
from breezy.runtime.order_enablement import OrderSubmissionPermit
from breezy.runtime.settings import SettingsError
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.composition import (
    NoTradableInstrumentsError,
    build_continuous_rung_hold_strategies,
    build_current_rung_hold_strategies,
    family_halt_submit_veto,
    phase0_family_permits,
    phase1_family_permits,
    resolve_station_instrument_ids,
    strategy_component_id,
)
from breezy.strategy.current_rung_hold.config import SUPPORTED_STATIONS
from breezy.strategy.current_rung_hold.continuous_strategy import ContinuousRungHoldStrategy
from breezy.strategy.current_rung_hold.strategy import CurrentRungHoldStrategy
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    open_trial_day_latch,
)
from breezy.strategy.weather_common.refusals import RefusalCounter
from tests.unit.operator_control_env import operator_control_env
from tests.unit.test_polymarket_us_permit_issuance import clock_at, enable_operator_gate
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_verified,  # noqa: F401 -- reused fixture, see test below
)

_POLYMARKET_VENUE = Venue("POLYMARKET_US")
_DAY = dt.date(2026, 9, 4)
_TODAY = {station: _DAY for station in SUPPORTED_STATIONS}


def _binary(
    slug: str,
    *,
    info: dict[str, object],
    ts: int = 0,
) -> BinaryOption:
    instrument_id = InstrumentId(Symbol(slug), _POLYMARKET_VENUE)
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        outcome="Yes",
        description="test",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=increment.precision,
        price_increment=increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=200 * 3_600_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal("0.06"),
        taker_fee=Decimal("0.06"),
        # ``ts_event``/``ts_init`` are DISTINCT per call (default ``ts=0``
        # keeps every other test's byte-identical, single-file behavior
        # unchanged): the real recorder's re-emitted definitions carry
        # distinct discovery-cycle timestamps, which is exactly what makes
        # ``ParquetDataCatalog`` write a NEW file per cycle instead of
        # silently skipping an identical-name duplicate.
        ts_event=ts,
        ts_init=ts,
        info=info,
    )


def _known(*, station: str, day: dt.date, measure: str = "high") -> dict[str, object]:
    return {
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: station,
        CLIMATE_DAY_KEY: day.isoformat(),
        MEASURE_KEY: measure,
        STRIKE_LOWER_F_KEY: 80,
        STRIKE_UPPER_F_KEY: 81,
    }


def _write(catalog_root: Path, instruments: list[BinaryOption]) -> None:
    ParquetDataCatalog(str(catalog_root)).write_data(instruments)


def test_strategy_component_id_is_unique_per_station() -> None:
    ids = [strategy_component_id(station) for station in SUPPORTED_STATIONS]
    assert len(ids) == len(set(ids))
    assert ids[0] == "CurrentRungHoldStrategy-LAX"


def test_discovery_keeps_only_high_supported_stations_on_the_station_climate_day(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        [
            _binary(
                "tc-temp-laxhigh-2026-09-04-gte80lt81f",
                info=_known(station="LAX", day=_DAY),
            ),
            _binary(
                "tc-temp-laxlow-2026-09-04-gte50lt51f",
                info=_known(station="LAX", day=_DAY, measure="low"),
            ),
            _binary(
                "tc-temp-laxhigh-2026-09-03-gte80lt81f",
                info=_known(station="LAX", day=dt.date(2026, 9, 3)),
            ),
            _binary(
                "tc-temp-nychigh-2026-09-04-lt79f",
                info=_known(station="NYC", day=_DAY),
            ),
            _binary(
                "tc-temp-mdwhigh-2026-09-04-gte90lt91f",
                info=_known(station="MDW", day=_DAY),
            ),
        ],
    )

    resolved = resolve_station_instrument_ids(tmp_path, _TODAY)

    assert [str(iid) for iid in resolved["LAX"]] == [
        "tc-temp-laxhigh-2026-09-04-gte80lt81f.POLYMARKET_US"
    ]
    assert [str(iid) for iid in resolved["MDW"]] == [
        "tc-temp-mdwhigh-2026-09-04-gte90lt91f.POLYMARKET_US"
    ]
    assert resolved["MIA"] == ()
    assert resolved["SFO"] == ()


def test_discovery_falls_back_to_the_slug_when_facts_are_unknown(tmp_path: Path) -> None:
    _write(
        tmp_path,
        [
            _binary(
                "tc-temp-miahigh-2026-09-04-gte91lt92f",
                info={WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_UNKNOWN},
            ),
        ],
    )

    resolved = resolve_station_instrument_ids(tmp_path, _TODAY)

    assert [str(iid) for iid in resolved["MIA"]] == [
        "tc-temp-miahigh-2026-09-04-gte91lt92f.POLYMARKET_US"
    ]


def test_discovery_dedupes_a_definition_re_emitted_across_recorder_cycles(
    tmp_path: Path,
) -> None:
    """The quote-tape recorder re-emits every instrument's definition each
    discovery cycle (docstring above), so ``catalog.instruments()`` returns
    the SAME ``InstrumentId`` many times over several ``write_data`` calls.
    ``resolve_station_instrument_ids`` must collapse those to one id per
    station, first-seen, not one entry per recorded row.
    """
    for cycle in range(4):
        _write(
            tmp_path,
            [
                _binary(
                    "tc-temp-laxhigh-2026-09-04-gte80lt81f",
                    info=_known(station="LAX", day=_DAY),
                    ts=cycle,
                )
            ],
        )

    resolved = resolve_station_instrument_ids(tmp_path, _TODAY)

    assert [str(iid) for iid in resolved["LAX"]] == [
        "tc-temp-laxhigh-2026-09-04-gte80lt81f.POLYMARKET_US"
    ]


@contextmanager
def _unused_latch_factory() -> Iterator[object]:
    yield object()


def test_all_stations_zero_raises_no_tradable_instruments_error(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    with pytest.raises(NoTradableInstrumentsError) as excinfo:
        build_current_rung_hold_strategies(
            catalog_root=tmp_path,
            today_by_station=_TODAY,
            trial_day_latch_factory=_unused_latch_factory,
        )

    message = str(excinfo.value)
    assert "LAX=0" in message
    assert "MDW=0" in message
    assert "MIA=0" in message
    assert "SFO=0" in message
    assert "2026-09-04" in message


def test_per_station_degradation_skips_zero_and_builds_the_rest(tmp_path: Path) -> None:
    _write(
        tmp_path,
        [
            _binary(
                "tc-temp-sfohigh-2026-09-04-gte70lt71f",
                info=_known(station="SFO", day=_DAY),
            ),
        ],
    )

    strategies = build_current_rung_hold_strategies(
        catalog_root=tmp_path,
        today_by_station=_TODAY,
        trial_day_latch_factory=_unused_latch_factory,
    )

    assert len(strategies) == 1
    strategy = strategies[0]
    assert isinstance(strategy, CurrentRungHoldStrategy)
    assert strategy._config.stations == ("SFO",)
    assert strategy._config.orders_enabled is False
    assert str(strategy.id) == "CurrentRungHoldStrategy-SFO"
    assert strategy.order_id_tag == "SFO"


def test_on_start_subscribes_each_instrument_exactly_once_despite_re_emitted_definitions(
    tmp_path: Path,
) -> None:
    """End-to-end through ``build_current_rung_hold_strategies`` + a real
    ``on_start``: a catalog holding the SAME instrument recorded 3 times
    (re-emitted definitions, as ``resolve_station_instrument_ids`` documents)
    must still yield exactly ONE ``subscribe_quote_ticks`` call per
    instrument -- never one per recorded row.
    """
    instrument = _binary(
        "tc-temp-sfohigh-2026-09-04-gte70lt71f",
        info=_known(station="SFO", day=_DAY),
    )
    for cycle in range(3):
        _write(
            tmp_path,
            [
                _binary(
                    "tc-temp-sfohigh-2026-09-04-gte70lt71f",
                    info=_known(station="SFO", day=_DAY),
                    ts=cycle,
                )
            ],
        )

    strategies = build_current_rung_hold_strategies(
        catalog_root=tmp_path,
        today_by_station=_TODAY,
        trial_day_latch_factory=_unused_latch_factory,
    )
    assert len(strategies) == 1
    strategy = strategies[0]
    assert strategy._config.instrument_ids == (instrument.id,)

    clock = TestClock()
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    cache.add_instrument(instrument)
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    strategy.register(
        trader_id=TraderId("BACKTEST-001"),
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
    subscribed: list[InstrumentId] = []
    strategy.subscribe_quote_ticks = subscribed.append  # type: ignore[method-assign]
    strategy.start()

    assert subscribed == [instrument.id]


class _FakeStrategy:
    """Duck-typed stand-in: `install_current_rung_hold_refusal_watch` only
    reads `.refusals`/`.diagnostics`/`.position_events`/`.id` and sets
    `.refusal_alerter`/`.diagnostics_alerter`/`.position_alerter` -- it
    never constructs a real `CurrentRungHoldStrategy`. The counters are
    the REAL `RefusalCounter` (a trivial dict-of-ints value type, no
    Nautilus coupling) so a test can drive `.record()` and exercise the
    real `RefusalAlerter`s this function wires, without a real strategy.
    """

    def __init__(self, strategy_id: str) -> None:
        self.id = strategy_id
        self.refusals = RefusalCounter()
        self.refusal_alerter: object | None = None
        self.diagnostics = RefusalCounter()
        self.diagnostics_alerter: object | None = None
        self.position_events = RefusalCounter()
        self.position_alerter: object | None = None


class _RecordingSink:
    """An `AlertSink` that keeps what it was handed (see
    `test_weather_common_refusals.py`'s identical helper).
    """

    def __init__(self) -> None:
        self.payloads: list[object] = []

    def emit(self, payload: object) -> None:
        self.payloads.append(payload)


class TestInstallRefusalWatch:
    def test_a_strategy_is_wired_for_per_tick_reporting_with_no_msgbus_at_all(
        self,
    ) -> None:
        """The primary (per-tick) path needs no `msgbus`, so a `node` with
        none still gets `strategy.refusal_alerter` populated.
        """
        from breezy.strategy.current_rung_hold.composition import (
            install_current_rung_hold_refusal_watch,
        )

        strategy = _FakeStrategy("CurrentRungHoldStrategy-LAX")
        install_current_rung_hold_refusal_watch(object(), [strategy])  # type: ignore[list-item]

        assert strategy.refusal_alerter is not None
        # Diagnostics get the SAME per-tick wiring, over a separate alerter
        # bound to `.diagnostics`, never `.refusals`.
        assert strategy.diagnostics_alerter is not None
        assert strategy.diagnostics_alerter is not strategy.refusal_alerter

    def test_a_missing_msgbus_logs_a_warning_instead_of_failing_silently(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        from breezy.strategy.current_rung_hold.composition import (
            install_current_rung_hold_refusal_watch,
        )

        class _KernellessNode:
            kernel = None

        strategy = _FakeStrategy("CurrentRungHoldStrategy-LAX")
        with caplog.at_level("WARNING"):
            install_current_rung_hold_refusal_watch(
                _KernellessNode(), [strategy]  # type: ignore[list-item]
            )

        assert any(
            record.levelname == "WARNING" and "msgbus" in record.getMessage()
            for record in caplog.records
        )
        # The primary path still wires despite the missing msgbus.
        assert strategy.refusal_alerter is not None

    def test_the_diagnostics_alerter_uses_wait_vocabulary_not_refusal_vocabulary(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Review finding 1: a WAIT-state diagnostic must never be reported
        in genuine-refusal vocabulary (the previous hardcoded `..._REFUSALS`
        event / "order(s) refused as ..." detail) -- exercises the REAL
        production wiring (not a hand-built `RefusalAlerter`), so a drift
        between this test and `install_current_rung_hold_refusal_watch`'s
        actual vocabulary would fail here.
        """
        from breezy.strategy.current_rung_hold import composition as composition_module

        sink = _RecordingSink()
        monkeypatch.setattr(composition_module, "resolve_alert_sink", lambda: sink)

        strategy = _FakeStrategy("CurrentRungHoldStrategy-LAX")
        composition_module.install_current_rung_hold_refusal_watch(
            object(), [strategy],  # type: ignore[list-item]
        )
        assert strategy.diagnostics_alerter is not None

        strategy.diagnostics.record("in_window_not_executable")
        strategy.diagnostics_alerter.report(now_ns=1_000)  # type: ignore[attr-defined]

        assert len(sink.payloads) == 1
        payload = sink.payloads[0]
        assert payload.event == "IN_WINDOW_NOT_EXECUTABLE_WAIT"  # type: ignore[attr-defined]
        assert "refused" not in payload.detail  # type: ignore[attr-defined]

    def test_the_diagnostics_alerter_renotifies_sooner_than_the_refusal_default(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Review finding 2: `AlertState`'s 24h default re-notify is longer
        than the whole `[12:00,17:00)` LST decision window, so a diagnostic
        firing once at the start of an afternoon would otherwise never show
        its count growing again before the process next restarts. The
        diagnostics alerter must re-notify materially sooner than the
        refusal alerters' UNCHANGED 24h default -- proved by advancing past
        the diagnostics cadence but staying well under 24h.
        """
        from breezy.strategy.current_rung_hold import composition as composition_module

        sink = _RecordingSink()
        monkeypatch.setattr(composition_module, "resolve_alert_sink", lambda: sink)

        strategy = _FakeStrategy("CurrentRungHoldStrategy-LAX")
        composition_module.install_current_rung_hold_refusal_watch(
            object(), [strategy],  # type: ignore[list-item]
        )
        assert strategy.refusal_alerter is not None
        assert strategy.diagnostics_alerter is not None

        strategy.refusals.record("outside_decision_window")
        strategy.diagnostics.record("in_window_not_executable")
        strategy.refusal_alerter.report(now_ns=0)  # type: ignore[attr-defined]
        strategy.diagnostics_alerter.report(now_ns=0)  # type: ignore[attr-defined]
        assert len(sink.payloads) == 2  # both false->true transitions fire
        sink.payloads.clear()

        # 20 minutes later: inside a covered afternoon's decision window,
        # well under the refusal path's 24h re-notify, but past a
        # materially shorter diagnostics-only cadence.
        twenty_minutes_ns = 20 * 60 * 1_000_000_000
        strategy.refusals.record("outside_decision_window")
        strategy.diagnostics.record("in_window_not_executable")
        strategy.refusal_alerter.report(now_ns=twenty_minutes_ns)  # type: ignore[attr-defined]
        strategy.diagnostics_alerter.report(now_ns=twenty_minutes_ns)  # type: ignore[attr-defined]

        assert len(sink.payloads) == 1
        assert sink.payloads[0].event == "IN_WINDOW_NOT_EXECUTABLE_WAIT"  # type: ignore[attr-defined]

    def test_a_strategy_is_wired_with_a_position_alerter(
        self,
    ) -> None:
        from breezy.strategy.current_rung_hold.composition import (
            install_current_rung_hold_refusal_watch,
        )

        strategy = _FakeStrategy("CurrentRungHoldStrategy-LAX")
        install_current_rung_hold_refusal_watch(object(), [strategy])  # type: ignore[list-item]

        assert strategy.position_alerter is not None
        assert strategy.position_alerter is not strategy.refusal_alerter
        assert strategy.position_alerter is not strategy.diagnostics_alerter

    def test_the_position_alerter_uses_log_only_vocabulary_not_refusal_vocabulary(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from breezy.strategy.current_rung_hold import composition as composition_module

        sink = _RecordingSink()
        monkeypatch.setattr(composition_module, "resolve_alert_sink", lambda: sink)

        strategy = _FakeStrategy("CurrentRungHoldStrategy-LAX")
        composition_module.install_current_rung_hold_refusal_watch(
            object(), [strategy],  # type: ignore[list-item]
        )
        assert strategy.position_alerter is not None

        strategy.position_events.record("position_opened")
        strategy.position_alerter.report(now_ns=1_000)  # type: ignore[attr-defined]

        assert len(sink.payloads) == 1
        payload = sink.payloads[0]
        assert payload.event == "POSITION_OPENED_POSITION"  # type: ignore[attr-defined]
        assert "refused" not in payload.detail  # type: ignore[attr-defined]
        assert "never an order" in payload.detail  # type: ignore[attr-defined]

    def test_the_three_alerters_are_wired_from_one_binding_table(
        self,
    ) -> None:
        """Intra-module: refusal / diagnostics / position share one binding
        table rather than three copy-pasted comprehensions.
        """
        from breezy.strategy.current_rung_hold.composition import _ALERTER_BINDINGS

        pairs = {(binding.counter_attr, binding.alerter_attr) for binding in _ALERTER_BINDINGS}
        assert pairs == {
            ("refusals", "refusal_alerter"),
            ("diagnostics", "diagnostics_alerter"),
            ("position_events", "position_alerter"),
        }
        assert len(_ALERTER_BINDINGS) == 3


def test_continuous_builder_uses_distinct_strategy_id(tmp_path: Path) -> None:
    _write(
        tmp_path,
        [
            _binary(
                "tc-temp-sfohigh-2026-09-04-gte70lt71f",
                info=_known(station="SFO", day=_DAY),
            ),
        ],
    )
    v2 = build_current_rung_hold_strategies(
        catalog_root=tmp_path,
        today_by_station=_TODAY,
        trial_day_latch_factory=_unused_latch_factory,
    )
    v3 = build_continuous_rung_hold_strategies(
        catalog_root=tmp_path,
        today_by_station=_TODAY,
        trial_day_latch_factory=_unused_latch_factory,
        order_submission_permit=None,
    )
    assert len(v2) == 1 and len(v3) == 1
    assert isinstance(v2[0], CurrentRungHoldStrategy)
    assert isinstance(v3[0], ContinuousRungHoldStrategy)
    assert str(v2[0].id) == "CurrentRungHoldStrategy-SFO"
    assert str(v3[0].id) == "ContinuousRungHoldStrategy-SFO"
    assert v3[0]._order_submission_permit is None


def test_continuous_builder_defaults_the_offer_tape_to_a_sibling_decisions_dir(
    tmp_path: Path,
) -> None:
    """GAP fix 2026-09-15: `offer_tape_path=None` (the live default --
    `app/trade.py` never passes this kwarg) must no longer mean
    in-memory-only -- it resolves to a real JSONL sidecar under a sibling
    `decisions/` dir, never nested under the quote-tape catalog root."""
    _write(
        tmp_path,
        [
            _binary(
                "tc-temp-sfohigh-2026-09-04-gte70lt71f",
                info=_known(station="SFO", day=_DAY),
            ),
        ],
    )
    v3 = build_continuous_rung_hold_strategies(
        catalog_root=tmp_path,
        today_by_station=_TODAY,
        trial_day_latch_factory=_unused_latch_factory,
        order_submission_permit=None,
    )
    assert len(v3) == 1
    offer_tape = v3[0].offer_tape
    assert offer_tape._path is not None  # type: ignore[attr-defined]
    assert offer_tape._path.parent.name == "decisions"  # type: ignore[attr-defined]
    assert offer_tape._path.parent.parent == tmp_path.parent  # type: ignore[attr-defined]
    assert offer_tape._path.name == f"offer_tape_{_DAY.isoformat()}.jsonl"  # type: ignore[attr-defined]


def test_continuous_builder_honors_an_explicit_offer_tape_path(tmp_path: Path) -> None:
    """An explicit `offer_tape_path` still wins unconditionally -- the
    default above never overrides a caller's own choice (tests/the backtest
    harness keep working unedited)."""
    _write(
        tmp_path,
        [
            _binary(
                "tc-temp-sfohigh-2026-09-04-gte70lt71f",
                info=_known(station="SFO", day=_DAY),
            ),
        ],
    )
    explicit_path = tmp_path / "explicit.jsonl"
    v3 = build_continuous_rung_hold_strategies(
        catalog_root=tmp_path,
        today_by_station=_TODAY,
        trial_day_latch_factory=_unused_latch_factory,
        order_submission_permit=None,
        offer_tape_path=explicit_path,
    )
    assert v3[0].offer_tape._path == explicit_path  # type: ignore[attr-defined]


def test_build_continuous_rung_hold_strategies_survives_an_unwritable_offer_tape_sidecar(
    tmp_path: Path,
) -> None:
    """H1 review finding (commit 309dab6): a blocked sidecar directory must
    never raise out of strategy construction at the live 16:50Z boot --
    ``OfferTape.__init__`` is best-effort (see
    ``tests/unit/test_current_rung_hold_offer_tape.py``)."""
    _write(
        tmp_path,
        [
            _binary(
                "tc-temp-sfohigh-2026-09-04-gte70lt71f",
                info=_known(station="SFO", day=_DAY),
            ),
        ],
    )
    blocker = tmp_path / "blocker_file"
    blocker.write_text("not a directory")
    offer_tape_path = blocker / "offer_tape.jsonl"

    v3 = build_continuous_rung_hold_strategies(
        catalog_root=tmp_path,
        today_by_station=_TODAY,
        trial_day_latch_factory=_unused_latch_factory,
        order_submission_permit=None,
        offer_tape_path=offer_tape_path,
    )

    assert len(v3) == 1
    assert v3[0].offer_tape.sidecar_errors == 1


def test_continuous_builder_refuses_a_non_none_permit(tmp_path: Path) -> None:
    """Phase 0 seal: `build_continuous_rung_hold_strategies` refuses a
    non-None `order_submission_permit`, naming Phase 0 in the error."""
    from breezy.strategy.current_rung_hold.continuous_strategy import (
        Phase0PermitForbiddenError,
    )

    _write(
        tmp_path,
        [
            _binary(
                "tc-temp-sfohigh-2026-09-04-gte70lt71f",
                info=_known(station="SFO", day=_DAY),
            ),
        ],
    )
    with pytest.raises(Phase0PermitForbiddenError, match="Phase 0"):
        build_continuous_rung_hold_strategies(
            catalog_root=tmp_path,
            today_by_station=_TODAY,
            trial_day_latch_factory=_unused_latch_factory,
            order_submission_permit=object(),  # type: ignore[arg-type]
        )


def test_no_flag_combination_mints_two_sending_families() -> None:
    fake_permit = object()
    for current in (False, True):
        for cont in (False, True):
            for permit in (None, fake_permit):
                v2, v3 = phase0_family_permits(
                    current_rung_hold=current,
                    continuous_rung_hold=cont,
                    permit=permit,  # type: ignore[arg-type]
                )
                assert v3 is None
                if current and permit is not None:
                    assert v2 is permit
                else:
                    assert v2 is None
                assert not (v2 is not None and v3 is not None)


# ---------------------------------------------------------------------------
# F3/F4 (plan rev 6.1, Phase 1): phase1_family_permits gives the single
# sending family's permit to whichever family is on -- v3 (continuous_rung_
# hold) MAY hold it here, unlike phase0_family_permits (kept, unchanged,
# above). Both families on together is refused (SettingsError) unless the
# Phase 0 shadow flag is threaded in, matching phase0_family_permits exactly.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _PermitRoutingSettings:
    """The narrow ``SettingsLike`` surface ``OrderSubmissionPermit.issue``
    needs, with ``current_rung_hold``/``continuous_rung_hold`` varied per
    combo under test."""

    current_rung_hold: bool
    continuous_rung_hold: bool
    orders_enabled_requested: bool = True
    live_observations: bool = True


def _mint_real_permit(
    monkeypatch: pytest.MonkeyPatch, *, current: bool, continuous: bool
) -> OrderSubmissionPermit:
    """Mint a genuine, sealed ``OrderSubmissionPermit`` for the given family
    combo -- F4 requires a real permit object, not a fake, so
    ``phase1_family_permits`` is exercised against the same construction
    path production uses."""
    enable_operator_gate(monkeypatch)
    clock = clock_at()
    live_permit = issue_live_trading_permit(clock=clock)
    settings = _PermitRoutingSettings(current_rung_hold=current, continuous_rung_hold=continuous)
    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "10.00"),
    ):
        return OrderSubmissionPermit.issue(
            settings=settings, live_trading_permit=live_permit, clock=clock,
        )


@pytest.mark.parametrize("shadow", (False, True))
@pytest.mark.parametrize("continuous", (False, True))
@pytest.mark.parametrize("current", (False, True))
def test_phase1_family_permits_all_combos_with_a_real_permit(
    current: bool,
    continuous: bool,
    shadow: bool,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    if not (current or continuous):
        # No family on: no permit is ever minted in production for this
        # combo (issue() itself refuses it); the routing function alone must
        # still resolve to no holder for a None permit.
        v2, v3 = phase1_family_permits(
            current_rung_hold=current,
            continuous_rung_hold=continuous,
            permit=None,
            phase0_shadow=shadow,
        )
        assert v2 is None
        assert v3 is None
        return

    permit = _mint_real_permit(monkeypatch, current=current, continuous=continuous)

    if current and continuous and not shadow:
        with pytest.raises(SettingsError):
            phase1_family_permits(
                current_rung_hold=current,
                continuous_rung_hold=continuous,
                permit=permit,
                phase0_shadow=shadow,
            )
        return

    v2, v3 = phase1_family_permits(
        current_rung_hold=current,
        continuous_rung_hold=continuous,
        permit=permit,
        phase0_shadow=shadow,
    )
    holders = [p for p in (v2, v3) if p is not None]
    assert len(holders) <= 1, "at most one family may hold the permit"
    if shadow:
        assert v3 is None
        assert v2 is (permit if current else None)
    elif continuous:
        assert v3 is permit
        assert v2 is None
    else:
        assert v2 is permit
        assert v3 is None


def test_continuous_only_phase1_builds_strategies_holding_the_real_permit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """End-to-end F3 wiring: continuous-only, no shadow -- the single
    sending family's permit is routed to v3, `build_continuous_rung_hold_
    strategies` is called with `phase0_permit_guard=(v3 is None)` exactly as
    `app/trade.py::run` does, and every constructed station strategy holds
    the SAME real permit object. v2 is never composed for this combo (there
    is no `current_rung_hold` flag on, so `app/trade.py::run` never calls
    `build_current_rung_hold_strategies` at all -- asserted here by never
    calling it)."""
    _write(
        tmp_path,
        [
            _binary("tc-temp-sfohigh-2026-09-04-gte70lt71f", info=_known(station="SFO", day=_DAY)),
            _binary("tc-temp-laxhigh-2026-09-04-gte70lt71f", info=_known(station="LAX", day=_DAY)),
        ],
    )
    permit = _mint_real_permit(monkeypatch, current=False, continuous=True)

    v2, v3 = phase1_family_permits(
        current_rung_hold=False,
        continuous_rung_hold=True,
        permit=permit,
        phase0_shadow=False,
    )
    assert v2 is None
    assert v3 is permit

    strategies = build_continuous_rung_hold_strategies(
        catalog_root=tmp_path,
        today_by_station=_TODAY,
        trial_day_latch_factory=_unused_latch_factory,
        order_submission_permit=v3,
        phase0_permit_guard=v3 is None,
    )
    assert len(strategies) == 2
    for strategy in strategies:
        assert isinstance(strategy, ContinuousRungHoldStrategy)
        assert strategy._order_submission_permit is permit


# ---------------------------------------------------------------------------
# Item 4 (slice 4 review, plan rev 6.1): family_halt_submit_veto -- a unit
# test on the veto callable in isolation (constructed here from a bare
# TrialDayLatch, no exec client involved). The end-to-end plumbing this
# callable feeds -- PolymarketUSExecClientConfig.submit_veto ->
# factories.py -> node_config.build_trade_node_config -> trade_cli.run ->
# app/trade.py::run's `family_halt_submit_veto(family_halt_latch)` at the
# v3 composition call site -- is now COMPLETE; the live end-to-end proof
# (composing + submitting through a real exec client denies WAIT-class
# with zero permit slots spent while the halt key is set) is
# tests/unit/test_current_rung_hold_ambiguous_resolver.py::
# test_a_family_halt_veto_denies_wait_class_and_spends_zero_permit_slots.
# ---------------------------------------------------------------------------


def test_family_halt_submit_veto_is_none_until_the_halt_key_is_set(tmp_path: Path) -> None:
    """The veto is a synchronous, read-only ``is_family_halted()`` under the
    SAME flock the given ``TrialDayLatch`` already holds -- no fresh open,
    no I/O beyond that read."""
    store_path = tmp_path / "state.db"
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        trial_day_latch = open_trial_day_latch(
            intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
        )
        veto = family_halt_submit_veto(trial_day_latch)

        assert veto() is None

        trial_day_latch.record_duplicate_fill(
            "SFO",
            "2026-09-04",
            venue_order_id="venue-order-1",
            qty=Decimal(1),
            fill_px=Decimal("0.50"),
            fee=Decimal("0.01"),
            ts_ns=1,
        )

        assert veto() == "family_halt"
        # Idempotent: a second call re-reads the SAME durable key, not a
        # cached value on the veto closure itself.
        assert veto() == "family_halt"


def test_family_halt_submit_veto_reads_a_family_wide_key_not_a_station_scoped_one(
    tmp_path: Path,
) -> None:
    """The halt is FAMILY-wide (`FAMILY_HALT_KEY`, one singleton per store),
    so a veto built from ANY station's `TrialDayLatch` binding observes a
    halt set via any other station's fill -- same store, same key, same
    flock."""
    store_path = tmp_path / "state.db"
    with open_submit_intent_latch(SqliteStateStore(store_path), store_path) as intent_latch:
        sfo_latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
        lax_latch = open_trial_day_latch(intent_latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX)
        veto_for_lax = family_halt_submit_veto(lax_latch)

        assert veto_for_lax() is None

        sfo_latch.record_duplicate_fill(
            "SFO",
            "2026-09-04",
            venue_order_id="venue-order-2",
            qty=Decimal(1),
            fill_px=Decimal("0.50"),
            fee=Decimal("0.01"),
            ts_ns=1,
        )

        assert veto_for_lax() == "family_halt"
