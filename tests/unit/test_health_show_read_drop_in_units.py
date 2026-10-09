"""AUT-6 health show read: the two units that carry TEMPORARY drop-ins are named explicitly.

``systemctl --user show -- 'breezy-*'`` lists a loaded unit only while it is active, activating or
failed, so the drop-ins on the ingest and replay services were seen only while those ran and rule
#5 fell back to the committed MemoryMax (2026-10-09 coverage gap).
"""

from __future__ import annotations

from pathlib import Path

from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE
from breezy.runtime.monitor_watch_memory import GIB
from breezy.runtime.unit_health_model import parse_show_blocks
from tests.support.unit_health_fixtures import show_block, show_text
from tests.unit.test_unit_health_memory import INGEST, check, deploy, violations  # noqa: F401

REPLAY = "breezy-replay-daily.service"
DROPIN = (
    "/home/jon/.config/systemd/user/breezy-quote-tape-ingest.service.d/"
    "zz-memory-containment-TEMPORARY.conf"
)


def _ingest_block(*, state: str = "inactive") -> str:
    return show_block(
        INGEST,
        ActiveState=state,
        MemoryMax=str(4 * GIB),
        MemoryHigh=str(GIB),
        DropInPaths=DROPIN,
    )


def test_the_show_read_names_the_ingest_and_replay_services_before_the_globs() -> None:
    (show,) = [
        r
        for r in AUTONOMY_BWRAP_TABLE["breezy-autonomy-health"].bus_reads
        if r.name == "units_show"
    ]
    argv = show.argv
    # reviewed widening (2026-10-09): two idle-by-default units that carry TEMPORARY drop-ins
    assert argv[argv.index("--") + 1 :] == (
        "breezy-quote-tape-rotate.service",
        "breezy-quote-tape-ingest.service",
        "breezy-replay-daily.service",
        "breezy-*",
        "us-source-collector@*",
    )


def test_an_inactive_ingest_block_still_yields_the_dropin_and_the_live_memory_max(
    deploy: Path,  # noqa: F811
) -> None:
    parsed = parse_show_blocks(show_text(_ingest_block()))
    result = check(deploy, parsed)
    assert "ingest_temporary_dropin_stands" in violations(result)


def test_a_duplicated_block_is_one_unit_not_two() -> None:
    """The unit named explicitly AND matched by the glob may print twice: the parser keys by Id."""
    once = parse_show_blocks(show_text(_ingest_block(state="active")))
    twice = parse_show_blocks(
        show_text(_ingest_block(state="active"), _ingest_block(state="active"))
    )
    assert twice == once and list(twice) == [INGEST]


def test_a_duplicated_block_does_not_double_count_the_memory_budget(deploy: Path) -> None:  # noqa: F811
    once = check(deploy, parse_show_blocks(show_text(_ingest_block())))
    twice = check(deploy, parse_show_blocks(show_text(_ingest_block(), _ingest_block())))
    assert once.metrics == twice.metrics
