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
import logging
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.strategy.current_rung_hold.offer_tape import (
    DEFAULT_OFFER_TAPE_MAXLEN,
    DEFAULT_OFFER_TAPE_SIDECAR_MAX_BYTES,
    OfferTape,
    OfferTapeRecord,
)

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
    # INC-E3 (plan §3, PREREG v4 §3b/§12): additive, `None` for every
    # entry-hunt row (this fixture's own row is one) -- see this module's
    # own docstring.
    "exit_rule": None,
    "exit_decision": None,
    "exit_reason_code": None,
    "exit_limit_price": None,
    "expected_settlement_value": None,
    # RESTING_BID_HUNT Rev 2 §5/§6 (shadow stage): additive, `None`/`False`
    # for every row before the shadow decider is wired in -- see this
    # module's own docstring.
    "shadow_rest_state": None,
    "shadow_rest_price": None,
    "shadow_rest_margin": None,
    "shadow_rest_reason": None,
    "shadow_fill_event": False,
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


def test_an_old_jsonl_line_missing_the_new_keys_still_round_trips_through_from_dict() -> None:
    """L1 review finding (commit 309dab6): a JSONL line written by the
    PRE-fix code (only the 16 old keys, no side/p_bound/etc.) is not merely
    parseable JSON (that assertion was vacuous) -- it round-trips through
    the reader ``OfferTapeRecord`` lacked until now: ``from_dict`` defaults
    every GAP-fix key exactly like a record built directly (mirrors
    ``test_a_pre_gap_fix_record_still_defaults_the_new_keys`` above)."""
    old_line = json.dumps(
        {key: getattr(_RECORD, key) for key in _OLD_SHAPE_KEYS}, sort_keys=True,
    )
    parsed = json.loads(old_line)
    assert _OLD_SHAPE_KEYS <= set(parsed)
    assert "side" not in parsed

    record = OfferTapeRecord.from_dict(parsed)

    as_dict = record.to_dict()
    for key in _OLD_SHAPE_KEYS:
        assert as_dict[key] == getattr(_RECORD, key)
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


def test_a_full_record_round_trips_exactly_through_from_dict_and_to_dict() -> None:
    """L1 review finding (commit 309dab6): a NEW-shape line (all 27 keys)
    round-trips byte-for-byte through ``from_dict`` -> ``to_dict``."""
    round_tripped = OfferTapeRecord.from_dict(_EXPECTED_DICT)
    assert round_tripped.to_dict() == _EXPECTED_DICT


def test_from_dict_refuses_a_payload_missing_a_legacy_key() -> None:
    """L1 review finding (commit 309dab6): ``from_dict`` is strict on the 16
    legacy keys -- unlike the GAP-fix keys, these have never been optional."""
    incomplete = {key: getattr(_RECORD, key) for key in _OLD_SHAPE_KEYS if key != "station"}
    with pytest.raises(ValueError, match="station"):
        OfferTapeRecord.from_dict(incomplete)


def test_default_offer_tape_maxlen_is_pinned_at_16384() -> None:
    """M2 review finding (commit 309dab6): YES+NO rows now share one tape,
    doubling the per-tick row count -- the default is doubled in step so
    YES retention depth is unchanged."""
    assert DEFAULT_OFFER_TAPE_MAXLEN == 16384


def test_a_file_where_the_sidecar_directory_should_be_still_constructs(
    tmp_path: Path,
) -> None:
    """H1 review finding (commit 309dab6): ``OfferTape.__init__`` must never
    raise from a blocked sidecar directory (composition.py now resolves a
    default sidecar path unconditionally) -- construction is best-effort,
    falling back to in-memory only."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    path = blocker / "sub" / "offer.jsonl"

    tape = OfferTape(path)

    assert tape.sidecar_errors == 1
    tape.append(_RECORD)
    assert len(tape) == 1
    assert not path.exists()


# ---------------------------------------------------------------------------
# 2026-09-16 GAP fix: per-climate-day sidecar byte cap (defect A).
# ---------------------------------------------------------------------------


def _line_bytes(record: OfferTapeRecord) -> int:
    return len(json.dumps(record.to_dict(), sort_keys=True).encode("utf-8")) + 1


def test_default_sidecar_max_bytes_is_pinned_at_the_measured_2026_09_25_value() -> None:
    """F-3 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md) re-pin: the 09-16 postmortem's
    64 MiB pin is superseded by the 2026-09-25 disk measurement (09-22's
    capped 64 MiB day projected to ~141 MiB uncapped through 01:00Z, plus an
    unmeasured F-1a NO-side growth margin -- F-1a is not implemented on this
    branch yet per Sequencing). This is a PROVISIONAL value pin, not a safety
    test: it may move again once a live day is measured with F-1a merged."""
    assert DEFAULT_OFFER_TAPE_SIDECAR_MAX_BYTES == 512 * 1024 * 1024


def test_half_cap_warn_once(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """AC2: one WARN when a sidecar crosses 50% of its cap -- distinct from,
    and logged before, the existing at-cap WARN."""
    path = tmp_path / "offer.jsonl"
    one_line = _line_bytes(_RECORD)
    # 4 lines fits comfortably under half of an 8-line cap; the 5th crosses it.
    cap = one_line * 8
    tape = OfferTape(path, sidecar_max_bytes=cap)

    caplog.set_level(logging.WARNING, logger="breezy.strategy.current_rung_hold.offer_tape")
    for _ in range(4):
        tape.append(_RECORD)
    assert not caplog.records

    tape.append(_RECORD)  # 5th line crosses the 50% threshold
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "50%" in warnings[0].message or "half" in warnings[0].message.lower()

    # Further rows below the cap never log a second half-cap WARN.
    for _ in range(2):
        tape.append(_RECORD)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_below_the_cap_every_row_is_written_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "offer.jsonl"
    tape = OfferTape(path, sidecar_max_bytes=DEFAULT_OFFER_TAPE_SIDECAR_MAX_BYTES)

    for _ in range(5):
        tape.append(_RECORD)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    assert tape.sidecar_capped == 0
    assert len(tape) == 5


def test_at_the_cap_further_rows_stop_appending_to_disk_but_not_to_the_deque(
    tmp_path: Path,
) -> None:
    """Cap reached: no further bytes land on disk, the counter increments
    once per refused row, and the in-memory deque is unaffected."""
    path = tmp_path / "offer.jsonl"
    one_line = _line_bytes(_RECORD)
    # Room for exactly 3 lines before the 4th would push over the cap.
    cap = one_line * 3
    tape = OfferTape(path, sidecar_max_bytes=cap)

    for _ in range(3):
        tape.append(_RECORD)
    size_at_cap = path.stat().st_size
    assert size_at_cap == cap

    for _ in range(4):
        tape.append(_RECORD)

    assert path.stat().st_size == size_at_cap  # not one more byte landed
    assert tape.sidecar_capped == 4
    assert len(tape) == 7  # the deque kept working throughout
    assert tape.sidecar_errors == 0  # a cap refusal is not a disk error

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    for line in lines:
        assert OfferTapeRecord.from_dict(json.loads(line)) == _RECORD


def test_the_cap_warning_is_logged_exactly_once(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """F-3 (AC2) note: a cap this small (one line == the whole cap) crosses
    BOTH the 50% half-cap threshold and the full cap on the very first
    append, so exactly one HALF-CAP warning and one AT-CAP warning are
    expected -- never more than one of either kind."""
    path = tmp_path / "offer.jsonl"
    one_line = _line_bytes(_RECORD)
    tape = OfferTape(path, sidecar_max_bytes=one_line)

    caplog.set_level(logging.WARNING, logger="breezy.strategy.current_rung_hold.offer_tape")
    tape.append(_RECORD)  # exactly fills the cap
    for _ in range(3):
        tape.append(_RECORD)  # every one of these is refused

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    at_cap = [r for r in warnings if "reached its" in r.message]
    half_cap = [r for r in warnings if "crossed 50%" in r.message]
    assert len(at_cap) == 1
    assert len(half_cap) == 1
    assert len(warnings) == 2
    assert tape.sidecar_capped == 3


def test_a_process_restart_resumes_the_cap_from_the_real_on_disk_size(
    tmp_path: Path,
) -> None:
    """A second `OfferTape` opened on a path that already has rows on disk
    (a mid-day process restart) must count those bytes toward its cap, not
    re-zero the budget and allow a second full `sidecar_max_bytes` past the
    true on-disk size."""
    path = tmp_path / "offer.jsonl"
    one_line = _line_bytes(_RECORD)
    cap = one_line * 3

    first = OfferTape(path, sidecar_max_bytes=cap)
    for _ in range(3):
        first.append(_RECORD)
    assert path.stat().st_size == cap

    second = OfferTape(path, sidecar_max_bytes=cap)
    second.append(_RECORD)

    assert path.stat().st_size == cap  # the restarted tape refused too
    assert second.sidecar_capped == 1
