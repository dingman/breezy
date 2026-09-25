"""Emit an evidence-gated promotion PROPOSAL. Never arms anything.

Reads replay results, the champion KILL clock, and the live tally store.
Writes only under ``derived/promotion/proposals/<content-hash>/``. Does not
edit ``deploy/families/``, does not set ``sending_family_id``, and does not
clear a family halt.

Exit 0: ``NO_PROPOSAL``, ``PROPOSAL_INCOMPLETE``, or ``PROPOSAL`` (a data
verdict), including an idempotent re-run. Exit 2: the run refuses
(clock integrity, unknown replay schema, unsafe output, hash collision).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, replace
from io import StringIO
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from breezy.analysis.promotion_criteria import (  # noqa: E402
    CRITERIA_MODULE_VERSION,
    RunRefusal,
    champion_kill_clock_path,
    evaluate_c_estimator,
    evaluate_c_kill,
    evaluate_c_n,
    evaluate_c_paired,
    evaluate_c_pin,
    evaluate_c_revision,
    evaluate_c_stations,
    evaluate_c_validity,
    render_rationale,
    assemble_outcome,
)
from breezy.analysis.replay_results import (  # noqa: E402
    DuplicateReplayResultError,
    UnknownReplayResultSchemaError,
    read_replay_results,
)
from breezy.analysis.replay_sufficiency import (  # noqa: E402
    UnknownReplaySufficiencySchemaError,
    read_replay_sufficiency,
)
from breezy.persistence.family_manifest import (  # noqa: E402
    FamilyManifest,
    FamilyManifestError,
    _UNPINNED_SHA256,
    dump_family_manifest,
    load_family_manifest,
    write_family_manifest,
)

_SCRIPT_DIR = Path(__file__).resolve().parent

#: The lifting-ruling path + sha256 check lives HERE, in scripts/, never in
#: `src/breezy/analysis/promotion_criteria.py`: `src/breezy` is the EVIDENCE
#: ONLY -- NEVER INGEST boundary
#: (`tests/unit/test_probe_containment.py::test_no_module_under_src_reads_docs_evidence`)
#: and must carry no `docs/evidence` path as a runtime constant. This
#: offline, never-arming script is the sanctioned place for that read.
LIFTING_RULING_RELATIVE = Path("docs/evidence/RULING_promotion_criteria_provisional_lift.md")
#: sha256 of the unissued-ruling sentence. Not the hash of any file in the
#: tree; a lift requires this constant to change with the ruling artefact.
LIFTING_RULING_SHA256 = "db14b89647c744ce1ac5b7e6f890caa172d61e9119ba133a22d51da00eda114b"


def resolve_criteria_status(repo_root: Path) -> str:
    """LIFTED only when the pinned ruling file's sha256 matches. Never raises."""
    path = repo_root / LIFTING_RULING_RELATIVE
    try:
        raw = path.read_bytes()
    except OSError:
        return "PROVISIONAL"
    digest = hashlib.sha256(raw).hexdigest()
    if digest != LIFTING_RULING_SHA256:
        return "PROVISIONAL"
    return "LIFTED"


class ProposalRefusal(Exception):
    """Refusing to emit an unsafe proposal. Not a data verdict."""


def refuse_unsafe_proposal(payload: dict[str, object], *, sending_family_id: str) -> None:
    """The three hard content refusals, before any byte is written."""
    if payload.get("status") == "REGISTERED":
        raise ProposalRefusal("refusing to emit status REGISTERED")
    family_id = payload.get("family_id")
    if family_id == sending_family_id:
        raise ProposalRefusal(
            f"refusing to emit family_id equal to sending_family_id {sending_family_id}"
        )


def _derived_root() -> Path:
    env = os.environ.get("BREEZY_LIVE_TALLY_OUTPUT_DIR")
    if env:
        return Path(env)
    return Path.home() / ".local/share/breezy/derived"


def _assert_output_root(root: Path) -> None:
    resolved = root.resolve()
    if resolved.name != "promotion" or resolved.parent.name != "derived":
        raise ProposalRefusal(f"refusing to write outside derived/promotion (got {resolved})")


def _sha(path: Path | None) -> str:
    if path is None or not path.is_file():
        return "ABSENT"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _content_hash(parts: list[tuple[str, str]]) -> str:
    body = "\n".join(f"{label}={value}" for label, value in parts)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _fill_count(db: Path | None, manifest: FamilyManifest):
    def _call() -> int | None:
        if db is None:
            return None
        if str(_SCRIPT_DIR) not in sys.path:
            sys.path.insert(0, str(_SCRIPT_DIR))
        from fill_time_count import count_filled_takes

        return count_filled_takes(
            db,
            family_prefix=manifest.trial_id_prefix,
            since_climate_day=manifest.d0_climate_day,
        )

    return _call


def _build_proposal(champion: FamilyManifest, *, on_date: dt.date) -> FamilyManifest:
    d0 = on_date.isoformat()
    if d0 <= champion.d0_climate_day:
        d0 = (
            dt.date.fromisoformat(champion.d0_climate_day) + dt.timedelta(days=1)
        ).isoformat()
    family_id = f"{champion.family_id}_d{d0.replace('-', '')}"
    if family_id == champion.family_id:
        family_id = f"{family_id}_proposal"
    return replace(
        champion,
        family_id=family_id,
        trial_id_prefix=f"continuous_rung_hold/{family_id}/trial/",
        d0_climate_day=d0,
        status="DRAFT_NOT_REGISTERED",
        boundary_inputs_sha256=_UNPINNED_SHA256,
        density_artefact_sha256=_UNPINNED_SHA256,
        manifest_sha256=_UNPINNED_SHA256,
    )


def _read_census(path: Path | None):
    if path is None or not path.is_file():
        return None
    rows = read_replay_sufficiency(path)
    return {(row.station, row.climate_day): row for row in rows}


def _read_drift(path: Path | None):
    if path is None or not path.exists():
        return None
    if str(_SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPT_DIR))
    from replay_daily_runner import read_replay_drift

    records = read_replay_drift(path)
    return frozenset((record.station, record.climate_day) for record in records)


def _parse(argv: Sequence[str]) -> argparse.Namespace:
    derived = _derived_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--replay-results", type=Path, default=derived / "replay" / "replay_results.jsonl")
    parser.add_argument(
        "--replay-sufficiency",
        type=Path,
        default=derived / "replay" / "replay_sufficiency.jsonl",
    )
    parser.add_argument("--replay-drift", type=Path, default=derived / "replay" / "replay_drift.jsonl")
    parser.add_argument("--tally-output-dir", type=Path, default=derived)
    parser.add_argument("--kill-clock", type=Path, default=None)
    parser.add_argument("--on-date", type=str, default=None)
    parser.add_argument("--exec-state-db", type=Path, default=None)
    parser.add_argument("--scored-trials-dir", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    try:
        _assert_output_root(args.output_root)
    except ProposalRefusal as exc:
        print(exc, file=sys.stderr)
        return 2
    try:
        champion = load_family_manifest(args.family_manifest)
    except (FamilyManifestError, OSError) as exc:
        print(f"NO_CHAMPION_MANIFEST: {exc}", file=sys.stderr)
        return 2

    on_date = (
        dt.date.fromisoformat(args.on_date)
        if args.on_date
        else dt.datetime.now(dt.UTC).date()
    )
    try:
        results = (
            read_replay_results(args.replay_results) if args.replay_results.is_file() else ()
        )
    except (UnknownReplayResultSchemaError, DuplicateReplayResultError, OSError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        return 2
    try:
        census = _read_census(args.replay_sufficiency)
    except UnknownReplaySufficiencySchemaError as exc:
        print(exc, file=sys.stderr)
        return 2
    try:
        drift = _read_drift(args.replay_drift)
    except (OSError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        return 2

    clock = args.kill_clock
    if clock is None:
        clock = champion_kill_clock_path(args.tally_output_dir, on_date=on_date)
    exec_db = args.exec_state_db
    if exec_db is None:
        env_db = os.environ.get("POLYMARKET_US_EXEC_STATE_DB")
        exec_db = Path(env_db) if env_db else None
    store = args.scored_trials_dir
    if store is None:
        root = Path(
            os.environ.get(
                "BREEZY_SCORED_TRIALS_DIR",
                str(Path.home() / ".local/share/breezy/derived/scored_trials"),
            )
        )
        store = root / champion.family_id

    try:
        kill = evaluate_c_kill(
            clock_path=clock,
            champion=champion,
            now_unix=dt.datetime.now(dt.UTC).timestamp(),
            fill_count=_fill_count(exec_db, champion),
            exec_state_db=exec_db or Path("POLYMARKET_US_EXEC_STATE_DB"),
        )
    except RunRefusal as exc:
        print(f"{exc.reason}: {exc.detail}", file=sys.stderr)
        return 2

    validity = evaluate_c_validity(
        results=results,
        census_by_station_day=census,
        drift_station_days=drift,
        results_path=str(args.replay_results),
        census_path=str(args.replay_sufficiency),
        drift_path=str(args.replay_drift),
    )
    proposal = _build_proposal(champion, on_date=on_date)
    rows = (
        kill,
        evaluate_c_paired(
            challenger_draws=None,
            champion_draws=(),
            d0_climate_day=champion.d0_climate_day,
            replay_results_path=str(args.replay_results),
        ),
        evaluate_c_estimator(store_dir=store, validity_allows_edge=validity.verdict == "true"),
        evaluate_c_n(store_dir=store),
        evaluate_c_revision(champion=champion, proposal=proposal),
        evaluate_c_pin(proposal),
        validity,
        evaluate_c_stations(proposal.stations),
    )
    status = resolve_criteria_status(args.repo_root)
    verdict = assemble_outcome(rows, criteria_status=status)
    payload = dump_family_manifest(proposal)
    try:
        refuse_unsafe_proposal(payload, sending_family_id=champion.family_id)
    except ProposalRefusal as exc:
        print(exc, file=sys.stderr)
        return 2

    parts = [
        ("criteria_module_version", CRITERIA_MODULE_VERSION),
        ("on_date", on_date.isoformat()),
        ("family_manifest", _sha(args.family_manifest)),
        ("replay_results", _sha(args.replay_results)),
        ("replay_sufficiency", _sha(args.replay_sufficiency)),
        ("replay_drift", _sha(args.replay_drift)),
        ("kill_clock", _sha(clock)),
        ("scored_trials_provenance", _sha(store / "provenance.json")),
    ]
    digest = _content_hash(parts)
    dest = args.output_root / "proposals" / digest
    criteria_body = json.dumps(
        {
            "content_hash": digest,
            "criteria_module_version": CRITERIA_MODULE_VERSION,
            "criteria_status": verdict.criteria_status,
            "failed": list(verdict.failed),
            "inert": [
                {"id": row.id, "inert_reason": row.inert_reason}
                for row in verdict.rows
                if row.verdict == "INERT"
            ],
            "outcome": verdict.outcome,
            "predicates": [asdict(row) for row in verdict.rows],
        },
        indent=2,
        sort_keys=True,
    ) + "\n"
    criteria_path = dest / "criteria.json"
    if dest.exists():
        try:
            existing = criteria_path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"hard error: cannot read {criteria_path}: {exc}", file=sys.stderr)
            return 2
        if existing != criteria_body:
            print(
                "hard error: criteria.json bytes differ under an unchanged content hash "
                f"{digest}",
                file=sys.stderr,
            )
            return 2
        print(f"{verdict.outcome}({digest}) unchanged")
        return 0

    dest.mkdir(parents=True, exist_ok=False)
    criteria_path.write_text(criteria_body, encoding="utf-8")
    write_family_manifest(dest / "proposal.json", proposal)
    (dest / "RATIONALE.md").write_text(render_rationale(verdict), encoding="utf-8")
    (dest / "INPUTS.json").write_text(
        json.dumps({"parts": parts}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evidence = dest / "evidence"
    evidence.mkdir()
    for label, path in (
        ("replay_results.jsonl", args.replay_results),
        ("replay_sufficiency.jsonl", args.replay_sufficiency),
        ("replay_drift.jsonl", args.replay_drift),
        ("kill_clock.json", clock),
        ("family_manifest.json", args.family_manifest),
    ):
        if path.is_file():
            target = evidence / label
            target.write_bytes(path.read_bytes())
            (evidence / f"{label}.sha256").write_text(_sha(path) + "\n", encoding="utf-8")
    failed = ",".join(verdict.failed) if verdict.failed else "-"
    inert = ",".join(verdict.inert) if verdict.inert else "-"
    if verdict.outcome == "PROPOSAL":
        print(f"PROPOSAL({digest})")
    else:
        print(f"{verdict.outcome}({failed}) INERT({inert})")
    return 0


def main_capture(argv: Sequence[str]) -> tuple[int, str]:
    buffer = StringIO()
    with redirect_stdout(buffer), redirect_stderr(buffer):
        code = main(argv)
    return code, buffer.getvalue()


if __name__ == "__main__":
    raise SystemExit(main())
