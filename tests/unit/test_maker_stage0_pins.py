"""MAKER-S2 WP1: input pins, model load, clean-tree assertion, catalog-slice manifest.

Plan r3 WP1 + r4 delta (c)(g). Git tests run in a ``tmp_path`` repository (never the real tree).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from breezy.analysis.nbp_calibration import DEFAULT_SPLITS
from scripts.analysis.maker_stage0_pins import (
    CLEAN_TREE_PATHSPECS,
    REQUIRED_PIN_KEYS,
    CatalogSliceManifest,
    DirtyTree,
    ModelRefused,
    PinSources,
    assert_clean_tree,
    git_commit,
    load_model,
    package_set_sha256,
    pin_inputs,
    seal_sidecars,
    write_pins,
)

ARTEFACT_BYTES = b'{"kind": "fixture artefact"}\n'
ARTEFACT_SHA = hashlib.sha256(ARTEFACT_BYTES).hexdigest()
ARTEFACT_REL = "deploy/families/artefacts/nbp_fixture.json"
MANIFEST_REL = "deploy/families/pm_us_crh_fq_v1.json"
DOC_REL = "docs/evidence/NBP_S2_VALIDATE_RESULT_2026-09-30.md"


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "-C",
            str(repo),
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout


def _doc(
    *,
    sha: str = ARTEFACT_SHA,
    bullet_sha: str | None = None,
    v5_last: str = "2026-06-30",
    other_last: str = "2026-05-03",
) -> str:
    body = {
        "artefact": {"path": "/x/a.json", "sha256": sha},
        "fit_provenance": {
            "v4.0": {
                "train": {
                    "first_climate_day": "2021-01-01",
                    "last_climate_day": "2023-01-17",
                    "rows": 1,
                }
            },
            "v4.2": {
                "validate": {
                    "first_climate_day": "2025-01-01",
                    "last_climate_day": other_last,
                    "rows": 1,
                }
            },
            "v5.0": {
                "v5_fit_slice": {
                    "first_climate_day": "2026-05-05",
                    "last_climate_day": v5_last,
                    "rows": 1,
                }
            },
        },
    }
    return (
        "# NBP S2 Validate Result\n\n"
        f"- artefact_sha256: `{bullet_sha or sha}`\n- sigma_d: `0.13`\n\n## Source JSON\n\n"
        f"```json\n{json.dumps(body, indent=2)}\n```\n"
    )


def _repo(tmp_path: Path, *, doc: str | None = None, manifest_sha: str = ARTEFACT_SHA) -> Path:
    repo = tmp_path / "repo"
    for rel, data in {
        ARTEFACT_REL: ARTEFACT_BYTES.decode(),
        MANIFEST_REL: json.dumps(
            {
                "family_id": "pm_us_crh_fq_v1",
                "density_artefact_path": ARTEFACT_REL,
                "density_artefact_sha256": manifest_sha,
                "taker_fee_coefficient": "0.0695",
            }
        ),
        DOC_REL: doc if doc is not None else _doc(),
        "uv.lock": "lock\n",
        "docs/strategies/SPEC.md": "spec\n",
        "scripts/analysis/a.py": "A = 1\n",
        "src/breezy/b.py": "B = 1\n",
        "tests/t.py": "T = 1\n",
        "tests/fixtures/f.txt": "F\n",
        "pyproject.toml": "[project]\n",
    }.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data)
    _git(repo, "init", "-q")
    _git(repo, "add", "--", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


# --- load_model ---------------------------------------------------------------------------


def test_load_model_asserts_artefact_sha_and_fit_window_from_evidence_doc(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    pin = load_model(repo)
    assert pin.artefact_sha256 == ARTEFACT_SHA
    assert pin.artefact_path == repo / ARTEFACT_REL
    assert pin.manifest_sha256 == hashlib.sha256((repo / MANIFEST_REL).read_bytes()).hexdigest()
    assert pin.evidence_doc_sha256 == hashlib.sha256((repo / DOC_REL).read_bytes()).hexdigest()
    assert pin.fit_window_end == dt.date(2026, 6, 30) == DEFAULT_SPLITS.v5_fit_slice.end


def test_artefact_sha_mismatch_refuses(tmp_path: Path) -> None:
    # The manifest names a sha the artefact bytes do not have.
    with pytest.raises(ModelRefused, match="manifest"):
        load_model(_repo(tmp_path, manifest_sha="0" * 64))


def test_evidence_doc_with_a_different_artefact_sha_refuses(tmp_path: Path) -> None:
    other = _repo(tmp_path, doc=_doc(sha="1" * 64))
    with pytest.raises(ModelRefused, match="artefact_sha256"):
        load_model(other)


def test_evidence_doc_bullet_and_json_block_must_agree(tmp_path: Path) -> None:
    with pytest.raises(ModelRefused, match="artefact_sha256"):
        load_model(_repo(tmp_path, doc=_doc(bullet_sha="2" * 64)))


@pytest.mark.parametrize(
    ("doc", "why"),
    [
        (_doc(v5_last="2026-06-29"), "fit window"),
        (_doc(v5_last="2026-07-01"), "fit window"),
        (_doc(other_last="2026-07-02"), "2026-06-30"),
        ("# no block at all\n- artefact_sha256: `" + ARTEFACT_SHA + "`\n", "unparseable"),
        ("- artefact_sha256: `" + ARTEFACT_SHA + "`\n```json\n{not json\n```\n", "unparseable"),
        (_doc().replace('"fit_provenance"', '"fit_prov"'), "unparseable"),
        (_doc().replace('"v5.0"', '"v6.0"'), "v5.0"),
    ],
)
def test_load_model_refuses_a_bad_evidence_doc(tmp_path: Path, doc: str, why: str) -> None:
    with pytest.raises(ModelRefused, match=why):
        load_model(_repo(tmp_path, doc=doc))


# --- clean tree ---------------------------------------------------------------------------


def test_clean_tree_scope_is_the_five_declared_paths() -> None:
    assert CLEAN_TREE_PATHSPECS == ("scripts/analysis", "src", "tests", "pyproject.toml", "uv.lock")


def test_verdict_run_refuses_dirty_tree_incl_pyproject_lock_and_fixtures(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert_clean_tree(repo)  # clean tree passes
    for rel in (
        "pyproject.toml",
        "uv.lock",
        "tests/fixtures/f.txt",
        "scripts/analysis/a.py",
        "src/breezy/b.py",
    ):
        path = repo / rel
        original = path.read_text()
        path.write_text(original + "# edit\n")
        with pytest.raises(DirtyTree, match=rel.replace(".", r"\.")):
            assert_clean_tree(repo)
        path.write_text(original)
    assert_clean_tree(repo)
    untracked = repo / "tests" / "fixtures" / "new.txt"
    untracked.write_text("n")
    with pytest.raises(DirtyTree, match="new.txt"):
        assert_clean_tree(repo)
    untracked.unlink()
    # Changes outside the five paths do not matter.
    (repo / "docs" / "note.md").write_text("n")
    assert_clean_tree(repo)


def test_git_commit_is_the_head_sha(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert git_commit(repo) == _git(repo, "rev-parse", "HEAD").strip()


def test_assert_clean_tree_refuses_a_directory_that_is_not_a_repository(tmp_path: Path) -> None:
    with pytest.raises(DirtyTree, match="git"):
        assert_clean_tree(tmp_path)


# --- package set --------------------------------------------------------------------------


def test_package_set_sha_is_order_and_case_independent() -> None:
    a = package_set_sha256([("Foo", "1.0"), ("bar", "2")])
    assert a == package_set_sha256([("bar", "2"), ("foo", "1.0")])
    assert a == hashlib.sha256(b"bar==2\nfoo==1.0").hexdigest()
    assert a != package_set_sha256([("bar", "2"), ("foo", "1.1")])


# --- pins ---------------------------------------------------------------------------------


def _sources(tmp_path: Path, repo: Path) -> PinSources:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    files = {}
    for name in (
        "census",
        "unit",
        "truth_copy",
        "truth_cross_check",
        "nbp_manifest",
        "process_schedule",
        "catalog_slice",
        "amendment",
        "node_a",
        "node_b",
        "overlay",
    ):
        files[name] = inputs / f"{name}.dat"
        files[name].write_text(f"bytes of {name}\n")
    return PinSources(
        repo_root=repo,
        census=files["census"],
        trade_unit=files["unit"],
        truth_copy=files["truth_copy"],
        truth_cross_check=files["truth_cross_check"],
        truth_csv_sha256="3" * 64,
        nbp_manifest=files["nbp_manifest"],
        nbp_consumed=(("2026092901", "aa"), ("2026092813", "bb")),
        process_schedule=files["process_schedule"],
        catalog_slice_manifest=files["catalog_slice"],
        amendment_final=files["amendment"],
        ledger_path=tmp_path / "derived" / "verdict_ledger.jsonl",
        node_logs=(files["node_a"], files["node_b"]),
        sidecar_names=("overlay_station_days.csv", "wp0_agreement.json"),
        argv=("maker_stage0_run.py", "--verdict"),
        theta_pin_site="deploy/families/pm_us_crh_fq_v1.json:taker_fee_coefficient",
        spec=repo / "docs/strategies/SPEC.md",
        packages=(("pkg-a", "1.0"), ("pkg-b", "2.0")),
    )


def test_pins_cover_every_mutable_input(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    src = _sources(tmp_path, repo)
    pins = pin_inputs(src)
    assert set(REQUIRED_PIN_KEYS) <= set(pins)
    # Each externally held input is hashed: mutating its bytes moves exactly its own pin.
    for key, path in [
        ("census", src.census),
        ("trade_unit", src.trade_unit),
        ("truth_csv", src.truth_copy),
        ("truth_cross_check", src.truth_cross_check),
        ("nbp_manifest", src.nbp_manifest),
        ("process_schedule", src.process_schedule),
        ("catalog_slice_manifest", src.catalog_slice_manifest),
        ("amendment_final", src.amendment_final),
    ]:
        before = pin_inputs(src)
        path.write_text(path.read_text() + "mutated\n")
        after = pin_inputs(src)
        assert after[key]["sha256"] != before[key]["sha256"], key
        own = {key, f"{key}_sha256"}
        assert {k: v for k, v in after.items() if k not in own} == {
            k: v for k, v in before.items() if k not in own
        }, key
    # Repo-held inputs are pinned by content (they are committed, so clean-tree covers drift).
    assert pins["uv_lock"]["sha256"] == hashlib.sha256(b"lock\n").hexdigest()
    assert pins["spec"]["sha256"] == hashlib.sha256(b"spec\n").hexdigest()
    assert (
        pins["deploy_manifest"]["sha256"]
        == hashlib.sha256((repo / MANIFEST_REL).read_bytes()).hexdigest()
    )
    assert pins["artefact"]["sha256"] == ARTEFACT_SHA
    assert pins["git_commit"] == git_commit(repo)
    assert pins["nbp_consumed"]["cycles"] == [["2026092813", "bb"], ["2026092901", "aa"]]
    assert len(pins["nbp_consumed"]["sha256"]) == 64


def test_pins_include_clean_tree_package_set_argv_node_logs_ledger_and_sidecars(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    src = _sources(tmp_path, repo)
    pins = pin_inputs(src)
    assert src.packages is not None
    assert pins["clean_tree"] == {"clean": True, "pathspecs": list(CLEAN_TREE_PATHSPECS)}
    assert pins["installed_package_set_sha256"] == package_set_sha256(src.packages)
    assert pins["argv"] == ["maker_stage0_run.py", "--verdict"]
    assert pins["truth_csv_sha256_frozen_block"] == "3" * 64
    assert pins["amendment_final_sha256"] == pins["amendment_final"]["sha256"]
    assert pins["ledger_path"] == str(src.ledger_path)
    assert pins["theta_pin_site"] == src.theta_pin_site
    assert [(n["path"], n["byte_range"]) for n in pins["node_logs"]] == [
        (str(p), [0, p.stat().st_size]) for p in src.node_logs
    ]
    assert all(len(n["sha256"]) == 64 and n["size"] > 0 for n in pins["node_logs"])
    assert pins["sidecars"] == {
        "overlay_station_days.csv": {"run_time_only": True, "sha256": None},
        "wp0_agreement.json": {"run_time_only": True, "sha256": None},
    }
    assert pins["model"]["artefact_sha256"] == ARTEFACT_SHA


def test_pin_inputs_refuses_a_dirty_tree(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    src = _sources(tmp_path, repo)
    (repo / "pyproject.toml").write_text("[project]\nchanged = 1\n")
    with pytest.raises(DirtyTree):
        pin_inputs(src)


def test_pins_are_deterministic_and_written_sorted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    src = _sources(tmp_path, repo)
    run_dir = tmp_path / "run"
    first = write_pins(run_dir, pin_inputs(src))
    again = write_pins(run_dir, pin_inputs(src))
    assert first == again == run_dir / "pins.json"
    assert json.loads(first.read_text()) == json.loads(again.read_text())
    assert list(json.loads(first.read_text())) == sorted(json.loads(first.read_text()))


def test_seal_sidecars_fills_each_named_sidecar_and_refuses_unnamed_ones(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    src = _sources(tmp_path, repo)
    pins = pin_inputs(src)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "overlay_station_days.csv").write_text("a,b\n")
    (run_dir / "wp0_agreement.json").write_text("{}")
    sealed = seal_sidecars(pins, run_dir)
    assert sealed["sidecars"]["overlay_station_days.csv"] == {
        "run_time_only": True,
        "sha256": hashlib.sha256(b"a,b\n").hexdigest(),
    }
    assert pins["sidecars"]["wp0_agreement.json"]["sha256"] is None  # input not mutated
    (run_dir / "wp0_agreement.json").unlink()
    with pytest.raises(FileNotFoundError):
        seal_sidecars(pins, run_dir)


# --- catalog slice manifest ---------------------------------------------------------------


def test_catalog_slice_manifest_records_size_mtime_and_sha_of_every_consumed_file(
    tmp_path: Path,
) -> None:
    a, b = tmp_path / "a.parquet", tmp_path / "b.parquet"
    a.write_bytes(b"A" * 3_000_000)
    b.write_bytes(b"B")
    manifest = CatalogSliceManifest()
    manifest.add(b)
    manifest.add(a)
    manifest.add(a)  # re-reading a file records it once
    body = manifest.to_dict()
    assert [e["path"] for e in body["files"]] == [str(a), str(b)]
    assert body["files"][0]["sha256"] == hashlib.sha256(b"A" * 3_000_000).hexdigest()
    assert body["files"][0]["size"] == 3_000_000
    assert body["files"][0]["mtime_ns"] == a.stat().st_mtime_ns
    out = manifest.write(tmp_path / "catalog_slice_manifest.json")
    assert json.loads(out.read_text()) == body


def test_catalog_slice_manifest_refuses_a_file_that_changed_between_reads(tmp_path: Path) -> None:
    a = tmp_path / "a.parquet"
    a.write_bytes(b"one")
    manifest = CatalogSliceManifest()
    manifest.add(a)
    a.write_bytes(b"two!")
    with pytest.raises(ValueError, match="changed"):
        manifest.add(a)
