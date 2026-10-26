"""``tests/support/fresh_rng.py``: an independent global RNG for a block, restored afterwards."""

from __future__ import annotations

import random

import numpy as np
import pytest

from tests.support.fresh_rng import fresh_global_rng


def test_the_block_gets_its_own_seeds_and_the_outer_state_is_restored() -> None:
    random.seed(1234)
    np.random.seed(1234)
    before_py, before_np = random.getstate(), np.random.get_state()

    with fresh_global_rng() as seeds:
        assert seeds.numpy is not None and 0 <= seeds.numpy < 2**32
        inner_py, inner_np = random.getstate(), np.random.get_state()

    assert inner_py != before_py
    assert not np.array_equal(inner_np[1], before_np[1])
    assert random.getstate() == before_py
    assert np.array_equal(np.random.get_state()[1], before_np[1])


def test_two_blocks_never_share_a_seed() -> None:
    with fresh_global_rng() as first:
        pass
    with fresh_global_rng() as second:
        pass
    assert first.python != second.python


def test_the_state_is_restored_when_the_block_raises() -> None:
    random.seed(99)
    expected = random.getstate()
    with pytest.raises(RuntimeError, match="boom"), fresh_global_rng():
        random.random()
        raise RuntimeError("boom")
    assert random.getstate() == expected
