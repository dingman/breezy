"""Murphy (1973) Brier-score decomposition, plus its exact extension for
coarse binning (SL-7; plan `FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md`
S2 statistics :419-421, build-slice row SL-7 :473).

Pure. No `nautilus_trader` import -- ``breezy.analysis`` is contract-barred
from importing it directly (`pyproject.toml`, "The offline analysis layer
never DIRECTLY imports Nautilus").

**What this implements, precisely.**

For ``N`` events with forecast probability ``p_i`` and binary outcome
``o_i in {0, 1}``, the Brier score is ``BS = (1/N) sum_i (p_i - o_i)^2``.

Grouping the events into bins (``bins`` maps each ``p_i`` to a bin key; every
event sharing a key shares a bin) with per-bin count ``n_k``, mean forecast
``f_k`` and mean observed frequency ``o_k``, and writing ``obar`` for the
overall base rate, the **classic Murphy (1973) decomposition** is::

    BS = REL - RES + UNC
    REL = (1/N) sum_k n_k * (f_k - o_k)^2      (reliability / calibration)
    RES = (1/N) sum_k n_k * (o_k - obar)^2     (resolution / sharpness)
    UNC = obar * (1 - obar)                    (uncertainty / base-rate variance)

This identity is **exact only when every forecast within a bin is
identical** -- i.e. the bin mean ``f_k`` IS every member's actual value, with
no within-bin spread. That is exactly the "exact-reconstruction mode":
``bin_by_value`` puts every DISTINCT forecast value in its own bin, so no bin
ever mixes unequal forecasts.

For coarser bins (several distinct forecast values sharing one bin, e.g.
``bin_by_edges``), the classic formula is only approximate, because ``REL``
compares the bin MEAN ``f_k`` to ``o_k`` rather than each member's own
``p_i``. This module implements the **extended decomposition** (in the shape
of Stephenson, Coelho & Jolliffe 2008, "Two Extra Components in the Brier
Score Decomposition", *Wea. Forecasting* 23:752-757), which adds two
correction terms so the identity holds **exactly regardless of bin
coarseness**::

    BS = REL - RES + UNC + W - C

    W = (1/N) sum_k sum_{i in bin k} (p_i - f_k)^2         (within-bin forecast variance)
    C = (2/N) sum_k sum_{i in bin k} (p_i - f_k)(o_i - o_k) (within-bin forecast/outcome covariance)

Derivation (exact algebra, no approximation): write ``p_i - o_i =
(f_k - o_i) + (p_i - f_k)``, square and sum within each bin. Using
``sum_{i in bin k} (p_i - f_k) = 0`` (the definition of ``f_k`` as the bin
mean) collapses the cross term to ``-2 sum_i (p_i - f_k) o_i``, which reduces
to the covariance term ``C`` above. The remaining ``sum_i (f_k - o_i)^2``
term splits (again exactly, since ``o_i in {0, 1}`` gives
``sum_i (o_i - o_k)^2 = n_k * o_k * (1 - o_k)``) into ``n_k * o_k*(1-o_k) +
n_k*(f_k - o_k)^2``. Summing over bins and dividing by ``N``, the first part
telescopes to ``UNC - RES`` by the standard total-variance identity for a
binary outcome (``sum_i (o_i-obar)^2 = sum_k [n_k*o_k*(1-o_k) +
n_k*(o_k-obar)^2]``), and the second part is exactly ``REL``. Putting the
pieces back together gives ``BS = REL - RES + UNC + W - C`` for ANY binning.

When every bin holds a single distinct forecast value, ``p_i == f_k`` for
every member, so ``W = 0`` and ``C = 0`` identically -- the extended formula
collapses to the classic one, which is why ``bin_by_value`` reconstructs
Brier to floating-point precision with ``within_bin_forecast_variance`` and
``within_bin_covariance`` both ~0.

**On ``UNC`` and six-rung ladders.** ``UNC = obar * (1 - obar)`` is always
computed FROM THE DATA -- ``obar`` is the corpus's measured mean outcome, not
an assumed constant. On a six-rung ladder where each rung independently wins
with EMPIRICAL frequency ``1/6`` in the scored corpus, that measured ``obar``
happens to equal ``1/6`` and ``UNC`` happens to equal ``(1/6)(5/6) = 5/36``.
That ``5/36`` figure is an **empirical property of the event set actually
scored**, not a consequence of "exactly one rung wins per station-day" on its
own -- a corpus where the six rungs win with unequal frequencies (or where
ties/pushes/missing rungs skew the mix) would measure a different ``obar``
and a different ``UNC``, even though exactly one rung still settles per
station-day. This function never assumes ``1/6``; it always measures
``obar`` from the ``outcomes`` it is given.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass

__all__ = [
    "MurphyDecomposition",
    "bin_by_edges",
    "bin_by_value",
    "murphy_decomposition",
    "resolution_difference",
]

#: A bin-key function: maps a forecast probability to any hashable key.
#: Events sharing a key share a bin.
BinKeyFn = Callable[[float], Hashable]


def bin_by_value(probability: float) -> float:
    """Identity bin key -- every DISTINCT forecast value is its own bin.

    Pass this as ``bins`` for the exact-reconstruction mode: the classic
    Murphy decomposition (``REL - RES + UNC``) reconstructs the Brier score
    to floating-point precision, because no bin ever mixes unequal forecast
    values.
    """
    return probability


def bin_by_edges(edges: Sequence[float]) -> BinKeyFn:
    """Return a bin-key function for coarse, fixed-edge binning.

    ``edges`` is a strictly ascending sequence of ``K + 1`` boundaries
    defining ``K`` bins. A probability ``p`` falls in bin ``i`` when
    ``edges[i] <= p < edges[i + 1]``, except the LAST bin, which is
    right-closed (``p == edges[-1]`` belongs to the last bin) -- the same
    convention `scripts/analysis/forecast_conditional_scoring.py:139-162`
    (`reliability`) uses for its buckets.

    Raises `ValueError` for fewer than two edges, non-ascending edges, or a
    probability outside ``[edges[0], edges[-1]]`` at call time.
    """
    if len(edges) < 2:
        raise ValueError("bin_by_edges needs at least two edges (one bin)")
    ordered = tuple(edges)
    if list(ordered) != sorted(ordered):
        raise ValueError(f"bin edges must be strictly ascending, got {ordered!r}")

    def _key(probability: float) -> int:
        last = len(ordered) - 2
        for index in range(len(ordered) - 1):
            lower, upper = ordered[index], ordered[index + 1]
            if lower <= probability < upper or (index == last and probability == upper):
                return index
        raise ValueError(f"{probability!r} is outside the bin edges {ordered!r}")

    return _key


@dataclass(frozen=True, slots=True)
class MurphyDecomposition:
    """One decomposition result: `Brier = reliability - resolution +
    uncertainty + within_bin_forecast_variance - within_bin_covariance`.

    `brier` is computed DIRECTLY from the raw `(probs, outcomes)` pairs, not
    reconstructed from the other fields -- `reconstructed_brier` is the sum
    of the other five fields, provided so a caller (or a test) can compare
    the two independently.
    """

    reliability: float
    resolution: float
    uncertainty: float
    brier: float
    within_bin_forecast_variance: float
    within_bin_covariance: float

    @property
    def reconstructed_brier(self) -> float:
        """`REL - RES + UNC + W - C`, which equals `brier` exactly (module
        docstring derivation) for any binning, including coarse ones."""
        return (
            self.reliability
            - self.resolution
            + self.uncertainty
            + self.within_bin_forecast_variance
            - self.within_bin_covariance
        )


def _validate_matched_lengths(probs: Sequence[float], outcomes: Sequence[bool]) -> None:
    if len(probs) != len(outcomes):
        raise ValueError(
            f"probs has {len(probs)} entries but outcomes has {len(outcomes)} -- "
            "murphy_decomposition needs one outcome per forecast"
        )
    if not probs:
        raise ValueError("murphy_decomposition of an empty forecast set is undefined")


def murphy_decomposition(
    probs: Sequence[float], outcomes: Sequence[bool], bins: BinKeyFn
) -> MurphyDecomposition:
    """The Murphy decomposition of `(probs, outcomes)`, binned by `bins`.

    `bins` maps each forecast probability to a bin key (any hashable);
    events sharing a key share a bin. Pass `bin_by_value` for the
    exact-reconstruction mode, or `bin_by_edges(edges)` for coarse,
    fixed-width bins -- see the module docstring for the exact identity this
    returns in each case.

    Raises `ValueError` if `probs` and `outcomes` have different lengths, or
    if both are empty.
    """
    _validate_matched_lengths(probs, outcomes)
    n = len(probs)

    grouped: dict[Hashable, list[int]] = {}
    for index, probability in enumerate(probs):
        grouped.setdefault(bins(probability), []).append(index)

    overall_mean_outcome = sum(float(outcome) for outcome in outcomes) / n
    uncertainty = overall_mean_outcome * (1.0 - overall_mean_outcome)

    reliability_sum = 0.0
    resolution_sum = 0.0
    variance_sum = 0.0
    covariance_sum = 0.0
    for indices in grouped.values():
        bin_size = len(indices)
        bin_probs = [probs[i] for i in indices]
        bin_outcomes = [float(outcomes[i]) for i in indices]
        mean_forecast = sum(bin_probs) / bin_size
        mean_observed = sum(bin_outcomes) / bin_size

        reliability_sum += bin_size * (mean_forecast - mean_observed) ** 2
        resolution_sum += bin_size * (mean_observed - overall_mean_outcome) ** 2
        variance_sum += sum((p - mean_forecast) ** 2 for p in bin_probs)
        covariance_sum += sum(
            (p - mean_forecast) * (o - mean_observed)
            for p, o in zip(bin_probs, bin_outcomes, strict=True)
        )

    brier = sum((p - float(o)) ** 2 for p, o in zip(probs, outcomes, strict=True)) / n

    return MurphyDecomposition(
        reliability=reliability_sum / n,
        resolution=resolution_sum / n,
        uncertainty=uncertainty,
        brier=brier,
        within_bin_forecast_variance=variance_sum / n,
        within_bin_covariance=2.0 * covariance_sum / n,
    )


def resolution_difference(
    probs_a: Sequence[float],
    probs_b: Sequence[float],
    outcomes: Sequence[bool],
    bins: BinKeyFn,
) -> float:
    """`D_res = RES_a - RES_b` on matched events (plan gates G2.2, G2.3).

    `probs_a`, `probs_b` and `outcomes` must be the SAME length -- one
    forecast from each system, plus one outcome, per matched event.
    Antisymmetric by construction: `resolution_difference(a, b, ...) ==
    -resolution_difference(b, a, ...)`.

    Point estimate only -- rung events within a station-day are mutually
    exclusive and negatively correlated; any CI must use the station-day
    cluster bootstrap, never a naive per-event CI.

    Raises `ValueError` if the three sequences are not all the same length.
    """
    if not (len(probs_a) == len(probs_b) == len(outcomes)):
        raise ValueError(
            "resolution_difference needs matched lengths: "
            f"probs_a={len(probs_a)}, probs_b={len(probs_b)}, outcomes={len(outcomes)}"
        )
    resolution_a = murphy_decomposition(probs_a, outcomes, bins).resolution
    resolution_b = murphy_decomposition(probs_b, outcomes, bins).resolution
    return resolution_a - resolution_b
