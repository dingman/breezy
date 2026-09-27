"""EDGE-2 Step 0: the read-only MIA 09-23 ambiguous-order probe
(``scripts/venue/edge2_ambiguous_order_probe.py``).

Authority: ``docs/plans/backlog/EDGE_2026-09-27/
EDGE-2_ambiguous_executions_resolver_plan_r3_2026-09-27.md`` section 6 (Step
0) and section 7 (test strategy, slice 0 row).

This suite covers ONLY the pure parts of the probe: the Q2(i)/(ii)/(iii)
filters, activities completeness, the Q2s ordering/cursor-stability checks,
the positive-control join, redaction, and the decision-table verdict
function. The async venue I/O (``_fetch_and_save``, ``_paginate_activities``,
``_run_step0``, ``main``) is exercised only by the read-only
``systemd-run --user`` oneshot against the real venue -- never by an offline
test, since it has no fake-transport seam here (mirroring the plan's own
framing of Step 0 as a hand-run, evidence-producing script rather than a
covered production module).
"""

from __future__ import annotations

import ast
import importlib.util
import os
import stat
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "venue" / "edge2_ambiguous_order_probe.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("edge2_ambiguous_order_probe", _SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    return _load_module()


# ---------------------------------------------------------------------------
# Fixtures: captured venue shapes (from the 09-05 evidence pack)
# ---------------------------------------------------------------------------


def _trade_activity(
    *,
    aggressor_id: str = "AGG-ID",
    passive_id: str = "PASV-ID",
    market_slug: str = "tc-temp-miahigh-2026-09-23-gte82lt83f",
    qty_decimal: str = "1.0000",
    trade_id: str = "TRADE-1",
    create_time: str = "2026-09-23T17:22:10.000000000Z",
) -> dict:
    return {
        "type": "ACTIVITY_TYPE_TRADE",
        "trade": {
            "id": trade_id,
            "marketSlug": market_slug,
            "createTime": create_time,
            "qtyDecimal": qty_decimal,
            "qty": qty_decimal,
            "aggressor": {"id": aggressor_id},
            "passive": {"id": passive_id},
        },
    }


def _position_resolution_activity(
    *,
    market_slug: str = "tc-temp-miahigh-2026-09-23-gte82lt83f",
    before_qty_bought: str = "0",
    after_update_time: str = "2026-09-24T00:00:00.000000000Z",
    trade_id: str = "RES-TRADE-1",
) -> dict:
    return {
        "type": "ACTIVITY_TYPE_POSITION_RESOLUTION",
        "positionResolution": {
            "marketSlug": market_slug,
            "tradeId": trade_id,
            "beforePosition": {"qtyBought": before_qty_bought},
            "afterPosition": {"updateTime": after_update_time},
        },
    }


def _deposit_activity(
    *, transaction_id: str = "TXN-1", create_time: str = "2026-09-20T00:00:00.000000000Z"
) -> dict:
    return {
        "type": "ACTIVITY_TYPE_ACCOUNT_DEPOSIT",
        "accountBalanceChange": {
            "transactionId": transaction_id,
            "createTime": create_time,
        },
    }


def _page(activities: list[dict], *, eof: bool = False, next_cursor: str | None = None) -> dict:
    page: dict = {"activities": activities, "eof": eof}
    if next_cursor is not None:
        page["nextCursor"] = next_cursor
    return page


# ---------------------------------------------------------------------------
# Q2(i)/(ii)/(iii) filters
# ---------------------------------------------------------------------------


class TestQ2Filters:
    def test_is_trade_for_order_matches_aggressor_id(self, probe: ModuleType) -> None:
        activity = _trade_activity(aggressor_id="CP05MNWMAWP6")
        assert probe.is_trade_for_order(activity, "CP05MNWMAWP6") is True

    def test_is_trade_for_order_matches_passive_id(self, probe: ModuleType) -> None:
        activity = _trade_activity(passive_id="CP05MNWMAWP6")
        assert probe.is_trade_for_order(activity, "CP05MNWMAWP6") is True

    def test_is_trade_for_order_false_for_non_trade_type(self, probe: ModuleType) -> None:
        activity = _deposit_activity()
        assert probe.is_trade_for_order(activity, "CP05MNWMAWP6") is False

    def test_is_trade_for_order_false_when_neither_leg_matches(self, probe: ModuleType) -> None:
        activity = _trade_activity(aggressor_id="OTHER-A", passive_id="OTHER-B")
        assert probe.is_trade_for_order(activity, "CP05MNWMAWP6") is False

    def test_is_trade_on_slug_true_for_matching_trade(self, probe: ModuleType) -> None:
        activity = _trade_activity(market_slug="tc-temp-miahigh-2026-09-23-gte82lt83f")
        assert probe.is_trade_on_slug(activity, "tc-temp-miahigh-2026-09-23-gte82lt83f") is True

    def test_is_trade_on_slug_false_for_other_slug(self, probe: ModuleType) -> None:
        activity = _trade_activity(market_slug="tc-temp-sfohigh-2026-09-05-gte73lt74f")
        assert probe.is_trade_on_slug(activity, "tc-temp-miahigh-2026-09-23-gte82lt83f") is False

    def test_is_trade_on_slug_false_for_non_trade_type(self, probe: ModuleType) -> None:
        activity = _position_resolution_activity(
            market_slug="tc-temp-miahigh-2026-09-23-gte82lt83f"
        )
        assert probe.is_trade_on_slug(activity, "tc-temp-miahigh-2026-09-23-gte82lt83f") is False

    def test_is_position_resolution_on_slug_true(self, probe: ModuleType) -> None:
        activity = _position_resolution_activity(
            market_slug="tc-temp-miahigh-2026-09-23-gte82lt83f"
        )
        assert (
            probe.is_position_resolution_on_slug(activity, "tc-temp-miahigh-2026-09-23-gte82lt83f")
            is True
        )

    def test_is_position_resolution_on_slug_false_for_other_slug(self, probe: ModuleType) -> None:
        activity = _position_resolution_activity(market_slug="other-slug")
        assert (
            probe.is_position_resolution_on_slug(activity, "tc-temp-miahigh-2026-09-23-gte82lt83f")
            is False
        )

    def test_is_position_resolution_on_slug_false_for_trade_type(self, probe: ModuleType) -> None:
        activity = _trade_activity(market_slug="tc-temp-miahigh-2026-09-23-gte82lt83f")
        assert (
            probe.is_position_resolution_on_slug(activity, "tc-temp-miahigh-2026-09-23-gte82lt83f")
            is False
        )


# ---------------------------------------------------------------------------
# Completeness (AC4(c))
# ---------------------------------------------------------------------------


class TestActivitiesAreComplete:
    def test_complete_when_a_page_reports_eof(self, probe: ModuleType) -> None:
        pages = [_page([_trade_activity()], eof=True)]
        assert probe.activities_are_complete(pages, threshold_iso="2026-09-23T17:21:00Z") is True

    def test_complete_when_min_create_time_is_before_threshold(self, probe: ModuleType) -> None:
        pages = [
            _page([_trade_activity(create_time="2026-09-23T18:00:00.000000000Z")]),
            _page([_deposit_activity(create_time="2026-09-20T00:00:00.000000000Z")]),
        ]
        assert probe.activities_are_complete(pages, threshold_iso="2026-09-23T17:21:00Z") is True

    def test_incomplete_when_no_eof_and_min_create_time_is_after_threshold(
        self, probe: ModuleType
    ) -> None:
        pages = [_page([_trade_activity(create_time="2026-09-23T18:00:00.000000000Z")])]
        assert probe.activities_are_complete(pages, threshold_iso="2026-09-23T17:21:00Z") is False

    def test_incomplete_when_no_pages(self, probe: ModuleType) -> None:
        assert probe.activities_are_complete([], threshold_iso="2026-09-23T17:21:00Z") is False

    def test_incomplete_when_no_activity_carries_a_timestamp(self, probe: ModuleType) -> None:
        pages = [_page([{"type": "ACTIVITY_TYPE_TRANSFER", "accountBalanceChange": {}}])]
        assert probe.activities_are_complete(pages, threshold_iso="2026-09-23T17:21:00Z") is False

    def test_max_pages_hit_without_eof_or_threshold_is_never_guessed_complete(
        self, probe: ModuleType
    ) -> None:
        pages = [
            _page([_trade_activity(create_time="2026-09-23T18:00:00.000000000Z")])
        ] * probe.MAX_ACTIVITY_PAGES
        assert probe.activities_are_complete(pages, threshold_iso="2026-09-23T17:21:00Z") is False


# ---------------------------------------------------------------------------
# Q2s: ordering and cursor stability
# ---------------------------------------------------------------------------


class TestQ2sOrdering:
    def test_non_increasing_true_for_descending_times(self, probe: ModuleType) -> None:
        times = [
            "2026-09-23T18:00:00.000000000Z",
            "2026-09-23T17:00:00.000000000Z",
            "2026-09-23T16:00:00.000000000Z",
        ]
        assert probe.create_times_non_increasing(times) is True

    def test_non_increasing_true_for_equal_adjacent_times(self, probe: ModuleType) -> None:
        times = ["2026-09-23T18:00:00.000000000Z", "2026-09-23T18:00:00.000000000Z"]
        assert probe.create_times_non_increasing(times) is True

    def test_non_increasing_false_when_a_later_time_is_greater(self, probe: ModuleType) -> None:
        times = [
            "2026-09-23T17:00:00.000000000Z",
            "2026-09-23T18:00:00.000000000Z",
        ]
        assert probe.create_times_non_increasing(times) is False

    def test_non_increasing_true_for_empty_and_single_element(self, probe: ModuleType) -> None:
        assert probe.create_times_non_increasing([]) is True
        assert probe.create_times_non_increasing(["2026-09-23T18:00:00.000000000Z"]) is True


class TestQ2sReReadIdentity:
    def test_identical_sequences_match(self, probe: ModuleType) -> None:
        run1 = probe.activity_identities(
            [_page([_trade_activity(trade_id="T1"), _trade_activity(trade_id="T2")])]
        )
        run2 = probe.activity_identities(
            [_page([_trade_activity(trade_id="T1"), _trade_activity(trade_id="T2")])]
        )
        assert probe.id_sequences_identical(run1, run2) is True

    def test_extra_new_row_in_run2_does_not_break_identity_over_the_overlap(
        self, probe: ModuleType
    ) -> None:
        run1 = probe.activity_identities([_page([_trade_activity(trade_id="T1")])])
        run2 = probe.activity_identities(
            [_page([_trade_activity(trade_id="T0"), _trade_activity(trade_id="T1")])]
        )
        assert probe.id_sequences_identical(run1, run2) is True

    def test_reordered_overlap_fails_identity(self, probe: ModuleType) -> None:
        run1 = probe.activity_identities(
            [_page([_trade_activity(trade_id="T1"), _trade_activity(trade_id="T2")])]
        )
        run2 = probe.activity_identities(
            [_page([_trade_activity(trade_id="T2"), _trade_activity(trade_id="T1")])]
        )
        assert probe.id_sequences_identical(run1, run2) is False

    def test_gap_in_run2_overlap_fails_identity(self, probe: ModuleType) -> None:
        # A page-boundary gap manifests as a missing id from run2's own
        # overlap-filtered sequence relative to run1's -- here simulated by
        # a duplicate collapsing what should have been two distinct rows.
        run1 = probe.activity_identities(
            [_page([_trade_activity(trade_id="T1"), _trade_activity(trade_id="T1")])]
        )
        run2 = probe.activity_identities([_page([_trade_activity(trade_id="T1")])])
        assert probe.id_sequences_identical(run1, run2) is False


class TestQ2sAscendingReverse:
    def test_ascending_is_exact_reverse_of_descending(self, probe: ModuleType) -> None:
        descending = probe.activity_identities(
            [
                _page(
                    [
                        _trade_activity(trade_id="T3"),
                        _trade_activity(trade_id="T2"),
                        _trade_activity(trade_id="T1"),
                    ]
                )
            ]
        )
        ascending = probe.activity_identities(
            [
                _page(
                    [
                        _trade_activity(trade_id="T1"),
                        _trade_activity(trade_id="T2"),
                        _trade_activity(trade_id="T3"),
                    ]
                )
            ]
        )
        assert probe.is_exact_reverse(descending, ascending) is True

    def test_ascending_not_exact_reverse_when_order_differs(self, probe: ModuleType) -> None:
        descending = probe.activity_identities(
            [
                _page(
                    [
                        _trade_activity(trade_id="T3"),
                        _trade_activity(trade_id="T2"),
                        _trade_activity(trade_id="T1"),
                    ]
                )
            ]
        )
        ascending = probe.activity_identities(
            [
                _page(
                    [
                        _trade_activity(trade_id="T2"),
                        _trade_activity(trade_id="T1"),
                        _trade_activity(trade_id="T3"),
                    ]
                )
            ]
        )
        assert probe.is_exact_reverse(descending, ascending) is False


class TestQ2sVerdict:
    def test_stable_when_all_three_checks_hold(self, probe: ModuleType) -> None:
        assert (
            probe.q2s_stability_verdict(
                non_increasing=True, identities_match=True, exact_reverse=True
            )
            == "STABLE"
        )

    @pytest.mark.parametrize(
        ("non_increasing", "identities_match", "exact_reverse"),
        [
            (False, True, True),
            (True, False, True),
            (True, True, False),
        ],
    )
    def test_unstable_when_any_check_fails(
        self, probe: ModuleType, non_increasing: bool, identities_match: bool, exact_reverse: bool
    ) -> None:
        assert (
            probe.q2s_stability_verdict(
                non_increasing=non_increasing,
                identities_match=identities_match,
                exact_reverse=exact_reverse,
            )
            == "UNSTABLE"
        )


# ---------------------------------------------------------------------------
# Positive control
# ---------------------------------------------------------------------------


class TestPositiveControl:
    def test_positive_control_passes_when_a_trade_matches_the_known_id(
        self, probe: ModuleType
    ) -> None:
        pages = [_page([_trade_activity(aggressor_id="CNC3HJD66WP9")])]
        assert probe.positive_control_passed(pages, "CNC3HJD66WP9") is True
        assert probe.positive_control_trade_count(pages, "CNC3HJD66WP9") == 1

    def test_positive_control_fails_when_no_trade_matches(self, probe: ModuleType) -> None:
        pages = [_page([_trade_activity(aggressor_id="SOMEONE-ELSE")])]
        assert probe.positive_control_passed(pages, "CNC3HJD66WP9") is False
        assert probe.positive_control_trade_count(pages, "CNC3HJD66WP9") == 0

    def test_positive_control_fails_on_empty_pages(self, probe: ModuleType) -> None:
        assert probe.positive_control_passed([], "CNC3HJD66WP9") is False


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


class TestRedactSecrets:
    def test_redacts_every_occurrence_of_a_secret(self, probe: ModuleType) -> None:
        text = 'account="ACC-123" other="ACC-123"'
        redacted = probe.redact_secrets(text, ["ACC-123"])
        assert "ACC-123" not in redacted
        assert redacted.count("<REDACTED>") == 2

    def test_redacts_multiple_distinct_secrets(self, probe: ModuleType) -> None:
        text = "key=KEY-1 account=ACC-2"
        redacted = probe.redact_secrets(text, ["KEY-1", "ACC-2"])
        assert "KEY-1" not in redacted
        assert "ACC-2" not in redacted

    def test_ignores_empty_secrets(self, probe: ModuleType) -> None:
        text = "nothing to redact here"
        assert probe.redact_secrets(text, ["", ""]) == text

    def test_leaves_unrelated_text_untouched(self, probe: ModuleType) -> None:
        text = "the order id is CP05MNWMAWP6"
        redacted = probe.redact_secrets(text, ["ACC-123"])
        assert redacted == text


# ---------------------------------------------------------------------------
# Verdict: the decision table, one case per verdict
# ---------------------------------------------------------------------------


def _evidence(probe: ModuleType, **overrides: object):
    defaults = {
        "q1_quantity": 1,
        "q1_cum_quantity": 0,
        "q1_state": "ORDER_STATE_EXPIRED",
        "q2_complete": True,
        "q2_trade_qty_sum": Decimal(0),
        "q2_position_resolution_before_qty": None,
        "q2s_verdict": "STABLE",
        "pc_passed": True,
        "l1_ok": True,
        "any_non_2xx": False,
    }
    defaults.update(overrides)
    return probe.Step0Evidence(**defaults)  # type: ignore[arg-type]


class TestClassifyVerdict:
    def test_fill_when_q2_trade_qty_sums_to_one(self, probe: ModuleType) -> None:
        # Q1 already shows a genuine fill (cum == quantity); Q2's trade
        # evidence corroborates it rather than contradicting a zero GET.
        evidence = _evidence(
            probe,
            q1_quantity=1,
            q1_state="ORDER_STATE_FILLED",
            q1_cum_quantity=1,
            q2_trade_qty_sum=Decimal(1),
        )
        assert probe.classify_verdict(evidence) == probe.VERDICT_FILL

    def test_fill_when_q1_cum_equals_quantity(self, probe: ModuleType) -> None:
        evidence = _evidence(
            probe,
            q1_quantity=1,
            q1_cum_quantity=1,
            q1_state="ORDER_STATE_FILLED",
            q2_trade_qty_sum=Decimal(1),
        )
        assert probe.classify_verdict(evidence) == probe.VERDICT_FILL

    def test_partial_fill_when_q2_trade_qty_sum_is_between_zero_and_one(
        self, probe: ModuleType
    ) -> None:
        # A non-terminal-zero Q1 shape (cum=1, not 0): Q2's own partial
        # trade evidence corroborates rather than contradicts it.
        evidence = _evidence(
            probe,
            q1_quantity=2,
            q1_cum_quantity=1,
            q1_state="ORDER_STATE_PARTIALLY_FILLED",
            q2_trade_qty_sum=Decimal("0.5"),
        )
        assert probe.classify_verdict(evidence) == probe.VERDICT_PARTIAL_FILL

    def test_partial_fill_when_q1_cum_between_zero_and_quantity(self, probe: ModuleType) -> None:
        evidence = _evidence(
            probe,
            q1_quantity=2,
            q1_cum_quantity=1,
            q1_state="ORDER_STATE_PARTIALLY_FILLED",
            q2_trade_qty_sum=Decimal(0),
        )
        assert probe.classify_verdict(evidence) == probe.VERDICT_PARTIAL_FILL

    def test_zero_fill_benign_matches_the_mia_0923_shape(self, probe: ModuleType) -> None:
        evidence = _evidence(
            probe,
            q1_quantity=1,
            q1_cum_quantity=0,
            q1_state="ORDER_STATE_EXPIRED",
            q2_trade_qty_sum=Decimal(0),
            q2_position_resolution_before_qty=None,
            q2s_verdict="STABLE",
            pc_passed=True,
            l1_ok=True,
        )
        assert probe.classify_verdict(evidence) == probe.VERDICT_ZERO_FILL_BENIGN

    def test_contradiction_when_q1_zero_but_q2_has_a_trade(self, probe: ModuleType) -> None:
        evidence = _evidence(
            probe,
            q1_quantity=1,
            q1_cum_quantity=0,
            q1_state="ORDER_STATE_EXPIRED",
            q2_trade_qty_sum=Decimal(1),
        )
        # Both a CONTRADICTION (q1 zero, q2 has a trade) and a FILL
        # (q2 sums to >= 1) condition are literally satisfiable here; the
        # table's own priority order resolves it as CONTRADICTION, since a
        # GET that disagrees with the trade ledger is never silently
        # accepted as a plain fill.
        assert probe.classify_verdict(evidence) == probe.VERDICT_CONTRADICTION

    def test_contradiction_when_q1_fill_but_q2_shows_no_trade(self, probe: ModuleType) -> None:
        evidence = _evidence(
            probe,
            q1_quantity=1,
            q1_cum_quantity=1,
            q1_state="ORDER_STATE_FILLED",
            q2_trade_qty_sum=Decimal(0),
        )
        assert probe.classify_verdict(evidence) == probe.VERDICT_CONTRADICTION

    def test_inconclusive_on_any_non_2xx(self, probe: ModuleType) -> None:
        evidence = _evidence(probe, any_non_2xx=True)
        assert probe.classify_verdict(evidence) == probe.VERDICT_INCONCLUSIVE

    def test_inconclusive_when_q2_is_incomplete(self, probe: ModuleType) -> None:
        evidence = _evidence(probe, q2_complete=False)
        assert probe.classify_verdict(evidence) == probe.VERDICT_INCONCLUSIVE

    def test_inconclusive_when_positive_control_fails(self, probe: ModuleType) -> None:
        evidence = _evidence(probe, pc_passed=False)
        assert probe.classify_verdict(evidence) == probe.VERDICT_INCONCLUSIVE

    def test_inconclusive_when_zero_fill_shape_but_q2s_unstable(self, probe: ModuleType) -> None:
        evidence = _evidence(probe, q2s_verdict="UNSTABLE")
        assert probe.classify_verdict(evidence) == probe.VERDICT_INCONCLUSIVE

    def test_inconclusive_when_zero_fill_shape_but_l1_not_ok(self, probe: ModuleType) -> None:
        evidence = _evidence(probe, l1_ok=False)
        assert probe.classify_verdict(evidence) == probe.VERDICT_INCONCLUSIVE

    def test_inconclusive_when_zero_fill_shape_but_resolution_shows_a_prior_holding(
        self, probe: ModuleType
    ) -> None:
        evidence = _evidence(probe, q2_position_resolution_before_qty=Decimal(5))
        assert probe.classify_verdict(evidence) == probe.VERDICT_INCONCLUSIVE


# ---------------------------------------------------------------------------
# PRIVATE file/dir modes -- no TOCTOU window at a permissive process umask
# ---------------------------------------------------------------------------


class TestPrivateFileModes:
    """Security fix (coordinator round-2 REQUEST_CHANGES): `write_private_file`
    and `make_private_dir` must create files/dirs at mode 0600/0700 AT
    CREATION -- never `write_text`/`mkdir` followed by a separate `chmod`,
    which would leave a TOCTOU window at the process umask. Proven here
    under a deliberately PERMISSIVE umask (0o022, the common default) so a
    process that never calls this module's own `main()` (and therefore
    never narrows the umask to 0o077) still gets private files."""

    @pytest.fixture(autouse=True)
    def _permissive_umask(self):
        previous = os.umask(0o022)
        yield
        os.umask(previous)

    def test_write_private_file_creates_mode_0600_under_a_permissive_umask(
        self, probe: ModuleType, tmp_path: Path
    ) -> None:
        target = tmp_path / "PRIVATE_example.json"
        probe.write_private_file(target, '{"k": "v"}')
        mode = stat.S_IMODE(os.stat(target).st_mode)
        assert mode == 0o600
        assert target.read_text() == '{"k": "v"}'

    def test_write_private_file_overwrite_stays_mode_0600(
        self, probe: ModuleType, tmp_path: Path
    ) -> None:
        target = tmp_path / "PRIVATE_example.json"
        probe.write_private_file(target, "first")
        probe.write_private_file(target, "second")
        mode = stat.S_IMODE(os.stat(target).st_mode)
        assert mode == 0o600
        assert target.read_text() == "second"

    def test_make_private_dir_creates_mode_0700_under_a_permissive_umask(
        self, probe: ModuleType, tmp_path: Path
    ) -> None:
        target = tmp_path / "evidence_dir"
        probe.make_private_dir(target)
        mode = stat.S_IMODE(os.stat(target).st_mode)
        assert mode == 0o700
        assert target.is_dir()

    def test_make_private_dir_creates_missing_parents(
        self, probe: ModuleType, tmp_path: Path
    ) -> None:
        target = tmp_path / "a" / "b" / "evidence_dir"
        probe.make_private_dir(target)
        mode = stat.S_IMODE(os.stat(target).st_mode)
        assert mode == 0o700

    def test_make_private_dir_is_idempotent_on_an_existing_private_dir(
        self, probe: ModuleType, tmp_path: Path
    ) -> None:
        target = tmp_path / "evidence_dir"
        probe.make_private_dir(target)
        probe.make_private_dir(target)  # second call must not raise
        mode = stat.S_IMODE(os.stat(target).st_mode)
        assert mode == 0o700


# ---------------------------------------------------------------------------
# Redaction / safety guards on the module itself
# ---------------------------------------------------------------------------


class TestModuleSafety:
    """Structural guards over the actual AST -- never the module docstring,
    which quotes both forbidden strings verbatim as prose (documenting what
    must never appear in CODE)."""

    @staticmethod
    def _parsed_tree() -> ast.Module:
        source = _SCRIPT_PATH.read_text(encoding="utf-8")
        return ast.parse(source, filename=str(_SCRIPT_PATH))

    def test_module_never_imports_the_exec_package(self, probe: ModuleType) -> None:
        tree = self._parsed_tree()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "exec" in node.module:
                pytest.fail(f"forbidden import: {node.module}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if "exec" in alias.name:
                        pytest.fail(f"forbidden import: {alias.name}")

    def test_module_never_references_account_balances_path_in_code(self, probe: ModuleType) -> None:
        tree = self._parsed_tree()
        docstring_node = None
        if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ):
            docstring_node = tree.body[0].value
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node is docstring_node:
                    continue
                assert "/v1/account/balances" not in node.value
