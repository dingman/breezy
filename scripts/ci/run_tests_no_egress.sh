#!/usr/bin/env bash
# Run the Breezy test suite with OS-level network egress BLOCKED.
#
# Why this exists (STK-1). `tests/conftest.py` monkeypatches
# `socket.socket.connect` and rebinds the `nautilus_pyo3` network-client
# attributes. Neither constrains `nautilus_pyo3.HttpClient`, which is a Rust
# `reqwest` client: it opens sockets through Tokio, never through Python's
# `socket` module. The in-process block (barrier N1) closes every *import
# path* to a native client, but it cannot constrain a client object captured
# before pytest configured itself, and it is undoable by any test that wants
# to undo it. Only a kernel-level control actually closes the hole. This
# script is that control.
#
# It sets BREEZY_TEST_OS_EGRESS_BLOCK=1 to ATTEST the block. Barrier N3
# refuses to take that attestation on trust: it issues a real outbound
# connect through the native client and fails unless the kernel refuses it.
# So a run that exports the variable without applying the sandbox fails.
#
# Usage:  scripts/ci/run_tests_no_egress.sh [pytest args...]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

PYTHON="${BREEZY_PYTHON:-$REPO_ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  echo "error: interpreter not found at $PYTHON (set BREEZY_PYTHON)" >&2
  exit 2
fi

# Loopback must stay usable: parts of the suite bind ephemeral local ports to
# discover a closed one. `--unshare-net` gives the sandbox a fresh network
# namespace whose only interface is a private loopback, so 127.0.0.1 works
# while every route off-box is gone.
run_bwrap() {
  exec bwrap \
    --unshare-net \
    --dev-bind / / \
    --chdir "$REPO_ROOT" \
    --setenv BREEZY_TEST_OS_EGRESS_BLOCK 1 \
    "$PYTHON" -m pytest "$@"
}

# `unshare -r -n` is the mechanism named in tests/conftest.py's
# OS_EGRESS_BLOCK_COMMAND, but it requires unprivileged user-namespace
# creation, which is denied on several hosts this repo is developed on
# (`unshare: write failed /proc/self/uid_map: Operation not permitted`).
# bubblewrap is tried first because it is the one measured to work.
run_unshare() {
  exec unshare -r -n env BREEZY_TEST_OS_EGRESS_BLOCK=1 "$PYTHON" -m pytest "$@"
}

if command -v bwrap >/dev/null 2>&1 && bwrap --unshare-net --dev-bind / / true 2>/dev/null; then
  echo "[breezy] OS egress block: bubblewrap network namespace" >&2
  run_bwrap "$@"
fi

if command -v unshare >/dev/null 2>&1 && unshare -r -n true 2>/dev/null; then
  echo "[breezy] OS egress block: unshare network namespace" >&2
  run_unshare "$@"
fi

echo "error: no usable unprivileged network-namespace mechanism on this host." >&2
echo "       install bubblewrap (apt install bubblewrap), or enable" >&2
echo "       unprivileged user namespaces (sysctl kernel.unprivileged_userns_clone=1)." >&2
echo "       Refusing to run: an unsandboxed run would NOT be egress-blocked," >&2
echo "       and exporting BREEZY_TEST_OS_EGRESS_BLOCK=1 anyway would be a lie" >&2
echo "       that barrier N3 will catch." >&2
exit 3
