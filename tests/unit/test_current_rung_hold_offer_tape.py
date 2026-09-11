"""``OfferTape`` JSONL serialization (L-29, credential-guard fix).

``dataclasses.asdict`` was removed from ``offer_tape.py`` entirely (it is
not a member of the closed ``_ALLOWED_ASDICT_CALL_SITES`` allowlist in
``test_polymarket_us_credential_serialization.py``, and that allowlist is
never widened -- see this module's own docstring). ``OfferTapeRecord`` now
serializes through an explicit, field-by-field ``to_dict()``.

This module pins that the JSONL sidecar's output is BYTE-IDENTICAL to what
``json.dumps(dataclasses.asdict(record), sort_keys=True)`` produced before
the refactor: every field name, present, with the exact same value, in the
same (sorted) key order.
"""

from __future__ import annotations

import json
from pathlib import Path

from breezy.strategy.current_rung_hold.offer_tape import OfferTape, OfferTapeRecord

_RECORD = OfferTapeRecord(
    station="KJFK",
    climate_day="2026-08-25",
    instrument_id="tc-temp-nyc-2026-08-25.POLYMARKET_US",
    ask="0.80",
    size=1,
    reason="edge_below_break_even",
    ts_event=1_787_617_188_120_237_895,
    hour_lst=14,
    width_code=2,
    m_code=1,
    trigger="on_quote_tick",
    quote_age_ns=5_000_000_000,
    minutes_since_window_open=12,
    prior_eligible_snaps=3,
    illegal_cell=False,
    source="depth",
)

#: The exact shape ``json.dumps(dataclasses.asdict(_RECORD), sort_keys=True)``
#: produced before the refactor -- every field name and value, independently
#: hand-derived from ``OfferTapeRecord``'s own field list, never copy-pasted
#: from the implementation under test.
_EXPECTED_DICT: dict[str, object] = {
    "station": "KJFK",
    "climate_day": "2026-08-25",
    "instrument_id": "tc-temp-nyc-2026-08-25.POLYMARKET_US",
    "ask": "0.80",
    "size": 1,
    "reason": "edge_below_break_even",
    "ts_event": 1_787_617_188_120_237_895,
    "hour_lst": 14,
    "width_code": 2,
    "m_code": 1,
    "trigger": "on_quote_tick",
    "quote_age_ns": 5_000_000_000,
    "minutes_since_window_open": 12,
    "prior_eligible_snaps": 3,
    "illegal_cell": False,
    "source": "depth",
}


def test_to_dict_matches_the_pre_refactor_asdict_shape_exactly() -> None:
    """``to_dict()`` carries every field ``asdict()`` would have, no more,
    no less, with identical values -- the field-by-field replacement is a
    pure rename of the mechanism, not a change of shape."""
    assert _RECORD.to_dict() == _EXPECTED_DICT
    assert set(_RECORD.to_dict()) == {field for field in _EXPECTED_DICT}


def test_the_jsonl_sidecar_line_is_byte_identical_to_the_pre_refactor_shape(
    tmp_path: Path,
) -> None:
    """The actual bytes written to disk are the sorted-keys JSON encoding of
    the exact same dict ``asdict()`` used to produce -- proven by re-deriving
    the expected line independently via ``json.dumps(..., sort_keys=True)``
    on the hand-built ``_EXPECTED_DICT`` above, then comparing byte for
    byte against what ``OfferTape.append`` actually wrote."""
    path = tmp_path / "offer.jsonl"
    tape = OfferTape(path)
    tape.append(_RECORD)

    expected_line = json.dumps(_EXPECTED_DICT, sort_keys=True)
    actual_line = path.read_text(encoding="utf-8").rstrip("\n")
    assert actual_line == expected_line


def test_as_dicts_also_uses_to_dict_and_matches_the_pre_refactor_shape() -> None:
    """``OfferTape.as_dicts()`` (the in-memory equivalent) carries the same
    shape as the JSONL sidecar -- one serialization path, not two drifting
    ones."""
    tape = OfferTape()
    tape.append(_RECORD)
    assert tape.as_dicts() == (_EXPECTED_DICT,)


def test_offer_tape_record_no_longer_calls_asdict() -> None:
    """Mechanical pin: the credential guard's fix is that ``asdict`` is
    GONE from this module, not merely allowlisted. A regression that
    reintroduces it (even on an allowlisted-looking argument) is caught
    here directly, independent of the guard test's own scan."""
    import ast

    from breezy.strategy.current_rung_hold import offer_tape as offer_tape_module

    source = Path(offer_tape_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    asdict_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "asdict")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "asdict")
        )
    ]
    assert asdict_calls == [], "offer_tape.py must never call dataclasses.asdict again"
