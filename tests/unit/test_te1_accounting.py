"""TE-1 WP-B: the per-fill accounting P&L (``fill_pnl`` / ``family_pnl``), schema v5 and the alerts.

Two layers. The pure layer drives ``breezy.analysis.labeling.accounting`` with small synthetic
fills, scored trials and label rows. The world layer runs ``portfolio_roi_report._run`` over the
REAL 34-fill ledger of 2026-10-11 (``tests/support/te1_fixtures.py``, real latch, fill and
scored-trial writers) with every host seam injected (L-57), and asserts the corrected audit:
34 fills / 4 wins / -2.63, FQ 25 / -2.17 (five of them post-terminal), crh -0.46, fees 0.27.

Tests labelled "regression pin" or "positive control" pass before any change and carry a named
one-line mutation instead of a RED run.
"""

from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import json
import re
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis.labeling import accounting as acct
from breezy.analysis.labeling.completeness import is_final_row
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.analysis.labeling.legacy_crh_scorer import LEGACY_SCORER_ID
from breezy.persistence.autonomy.label_schema import ExcludedReason, LabelRole, PSource
from breezy.persistence.autonomy.label_store import (
    RunMarker,
    RunOutcome,
    read_labels,
    write_labels,
    write_marker,
)
from breezy.settlement.trial_scorer import ScoredTrial
from tests.support.aut2_fixtures import (
    durable_fill,
    make_label_row,
    portfolio_roi_module,
    seed_fills,
)
from tests.support.te1_accounting_guard import offending_lines, scan_file
from tests.support.te1_fixtures import LEGACY_COIDS, World, day_start_ns, slug
from tests.support.te1_report_fixtures import (
    label_world,
    post_terminal_label_keys,
    run_report,
    settlements_reader,
)

_prr = portfolio_roi_module()
_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOUR_NS = 3_600_000_000_000
_DEADLINE = 1_790_000_000_000_000_000
_FQ = "pm_us_crh_fq_v1"
_MIA_1003 = "tc-temp-miahigh-2026-10-03-gte86lt87f.POLYMARKET_US"
_AGREE_READER: Callable[[str, dt.date], int | None] = lambda station, day: 87


# ---------------------------------------------------------------------------------------------
# synthetic builders
# ---------------------------------------------------------------------------------------------


def _fill(
    coid: str,
    *,
    instrument: str = _MIA_1003,
    cost: str = "0.12",
    fee: str = "0.01",
    side: str = "BUY",
    reconciled: bool = True,
    ts: int = 1_789_000_000_000_000_000,
) -> Any:
    return durable_fill(
        venue_order_id=f"vo-{coid}",
        client_order_id=coid,
        instrument_id=instrument,
        order_side=side,
        cost=Decimal(cost),
        fee=Decimal(fee),
        fee_reconciled=reconciled,
        ts_event=ts,
        trade_id=f"T-{coid}",
    )


def _af(fill: Any, trial_id: str | None = None) -> Any:
    return _prr.AttributedFill(fill=fill, trial_id=trial_id)


def _buckets(*, scored: Any = (), residual: Any = (), unreconciled: Any = ()) -> Any:
    fills = [*scored, *residual, *unreconciled]
    scored_ids = frozenset(a.trial_id for a in scored)
    residual_ids = frozenset(a.trial_id for a in residual)
    return _prr.bucket_ledger_fills(
        fills, scored_trial_ids=scored_ids, residual_trial_ids=residual_ids
    )


def _scored(trial_id: str, fill: Any, *, tmax: int = 87, held: bool = True) -> ScoredTrial:
    cost, fee = fill.cumulative_cost, fill.cumulative_fee
    return ScoredTrial(
        trial_id=trial_id,
        station="MIA",
        climate_day="2026-10-03",
        instrument_id=fill.instrument_id,
        settlement_tmax_f=tmax,
        held=held,
        pnl=(Decimal(1) if held else Decimal(0)) - cost - fee,
        revision_seq=1,
        raw_sha256="c" * 64,
        scored_at_ns=1,
        score_seq=1,
        settlement_basis="nws_final",
        excluded_reason=None,
        slippage=Decimal(0),
        entry_ask=cost,
        fill_px=cost,
        fee=fee,
    )


@dataclasses.dataclass(frozen=True)
class _Residual:
    realised_pnl: Decimal
    payout: Decimal
    settlement_tmax_f: int | None


def _row(coid: str, **over: Any) -> Any:
    """A pre-epoch FQ accounting row: UNATTRIBUTED, inadmissible, settled, with a net."""
    base: dict[str, Any] = {
        "client_order_id": coid,
        "family_id": _FQ,
        "admissible": False,
        "excluded_reason": ExcludedReason.UNATTRIBUTED,
        "p_source": PSource.NONE,
        "decision_id": None,
        "settled_outcome": True,
        "settlement_tmax_f": Decimal(87),
        "realized_pnl": Decimal("0.87"),
        "instrument_id": _MIA_1003,
        "station": "MIA",
        "climate_day": "2026-10-03",
    }
    base.update(over)
    return make_label_row(**base)


def _build(
    buckets: Any,
    *,
    scored: Any = None,
    residual: Any = None,
    accounting: Any = (),
    gate: str | None = None,
    reader: Callable[[str, dt.date], int | None] | None = None,
    now: int = _DEADLINE + _HOUR_NS,
    manifests: Any = (),
) -> tuple[acct.FillPnlRow, ...]:
    return acct.build_fill_pnl(
        buckets,
        scored=scored or {},
        residual=residual or {},
        accounting=accounting,
        gate_status=gate,
        cli_check=reader if reader is not None else (lambda station, day: None),
        now_ns=now,
        deadline_ns=lambda fill: _DEADLINE,
        family_of_trial=lambda trial_id, day: "pm_us_crh_cont",
        manifests=manifests,
    )


# ---------------------------------------------------------------------------------------------
# selector (R1)
# ---------------------------------------------------------------------------------------------

_LEGACY_IDS = frozenset({LEGACY_SCORER_ID})


def _ids(rows: Any) -> list[str]:
    return [r.client_order_id for r in rows]


def test_accounting_rows_selects_entry_nonlegacy_final_unattributed_or_none() -> None:
    rows = [
        _row("admissible", admissible=True, excluded_reason=None, p_source=PSource.C1_DECISION),
        _row("unattributed"),
        _row("venue-fallback", excluded_reason=None, settled_outcome=True),
        _row("exit-role", role=LabelRole.EXIT),
        _row("legacy", scorer_id=LEGACY_SCORER_ID),
    ]

    selected = acct.accounting_rows(rows, legacy_scorer_ids=_LEGACY_IDS)

    assert _ids(selected) == ["admissible", "unattributed", "venue-fallback"]


def test_accounting_predicate_equals_is_final_row_on_selected_set() -> None:
    """On every entry, non-legacy row whose reason is UNATTRIBUTED or none, the static predicate IS
    ``is_final_row``; and nothing it selects is non-final."""
    grid = []
    for n, (admissible, reason, settled) in enumerate(
        (a, r, s)
        for a in (True, False)
        for r in (None, ExcludedReason.UNATTRIBUTED)
        for s in (True, False, None)
    ):
        grid.append(
            _row(
                f"g{n}",
                admissible=admissible,
                excluded_reason=reason,
                settled_outcome=settled,
                realized_pnl=Decimal("0.1") if settled else None,
            )
        )

    selected = {
        r.client_order_id for r in acct.accounting_rows(grid, legacy_scorer_ids=_LEGACY_IDS)
    }
    final = {r.client_order_id for r in grid if is_final_row(r, now_ns=1, deadline_ns=1)}

    assert final, "the grid must contain final rows"
    assert selected == final


@pytest.mark.parametrize(
    "reason",
    [
        ExcludedReason.DUPLICATE_FILL,
        ExcludedReason.QTY_NOT_ONE,
        ExcludedReason.CANARY,
        ExcludedReason.DRILL,
        ExcludedReason.VOIDED_PAIR,
        ExcludedReason.SLIPPAGE_DEFECT,
    ],
)
def test_accounting_rows_excludes_each_final_non_accounting_reason(reason: ExcludedReason) -> None:
    """Positive control: a final row whose reason is not UNATTRIBUTED never books P&L."""
    row = _row("x", excluded_reason=reason, settled_outcome=True)
    assert is_final_row(row, now_ns=1, deadline_ns=1)

    assert acct.accounting_rows([row], legacy_scorer_ids=_LEGACY_IDS) == ()


def test_accounting_rows_excludes_legacy_scorer_rows() -> None:
    """Positive control: a LEGACY scorer row is the same trial the scored store already pays."""
    rows = [_row("legacy", scorer_id=LEGACY_SCORER_ID, excluded_reason=None, admissible=True)]

    assert acct.accounting_rows(rows, legacy_scorer_ids=_LEGACY_IDS) == ()


@pytest.mark.parametrize(
    "over",
    [
        {"excluded_reason": ExcludedReason.WINDOW_INCOMPLETE, "settled_outcome": None},
        {"excluded_reason": ExcludedReason.FEE_UNRECONCILED, "settled_outcome": None},
        {"excluded_reason": None, "settled_outcome": None},
    ],
)
def test_accounting_rows_excludes_window_incomplete_and_unsettled_none_reason(
    over: dict[str, Any],
) -> None:
    """Positive control: non-final rows never book."""
    row = _row("x", realized_pnl=None, **over)

    assert acct.accounting_rows([row], legacy_scorer_ids=_LEGACY_IDS) == ()


# ---------------------------------------------------------------------------------------------
# guard (merge 5): only the report may reference the accounting module
# ---------------------------------------------------------------------------------------------

_ALLOWED = {
    Path("scripts/analysis/portfolio_roi_report.py"),
    Path("src/breezy/analysis/labeling/accounting.py"),
}


def test_only_the_report_references_the_accounting_module() -> None:
    offenders = {}
    for root in (_REPO_ROOT / "src", _REPO_ROOT / "scripts"):
        for path in sorted(root.rglob("*.py")):
            if path.relative_to(_REPO_ROOT) in _ALLOWED:
                continue
            lines = scan_file(path, _REPO_ROOT)
            if lines:
                offenders[str(path.relative_to(_REPO_ROOT))] = lines

    assert offenders == {}
    assert scan_file(_REPO_ROOT / "scripts/analysis/portfolio_roi_report.py", _REPO_ROOT)


def test_accounting_guard_rejects_planted_attribute_access() -> None:
    planted = "import breezy\n\nTOTAL = breezy.analysis.labeling.accounting.build_fill_pnl\n"

    assert offending_lines(planted, module="breezy.analysis.labeling.verdicts") == [3]


def test_accounting_guard_rejects_from_labeling_import_accounting() -> None:
    planted = "from breezy.analysis.labeling import accounting\n"

    assert offending_lines(planted, module="breezy.analysis.labeling.verdicts") == [1]
    assert offending_lines("from . import accounting\n", module="breezy.analysis.labeling.x") == [1]
    assert offending_lines(
        "from .accounting import Disclosures\n", module="breezy.analysis.labeling.x"
    ) == [1]
    assert offending_lines("import breezy.analysis.labeling.accounting as a\n", module="m") == [1]
    assert offending_lines(
        "from breezy.analysis import labeling\nlabeling.accounting.family_pnl\n", module="m"
    ) == [2]


def test_accounting_guard_ignores_nautilus_trader_accounting() -> None:
    """Positive control: the bare name ``accounting`` is not the module."""
    clean = (
        "from nautilus_trader import accounting\n"
        "import nautilus_trader.accounting.accounts as acc\n"
        "from nautilus_trader.accounting.factory import AccountFactory\n"
        "x = accounting.margin\n"
    )

    assert offending_lines(clean, module="breezy.runtime.node") == []


# ---------------------------------------------------------------------------------------------
# fill_pnl assembly (pure)
# ---------------------------------------------------------------------------------------------


def test_fill_pnl_consumes_bucket_ledger_fills_one_row_per_fill() -> None:
    legacy = _fill("c-legacy")
    residual = _fill("c-res", reconciled=False)
    c2 = _fill("c-c2")
    buckets = _buckets(
        scored=[_af(legacy, "t-legacy")],
        residual=[_af(residual, "t-res")],
        unreconciled=[_af(c2)],
    )

    rows = _build(
        buckets,
        scored={"t-legacy": _scored("t-legacy", legacy)},
        residual={"t-res": _Residual(Decimal("0.30"), Decimal(1), 87)},
        accounting=[_row("c-c2")],
    )

    assert sorted((r.client_order_id, r.source) for r in rows) == [
        ("c-c2", acct.PnlSource.C2),
        ("c-legacy", acct.PnlSource.LEGACY),
        ("c-res", acct.PnlSource.RESIDUAL),
    ]
    assert len({r.fill_key for r in rows}) == 3


def test_legacy_and_residual_sums_equal_existing_totals() -> None:
    legacy = _fill("c-legacy")
    residual = _fill("c-res", reconciled=False)
    buckets = _buckets(scored=[_af(legacy, "t-l")], residual=[_af(residual, "t-r")])
    rows = _build(
        buckets,
        scored={"t-l": _scored("t-l", legacy)},
        residual={"t-r": _Residual(Decimal("0.30"), Decimal(1), 87)},
    )
    legacy_net = Decimal(1) - Decimal("0.12") - Decimal("0.01")

    assert [r.net for r in rows if r.source is acct.PnlSource.LEGACY] == [legacy_net]
    acct.assert_source_totals(rows, legacy_expected=legacy_net, residual_expected=Decimal("0.30"))


def test_legacy_sum_mismatch_raises() -> None:
    """Positive control for the test above: a wrong report total is refused, never absorbed."""
    legacy = _fill("c-legacy")
    rows = _build(_buckets(scored=[_af(legacy, "t-l")]), scored={"t-l": _scored("t-l", legacy)})

    with pytest.raises(acct.SourceTotalMismatch):
        acct.assert_source_totals(
            rows, legacy_expected=Decimal("9.99"), residual_expected=Decimal(0)
        )
    with pytest.raises(acct.SourceTotalMismatch):
        acct.assert_source_totals(
            rows, legacy_expected=rows[0].net or Decimal(0), residual_expected=Decimal(1)
        )


def test_legacy_check_uses_scored_bucket_subset_when_store_has_extra_trials() -> None:
    """Merge 8, a branch test only: S0-5 recorded store total == SCORED sum, so the whole-store
    form is the runtime default; a store with a trial that has no ledger fill needs the subset."""
    store_total, bucket_total = Decimal("-0.24"), Decimal("-0.54")

    assert acct.LEGACY_CHECK_WHOLE_STORE is True
    assert (
        acct.legacy_expected_total(store_total=store_total, scored_bucket_total=bucket_total)
        == store_total
    )
    assert (
        acct.legacy_expected_total(
            store_total=store_total, scored_bucket_total=bucket_total, whole_store=False
        )
        == bucket_total
    )


def test_legacy_fill_never_counted_twice_with_its_label_row() -> None:
    legacy = _fill("c-legacy")
    label_rows = [
        _row("c-legacy", scorer_id=LEGACY_SCORER_ID, excluded_reason=None, admissible=True)
    ]
    booked = acct.accounting_rows(label_rows, legacy_scorer_ids=_LEGACY_IDS)

    rows = _build(
        _buckets(scored=[_af(legacy, "t-l")]),
        scored={"t-l": _scored("t-l", legacy)},
        accounting=booked,
    )

    assert [(r.source, r.net) for r in rows] == [(acct.PnlSource.LEGACY, Decimal("0.87"))]


def test_family_pnl_sums_to_accounting_total_pure() -> None:
    fills = [_fill(f"c{n}") for n in range(3)]
    buckets = _buckets(unreconciled=[_af(f) for f in fills])
    rows = _build(
        buckets,
        accounting=[
            _row("c0", realized_pnl=Decimal("0.87")),
            _row("c1", realized_pnl=Decimal("-0.13"), settled_outcome=False, family_id="other"),
            _row("c2", realized_pnl=Decimal("-0.13"), settled_outcome=False),
        ],
    )

    families = acct.family_pnl(rows)

    assert {f.family_id: f.net for f in families} == {
        _FQ: Decimal("0.74"),
        "other": Decimal("-0.13"),
    }
    assert sum((f.net for f in families), Decimal(0)) == sum(
        (r.net or Decimal(0) for r in rows), Decimal(0)
    )
    assert {f.family_id: f.n_wins for f in families} == {_FQ: 1, "other": 0}


# ---------------------------------------------------------------------------------------------
# R9 statuses, R10 settlement check, R6 status (pure)
# ---------------------------------------------------------------------------------------------


def _case_exit() -> tuple[Any, dict[str, Any]]:
    return _buckets(unreconciled=[_af(_fill("x", side="SELL"))]), {}


def _case_settled() -> tuple[Any, dict[str, Any]]:
    fill = _fill("x")
    return _buckets(scored=[_af(fill, "t")]), {"scored": {"t": _scored("t", fill)}}


def _case_residual_pending() -> tuple[Any, dict[str, Any]]:
    return _buckets(residual=[_af(_fill("x"), "t")]), {}


def _case_unsettled() -> tuple[Any, dict[str, Any]]:
    return _buckets(unreconciled=[_af(_fill("x"))]), {"accounting": [_row("x", realized_pnl=None)]}


def _case_labels_gated() -> tuple[Any, dict[str, Any]]:
    return _buckets(unreconciled=[_af(_fill("x"))]), {"gate": "GATED_IDENTITY"}


def _case_open() -> tuple[Any, dict[str, Any]]:
    return _buckets(unreconciled=[_af(_fill("x"))]), {"now": _DEADLINE + 24 * _HOUR_NS - 1}


def _case_unpriced() -> tuple[Any, dict[str, Any]]:
    return _buckets(unreconciled=[_af(_fill("x"))]), {"now": _DEADLINE + 24 * _HOUR_NS}


_STATUS_CASES = [
    (acct.FillStatus.EXIT, _case_exit),
    (acct.FillStatus.SETTLED_NWS_IMPLIED, _case_settled),
    (acct.FillStatus.RESIDUAL_PENDING, _case_residual_pending),
    (acct.FillStatus.UNSETTLED, _case_unsettled),
    (acct.FillStatus.LABELS_GATED, _case_labels_gated),
    (acct.FillStatus.OPEN, _case_open),
    (acct.FillStatus.UNPRICED, _case_unpriced),
]


@pytest.mark.parametrize(
    ("expected", "case"), _STATUS_CASES, ids=[c[0].value for c in _STATUS_CASES]
)
def test_each_status_trigger(expected: acct.FillStatus, case: Callable[[], Any]) -> None:
    buckets, kwargs = case()

    rows = _build(buckets, **kwargs)

    assert [r.status for r in rows] == [expected]


@pytest.mark.parametrize(
    "case", [c[1] for c in _STATUS_CASES if c[0] is not acct.FillStatus.SETTLED_NWS_IMPLIED]
)
def test_win_payout_null_for_non_settled_rows(case: Callable[[], Any]) -> None:
    buckets, kwargs = case()

    rows = _build(buckets, **kwargs)

    assert len(rows) == 1
    assert (rows[0].win, rows[0].payout, rows[0].cli_final_check) == (
        None,
        None,
        acct.CliCheck.UNAVAILABLE,
    )


def test_settled_row_carries_win_and_payout() -> None:
    """Positive control for the test above."""
    buckets, kwargs = _case_settled()

    rows = _build(buckets, **kwargs)

    assert [(r.win, r.payout) for r in rows] == [(True, Decimal(1))]


def test_null_pnl_final_row_unsettled_alerted_not_zero_pure() -> None:
    rows = _build(
        _buckets(unreconciled=[_af(_fill("x"))]), accounting=[_row("x", realized_pnl=None)]
    )

    assert [(r.status, r.net, r.source) for r in rows] == [
        (acct.FillStatus.UNSETTLED, None, acct.PnlSource.C2)
    ]
    disclosures = acct.build_disclosures(rows)
    assert disclosures.n_null_pnl_final == 1
    assert disclosures.booked_total == Decimal(0)


def test_c2_fee_unreconciled_row_is_never_booked() -> None:
    row = _row(
        "x",
        excluded_reason=ExcludedReason.FEE_UNRECONCILED,
        realized_pnl=None,
        settled_outcome=None,
    )
    selected = acct.accounting_rows([row], legacy_scorer_ids=_LEGACY_IDS)
    buckets = _buckets(unreconciled=[_af(_fill("x"))])

    inside = _build(buckets, accounting=selected, now=_DEADLINE + _HOUR_NS)
    overdue = _build(buckets, accounting=selected, now=_DEADLINE + 24 * _HOUR_NS)

    assert [(r.status, r.net) for r in inside] == [(acct.FillStatus.OPEN, None)]
    assert [(r.status, r.net) for r in overdue] == [(acct.FillStatus.UNPRICED, None)]


def test_cli_final_check_compares_booked_tmax_with_fresh_read() -> None:
    fill = _fill("x")
    buckets = _buckets(scored=[_af(fill, "t")])
    scored = {"t": _scored("t", fill, tmax=87)}

    agree = _build(buckets, scored=scored, reader=lambda s, d: 87)
    disagree = _build(buckets, scored=scored, reader=lambda s, d: 88)
    unavailable = _build(buckets, scored=scored, reader=lambda s, d: None)

    assert [(r.cli_final_check, r.booked_tmax_f) for r in agree] == [(acct.CliCheck.AGREE, 87)]
    assert [r.cli_final_check for r in disagree] == [acct.CliCheck.DISAGREE]
    assert [r.cli_final_check for r in unavailable] == [acct.CliCheck.UNAVAILABLE]
    # the booked net is never edited by the check; the fresh outcome is disclosure only
    assert [r.net for r in disagree] == [r.net for r in agree] == [Decimal("0.87")]
    assert [r.cli_final_net for r in disagree] == [Decimal("-0.13")]
    assert [r.cli_final_net for r in agree] == [None]


def test_cli_final_check_reads_the_station_day_of_the_instrument() -> None:
    seen: list[tuple[str, dt.date]] = []
    fill = _fill("x")

    _build(
        _buckets(scored=[_af(fill, "t")]),
        scored={"t": _scored("t", fill)},
        reader=lambda s, d: seen.append((s, d)) or 87,
    )

    assert seen == [("MIA", dt.date(2026, 10, 3))]


_BAND_CASES = [
    # (instrument, fresh tmax, expected win)  expectations are decided by bucket_facts only
    (slug("MIA", "2026-09-13", 91), 92, True),
    (slug("MIA", "2026-09-15", 92, no=True), 93, False),
    (slug("MDW", "2026-09-22", 62, no=True), 64, True),
    ("tc-temp-mdwhigh-2026-10-02-lt70f.POLYMARKET_US", 69, True),
    ("tc-temp-mdwhigh-2026-10-02-lt70f.POLYMARKET_US", 70, False),
    ("tc-temp-laxhigh-2026-10-02-gte90f.POLYMARKET_US", 90, True),
]


def test_band_fixture_reproduces_through_bucket_facts() -> None:
    """Every expected outcome comes from ``bucket_facts_from_instrument_id`` (inclusive bands);
    the report's fresh-read net reproduces it row by row and in total."""
    rows: list[acct.FillPnlRow] = []
    expected: list[Decimal] = []
    for n, (instrument, tmax, expected_win) in enumerate(_BAND_CASES):
        facts = bucket_facts_from_instrument_id(instrument)
        assert facts is not None
        inside = facts.contains(tmax)
        held = (not inside) if "^no" in instrument else inside
        assert held is expected_win, instrument
        fill = _fill(f"b{n}", instrument=instrument, cost="0.20", fee="0.00")
        # the booked tmax deliberately differs, so the fresh read is the one that is compared
        booked = _scored(f"t{n}", fill, tmax=tmax - 5, held=not held)
        rows += _build(
            _buckets(scored=[_af(fill, f"t{n}")]),
            scored={f"t{n}": booked},
            reader=lambda station, day, fresh=tmax: fresh,
        )
        expected.append((Decimal(1) if held else Decimal(0)) - Decimal("0.20"))

    assert [r.cli_final_check for r in rows] == [acct.CliCheck.DISAGREE] * len(_BAND_CASES)
    assert [r.cli_final_net for r in rows] == expected
    assert sum((r.cli_final_net or Decimal(0) for r in rows), Decimal(0)) == sum(
        expected, Decimal(0)
    )


def test_roi_accounting_status_ok_only_when_every_fill_settled_or_exit() -> None:
    settled = [acct.FillStatus.SETTLED_NWS_IMPLIED] * 3
    for status in acct.FillStatus:
        got = acct.roi_accounting_status(
            gate_status=None, n_unlabelled_fq=0, statuses=[*settled, status]
        )
        ok = status in (acct.FillStatus.SETTLED_NWS_IMPLIED, acct.FillStatus.EXIT)
        assert (got is acct.RoiAccountingStatus.OK) is ok, status
        if not ok:
            assert got is acct.RoiAccountingStatus.GATED_UNSETTLED_CAPITAL, status


def test_roi_accounting_status_derivation_order() -> None:
    settled = [acct.FillStatus.SETTLED_NWS_IMPLIED]
    pending = [acct.FillStatus.OPEN]

    def status(gate: str | None, n: int, statuses: list[acct.FillStatus]) -> str:
        return str(
            acct.roi_accounting_status(gate_status=gate, n_unlabelled_fq=n, statuses=statuses)
        )

    assert status("GATED_IDENTITY", 3, pending) == "GATED_IDENTITY"
    assert status(None, 3, pending) == "GATED_UNLABELLED_FQ"
    assert status("GATED_UNSETTLED_CAPITAL", 0, settled) == "GATED_UNSETTLED_CAPITAL"
    assert status(None, 0, pending) == "GATED_UNSETTLED_CAPITAL"
    assert status(None, 0, settled) == "OK"
    assert status(None, 0, []) == "OK"


def test_roi_accounting_status_maps_gated_unlabelled_fq() -> None:
    got = acct.roi_accounting_status(
        gate_status=None, n_unlabelled_fq=1, statuses=[acct.FillStatus.SETTLED_NWS_IMPLIED]
    )

    assert got is acct.RoiAccountingStatus.GATED_UNLABELLED_FQ


def test_accounting_string_constants_equal_the_report_constants() -> None:
    assert acct.RoiAccountingStatus.GATED_IDENTITY.value == _prr.ROI_STATUS_GATED_IDENTITY
    assert acct.RoiAccountingStatus.GATED_UNLABELLED_FQ.value == _prr.ROI_STATUS_GATED_UNLABELLED_FQ
    assert (
        acct.RoiAccountingStatus.GATED_UNSETTLED_CAPITAL.value
        == _prr.ROI_STATUS_GATED_UNSETTLED_CAPITAL
    )
    assert acct.UNKNOWN_FAMILY == _prr.UNKNOWN_TRIAL_FAMILY_LABEL


def test_basis_of_a_straddle_row_is_derived_from_the_exported_predicate() -> None:
    from tests.support.te1_fixtures import load_repo_manifests

    manifests = load_repo_manifests()
    terminal_ns = day_start_ns("2026-10-05", 17)  # the straddle window: terminal day, UTC
    straddle = _fill(
        "s", instrument="tc-temp-sfohigh-2026-10-06-gte81lt82f.POLYMARKET_US", ts=terminal_ns
    )
    inside = _fill(
        "i", instrument="tc-temp-sfohigh-2026-10-03-gte81lt82f.POLYMARKET_US", ts=terminal_ns
    )
    rows = _build(
        _buckets(unreconciled=[_af(straddle), _af(inside)]),
        accounting=[
            _row("s", instrument_id=straddle.instrument_id, climate_day="2026-10-06"),
            _row("i", instrument_id=inside.instrument_id, climate_day="2026-10-03"),
        ],
        manifests=manifests,
    )

    assert {r.client_order_id: r.attribution_basis for r in rows} == {
        "s": acct.Basis.PRE_EPOCH_BRIDGE_POST_TERMINAL,
        "i": acct.Basis.PRE_EPOCH_BRIDGE,
    }


# ---------------------------------------------------------------------------------------------
# the real 34-fill world through the report
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def world(tmp_path: Path) -> World:
    return label_world(tmp_path / "w")


@pytest.fixture
def run(world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    return run_report(monkeypatch, world, tmp_path)


def _rows(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["client_order_id"]: r for r in report["fill_pnl"]}


def _row_of(report: dict[str, Any], coid: str) -> dict[str, Any]:
    rows = _rows(report)
    assert coid in rows, f"{coid} has no fill_pnl row ({len(rows)} rows)"
    return rows[coid]


def _net(rows: Any) -> Decimal:
    return sum((Decimal(r["net"]) for r in rows if r["net"] is not None), Decimal(0))


def test_world_reproduces_the_corrected_audit(world: World, run: Any) -> None:
    report = run.report()
    rows = report["fill_pnl"]
    fq = [r for r in rows if r["family_id"] == _FQ]

    assert run.exit_code == 0
    assert report["n_ledger_rows"] == len(rows) == 34
    assert _net(rows) == Decimal("-2.63")
    assert sum(1 for r in rows if r["win"] is True) == 4
    assert (len(fq), sum(1 for r in fq if r["win"]), _net(fq)) == (25, 2, Decimal("-2.17"))
    assert _net(r for r in rows if r["family_id"] != _FQ) == Decimal("-0.46")
    assert sum(1 for r in rows if r["family_id"] != _FQ and r["win"]) == 2
    assert sum((Decimal(r["cost"]) for r in rows), Decimal(0)) == Decimal("6.36")
    assert sum((Decimal(r["fee"]) for r in rows), Decimal(0)) == Decimal("0.27")
    assert {r["status"] for r in rows} == {"SETTLED_NWS_IMPLIED"}
    assert {r["cli_final_check"] for r in rows} == {"AGREE"}
    assert report["disclosures"]["n_settlement_disagree"] == 0
    assert "PORTFOLIO_ROI_NO_INPUT" not in run.sink.events()


def test_world_sources_and_fee_unverified_residuals(world: World, run: Any) -> None:
    rows = run.report()["fill_pnl"]
    by_source = {s: [r for r in rows if r["source"] == s] for s in ("LEGACY", "RESIDUAL", "C2")}

    assert {s: len(v) for s, v in by_source.items()} == {"LEGACY": 7, "RESIDUAL": 2, "C2": 25}
    assert _net(by_source["LEGACY"]) == Decimal("-0.54")
    assert _net(by_source["RESIDUAL"]) == Decimal("0.08")
    assert {r["client_order_id"] for r in by_source["RESIDUAL"]} == set(LEGACY_COIDS[:2])
    assert all(r["fee_unverified"] for r in by_source["RESIDUAL"])
    assert not any(r["fee_unverified"] for r in by_source["LEGACY"] + by_source["C2"])
    assert run.report()["disclosures"]["n_fee_unverified"] == 2


def test_residual_fee_unverified_booked_at_recorded_fee(world: World, run: Any) -> None:
    residual = [r for r in run.report()["fill_pnl"] if r["source"] == "RESIDUAL"]

    by_coid = {r["client_order_id"]: r for r in residual}
    assert set(by_coid) == set(LEGACY_COIDS[:2])
    sfo, mia = by_coid[LEGACY_COIDS[0]], by_coid[LEGACY_COIDS[1]]
    assert (sfo["fee"], mia["fee"]) == ("0", "0")  # the recorded fee, never the modelled one
    assert (Decimal(sfo["net"]), Decimal(mia["net"])) == (Decimal("-0.22"), Decimal("0.30"))
    assert (mia["win"], mia["booked_tmax_f"]) == (True, 92)


def test_family_pnl_fq_includes_post_terminal_fills(world: World, run: Any) -> None:
    report = run.report()
    families = {f["family_id"]: f for f in report["family_pnl"]}

    assert _FQ in families
    assert (families[_FQ]["n_fills"], families[_FQ]["n_wins"], Decimal(families[_FQ]["net"])) == (
        25,
        2,
        Decimal("-2.17"),
    )
    assert families.get("UNKNOWN") is None
    assert sum(Decimal(f["net"]) for f in families.values()) == Decimal("-2.63")


def test_family_pnl_sums_to_accounting_total(world: World, run: Any) -> None:
    report = run.report()

    total = Decimal(report["realised_pnl_accounting_total"])
    assert total == _net(report["fill_pnl"]) == Decimal("-2.63")
    assert sum(Decimal(f["net"]) for f in report["family_pnl"]) == total


def test_label_and_report_post_terminal_sets_identical(world: World, run: Any) -> None:
    """The five fills the labeler bridges by the R11 straddle are, as a set, the five the report
    books as ``pre_epoch_bridge_post_terminal``."""
    rows = run.report()["fill_pnl"]
    reported = {
        r["fill_key"] for r in rows if r["attribution_basis"] == "pre_epoch_bridge_post_terminal"
    }

    assert len(reported) == 5
    assert reported == post_terminal_label_keys(world)


def test_post_terminal_disclosure_names_the_excluded_straddle_pnl(world: World, run: Any) -> None:
    disclosures = run.report()["disclosures"]
    rows = run.report()["fill_pnl"]
    five = [r for r in rows if r["attribution_basis"] == "pre_epoch_bridge_post_terminal"]

    assert disclosures["n_post_terminal_bridge"] == 5
    assert disclosures["post_terminal_wins"] == 0 == sum(1 for r in five if r["win"])
    assert Decimal(disclosures["post_terminal_pnl"]) == _net(five)
    assert disclosures["post_terminal_ref"] == "TE-2 P16 / cebaab49"
    assert "terminal window" in disclosures["post_terminal_note"]
    assert "unrelated counts" in disclosures["post_terminal_note"]


def test_disclosures_no_fill_intents_five_ambiguous_unknown_and_venue_positions_false(
    world: World, run: Any
) -> None:
    """``n_no_fill_intents`` (never-filled intents, Stage 0 S0-11) and ``n_post_terminal_bridge``
    (fills sent after the failed halt) are unrelated counts that happen to both be five."""
    disclosures = run.report()["disclosures"]

    assert disclosures["n_no_fill_intents"] == 5
    assert disclosures["no_fill_source"] == "exec/polymarket_us/intent/history+resolver"
    assert disclosures["n_ambiguous_no_fill"] == "UNKNOWN"
    assert disclosures["n_ambiguous_no_fill"] != 0
    assert disclosures["venue_positions_reconciled"] is False
    assert disclosures["n_labels_gated"] == 0
    assert disclosures["n_null_pnl_final"] == 0
    assert disclosures["n_fee_unverified"] == 2  # counted from the table, not a constant
    assert "FU-3d" in disclosures["fee_delta_disclosure_ref"]
    assert "fee_unverified residuals (FU-3d" in (run.json_path.with_suffix(".md")).read_text()


def test_world_roi_fields(world: World, run: Any) -> None:
    report = run.report()
    capital = _prr.total_capital_deployed(
        f for f in _prr.read_ledger_fills_with_counts(world.exec_db).fills
    )

    assert report["roi_status"] == "GATED_ACCOUNTING_ONLY"
    assert report["roi"] is None
    assert report["roi_accounting_status"] == "OK"
    assert Decimal(report["roi_accounting"]) == _prr.roi(
        total_realised_pnl=Decimal("-2.63"), total_capital_deployed=capital
    )
    assert report["schema_version"] == 5
    assert report["fill_pnl"] and (run.json_path.stat().st_mode & 0o777) == 0o600


def test_roi_gated_accounting_only_when_pnl_outside_admissible(world: World, run: Any) -> None:
    report = run.report()

    assert report["roi_status"] == "GATED_ACCOUNTING_ONLY"
    assert Decimal(report["realised_pnl_c2_total"]) == Decimal(0)  # the 25 rows are not admissible
    assert Decimal(report["realised_pnl_accounting_total"]) == Decimal("-2.63")


def test_roi_ok_when_all_pnl_admissible() -> None:
    """Positive control: no accounting P&L outside the admissible set leaves the status OK."""
    kwargs = _report_kwargs()

    outside = _prr.build_portfolio_roi_report_data(**kwargs, pnl_outside_admissible=True)
    inside = _prr.build_portfolio_roi_report_data(**kwargs, pnl_outside_admissible=False)

    assert outside.roi_status == "GATED_ACCOUNTING_ONLY"
    assert inside.roi_status == "OK"
    assert "GATED_ACCOUNTING_ONLY" in _prr._LABEL_GATED_STATUSES


def test_a_label_status_beats_accounting_only() -> None:
    kwargs = _report_kwargs()

    gated = _prr.build_portfolio_roi_report_data(
        **kwargs, pnl_outside_admissible=True, roi_status_override="GATED_IDENTITY"
    )

    assert gated.roi_status == "GATED_IDENTITY"


def _report_kwargs() -> dict[str, Any]:
    base = _prr.cumulative_reconciliation(daily_rows=(), settled_through="2026-10-01")
    baselines = _prr.roi_against_baselines(
        total_realised_pnl=Decimal(0), total_capital_deployed=Decimal(0), fills=[]
    )
    return {
        "period_start": "2026-10-01",
        "period_end": "2026-10-03",
        "fill_buckets": {},
        "total_realised_pnl": Decimal(0),
        "total_capital_deployed": Decimal(0),
        "baselines": baselines,
        "cumulative": base,
        "settled_through_statistic": "max",
        "lag_sample_n": 0,
        "permanently_unsettled": (),
    }


def test_c2_total_stays_admissible_only(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression pin: ``realised_pnl_c2_total`` and ``roi*`` stay statistics-only. One admissible
    control row (no ledger fill) is the whole C2 term; the 25 accounting rows add nothing to it."""
    control = make_label_row(
        label_id="9" * 32, client_order_id="O-CONTROL", trade_id="T-CONTROL", family_id=_FQ
    )
    write_labels(world.data_root, _FQ, [control], now_ns=world.now_ns + 1)

    report = run_report(monkeypatch, world, tmp_path).report()

    assert Decimal(report["realised_pnl_c2_total"]) == Decimal("0.57")
    assert Decimal(report["realised_pnl_accounting_total"]) == Decimal("-2.63")


def test_overlap_guard_covers_accounting_rows(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A non-admissible accounting row sharing a trial id with a scored trial would pay it twice."""
    scored_trial_id = next(iter(world.scored))
    clash = _row("O-CLASH", label_id="8" * 32, trade_id="T-CLASH", trial_id=scored_trial_id)
    write_labels(world.data_root, _FQ, [clash], now_ns=world.now_ns + 1)

    run = run_report(monkeypatch, world, tmp_path)

    assert run.exit_code == 1
    assert "PNL_SOURCE_OVERLAP" in capsys.readouterr().err
    assert not run.json_path.exists()


def test_no_overlap_leaves_the_world_run_clean(world: World, run: Any) -> None:
    """Positive control for the overlap test."""
    assert run.exit_code == 0
    assert run.json_path.exists()


# -- gate states -------------------------------------------------------------------------------


def _extra_fill(world: World, coid: str, instrument: str, ts: int) -> None:
    seed_fills(world.exec_db, [_fill(coid, instrument=instrument, ts=ts, cost="0.10", fee="0.00")])


def _marker(world: World, *, pending: int = 0, written_at_ns: int | None = None) -> None:
    write_marker(
        world.data_root,
        RunMarker(
            run_outcome=RunOutcome.PENDING if pending else RunOutcome.LABELLED,
            durable_fill_count=34,
            durable_fill_count_prev=None,
            labelled_final=34 - pending,
            unattributed_pre_epoch=25,
            legacy_labelled=9,
            open=0,
            pending=pending,
            unresolved=0,
            missing_label=0,
            p_null_count=0,
            non_c1_post_epoch_count=0,
        ),
        day="2026-10-11",
        now_ns=written_at_ns if written_at_ns is not None else world.now_ns + 5,
    )


def test_gated_unsettled_capital_books_final_rows_and_marks_only_pending_fill(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _marker(world, pending=1)
    _extra_fill(world, "O-PENDING", slug("MIA", "2026-10-11", 90), world.now_ns - _HOUR_NS)

    run = run_report(monkeypatch, world, tmp_path)
    report = run.report()
    statuses = {r["client_order_id"]: r["status"] for r in report["fill_pnl"]}

    assert "O-PENDING" in statuses
    assert statuses.pop("O-PENDING") == "OPEN"
    assert set(statuses.values()) == {"SETTLED_NWS_IMPLIED"}
    assert len(statuses) == 34
    assert report["roi_accounting_status"] == "GATED_UNSETTLED_CAPITAL"
    assert report["roi_accounting"] is None
    assert Decimal(report["realised_pnl_accounting_total"]) == Decimal("-2.63")
    assert run.exit_code == 0
    assert "PORTFOLIO_ROI_LABEL_IDENTITY" not in run.sink.events()


def test_gated_identity_books_no_label_row_alerts_identity_not_no_input(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty_root = tmp_path / "empty_labels"
    empty_root.mkdir(mode=0o700)

    run = run_report(monkeypatch, world, tmp_path, labels_root=empty_root)
    report = run.report()
    rows = report["fill_pnl"]
    gated = [r for r in rows if r["status"] == "LABELS_GATED"]

    assert len(gated) == 25
    assert {r["source"] for r in gated} == {"NONE"}
    assert all(r["net"] is None and r["win"] is None for r in gated)
    assert sum(1 for r in rows if r["source"] in ("LEGACY", "RESIDUAL")) == 9  # always booked
    assert _net(rows) == Decimal("-0.46")
    assert report["disclosures"]["n_labels_gated"] == 25
    assert report["roi_accounting_status"] == "GATED_IDENTITY"
    assert run.exit_code == 1
    assert run.sink.events().count("PORTFOLIO_ROI_LABEL_IDENTITY") == 1
    assert run.sink.severities("PORTFOLIO_ROI_LABEL_IDENTITY") == ["CRITICAL"]
    assert "PORTFOLIO_ROI_NO_INPUT" not in run.sink.events()


def test_stale_marker_is_identity_not_unsettled_capital(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale_at = world.now_ns - 100 * _HOUR_NS
    for marker in sorted((world.data_root / "derived" / "label_outcomes").rglob("marker_*.json")):
        marker.unlink()
    _marker(world, pending=1, written_at_ns=stale_at)
    assert _prr._gate_status_of(world.data_root, world.now_ns) == "GATED_IDENTITY"

    run = run_report(monkeypatch, world, tmp_path)

    assert run.report()["roi_accounting_status"] == "GATED_IDENTITY"
    assert run.exit_code == 1


def test_fresh_pending_marker_is_unsettled_capital_not_identity(world: World) -> None:
    """Positive control for the stale-marker test."""
    for marker in sorted((world.data_root / "derived" / "label_outcomes").rglob("marker_*.json")):
        marker.unlink()
    _marker(world, pending=1)

    assert _prr._gate_status_of(world.data_root, world.now_ns + 10) == "GATED_UNSETTLED_CAPITAL"


def test_roi_accounting_status_maps_gated_unlabelled_fq_in_the_world(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An FQ fill that arrives after the label run, with a consumable marker, is never OK."""
    _extra_fill(world, "O-AFTER", slug("MIA", "2026-10-12", 90), world.now_ns - _HOUR_NS)

    run = run_report(monkeypatch, world, tmp_path)
    report = run.report()

    assert report["roi_accounting_status"] == "GATED_UNLABELLED_FQ"
    assert report["roi_accounting"] is None
    assert report["roi_status"] == "GATED_UNLABELLED_FQ"


# -- statuses, nulls, alerts -------------------------------------------------------------------


def _rewrite(world: World, coid: str, **over: Any) -> None:
    row = next(r for r in read_labels(world.data_root) if r.client_order_id == coid)
    newer = dataclasses.replace(row, label_seq=row.label_seq + 1, **over)
    write_labels(world.data_root, row.family_id, [newer], now_ns=world.now_ns + 2)


def test_null_pnl_final_row_unsettled_alerted_not_zero(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    victim = "O-20261003-021031-L001-MIA-1"
    _rewrite(world, victim, realized_pnl=None)

    run = run_report(monkeypatch, world, tmp_path)
    report = run.report()
    row = _row_of(report, victim)

    assert (row["status"], row["net"], row["win"]) == ("UNSETTLED", None, None)
    assert report["disclosures"]["n_null_pnl_final"] == 1
    assert Decimal(report["realised_pnl_accounting_total"]) == Decimal("-2.63") - Decimal("0.88")
    assert run.sink.severities("PORTFOLIO_ROI_NULL_PNL_FINAL") == ["CRITICAL"]
    assert report["roi_accounting_status"] == "GATED_UNSETTLED_CAPITAL"


def test_c2_fee_unreconciled_not_booked_and_alerted(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    victim = "O-20261003-021031-L001-MIA-1"
    _rewrite(
        world,
        victim,
        excluded_reason=ExcludedReason.FEE_UNRECONCILED,
        realized_pnl=None,
        settled_outcome=None,
    )

    run = run_report(monkeypatch, world, tmp_path)
    row = _row_of(run.report(), victim)

    assert (row["status"], row["net"]) == ("UNPRICED", None)
    assert run.exit_code == 1
    assert "PORTFOLIO_ROI_NO_INPUT" in run.sink.events()


def test_overdue_unpriced_fill_alerts_no_input_exit_1(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _extra_fill(world, "O-OVERDUE", slug("MIA", "2026-10-08", 90), day_start_ns("2026-10-08", 15))

    run = run_report(monkeypatch, world, tmp_path)
    row = _row_of(run.report(), "O-OVERDUE")

    assert row["status"] == "UNPRICED"
    assert run.exit_code == 1
    assert run.sink.events().count("PORTFOLIO_ROI_NO_INPUT") == 1
    assert run.sink.severities("PORTFOLIO_ROI_NO_INPUT") == ["CRITICAL"]


def test_pending_inside_deadline_does_not_alert(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive control: an unlabelled fill still inside its deadline window is only OPEN."""
    _extra_fill(world, "O-INSIDE", slug("MIA", "2026-10-12", 90), world.now_ns - _HOUR_NS)

    run = run_report(monkeypatch, world, tmp_path)

    assert _row_of(run.report(), "O-INSIDE")["status"] == "OPEN"
    assert run.exit_code == 0
    assert "PORTFOLIO_ROI_NO_INPUT" not in run.sink.events()


def test_fill_count_mismatch_alerts_exit_1(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = _prr.accounting.build_fill_pnl
    monkeypatch.setattr(_prr.accounting, "build_fill_pnl", lambda *a, **k: real(*a, **k)[1:])

    run = run_report(monkeypatch, world, tmp_path)

    assert run.exit_code == 1
    assert "PORTFOLIO_ROI_FILL_COUNT_MISMATCH" in run.sink.events()
    assert run.sink.severities("PORTFOLIO_ROI_FILL_COUNT_MISMATCH") == ["CRITICAL"]


def test_legacy_total_mismatch_raises_exit_1_and_writes_nothing(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    real = _prr.total_realised_pnl_all_settled
    monkeypatch.setattr(
        _prr, "total_realised_pnl_all_settled", lambda trials: real(trials) + Decimal("0.01")
    )

    run = run_report(monkeypatch, world, tmp_path)

    assert run.exit_code == 1
    assert "SourceTotalMismatch" in capsys.readouterr().err
    assert not run.json_path.exists()


def test_settlement_disagree_flagged_and_warned(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A synthetic correction: the fresh FINAL for MIA 10-03 is one degree higher than booked."""
    reader = settlements_reader(world, shift={("MIA", "2026-10-03"): 1})

    run = run_report(monkeypatch, world, tmp_path, reader=reader)
    report = run.report()
    row = _row_of(report, "O-20261003-021031-L001-MIA-1")

    assert row["cli_final_check"] == "DISAGREE"
    assert Decimal(row["net"]) == Decimal("0.88")  # booked, never edited
    assert Decimal(row["cli_final_net"]) == Decimal("-0.12")  # gte86lt87 no longer contains 88
    assert report["disclosures"]["n_settlement_disagree"] == 1
    disclosures = report["disclosures"]
    assert Decimal(disclosures["booked_total"]) == Decimal("-2.63")
    assert Decimal(disclosures["cli_final_net_total"]) == Decimal("-3.63")
    assert run.sink.severities("PORTFOLIO_ROI_SETTLEMENT_DISAGREE") == ["WARN"]
    assert run.exit_code == 0


def test_unavailable_cli_reader_is_disclosed_never_agree(
    world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = run_report(monkeypatch, world, tmp_path, reader=lambda station, day: None)
    report = run.report()

    assert {r["cli_final_check"] for r in report["fill_pnl"]} == {"UNAVAILABLE"}
    assert report["disclosures"]["n_cli_final_unavailable"] == 34
    assert report["disclosures"]["n_settlement_disagree"] == 0
    assert run.exit_code == 0


def test_default_cli_reader_never_touches_the_host_catalog_under_pytest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L-57: the production default (no injected reader, the real catalog root) is refused under
    pytest and reports UNAVAILABLE without opening, creating or reading anything."""

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("the host catalog must not be opened under pytest")

    monkeypatch.setattr(_prr, "open_station_catalog", boom)
    monkeypatch.setattr(_prr, "read_climate_day_including_corrections", boom)

    reader = _prr._default_cli_final_reader(_prr.DEFAULT_NWS_CATALOG_BASE)

    assert reader("MIA", dt.date(2026, 10, 3)) is None


def test_injected_cli_reader_reads_only_an_existing_station_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive control: an injected base is read, and a station with no catalog directory is
    never created (UNAVAILABLE)."""
    opened: list[str] = []
    monkeypatch.setattr(
        _prr, "open_station_catalog", lambda base, venue, city: opened.append(city) or city
    )
    record = type("R", (), {"is_final": True, "tmax_f": 87})()
    monkeypatch.setattr(_prr, "read_climate_day_including_corrections", lambda cat, **k: record)
    reader = _prr._default_cli_final_reader(tmp_path / "catalog")
    (tmp_path / "catalog" / "polymarket_us" / "MIA").mkdir(parents=True)

    assert reader("MIA", dt.date(2026, 10, 3)) == 87
    assert reader("LAX", dt.date(2026, 10, 3)) is None
    assert opened == ["MIA"]
    assert not (tmp_path / "catalog" / "polymarket_us" / "LAX").exists()


# -- schema v5 and the journal -----------------------------------------------------------------

_V5_KEYS = (
    "realised_pnl_accounting_total",
    "roi_accounting",
    "roi_accounting_status",
    "fill_pnl",
    "family_pnl",
    "disclosures",
)


def test_schema_v5_reader_accepts_1_to_5_and_rejects_v5_missing_keys(
    world: World, run: Any, tmp_path: Path
) -> None:
    raw = run.report()
    path = tmp_path / "v.json"

    assert _prr.PORTFOLIO_ROI_SCHEMA_VERSION == 5
    view = _prr.read_portfolio_roi_report(run.json_path)
    assert view.schema_version == 5
    assert view.roi_accounting_status == "OK"
    assert view.realised_pnl_accounting_total == Decimal("-2.63")
    assert view.fill_pnl is not None and len(view.fill_pnl) == 34
    assert view.family_pnl is not None and {f.family_id for f in view.family_pnl} >= {_FQ}
    for version in (1, 2, 3, 4):
        path.write_text(json.dumps({**raw, "schema_version": version}))
        old = _prr.read_portfolio_roi_report(path)
        assert old.schema_version == version
    for key in _V5_KEYS:
        broken = {k: v for k, v in raw.items() if k != key}
        path.write_text(json.dumps(broken))
        with pytest.raises(_prr.PortfolioRoiReportMalformedFieldError):
            _prr.read_portfolio_roi_report(path)


def test_a_v4_report_has_no_accounting_view(run: Any, tmp_path: Path) -> None:
    raw = {k: v for k, v in run.report().items() if k not in _V5_KEYS}
    path = tmp_path / "v4.json"
    path.write_text(json.dumps({**raw, "schema_version": 4}))

    view = _prr.read_portfolio_roi_report(path)

    assert (view.fill_pnl, view.family_pnl, view.roi_accounting_status) == (None, None, None)


def test_accounting_only_report_reader_raises_on_statistics_roi(run: Any) -> None:
    view = _prr.read_portfolio_roi_report(run.json_path)

    with pytest.raises(_prr.UnsettledCapitalRoiError):
        _ = view.roi


def test_journal_line_dimensionless(
    world: World,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Regression pin: the journal line the wrapper prints stays free of any currency token (the
    wrapper withholds a line matching ``\\$|[0-9]+\\.[0-9]{2}|USD``)."""
    run_report(monkeypatch, world, tmp_path)

    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("PORTFOLIO_ROI ")]

    assert len(lines) == 1
    assert "roi_status=GATED_ACCOUNTING_ONLY" in lines[0]
    assert not re.search(r"\$|[0-9]+\.[0-9]{2}|USD", lines[0])


def test_accounting_module_never_uses_dataclasses_asdict() -> None:
    """No ``dataclasses.asdict`` anywhere in the new module (credential-serialisation guard)."""
    source = (_REPO_ROOT / "src/breezy/analysis/labeling/accounting.py").read_text()
    tree = ast.parse(source)

    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
        n.id for n in ast.walk(tree) if isinstance(n, ast.Name)
    }
    assert "asdict" not in names
