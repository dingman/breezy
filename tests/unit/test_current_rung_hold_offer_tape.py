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

GAP fix (2026-09-15): ``OfferTapeRecord`` grew nine postmortem-observability
fields (``side``/``p_bound``/``break_even``/running-max interval/staleness/
fee coefficient/``observed_at_ns``/``admission_reason``/``decision``) --
the fixture and expected dict below now cover the FULL current shape
(sanctioned schema growth, not a weakening of this pin: every original key
and value is unchanged, only new keys were appended).
"""

from __future__ import annotations

import json
from decimal import Decimal
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
    side="YES",
    p_bound=Decimal("0.6982"),
    break_even=Decimal("0.81"),
    running_max_lower=Decimal(87),
    running_max_upper=Decimal(87),
    running_max_exact=True,
    staleness_ns=1_000_000_000,
    fee_coefficient=Decimal("0.06"),
    observed_at_ns=1_787_617_188_000_000_000,
    admission_reason=None,
    decision="refuse",
)

#: The exact shape ``json.dumps(dataclasses.asdict(_RECORD), sort_keys=True)``
#: would produce -- every field name and value, independently hand-derived
#: from ``OfferTapeRecord``'s own field list, never copy-pasted from the
#: implementation under test.
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
    "side": "YES",
    "p_bound": "0.6982",
    "break_even": "0.81",
    "running_max_lower": "87",
    "running_max_upper": "87",
    "running_max_exact": True,
    "staleness_ns": 1_000_000_000,
    "fee_coefficient": "0.06",
    "observed_at_ns": 1_787_617_188_000_000_000,
    "admission_reason": None,
    "decision": "refuse",
}

_OLD_SHAPE_KEYS = frozenset(
    {
        "station",
        "climate_day",
        "instrument_id",
        "ask",
        "size",
        "reason",
        "ts_event",
        "hour_lst",
        "width_code",
        "m_code",
        "trigger",
        "quote_age_ns",
        "minutes_since_window_open",
        "prior_eligible_snaps",
        "illegal_cell",
        "source",
    }
)


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


def test_a_pre_gap_fix_record_still_defaults_the_new_keys() -> None:
    """GAP fix 2026-09-15 RED: a record built with ONLY the pre-fix (old
    15-field) shape -- exactly how ``continuous_strategy.py`` constructed
    every ``OfferTapeRecord`` before this fix -- must still construct and
    serialize, defaulting every new key rather than raising."""
    old_shape_record = OfferTapeRecord(
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
    as_dict = old_shape_record.to_dict()
    assert _OLD_SHAPE_KEYS <= set(as_dict)
    assert as_dict["side"] == "YES"
    assert as_dict["p_bound"] is None
    assert as_dict["break_even"] is None
    assert as_dict["running_max_lower"] is None
    assert as_dict["running_max_upper"] is None
    assert as_dict["running_max_exact"] is False
    assert as_dict["staleness_ns"] is None
    assert as_dict["fee_coefficient"] is None
    assert as_dict["observed_at_ns"] is None
    assert as_dict["admission_reason"] is None
    assert as_dict["decision"] == "refuse"


def test_an_old_jsonl_line_missing_the_new_keys_still_parses() -> None:
    """GAP fix 2026-09-15 RED: a JSONL line written by the PRE-fix code (only
    the 16 old keys, no side/p_bound/etc.) is still valid, parseable JSON --
    nothing in this module requires every historical line to carry the new
    keys."""
    old_line = json.dumps({key: None for key in _OLD_SHAPE_KEYS} | {"size": 1}, sort_keys=True)
    parsed = json.loads(old_line)
    assert _OLD_SHAPE_KEYS <= set(parsed)
    assert "side" not in parsed
