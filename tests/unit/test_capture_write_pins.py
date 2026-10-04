"""AUT-1 WP5 stage 3, S2: the runtime write pins of the units that share a data directory
(design r3 D5, S3-R16, S3-R35, RC-1).

These tests do not read the code for what it might do; they run it and record what it DID write:

* the settlement closure shares ``catalog/quote_tape/decisions`` with the live node, so its only
  writes are ``replace_atomic`` onto ``settlement_<day>.jsonl`` names (the old bytes kept as a
  prefix of the new bytes, the temp file in the same directory) and an ``O_CREAT`` of the literal
  ``LOCK_FILE``, through the ``replace`` seam of ``run_settlement``;
* the audit writes capture-family HEALTH verdicts into ``derived/verdicts`` and nothing else
  there, and the live-proof unit writes no verdict at all.
"""

import ast
import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.analysis import capture_audit as audit
from breezy.analysis import capture_live_proof_cli as live_cli
from breezy.analysis import capture_settlement as cs
from breezy.persistence.autonomy.single_read import replace_atomic
from tests.support import capture_audit_fixtures as fx
from tests.support import capture_audit_w3_fixtures as w3
from tests.support.capture_audit_run_support import Offers, fake_gather, quiet_duties, run
from tests.support.capture_audit_w3_fixtures import stub_legs
from tests.unit.test_capture_settlement import SITES, TODAY, VENUE, _climate_day

_SETTLEMENT_NAME: Final = re.compile(r"\Asettlement_\d{4}-\d{2}-\d{2}\.jsonl\Z")
_SRC: Final = Path(audit.__file__).parent


class _OsProxy:
    """``os`` as the settlement module sees it, noting every ``os.open`` that may create a file."""

    def __init__(self, creations: list[tuple[str, int]]) -> None:
        self._creations = creations

    def open(self, path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if flags & os.O_CREAT:
            self._creations.append((os.fspath(path), flags))
        return os.open(path, flags, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(os, name)


def _read_day(sha_for: dict[tuple[str, dt.date], str]) -> Any:
    def read(_base: Path, _venue: str, site: cs.SettlementSite, day: dt.date) -> Any:
        return _climate_day(site.cli_location, day, sha=sha_for.get((site.cli_location, day)))

    return read


def _run(
    decisions: Path, tmp_path: Path, replaced: list[tuple[Path, bytes, Path]], read: Any
) -> Any:
    def recording_replace(path: Path, data: bytes, *, root: Path, mode: int) -> None:
        replaced.append((path, data, root))
        replace_atomic(path, data, root=root, mode=mode)

    return cs.run_settlement(
        venue=VENUE,
        today=TODAY,
        decisions_dir=decisions,
        catalog_base=tmp_path / "catalog",
        sites=SITES,
        offer=Offers(),
        read_day=read,
        replace=recording_replace,
    )


def test_settlement_writes_only_settlement_names_prefix_preserved_lock_only_ocreat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decisions = tmp_path / "decisions"
    decisions.mkdir(mode=0o700)
    creations: list[tuple[str, int]] = []
    monkeypatch.setattr(cs, "os", _OsProxy(creations))
    first: list[tuple[Path, bytes, Path]] = []
    assert _run(decisions, tmp_path, first, _read_day({})).appended == 14
    before = {p.name: p.read_bytes() for p in decisions.iterdir() if p.name != cs.LOCK_FILE}

    again: list[tuple[Path, bytes, Path]] = []  # a corrected record for one station-day
    corrected = _read_day({("NYC", TODAY - dt.timedelta(days=2)): "ee" * 32})
    assert _run(decisions, tmp_path, again, corrected).appended == 1

    for path, data, root in [*first, *again]:
        assert path.parent == decisions and root == decisions  # the temp file lives beside it
        assert _SETTLEMENT_NAME.fullmatch(path.name), path.name
    (path, data, _root) = again[0]
    assert (
        len(again) == 1
        and data.startswith(before[path.name])
        and len(data) > len(before[path.name])
    )
    names = sorted(p.name for p in decisions.iterdir())
    assert all(_SETTLEMENT_NAME.fullmatch(n) or n == cs.LOCK_FILE for n in names), names
    assert cs.LOCK_FILE in names  # the control: the lock file really was created
    assert creations and {Path(p).name for p, _f in creations} == {cs.LOCK_FILE}
    assert {Path(p).parent for p, _f in creations} == {decisions}


def test_the_write_pin_would_catch_a_stray_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive control: the recording proxy does see an ``O_CREAT`` of another name."""
    decisions = tmp_path / "decisions"
    decisions.mkdir(mode=0o700)
    creations: list[tuple[str, int]] = []
    proxy = _OsProxy(creations)
    monkeypatch.setattr(cs, "os", proxy)
    fd = proxy.open(decisions / "stray.tmp", os.O_WRONLY | os.O_CREAT, 0o600)
    os.close(fd)
    assert [Path(p).name for p, _f in creations] == ["stray.tmp"]


# -- the verdicts ----------------------------------------------------------------------------------


def _files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def test_audit_and_live_proof_write_only_capture_family_verdicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.make_root(tmp_path)
    monkeypatch.setattr(audit, "PRODUCER_SOURCE_SHA256", {audit.PRODUCER_ID: "ab" * 32})
    stub_legs(monkeypatch)
    quiet_duties(monkeypatch)
    fake_gather(monkeypatch)
    assert run(root, Offers()) == 0
    written = _files(root)
    verdict_files = sorted(f for f in written if f.startswith("derived/"))
    assert verdict_files, "the audit wrote no verdict: the pin would be vacuous"
    for name in verdict_files:
        assert name.startswith(f"derived/verdicts/{fx.FAMILY_ID}/"), name
        body = json.loads((root / name).read_text())
        assert body["kind"] == "HEALTH" and body["detector"] == audit.DETECTOR
        assert body["subject_family_id"] == fx.FAMILY_ID
        assert body["declared_action_class"] == "NONE"
    assert all(
        f.startswith(("derived/", f"evidence/capture/audit/{fx.FAMILY_ID}/")) for f in written
    )

    code = live_cli._main(
        ["--data-root", str(root), f"--family-id={fx.FAMILY_ID}"],
        offer=Offers(),
        clock=lambda: w3.NOW_NS,
    )
    assert code == 0
    added = _files(root) - written
    assert added, "the live-proof run wrote nothing: the pin would be vacuous"
    assert all(f.startswith("evidence/capture/live_proof/") for f in added), sorted(added)
    assert not any(f.startswith("derived/") for f in added)


def _calls(path: Path, callee: str) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name | ast.Attribute)
        and (node.func.id if isinstance(node.func, ast.Name) else node.func.attr) == callee
    ]


def test_only_the_health_verdict_site_in_the_audit_writes_a_verdict() -> None:
    (call,) = _calls(_SRC / "capture_audit.py", "write_verdict")
    keywords = {k.arg: ast.unparse(k.value) for k in call.keywords}
    assert ast.unparse(call.args[1]).startswith("Verdict(")
    verdict = call.args[1]
    assert isinstance(verdict, ast.Call)
    fields = {k.arg: ast.unparse(k.value) for k in verdict.keywords}
    assert fields["detector"] == "DETECTOR" and fields["kind"] == "VerdictKind.HEALTH"
    assert fields["declared_action_class"] == "ActionClass.NONE" and not keywords


@pytest.mark.parametrize("module", ["capture_live_proof.py", "capture_live_proof_cli.py"])
def test_the_live_proof_modules_hold_no_verdict_writer(module: str) -> None:
    source = (_SRC / module).read_text(encoding="utf-8")
    assert not _calls(_SRC / module, "write_verdict")
    assert "persistence.autonomy.verdict" not in source and "derived" not in source


# -- the closures of the new modules (S3-R16, S3-R37) ----------------------------------------------

_NEW_MODULES: Final = (
    "capture_live_proof.py",
    "capture_live_proof_cli.py",
    "capture_aut6_contract.py",
    "capture_audit_io.py",
)
_FORBIDDEN_IMPORT_PREFIXES: Final = (
    "breezy.adapters",
    "breezy.ingest",
    "httpx",
    "requests",
    "aiohttp",
    "urllib3",
    "nautilus_trader",
)
_FORBIDDEN_IMPORT_FRAGMENTS: Final = ("resolver", "exec_store", "exec_view", "permit")
_FORBIDDEN_REFERENCES: Final = ("permit", "exec_store", "exec_view", "orders_enabled")


def _imported(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
            found.extend(f"{node.module}.{a.name}" for a in node.names)
    return found


def _code_strings(tree: ast.AST) -> list[str]:
    """Every string constant that is not a docstring."""
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _identifiers(tree: ast.AST) -> list[str]:
    names = [n.id for n in ast.walk(tree) if isinstance(n, ast.Name)]
    return names + [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)]


def _closure_findings(source: str) -> list[str]:
    tree = ast.parse(source)
    found = [
        f"import {name}"
        for name in _imported(tree)
        if name.startswith(_FORBIDDEN_IMPORT_PREFIXES)
        or any(fragment in name for fragment in _FORBIDDEN_IMPORT_FRAGMENTS)
    ]
    found += [
        f"string {text!r}"
        for text in _code_strings(tree)
        if text == "state" or text.startswith("state/") or "permit" in text.lower()
    ]
    found += [
        f"name {name}"
        for name in _identifiers(tree)
        if any(word in name.lower() for word in _FORBIDDEN_REFERENCES)
    ]
    return found


def test_new_modules_reference_no_state_exec_or_permit() -> None:
    for module in _NEW_MODULES:
        source = (_SRC / module).read_text(encoding="utf-8")
        assert len(ast.parse(source).body) > 3, f"{module} is a stub: the scan would be vacuous"
        assert "NotImplementedError" not in source, module
        assert _closure_findings(source) == [], module


@pytest.mark.parametrize(
    "planted",
    [
        "import httpx\n",
        "from breezy.adapters.polymarket_us import recorder_watchdog\n",
        "from breezy.ingest import nbm_quantile_actor\n",
        "from breezy.analysis.capture_audit_exec_view import read_exec_view\n",
        "from breezy.runtime.order_permit import mint\n",
        "ROOT = ('state', 'exec.db')\nDIR = 'state'\n",
        "PATH = 'state/exec_store'\n",
        "def f(permit):\n    return permit\n",
        "def f(x):\n    return x.orders_enabled\n",
    ],
)
def test_the_closure_scan_flags_a_planted_reference(planted: str) -> None:
    """Positive control: each planted line is a finding, so a clean real file means something."""
    assert _closure_findings(planted)
