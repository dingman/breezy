"""AUT-6 WP5: ``PermitLapsedDetector`` (NODE_LOCAL #4; plan r15 sections 3.2 and 3.3.2).
AUT-6 WP2 adds ``AlertsUndeliverableDetector`` (NODE_LOCAL #5; sections 3.2 and 3.7.1) below.

The detector is handed an integer expiry (``read_expiry_ns``) at composition. It judges
``now_ns > expiry`` and never holds, reads or constructs the permit object that authorises orders.
"""

from __future__ import annotations

import ast
import datetime as dt
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.persistence.autonomy.pins import WATCH_TICK_STALE_S
from breezy.persistence.autonomy.plugin import Detector, DetectorKind, PluginRefused
from breezy.persistence.autonomy.veto import VetoReason
from breezy.runtime import autonomy_node_detectors
from breezy.runtime.alert_outbox import DeliveryRecordWriter, write_armed_marker
from breezy.runtime.autonomy_node_detectors import AlertsUndeliverableDetector, PermitLapsedDetector

_NS: Final = 1_000_000_000


def _ns(year: int, month: int, day: int, hour: int, minute: int = 0, second: int = 0) -> int:
    return int(dt.datetime(year, month, day, hour, minute, second, tzinfo=dt.UTC).timestamp()) * _NS


def _fixed(expiry_ns: int | None) -> Callable[[], int | None]:
    return lambda: expiry_ns


def test_permit_lapsed_vetoes_after_expiry_and_alerts_only_in_b1_window() -> None:
    expiry = _ns(2026, 10, 9, 18, 0)
    detector = PermitLapsedDetector(read_expiry_ns=_fixed(expiry))
    assert detector.id == "permit_lapsed"
    assert detector.kind is DetectorKind.NODE_LOCAL

    # at the expiry instant the permit is still valid (strictly greater than)
    at = detector.observe(expiry)
    assert (at.state, at.veto, at.page_event) == ("AGREE", None, None)
    assert detector.evaluate(expiry) is None

    # one ns later it lapses: DISAGREE, the veto, and (17:10Z-01:00Z window) one CRITICAL page
    first = detector.observe(expiry + 1)
    assert (first.state, first.veto, first.page_event) == (
        "DISAGREE",
        VetoReason.PERMIT_LAPSED,
        "permit_lapsed",
    )
    # only the transition pages: the persisting lapse vetoes without a second page
    later = detector.observe(expiry + 60 * _NS)
    assert (later.state, later.veto, later.page_event) == (
        "DISAGREE",
        VetoReason.PERMIT_LAPSED,
        None,
    )
    assert detector.evaluate(expiry + 120 * _NS) is VetoReason.PERMIT_LAPSED

    # renewal clears it, and the next lapse in the window pages again
    renewed = {"v": expiry + 3600 * _NS}
    detector = PermitLapsedDetector(read_expiry_ns=lambda: renewed["v"])
    assert detector.observe(expiry).state == "AGREE"
    assert detector.observe(renewed["v"] + 1).page_event == "permit_lapsed"
    renewed["v"] += 24 * 3600 * _NS
    assert detector.observe(expiry + 7200 * _NS).state == "AGREE"
    assert detector.observe(renewed["v"] + 1).page_event == "permit_lapsed"


@pytest.mark.parametrize(
    ("hour", "minute", "second", "pages"),
    [
        (17, 9, 59, False),  # one second before the window opens
        (17, 10, 0, True),  # inclusive start
        (23, 59, 59, True),
        (0, 0, 0, True),  # the window spans UTC midnight
        (0, 59, 59, True),
        (1, 0, 0, False),  # exclusive end
        (2, 50, 0, False),  # the daily expiry (about 02:50Z): a record, no page
        (12, 0, 0, False),
    ],
)
def test_permit_lapsed_page_window_boundaries(
    hour: int, minute: int, second: int, pages: bool
) -> None:
    now = _ns(2026, 10, 9, hour, minute, second)
    detector = PermitLapsedDetector(read_expiry_ns=_fixed(now - 1))
    observation = detector.observe(now)
    # the veto and the DISAGREE record exist at every hour; only the page depends on the window
    assert observation.state == "DISAGREE"
    assert observation.veto is VetoReason.PERMIT_LAPSED
    assert (observation.page_event == "permit_lapsed") is pages


def test_permit_none_is_agree_no_permit() -> None:
    detector = PermitLapsedDetector(read_expiry_ns=_fixed(None))
    observation = detector.observe(_ns(2026, 10, 9, 18, 0))
    assert (observation.state, observation.detail, observation.veto, observation.page_event) == (
        "AGREE",
        "no_permit",
        None,
        None,
    )
    assert detector.evaluate(_ns(2026, 10, 9, 18, 0)) is None


def test_permit_lapsed_read_error_unknown_then_vetoes_after_180s() -> None:
    assert WATCH_TICK_STALE_S == 180
    t0 = _ns(2026, 10, 9, 18, 0)
    state: dict[str, Any] = {"fail": True}

    def read() -> int | None:
        if state["fail"]:
            raise OSError("permit store unreadable")
        return t0 + 3600 * _NS

    detector = PermitLapsedDetector(read_expiry_ns=read)
    first = detector.observe(t0)
    assert (first.state, first.veto, first.page_event) == ("UNKNOWN", None, None)
    # for at most 180 s it vetoes nothing
    mid = detector.observe(t0 + 180 * _NS)
    assert (mid.state, mid.veto, mid.page_event) == ("UNKNOWN", None, None)
    # past 180 s it vetoes under its own reason; the transition pages once
    past = detector.observe(t0 + 180 * _NS + 1)
    assert (past.state, past.detail, past.veto, past.page_event) == (
        "UNKNOWN",
        "persistent",
        VetoReason.PERMIT_LAPSED,
        "aut6_detector_unknown_persistent",
    )
    again = detector.observe(t0 + 240 * _NS)
    assert (again.veto, again.page_event) == (VetoReason.PERMIT_LAPSED, None)
    # the next good observation clears it and restarts the timer
    state["fail"] = False
    good = detector.observe(t0 + 300 * _NS)
    assert (good.state, good.veto, good.page_event) == ("AGREE", None, None)
    state["fail"] = True
    assert detector.observe(t0 + 400 * _NS).veto is None
    assert detector.observe(t0 + 400 * _NS + 181 * _NS).veto is VetoReason.PERMIT_LAPSED


class _PermitObject:
    """Stands in for the order-authorising permit: any attribute access is a failure."""

    touched: list[str] = []  # noqa: RUF012

    def __getattribute__(self, name: str) -> Any:
        _PermitObject.touched.append(name)
        raise AssertionError(f"the permit object was touched: {name}")


_BAD_VALUES: Final[dict[str, Callable[[], Any]]] = {
    "permit_object": _PermitObject,
    "bool": lambda: True,
    "negative": lambda: -5,
    "float": lambda: 1.5,
    "str": lambda: "1",
    "bytes": lambda: b"1",
}


@pytest.mark.parametrize("kind", sorted(_BAD_VALUES))
def test_permit_lapsed_reads_value_never_the_permit_object_authority(kind: str) -> None:
    _PermitObject.touched.clear()
    bad = _BAD_VALUES[kind]()
    detector = PermitLapsedDetector(read_expiry_ns=lambda: bad)
    observation = detector.observe(_ns(2026, 10, 9, 18, 0))
    # anything but a plain non-negative int is an unreadable observation: UNKNOWN, fail closed
    assert observation.state == "UNKNOWN"
    assert _PermitObject.touched == []
    # the module itself imports nothing that confers or constructs order authority
    tree = ast.parse(Path(autonomy_node_detectors.__file__).read_text(encoding="utf-8"))
    imported = {
        (node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {a.name for node in ast.walk(tree) if isinstance(node, ast.Import) for a in node.names}
    assert not {m for m in imported if "order_enablement" in m or "permit" in m}
    assert not {m for m in imported if m.startswith("breezy.adapters")}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    assert not names & {
        "OrderSubmissionPermit",
        "LiveTradingPermit",
        "issue_live_trading_permit",
        "expires_at_ns",
    }


def test_permit_lapsed_detector_satisfies_the_c6_detector_protocol() -> None:
    detector: Detector = PermitLapsedDetector(read_expiry_ns=_fixed(None))
    assert detector.id == "permit_lapsed" and detector.kind is DetectorKind.NODE_LOCAL


def test_fq_plugin_detectors_are_provided_by_composition_and_refuse_by_default() -> None:
    from breezy.strategy.forecast_quantile_ladder.plugin import build_fq_node_plugin

    class _Adapter:
        def decision_record(self, decision: Any, ctx: Any) -> Any:
            return None

        def order_tags(self, decision_id: str) -> Any:
            return ()

    bare = build_fq_node_plugin(_Adapter())  # type: ignore[arg-type]
    with pytest.raises(PluginRefused):
        _ = bare.detectors

    permit = PermitLapsedDetector(read_expiry_ns=_fixed(None))
    wired = build_fq_node_plugin(_Adapter(), node_detectors=(permit,))  # type: ignore[arg-type]
    assert wired.detectors == (permit,)

    class _Rogue:
        id = "rogue_detector"
        kind = DetectorKind.NODE_LOCAL

        def evaluate(self, *args: Any, **kwargs: Any) -> None:
            return None

    with pytest.raises(PluginRefused, match="rogue_detector"):
        build_fq_node_plugin(_Adapter(), node_detectors=(_Rogue(),))  # type: ignore[arg-type]

    class _Mislabelled(_Rogue):
        id = "permit_lapsed"
        kind = DetectorKind.VERDICT

    with pytest.raises(PluginRefused, match="NODE_LOCAL"):
        build_fq_node_plugin(_Adapter(), node_detectors=(_Mislabelled(),))  # type: ignore[arg-type]
    with pytest.raises(PluginRefused, match="duplicate"):
        build_fq_node_plugin(_Adapter(), node_detectors=(permit, permit))  # type: ignore[arg-type]


def test_persistent_unknown_pages_once_recovers_then_repages_once() -> None:
    t0 = _ns(2026, 10, 9, 18, 0)
    state: dict[str, bool] = {"fail": True}

    def read() -> int | None:
        if state["fail"]:
            raise OSError("unreadable")
        return t0 + 86_400 * _NS

    detector = PermitLapsedDetector(read_expiry_ns=read)
    detector.observe(t0)
    first = detector.observe(t0 + 181 * _NS)
    assert (first.veto, first.page_event) == (
        VetoReason.PERMIT_LAPSED,
        "aut6_detector_unknown_persistent",
    )
    assert detector.observe(t0 + 300 * _NS).page_event is None
    state["fail"] = False
    assert detector.observe(t0 + 400 * _NS).state == "AGREE"
    state["fail"] = True
    assert detector.observe(t0 + 500 * _NS).page_event is None  # timer restarts, no veto yet
    second = detector.observe(t0 + 500 * _NS + 181 * _NS)
    assert (second.veto, second.page_event) == (
        VetoReason.PERMIT_LAPSED,
        "aut6_detector_unknown_persistent",
    )
    assert detector.observe(t0 + 900 * _NS).page_event is None


# ---------------------------------------------------------------------------------------------
# AUT-6 WP2: AlertsUndeliverableDetector (NODE_LOCAL #5)
# ---------------------------------------------------------------------------------------------

_HOUR: Final = 3600 * _NS
_NOW: Final = _ns(2026, 10, 9, 18, 0)


def _record(
    root: Path,
    at_ns: int,
    *,
    delivered: bool = True,
    kind: str = "canary",
    severity: str = "INFO",
    drill: bool = False,
    writer: str = "canary",
) -> None:
    DeliveryRecordWriter(root).write(
        event="autonomy_canary",
        ts_ns=at_ns,
        writer=writer,
        delivered=delivered,
        status_class="2xx" if delivered else "5xx",
        severity=severity,
        attempt_kind=kind,
        drill=drill,
        site="global",
        outbox_entry="",
    )


def _arm(root: Path, at_ns: int = _NOW - 40 * _HOUR) -> None:
    write_armed_marker(root, record="x_canary_d.json", ts_ns=at_ns)


def test_alerts_undeliverable_veto(tmp_path: Path) -> None:
    _arm(tmp_path)
    detector = AlertsUndeliverableDetector(alerts_root=tmp_path)
    assert detector.id == "alerts_undeliverable"
    assert detector.kind is DetectorKind.NODE_LOCAL
    _record(tmp_path, _NOW - 27 * _HOUR)
    stale = detector.observe(_NOW)
    assert (stale.state, stale.veto, stale.page_event) == (
        "DISAGREE",
        VetoReason.ALERTS_UNDELIVERABLE,
        "alerts_undeliverable",
    )
    assert detector.evaluate(_NOW) is VetoReason.ALERTS_UNDELIVERABLE
    fresh = AlertsUndeliverableDetector(alerts_root=tmp_path)
    _record(tmp_path, _NOW - 2 * _HOUR)
    assert fresh.observe(_NOW).veto is None
    assert fresh.evaluate(_NOW) is None


def test_alerts_undeliverable_reads_two_days(tmp_path: Path) -> None:
    _arm(tmp_path)
    # yesterday's directory is read
    _record(tmp_path, _ns(2026, 10, 8, 19, 0))
    assert AlertsUndeliverableDetector(alerts_root=tmp_path).evaluate(_NOW) is None
    # two days back is not
    other = tmp_path / "other"
    other.mkdir()
    _arm(other)
    _record(other, _ns(2026, 10, 7, 23, 0))
    assert AlertsUndeliverableDetector(alerts_root=other).evaluate(_NOW) is (
        VetoReason.ALERTS_UNDELIVERABLE
    )


def test_alerts_undeliverable_counts_canary_or_critical_only(tmp_path: Path) -> None:
    _arm(tmp_path)
    _record(tmp_path, _NOW - 3 * _HOUR, kind="alert", severity="INFO")
    _record(tmp_path, _NOW - 2 * _HOUR, kind="canary", delivered=False)
    _record(tmp_path, _NOW - 1 * _HOUR, kind="retry", severity="WARN")
    stale_only = _NOW - 30 * _HOUR
    _record(tmp_path, stale_only, kind="canary")
    assert AlertsUndeliverableDetector(alerts_root=tmp_path).evaluate(_NOW) is (
        VetoReason.ALERTS_UNDELIVERABLE
    )
    _record(tmp_path, _NOW - 4 * _HOUR, kind="alert", severity="CRITICAL")
    assert AlertsUndeliverableDetector(alerts_root=tmp_path).evaluate(_NOW) is None


def test_alerts_undeliverable_ignores_warn_and_info_records(tmp_path: Path) -> None:
    _arm(tmp_path)
    for kind in ("alert", "retry", "drain"):
        _record(tmp_path, _NOW - 1 * _HOUR, kind=kind, severity="WARN")
        _record(tmp_path, _NOW - 1 * _HOUR, kind=kind, severity="INFO")
    assert AlertsUndeliverableDetector(alerts_root=tmp_path).evaluate(_NOW) is (
        VetoReason.ALERTS_UNDELIVERABLE
    )


def test_alerts_undeliverable_counts_delivered_drill_critical(tmp_path: Path) -> None:
    _arm(tmp_path)
    _record(tmp_path, _NOW - 1 * _HOUR, kind="alert", severity="CRITICAL", drill=True)
    assert AlertsUndeliverableDetector(alerts_root=tmp_path).evaluate(_NOW) is None
    other = tmp_path / "o"
    other.mkdir()
    _arm(other)
    _record(other, _NOW - 1 * _HOUR, kind="canary", drill=True)
    assert AlertsUndeliverableDetector(alerts_root=other).evaluate(_NOW) is None


def test_one_failed_canary_does_not_veto_next_window(tmp_path: Path) -> None:
    _arm(tmp_path)
    _record(tmp_path, _ns(2026, 10, 9, 15, 45), delivered=True)
    _record(tmp_path, _ns(2026, 10, 9, 16, 45), delivered=False)
    for hour in (17, 20, 23):
        assert (
            AlertsUndeliverableDetector(alerts_root=tmp_path).evaluate(_ns(2026, 10, 9, hour, 10))
            is None
        )


def test_veto_arithmetic_worst_case_lands_1845z_inside_window(tmp_path: Path) -> None:
    _arm(tmp_path)
    _record(tmp_path, _ns(2026, 10, 8, 16, 45))  # D-1 16:45 is the newest delivered record
    window_start = _ns(2026, 10, 9, 17, 10)
    just_before = _ns(2026, 10, 9, 18, 44, 59)
    at_limit = _ns(2026, 10, 9, 18, 45)
    assert AlertsUndeliverableDetector(alerts_root=tmp_path).evaluate(window_start) is None
    assert AlertsUndeliverableDetector(alerts_root=tmp_path).evaluate(just_before) is None
    assert AlertsUndeliverableDetector(alerts_root=tmp_path).evaluate(at_limit) is (
        VetoReason.ALERTS_UNDELIVERABLE
    )
    assert window_start < at_limit < _ns(2026, 10, 10, 1, 0)


def test_alerts_undeliverable_unarmed_before_first_delivery(tmp_path: Path) -> None:
    detector = AlertsUndeliverableDetector(alerts_root=tmp_path)
    assert (detector.observe(_NOW).state, detector.observe(_NOW).veto) == ("AGREE", None)
    _record(tmp_path, _NOW - 40 * _HOUR)  # a stale record but no marker: still unarmed
    unarmed = AlertsUndeliverableDetector(alerts_root=tmp_path).observe(_NOW)
    assert (unarmed.state, unarmed.detail, unarmed.veto, unarmed.page_event) == (
        "AGREE",
        "unarmed",
        None,
        None,
    )


def test_armed_marker_survives_three_day_gap_and_vetoes(tmp_path: Path) -> None:
    _arm(tmp_path, _NOW - 100 * _HOUR)
    assert not list(tmp_path.glob("????-??-??"))  # no dated directory at all
    gap = AlertsUndeliverableDetector(alerts_root=tmp_path).observe(_NOW)
    assert (gap.state, gap.veto) == ("DISAGREE", VetoReason.ALERTS_UNDELIVERABLE)


def test_armed_marker_enoent_unarmed_other_error_unknown(tmp_path: Path) -> None:
    detector = AlertsUndeliverableDetector(alerts_root=tmp_path)
    assert detector.observe(_NOW).detail == "unarmed"
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "armed.json").mkdir()  # not a regular file: a read error, not ENOENT
    bad = AlertsUndeliverableDetector(alerts_root=broken)
    first = bad.observe(_NOW)
    assert (first.state, first.veto, first.page_event) == ("UNKNOWN", None, None)
    assert bad.observe(_NOW + WATCH_TICK_STALE_S * _NS).veto is None
    persistent = bad.observe(_NOW + WATCH_TICK_STALE_S * _NS + 1)
    assert (persistent.state, persistent.veto, persistent.page_event) == (
        "UNKNOWN",
        VetoReason.ALERTS_UNDELIVERABLE,
        "aut6_detector_unknown_persistent",
    )
    (broken / "armed.json").rmdir()
    (broken / "armed.json").write_text("not json")  # garbage content is also not ENOENT
    garbage = AlertsUndeliverableDetector(alerts_root=broken).observe(_NOW)
    assert garbage.state == "UNKNOWN"


def test_node_local_unknown_vetoes_after_watch_tick_stale(tmp_path: Path) -> None:
    (tmp_path / "armed.json").write_text("{")
    detector = AlertsUndeliverableDetector(alerts_root=tmp_path)
    assert detector.observe(_NOW).veto is None
    assert detector.observe(_NOW + 181 * _NS).veto is VetoReason.ALERTS_UNDELIVERABLE


def test_alerts_undeliverable_clears_on_next_2xx(tmp_path: Path) -> None:
    _arm(tmp_path)
    detector = AlertsUndeliverableDetector(alerts_root=tmp_path)
    assert detector.observe(_NOW).veto is VetoReason.ALERTS_UNDELIVERABLE
    assert detector.observe(_NOW + 60 * _NS).page_event is None  # one page per transition
    _record(tmp_path, _NOW + 100 * _NS, kind="canary")
    # the listing is cached for 600 s, so the new record is not seen yet
    assert detector.observe(_NOW + 300 * _NS).veto is VetoReason.ALERTS_UNDELIVERABLE
    cleared = detector.observe(_NOW + 601 * _NS)
    assert (cleared.state, cleared.veto) == ("AGREE", None)


def test_alerts_undeliverable_ignores_non_record_files(tmp_path: Path) -> None:
    _arm(tmp_path)
    day = tmp_path / "2026-10-09"
    day.mkdir()
    (day / f"{_NOW - _HOUR}_canary_d.json.partial").write_text("{}")
    (day / f"heartbeat_{_NOW}.json").write_text('{"delivered": true, "attempt_kind": "canary"}')
    (day / "notes.txt").write_text("x")
    (day / f"{_NOW - _HOUR}_canary_d.json").symlink_to(tmp_path / "armed.json")
    assert AlertsUndeliverableDetector(alerts_root=tmp_path).evaluate(_NOW) is (
        VetoReason.ALERTS_UNDELIVERABLE
    )


def test_detector_never_raises(tmp_path: Path) -> None:
    """L-16: garbage records, a missing root and a file for a directory are observations."""
    _arm(tmp_path)
    day = tmp_path / "2026-10-09"
    day.mkdir()
    (day / f"{_NOW - _HOUR}_canary_d.json").write_text("not json")
    (day / f"{_NOW - _HOUR + 1}_canary_d.json").write_text("[1, 2]")
    (day / f"{_NOW - _HOUR + 2}_canary_d.json").write_bytes(b"{" + b" " * 100_000 + b"}")
    (tmp_path / "2026-10-08").write_text("a file, not a directory")
    detector = AlertsUndeliverableDetector(alerts_root=tmp_path)
    observation = detector.observe(_NOW)
    assert observation.veto is VetoReason.ALERTS_UNDELIVERABLE
    missing = AlertsUndeliverableDetector(alerts_root=tmp_path / "nope")
    assert missing.observe(_NOW).state == "AGREE"
    file_root = tmp_path / "afile"
    file_root.write_text("x")
    assert AlertsUndeliverableDetector(alerts_root=file_root).observe(_NOW).state in {
        "AGREE",
        "UNKNOWN",
    }


def test_alerts_undeliverable_detector_satisfies_the_c6_detector_protocol() -> None:
    detector: Detector = AlertsUndeliverableDetector(alerts_root=Path("/nonexistent"))
    assert detector.id == "alerts_undeliverable" and detector.kind is DetectorKind.NODE_LOCAL
