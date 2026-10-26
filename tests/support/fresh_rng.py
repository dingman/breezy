"""A context manager that gives a block its own, unpredictable global RNG state.

pytest-randomly reseeds ``random`` (and numpy's legacy global generator) before every test
phase. A module-scoped fixture built in one test's setup therefore starts from that phase's
seed, and an independent run made inside a later test would start from the same seed unless it
reseeds. ``fresh_global_rng`` reseeds both from ``os.urandom`` for the block and restores the
previous state on exit, so the block is independent of the shared run without leaking state.
"""

from __future__ import annotations

import os
import random
from collections.abc import Iterator
from contextlib import contextmanager
from typing import NamedTuple

_PYTHON_SEED_BYTES = 8
_NUMPY_SEED_BYTES = 4  # numpy.random.seed takes an integer below 2**32


class FreshSeeds(NamedTuple):
    """The seeds a block ran under (``numpy`` is ``None`` when numpy is not importable)."""

    python: int
    numpy: int | None


@contextmanager
def fresh_global_rng() -> Iterator[FreshSeeds]:
    """Reseed ``random`` and, if importable, ``numpy.random`` from ``os.urandom``; restore."""
    try:
        import numpy
    except ImportError:  # pragma: no cover - numpy is a hard dependency of the project
        numpy = None  # type: ignore[assignment]
    python_state = random.getstate()
    numpy_state = numpy.random.get_state() if numpy is not None else None
    python_seed = int.from_bytes(os.urandom(_PYTHON_SEED_BYTES), "big")
    numpy_seed = int.from_bytes(os.urandom(_NUMPY_SEED_BYTES), "big") if numpy is not None else None
    random.seed(python_seed)
    if numpy is not None and numpy_seed is not None:
        numpy.random.seed(numpy_seed)
    try:
        yield FreshSeeds(python_seed, numpy_seed)
    finally:
        random.setstate(python_state)
        if numpy is not None and numpy_state is not None:
            numpy.random.set_state(numpy_state)
