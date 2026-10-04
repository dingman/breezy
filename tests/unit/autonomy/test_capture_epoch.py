"""AUT-1 WP1 part A: ``capture_epoch_start`` (r8 section 3.3.5, unchanged by r12 section 3.4.5)."""

import json
import os
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

from breezy.persistence.autonomy.capture_epoch import (
    EPOCH_SCHEMA,
    EpochStatus,
    epoch_relative_path,
    read_epoch,
    write_epoch_once,
)

FAMILY = "forecast_quantile_ladder_lax"


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    return root


def _recorder(sink: list[tuple[str, str, str]]) -> Callable[[str, str, str], bool]:
    def offer(event: str, severity: str, detail: str) -> bool:
        sink.append((event, severity, detail))
        return True

    return offer


def _epoch_file(root: Path) -> Path:
    return root.joinpath(*epoch_relative_path(FAMILY))


def test_epoch_written_once_with_o_excl(data_root: Path) -> None:
    """The first boot publishes the record, mode 0444, via the sanctioned ``single_read`` writer
    (a temp file created ``O_EXCL|O_NOFOLLOW`` then ``os.link``: never a replace).

    MUTATION: replacing the file on every call changes ``epoch_start_ns`` on the second boot.
    """
    offered: list[tuple[str, str, str]] = []
    first = write_epoch_once(
        data_root,
        family_id=FAMILY,
        node_boot_id="boot-1",
        build_sha="abc123",
        now_ns=1_790_000_000_000_000_000,
        alert_offer=_recorder(offered),
    )
    assert first.status is EpochStatus.WRITTEN
    assert first.epoch_start_ns == 1_790_000_000_000_000_000
    path = _epoch_file(data_root)
    assert path.relative_to(data_root).parts == ("evidence", "capture", "epoch", f"{FAMILY}.json")
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body == {
        "schema": "capture_epoch/v1",
        "family_id": FAMILY,
        "epoch_start_ns": 1_790_000_000_000_000_000,
        "node_boot_id": "boot-1",
        "build_sha": "abc123",
    }
    assert EPOCH_SCHEMA == "capture_epoch/v1"
    assert stat.S_IMODE(path.stat().st_mode) == 0o444
    assert offered == []


def test_existing_epoch_is_verified_not_rewritten(data_root: Path) -> None:
    write_epoch_once(
        data_root, family_id=FAMILY, node_boot_id="boot-1", build_sha="abc", now_ns=111
    )
    path = _epoch_file(data_root)
    before = path.read_bytes()
    second = write_epoch_once(
        data_root, family_id=FAMILY, node_boot_id="boot-2", build_sha="def", now_ns=999
    )
    assert second.status is EpochStatus.VERIFIED
    assert second.epoch_start_ns == 111
    assert path.read_bytes() == before
    record = read_epoch(data_root, FAMILY)
    assert record is not None and record.node_boot_id == "boot-1"


def test_read_epoch_is_none_when_absent(data_root: Path) -> None:
    assert read_epoch(data_root, FAMILY) is None


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        b"[]",
        json.dumps({"schema": "capture_epoch/v9"}).encode(),
        json.dumps(
            {
                "schema": "capture_epoch/v1",
                "family_id": "someone_else",
                "epoch_start_ns": 1,
                "node_boot_id": "b",
                "build_sha": "s",
            }
        ).encode(),
        json.dumps(
            {
                "schema": "capture_epoch/v1",
                "family_id": FAMILY,
                "epoch_start_ns": "1",
                "node_boot_id": "b",
                "build_sha": "s",
            }
        ).encode(),
        b"x" * 100_000,
    ],
    ids=["garbage", "not_object", "wrong_schema", "wrong_family", "wrong_type", "oversize"],
)
def test_unreadable_epoch_alerts_without_veto(data_root: Path, content: bytes) -> None:
    """A corrupt existing file gives one CRITICAL and an UNREADABLE outcome: no exception (so no
    health veto) and no rewrite. MUTATION: raising instead of returning goes red."""
    path = _epoch_file(data_root)
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    path.chmod(0o444)
    offered: list[tuple[str, str, str]] = []
    outcome = write_epoch_once(
        data_root,
        family_id=FAMILY,
        node_boot_id="b2",
        build_sha="s2",
        now_ns=5,
        alert_offer=_recorder(offered),
    )
    assert outcome.status is EpochStatus.UNREADABLE
    assert outcome.epoch_start_ns == 0
    assert [(e, s) for e, s, _ in offered] == [("CAPTURE_EPOCH_UNREADABLE", "CRITICAL")]
    assert path.read_bytes() == content
    assert str(data_root) not in offered[0][2]


def test_a_symlinked_epoch_is_never_followed(data_root: Path, tmp_path: Path) -> None:
    target = tmp_path / "elsewhere.json"
    target.write_text("{}", encoding="utf-8")
    path = _epoch_file(data_root)
    path.parent.mkdir(parents=True)
    os.symlink(target, path)
    offered: list[tuple[str, str, str]] = []
    outcome = write_epoch_once(
        data_root,
        family_id=FAMILY,
        node_boot_id="b",
        build_sha="s",
        now_ns=5,
        alert_offer=_recorder(offered),
    )
    assert outcome.status is EpochStatus.UNREADABLE
    assert target.read_text(encoding="utf-8") == "{}"
    assert len(offered) == 1


def test_a_raising_or_absent_alert_offer_never_raises(data_root: Path) -> None:
    path = _epoch_file(data_root)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"junk")

    def boom(*_a: str) -> bool:
        raise RuntimeError("outbox down")

    for offer in (boom, None):
        outcome = write_epoch_once(
            data_root,
            family_id=FAMILY,
            node_boot_id="b",
            build_sha="s",
            now_ns=5,
            alert_offer=offer,
        )
        assert outcome.status is EpochStatus.UNREADABLE


def test_family_id_is_validated_as_a_path_component(data_root: Path) -> None:
    for bad in ("", "../x", "a/b", "A B"):
        with pytest.raises(Exception, match=r"."):
            write_epoch_once(data_root, family_id=bad, node_boot_id="b", build_sha="s", now_ns=1)
