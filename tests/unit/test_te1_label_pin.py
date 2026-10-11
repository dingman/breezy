"""TE-1 WP-A re-pin: ``aut2.label`` is pinned to the closure of ``label_run`` (R2)."""

from __future__ import annotations

from types import MappingProxyType

import pytest

from breezy.analysis.labeling import unit_wiring
from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.closure import closure_sha256
from tests.support.closure_manifest_literal import is_pure_literal


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


_LITERAL_HEAD = '"""d."""\nfrom types import MappingProxyType\nfrom typing import Final\n'


def _source(literal: str) -> str:
    return (
        f"{_LITERAL_HEAD}X: Final[MappingProxyType[str, tuple[str, ...]]] = "
        f"MappingProxyType({literal})\n"
    )


@pytest.mark.parametrize(
    "literal",
    ['{"a": ("b",)}', '{"a": ("b", "c")}', "{}"],
)
def test_pure_literal_accepts_str_keys_and_tuple_of_str_values(literal: str) -> None:
    src = _source(literal)
    assert is_pure_literal(src)


@pytest.mark.parametrize(
    "literal",
    ["{1: ('b',)}", '{"a": ["b"]}', '{"a": (1,)}', '{"a": "b"}', '{"a": ("b", None)}', "[1]"],
)
def test_pure_literal_rejects_other_shapes(literal: str) -> None:
    src = _source(literal)
    assert not is_pure_literal(src)
