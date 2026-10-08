"""AUT-6 WP5: ``PermitLapsedDetector`` (NODE_LOCAL #4; plan r15 sections 3.2 and 3.3.2).

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
from breezy.runtime.autonomy_node_detectors import PermitLapsedDetector

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
    with pytest.raises(PluginRefused, match="duplicate"):
        build_fq_node_plugin(_Adapter(), node_detectors=(permit, permit))  # type: ignore[arg-type]
