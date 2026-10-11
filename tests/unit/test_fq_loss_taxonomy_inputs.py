"""TE-2 WP0 (RED): truth, log and count wrappers of the FQ v1 loss taxonomy.

Plan tests 33-35, 40-43, 45, 46, 48, 49 (the pin/git tests live in ..._pins.py, the AST pin in
..._guard.py). Offline and synthetic. Per L-55 each injected fake is paired with a production
default path: the real ``NwsCliFinal`` over a tmp Parquet catalog, the real ``C1Epoch`` over an
empty data root, and the real ``read_durable_fills`` over a store written by the real writer.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import inspect
import tracemalloc
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from breezy.analysis.labeling.attribution import BackfillRefused
from breezy.analysis.labeling.decision_link import parse_log_line, read_log_events
from breezy.analysis.labeling.fill_source import FillStoreCorruption, read_durable_fills
from breezy.analysis.labeling.settlement_source import NwsCliFinal
from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.persistence.autonomy.capture_reader import OrderLinkView
from breezy.persistence.catalog import open_station_catalog, write_records
from breezy.runtime.sqlite_store import SqliteStateStore
from scripts.analysis.fq_loss_taxonomy_core import (
    S0DMiss,
    classify_s0d_miss,
    s0d_compare,
)
from scripts.analysis.fq_loss_taxonomy_inputs import (
    ClippingSettlementSource,
    PhaseAProjection,
    S0ACounts,
    S0AStop,
    UnclassifiedFillsStop,
    UnparseableInstrumentStop,
    alt_truth_summary,
    attribute_fills,
    iter_partition_events,
    partition_union,
    phase_a_truth,
    project_phase_a,
    reproduce_audit,
    s0a_counts,
    s0a_gate,
    stream_take_events,
    truth_status,
)
from tests.support.aut2_fixtures import FILL_KEY_PREFIX, durable_fill, seed_fills
from tests.support.te2_fixtures import (
    fill_read,
    fq_durable_fills,
    fq_out_of_scope_fill,
    fq_september_fills,
    fq_settlement_records,
    log_filled,
    log_init,
    log_refuse,
    log_take,
    nws_record,
)

_LAX_YES = "tc-temp-laxhigh-2026-10-02-gte89lt90f.POLYMARKET_US"
_D5, _D6, _D7 = dt.date(2026, 10, 5), dt.date(2026, 10, 6), dt.date(2026, 10, 7)
_MIB = 1 << 20


class _Src:
    def __init__(self, records: dict[tuple[str, dt.date], Any]) -> None:
        self.records = records
        self.asked: list[dt.date] = []

    def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None:
        self.asked.append(climate_day)
        return cast("NwsClimateDay | None", self.records.get((station, climate_day)))


class _CatalogRouter:
    """The production ``NwsCliFinal`` over one real tmp catalog per station."""

    def __init__(self, base: Path, records: Sequence[NwsClimateDay]) -> None:
        base.mkdir(parents=True, exist_ok=True)
        self._sources = {}
        for station in sorted({r.station for r in records}):
            catalog = open_station_catalog(base, "polymarket_us", station)
            write_records(catalog, [r for r in records if r.station == station])
            self._sources[station] = NwsCliFinal(catalog)

    def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None:
        return self._sources[station].record(station, climate_day)


def test_clipping_wrapper_implements_settlement_source_and_clips_after_2026_10_06(
    tmp_path: Path,
) -> None:
    inner = _Src(
        {("LAX", _D6): nws_record("LAX", _D6, 90), ("LAX", _D7): nws_record("LAX", _D7, 91)}
    )
    clip = ClippingSettlementSource(inner, _D6)

    assert clip.record("LAX", _D6) is inner.records[("LAX", _D6)]
    assert clip.record("LAX", _D7) is None
    assert _D7 not in inner.asked  # the clipped day never reaches the inner source
    assert list(inspect.signature(clip.record).parameters) == ["station", "climate_day"]
    # production default path: the real NwsCliFinal over a real tmp catalog
    router = _CatalogRouter(tmp_path, [nws_record("LAX", _D6, 90), nws_record("LAX", _D7, 91)])
    real = ClippingSettlementSource(router, _D6)
    record = real.record("LAX", _D6)
    assert record is not None and record.tmax_f == 90
    assert real.record("LAX", _D7) is None


def test_clipping_wrapper_clips_below_first_day_without_asking_the_inner_source() -> None:
    first, before = dt.date(2026, 10, 1), dt.date(2026, 9, 30)
    inner = _Src(
        {("LAX", before): nws_record("LAX", before, 80), ("LAX", first): nws_record("LAX", first, 81),
         ("LAX", _D6): nws_record("LAX", _D6, 90)}
    )  # fmt: skip
    clip = ClippingSettlementSource(inner, _D6, first_day=first)

    assert clip.record("LAX", before) is None  # holdout side: never reaches the inner source
    assert before not in inner.asked
    assert clip.record("LAX", first) is inner.records[("LAX", first)]
    assert clip.record("LAX", _D6) is inner.records[("LAX", _D6)]
    assert clip.record("LAX", _D7) is None


def test_last_valid_day_streams_the_csv_instead_of_loading_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.analysis import fq_loss_taxonomy_truth as truth

    folder = tmp_path / "metar-routine" / "KLAX"
    folder.mkdir(parents=True)
    (folder / "2026.csv").write_text(
        "station,valid_utc,tmpf\nKLAX,2026-10-02T07:53Z,70\nKLAX,2026-10-09T01:00Z,71\n"
    )

    def _boom(*_a: Any, **_k: Any) -> str:
        raise AssertionError("read_text loads the whole file; stream it")

    monkeypatch.setattr(Path, "read_text", _boom)

    assert truth._last_valid_day(folder) == "2026-10-09"


class _Explosive:
    station, climate_day = "LAX", _D6
    is_final, is_superseded, correction_flag, revision_seq = True, False, False, 1

    @property
    def tmax_f(self) -> int:
        raise AssertionError("Phase A read tmax_f")


def test_phase_a_projection_without_tmax_f_passes_when_tmax_f_raises(tmp_path: Path) -> None:
    expected = PhaseAProjection("LAX", _D6, True, False, False, 1)
    src = _Src({("LAX", _D6): _Explosive(), ("LAX", _D7): _Explosive()})

    assert project_phase_a(cast(NwsClimateDay, _Explosive())) == expected
    assert phase_a_truth(src, "LAX", _D6) == expected  # the single entry point: clip, then project
    assert phase_a_truth(src, "LAX", _D7) is None  # clipped before the record is even requested
    assert _D7 not in src.asked
    assert phase_a_truth(src, "MIA", _D6) is None
    assert "tmax_f" not in {f.name for f in dataclasses.fields(PhaseAProjection)}
    router = _CatalogRouter(tmp_path, [nws_record("LAX", _D6, 90)])  # production default path
    assert phase_a_truth(router, "LAX", _D6) == expected


def test_truth_unsettled_for_flagged_or_superseded_day() -> None:
    def status(**over: Any) -> str:
        return truth_status(project_phase_a(nws_record("LAX", _D6, 90, **over)))

    assert status() == "SETTLED"
    assert status(correction_flag=True) == "TRUTH_UNSETTLED"
    assert status(is_superseded=True) == "TRUTH_UNSETTLED"
    assert status(is_final=False) == "TRUTH_UNSETTLED"
    clean = project_phase_a(nws_record("LAX", _D6, 90))
    assert truth_status(clean, catalog_disagreement=True) == "TRUTH_UNSETTLED"  # S0-F catalog check
    assert truth_status(clean, catalog_disagreement=False) == "SETTLED"


def _boundary_fill(day: str) -> Any:
    return durable_fill(
        venue_order_id=f"b-{day}",
        instrument_id=f"tc-temp-laxhigh-{day}-gte80lt81f.POLYMARKET_US",
        ts_event=1_790_000_000_000_000_000,
    )


def test_s0a_count_only_runs_without_any_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("S0-A touched settlement data")

    monkeypatch.setattr(NwsCliFinal, "record", boom)
    store = tmp_path / "exec.db"
    seed_fills(store, [*fq_durable_fills(), *fq_september_fills()])

    counts = s0a_counts(store, _D5)

    assert counts == S0ACounts(
        n_fills=25, n_instruments=25, n_no_leg=0, n_open_ended=6, n_station_days=14,
        n_clusters=7, n_clusters_excluding_k1b=6, n_k1b_fills=5, n_k1b_station_days=3,
    )  # fmt: skip
    s0a_gate(counts)  # the verified P6 counts pass
    params = set(inspect.signature(s0a_counts).parameters)
    assert not params & {"catalog", "settlement", "source", "tmax"}
    assert not {f.name for f in dataclasses.fields(S0ACounts)} & {"n_wins", "pnl", "tmax"}
    # the 10-01 window boundary: 09-30 is out, 10-01 is in
    edge = tmp_path / "edge.db"
    seed_fills(edge, [_boundary_fill("2026-09-30"), _boundary_fill("2026-10-01")])
    assert s0a_counts(edge, _D5).n_fills == 1
    # a ^no-leg fill is counted, and the gate STOPs on it
    no_leg = durable_fill(
        venue_order_id="no-1", instrument_id=_LAX_YES.replace(".POLY", "^no.POLY")
    )
    with_no = tmp_path / "no.db"
    seed_fills(with_no, [*fq_durable_fills(), no_leg])
    counted = s0a_counts(with_no, _D5)
    assert (counted.n_no_leg, counted.n_fills) == (1, 26)
    with pytest.raises(S0AStop):
        s0a_gate(counted)
    # an unparseable instrument id is a STOP, never a skip
    junk = tmp_path / "junk.db"
    seed_fills(junk, [durable_fill(venue_order_id="j-1", instrument_id="garbage.POLYMARKET_US")])
    with pytest.raises(UnparseableInstrumentStop):
        s0a_counts(junk, _D5)
    writer = SqliteStateStore(store)
    try:
        writer.set(f"{FILL_KEY_PREFIX}vo-bad", b"{not json")
    finally:
        writer.close()
    with pytest.raises(FillStoreCorruption):  # require_clean: corruption is a STOP, never a skip
        s0a_counts(store, _D5)


class _EpochReader:
    def __init__(self, start: int | None, *, links: bool = False) -> None:
        self._start, self._links = start, links

    def epoch_start_ns(self) -> int | None:
        return self._start

    def order_link(self, client_order_id: str) -> OrderLinkView | None:
        if not self._links:
            return None
        return OrderLinkView(
            decision_id=f"dec-{client_order_id}", client_order_id=client_order_id,
            venue_order_id_sha256="", instrument_id=_LAX_YES, side="1", qty="1.00", px="0.15",
            time_in_force="2", intent_fingerprint="f" * 64, ts_ns=2, source="live",
        )  # fmt: skip

    def earliest_order_link_ns(self) -> None:
        return None


def _fq_log(path: Path, *, skip_take_for: int | None = None) -> Path:
    lines = ["noise line without a stamp"]
    for index, fill in enumerate(fq_durable_fills()):
        t = 10.0 * index
        if index != skip_take_for:
            lines.append(log_take(t, fill.instrument_id))
        lines.append(log_init(t + 1, fill.client_order_id, fill.instrument_id))
        trade = cast(str, fill.trade_id)
        lines.append(log_filled(t + 2, fill.client_order_id, trade, fill.instrument_id))
    for n in range(7):  # the IOC-missed Takes: no OrderInitialized follows
        lines.append(log_take(300.0 + n, f"tc-temp-laxhigh-2026-10-02-lt{60 + n}f.POLYMARKET_US"))
    path.write_text("\n".join(lines) + "\n")
    return path


def test_all_25_fills_attribute_or_stop_unclassified(tmp_path: Path) -> None:
    fills = fill_read(fq_durable_fills())
    log = _fq_log(tmp_path / "boot.log")
    root = tmp_path / "root"
    root.mkdir()

    fake = attribute_fills(fills, [log], data_root=root, epoch_reader=_EpochReader(None))
    default = attribute_fills(fills, [log], data_root=root)  # production C1Epoch, empty root

    for result in (fake, default):
        assert (result.report.n, result.report.matched, result.report.p_null_count) == (25, 25, 0)
        assert len(result.matches) == 25
        assert all(m.p_at_decision == pytest.approx(0.38) for m in result.matches)
    missing = _fq_log(tmp_path / "missing.log", skip_take_for=7)
    with pytest.raises(UnclassifiedFillsStop):
        attribute_fills(fills, [missing], data_root=root, epoch_reader=_EpochReader(None))
    with pytest.raises(UnclassifiedFillsStop):  # UNRESOLVED epoch (no order link): never bridged
        attribute_fills(fills, [log], data_root=root, epoch_reader=_EpochReader(1))
    with pytest.raises(BackfillRefused):  # POST_EPOCH: bridge_decision refuses, the plan STOPs
        attribute_fills(fills, [log], data_root=root, epoch_reader=_EpochReader(1, links=True))


def test_s0d_perturbed_vector_mismatches_and_is_classed_k1a() -> None:
    logged = {f"f{i}": 0.38 + 0.001 * i for i in range(25)}
    reproduced: dict[str, float | None] = dict(logged)

    assert s0d_compare(logged, reproduced).n_match == 25
    reproduced["f3"] = logged["f3"] + 1e-6  # the positive control
    reproduced["f4"] = logged["f4"] + 5e-10  # inside the 1e-9 tolerance
    reproduced["f5"] = None
    result = s0d_compare(logged, reproduced)

    assert result.n_match == 23
    assert set(result.mismatched_fill_ids) == {"f3", "f5"}
    assert classify_s0d_miss(
        bulletin_available=True, bulletin_reissued=False,
        cycle_selection_matches=True, delta_survives_root_cause=True,
    ) == S0DMiss.K1A  # fmt: skip


def test_unavailable_bulletin_is_untestable_and_cycle_mismatch_is_cycle_ambiguous() -> None:
    def miss(**over: bool) -> S0DMiss:
        base = {
            "bulletin_available": True, "bulletin_reissued": False,
            "cycle_selection_matches": True, "delta_survives_root_cause": True,
        }  # fmt: skip
        return classify_s0d_miss(**{**base, **over})

    assert miss(bulletin_available=False) == S0DMiss.UNTESTABLE
    assert miss(bulletin_reissued=True) == S0DMiss.UNTESTABLE
    assert miss(cycle_selection_matches=False) == S0DMiss.CYCLE_AMBIGUOUS
    assert miss(bulletin_available=False, cycle_selection_matches=False) == S0DMiss.UNTESTABLE
    assert miss(delta_survives_root_cause=False) == S0DMiss.NO_DEFECT  # not a defect, not K1a


def _write_log(path: Path, lines: Sequence[str]) -> Path:
    path.write_text("\n".join(lines) + "\n")
    return path


def test_streaming_reader_is_a_lazy_generator_or_tracemalloc_bounded_and_keeps_a_take_split_across_a_prefilter_boundary(  # noqa: E501
    tmp_path: Path,
) -> None:
    takes = [log_take(t, f"tc-temp-laxhigh-2026-10-02-lt{60 + t}f.POLYMARKET_US") for t in range(4)]
    parsed = [e for e in (parse_log_line(t) for t in takes) if e is not None]
    small = _write_log(tmp_path / "small.log", ["x" * 100, takes[0], "y" * 70, takes[1], takes[2]])

    stream = stream_take_events(small, chunk_size=64)  # every Take straddles several chunks

    assert iter(stream) is stream  # lazy: a generator, never a list
    assert list(stream) == parsed[:3] == [e for e in read_log_events([small]) if e.kind == "take"]
    assert list(stream_take_events(small)) == parsed[:3]  # production default chunk size
    # a Take that straddles exactly the 1 MiB offset, and one that starts exactly on it
    line = takes[0] + "\n"
    straddle = tmp_path / "straddle.log"
    head = "z" * (_MIB - len(line) // 2 - 1) + "\n"
    straddle.write_text(head + line + "y" * 50 + "\n")
    assert [e.instrument_id for e in stream_take_events(straddle)] == [parsed[0].instrument_id]
    on_edge = tmp_path / "on_edge.log"
    on_edge.write_text("z" * (_MIB - 1) + "\n" + takes[1] + "\n")
    assert [e.instrument_id for e in stream_take_events(on_edge)] == [parsed[1].instrument_id]
    # a single Take line far larger than the chunk, after a non-Take line larger than the chunk
    huge = takes[3] + " " + "q" * 5000
    giant = _write_log(tmp_path / "giant.log", ["w" * 5000, huge])
    assert list(stream_take_events(giant, chunk_size=64)) == [parsed[3]]
    filler = "z" * 2000
    big = tmp_path / "big.log"
    with big.open("w") as handle:
        for index in range(12_000):  # ~24 MB
            handle.write(filler + "\n")
            if index % 4000 == 0:
                handle.write(takes[0] + "\n")
    tracemalloc.start()
    try:
        count = sum(1 for _ in stream_take_events(big))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert count == 3
    assert peak < 8 * 1024 * 1024


def test_partition_union_reader_includes_refuse_lines(tmp_path: Path) -> None:
    log = _write_log(
        tmp_path / "boot.log",
        [
            log_take(1, _LAX_YES, station="LAX", rung_id="89_90"),
            log_refuse(2, _LAX_YES, station="LAX", rung_id="87_88"),
            log_refuse(3, _LAX_YES, station="LAX", rung_id="91_92"),
            log_refuse(4, _LAX_YES, station="MIA", rung_id="86_87"),
        ],
    )

    union = partition_union(iter_partition_events(log))

    day = dt.date(2026, 10, 2)
    assert union[("LAX", day)] == frozenset({"89_90", "87_88", "91_92"})
    assert union[("MIA", day)] == frozenset({"86_87"})
    assert len(read_log_events([log])) == 1  # the bridge reader keeps only the Take


def test_alt_truth_unavailable_marks_untestable_not_zero() -> None:
    absent = alt_truth_summary(None, None)
    empty = alt_truth_summary({}, {})
    flips = alt_truth_summary({"f1": True, "f2": False}, {"f1": False})

    assert (absent.k3_status, absent.k3_count, absent.k4_status, absent.k4_count) == (
        "UNTESTABLE", None, "UNTESTABLE", None,
    )  # fmt: skip
    assert (empty.k3_status, empty.k3_count, empty.k4_count) == ("TESTED", 0, 0)
    assert (flips.k3_count, flips.k4_count) == (1, 0)


def test_reproduces_audit_25_fills_2_wins_minus_2_17(tmp_path: Path) -> None:
    store = tmp_path / "exec.db"
    seed_fills(store, [*fq_durable_fills(), *fq_september_fills(), fq_out_of_scope_fill()])
    read = read_durable_fills(store).require_clean()  # L-42: the real writer, the real reader
    records = [
        *fq_settlement_records(),
        nws_record("LAX", _D7, 90),
    ]  # a 10-07 record that would win
    source = ClippingSettlementSource(_CatalogRouter(tmp_path / "catalog", records), _D6)
    now_ns = 1_800_000_000_000_000_000

    def audit(marker: str | None) -> Any:
        keep = [f for f in read.fills if marker is None or marker in f.instrument_id]
        return reproduce_audit(fill_read(keep), source, now_ns=now_ns)

    full, october, september = audit(None), audit("-2026-10-0"), audit("-2026-09-")

    assert (full.n_fills, full.n_wins, full.n_refused) == (34, 4, 1)  # the 10-07 fill is refused
    assert abs(full.net_pnl - Decimal("-2.63")) <= Decimal("0.005")
    assert (october.n_fills, october.n_wins, october.n_refused) == (25, 2, 1)
    assert abs(october.net_pnl - Decimal("-2.17")) <= Decimal("0.005")
    assert (september.n_fills, september.n_wins) == (9, 2)
    assert abs(september.net_pnl - Decimal("-0.46")) <= Decimal("0.005")
    assert set(october.wins) == {  # the upper edge of the inclusive band is a win
        ("tc-temp-miahigh-2026-10-03-gte86lt87f.POLYMARKET_US", 87),
        ("tc-temp-miahigh-2026-10-05-gte89lt90f.POLYMARKET_US", 90),
    }
    assert "clip_after" not in inspect.signature(reproduce_audit).parameters
