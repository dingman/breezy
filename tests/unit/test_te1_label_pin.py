"""TE-1 WP-A re-pin: ``aut2.label`` is pinned to the closure of ``label_run`` (R2)."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from breezy.analysis.labeling import unit_wiring
from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.closure import closure_sha256


def test_aut2_label_is_pinned_to_its_own_closure() -> None:
    """The committed pin names the closure of ``label_run`` (cut after the R11 code landed); a stale
    pin would read as unpinned and the default factory would refuse ``producer_unpinned``."""
    pinned, code_sha = unit_wiring.producer_pin_state()

    assert pinned is True
    assert code_sha == closure_sha256(unit_wiring.ENTRY_MODULE)
    assert pins.PRODUCER_SOURCE_SHA256[unit_wiring.PRODUCER_ID] == code_sha


def test_a_stale_aut2_label_pin_reads_as_unpinned(monkeypatch: pytest.MonkeyPatch) -> None:
    """Positive control: change the pin and the same function reports unpinned."""
    stale = MappingProxyType({**pins.PRODUCER_SOURCE_SHA256, "aut2.label": "0" * 64})
    monkeypatch.setattr(pins, "PRODUCER_SOURCE_SHA256", stale)

    assert unit_wiring.producer_pin_state()[0] is False
