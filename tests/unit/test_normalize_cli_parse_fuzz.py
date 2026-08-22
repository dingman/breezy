"""Wall-clock-bounded fuzz test for breezy.normalize.cli_parse.

Phase 1 parses CLI product text INLINE on the asyncio event loop -- there
is no executor/process containment for this path (`Actor.run_in_executor`
discards its callable's return value in both modes, so it cannot host a
parse that must return a value). The consequence: a parse that is merely
SLOW -- not necessarily catastrophically exponential -- stalls the
ENTIRE Nautilus event loop, not just ingestion. Every venue heartbeat and
every execution path in the process, halted by one malformed weather
product.

This test does not assert the parser accepts or rejects any given input
correctly (that is covered by test_normalize_cli_parse*.py). It asserts
ONLY that `parse_cli_product` RETURNS -- whether by succeeding or by
raising `CliParseError`/`CliSanityError` -- within a bounded wall-clock
ceiling, for
adversarial inputs up to the 128 KiB transport-layer body cap. Its job
is to catch a FUTURE regex edit that introduces a stall; the current
regexes were assessed free of catastrophic-backtracking shapes, but "we
inspected the patterns" is a weaker guarantee than this blast radius
deserves.
"""

from __future__ import annotations

import re
import time

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from breezy.normalize.cli_parse import CliParseError, parse_cli_product
from breezy.normalize.sanity import CliSanityError

NYC_HEADER_REGEX = re.compile(
    r"^\.\.\.THE\s+CENTRAL\s+PARK\s+NY\s+CLIMATE\s+SUMMARY\s+FOR\b", re.MULTILINE
)

TRANSPORT_BODY_CAP_CHARS = 128 * 1024
"""Mirrors the ingest transport layer's 128 KiB body-size cap (plan Sec
6): production never hands the parser a body larger than this, so the
fuzz corpus is bounded to the same ceiling (characters, not exact bytes
-- a conservative proxy that is never larger than the real cap allows)."""

# Chosen with real headroom over observed parse times, measured during
# authorship of this test: a genuine ~4 KB real CLI product parses in
# ~0.013ms (2000-iteration average); the worst of four hand-built
# 128 KiB-capped pathological bodies (deeply repeated MAXIMUM tokens,
# pure whitespace, repeated near-matching headers, high-cardinality
# unicode) was 0.33ms; 500 hypothesis-generated adversarial examples
# up to ~21 KB peaked at 0.47ms. 250ms gives >500x headroom over every
# worst case observed, while still being tight enough to catch a
# genuine O(n)-or-worse regression from a future regex edit (which
# would show up as tens-to-hundreds of milliseconds, not a fraction of
# a millisecond).
PARSE_TIME_CEILING_SECONDS = 0.25


def _adversarial_text() -> st.SearchStrategy[str]:
    """Adversarial CLI-shaped and non-CLI-shaped text, composed from
    several pathological shapes and capped at the transport body limit:
    pathological whitespace runs, repeated near-matching headers,
    truncated real-product prefixes, deeply repeated MAXIMUM tokens, and
    high-cardinality unicode.
    """
    whitespace_runs = st.text(alphabet=" \t\n", min_size=0, max_size=20_000)

    near_matching_headers = st.integers(min_value=0, max_value=500).map(
        lambda n: "...THE CENTRAL PARK N CLIMATE SUMMAR FOR AUGUST\n" * n
    )

    repeated_maximum_tokens = st.integers(min_value=0, max_value=5_000).map(
        lambda n: "TEMPERATURE (F)\n YESTERDAY\n" + "  MAXIMUM 79\n" * n + "PRECIPITATION\n"
    )

    truncated_real_shapes = st.sampled_from(
        [
            "\n000\nCDUS41 KOKX 220626\nCLINYC\n",
            (
                "\n000\nCDUS41 KOKX 220626\nCLINYC\n"
                "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR"
            ),
            (
                "\n000\nCDUS41 KOKX 220626\nCLINYC\n"
                "...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 21 2026...\n"
                "TEMPERATURE (F"
            ),
        ]
    )

    high_cardinality_unicode = st.text(
        alphabet=st.characters(
            min_codepoint=0x20, max_codepoint=0x1FFFF, exclude_categories=("Cs",)
        ),
        min_size=0,
        max_size=20_000,
    )

    plain_text = st.text(min_size=0, max_size=20_000)

    combined = st.one_of(
        whitespace_runs,
        near_matching_headers,
        repeated_maximum_tokens,
        truncated_real_shapes,
        high_cardinality_unicode,
        plain_text,
    )

    return (
        st.lists(combined, min_size=1, max_size=6)
        .map("".join)
        .map(lambda s: s[:TRANSPORT_BODY_CAP_CHARS])
    )


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(_adversarial_text())
def test_parse_time_is_bounded_for_adversarial_input(text: str) -> None:
    """If this test starts failing: a change to cli_parse.py's regexes has
    made some input slow -- even non-exponentially slow is enough to
    matter, because Phase 1 parses inline on the asyncio event loop and a
    slow parse there stalls the ENTIRE event loop (every venue heartbeat,
    every execution path), not just ingestion. Investigate the regex(es)
    changed since this test last passed; do not raise the ceiling to make
    it pass without first ruling out a real regression.
    """
    start = time.perf_counter()
    try:
        parse_cli_product(text, cli_location="NYC", body_header_regex=NYC_HEADER_REGEX)
    except (CliParseError, CliSanityError):
        pass
    elapsed = time.perf_counter() - start

    assert elapsed < PARSE_TIME_CEILING_SECONDS, (
        f"parse_cli_product took {elapsed * 1000:.1f}ms (ceiling: "
        f"{PARSE_TIME_CEILING_SECONDS * 1000:.0f}ms) for a {len(text)}-character "
        "adversarial input. This test exists to catch a regex edit that "
        "introduces a parse stall: Phase 1 parses CLI text inline on the "
        "asyncio event loop, so a slow parse here freezes the ENTIRE "
        "event loop -- every venue heartbeat and every execution path in "
        "the process -- not just ingestion. Investigate recently-changed "
        "regexes in cli_parse.py; do not raise this ceiling to force a "
        "pass without first ruling out a genuine regression."
    )
