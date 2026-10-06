"""F7b-core: the KILL test (`analysis/autonomy/confidence_sequence.py`), E-25 rule 3.

F7B-R10 / R22: the validity argument rests on the m = 0 capital `prod(1 - lam (Y - 0))`, a
supermartingale under the NO-LOSS null E[Y | F] >= 0, so false-KILL <= alpha_kill / 2; the other
grid points only add conservatism. Under the PASS null (E[Y] <= 0) the capital grows and KILL is
intended. F7B-R21: BSS-on-takes compares against the RAW executable ask.
"""

from __future__ import annotations

import ast
import itertools
import math
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Final

import pytest

from breezy.analysis.autonomy import confidence_sequence as cs
from breezy.analysis.autonomy.confidence_sequence import (
    KILL_GRID_POINTS,
    TakeScore,
    bss_on_takes,
    kill_bar,
    kill_crossed,
    kill_first_n,
    kill_log_capitals,
)
from tests.support.fq_eprocess_fixtures import climate_day
from tests.support.fq_mc_reference_vectors import REFERENCE

SRC: Final = Path(__file__).resolve().parents[3] / "src/breezy/analysis/autonomy"
CS_SRC: Final = SRC / "confidence_sequence.py"
X_MAX: Final = 4.0
ALPHA_KILL: Final = 0.05


def test_kill_constants_are_the_mc_constants() -> None:
    assert KILL_GRID_POINTS == 5
    assert kill_bar(0.05) == math.log(2.0 / 0.05)
    assert kill_bar(Decimal("0.05")) == kill_bar(0.05)  # converted once
    for bad in (0.0, 1.0, -0.1, 2.0):
        with pytest.raises(ValueError, match="alpha_kill"):
            kill_bar(bad)


def test_module_docstring_states_the_m0_supermartingale_argument() -> None:
    doc = " ".join((cs.__doc__ or "").split())
    for phrase in ("m = 0", "supermartingale", "no-loss null", "alpha_kill / 2", "conservatism"):
        assert phrase in doc, phrase
    assert "UB < 0" not in doc.replace("never claims", "")  # the withdrawn wording is not claimed


@pytest.mark.parametrize("key", ["A_m2", "A_m3", "B_m2"])
def test_kill_matches_f5_mc_reference_on_shared_fixtures(key: str) -> None:
    ref = REFERENCE[key]
    caps = kill_log_capitals(ref["y"], x_max=X_MAX)
    assert len(caps) == len(ref["y"])
    for got_row, want_row in zip(caps, ref["log_k"], strict=True):
        assert len(got_row) == KILL_GRID_POINTS
        assert all(
            math.isclose(g, w, rel_tol=1e-12, abs_tol=1e-15)
            for g, w in zip(got_row, want_row, strict=True)
        )
    elo = ref["earliest_look_n"]
    got = kill_first_n(
        ref["y"], ref["n_cum"], x_max=X_MAX, alpha_kill=ALPHA_KILL, earliest_look_n=elo
    )
    assert got == (None if ref["kill_first_n"] < 0 else ref["kill_first_n"])
    assert key != "B_m2" or got == 78


def test_cs_reject_only_when_ub_lt_0() -> None:
    """KILL needs EVERY grid capital at the bar (the m = 0 point decides validity; the rest only
    add conservatism)."""
    bar = kill_bar(ALPHA_KILL)
    assert kill_crossed((bar,) * KILL_GRID_POINTS, bar)
    assert not kill_crossed((bar + 5.0, bar + 5.0, bar + 5.0, bar + 5.0, bar - 1e-9), bar)
    assert not kill_crossed((bar - 1e-9, bar + 5.0, bar + 5.0, bar + 5.0, bar + 5.0), bar)
    assert not kill_crossed((), bar)


def test_kill_boundary_log_space() -> None:
    bar = kill_bar(0.05)
    assert kill_crossed((bar,) * 5, bar)
    assert not kill_crossed((math.nextafter(bar, 0.0),) * 5, bar)


def test_kill_respects_earliest_look_n() -> None:
    ys = [-1.0] * 60
    n_cum = [2 * (i + 1) for i in range(60)]
    early = kill_first_n(ys, n_cum, x_max=X_MAX, alpha_kill=ALPHA_KILL, earliest_look_n=1)
    late = kill_first_n(ys, n_cum, x_max=X_MAX, alpha_kill=ALPHA_KILL, earliest_look_n=100)
    assert early is not None and early >= 2
    assert late is not None and late >= 100
    assert kill_first_n([], [], x_max=X_MAX, alpha_kill=ALPHA_KILL, earliest_look_n=1) is None
    with pytest.raises(ValueError, match="length"):
        kill_first_n([0.0], [1, 2], x_max=X_MAX, alpha_kill=ALPHA_KILL, earliest_look_n=1)


def test_kill_cs_uses_clipped_haircut_y() -> None:
    """The input is the clipped, haircut-BE Y_d produced by the e-process core, nothing else."""
    from breezy.analysis.autonomy.eprocess import EProcessDesign, build_day_stats
    from tests.support.fq_eprocess_fixtures import FIXTURE_A, FIXTURE_A_DAYS
    from tests.unit.autonomy.test_eprocess import takes_of

    d = EProcessDesign(m_cap=2, x_max=X_MAX, lambda_max=0.5, mu_max=0.5, earliest_look_n=3)
    stats = build_day_stats(
        takes_of(FIXTURE_A),
        covered_days=frozenset(climate_day(i) for i in range(FIXTURE_A_DAYS)),
        first_day=climate_day(0),
        last_settled_day=climate_day(FIXTURE_A_DAYS - 1),
        design=d,
    )
    ys = [s.y for s in stats]
    assert max(ys) <= X_MAX  # the clip is already applied (day 4: be .169 would be 4.9 unclipped)
    got = kill_log_capitals(ys, x_max=X_MAX)
    want = REFERENCE["A_m2"]["log_k"]
    assert all(
        math.isclose(g, w, rel_tol=1e-12, abs_tol=1e-15)
        for gr, wr in zip(got, want, strict=True)
        for g, w in zip(gr, wr, strict=True)
    )


def test_alpha_kill_pinned_separately_never_charged() -> None:
    import inspect

    params = inspect.signature(kill_first_n).parameters
    assert params["alpha_kill"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["alpha_kill"].default is inspect.Parameter.empty  # no hidden default
    tree = ast.parse(CS_SRC.read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {a.arg for n in ast.walk(tree) if isinstance(n, ast.arguments) for a in n.args}
    assert "alpha_spent" not in names  # no field or variable ever charges it


def test_cs_range_normalised_kill_side_lambda_usable() -> None:
    """The per-m cap keeps 1 - lam (Y - m) > 0 for every Y in [-1, X_max] and every grid m."""
    ys_extreme = [-1.0, 4.0, 0.0, 4.0, -1.0, -1.0, 4.0]
    for scale in (1.0, 0.5):
        caps = kill_log_capitals([y * scale for y in ys_extreme] * 10, x_max=X_MAX)
        assert all(math.isfinite(v) for row in caps for v in row)


def test_enumeration_m0_capital_is_a_supermartingale_at_zero_edge() -> None:
    """F7B-R22: at E[Y] = 0 the m = 0 capital has expectation <= 1 (exact over a Bernoulli tree)."""
    q = Fraction(1, 4)  # be = 1/4 -> X = 3 or -1, E[X] = 0
    days = 4
    total = Fraction(0)
    for path in itertools.product((0, 1), repeat=days * 2):
        w = Fraction(1)
        ys = []
        for d in range(days):
            hs = path[2 * d : 2 * d + 2]
            for h in hs:
                w *= q if h else 1 - q
            ys.append(sum(3.0 if h else -1.0 for h in hs) / 2)
        total += w * Fraction(math.exp(kill_log_capitals(ys, x_max=X_MAX)[-1][0]))
    assert total <= 1 + Fraction(1, 10**9)


def test_mutation_future_betting_breaks_the_m0_supermartingale() -> None:
    """MUTATION: a capital whose bet may see today's Y exceeds 1 in expectation at the null."""
    q = Fraction(1, 4)
    total = Fraction(0)
    for hs in itertools.product((0, 1), repeat=6):
        w = Fraction(1)
        log_cap = 0.0
        for k in range(0, 6, 2):
            pair = hs[k : k + 2]
            for h in pair:
                w *= q if h else 1 - q
            y = sum(3.0 if h else -1.0 for h in pair) / 2
            lam = 0.5 if y < 0 else 0.0  # bets on E[Y] < 0 only when it has seen Y < 0
            log_cap += math.log1p(-lam * y)
        total += w * Fraction(math.exp(log_cap))
    assert total > 1 + Fraction(1, 100)


# ---------------------------------------------------------------- BSS on takes (diagnostic)


def _scores() -> list[TakeScore]:
    return [
        TakeScore(climate_day(0), 0.30, 0.45, 1),
        TakeScore(climate_day(0), 0.30, 0.20, 0),
        TakeScore(climate_day(1), 0.50, 0.65, 1),
        TakeScore(climate_day(2), 0.40, 0.35, 0),
        TakeScore(climate_day(3), 0.60, 0.70, 1),
        TakeScore(climate_day(4), 0.55, 0.30, 0),
    ]


def test_bss_on_takes_uses_ask_comparator() -> None:
    scores = _scores()
    num = sum((s.p_model - s.h) ** 2 for s in scores)
    den = sum((s.raw_ask - s.h) ** 2 for s in scores)
    got = bss_on_takes(scores, iterations=50)
    assert math.isclose(got.point or 0.0, 1 - num / den, rel_tol=1e-12)
    # the haircut BE is not an input at all: the score type carries only the RAW ask
    assert set(TakeScore.__dataclass_fields__) == {"climate_day", "raw_ask", "p_model", "h"}


def test_bss_undefined_when_the_comparator_is_perfect() -> None:
    perfect = [TakeScore(climate_day(0), 1.0, 0.5, 1), TakeScore(climate_day(1), 0.0, 0.5, 0)]
    got = bss_on_takes(perfect, iterations=10)
    assert got.point is None and got.low is None and got.high is None
    assert bss_on_takes([], iterations=10).point is None


def test_bootstrap_clusters_by_calendar_day() -> None:
    scores = _scores()
    got = bss_on_takes(scores, iterations=200)
    assert got.cluster == "date"
    assert got.n_clusters == 5  # six takes on five calendar days
    assert got.low is not None and got.high is not None and got.low <= got.high
    assert score_cluster_keys(scores) == {climate_day(i) for i in range(5)}
    with pytest.raises(ValueError, match="cluster"):
        scores[0].cluster_key("station")


def score_cluster_keys(scores: list[TakeScore]) -> set[object]:
    return {s.cluster_key("date") for s in scores}


def test_bss_is_diagnostic_only() -> None:
    text = CS_SRC.read_text(encoding="utf-8")
    assert "diagnostic" in text.lower()
