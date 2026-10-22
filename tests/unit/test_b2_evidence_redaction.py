"""ARM B2 -- a regex scan over ``docs/evidence/b2/`` that forbids secret-shaped strings.

Authority: ``plan_r2_delta.md`` D3 ("a regex test over the evidence dir"). The patterns here are
this test's own, independent of the script's writer-side guard: a second, stricter pair of eyes.
Every evidence file must be mode 0600, valid JSON, and free of anything shaped like a header,
a signature, a key id, a key, a URL with a query or userinfo, or a raw order body.

The directory does not exist until the control has run; the scan is then vacuous on purpose,
and the non-vacuity tests below prove the scanner trips on every forbidden shape and passes a
document the real script produced.
"""

from __future__ import annotations

import asyncio
import json
import re
import stat
from pathlib import Path
from typing import Any, Final

import pytest

from tests.unit import b2_control_fakes as fk


@pytest.fixture(scope="module")
def ctl() -> Any:
    return fk.load_control()


REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_DIR: Final[Path] = REPO_ROOT / "docs" / "evidence" / "b2"

FORBIDDEN: Final[dict[str, re.Pattern[str]]] = {
    "pem": re.compile(r"-----BEGIN"),
    "base64-run": re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),
    "hex-64": re.compile(r"\b[0-9a-fA-F]{64}\b"),
    "uuid": re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
    ),
    "pm-header": re.compile(r"x-pm-", re.IGNORECASE),
    "auth-words": re.compile(r"authorization|bearer|password|passwd|api[_-]?key", re.IGNORECASE),
    "secret-words": re.compile(r"secret|signature|private[_-]?key|key[_-]?id", re.IGNORECASE),
    "url-query": re.compile(r"https?://[^\s\"]*\?"),
    "url-userinfo": re.compile(r"https?://[^/\s\"]*@"),
    "raw-body-field": re.compile(r"\"(?:body|headers|response_body|raw)\"\s*:", re.IGNORECASE),
}


def scan_text(text: str) -> list[str]:
    return sorted(name for name, pattern in FORBIDDEN.items() if pattern.search(text))


def evidence_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.json")) if directory.is_dir() else []


def check_directory(directory: Path) -> list[str]:
    """Findings for every file under ``directory``: shape hits, bad mode, bad JSON."""
    findings: list[str] = []
    for path in evidence_files(directory):
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != 0o600:
            findings.append(f"{path.name}: mode {oct(mode)}")
        text = path.read_text(encoding="utf-8")
        try:
            json.loads(text)
        except ValueError:
            findings.append(f"{path.name}: not JSON")
        findings.extend(f"{path.name}: {hit}" for hit in scan_text(text))
    return findings


def test_the_committed_b2_evidence_directory_is_free_of_secret_shapes() -> None:
    assert check_directory(EVIDENCE_DIR) == []


@pytest.mark.parametrize(
    ("label", "planted"),
    [
        ("pem", "-----BEGIN PRIVATE KEY-----"),
        ("base64-run", "A" * 44 + "=="),
        ("hex-64", "ab" * 32),
        ("uuid", "11111111-2222-3333-4444-555555555555"),
        ("pm-header", "X-PM-Access-Key"),
        ("auth-words", "Authorization"),
        ("secret-words", "signature"),
        ("url-query", "https://api.example.invalid/v1/markets?limit=100"),
        ("url-userinfo", "https://user:pass@api.example.invalid/v1"),
        ("raw-body-field", '"body": "{}"'),
    ],
)
def test_the_scanner_trips_on_each_forbidden_shape(label: str, planted: str) -> None:
    assert label in scan_text(planted)


def test_the_scanner_flags_a_loose_mode_and_non_json_file(tmp_path: Path) -> None:
    loose = tmp_path / "a.json"
    loose.write_text("{}", encoding="utf-8")
    loose.chmod(0o644)
    bad = tmp_path / "b.json"
    bad.write_text("not json", encoding="utf-8")
    bad.chmod(0o600)
    findings = check_directory(tmp_path)
    assert any("a.json: mode" in f for f in findings)
    assert any("b.json: not JSON" in f for f in findings)


def test_a_document_the_real_script_produced_passes_the_scan(
    ctl: Any,
    tmp_path: Path,
) -> None:
    rig = fk.Rig(ctl)
    deps = ctl.Deps(
        today_utc=lambda: "2026-10-22",
        list_units=lambda: "breezy-trade-supervisor.service loaded active running x\n",
        probe_node=lambda: None,
        load_env=dict,
        build_session=lambda _env: rig.session,
        sleep=rig.venue.sleep,
        evidence_dir=tmp_path / "b2",
        stamp=lambda: "20261022T120000Z",
    )
    assert asyncio.run(ctl.run("2026-10-22", deps)) == 0
    assert len(evidence_files(tmp_path / "b2")) == 1
    assert check_directory(tmp_path / "b2") == []


def test_the_script_writer_refuses_every_shape_this_scanner_forbids(
    ctl: Any,
    tmp_path: Path,
) -> None:
    doc = fk.Rig(ctl).run().document
    leaks = [
        fk.KEY_ID_SENTINEL,
        fk.SIGNATURE_SENTINEL,
        "X-PM-Access-Key",
        "-----BEGIN PRIVATE KEY-----",
        "ab" * 32,
        "https://api.example.invalid/v1/markets?limit=100",
    ]
    for index, leak in enumerate(leaks):
        with pytest.raises(ValueError, match="secret"):
            ctl.write_evidence({**doc, "failure": leak}, tmp_path / "ev", stamp=f"s{index}")
