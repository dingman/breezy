"""Shared helpers for the unit suite.

Currently one thing lives here: the walker over the captured Polymarket.us
payload corpus. It was previously duplicated byte-for-byte in
``test_polymarket_us_fee_model.py`` and ``test_polymarket_us_parsing.py``,
which meant a change to what counts as a "market object" had to be made twice
and could silently diverge. One definition, imported by both.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The append-only capture of real venue payloads. Read-only in tests.
RAW_CAPTURE_DIR = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"

#: Non-vacuity floor for corpus properties. The capture held 729 market
#: observations on 2026-08-26; a property asserted over an empty or gutted
#: corpus is worthless, so every corpus test asserts this floor first.
MIN_CAPTURED_MARKETS = 700


def iter_captured_market_payloads(
    directory: Path = RAW_CAPTURE_DIR,
) -> list[dict[str, Any]]:
    """Every market object in every captured file, as a parseable payload.

    A market object is any JSON object carrying BOTH ``slug`` and
    ``orderPriceMinTickSize`` -- the shape ``parse_binary_option`` consumes.
    The walk is recursive, so markets nested under ``events[].markets[]``
    count too; a top-level-only scan misses most of the corpus.

    Returned as ``{"market": <object>}`` because that is the envelope
    ``parse_binary_option`` expects.
    """
    found: list[dict[str, Any]] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            if "slug" in node and "orderPriceMinTickSize" in node:
                found.append({"market": node})
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for path in sorted(directory.glob("*.json")):
        walk(json.loads(path.read_text(encoding="utf-8")))
    return found
