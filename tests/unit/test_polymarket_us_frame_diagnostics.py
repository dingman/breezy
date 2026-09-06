"""Bounded structure diagnostics for inbound Polymarket.us frames.

``diagnose_frame_payload`` runs on every websocket frame. A production book
carries a dozen bid/offer levels; walking every level (and then walking the
tree a second time for slug leaves) was ~194 µs of the ~515 µs handler.
The diagnostic describes *shape*, not cardinality, so only the first sequence
element is part of the contract.
"""

from __future__ import annotations

import json
from pathlib import Path

from breezy.adapters.polymarket_us import data as data_mod
from breezy.adapters.polymarket_us.data import diagnose_frame_payload

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOK_OPEN_PATH = (
    REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw" / "book_open_510636.json"
)
SLUG = "tc-temp-nychigh-2026-08-25-lt79f"

# One ``_walk_structure`` visit per node; ``structure_paths`` stores one path
# per visit. Measured post-fix first-element walk on book_open_510636: 61
# nodes. Ceiling is ~1.5x that. The pre-fix level-by-level walk visited 181
# nodes, well above this ceiling.
_BOUNDED_WALK_NODE_COUNT = 61
_BOUNDED_WALK_NODE_CEILING = 92
_PRE_FIX_UNBOUNDED_NODE_COUNT = 181


def _load_book_open() -> dict[str, object]:
    payload: dict[str, object] = json.loads(BOOK_OPEN_PATH.read_text(encoding="utf-8"))
    return payload


def test_diagnose_frame_payload_records_first_book_level_shape_not_later_levels() -> None:
    payload = _load_book_open()

    diagnostic = diagnose_frame_payload(payload, [SLUG])

    assert diagnostic.frame_class == "market_data"
    assert "marketData.marketSlug" in diagnostic.structure_paths
    assert diagnostic.safe_values["marketData.marketSlug"] == SLUG
    assert diagnostic.slug_bearing_keys == ("marketData.marketSlug",)
    assert "marketData.bids[0].px.value" in diagnostic.structure_paths
    assert "marketData.offers[0].px.value" in diagnostic.structure_paths
    assert "marketData.stats.openPx.value" in diagnostic.structure_paths
    assert "marketData.bids[11]" not in diagnostic.structure_paths
    assert "marketData.bids[11].px.value" not in diagnostic.structure_paths
    assert not any("[11]" in path for path in diagnostic.structure_paths)
    assert not any("[1]" in path for path in diagnostic.structure_paths)


def test_diagnose_frame_payload_walks_a_bounded_node_count_on_book_open_510636() -> None:
    """One diagnose_frame_payload call on book_open_510636 visits ≤ 92 nodes.

    Measured post-fix first-element walk: 61 nodes. Ceiling is ~1.5× that
    (92). The pre-fix walk that recursed every bid/offer level visited 181
    nodes, so this bound sits well below 181: a cardinality regression fails
    here without depending on wall-clock.
    """
    payload = _load_book_open()
    visits = {"count": 0}
    original = data_mod._walk_structure

    def counting_walk(*args: object, **kwargs: object) -> None:
        visits["count"] += 1
        original(*args, **kwargs)

    data_mod._walk_structure = counting_walk
    try:
        diagnostic = data_mod.diagnose_frame_payload(payload, [SLUG])
    finally:
        data_mod._walk_structure = original

    assert visits["count"] <= _BOUNDED_WALK_NODE_CEILING, (
        f"_walk_structure ran {visits['count']} times on book_open_510636 "
        f"(ceiling {_BOUNDED_WALK_NODE_CEILING}; post-fix {_BOUNDED_WALK_NODE_COUNT}; "
        f"pre-fix {_PRE_FIX_UNBOUNDED_NODE_COUNT}). A production book must not "
        "be recursed level-by-level. Investigate _walk_structure / "
        "diagnose_frame_payload; do not raise this ceiling to force a pass."
    )
    assert len(diagnostic.structure_paths) == visits["count"]
