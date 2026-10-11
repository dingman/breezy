"""EXEC-PAR BG-5a: the Wilson-DEFF helper. ICC is an argument; nothing here estimates it."""

from __future__ import annotations

from math import isfinite, sqrt


def wilson_deff_upper_bound(k: int, n: int, *, icc: float, m_bar: float, z: float) -> float:
    """One-sided Wilson upper bound on a pooled rate with the design effect (s5).

    ``DEFF = 1 + (m_bar - 1) x icc`` and ``n_eff = n / DEFF``. ``icc`` is an ARGUMENT: the
    evaluator never estimates it (r4.5 O2/O5); BG-10(f) supplies ICC_v. ``z`` is
    :data:`Z_ONE_SIDED_90` or :data:`Z_ONE_SIDED_95`.
    """
    if not all(isfinite(v) for v in (icc, m_bar, z, k, n)):
        raise ValueError("Wilson-DEFF arguments must be finite")
    if n <= 0 or k < 0 or k > n or icc < 0 or m_bar <= 0 or z <= 0:
        raise ValueError("invalid Wilson-DEFF arguments")
    n_eff = n / max(1.0, 1.0 + (m_bar - 1.0) * icc)  # DEFF is never below 1
    p = k / n
    z2 = z * z
    centre = p + z2 / (2.0 * n_eff)
    spread = z * sqrt(p * (1.0 - p) / n_eff + z2 / (4.0 * n_eff * n_eff))
    return min(1.0, (centre + spread) / (1.0 + z2 / n_eff))
