"""Executable gates for the archived backfill separation contract."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Final

from breezy.ingest.shared_state import DEFAULT_ALLOWED_HOSTS
from tests.support.host_python import resolve_sibling_entrypoint

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SRC_ROOT: Final[Path] = REPO_ROOT / "src" / "breezy"
CATALOG_MODULE: Final[Path] = SRC_ROOT / "persistence" / "catalog.py"
GENERATED_INTERMEDIARY: Final[Path] = (
    SRC_ROOT / "persistence" / "_gate_archive_intermediary.py"
)

_GENERATED_SOURCE = '''"""Synthesised by the archive separation gate test; deleted after."""

from __future__ import annotations

from breezy.persistence.archive_catalog import read_archived_climate_days

__all__ = ["read_archived_climate_days"]
'''

_CATALOG_IMPORT = "\nfrom breezy.persistence import _gate_archive_intermediary\n"


def _run_lint_imports() -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "UV_CACHE_DIR": "/tmp/uv-cache"}
    # WT-VENV: derived from the resolved interpreter's own `bin/`, not
    # `REPO_ROOT` -- a worktree has no `.venv` of its own.
    return subprocess.run(
        [str(resolve_sibling_entrypoint("lint-imports"))],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_lint_imports_catches_archived_records_through_indirect_chain() -> None:
    """Separation mutant: `allow_indirect_imports = true` or readers in catalog."""
    original_catalog = CATALOG_MODULE.read_text(encoding="utf-8")
    GENERATED_INTERMEDIARY.write_text(_GENERATED_SOURCE, encoding="utf-8")
    CATALOG_MODULE.write_text(original_catalog + _CATALOG_IMPORT, encoding="utf-8")

    try:
        result = _run_lint_imports()
    finally:
        CATALOG_MODULE.write_text(original_catalog, encoding="utf-8")
        GENERATED_INTERMEDIARY.unlink(missing_ok=True)

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "Settlement and strategy code never reaches archived backfill records" in output
    assert "breezy.ingest.nws_actor" in output
    assert "breezy.persistence.archive_catalog" in output


def test_archive_forbidden_contract_is_explicitly_indirect_strict() -> None:
    """Separation mutant: silently relying on or weakening the default."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert (
        'name = "Settlement and strategy code never reaches archived backfill records"' in pyproject
    )
    assert "allow_indirect_imports = false" in pyproject
    assert "breezy.persistence.archive_catalog" in pyproject
    assert "breezy.ingest.archive_records" in pyproject


SETTLEMENT_HOST: Final[str] = "api.weather.gov"
IEM_HOST: Final[str] = "mesonet.agron.iastate.edu"

#: WP-12c. The ONE module in `src/` allowed to name the IEM host: the forecast
#: FALLBACK transport, which carries its own named, paced, distinct
#: `allowed_hosts` and is never the live primary (NBM direct is).
#: An exact set, not a prefix -- a second module naming the host fails here.
IEM_HOST_ALLOWED_MODULES: Final[frozenset[str]] = frozenset(
    {"src/breezy/ingest/iem_mos_fallback_transport.py"}
)


def is_settlement_module(rel_path: str, source: str) -> bool:
    """A settlement module: it lives in `settlement/` or it names the NWS origin."""
    return rel_path.startswith("src/breezy/settlement/") or SETTLEMENT_HOST in source


def find_iem_host_in_settlement_modules(
    entries: list[tuple[str, str]],
) -> list[str]:
    """Report every SETTLEMENT module that names the IEM host.

    This is the rule WP-12c re-scoped, and it is still a real constraint:
    the mutant the original assertion protected against -- *"moving IEM
    retrieval into `src/breezy`"* in its own words -- was about the
    SETTLEMENT transports, whose hosts stay NWS-only. Banning the string
    repo-wide also banned the legitimate, contained forecast fallback.
    """
    return [
        f"{rel_path}: settlement module names the IEM host"
        for rel_path, source in entries
        if is_settlement_module(rel_path, source) and IEM_HOST in source
    ]


def _src_entries() -> list[tuple[str, str]]:
    return [
        (path.relative_to(REPO_ROOT).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(SRC_ROOT.rglob("*.py"))
    ]


def test_settlement_transport_hosts_stay_nws_only() -> None:
    """Separation mutant: moving IEM retrieval into a SETTLEMENT module.

    Settlement transports stay NWS-only. The forecast fallback is a named,
    paced, distinct `allowed_hosts` in `ingest/iem_mos_fallback_transport.py`
    (WP-12c) and is NOT a settlement surface.
    """
    assert DEFAULT_ALLOWED_HOSTS == frozenset({SETTLEMENT_HOST})

    assert find_iem_host_in_settlement_modules(_src_entries()) == []


def test_the_settlement_host_rule_still_bites() -> None:
    """Mutation proof: a settlement module naming the IEM host FAILS.

    Both shapes of settlement module are mutated -- one classified by its
    package, one by the NWS origin it names -- so the re-scoping cannot be
    satisfied by a module simply moving out of `settlement/`.
    """
    by_package = ("src/breezy/settlement/mutant.py", f'HOST = "{IEM_HOST}"\n')
    by_origin = (
        "src/breezy/ingest/mutant_transport.py",
        f'HOSTS = {{"{SETTLEMENT_HOST}", "{IEM_HOST}"}}\n',
    )

    assert len(find_iem_host_in_settlement_modules([by_package])) == 1
    assert len(find_iem_host_in_settlement_modules([by_origin])) == 1
    assert find_iem_host_in_settlement_modules([("src/breezy/ingest/ok.py", "X = 1\n")]) == []


def test_only_the_named_fallback_module_may_name_the_iem_host() -> None:
    """The re-scoping is not a blanket permit: the allowance is one exact path."""
    namers = {
        rel_path for rel_path, source in _src_entries() if IEM_HOST in source
    }

    assert namers == IEM_HOST_ALLOWED_MODULES
