"""AUT-2 r7 WP3 / section 3.4.4: the bought leg's win probability and its source.

``p_hat`` is P(YES rung) in both side modes, so a NO buy's probability is ``1 - p_hat``. A take
whose side disagrees with the fill's leg is unmatched, never guessed.
"""

from __future__ import annotations

import pytest

from breezy.analysis.labeling.probability import (
    BoughtLegP,
    LegMismatch,
    artefact_p_raw,
    bought_leg_probabilities,
)


def test_p_at_decision_is_bought_leg_probability() -> None:
    yes = bought_leg_probabilities(p_hat="0.62", p_hat_raw="0.60", side="yes", leg="yes")
    no = bought_leg_probabilities(p_hat="0.62", p_hat_raw="0.60", side="no", leg="no")

    assert isinstance(yes, BoughtLegP) and isinstance(no, BoughtLegP)
    assert yes.p_at_decision == pytest.approx(0.62)
    assert no.p_at_decision == pytest.approx(0.38)


def test_p_raw_at_decision_is_bought_leg_raw_probability() -> None:
    yes = bought_leg_probabilities(p_hat="0.62", p_hat_raw="0.60", side="yes", leg="yes")
    no = bought_leg_probabilities(p_hat="0.62", p_hat_raw="0.60", side="no", leg="no")
    unknown_raw = bought_leg_probabilities(p_hat="0.62", p_hat_raw="", side="no", leg="no")

    assert isinstance(yes, BoughtLegP) and isinstance(no, BoughtLegP)
    assert yes.p_raw_at_decision == pytest.approx(0.60)
    assert no.p_raw_at_decision == pytest.approx(0.40)
    assert isinstance(unknown_raw, BoughtLegP) and unknown_raw.p_raw_at_decision is None


def test_artefact_recompute_p_raw_equals_p_only_when_recalibration_none() -> None:
    assert artefact_p_raw(0.37, recalibration="none") == pytest.approx(0.37)
    assert artefact_p_raw(0.37, recalibration="isotonic") is None
    assert artefact_p_raw(0.37, recalibration=None) is None


@pytest.mark.parametrize(("side", "leg"), [("yes", "no"), ("no", "yes")])
def test_take_side_disagreeing_with_fill_leg_unmatched(side: str, leg: str) -> None:
    result = bought_leg_probabilities(p_hat="0.62", p_hat_raw="0.60", side=side, leg=leg)

    assert isinstance(result, LegMismatch)
    assert (result.side, result.leg) == (side, leg)


@pytest.mark.parametrize("bad", ["", "nan", "1.5", "-0.1", "abc"])
def test_an_unusable_p_hat_is_refused_not_coerced(bad: str) -> None:
    with pytest.raises(ValueError, match="p_hat"):
        bought_leg_probabilities(p_hat=bad, p_hat_raw="0.5", side="yes", leg="yes")
