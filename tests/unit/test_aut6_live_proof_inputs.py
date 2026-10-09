"""AUT-6 WP9: the loader reads evidence read-only and writes only its own artefact."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from breezy.analysis.aut6_live_proof_inputs import (
    artefact_name,
    build_report,
    main,
    write_artefact,
)

NS = 1_000_000_000
ASOF = dt.date(2026, 11, 2)


def _put(root: Path, rel: str, body: object) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body) + "\n", encoding="utf-8")


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


def _seed(root: Path) -> None:
    day = ASOF - dt.timedelta(days=1)
    end = int(dt.datetime.combine(ASOF, dt.time(), dt.UTC).timestamp()) * NS
    _put(
        root,
        f"evidence/unit_health/day_{day}.json",
        {
            "passes_completed": 143,
            "passes_unknown": 0,
            "max_passes_unknown_streak": 0,
            "unexplained_failed_units": {"count": 0, "names": []},
            "produced_at_ns": end - 60 * NS,
        },
    )
    _put(
        root,
        f"evidence/alerts/{day}/{end - 3600 * NS}_canary_d.json",
        {
            "schema": "alert_delivery/v1",
            "attempt_kind": "canary",
            "delivered": True,
            "drill": False,
            "event": "autonomy_canary",
            "severity": "INFO",
            "site": "global",
            "ts_ns": end - 3600 * NS,
        },
    )
    log = root / "logs" / "breezy-trade-20261101T000000Z.log"
    log.parent.mkdir(parents=True)
    expiry = end - 7200 * NS
    log.write_text(
        f"2026-11-01 14:00:00,000 [INFO] breezy.app.trade.boot: live-trading permit issued "
        f"issued_at_ns=1 expires_at_ns={expiry} ttl_s=36000\n"
        "2026-11-01T22:00:10.000000000Z [INFO] x: entry_veto reason=permit_lapsed\n",
        encoding="utf-8",
    )


def test_loader_builds_report_from_evidence_and_writes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "data"
    _seed(root)
    before = _snapshot(root)
    report = build_report(root, ASOF, node_log_dir=root / "logs")
    assert _snapshot(root) == before
    assert report["classes"]["ALERT"]["satisfied"] is True
    assert report["classes"]["ENTRY_VETO"]["satisfied"] is True  # veto 10 s after expiry
    assert report["verdict"] == "NOT_YET"
    assert "aut5b_ruling_not_filed" in report["blockers"]
    assert report["citations"]["rollups"] == [(ASOF - dt.timedelta(days=1)).isoformat()]
    assert report["citations"]["node_logs"] == ["breezy-trade-20261101T000000Z.log"]


def test_artefact_is_written_atomically_to_its_own_path_only(tmp_path: Path) -> None:
    root = tmp_path / "data"
    _seed(root)
    out = tmp_path / "out"
    report = build_report(
        root, ASOF, aut5b_ruling_date="2026-10-20", ing2_amend2_landed_date="2026-10-20"
    )
    path = write_artefact(out, report)
    assert path == out / "aut6" / artefact_name(report)
    assert path.name == f"live_proof_2026-10-21_{ASOF - dt.timedelta(days=1)}.json"
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == "aut6_live_proof/v1"
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name]  # no temp left behind
    assert not any(out.rglob(".tmp-*"))
    assert write_artefact(out, report) == path  # idempotent replace


def test_main_writes_the_artefact_and_prints_the_verdict(tmp_path: Path) -> None:
    root = tmp_path / "data"
    _seed(root)
    out = tmp_path / "out"
    code = main(
        [
            "--data-root",
            str(root),
            "--out-root",
            str(out),
            "--asof",
            ASOF.isoformat(),
            "--node-log-dir",
            str(root / "logs"),
        ]
    )
    assert code == 0
    assert len(list((out / "aut6").glob("live_proof_*.json"))) == 1
    assert sorted(os.listdir(root)) == ["evidence", "logs"]
