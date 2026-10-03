"""Golden characterisation of `load_family_manifest` (ARCH-0 seam A, WP-1b).

Recorded on the UNSPLIT parser, so that WP-1c (which moves the parsing body
into `parse_family_manifest`) must leave this test passing UNMODIFIED. Every
corpus input under `tests/fixtures/family_manifest_golden/` (committed
manifests, mutated invalid manifests, valid variants) plus the inputs built
in `tmp_path` at test time (missing/unreadable paths, a mechanism-test
marker, symlink escapes -- never committed as symlinks) runs under both
`allow_draft` values and must match `expected.json`.

Regenerate `expected.json` ONLY for an intended behaviour change:

    PYTHONPATH=<tree>/src /home/jon/breezy/.venv/bin/python \
        tests/fixtures/family_manifest_golden/golden_cases.py --write
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

_CASES_FILE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "family_manifest_golden"
    / ("golden_cases.py")
)


def _load_cases_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("family_manifest_golden_cases", _CASES_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_split_matches_presplit_golden(tmp_path: Path) -> None:
    cases = _load_cases_module()
    expected = json.loads(cases.EXPECTED.read_text())["cases"]

    assert sorted(expected) == sorted(cases.case_ids()), "corpus and expected.json out of sync"

    mismatches: dict[str, object] = {}
    for index, case_id in enumerate(cases.case_ids()):
        scratch = tmp_path / str(index)
        scratch.mkdir()
        actual = cases.run_case(case_id, scratch)
        if actual != expected[case_id]:
            mismatches[case_id] = {"expected": expected[case_id], "actual": actual}
    assert not mismatches, json.dumps(mismatches, indent=2, sort_keys=True)
