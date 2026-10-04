"""AUT-1 WP1 part A: decision ids, the per-frame ordinal counter and the Nautilus-free guard.

Plan r12 section 3.4.1 (ids: r8 section 3.3.1, unchanged) and r8's id tests. r8's payload-ref tests
(``test_depth_ref_excludes_ts_init_and_size_zero_pads``, ``test_quote_ref_is_canonical``,
``test_quote_payload_body_is_exactly_ask_bid_ts_event``, ``test_ref_equals_payload_store_name``,
``test_forecast_input_sha_is_canonical``) belong to the payload store that ER-3 removes: a frame
reference is now ``(frame_kind, instrument, frame_ts_event)`` and carries no hash.
"""

import hashlib
import inspect
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from breezy.persistence import exit_tags
from breezy.persistence.autonomy import capture_ids
from breezy.persistence.autonomy.capture_ids import (
    EVAL_SEQ_REORDER_BASE,
    EVAL_SEQ_RETAINED_TS,
    EvalSeqCounter,
    compute_decision_id,
    compute_exit_decision_id,
    compute_orphan_decision_id,
)
from breezy.persistence.autonomy.capture_records import DecisionRecord, make_record

SRC_DIR = Path(__file__).resolve().parents[3] / "src"
IID = "tc-temp-laxhigh-2026-10-03-gte93lt94f.POLYMARKET_US"

_BASE: dict[str, Any] = {
    "family_id": "forecast-quantile-ladder-lax",
    "manifest_sha256": "a" * 64,
    "artefact_sha256": "b" * 64,
    "station": "KLAX",
    "climate_day": "2026-10-03",
    "rung_id": "gte93lt94f",
    "side": "YES",
    "eval_ns": 1_790_972_433_000_000_000,
    "eval_seq": 0,
}


def _expected(**overrides: object) -> str:
    values = {**_BASE, **overrides}
    order = (
        "family_id",
        "manifest_sha256",
        "artefact_sha256",
        "station",
        "climate_day",
        "rung_id",
        "side",
        "eval_ns",
        "eval_seq",
    )
    text = "|".join(str(values[k]) for k in order)
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def test_decision_id_field_order_is_pinned() -> None:
    """Independent recomputation: sha256 of the nine fields joined by ``|`` in the C1 order,
    first 32 hex. MUTATION: swapping any two inputs (for example station and rung) goes red."""
    assert compute_decision_id(**_BASE) == _expected()
    swapped = {**_BASE, "station": _BASE["rung_id"], "rung_id": _BASE["station"]}
    assert compute_decision_id(**swapped) != compute_decision_id(**_BASE)
    assert len(compute_decision_id(**_BASE)) == 32


def test_decision_id_includes_eval_seq() -> None:
    first = compute_decision_id(**{**_BASE, "eval_seq": 0})
    second = compute_decision_id(**{**_BASE, "eval_seq": 1})
    assert first != second
    assert second == _expected(eval_seq=1)


def test_decision_id_recomputes_from_stored_record() -> None:
    """The id recomputes from the record's OWN stored fields, never from a clock or a counter.

    MUTATION: dropping ``eval_seq`` or mixing ``wall_ns`` into the hash makes the recompute differ
    from the stored id.
    """
    stored_id = compute_decision_id(**_BASE)
    record = make_record(
        DecisionRecord,
        ts_event=int(str(_BASE["eval_ns"])),
        ts_init=int(str(_BASE["eval_ns"])) + 987_654_321,
        decision_id=stored_id,
        family_id=str(_BASE["family_id"]),
        manifest_sha256=str(_BASE["manifest_sha256"]),
        artefact_sha256=str(_BASE["artefact_sha256"]),
        station=str(_BASE["station"]),
        climate_day=str(_BASE["climate_day"]),
        rung_id=str(_BASE["rung_id"]),
        side=str(_BASE["side"]),
        eval_ns=int(str(_BASE["eval_ns"])),
        eval_seq=int(str(_BASE["eval_seq"])),
        wall_ns=int(str(_BASE["eval_ns"])) + 123_456,
    )
    recomputed = compute_decision_id(
        record.family_id,
        record.manifest_sha256,
        record.artefact_sha256,
        record.station,
        record.climate_day,
        record.rung_id,
        record.side,
        record.eval_ns,
        record.eval_seq,
    )
    assert recomputed == record.decision_id
    assert record.decision_id == _expected()  # and equals the independent recomputation


def test_decision_id_unique_per_take() -> None:
    """One frame, two handler calls (quote then depth), three rungs: every decision id is distinct
    because ``eval_seq`` counts across both calls (R-10). MUTATION: a per-call counter that resets
    to 0 for the depth call collides with the quote call's id."""
    counter = EvalSeqCounter()
    ids: set[str] = set()
    for rung in ("r1", "r2", "r3"):
        for _handler in ("quote", "depth"):
            seq = counter.next(IID, 1_000)
            ids.add(compute_decision_id(**{**_BASE, "rung_id": rung, "eval_seq": seq}))
    # six evaluations on one frame, ordinals 0..5, three rungs: 6 distinct ids
    assert len(ids) == 6


def test_same_frame_quote_and_depth_get_distinct_ids() -> None:
    counter = EvalSeqCounter()
    quote_seq = counter.next(IID, 5_000)
    depth_seq = counter.next(IID, 5_000)
    assert (quote_seq, depth_seq) == (0, 1)
    assert compute_decision_id(**{**_BASE, "eval_ns": 5_000, "eval_seq": quote_seq}) != (
        compute_decision_id(**{**_BASE, "eval_ns": 5_000, "eval_seq": depth_seq})
    )


def test_eval_seq_counts_unadmitted_evaluations() -> None:
    """The counter advances on EVERY call; admission by the on-change filter is not its input."""
    counter = EvalSeqCounter()
    assert [counter.next(IID, 7) for _ in range(5)] == [0, 1, 2, 3, 4]
    assert counter.next(IID, 8) == 0  # a new frame restarts at 0


def test_eval_seq_counter_is_bounded_per_instrument() -> None:
    """At most ``EVAL_SEQ_RETAINED_TS`` (4) ts_events per instrument are retained.

    MUTATION: never evicting grows without bound (``retained`` > 4).
    """
    counter = EvalSeqCounter()
    for ts in range(1, 50):
        counter.next(IID, ts)
        counter.next("other", ts)
    assert EVAL_SEQ_RETAINED_TS == 4
    assert counter.retained(IID) == 4
    assert counter.retained("other") == 4
    assert counter.retained("never-seen") == 0


def test_nonmonotone_ts_event_never_repeats_an_ordinal() -> None:
    """A ts_event that was evicted and is older than the newest retained one starts at
    ``EVAL_SEQ_REORDER_BASE`` and counts up, so no ordinal repeats (and the callback fires)."""
    seen: list[str] = []
    counter = EvalSeqCounter(on_nonmonotone=seen.append)
    for ts in (1, 2, 3, 4, 5):  # the fifth evicts ts=1
        assert counter.next(IID, ts) == 0
    assert EVAL_SEQ_REORDER_BASE == 1_000_000
    late = [counter.next(IID, 1), counter.next(IID, 1), counter.next(IID, 0)]
    assert late == [EVAL_SEQ_REORDER_BASE, EVAL_SEQ_REORDER_BASE + 1, EVAL_SEQ_REORDER_BASE + 2]
    assert counter.nonmonotone_count(IID) == 3
    assert seen == [IID, IID, IID]
    assert counter.next(IID, 5) == 1  # a retained frame keeps its own ordinals
    assert counter.next(IID, 6) == 0


def test_exit_decision_id_is_deterministic_from_exit_tags() -> None:
    args = ("rule-1", "pos-1", "fam-1", "O-1")
    expected = hashlib.sha256(("exit/v1|" + "|".join(args)).encode()).hexdigest()[:32]
    assert compute_exit_decision_id(*args) == expected
    assert compute_exit_decision_id(*args) == compute_exit_decision_id(*args)


def test_exit_decision_id_uses_only_the_four_exit_tag_values() -> None:
    """Exactly four parameters, named for the four ``exit_tags`` prefixes in their pinned order;
    each one moves the id. MUTATION: a fifth input (a clock) fails the signature check."""
    params = list(inspect.signature(compute_exit_decision_id).parameters)
    assert params == ["exit_rule", "exit_position_id", "exit_family_id", "exit_client_order_id"]
    prefixes = [
        exit_tags.EXIT_RULE_TAG_PREFIX,
        exit_tags.EXIT_POSITION_TAG_PREFIX,
        exit_tags.EXIT_FAMILY_TAG_PREFIX,
        exit_tags.EXIT_CLIENT_ORDER_ID_TAG_PREFIX,
    ]
    assert [p.removesuffix("=") for p in prefixes] == params
    base = compute_exit_decision_id("a", "b", "c", "d")
    for index in range(4):
        changed = ["a", "b", "c", "d"]
        changed[index] = "z"
        assert compute_exit_decision_id(*changed) != base


def test_orphan_decision_id_never_equals_a_decision_id_domain() -> None:
    """The orphan id has its own ``orphan/v1|`` domain: the same two strings hashed as an exit id
    or as the first two decision fields never collide with it."""
    orphan = compute_orphan_decision_id("fam", "O-1")
    assert orphan == hashlib.sha256(b"orphan/v1|fam|O-1").hexdigest()[:32]
    assert orphan != compute_exit_decision_id("fam", "O-1", "", "")
    assert orphan != hashlib.sha256(b"fam|O-1").hexdigest()[:32]


def test_decision_id_tag_prefix_is_defined_beside_the_exit_prefixes() -> None:
    assert exit_tags.DECISION_ID_TAG_PREFIX == "breezy:decision_id="
    assert "DECISION_ID_TAG_PREFIX" in exit_tags.__all__


@pytest.mark.parametrize("module", ["capture_ids", "capture_on_change"])
def test_capture_ids_and_on_change_do_not_import_nautilus(module: str) -> None:
    """Fresh interpreter: importing the module loads no ``nautilus_trader`` and no ``pyarrow``.

    Positive control: ``capture_records`` in the same probe does load ``nautilus_trader``.
    """
    probe = (
        "import importlib, json, sys; importlib.import_module(sys.argv[1]); "
        "print(json.dumps(sorted(m for m in sys.modules if m.split('.')[0] in "
        "('nautilus_trader', 'pyarrow'))))"
    )

    def loaded(name: str) -> str:
        result = subprocess.run(
            [sys.executable, "-c", probe, f"breezy.persistence.autonomy.{name}"],
            capture_output=True,
            text=True,
            check=True,
            env={"PYTHONPATH": str(SRC_DIR), "PATH": "/usr/bin:/bin"},
        )
        return result.stdout.strip().splitlines()[-1]

    assert loaded(module) == "[]"
    assert "nautilus_trader" in loaded("capture_records")


def test_module_exports_are_pinned() -> None:
    assert set(capture_ids.__all__) >= {
        "EvalSeqCounter",
        "compute_decision_id",
        "compute_exit_decision_id",
        "compute_orphan_decision_id",
    }
