"""BL-23: the console entrypoint the operator runs before trusting a tape.

The exit code is the whole product here. A read-back that reports truncation in
prose but exits 0 is still silent to systemd, to a pipeline, and to anyone who
reads the last line of a log. The codes are deliberately distinct:

===========================  ====  =====================================
Outcome                      Code  Meaning
===========================  ====  =====================================
Intact, rows recovered          0  the tape is safe to interpret
Nothing captured                1  0 rows -- never "success", but not loss
Usage / configuration error     2  matches ``breezy-quote-tape``'s code 2
TRUNCATION DETECTED             3  bytes were written and then cut
===========================  ====  =====================================

Code 3 is separate from 1 precisely because the two mean opposite things about
the market: "nothing happened" versus "something happened and we lost it".
Collapsing them is the defect this ticket closes.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pyarrow as pa

from breezy.runtime.quote_tape_preflight_cli import (
    CATALOG_ENV_VAR,
    EXIT_NOTHING_CAPTURED,
    EXIT_OK,
    EXIT_TRUNCATED,
    EXIT_USAGE,
    run,
)

_SCHEMA = pa.schema([pa.field("value", pa.int64()), pa.field("ts_init", pa.int64())])


def _write_stream(path: Path, *, batches: int, close: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sink = pa.OSFile(str(path), "wb")
    writer = pa.ipc.new_stream(sink, _SCHEMA)
    for index in range(batches):
        writer.write_batch(
            pa.record_batch(
                [pa.array([index] * 10), pa.array(list(range(10)))], schema=_SCHEMA
            )
        )
    if close:
        writer.close()
    sink.close()


def _truncate(path: Path, *, drop_bytes: int) -> None:
    with path.open("r+b") as handle:
        handle.truncate(path.stat().st_size - drop_bytes)


def _invoke(*argv: str, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = run(argv=list(argv), env={} if env is None else env, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_an_intact_tape_exits_zero(tmp_path: Path) -> None:
    _write_stream(tmp_path / "live" / "run-a" / "quote_tick_1.feather", batches=5)

    code, out, _ = _invoke("--catalog", str(tmp_path), "--instance-id", "run-a")

    assert code == EXIT_OK
    assert "INTACT" in out
    assert "rows=50" in out


def test_a_truncated_tape_exits_with_the_truncation_code_and_names_the_file(
    tmp_path: Path,
) -> None:
    """The measured defect, made loud: 0 rows in the native path, exit 3 here."""
    tape = tmp_path / "live" / "run-a" / "quote_tick_1.feather"
    _write_stream(tape, batches=20, close=False)
    _truncate(tape, drop_bytes=64)

    code, out, err = _invoke("--catalog", str(tmp_path), "--instance-id", "run-a")

    assert code == EXIT_TRUNCATED
    assert "TRUNCATION DETECTED" in out
    assert "TRUNCATION DETECTED" in err
    assert tape.name in out
    assert "rows=190" in out
    assert "lost=" in out


def test_a_capture_that_recorded_nothing_exits_one_not_zero_and_not_three(
    tmp_path: Path,
) -> None:
    """Never success; never confused with loss."""
    _write_stream(tmp_path / "live" / "run-a" / "quote_tick_1.feather", batches=0)
    (tmp_path / "live" / "run-a" / "instrument_close_1.feather").write_bytes(b"")

    code, out, _ = _invoke("--catalog", str(tmp_path), "--instance-id", "run-a")

    assert code == EXIT_NOTHING_CAPTURED
    assert "CAPTURED NOTHING" in out
    assert "TRUNCATION DETECTED" not in out


def test_truncation_dominates_a_nothing_captured_instance(tmp_path: Path) -> None:
    _write_stream(tmp_path / "live" / "run-a" / "quote_tick_1.feather", batches=0)
    tape = tmp_path / "live" / "run-b" / "quote_tick_1.feather"
    _write_stream(tape, batches=20, close=False)
    _truncate(tape, drop_bytes=64)

    code, out, _ = _invoke("--catalog", str(tmp_path))

    assert code == EXIT_TRUNCATED
    assert "CAPTURED NOTHING" in out
    assert "TRUNCATION DETECTED" in out


def test_the_catalog_root_defaults_to_the_recorder_environment_variable(
    tmp_path: Path,
) -> None:
    _write_stream(tmp_path / "live" / "run-a" / "quote_tick_1.feather", batches=2)

    code, out, _ = _invoke(env={CATALOG_ENV_VAR: str(tmp_path)})

    assert code == EXIT_OK
    assert "run-a" in out


def test_an_unset_catalog_root_is_a_usage_error(tmp_path: Path) -> None:
    code, _, err = _invoke()

    assert code == EXIT_USAGE
    assert CATALOG_ENV_VAR in err


def test_a_missing_catalog_root_is_a_usage_error_not_an_empty_pass(tmp_path: Path) -> None:
    code, _, err = _invoke("--catalog", str(tmp_path / "nope"))

    assert code == EXIT_USAGE
    assert "nope" in err


def test_an_unknown_instance_is_a_usage_error(tmp_path: Path) -> None:
    _write_stream(tmp_path / "live" / "run-a" / "quote_tick_1.feather", batches=2)

    code, _, err = _invoke("--catalog", str(tmp_path), "--instance-id", "typo")

    assert code == EXIT_USAGE
    assert "typo" in err


def test_latest_selects_the_most_recently_written_instance(tmp_path: Path) -> None:
    """The operator does not know the id of the run that just finished."""
    old = tmp_path / "live" / "run-old" / "quote_tick_1.feather"
    _write_stream(old, batches=2)
    new = tmp_path / "live" / "run-new" / "quote_tick_1.feather"
    _write_stream(new, batches=3)
    os.utime(old, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))

    code, out, _ = _invoke("--catalog", str(tmp_path), "--latest")

    assert code == EXIT_OK
    assert "run-new" in out
    assert "run-old" not in out


def test_json_output_carries_every_per_file_verdict(tmp_path: Path) -> None:
    tape = tmp_path / "live" / "run-a" / "quote_tick_1.feather"
    _write_stream(tape, batches=20, close=False)
    _truncate(tape, drop_bytes=64)

    code, out, _ = _invoke("--catalog", str(tmp_path), "--instance-id", "run-a", "--json")

    assert code == EXIT_TRUNCATED
    payload = json.loads(out)
    assert payload["exit_code"] == EXIT_TRUNCATED
    assert payload["has_truncation"] is True
    instance = payload["instances"][0]
    assert instance["instance_id"] == "run-a"
    assert instance["files"][0]["status"] == "TRUNCATED"
    assert instance["files"][0]["rows"] == 190
    assert instance["files"][0]["ended_mid_message"] is True


def test_list_mode_prints_instance_ids_without_scanning(tmp_path: Path) -> None:
    _write_stream(tmp_path / "live" / "run-a" / "quote_tick_1.feather", batches=1)
    _write_stream(tmp_path / "live" / "run-b" / "quote_tick_1.feather", batches=1)

    code, out, _ = _invoke("--catalog", str(tmp_path), "--list")

    assert code == EXIT_OK
    assert out.split() == ["run-a", "run-b"]


def test_a_file_still_being_written_is_flagged_as_a_possible_false_alarm(
    tmp_path: Path,
) -> None:
    """At 13:00Z the operator runs this near a live writer.

    A file whose final message is incomplete BECAUSE the writer is mid-write is
    indistinguishable on disk from one cut by a kill. The verdict must NOT be
    softened -- exit 3 stands -- but the report says the file was touched
    seconds ago so the operator re-runs after the recorder exits instead of
    declaring the tape lost.
    """
    tape = tmp_path / "live" / "run-a" / "quote_tick_1.feather"
    _write_stream(tape, batches=20, close=False)
    _truncate(tape, drop_bytes=64)

    code, out, _ = _invoke("--catalog", str(tmp_path), "--instance-id", "run-a")

    assert code == EXIT_TRUNCATED
    assert "still being written" in out


def test_the_module_is_runnable_with_python_dash_m(tmp_path: Path) -> None:
    """The paste-ready operator command must work on an un-reinstalled checkout.

    The ``breezy-quote-tape-preflight`` console script only exists after a
    package reinstall, and reinstalling while a capture is running is an
    avoidable risk. ``python -m`` needs no install, so it is the form the
    runbook gives -- and it is pinned here rather than assumed.
    """
    tape = tmp_path / "live" / "run-a" / "quote_tick_1.feather"
    _write_stream(tape, batches=20, close=False)
    _truncate(tape, drop_bytes=64)

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "breezy.runtime.quote_tape_preflight_cli",
            "--catalog",
            str(tmp_path),
            "--latest",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == EXIT_TRUNCATED, completed.stderr
    assert "TRUNCATION DETECTED" in completed.stdout


def test_quiet_mode_prints_only_problem_files_but_still_exits_three(
    tmp_path: Path,
) -> None:
    """A real capture stages hundreds of files; the healthy ones are the noise.

    Measured against the live tree: 235 files, 211 of them INTACT, 37 KB of
    output. Suppressing the healthy lines is what makes the verdict readable --
    it must not change the verdict.
    """
    _write_stream(tmp_path / "live" / "run-a" / "healthy_1.feather", batches=5)
    tape = tmp_path / "live" / "run-a" / "quote_tick_1.feather"
    _write_stream(tape, batches=20, close=False)
    _truncate(tape, drop_bytes=64)

    code, out, _ = _invoke("--catalog", str(tmp_path), "--instance-id", "run-a", "--quiet")

    assert code == EXIT_TRUNCATED
    assert "quote_tick_1.feather" in out
    assert "healthy_1.feather" not in out
    assert "1 healthy file(s) not shown" in out
    assert "TRUNCATION DETECTED" in out


def test_the_verdict_warns_when_the_truncated_files_are_still_being_written(
    tmp_path: Path,
) -> None:
    """The caveat must reach the LAST line, not only the per-file detail.

    On a 235-file capture the per-file notes scroll past; the verdict is what
    gets read. The exit code is deliberately unchanged -- a partial trailing
    message is still a partial trailing message.
    """
    tape = tmp_path / "live" / "run-a" / "quote_tick_1.feather"
    _write_stream(tape, batches=20, close=False)
    _truncate(tape, drop_bytes=64)

    code, out, err = _invoke("--catalog", str(tmp_path), "--instance-id", "run-a", "--quiet")

    assert code == EXIT_TRUNCATED
    assert "STILL RUNNING" in out
    assert "STILL RUNNING" in err


def test_an_old_truncated_file_gets_no_still_running_caveat(tmp_path: Path) -> None:
    """A tape cut hours ago is a real loss and must not be excused."""
    tape = tmp_path / "live" / "run-a" / "quote_tick_1.feather"
    _write_stream(tape, batches=20, close=False)
    _truncate(tape, drop_bytes=64)
    os.utime(tape, ns=(1_000_000_000_000_000_000, 1_000_000_000_000_000_000))

    code, out, _ = _invoke("--catalog", str(tmp_path), "--instance-id", "run-a")

    assert code == EXIT_TRUNCATED
    assert "STILL RUNNING" not in out
    assert "still being written" not in out
