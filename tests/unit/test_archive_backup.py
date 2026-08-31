"""P0 -- off-device backup of the two irreplaceable datasets.

Every test here exists because a specific way of *believing* you have a backup
when you do not was identified in `docs/plans/DATA_CAPTURE_AND_RISK_PLAN.md`
§4.P0:

* backing up a primary that is already corrupt (nobody would ever know),
* "off-host" satisfied by a sibling directory on the same device,
* a tarball nobody ever extracted -- a backup never restored is a hypothesis,
* a dry run that quietly wrote something anyway,
* a re-fetch path. The settlement-alignment archive is an IEM-curated product;
  a re-fetch returns a *later revision*, so it would silently invalidate three
  published evidence documents. Re-fetch is prohibited, not a fallback.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "archive" / "backup_irreplaceable_data.py"


def _load_script() -> ModuleType:
    """Load the backup script by path, as the rest of the suite loads scripts.

    ``scripts/`` is deliberately not an importable package (see
    ``test_polymarket_us_auth_smoke.py:72`` and
    ``test_settlement_truth_dataset.py``), so the module is loaded from its
    file exactly as an operator would run it.
    """
    spec = importlib.util.spec_from_file_location("breezy_backup_irreplaceable_data", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


backup = _load_script()

DigestMismatchError = backup.DigestMismatchError
RestoreVerificationError = backup.RestoreVerificationError
SameDeviceError = backup.SameDeviceError
backup_dataset = backup.backup_dataset
build_manifest = backup.build_manifest
format_sha256_manifest = backup.format_sha256_manifest
main = backup.main
parse_sha256_manifest = backup.parse_sha256_manifest
require_distinct_device = backup.require_distinct_device
verify_tree = backup.verify_tree

#: Root packages that would give this script a way to fetch bytes off a
#: network. `urllib` is included because `urllib.request` is the stdlib HTTP
#: client, and `socket`/`ftplib` because "no HTTP" must not be satisfied by
#: reaching one layer lower.
BANNED_NETWORK_ROOTS = frozenset(
    {
        "httpx",
        "requests",
        "urllib",
        "urllib3",
        "http",
        "aiohttp",
        "socket",
        "ssl",
        "ftplib",
        "smtplib",
        "telnetlib",
        "xmlrpc",
        "webbrowser",
    }
)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _tree(root: Path, files: Mapping[str, bytes]) -> Path:
    for name, payload in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    return root


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    root = tmp_path / "primary" / "settlement-alignment-cache"
    root.mkdir(parents=True)
    return _tree(
        root,
        {
            "a.zip": b"alpha-bytes",
            "b.txt": b"bravo-bytes",
            "nested/c.zip": b"charlie-bytes",
        },
    )


def _distinct_devices(source: Path, destination: Path) -> object:
    """Stand-in for `os.stat().st_dev` that reports two different devices.

    Injected only so the happy path is testable inside one `tmp_path`. The
    real run resolves devices through `os.stat` and records both numbers in
    the evidence document.
    """

    def dev_of(path: Path) -> int:
        resolved = str(path.resolve())
        # Destination first: in the CLI tests the destination is NESTED under
        # the source root, so a source-first test would report one device for
        # both and mask the very thing under test.
        if resolved.startswith(str(destination.resolve())):
            return 2002
        if resolved.startswith(str(source.resolve())):
            return 1001
        return 3003

    return dev_of


def _total_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


# --------------------------------------------------------------------------
# Pure policy: manifests
# --------------------------------------------------------------------------


def test_parse_sha256_manifest_reads_the_git_tracked_format() -> None:
    text = (
        "4279f471c6b5b92a17d78419e871b5a91ec93a4bf2a2b51740e6fba1f79bfd74  a.zip\n"
        "10c46a80d4834242a9b86915c944bac5ece2c42789a0949de6a2929e915c332a  b.txt\n"
    )

    assert parse_sha256_manifest(text) == {
        "a.zip": "4279f471c6b5b92a17d78419e871b5a91ec93a4bf2a2b51740e6fba1f79bfd74",
        "b.txt": "10c46a80d4834242a9b86915c944bac5ece2c42789a0949de6a2929e915c332a",
    }


def test_parse_sha256_manifest_rejects_a_duplicate_name() -> None:
    digest = "a" * 64
    text = f"{digest}  x\n{digest}  x\n"

    with pytest.raises(ValueError, match="duplicate"):
        parse_sha256_manifest(text)


def test_build_manifest_covers_every_file_including_nested(source_tree: Path) -> None:
    manifest = build_manifest(source_tree)

    assert sorted(manifest) == ["a.zip", "b.txt", "nested/c.zip"]
    assert manifest["a.zip"] == hashlib.sha256(b"alpha-bytes").hexdigest()


def test_format_sha256_manifest_round_trips(source_tree: Path) -> None:
    manifest = build_manifest(source_tree)

    assert parse_sha256_manifest(format_sha256_manifest(manifest)) == manifest


# --------------------------------------------------------------------------
# Pure policy: verification
# --------------------------------------------------------------------------


def test_verify_tree_reports_ok_when_every_digest_matches(source_tree: Path) -> None:
    result = verify_tree(source_tree, build_manifest(source_tree))

    assert result.ok
    assert result.checked == 3
    assert result.mismatched == ()
    assert result.missing == ()
    assert result.unexpected == ()


def test_verify_tree_flags_a_mutated_file(source_tree: Path) -> None:
    expected = build_manifest(source_tree)
    (source_tree / "b.txt").write_bytes(b"bravo-bytes-TAMPERED")

    result = verify_tree(source_tree, expected)

    assert not result.ok
    assert result.mismatched == ("b.txt",)


def test_verify_tree_flags_a_missing_file(source_tree: Path) -> None:
    expected = build_manifest(source_tree)
    (source_tree / "a.zip").unlink()

    result = verify_tree(source_tree, expected)

    assert not result.ok
    assert result.missing == ("a.zip",)


def test_verify_tree_flags_an_unexpected_file(source_tree: Path) -> None:
    expected = build_manifest(source_tree)
    (source_tree / "d.zip").write_bytes(b"delta")

    result = verify_tree(source_tree, expected)

    assert not result.ok
    assert result.unexpected == ("d.zip",)


# --------------------------------------------------------------------------
# Requirement 2 -- same-device destinations are refused
# --------------------------------------------------------------------------


def test_require_distinct_device_refuses_equal_st_dev(tmp_path: Path) -> None:
    source = tmp_path / "src"
    destination = tmp_path / "dst"
    source.mkdir()
    destination.mkdir()

    # No injection: both really are on one device, which is the whole point.
    assert os.stat(source).st_dev == os.stat(destination).st_dev

    with pytest.raises(SameDeviceError, match="st_dev"):
        require_distinct_device(source, destination)


def test_require_distinct_device_returns_both_devices_when_they_differ(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    destination = tmp_path / "dst"
    source.mkdir()
    destination.mkdir()

    devices = require_distinct_device(
        source, destination, dev_of=_distinct_devices(source, destination)
    )

    assert devices == (1001, 2002)


def test_backup_refuses_a_sibling_directory_on_the_same_device(
    tmp_path: Path, source_tree: Path
) -> None:
    """ "Off-host satisfied by a sibling directory" must be impossible."""
    destination = tmp_path / "same-device-destination"

    with pytest.raises(SameDeviceError):
        backup_dataset(
            dataset="settlement-alignment-cache",
            source=source_tree,
            destination_dir=destination,
            apply=True,
        )

    assert _total_bytes(destination) == 0


# --------------------------------------------------------------------------
# Requirement 1 -- verify the primary BEFORE copying
# --------------------------------------------------------------------------


def test_digest_mismatch_raises_and_writes_nothing(tmp_path: Path, source_tree: Path) -> None:
    expected = build_manifest(source_tree)
    (source_tree / "b.txt").write_bytes(b"bravo-bytes-CORRUPT")
    destination = tmp_path / "dest"

    with pytest.raises(DigestMismatchError) as excinfo:
        backup_dataset(
            dataset="settlement-alignment-cache",
            source=source_tree,
            destination_dir=destination,
            expected_manifest_text=format_sha256_manifest(expected),
            apply=True,
            dev_of=_distinct_devices(source_tree, destination),
        )

    assert "b.txt" in str(excinfo.value)
    # Backing up an already-corrupt primary must be impossible: not even an
    # empty destination directory is created.
    assert not destination.exists()


def test_primary_is_verified_before_the_device_check(tmp_path: Path, source_tree: Path) -> None:
    """A corrupt primary is refused even when the destination is also wrong.

    Ordering matters: if the device check ran first, a corrupt primary copied
    to a legitimately separate device would be reported as a success.
    """
    expected = build_manifest(source_tree)
    (source_tree / "a.zip").write_bytes(b"alpha-bytes-CORRUPT")
    destination = tmp_path / "dest"

    with pytest.raises(DigestMismatchError):
        backup_dataset(
            dataset="settlement-alignment-cache",
            source=source_tree,
            destination_dir=destination,
            expected_manifest_text=format_sha256_manifest(expected),
            apply=True,
        )


# --------------------------------------------------------------------------
# Requirement 5 -- dry-run writes zero bytes
# --------------------------------------------------------------------------


def test_dry_run_writes_zero_bytes(tmp_path: Path, source_tree: Path) -> None:
    destination = tmp_path / "dest"

    report = backup_dataset(
        dataset="settlement-alignment-cache",
        source=source_tree,
        destination_dir=destination,
        apply=False,
        dev_of=_distinct_devices(source_tree, destination),
    )

    assert report.applied is False
    assert report.file_count == 3
    assert report.total_bytes == len(b"alpha-bytes") + len(b"bravo-bytes") + len(b"charlie-bytes")
    assert not destination.exists()
    assert _total_bytes(destination) == 0


def test_cli_defaults_to_dry_run_and_writes_zero_bytes(
    tmp_path: Path, source_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "dest"
    tape = tmp_path / "tape-live"
    _tree(tape, {"run/quotes.feather": b"feather-bytes"})
    # `_device_of` is the single seam through which every device decision is
    # made, so patching it is enough to model a genuine second device.
    monkeypatch.setattr(backup, "_device_of", _distinct_devices(tmp_path, destination))

    exit_code = main(
        [
            "--archive-dir",
            str(source_tree),
            "--tape-live-dir",
            str(tape),
            "--destination",
            str(destination),
            "--no-manifest-check",
        ]
    )

    assert exit_code == 0
    assert not destination.exists()
    assert _total_bytes(destination) == 0


def test_cli_apply_on_a_valid_destination_writes_and_verifies_the_restore(
    tmp_path: Path, source_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "dest"
    tape = tmp_path / "tape-live"
    _tree(tape, {"run/quotes.feather": b"feather-bytes"})
    monkeypatch.setattr(backup, "_device_of", _distinct_devices(tmp_path, destination))

    exit_code = main(
        [
            "--archive-dir",
            str(source_tree),
            "--tape-live-dir",
            str(tape),
            "--destination",
            str(destination),
            "--no-manifest-check",
            "--stamp",
            "20260831T000000Z",
            "--apply",
        ]
    )

    assert exit_code == 0
    assert (destination / "settlement-alignment-cache-20260831T000000Z.tar.zst").is_file()
    assert (destination / "quote-tape-live-20260831T000000Z.tar.zst").is_file()


def test_cli_refuses_a_same_device_destination_even_in_dry_run(
    tmp_path: Path, source_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A dry run reports what WOULD happen -- and this would be refused."""
    destination = tmp_path / "dest"
    tape = tmp_path / "tape-live"
    _tree(tape, {"run/quotes.feather": b"feather-bytes"})

    exit_code = main(
        [
            "--archive-dir",
            str(source_tree),
            "--tape-live-dir",
            str(tape),
            "--destination",
            str(destination),
            "--no-manifest-check",
        ]
    )

    assert exit_code != 0
    assert "st_dev" in capsys.readouterr().err
    assert _total_bytes(destination) == 0


def test_cli_requires_apply_to_write(tmp_path: Path, source_tree: Path) -> None:
    destination = tmp_path / "dest"
    tape = tmp_path / "tape-live"
    _tree(tape, {"run/quotes.feather": b"feather-bytes"})

    # Same device, so `--apply` must fail loudly rather than write.
    exit_code = main(
        [
            "--archive-dir",
            str(source_tree),
            "--tape-live-dir",
            str(tape),
            "--destination",
            str(destination),
            "--no-manifest-check",
            "--apply",
        ]
    )

    assert exit_code != 0
    assert _total_bytes(destination) == 0


# --------------------------------------------------------------------------
# Requirements 3 + 4 -- artifacts, and a proven restore
# --------------------------------------------------------------------------


def test_apply_writes_tar_zst_detached_digest_and_manifest(
    tmp_path: Path, source_tree: Path
) -> None:
    destination = tmp_path / "dest"
    expected_text = format_sha256_manifest(build_manifest(source_tree))

    report = backup_dataset(
        dataset="settlement-alignment-cache",
        source=source_tree,
        destination_dir=destination,
        expected_manifest_text=expected_text,
        apply=True,
        stamp="20260831T000000Z",
        dev_of=_distinct_devices(source_tree, destination),
    )

    tarball = destination / "settlement-alignment-cache-20260831T000000Z.tar.zst"
    detached = destination / "settlement-alignment-cache-20260831T000000Z.tar.zst.sha256"
    manifest = destination / "settlement-alignment-cache-20260831T000000Z.files.sha256"

    assert report.applied is True
    assert tarball.is_file() and tarball.stat().st_size > 0
    assert detached.is_file()
    assert manifest.is_file()

    # The detached digest is of the tarball, and it is correct.
    assert detached.read_text().split()[0] == hashlib.sha256(tarball.read_bytes()).hexdigest()
    assert detached.read_text().split()[1] == tarball.name

    # The per-file manifest travels UNCHANGED -- it is the git-tracked record.
    assert manifest.read_text() == expected_text


def test_restore_verification_checks_the_extracted_tree_not_the_source(
    tmp_path: Path, source_tree: Path
) -> None:
    destination = tmp_path / "dest"

    report = backup_dataset(
        dataset="settlement-alignment-cache",
        source=source_tree,
        destination_dir=destination,
        apply=True,
        stamp="20260831T000000Z",
        dev_of=_distinct_devices(source_tree, destination),
    )

    assert report.restore.ok
    assert report.restore.checked == 3
    assert report.restore_root is not None
    assert report.restore_root.is_dir()
    # Proven by extraction, on the destination device -- not by re-reading the
    # source. The extracted tree is retained as the restored copy.
    assert (report.restore_root / "b.txt").read_bytes() == b"bravo-bytes"
    assert not str(report.restore_root).startswith(str(source_tree))


def test_restore_verification_failure_raises(
    tmp_path: Path, source_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tarball that restores to the wrong bytes is a FAILED backup.

    Simulated by corrupting the extracted tree between extraction and
    verification, which is exactly the class of fault (silent media/transport
    corruption) that verifying the source instead of the extraction misses.
    """
    real_extract: Callable[[Path, Path], Path] = backup.extract_archive

    def corrupting_extract(tarball: Path, into: Path) -> Path:
        root: Path = real_extract(tarball, into)
        (root / "b.txt").write_bytes(b"corrupted-in-transit")
        return root

    monkeypatch.setattr(backup, "extract_archive", corrupting_extract)
    destination = tmp_path / "dest"

    with pytest.raises(RestoreVerificationError, match="b.txt"):
        backup_dataset(
            dataset="settlement-alignment-cache",
            source=source_tree,
            destination_dir=destination,
            apply=True,
            stamp="20260831T000000Z",
            dev_of=_distinct_devices(source_tree, destination),
        )


def test_tape_backup_generates_its_own_manifest(tmp_path: Path) -> None:
    """The quote tape has no pre-existing manifest, so one is generated."""
    tape = tmp_path / "live"
    _tree(
        tape,
        {
            "run-a/quote_tick/INSTR/part-0.feather": b"quotes-a",
            "run-a/config.json": b"{}",
        },
    )
    destination = tmp_path / "dest"

    report = backup_dataset(
        dataset="quote-tape-live",
        source=tape,
        destination_dir=destination,
        apply=True,
        stamp="20260831T000000Z",
        dev_of=_distinct_devices(tape, destination),
    )

    manifest_path = destination / "quote-tape-live-20260831T000000Z.files.sha256"
    generated = parse_sha256_manifest(manifest_path.read_text())

    assert sorted(generated) == ["run-a/config.json", "run-a/quote_tick/INSTR/part-0.feather"]
    assert generated["run-a/config.json"] == hashlib.sha256(b"{}").hexdigest()
    assert report.restore.ok
    assert report.restore.checked == 2


def test_empty_source_is_refused(tmp_path: Path) -> None:
    """A zero-file "backup" that verifies vacuously is the worst outcome."""
    empty = tmp_path / "live"
    empty.mkdir()
    destination = tmp_path / "dest"

    with pytest.raises(ValueError, match="no files"):
        backup_dataset(
            dataset="quote-tape-live",
            source=empty,
            destination_dir=destination,
            apply=True,
            dev_of=_distinct_devices(empty, destination),
        )


# --------------------------------------------------------------------------
# Requirement 6 -- no re-fetch path can ever exist
# --------------------------------------------------------------------------


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_script_imports_no_http_client() -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(), filename=str(SCRIPT_PATH))

    offending = sorted(_imported_roots(tree) & BANNED_NETWORK_ROOTS)

    assert offending == [], (
        f"{SCRIPT_PATH.name} imports {offending}; the settlement-alignment "
        "archive is IEM-curated and a re-fetch returns a LATER revision, "
        "silently invalidating three published evidence documents"
    )


def test_script_does_not_reach_breezy_http_transport() -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(), filename=str(SCRIPT_PATH))

    assert "breezy.ingest.http" not in {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }


def test_tape_root_env_var_matches_the_recorder() -> None:
    """The backup must read the tape root the RECORDER writes.

    A literal is unavoidable here (importing `breezy.runtime.settings` would
    pull an HTTP-capable dependency graph into a script whose whole point is
    that it cannot fetch). So the literal is pinned to `settings.py` by
    parsing that module's AST -- no import, no drift.
    """
    settings_path = REPO_ROOT / "src" / "breezy" / "runtime" / "settings.py"
    tree = ast.parse(settings_path.read_text(), filename=str(settings_path))

    declared = {
        target.id: node.value.value
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in ([node.target] if isinstance(node, ast.AnnAssign) else node.targets)
        if isinstance(target, ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }

    assert declared["QUOTE_TAPE_CATALOG_VAR"] == backup.QUOTE_TAPE_CATALOG_VAR


def test_tape_live_dir_is_resolved_from_the_env_var_not_hardcoded() -> None:
    resolved = backup.resolve_tape_live_dir(
        {backup.QUOTE_TAPE_CATALOG_VAR: "/srv/tape/polymarket_us"}
    )

    assert resolved == Path("/srv/tape/polymarket_us/live")


def test_tape_live_dir_refuses_when_the_env_var_is_unset() -> None:
    with pytest.raises(backup.BackupError, match=backup.QUOTE_TAPE_CATALOG_VAR):
        backup.resolve_tape_live_dir({})


def test_script_never_deletes_the_primary() -> None:
    """No unlink/rmtree/remove anywhere: P0 copies, it never removes."""
    tree = ast.parse(SCRIPT_PATH.read_text(), filename=str(SCRIPT_PATH))

    destructive = {"unlink", "rmtree", "remove", "removedirs", "rmdir"}
    found = sorted(
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in destructive
    )

    assert found == []
