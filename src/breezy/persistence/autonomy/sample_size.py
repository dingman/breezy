"""One-sided normal-approximation sample-size primitives (AUT-4 r11 RC-1, K2).

The single definition of the MDE, power and ``n_min`` arithmetic that AUT-4's evaluators, the
nomination columns and ``hypothesis_ledger.recompute_mde`` share. Lifted from
``recompute_mde`` with sigma as a parameter; stdlib only (``statistics.NormalDist`` and ``math``).

Never redefine any name here elsewhere (``test_sample_size_primitives_single_definition``).
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Final

#: Design power of every AUT-4 test (``hypothesis_ledger.POWER``).
DESIGN_POWER: Final[float] = 0.80
#: Cluster-count floor factor: ``c_min(alpha) = ceil(log2(CLUSTER_FLOOR_FACTOR / alpha))``.
CLUSTER_FLOOR_FACTOR: Final[int] = 10
#: ``n_min_eff`` never falls below this many observations per cluster-floor unit.
CLUSTERS_PER_FLOOR_UNIT: Final[int] = 4


def _z_sum(alpha: float, power: float) -> float:
    normal = NormalDist()
    return float(normal.inv_cdf(1.0 - alpha) + normal.inv_cdf(power))


def mde_one_sided(sigma: float, n: int, alpha: float, power: float = DESIGN_POWER) -> float:
    """Minimum detectable effect at ``n`` units: ``(z(1-alpha)+z(power))*sigma/sqrt(n)``.

    The operation order is that of ``recompute_mde``, so the result is bit-identical to it at
    ``sigma = sqrt(0.25)``.
    """
    if n <= 0:
        raise ValueError(f"mde_one_sided is undefined for n <= 0, was {n!r}")
    if sigma <= 0.0:
        raise ValueError(f"sigma must be positive, was {sigma!r}")
    return float(_z_sum(alpha, power) * float(sigma) / (float(n) ** 0.5))


def n_min_one_sided(sigma: float, mde: float, alpha: float, power: float = DESIGN_POWER) -> int:
    """Smallest integer ``n`` with ``mde_one_sided(sigma, n, alpha, power) <= mde``."""
    if sigma <= 0.0:
        raise ValueError(f"sigma must be positive, was {sigma!r}")
    if mde <= 0.0:
        raise ValueError(f"mde must be positive, was {mde!r}")
    return math.ceil((_z_sum(alpha, power) * float(sigma) / float(mde)) ** 2)


def power_one_sided(sigma: float, n: int, alpha: float, delta: float) -> float:
    """Power of the one-sided level-``alpha`` test at true effect ``delta`` and ``n`` units."""
    if n <= 0:
        raise ValueError(f"power_one_sided is undefined for n <= 0, was {n!r}")
    if sigma <= 0.0:
        raise ValueError(f"sigma must be positive, was {sigma!r}")
    normal = NormalDist()
    return float(normal.cdf(delta * math.sqrt(n) / sigma - normal.inv_cdf(1.0 - alpha)))


def c_min(alpha: float) -> int:
    """Smallest cluster count the date-cluster permutation test may run on at level ``alpha``."""
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must lie in (0, 1), was {alpha!r}")
    return math.ceil(math.log2(CLUSTER_FLOOR_FACTOR / alpha))


def deff(m_bar: float, rho: float) -> float:
    """Design effect ``1 + (m_bar - 1) * rho`` for mean cluster size ``m_bar`` and ICC ``rho``."""
    return 1.0 + (float(m_bar) - 1.0) * float(rho)


def n_min_eff(n_min: int, deff: float, c_min: int) -> int:
    """``max(ceil(deff * n_min), 4 * c_min)``: ``n_min`` inflated for clustering, floored."""
    return max(math.ceil(float(deff) * n_min), CLUSTERS_PER_FLOOR_UNIT * c_min)
