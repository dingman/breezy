"""AUT-6 WP3b (plan r15 section 3.8.1, G12): the discovery pull's bounded-memory read.

The 10-02 run read every node log whole and kept every parsed record (working set about 4.47 GB
through a 256M cgroup). These tests pin the redesign: today's window only, bounded chunks, only the
records the consumer reads, atomic outputs, and behaviour unchanged on a trimmed real 10-02 log.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import scripts.analysis.discovery_venue_pull as module
from scripts.analysis.discovery_venue_pull import (
    FollowState,
    find_initial_trigger,
    poll_node_logs_once,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "discovery_pull"
_SINCE_NS = int(datetime(2026, 10, 3, 16, 35, tzinfo=UTC).timestamp() * 1_000_000_000)
_MIB = 1024 * 1024
_DATA_CLIENT = "BREEZY-L001.DataClient-POLYMARKET_US"
_OTHER = "BREEZY-L001.TradingNode"


def _line(ts: str, component: str, message: str) -> str:
    return f"{ts}Z [INFO] {component}: {message}\n"


def _initial(ts: str) -> str:
    return _line(
        ts,
        _DATA_CLIENT,
        "Polymarket.us discovery cycle initial: subscribed=('a',) unsubscribed=() "
        "blocked_missing_cache=()",
    )


def test_first_poll_skips_logs_older_than_today_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = tmp_path / "breezy-trade-20261002T205521Z.log"
    old.write_text(_initial("2026-10-02T20:55:30.000000000"), encoding="utf-8")
    today = tmp_path / "breezy-trade-20261003T165045Z.log"
    today.write_text(_initial("2026-10-03T16:50:49.000000000"), encoding="utf-8")
    opened: list[str] = []
    real_open = open

    def spy_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        opened.append(Path(file).name)
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(module, "open", spy_open, raising=False)

    state, records, _truncated = poll_node_logs_once(tmp_path, FollowState(), since_ns=_SINCE_NS)

    assert opened == [today.name]
    assert {r.source for r in records} == {today}
    assert state.cursors[old].offset == old.stat().st_size


_CHILD = textwrap.dedent(
    """
    import json, resource, sys
    from pathlib import Path
    from scripts.analysis.discovery_venue_pull import FollowState, poll_node_logs_once

    def peak_kib() -> int:
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss

    log_dir, since_ns = Path(sys.argv[1]), int(sys.argv[2])
    poll_node_logs_once(log_dir / "warm", FollowState(), since_ns=since_ns)
    baseline = peak_kib()
    _state, records, _ = poll_node_logs_once(log_dir, FollowState(), since_ns=since_ns)
    print(json.dumps({"delta_kib": peak_kib() - baseline, "kept": len(records)}))
    """
)


def test_poll_reads_in_bounded_chunks_not_whole_file(tmp_path: Path) -> None:
    (tmp_path / "warm").mkdir()
    big = tmp_path / "breezy-trade-20261003T165045Z.log"
    filler = _line("2026-10-03T16:50:50.000000000", _OTHER, "x" * 200)
    with open(big, "w", encoding="utf-8") as fh:
        fh.write(_initial("2026-10-03T16:50:49.000000000"))
        fh.writelines(filler for _ in range(64 * _MIB // len(filler)))
    assert big.stat().st_size >= 64 * _MIB

    env = {**os.environ, "PYTHONPATH": f"{_REPO_ROOT}:{_REPO_ROOT / 'src'}"}
    done = subprocess.run(
        [sys.executable, "-c", _CHILD, str(tmp_path), str(_SINCE_NS)],
        capture_output=True,
        text=True,
        check=True,
        cwd=_REPO_ROOT,
        env=env,
    )

    result = json.loads(done.stdout)
    assert result["kept"] == 1
    assert result["delta_kib"] < 32 * 1024


def test_only_polymarket_data_client_records_kept(tmp_path: Path) -> None:
    path = tmp_path / "breezy-trade-20261003T165045Z.log"
    path.write_text(
        _line("2026-10-03T16:50:48.000000000", _OTHER, "noise")
        + _initial("2026-10-03T16:50:49.000000000")
        + _line("2026-10-03T16:50:50.000000000", "BREEZY-L001.POLYMARKET_US-discovery", "other")
        + "bare stdlib line\n",
        encoding="utf-8",
    )

    _state, records, _truncated = poll_node_logs_once(tmp_path, FollowState(), since_ns=_SINCE_NS)

    assert [r.component for r in records] == [_DATA_CLIENT]


def test_outputs_written_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "2026-10-03.json"
    target.write_text("old", encoding="utf-8")
    seen: list[tuple[str, str, str]] = []
    real_replace = os.replace

    def spy_replace(src: Any, dst: Any) -> None:
        seen.append((Path(src).parent.name, Path(dst).name, Path(src).read_text(encoding="utf-8")))
        assert target.read_text(encoding="utf-8") == "old"  # not yet touched
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)

    module._write_text_atomic(target, '{"a": 1}')

    assert seen == [(tmp_path.name, target.name, '{"a": 1}')]
    assert target.read_text(encoding="utf-8") == '{"a": 1}'
    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


def test_failed_atomic_write_leaves_old_file_and_no_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "2026-10-03.json"
    target.write_text("old", encoding="utf-8")

    def boom(src: Any, dst: Any) -> None:
        raise OSError("disk")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError, match="disk"):
        module._write_text_atomic(target, "new")

    assert target.read_text(encoding="utf-8") == "old"
    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


def test_initial_trigger_found_unchanged_on_replayed_10_02_fixture(tmp_path: Path) -> None:
    shutil.copy(_FIXTURE_DIR / "breezy-trade-20261002T165039Z.log", tmp_path)
    since_ns, _deadline = module._today_window_ns(datetime(2026, 10, 2, 16, 52, tzinfo=UTC))

    _state, records, _truncated = poll_node_logs_once(tmp_path, FollowState(), since_ns=since_ns)
    trigger = find_initial_trigger(records, since_ns=since_ns)

    assert trigger is not None
    assert trigger.ts_ns == 1790959844888827148
    assert trigger.source.name == "breezy-trade-20261002T165039Z.log"
    active = module._replay_node_active_slugs(trigger.source, up_to_ns=trigger.ts_ns)
    assert len(active) == 60
    assert active[0] == "tc-temp-laxhigh-2026-10-02-gte85lt86f"


# ---------------------------------------------------------------------------
# Reader edge cases: chunk boundaries, CRLF, multi-byte characters across polls
# ---------------------------------------------------------------------------

_MULTIBYTE = "café € \U0001f600 done"


def _edge_payload() -> bytes:
    lines = [
        _line("2026-10-03T16:50:48.000000000", _OTHER, "noise"),
        _line("2026-10-03T16:50:49.000000000", _DATA_CLIENT, _MULTIBYTE),
        _line("2026-10-03T16:50:50.000000000", _DATA_CLIENT, "second record"),
    ]
    crlf = [item.replace("\n", "\r\n") for item in lines]
    return "".join(lines[:1] + crlf[1:2] + lines[2:]).encode("utf-8")


def _summarise(state: FollowState, records: Any) -> tuple[Any, ...]:
    cursors = {p.name: (c.offset, c.tail) for p, c in state.cursors.items()}
    return cursors, [(r.ts_ns, r.component, r.message) for r in records]


def test_chunked_read_equals_one_shot_read_for_straddling_crlf_and_multibyte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "breezy-trade-20261003T165045Z.log"
    path.write_bytes(_edge_payload())
    state, records, _ = poll_node_logs_once(tmp_path, FollowState(), since_ns=_SINCE_NS)
    expected = _summarise(state, records)
    assert [r.message for r in records] == [_MULTIBYTE, "second record"]

    for size in (1, 2, 3, 5, 7, 16):
        monkeypatch.setattr(module, "READ_CHUNK_BYTES", size)
        state, records, _ = poll_node_logs_once(tmp_path, FollowState(), since_ns=_SINCE_NS)
        assert _summarise(state, records) == expected, size


def test_multibyte_char_split_across_two_polls_is_not_corrupted(tmp_path: Path) -> None:
    path = tmp_path / "breezy-trade-20261003T165045Z.log"
    payload = _edge_payload()
    cut = payload.index("€".encode()) + 1  # mid-way through the 3-byte euro sign
    path.write_bytes(payload[:cut])
    state, first, _ = poll_node_logs_once(tmp_path, FollowState(), since_ns=_SINCE_NS)
    with open(path, "ab") as fh:
        fh.write(payload[cut:])

    state, second, _ = poll_node_logs_once(tmp_path, state, since_ns=_SINCE_NS)

    assert [r.message for r in (*first, *second)] == [_MULTIBYTE, "second record"]
