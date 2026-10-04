"""Operator clear tool for the `pm_us_crh_cont` family-wide halt.

Mirrors `tests/unit/test_clear_submit_intent_cli.py`'s structure: a tmp_path
SQLite store shared with R-7's submit-intent flock, since `TrialDayLatch`
(and therefore the family halt key) lives in that SAME store.
"""

from __future__ import annotations

import ast
import io
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from breezy.adapters.polymarket_us.factories import EXEC_STATE_DB_ENV_VAR
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.clear_family_halt_cli import (
    EXIT_NOTHING_TO_CLEAR,
    EXIT_OK,
    EXIT_REFUSED,
    main,
)
from breezy.strategy.current_rung_hold.trial_day_latch import (
    FAMILY_HALT_CLEARED_KEY_PREFIX,
    LEGACY_FAMILY_HALT_KEY,
    family_halt_key,
    open_trial_day_latch,
)

DUP_FILL_TS_NS = 1_787_617_213_000_000_000
CLEAR_TS_NS = 1_787_700_000_000_000_000
#: The real, checked-in v4 manifest -- mirrors `test_set_family_halt_cli.py`:
#: every test uses this id against the repo's real `deploy/families/` (the
#: default `--families-dir`), so no test needs to fabricate a manifest.
TEST_FAMILY_ID = "pm_us_crh_v4"


def _audit_key(ts_ns: int, family_id: str = TEST_FAMILY_ID) -> str:
    return f"{FAMILY_HALT_CLEARED_KEY_PREFIX}{family_id}/{ts_ns}"


def _evidence(tmp_path: Path, name: str = "evidence.txt") -> Path:
    path = tmp_path / name
    path.write_text("positions snapshot + fill record attached out of band", encoding="utf-8")
    return path


def _env(store_path: Path) -> dict[str, str]:
    return {EXEC_STATE_DB_ENV_VAR: str(store_path)}


def _seed_halt(store_path: Path, *, family_id: str = TEST_FAMILY_ID) -> None:
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(intent_latch, family_id=family_id)
        trial_latch.record_duplicate_fill(
            "KSFO",
            "2026-09-12",
            venue_order_id="v-dup-1",
            qty=Decimal(1),
            fill_px=Decimal("0.4"),
            fee=Decimal(0),
            ts_ns=DUP_FILL_TS_NS,
        )
    store.close()


def _run(
    argv: list[str],
    store_path: Path,
    *,
    stdout: io.StringIO,
    stderr: io.StringIO,
    ts_ns: int = CLEAR_TS_NS,
) -> int:
    if "--family-id" not in argv and "--legacy" not in argv:
        argv = [*argv, "--family-id", TEST_FAMILY_ID]
    with patch(
        "breezy.strategy.current_rung_hold.clear_family_halt_cli.time.time_ns",
        return_value=ts_ns,
    ):
        return main(argv, env=_env(store_path), stdout=stdout, stderr=stderr)


def _seed_raw_halt(store_path: Path, raw: bytes, *, family_id: str = TEST_FAMILY_ID) -> None:
    """Write `raw` directly under the per-family halt key, bypassing
    `record_duplicate_fill` -- used to simulate a corrupt or legacy-schema
    halt record that no writer in this codebase produces today."""
    store = SqliteStateStore(store_path)
    store.set(family_halt_key(family_id), raw)
    store.close()


def test_refuses_when_the_halt_key_is_absent(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    SqliteStateStore(store_path).close()
    stdout = io.StringIO()
    code = _run(
        [
            "--reason",
            "false alarm, verified via venue console",
            "--evidence-path",
            str(_evidence(tmp_path)),
        ],
        store_path,
        stdout=stdout,
        stderr=io.StringIO(),
    )
    assert code == EXIT_NOTHING_TO_CLEAR
    assert "nothing to clear" in stdout.getvalue()

    store = SqliteStateStore(store_path)
    assert store.get(family_halt_key(TEST_FAMILY_ID)) is None
    assert store.get(LEGACY_FAMILY_HALT_KEY) is None
    store.close()


def test_refuses_while_the_node_holds_the_lock(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_halt(store_path)
    store = SqliteStateStore(store_path)
    stdout = io.StringIO()
    stderr = io.StringIO()
    with open_submit_intent_latch(store, store_path):
        code = _run(
            [
                "--reason",
                "confirmed duplicate fill was a resend, not a new order",
                "--evidence-path",
                str(_evidence(tmp_path)),
            ],
            store_path,
            stdout=stdout,
            stderr=stderr,
        )
    store.close()
    assert code == EXIT_REFUSED
    assert "holds the lock" in stderr.getvalue()

    store2 = SqliteStateStore(store_path)
    with open_submit_intent_latch(store2, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(intent_latch, family_id=TEST_FAMILY_ID)
        assert trial_latch.is_family_halted() is True
    assert store2.get(_audit_key(CLEAR_TS_NS)) is None
    store2.close()


def test_happy_path_clears_the_halt_and_writes_an_audit_record(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_halt(store_path)
    evidence = _evidence(tmp_path)
    stdout = io.StringIO()
    reason = "verified via venue console: duplicate fill was a websocket resend"
    code = _run(
        ["--reason", reason, "--evidence-path", str(evidence)],
        store_path,
        stdout=stdout,
        stderr=io.StringIO(),
    )
    assert code == EXIT_OK
    assert "cleared" in stdout.getvalue()

    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(intent_latch, family_id=TEST_FAMILY_ID)
        assert trial_latch.is_family_halted() is False
    audit_raw = store.get(_audit_key(CLEAR_TS_NS))
    store.close()
    assert audit_raw is not None
    audit = json.loads(audit_raw.decode("utf-8"))
    assert audit["reason"] == reason
    assert audit["tsNs"] == CLEAR_TS_NS
    assert audit["priorHalt"]["venueOrderId"] == "v-dup-1"
    assert len(audit["evidenceSha256"]) == 64


def test_second_run_after_clearing_is_idempotent(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_halt(store_path)
    evidence = _evidence(tmp_path)
    reason = "verified via venue console, duplicate was a resend"
    code1 = _run(
        ["--reason", reason, "--evidence-path", str(evidence)],
        store_path,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert code1 == EXIT_OK

    stdout2 = io.StringIO()
    code2 = _run(
        ["--reason", reason, "--evidence-path", str(evidence)],
        store_path,
        stdout=stdout2,
        stderr=io.StringIO(),
    )
    assert code2 == EXIT_NOTHING_TO_CLEAR
    assert "nothing to clear" in stdout2.getvalue()


def test_argparse_rejects_a_too_short_reason(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_halt(store_path)
    raised = False
    try:
        main(
            ["--reason", "too short", "--evidence-path", str(_evidence(tmp_path))],
            env=_env(store_path),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    except SystemExit as exc:
        raised = True
        assert exc.code == 2
    assert raised
    store = SqliteStateStore(store_path)
    assert store.get(family_halt_key(TEST_FAMILY_ID)) is not None  # unchanged: still live
    store.close()


def test_argparse_rejects_a_missing_evidence_file(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_halt(store_path)
    missing = tmp_path / "does-not-exist.json"
    raised = False
    try:
        main(
            [
                "--reason",
                "verified via venue console, duplicate was a resend",
                "--evidence-path",
                str(missing),
            ],
            env=_env(store_path),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    except SystemExit as exc:
        raised = True
        assert exc.code == 2
    assert raised
    store = SqliteStateStore(store_path)
    assert store.get(family_halt_key(TEST_FAMILY_ID)) is not None  # unchanged
    store.close()


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param(b"\xff\xfe\x00garbage-not-utf8", id="garbage_bytes"),
        pytest.param(b"", id="empty_string"),
        pytest.param(
            b'{"schemaVersion": 0, "note": "pre-halt-audit legacy format"}',
            id="old_version_json",
        ),
    ],
)
def test_a_corrupt_or_legacy_halt_payload_fails_closed_and_is_still_clearable(
    tmp_path: Path, raw: bytes
) -> None:
    """MEDIUM gap: `is_family_halted` must fail CLOSED (True) on garbage
    bytes, an empty value, or an unrecognised/legacy schema -- and the CLI
    must still be able to clear it with evidence rather than raising."""
    store_path = tmp_path / "state.db"
    SqliteStateStore(store_path).close()
    _seed_raw_halt(store_path, raw)

    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(intent_latch, family_id=TEST_FAMILY_ID)
        assert trial_latch.is_family_halted() is True
    store.close()

    stdout = io.StringIO()
    code = _run(
        [
            "--reason",
            "cleared a corrupt/legacy halt payload after manual review",
            "--evidence-path",
            str(_evidence(tmp_path)),
        ],
        store_path,
        stdout=stdout,
        stderr=io.StringIO(),
    )
    assert code == EXIT_OK
    assert "cleared" in stdout.getvalue()

    store2 = SqliteStateStore(store_path)
    audit_raw = store2.get(_audit_key(CLEAR_TS_NS))
    with open_submit_intent_latch(store2, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(intent_latch, family_id=TEST_FAMILY_ID)
        assert trial_latch.is_family_halted() is False
    store2.close()
    assert audit_raw is not None
    audit = json.loads(audit_raw.decode("utf-8"))
    assert "priorHalt" in audit


def test_clearing_never_blocks_a_later_genuine_halt_and_each_clear_gets_its_own_audit_key(
    tmp_path: Path,
) -> None:
    """MEDIUM gap: after a clear, a FRESH `record_duplicate_fill` must be
    able to re-halt the family (not be silently swallowed by a stale
    "already halted" read of the cleared sentinel), and a second clear of
    that fresh halt must succeed and land under its OWN audit key -- never
    overwriting the first clear's audit record."""
    store_path = tmp_path / "state.db"
    _seed_halt(store_path)
    first_clear_ts_ns = CLEAR_TS_NS
    second_clear_ts_ns = CLEAR_TS_NS + 1

    code1 = _run(
        [
            "--reason",
            "first clear: confirmed duplicate fill was a resend",
            "--evidence-path",
            str(_evidence(tmp_path, "evidence-1.txt")),
        ],
        store_path,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        ts_ns=first_clear_ts_ns,
    )
    assert code1 == EXIT_OK

    # A second, genuinely new duplicate fill re-halts the family with a
    # FRESH payload -- not the cleared sentinel left behind above.
    store = SqliteStateStore(store_path)
    with open_submit_intent_latch(store, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(intent_latch, family_id=TEST_FAMILY_ID)
        assert trial_latch.is_family_halted() is False
        trial_latch.record_duplicate_fill(
            "KLAX",
            "2026-09-13",
            venue_order_id="v-dup-2",
            qty=Decimal(1),
            fill_px=Decimal("0.5"),
            fee=Decimal(0),
            ts_ns=DUP_FILL_TS_NS + 1,
        )
        assert trial_latch.is_family_halted() is True
    store.close()

    stdout2 = io.StringIO()
    code2 = _run(
        [
            "--reason",
            "second clear: confirmed the second duplicate fill was also a resend",
            "--evidence-path",
            str(_evidence(tmp_path, "evidence-2.txt")),
        ],
        store_path,
        stdout=stdout2,
        stderr=io.StringIO(),
        ts_ns=second_clear_ts_ns,
    )
    assert code2 == EXIT_OK
    assert "cleared" in stdout2.getvalue()

    store2 = SqliteStateStore(store_path)
    first_audit = store2.get(_audit_key(first_clear_ts_ns))
    second_audit = store2.get(_audit_key(second_clear_ts_ns))
    with open_submit_intent_latch(store2, store_path) as intent_latch:
        trial_latch = open_trial_day_latch(intent_latch, family_id=TEST_FAMILY_ID)
        assert trial_latch.is_family_halted() is False
    store2.close()

    assert first_audit is not None
    assert second_audit is not None
    assert first_audit != second_audit
    second_payload = json.loads(second_audit.decode("utf-8"))
    assert second_payload["priorHalt"]["venueOrderId"] == "v-dup-2"


# ---------------------------------------------------------------------------
# EDGE-3 test 22: unknown / non-continuous / mismatched / escaping family id,
# plus the required, mutually-exclusive --family-id/--legacy group.
# ---------------------------------------------------------------------------


def test_set_and_clear_refuse_unknown_non_continuous_mismatched_or_escaping_family_id(
    tmp_path: Path,
) -> None:
    import json as _json

    families = tmp_path / "families"
    families.mkdir()

    # (a) unknown: no manifest file at all.
    store_path = tmp_path / "state.db"
    SqliteStateStore(store_path).close()
    code_unknown = main(
        [
            "--family-id", "pm_us_crh_does_not_exist",
            "--families-dir", str(families),
            "--reason", "attempted clear of an unregistered family id here",
            "--evidence-path", str(_evidence(tmp_path, "u.txt")),
        ],
        env=_env(store_path),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert code_unknown == EXIT_REFUSED

    # (b) non-continuous composition_kind.
    v4_manifest = _json.loads(Path("deploy/families/pm_us_crh_v4.json").read_text())
    non_continuous = dict(
        v4_manifest, family_id="pm_us_crh_noncont", composition_kind="current_rung_hold",
    )
    (families / "pm_us_crh_noncont.json").write_text(_json.dumps(non_continuous))
    code_noncont = main(
        [
            "--family-id", "pm_us_crh_noncont",
            "--families-dir", str(families),
            "--reason", "attempted clear of a non-continuous family here",
            "--evidence-path", str(_evidence(tmp_path, "b.txt")),
        ],
        env=_env(store_path),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert code_noncont == EXIT_REFUSED

    # (c) mismatched: the manifest's own family_id disagrees with the arg.
    mismatched = dict(v4_manifest, family_id="pm_us_crh_someone_else")
    (families / "pm_us_crh_mismatch.json").write_text(_json.dumps(mismatched))
    code_mismatch = main(
        [
            "--family-id", "pm_us_crh_mismatch",
            "--families-dir", str(families),
            "--reason", "attempted clear of a mismatched family id here",
            "--evidence-path", str(_evidence(tmp_path, "c.txt")),
        ],
        env=_env(store_path),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert code_mismatch == EXIT_REFUSED

    # (d) escaping: a symlink inside `families/` whose target lives outside it.
    outside = tmp_path / "outside_secret.json"
    outside.write_text(_json.dumps(dict(v4_manifest, family_id="pm_us_crh_escape")))
    escape_link = families / "pm_us_crh_escape.json"
    escape_link.symlink_to(outside)
    code_escape = main(
        [
            "--family-id", "pm_us_crh_escape",
            "--families-dir", str(families),
            "--reason", "attempted clear via a families-dir-escaping symlink",
            "--evidence-path", str(_evidence(tmp_path, "d.txt")),
        ],
        env=_env(store_path),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert code_escape == EXIT_REFUSED
    # The symlink target itself must never have been read as a valid escape.
    assert outside.exists()


def test_clear_family_id_and_legacy_are_a_required_mutually_exclusive_group(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "state.db"
    SqliteStateStore(store_path).close()

    # Neither given.
    with pytest.raises(SystemExit) as neither_exc:
        main(
            [
                "--reason", "neither --family-id nor --legacy given here",
                "--evidence-path", str(_evidence(tmp_path, "neither.txt")),
            ],
            env=_env(store_path),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    assert neither_exc.value.code == 2

    # Both given.
    with pytest.raises(SystemExit) as both_exc:
        main(
            [
                "--family-id", "pm_us_crh_v4",
                "--legacy",
                "--reason", "both --family-id and --legacy given here",
                "--evidence-path", str(_evidence(tmp_path, "both.txt")),
            ],
            env=_env(store_path),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    assert both_exc.value.code == 2


def test_clear_family_halt_resolves_manifest_independent_of_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = tmp_path / "state.db"
    _seed_halt(store_path)
    foreign = tmp_path / "foreign_cwd"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    assert not Path("deploy/families").exists()

    code = _run(
        ["--reason", "x" * 40, "--evidence-path", str(_evidence(tmp_path))],
        store_path,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert code == EXIT_OK


def test_clear_status_works_from_foreign_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store_path = tmp_path / "state.db"
    _seed_halt(store_path)
    foreign = tmp_path / "foreign_cwd"
    foreign.mkdir()
    monkeypatch.chdir(foreign)
    out = io.StringIO()

    code = _run(["--status"], store_path, stdout=out, stderr=io.StringIO())

    assert code == EXIT_OK
    assert "halted=True" in out.getvalue()


def test_clear_missing_families_dir_fails_closed_rc2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from breezy.strategy.current_rung_hold import family_id_arg

    store_path = tmp_path / "state.db"
    _seed_halt(store_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(family_id_arg, "_REPO_ROOT", tmp_path / "no_such_root")
    err = io.StringIO()

    code = _run(
        ["--reason", "x" * 40, "--evidence-path", str(_evidence(tmp_path))],
        store_path,
        stdout=io.StringIO(),
        stderr=err,
    )

    assert code == EXIT_REFUSED
    assert "families directory not found" in err.getvalue()


def test_clear_relative_evidence_path_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store_path = tmp_path / "state.db"
    _seed_halt(store_path)
    evidence = _evidence(tmp_path)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as excinfo:
        _run(
            ["--reason", "x" * 40, "--evidence-path", evidence.name],
            store_path,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )

    assert excinfo.value.code == 2
    assert "must be an absolute path" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# FQ loss response F3: clearing the FQ halt is evidenced, audited and CLI-only
# ---------------------------------------------------------------------------

_FQ_ID = "pm_us_crh_fq_v1"
_REPO_ROOT = Path(__file__).resolve().parents[2]
#: The only modules allowed to define or reference `clear_family_halt`: the
#: latch that owns the method and the operator CLI that is its sole caller.
_CLEAR_ALLOWED_FILES = frozenset(
    {
        "src/breezy/strategy/current_rung_hold/trial_day_latch.py",
        "src/breezy/strategy/current_rung_hold/clear_family_halt_cli.py",
    }
)


def _refs_clear_family_halt(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "clear_family_halt":
            return True
        if isinstance(node, ast.Name) and node.id == "clear_family_halt":
            return True
        if isinstance(node, ast.alias) and node.name == "clear_family_halt":
            return True
        if isinstance(node, ast.FunctionDef) and node.name == "clear_family_halt":
            return True
    return False


def test_clear_fq_requires_audit_record_and_is_cli_only(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    _seed_halt(store_path, family_id=_FQ_ID)
    evidence = _evidence(tmp_path)
    reason = "FQ halt cleared after reviewed evidence of the loss response"

    # --reason and --evidence-path are both mandatory to clear.
    for argv in (
        ["--family-id", _FQ_ID, "--evidence-path", str(evidence)],
        ["--family-id", _FQ_ID, "--reason", reason],
    ):
        with pytest.raises(SystemExit) as exc:
            main(argv, env=_env(store_path), stdout=io.StringIO(), stderr=io.StringIO())
        assert exc.value.code == 2
    check = SqliteStateStore(store_path)
    assert check.get(family_halt_key(_FQ_ID)) not in (None, b"cleared")
    check.close()

    # The audit record is written BEFORE the halt row is overwritten.
    writes: list[str] = []
    real_set = SqliteStateStore.set

    def _recording_set(self: SqliteStateStore, key: str, value: bytes) -> None:
        writes.append(key)
        real_set(self, key, value)

    with patch.object(SqliteStateStore, "set", _recording_set):
        code = _run(
            ["--family-id", _FQ_ID, "--reason", reason, "--evidence-path", str(evidence)],
            store_path,
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    assert code == EXIT_OK
    audit_key = _audit_key(CLEAR_TS_NS, _FQ_ID)
    halt_key = family_halt_key(_FQ_ID)
    assert audit_key in writes and halt_key in writes
    assert writes.index(audit_key) < writes.index(halt_key)
    store = SqliteStateStore(store_path)
    audit = json.loads((store.get(audit_key) or b"{}").decode("utf-8"))
    store.close()
    assert audit["reason"] == reason
    assert len(audit["evidenceSha256"]) == 64

    # CLI-only: no module other than the latch and the CLI references it.
    offenders = []
    for root in ("src", "scripts"):
        for path in sorted((_REPO_ROOT / root).rglob("*.py")):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if rel in _CLEAR_ALLOWED_FILES:
                continue
            if _refs_clear_family_halt(ast.parse(path.read_text(encoding="utf-8"))):
                offenders.append(rel)
    assert offenders == []
