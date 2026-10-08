"""AUT-6 WP1 (gate phase 2, E-7a/E-7d): the AUT-6 bwrap rows in a real namespace.

Every test runs a child under real bubblewrap through ``tests.support.bwrap_harness`` in the shipped
``breezy-autonomy-alert-redeliver`` row, with ``SandboxRoots`` substituted for the real home. The
assertions observe what the child can and cannot do (E-7 rule 1), not what an argv says.

This file is a member of ``BWRAP_HOST_TEST_FILES``; its 2 tests (the second parametrised over the
1 AUT-6 row, so 2 cases) are part of ``BWRAP_HOST_EXPECTED_TESTS`` (L-12). Each later AUT-6 work
package adds its row to ``AUT6_ROWS``, which widens the second test's cases.
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE, SandboxRoots
from tests.support.bwrap_harness import CHILD_ROOTS_PRELUDE, make_roots, roots_json, run_in_row

pytestmark = pytest.mark.bwrap_host

AUT6_ROWS: Final[tuple[str, ...]] = ("breezy-autonomy-alert-redeliver", "breezy-autonomy-canary")
PRIVATE: Final = 0o700
PROBE_DIR: Final = ".bwrap_probe"


@pytest.fixture
def roots(tmp_path: Path) -> SandboxRoots:
    made = make_roots(tmp_path)
    for row in AUT6_ROWS:
        for rel in AUTONOMY_BWRAP_TABLE[row].binds:
            directory = made.data_root / rel / PROBE_DIR
            directory.mkdir(parents=True, exist_ok=True)
            for part in [directory, *directory.parents]:
                if part == made.data_root.parent:
                    break
                part.chmod(PRIVATE)
    return made


def _run(row: str, roots: SandboxRoots, code: str, *args: str) -> dict[str, Any]:
    command = [
        sys.executable,
        "-c",
        CHILD_ROOTS_PRELUDE + textwrap.dedent(code),
        roots_json(roots),
        *args,
    ]
    result = run_in_row(row, command, roots)
    assert result.returncode == 0, f"rc={result.returncode}\n{result.stderr}\n{result.stdout}"
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


EXDEV_CODE = """
import errno
from breezy.registry.health_model import AlertPayload
from breezy.runtime.alert_delivery import (
    AlertOutbox, DeliveryRecordWriter, deliver_with_proof, enqueue_alert)
root = roots.data_root / "evidence" / "alerts"
payload = AlertPayload(severity="CRITICAL", event="ROW_PROBE", site="row", detail="closed")
out = {}
box = AlertOutbox(root)
out["enqueued"] = enqueue_alert(
    payload, writer="redeliver", outbox=box, records=DeliveryRecordWriter(root))
entry = next((root / "outbox").glob("*.json"))
claimed = box.claim(entry, "redeliver")
out["claimed_in_bind"] = claimed is not None and claimed.parent.parent.parent == root / "outbox"
record = DeliveryRecordWriter(root).write(
    event="ROW_PROBE", ts_ns=1, writer="redeliver", delivered=True, status_class="2xx",
    severity="CRITICAL", attempt_kind="drain", drill=False, site="row", outbox_entry=entry.name)
out["record_in_bind"] = record.is_file()
box.complete(claimed)
out["entry_removed"] = not claimed.exists()
src = root / "outbox" / "cross.json"
src.write_text("{}")
try:
    os.link(src, "/tmp/aut6_cross_bind")
    out["cross_bind"] = "linked"
except OSError as exc:
    out["cross_bind"] = errno.errorcode[exc.errno]
print(json.dumps(out))
"""

PROBE_CODE = """
import errno
binds = json.loads(sys.argv[2])
data = roots.data_root
out = {"negative": {}, "positive": {}}
for rel in ("state", "registry", "evidence"):
    directory = data / rel
    st = os.stat(directory)
    assert st.st_uid == os.getuid()
    try:
        fd = os.open(directory / ".aut6_bwrap_probe_x", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        out["negative"][rel] = "created"
    except OSError as exc:
        out["negative"][rel] = errno.errorcode[exc.errno]
for rel in binds:
    probe = data / rel / ".bwrap_probe" / ".aut6_bwrap_probe_x"
    fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    os.unlink(probe)
    out["positive"][rel] = "ok"
print(json.dumps(out))
"""


def test_aut6_rows_keep_temp_and_final_in_one_bind_with_exdev_control(
    roots: SandboxRoots,
) -> None:
    out = _run("breezy-autonomy-alert-redeliver", roots, EXDEV_CODE)
    assert out["enqueued"] is True
    assert out["claimed_in_bind"] is True and out["record_in_bind"] is True
    assert out["entry_removed"] is True
    # The positive control: a link across the bind boundary fails EXDEV, so the temp file and
    # the final name must (and do) stay in the one bind.
    assert out["cross_bind"] == "EXDEV"


@pytest.mark.parametrize("row", AUT6_ROWS)
def test_every_aut6_row_self_probe_both_directions_under_real_bwrap(
    row: str, roots: SandboxRoots
) -> None:
    binds = AUTONOMY_BWRAP_TABLE[row].binds
    out = _run(row, roots, PROBE_CODE, json.dumps(list(binds)))
    assert out["negative"] == {"state": "EROFS", "registry": "EROFS", "evidence": "EROFS"}
    assert out["positive"] == {rel: "ok" for rel in binds}
