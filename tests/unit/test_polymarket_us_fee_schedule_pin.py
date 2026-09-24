"""Capture pin: declared taker theta, tracked wire corpus, adapter constant, sites.

This module is the single link between the venue's documented taker coefficient
and every in-scope pin site. It does not retune a running family. The pinned
value is ``Decimal("0.06")``. The 2026-09-17 wire move to 0.0695 is recorded
in the evidence note, never "fixed" here.

SPLIT READ (binding): ``scripts/analysis/*.py`` theta sites are read by
``ast.parse`` of the file text -- module-level ``Assign`` / ``AnnAssign``
whose value is ``Decimal("...")`` or a numeric literal. This module must NOT
import any ``scripts/`` module. The two ``src/`` config sites
(``CurrentRungHoldConfig().required_fee_coefficient``,
``LadderEvConfig().required_fee_coefficient``) are read by normal package
import. The adapter constant is the public name this file imports.

CORPUS REFRESH POLICY: the wire-theta exact-set is keyed by capture date.
The tracked raw corpus is the 2026-08-25 SHA256SUMS snapshot:

    {("2026-08-25", Decimal("0.06"))}

Do not copy the 2026-09-17 runtime tape or recorder definitions into
``docs/evidence`` in this item; that is a separate evidence-capture step.
A new capture date is a new member of the exact-set, added in the same
commit that vendors the payloads -- widen, never relax ``==``.

NAMED-ONLY, NOT ASSERTED: ``scripts/analysis/k1_cheap_open_settlement.py:1450``
is an inline fallback (``Decimal("0.06")`` when the population's thetas are
not unique), not a module-level declaration. Test-side theta copies are out
of scope by construction -- a fixture literal is not a declaration.

Maker rebate ``MAKER_FEE_COEFFICIENT`` is a different coefficient; this census
must not fuse it with taker theta.

Cited, not rewritten: the parser mirror
``info[fee_coefficient] -> maker_fee/taker_fee`` is already pinned by
``test_the_flat_fee_fields_carry_theta_not_a_zero_and_not_a_notional_rate``
and ``test_the_flat_fields_are_theta_itself_and_not_a_notional_rate`` in
``tests/unit/test_polymarket_us_parsing.py`` (``parsing.py:1460-1461,1537-1538``).
Refusal coverage cited GREEN, not rewritten:
``test_current_rung_hold_decision.py`` (drifted),
``TestFeeScheduleGuard`` in ``test_current_rung_hold_strategy.py:534-569``
(absent), ``test_weather_common_risk.py:2120,2132``.

WP-0d's "capture-test extend" was read as "reuse the existing drift-capture
PATTERN", not "edit ``test_polymarket_us_fee_coefficient_source.py``" (which
importlib-loads a script at import time at ``:61``).
"""

from __future__ import annotations

import ast
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from breezy.adapters.polymarket_us.fees import DOCUMENTED_TAKER_FEE_COEFFICIENT
from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.continuous_strategy import (
    ContinuousRungHoldStrategy,
)
from breezy.strategy.current_rung_hold.strategy import CurrentRungHoldStrategy
from breezy.strategy.ladder_ev.config import LadderEvConfig
from tests.unit.conftest import MIN_CAPTURED_MARKETS, iter_captured_market_payloads

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us"
SNAPSHOT_PATH = EVIDENCE / "docs_snapshots" / "fees_2026-08-25.md"
ANALYSIS_DIR = REPO_ROOT / "scripts" / "analysis"
RAW_MARKET = EVIDENCE / "raw" / "market_open_510636_by_slug.json"
TS_INIT = 1_787_617_213_000_000_000

TRACKED_CORPUS_CAPTURE_DATE = "2026-08-25"

WIRE_THETA_BY_CAPTURE_DATE: frozenset[tuple[str, Decimal]] = frozenset(
    {
        (TRACKED_CORPUS_CAPTURE_DATE, Decimal("0.06")),
    }
)

# Venue-keyed exact-set of module-level study-script theta declarations.
# Widen in the same commit that adds a site; never relax ``==``.
STUDY_THETA_BY_VENUE: frozenset[tuple[str, str, str, Decimal]] = frozenset(
    {
        ("polymarket_us", "band_decider_stage0b_screen", "THETA", Decimal("0.06")),
        (
            "polymarket_us",
            "price_conditional_settlement_analysis",
            "DEFAULT_THETA",
            Decimal("0.06"),
        ),
        (
            "polymarket_us",
            "crh_group_sequential_boundaries",
            "DRIFT_FEE_THETA",
            Decimal("0.06"),
        ),
        ("polymarket_us", "mb_current_rung_edge_study", "FEE_THETA", Decimal("0.06")),
        (
            "polymarket_us",
            "resting_bid_core",
            "TAKER_FEE_COEFFICIENT",
            Decimal("0.06"),
        ),
        # HUNT-2. The ONLY study site carrying the post-drift coefficient the
        # venue has actually charged since 2026-09-17. It is deliberately
        # visible here and deliberately NOT 0.06: an ask-relative edge measured
        # against the superseded coefficient would understate the hurdle by
        # ~16% and could manufacture an hour that looks tradeable. This entry
        # registers a STUDY site; it neither is nor touches
        # `DOCUMENTED_TAKER_FEE_COEFFICIENT`, which stays pinned at 0.06.
        (
            "polymarket_us",
            "hourly_ask_relative_edge",
            "TAKER_FEE_COEFFICIENT",
            Decimal("0.0695"),
        ),
        ("kalshi", "k1_kalshi_prior", "KALSHI_TAKER_THETA", Decimal("0.07")),
    }
)

_TAKER_FEE_THETA = re.compile(
    r"\*\*Taker Fee\*\*[^\n]*\|\s*([0-9]+(?:\.[0-9]+)?)",
)
_THETA_NAME = re.compile(r"(?i)(theta|taker_fee_coefficient)$")


def declared_theta_from_snapshot(text: str) -> Decimal:
    """Theta cell of the snapshot's Taker Fee row, not a later dollar amount."""
    match = _TAKER_FEE_THETA.search(text)
    if match is None:
        raise AssertionError("fees snapshot has no **Taker Fee** theta cell")
    return Decimal(match.group(1))


def wire_thetas_from_raw(
    payloads: list[dict[str, Any]] | None = None,
    *,
    capture_date: str = TRACKED_CORPUS_CAPTURE_DATE,
) -> frozenset[tuple[str, Decimal]]:
    """Capture-date-keyed exact-set of ``feeCoefficient`` on captured markets."""
    if payloads is None:
        payloads = iter_captured_market_payloads()
    found: set[tuple[str, Decimal]] = set()
    for envelope in payloads:
        raw = envelope["market"].get("feeCoefficient")
        if raw is None:
            continue
        found.add((capture_date, Decimal(str(raw))))
    return frozenset(found)


def _literal_decimal(node: ast.AST) -> Decimal | None:
    if isinstance(node, ast.Call):
        func = node.func
        name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None
        )
        if name == "Decimal" and node.args:
            arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return Decimal(arg.value)
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return Decimal(str(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _literal_decimal(node.operand)
        return None if inner is None else -inner
    return None


def _module_level_bindings(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    found: list[tuple[str, ast.AST]] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    found.append((target.id, stmt.value))
        elif (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.value is not None
        ):
            found.append((stmt.target.id, stmt.value))
    return found


def _venue_for_module(stem: str) -> str:
    return "kalshi" if "kalshi" in stem.lower() else "polymarket_us"


def study_theta_sites_from_source(
    source: str, *, module_stem: str
) -> frozenset[tuple[str, str, str, Decimal]]:
    """Module-level theta declarations in one file. Never imports the module."""
    tree = ast.parse(source)
    venue = _venue_for_module(module_stem)
    found: set[tuple[str, str, str, Decimal]] = set()
    for name, value in _module_level_bindings(tree):
        if not _THETA_NAME.search(name):
            continue
        theta = _literal_decimal(value)
        if theta is None:
            continue
        found.add((venue, module_stem, name, theta))
    return frozenset(found)


def study_theta_sites_from_analysis_scripts(
    analysis_dir: Path = ANALYSIS_DIR,
) -> frozenset[tuple[str, str, str, Decimal]]:
    found: set[tuple[str, str, str, Decimal]] = set()
    for path in sorted(analysis_dir.glob("*.py")):
        found |= study_theta_sites_from_source(
            path.read_text(encoding="utf-8"), module_stem=path.stem
        )
    return frozenset(found)


def test_the_documented_taker_theta_is_a_public_declared_constant() -> None:
    import breezy.adapters.polymarket_us.fees as fees_mod

    assert DOCUMENTED_TAKER_FEE_COEFFICIENT == Decimal("0.06")
    assert "DOCUMENTED_TAKER_FEE_COEFFICIENT" in fees_mod.__all__
    assert not hasattr(fees_mod, "_DOCUMENTED_TAKER_FEE_COEFFICIENT")


def test_the_declared_theta_matches_the_snapshot_and_every_captured_payload() -> None:
    snapshot = SNAPSHOT_PATH.read_text(encoding="utf-8")
    assert declared_theta_from_snapshot(snapshot) == DOCUMENTED_TAKER_FEE_COEFFICIENT

    payloads = iter_captured_market_payloads()
    assert len(payloads) >= MIN_CAPTURED_MARKETS
    assert wire_thetas_from_raw(payloads) == WIRE_THETA_BY_CAPTURE_DATE


def test_every_in_scope_theta_site_agrees_with_its_venue_constant() -> None:
    extracted = study_theta_sites_from_analysis_scripts()
    added = extracted - STUDY_THETA_BY_VENUE
    missing = STUDY_THETA_BY_VENUE - extracted
    assert extracted == STUDY_THETA_BY_VENUE, (
        f"study theta census drifted; added={sorted(added)!r} "
        f"missing={sorted(missing)!r}"
    )

    crh = Decimal(str(CurrentRungHoldConfig().required_fee_coefficient))
    ladder = Decimal(str(LadderEvConfig().required_fee_coefficient))
    assert crh == DOCUMENTED_TAKER_FEE_COEFFICIENT
    assert ladder == DOCUMENTED_TAKER_FEE_COEFFICIENT


def _known_and_unknown_from_the_same_fixture() -> tuple[Any, Any]:
    payload = json.loads(RAW_MARKET.read_text(encoding="utf-8"))
    known = parse_binary_option(payload, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)
    missing = json.loads(RAW_MARKET.read_text(encoding="utf-8"))
    del missing["market"]["feeCoefficient"]
    unknown = parse_binary_option(missing, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)
    return known, unknown


def test_both_guard_copies_return_none_on_unknown_and_maker_fee_on_known() -> None:
    """Parity pin for the two independent ``_guarded_fee_coefficient`` copies.

    Read-only on ``strategy.py:708`` and ``continuous_strategy.py:2451``.
    Neither copy is refactored.
    """
    known, unknown = _known_and_unknown_from_the_same_fixture()
    owners: tuple[type[Any], ...] = (
        CurrentRungHoldStrategy,
        ContinuousRungHoldStrategy,
    )
    for owner in owners:
        method: Any = owner.__dict__["_guarded_fee_coefficient"]
        assert method(None, unknown) is None
        assert method(None, known) == known.maker_fee


# AUD-13b (plan §7 13b step 1d, §8 item 18): the dated reconciliation fee
# schedule is declared ONLY in `fees.py`. `STUDY_THETA_BY_VENUE` and
# `test_every_in_scope_theta_site_agrees_with_its_venue_constant` above are
# untouched: this is a SEPARATE, src-scoped expected set over the same
# scanner, never a widening of the study-script census.
SRC_FEES_PATH = REPO_ROOT / "src" / "breezy" / "adapters" / "polymarket_us" / "fees.py"
SRC_EXEC_CLIENT_PATH = (
    REPO_ROOT / "src" / "breezy" / "adapters" / "polymarket_us" / "exec" / "client.py"
)
SRC_FEE_SCHEDULE_THETA_SITES: frozenset[tuple[str, str, str, Decimal]] = frozenset(
    {
        ("polymarket_us", "fees", "DOCUMENTED_TAKER_FEE_COEFFICIENT", Decimal("0.06")),
        # Enumerated, dated exception: the post-drift taker theta the venue has
        # charged since 2026-09-17T17:00:00Z, evidenced by
        # docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md
        # (first drift alert 17:00:00.610319588Z; all six 2026-09-17 offer-tape
        # rows `fee_coefficient="0.0695"`). Used ONLY by reconciliation's
        # as-of-fill-time resolver; `DOCUMENTED_TAKER_FEE_COEFFICIENT` stays 0.06.
        ("polymarket_us", "fees", "_POST_DRIFT_TAKER_FEE_COEFFICIENT", Decimal("0.0695")),
    }
)


def test_the_dated_fee_schedule_is_declared_only_in_fees_py() -> None:
    fees_sites = study_theta_sites_from_source(
        SRC_FEES_PATH.read_text(encoding="utf-8"), module_stem="fees"
    )
    added = fees_sites - SRC_FEE_SCHEDULE_THETA_SITES
    missing = SRC_FEE_SCHEDULE_THETA_SITES - fees_sites
    assert fees_sites == SRC_FEE_SCHEDULE_THETA_SITES, (
        f"fees.py theta census drifted; added={sorted(added)!r} missing={sorted(missing)!r}"
    )
    client_sites = study_theta_sites_from_source(
        SRC_EXEC_CLIENT_PATH.read_text(encoding="utf-8"), module_stem="client"
    )
    assert client_sites == frozenset(), client_sites
