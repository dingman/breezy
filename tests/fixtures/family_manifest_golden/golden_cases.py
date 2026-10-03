"""Case enumeration, runner and generator for the family-manifest golden corpus.

Single source of truth shared by the characterisation test
(`tests/unit/test_parse_split_matches_presplit_golden.py`) and the generator
(`python tests/fixtures/family_manifest_golden/golden_cases.py --write`,
run with the repo venv interpreter and `PYTHONPATH=<tree>/src`).

Every input is run through `load_family_manifest` under BOTH
`allow_draft=False` and `allow_draft=True`. The recorded outcome is either
the raised exception type name plus its message (input path -> `<PATH>`,
its parent directory -> `<DIR>`), or the canonical dump of the parsed
`FamilyManifest` plus its sha256.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
import sys
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

from breezy.persistence.family_manifest import load_family_manifest

CORPUS = Path(__file__).resolve().parent
EXPECTED = CORPUS / "expected.json"
_FILE_DIRS = ("manifests", "invalid", "valid_variants")
_BASE = CORPUS / "manifests" / "pm_us_crh_v4.json"
_LAYOUT = Path("deploy") / "families"

Builder = Callable[[Path], Path]


def _write_base(directory: Path, **overrides: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    payload = json.loads(_BASE.read_text())
    payload.update(overrides)
    target = directory / "m.json"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return target


def _missing_parent(tmp: Path) -> Path:
    return tmp / "no_such_dir" / "m.json"


def _missing_file(tmp: Path) -> Path:
    (tmp / "d").mkdir()
    return tmp / "d" / "m.json"


def _parent_is_file(tmp: Path) -> Path:
    (tmp / "f").write_text("x")
    return tmp / "f" / "m.json"


def _mechanism_marker(tmp: Path) -> Path:
    target = _write_base(tmp / "d")
    (tmp / "d" / "mechanism_trials.csv").write_text("mechanism_test_only\ntrue\n")
    return target


def _symlink_escape(field: str) -> Builder:
    def build(tmp: Path) -> Path:
        outside = tmp / "outside"
        outside.mkdir()
        families = tmp / "m" / _LAYOUT
        families.mkdir(parents=True)
        (families / "link").symlink_to(outside, target_is_directory=True)
        return _write_base(tmp / "m", **{field: "deploy/families/link/x.json"})

    return build


TMP_BUILDERS: dict[str, Builder] = {
    "tmp/missing_parent": _missing_parent,
    "tmp/missing_file_existing_parent": _missing_file,
    "tmp/parent_is_file": _parent_is_file,
    "tmp/mechanism_marker": _mechanism_marker,
    "tmp/symlink_escape_boundary": _symlink_escape("boundary_artefact_path"),
    "tmp/symlink_escape_density": _symlink_escape("density_artefact_path"),
}


def corpus_files() -> list[str]:
    """Corpus-relative posix names of every committed top-level input."""
    return sorted(
        f"{directory}/{path.name}"
        for directory in _FILE_DIRS
        for path in (CORPUS / directory).glob("*.json")
    )


def case_ids() -> list[str]:
    names = corpus_files() + sorted(TMP_BUILDERS)
    return [f"{name}[allow_draft={flag}]" for name in names for flag in (False, True)]


def _split_id(case_id: str) -> tuple[str, bool]:
    name, _, flag = case_id.rpartition("[allow_draft=")
    return name, flag == "True]"


def _canonical(manifest: object) -> dict[str, object]:
    def convert(value: object) -> object:
        if isinstance(value, Path):
            return value.as_posix()
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, tuple):
            return [convert(item) for item in value]
        return value

    assert dataclasses.is_dataclass(manifest) and not isinstance(manifest, type)
    return {f.name: convert(getattr(manifest, f.name)) for f in dataclasses.fields(manifest)}


def _scrub(message: str, path: Path) -> str:
    return message.replace(str(path), "<PATH>").replace(str(path.parent), "<DIR>")


def run_case(case_id: str, tmp: Path) -> dict[str, object]:
    """Run one case; `tmp` is a fresh empty directory for builder cases."""
    name, allow_draft = _split_id(case_id)
    path = TMP_BUILDERS[name](tmp) if name in TMP_BUILDERS else CORPUS / name
    try:
        manifest = load_family_manifest(path, allow_draft=allow_draft)
    except Exception as exc:  # noqa: BLE001 - characterisation records every refusal
        return {"raises": type(exc).__name__, "message": _scrub(str(exc), path)}
    dump = json.dumps(_canonical(manifest), sort_keys=True, separators=(",", ":"))
    return {"parsed": json.loads(dump), "sha256": hashlib.sha256(dump.encode()).hexdigest()}


def generate(scratch: Path) -> dict[str, dict[str, object]]:
    cases: dict[str, dict[str, object]] = {}
    for case_id in case_ids():
        tmp = scratch / str(len(cases))
        tmp.mkdir()
        cases[case_id] = run_case(case_id, tmp)
    return cases


def main() -> None:
    import tempfile

    if "--write" not in sys.argv:
        sys.exit("usage: golden_cases.py --write")
    scratch = Path(tempfile.mkdtemp(prefix="family_manifest_golden_"))
    try:
        body = json.dumps({"cases": generate(scratch)}, indent=2, sort_keys=True) + "\n"
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    EXPECTED.write_text(body)


if __name__ == "__main__":
    main()
