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
# Phase 2 exists because real namespace tests cannot create nested user
# namespaces inside the phase-1 egress block on this host. The gate therefore
# runs ordinary tests once under the OS egress block, then runs the exact
# bwrap-host registry once outside that nested namespace with pytest-level
# admission checks and no forwarded user arguments.
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

unset BREEZY_BWRAP_HOST_PHASE BREEZY_GATE_COLLECT_ONLY_CLAIM BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE

GATE_DIR="${BREEZY_GATE_DIR:-$HOME/.cache/breezy-gate}"
if [[ -e "$GATE_DIR" && ! -d "$GATE_DIR" ]]; then
  echo "[breezy] gate dir is not a directory: $GATE_DIR" >&2
  exit 3
fi
if [[ -d "$GATE_DIR" && ! -O "$GATE_DIR" ]]; then
  echo "[breezy] gate dir is not owned by this user: $GATE_DIR" >&2
  exit 3
fi
install -d -m 0700 "$GATE_DIR"
chmod 0700 "$GATE_DIR"
gate_mode=$(stat -c %a "$GATE_DIR")
if [[ "$gate_mode" != "700" ]]; then
  echo "[breezy] gate dir mode is not 0700: $GATE_DIR mode=$gate_mode" >&2
  exit 3
fi
P1_CONFIRM=$(mktemp "$GATE_DIR/p1-confirm.XXXXXX")
P2_BT=""
trap 'rm -rf -- "$P1_CONFIRM" ${P2_BT:+"$P2_BT"}' EXIT

bwrap_ok() {
  command -v bwrap >/dev/null 2>&1 && bwrap --unshare-net --dev-bind / / true 2>/dev/null
}

unshare_ok() {
  command -v unshare >/dev/null 2>&1 && unshare -r -n true 2>/dev/null
}

refuse_message() {
  echo "error: no usable unprivileged network-namespace mechanism on this host." >&2
  echo "       install bubblewrap (apt install bubblewrap), or enable" >&2
  echo "       unprivileged user namespaces (sysctl kernel.unprivileged_userns_clone=1)." >&2
  echo "       Refusing to run: an unsandboxed run would NOT be egress-blocked," >&2
  echo "       and exporting BREEZY_TEST_OS_EGRESS_BLOCK=1 anyway would be a lie" >&2
  echo "       that barrier N3 will catch." >&2
}

# Loopback must stay usable: parts of the suite bind ephemeral local ports to
# discover a closed one. `--unshare-net` gives the sandbox a fresh network
# namespace whose only interface is a private loopback, so 127.0.0.1 works
# while every route off-box is gone.
run_bwrap() {
  bwrap \
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
  unshare -r -n env BREEZY_TEST_OS_EGRESS_BLOCK=1 "$PYTHON" -m pytest "$@"
}

run_phase2() {
  if [[ -n "${BREEZY_TEST_OS_EGRESS_BLOCK:-}" ]]; then
    echo "[breezy] phase 2 refuses: phase-1 attestation is set" >&2
    return 3
  fi
  if ! command -v bwrap >/dev/null 2>&1; then
    echo "[breezy] phase 2 refuses: bwrap is absent" >&2
    return 3
  fi
  if ! bwrap --unshare-user --disable-userns --unshare-net --unshare-pid --ro-bind / / --dev /dev --proc /proc true 2>/dev/null; then
    echo "[breezy] phase 2 refuses: bwrap precheck failed" >&2
    return 3
  fi

  mapfile -t files < <(
    "$PYTHON" -I -c 'import sys; sys.path.insert(0, "'"$REPO_ROOT"'"); from tests.support.bwrap_host_phase import registry_paths; print("\n".join(registry_paths()))'
  )
  if [[ "${#files[@]}" -eq 0 ]]; then
    echo "[breezy] phase 2 refuses: empty phase-2 registry" >&2
    return 3
  fi

  P2_BT=$(mktemp -d "$GATE_DIR/phase2-bt.XXXXXX")
  env \
    -u BREEZY_TEST_OS_EGRESS_BLOCK \
    -u BREEZY_GATE_COLLECT_ONLY_CLAIM \
    -u BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE \
    -u PYTEST_PLUGINS \
    -u PYTEST_ADDOPTS \
    BREEZY_BWRAP_HOST_PHASE=1 \
    "$PYTHON" -m pytest \
      -p tests.support.bwrap_host_phase \
      -p no:randomly \
      -p no:cacheprovider \
      -m bwrap_host \
      --basetemp="$P2_BT" \
      "${files[@]}"
}

collect_only=0
for a in "$@"; do
  case "$a" in
    --collect-only|--co|--collectonly) collect_only=1 ;;
  esac
done

export BREEZY_GATE_COLLECT_ONLY_CLAIM="$collect_only" BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE="$P1_CONFIRM"
phase1_rc=0
if bwrap_ok; then
  echo "[breezy] OS egress block: bubblewrap network namespace" >&2
  run_bwrap -p tests.support.bwrap_host_phase "$@" || phase1_rc=$?
elif unshare_ok; then
  echo "[breezy] OS egress block: unshare network namespace" >&2
  run_unshare -p tests.support.bwrap_host_phase "$@" || phase1_rc=$?
else
  refuse_message
  exit 3
fi

if [[ "$collect_only" == 1 && "$(cat -- "$P1_CONFIRM")" == "collect-only" ]]; then
  echo "[breezy] gate: phase1 rc=$phase1_rc phase2 omitted (collect-only confirmed)" >&2
  exit "$phase1_rc"
fi

phase2_rc=0
run_phase2 || phase2_rc=$?
echo "[breezy] gate: phase1 rc=$phase1_rc phase2 rc=$phase2_rc" >&2
[[ "$phase1_rc" -ne 0 ]] && exit "$phase1_rc"
exit "$phase2_rc"
