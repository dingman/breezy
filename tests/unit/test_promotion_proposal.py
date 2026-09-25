"""AUD-10b steps 12–13: proposal script refusals, idempotency, and C19."""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from breezy.analysis.replay_results import REPLAY_RESULTS_SCHEMA_VERSION, REPLAY_VALIDITY, ReplayResult
from breezy.persistence.family_manifest import (
    UnregisteredFamilyManifestError,
    load_family_manifest,
)

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "analysis" / "promotion_proposal.py"
_WRAPPER = _REPO / "deploy" / "systemd" / "replay-daily-run.sh"
_V4 = _REPO / "deploy" / "families" / "pm_us_crh_v4.json"
_V2 = _REPO / "deploy" / "families" / "pm_us_crh_v2.json"
_NAMED = (
    "replay_sufficiency_census.py",
    "replay_daily_runner.py",
    "promotion_proposal.py",
)


def _proposal():
    spec = importlib.util.spec_from_file_location("promotion_proposal", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _code_lines(text: str) -> str:
    kept = [
        line
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return "\n".join(kept)


def _output_root(tmp_path: Path) -> Path:
    root = tmp_path / "derived" / "promotion"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _exec_db(tmp_path: Path) -> Path:
    path = tmp_path / "exec.sqlite"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value BLOB)")
    conn.commit()
    conn.close()
    return path


def _counter(tmp_path: Path, manifest: Path, name: str) -> Path:
    catalog = tmp_path / name / "catalog"
    (catalog / "data" / "order_book_depths").mkdir(parents=True)
    out = tmp_path / name / "counter.json"
    subprocess.run(
        [
            sys.executable,
            str(_REPO / "scripts" / "analysis" / "structural_dead_stop.py"),
            "--catalog-root",
            str(catalog),
            "--family-manifest",
            str(manifest),
            "--output",
            str(out),
        ],
        check=True,
        cwd=_REPO,
    )
    return out


def _results(path: Path, **overrides: object) -> None:
    base: dict[str, object] = {
        "schema_version": REPLAY_RESULTS_SCHEMA_VERSION,
        "run_ts": "2026-09-25T00:00:00+00:00",
        "station": "LAX",
        "climate_day": "2026-09-21",
        "strategy": "continuous_rung_hold",
        "lag_minutes": 30,
        "outcome": "COMPLETED",
        "validity": REPLAY_VALIDITY,
        "blocked_reason": None,
        "exception_type": None,
        "family_id": "pm_us_crh_v4",
        "manifest_sha256": "a" * 64,
        "manifest_taker_fee_coefficient": "0.0695",
        "engine_required_fee_coefficient": "0.0695",
        "engine_params_source": "FAMILY_MANIFEST",
        "params_match": True,
        "composition_kind": "continuous_rung_hold",
        "tape_instance_id": "inst",
        "sufficiency_reason": "",
        "trials": 0,
        "fills": 0,
        "fill_price_vs_decision_ask": [],
        "refusal_counts": {},
        "wall_s": 1.0,
        "peak_rss_bytes": 1,
        "parquet_sha256": None,
        "window_complete": True,
        "replayed_first_ns": 1,
        "replayed_last_ns": 2,
        "census_schema_version": 3,
    }
    base.update(overrides)
    path.write_text(json.dumps(base, sort_keys=True) + "\n")
    ReplayResult.from_dict(json.loads(path.read_text()))


def _run(tmp_path: Path, clock: Path | None, *, extra: list[str] | None = None) -> tuple[int, str]:
    module = _proposal()
    tmp_path.mkdir(parents=True, exist_ok=True)
    results = tmp_path / "replay_results.jsonl"
    if not (extra and "--replay-results" in extra):
        _results(results)
    drift = tmp_path / "replay_drift.jsonl"
    if not drift.exists():
        drift.write_text("")
    args = [
        "--family-manifest",
        str(_V4),
        "--output-root",
        str(_output_root(tmp_path)),
        "--replay-results",
        str(results),
        "--replay-sufficiency",
        str(tmp_path / "no-census.jsonl"),
        "--replay-drift",
        str(drift),
        "--scored-trials-dir",
        str(tmp_path / "no-such-store"),
        "--exec-state-db",
        str(_exec_db(tmp_path)),
        "--repo-root",
        str(tmp_path / "repo"),
    ]
    if extra and "--replay-results" in extra:
        index = args.index("--replay-results")
        del args[index : index + 2]
    if clock is not None:
        args.extend(["--kill-clock", str(clock)])
    else:
        args.extend(["--tally-output-dir", str(tmp_path / "empty-tally"), "--on-date", "2026-09-25"])
    if extra:
        args.extend(extra)
    code, output = module.main_capture(args)
    return code, output


def test_refuses_to_write_outside_derived_promotion(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    module = _proposal()
    code = module.main(
        [
            "--family-manifest",
            str(_V4),
            "--output-root",
            str(tmp_path / "not-promotion"),
            "--replay-results",
            str(tmp_path / "missing.jsonl"),
            "--scored-trials-dir",
            str(tmp_path / "store"),
        ]
    )
    assert code != 0
    captured = capsys.readouterr()
    assert "derived/promotion" in captured.err + captured.out
    assert not (tmp_path / "not-promotion").exists() or not any((tmp_path / "not-promotion").rglob("*"))


def test_refuses_registered_status_and_the_armed_family_id() -> None:
    module = _proposal()
    with pytest.raises(module.ProposalRefusal, match="REGISTERED"):
        module.refuse_unsafe_proposal(
            {"status": "REGISTERED", "family_id": "other"},
            sending_family_id="pm_us_crh_v4",
        )
    with pytest.raises(module.ProposalRefusal, match="sending_family_id"):
        module.refuse_unsafe_proposal(
            {"status": "DRAFT_NOT_REGISTERED", "family_id": "pm_us_crh_v4"},
            sending_family_id="pm_us_crh_v4",
        )


def test_no_proposal_names_failed_criteria_and_artefacts_and_cites_no_edge(
    tmp_path: Path,
) -> None:
    clock = _counter(tmp_path, _V4, "v4")
    code, output = _run(tmp_path / "run", clock)
    assert code == 0, output
    assert not output.startswith("PROPOSAL(")
    assert "NO_PROPOSAL" in output
    written = list((tmp_path / "run" / "derived" / "promotion").rglob("criteria.json"))
    assert len(written) == 1
    payload = json.loads(written[0].read_text())
    assert payload["outcome"] == "NO_PROPOSAL"
    assert payload["criteria_status"] == "PROVISIONAL"
    failed = {row["id"]: row for row in payload["predicates"] if row["verdict"] == "false"}
    assert "C-N" in failed and "C-VALIDITY" in failed
    for row in failed.values():
        assert row["input_artefact"]
    inert = {row["id"]: row for row in payload["predicates"] if row["verdict"] == "INERT"}
    assert inert["C-PAIRED"]["inert_reason"] == "NO_CHALLENGER_REPLAY_PATH"
    blob = "\n".join(path.read_text() for path in written[0].parent.rglob("*") if path.is_file())
    assert "edge_hat" not in blob
    proposal = written[0].parent / "proposal.json"
    with pytest.raises(UnregisteredFamilyManifestError):
        load_family_manifest(proposal)
    loaded = load_family_manifest(proposal, allow_draft=True)
    assert loaded.status == "DRAFT_NOT_REGISTERED"
    assert loaded.family_id != "pm_us_crh_v4"
    rationale = (written[0].parent / "RATIONALE.md").read_text()
    assert "PROVISIONAL" in rationale
    assert "never arms" in rationale.lower()


def test_a_second_unchanged_run_is_idempotent_and_a_tamper_is_a_hard_error(
    tmp_path: Path,
) -> None:
    clock = _counter(tmp_path, _V4, "clock")
    first_root = tmp_path / "a"
    code1, _out1 = _run(first_root, clock)
    assert code1 == 0
    dirs = list((first_root / "derived" / "promotion" / "proposals").iterdir())
    assert len(dirs) == 1
    code2, _out2 = _run(first_root, clock)
    assert code2 == 0
    assert len(list((first_root / "derived" / "promotion" / "proposals").iterdir())) == 1
    criteria = dirs[0] / "criteria.json"
    criteria.write_text(criteria.read_text().replace("NO_PROPOSAL", "PROPOSAL"))
    code3, out3 = _run(first_root, clock)
    assert code3 != 0
    assert "hard error" in out3.lower() or "byte" in out3.lower()


def _store(tmp_path: Path, name: str) -> Path:
    store = tmp_path / name
    store.mkdir(parents=True, exist_ok=True)
    (store / "provenance.json").write_text(json.dumps({"provenance": "live"}))
    return store


def test_new_scored_trial_file_between_runs_yields_a_new_proposal_directory(
    tmp_path: Path,
) -> None:
    """C12 fix: the content hash must cover the scored-trials STORE's actual
    contents (parquet/sidecar files), not just its provenance.json sidecar --
    a new fill/scored-trial landing between two same-day runs must produce a
    NEW proposal directory and exit 0, never a false 'tamper' hard error."""
    clock = _counter(tmp_path, _V4, "clock")
    store = _store(tmp_path, "store")
    run_root = tmp_path / "a"
    code1, out1 = _run(run_root, clock, extra=["--scored-trials-dir", str(store)])
    assert code1 == 0, out1
    dirs1 = {p.name for p in (run_root / "derived" / "promotion" / "proposals").iterdir()}
    assert len(dirs1) == 1

    # A new scored fill lands in the store between runs.
    (store / "fill_order.jsonl").write_text(
        json.dumps({"trial_id": "t1", "score_seq": 0, "filled_at_ns": 1}) + "\n"
    )

    code2, out2 = _run(run_root, clock, extra=["--scored-trials-dir", str(store)])
    assert code2 == 0, out2
    assert "hard error" not in out2.lower()
    dirs2 = {p.name for p in (run_root / "derived" / "promotion" / "proposals").iterdir()}
    assert len(dirs2) == 2
    assert dirs1 < dirs2


def test_new_exec_state_db_row_between_runs_yields_a_new_proposal_directory(
    tmp_path: Path,
) -> None:
    """C12 fix: the exec-state DB is a content input too -- a new fill
    written between two same-day runs must produce a NEW proposal directory
    and exit 0, never a false 'tamper' hard error."""
    clock = _counter(tmp_path, _V4, "clock")
    exec_db = _exec_db(tmp_path)
    run_root = tmp_path / "b"
    code1, out1 = _run(run_root, clock, extra=["--exec-state-db", str(exec_db)])
    assert code1 == 0, out1
    dirs1 = {p.name for p in (run_root / "derived" / "promotion" / "proposals").iterdir()}
    assert len(dirs1) == 1

    conn = sqlite3.connect(exec_db)
    conn.execute(
        "INSERT INTO state (key, value) VALUES (?, ?)",
        ("some/new/key", b"a new fill landed"),
    )
    conn.commit()
    conn.close()

    code2, out2 = _run(run_root, clock, extra=["--exec-state-db", str(exec_db)])
    assert code2 == 0, out2
    assert "hard error" not in out2.lower()
    dirs2 = {p.name for p in (run_root / "derived" / "promotion" / "proposals").iterdir()}
    assert len(dirs2) == 2
    assert dirs1 < dirs2


def test_unchanged_scored_trials_store_and_exec_db_reuse_the_same_directory(
    tmp_path: Path,
) -> None:
    """Unchanged store + exec-db content (even under a different exec-db
    file path) yields the SAME content-hashed directory and exit 0."""
    clock = _counter(tmp_path, _V4, "clock")
    store = _store(tmp_path, "store")
    run_root = tmp_path / "c"
    code1, out1 = _run(
        run_root,
        clock,
        extra=["--scored-trials-dir", str(store), "--exec-state-db", str(_exec_db(tmp_path))],
    )
    assert code1 == 0, out1
    dirs1 = {p.name for p in (run_root / "derived" / "promotion" / "proposals").iterdir()}
    assert len(dirs1) == 1

    # A fresh exec-db file with byte-identical (empty) content, same store.
    code2, out2 = _run(
        run_root,
        clock,
        extra=["--scored-trials-dir", str(store), "--exec-state-db", str(_exec_db(tmp_path))],
    )
    assert code2 == 0, out2
    dirs2 = {p.name for p in (run_root / "derived" / "promotion" / "proposals").iterdir()}
    assert dirs1 == dirs2


def test_unknown_replay_schema_refuses(tmp_path: Path) -> None:
    clock = _counter(tmp_path, _V4, "clock")
    results = tmp_path / "bad.jsonl"
    row = {"schema_version": 99, "station": "LAX"}
    results.write_text(json.dumps(row) + "\n")
    code, output = _run(tmp_path / "run", clock, extra=["--replay-results", str(results)])
    assert code != 0
    assert "99" in output
    assert "schema_version" in output


def test_absent_kill_clock_refuses_the_run(tmp_path: Path) -> None:
    code, output = _run(tmp_path / "run", None)
    assert code != 0
    assert "KILL_CLOCK_ABSENT" in output


def test_non_champion_clock_is_inert_and_cannot_emit_proposal(tmp_path: Path) -> None:
    clock = _counter(tmp_path, _V2, "v2")
    payload = json.loads(clock.read_text())
    payload["depth_root_present"] = False
    clock.write_text(json.dumps(payload))
    old = 1_000.0
    os.utime(clock, (old, old))
    code, output = _run(tmp_path / "run", clock)
    assert code == 0, output
    assert not output.startswith("PROPOSAL(")
    written = next((tmp_path / "run" / "derived" / "promotion").rglob("criteria.json"))
    body = json.loads(written.read_text())
    kill = next(row for row in body["predicates"] if row["id"] == "C-KILL")
    assert kill["verdict"] == "INERT"
    assert kill["inert_reason"] == "NO_CHAMPION_SCOPED_KILL_CLOCK"
    assert body["outcome"] != "PROPOSAL"


def test_stale_champion_clock_refuses(tmp_path: Path) -> None:
    from breezy.analysis.promotion_criteria import KILL_CLOCK_MAX_AGE_SECONDS

    clock = _counter(tmp_path, _V4, "stale")
    old = clock.stat().st_mtime - (KILL_CLOCK_MAX_AGE_SECONDS + 5)
    os.utime(clock, (old, old))
    code, output = _run(tmp_path / "run", clock)
    assert code != 0
    assert "KILL_CLOCK_STALE" in output


def test_step14_one_real_run_against_todays_evidence_c8() -> None:
    """AUD-10b step 14 / C8. Read-only against the real derived evidence tree;
    writes only under a worktree-local scratch directory, never the live
    ``~/.local/share/breezy/derived`` tree. Skips (never fails) on a host
    lacking the real artefacts, since this asserts against live host state,
    not a fixture.
    """
    home = Path.home()
    derived = home / ".local" / "share" / "breezy" / "derived"
    exec_db = Path(
        os.environ.get(
            "POLYMARKET_US_EXEC_STATE_DB",
            str(home / ".local" / "share" / "breezy" / "state" / "exec_polymarket_us.sqlite"),
        )
    )
    replay_results = derived / "replay" / "replay_results.jsonl"
    if not (_V4.is_file() and replay_results.is_file() and exec_db.is_file()):
        pytest.skip("real evidence artefacts are not present on this host")

    output_root = _REPO / "scratch" / "aud10b_step14" / "derived" / "promotion"
    module = _proposal()
    code, output = module.main_capture(
        [
            "--family-manifest",
            str(_V4),
            "--output-root",
            str(output_root),
            "--replay-results",
            str(replay_results),
            "--replay-sufficiency",
            str(derived / "replay" / "replay_sufficiency.jsonl"),
            "--replay-drift",
            str(derived / "replay" / "replay_drift.jsonl"),
            "--tally-output-dir",
            str(derived),
            "--exec-state-db",
            str(exec_db),
        ]
    )
    assert code == 0, output
    criteria_files = list(output_root.rglob("criteria.json"))
    assert len(criteria_files) == 1, output
    payload = json.loads(criteria_files[0].read_text())
    if payload["outcome"] == "NO_PROPOSAL":
        assert payload["failed"], f"C8: NO_PROPOSAL must name a failed criterion: {payload}"
    elif payload["outcome"] == "PROPOSAL":
        assert all(row["verdict"] == "true" for row in payload["predicates"]), payload
        proposal_path = criteria_files[0].parent / "proposal.json"
        with pytest.raises(UnregisteredFamilyManifestError):
            load_family_manifest(proposal_path)
    else:
        pytest.fail(
            f"C8: outcome {payload['outcome']!r} is a third shape; "
            "acceptance requires NO_PROPOSAL or PROPOSAL"
        )


def test_criteria_status_lifts_only_on_an_exact_sha_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lifting-ruling path + sha256 check lives HERE, in the script, not
    in ``src/breezy/analysis/promotion_criteria.py`` -- see
    ``test_probe_containment.py::test_no_module_under_src_reads_docs_evidence``.
    """
    module = _proposal()
    target = tmp_path / module.LIFTING_RULING_RELATIVE
    target.parent.mkdir(parents=True)
    body = b"lifting ruling body\n"
    target.write_bytes(body)
    assert module.resolve_criteria_status(tmp_path) == "PROVISIONAL"
    import hashlib

    original_sha256 = module.LIFTING_RULING_SHA256
    assert original_sha256 != hashlib.sha256(body).hexdigest()
    monkeypatch.setattr(module, "LIFTING_RULING_SHA256", hashlib.sha256(body).hexdigest())
    assert module.resolve_criteria_status(tmp_path) == "LIFTED"
    target.write_bytes(b"tampered\n")
    assert module.resolve_criteria_status(tmp_path) == "PROVISIONAL"
    target.unlink()
    assert module.resolve_criteria_status(tmp_path) == "PROVISIONAL"
    target.mkdir()
    assert module.resolve_criteria_status(tmp_path) == "PROVISIONAL"


def test_c19_wrapper_names_the_three_scripts_inside_the_lock() -> None:
    code = _code_lines(_WRAPPER.read_text())
    import re

    invoked = re.findall(r'"\$PY"\s+"\$REPO/scripts/analysis/([^"]+)"', code)
    assert invoked, "wrapper has no \"$PY\" invocation"
    assert set(invoked) <= set(_NAMED)
    assert "promotion_proposal.py" in invoked
    assert "record_blocked" not in code
    assert ".jsonl" not in code
    assert "json.load" not in code
    lock_at = code.index("breezy-studies.lock")
    proposal_at = code.index("promotion_proposal.py")
    replay_at = code.index("--family-manifest")
    assert lock_at < proposal_at
    assert replay_at < proposal_at
