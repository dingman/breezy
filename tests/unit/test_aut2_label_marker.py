"""AUT-2 r7 WP6 / section 3.12: the run marker is written once, read newest-first, never guessed."""

from __future__ import annotations

import stat
from dataclasses import replace
from pathlib import Path

import pytest

from breezy.persistence.autonomy.label_store import (
    MARKER_DIR,
    LabelMarker,
    MarkerCorrupt,
    RunMarker,
    RunOutcome,
    labels_consumable,
    read_newest_marker,
    write_marker,
)
from breezy.persistence.autonomy.single_read import SingleReadReason, SingleReadRefused

_H = 3_600_000_000_000
_NOW = 1_790_000_000_000_000_000
_DAY = "2026-09-22"


def _marker(**over: object) -> RunMarker:
    base: dict[str, object] = {
        "run_outcome": RunOutcome.LABELLED,
        "durable_fill_count": 11,
        "durable_fill_count_prev": 9,
        "labelled_final": 7,
        "unattributed_pre_epoch": 3,
        "legacy_labelled": 1,
        "open": 0,
        "pending": 0,
        "unresolved": 0,
        "missing_label": 0,
        "p_null_count": 0,
        "non_c1_post_epoch_count": 0,
    }
    base.update(over)
    return RunMarker(**base)  # type: ignore[arg-type]


def test_marker_round_trips_with_every_plan_count_and_private_modes(tmp_path: Path) -> None:
    path = write_marker(tmp_path, _marker(), day=_DAY, now_ns=_NOW)

    got = read_newest_marker(tmp_path)

    assert got == replace(_marker(), written_at_ns=_NOW)
    assert path == tmp_path.joinpath(*MARKER_DIR, _DAY, f"marker_{_NOW}.json")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    text = path.read_text()
    assert '"schema":"label_outcomes_marker/v1"' in text
    for name in (
        "run_outcome",
        "durable_fill_count",
        "durable_fill_count_prev",
        "labelled_final",
        "unattributed_pre_epoch",
        "legacy_labelled",
        "open",
        "pending",
        "unresolved",
        "missing_label",
        "p_null_count",
        "non_c1_post_epoch_count",
    ):
        assert f'"{name}"' in text


def test_the_newest_marker_wins_across_days(tmp_path: Path) -> None:
    write_marker(tmp_path, _marker(labelled_final=1), day="2026-09-21", now_ns=_NOW - 30 * _H)
    write_marker(tmp_path, _marker(labelled_final=2), day=_DAY, now_ns=_NOW)
    write_marker(tmp_path, _marker(labelled_final=3), day=_DAY, now_ns=_NOW - _H)

    got = read_newest_marker(tmp_path)

    assert got is not None and (got.labelled_final, got.written_at_ns) == (2, _NOW)


def test_absent_marker_reads_none(tmp_path: Path) -> None:
    assert read_newest_marker(tmp_path) is None


def test_second_identical_write_is_a_no_op_and_a_different_one_is_refused(tmp_path: Path) -> None:
    write_marker(tmp_path, _marker(), day=_DAY, now_ns=_NOW)
    write_marker(tmp_path, _marker(), day=_DAY, now_ns=_NOW)

    with pytest.raises(SingleReadRefused) as caught:
        write_marker(tmp_path, _marker(pending=1), day=_DAY, now_ns=_NOW)

    assert caught.value.reason is SingleReadReason.EXISTS_DIFFERENT


@pytest.mark.parametrize(
    "text",
    [
        b"not json",
        b'{"schema":"label_outcomes_marker/v2"}',
        b'{"schema":"label_outcomes_marker/v1","run_outcome":"MAYBE"}',
        b'{"schema":"label_outcomes_marker/v1","run_outcome":"LABELLED"}',
    ],
)
def test_a_corrupt_marker_raises_never_reads_as_absent(tmp_path: Path, text: bytes) -> None:
    write_marker(tmp_path, _marker(), day=_DAY, now_ns=_NOW - _H)
    bad = tmp_path.joinpath(*MARKER_DIR, _DAY, f"marker_{_NOW}.json")
    bad.write_bytes(text)
    bad.chmod(0o600)

    with pytest.raises(MarkerCorrupt):
        read_newest_marker(tmp_path)


def test_a_marker_file_with_a_malformed_name_is_corrupt(tmp_path: Path) -> None:
    write_marker(tmp_path, _marker(), day=_DAY, now_ns=_NOW)
    stray = tmp_path.joinpath(*MARKER_DIR, _DAY, "marker_x.json")
    stray.write_text("{}")
    stray.chmod(0o600)

    with pytest.raises(MarkerCorrupt):
        read_newest_marker(tmp_path)


def test_marker_gate_view_feeds_the_shared_consumer_predicate() -> None:
    ok = replace(_marker(), written_at_ns=_NOW)
    bad = replace(_marker(missing_label=1), written_at_ns=_NOW)
    failed = replace(_marker(run_outcome=RunOutcome.FAILED_IDENTITY), written_at_ns=_NOW)

    assert isinstance(ok.gate(), LabelMarker)
    assert labels_consumable(ok.gate(), now_ns=_NOW + _H) is True
    assert labels_consumable(bad.gate(), now_ns=_NOW + _H) is False
    assert labels_consumable(failed.gate(), now_ns=_NOW + _H) is False


def test_negative_counts_are_refused_before_any_write(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_marker(tmp_path, _marker(pending=-1), day=_DAY, now_ns=_NOW)

    assert not (tmp_path / "derived").exists()
