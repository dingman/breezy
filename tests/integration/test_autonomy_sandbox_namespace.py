"""ARCH-0 seam B (WP-B2b-3, gate phase 2): the autonomy sandbox in a real namespace.

Every test builds the wrapper's own argv (``build_bwrap_argv`` over validated bind
fds and the exact ``/run`` re-binds) and runs a child under real bubblewrap
through ``tests.support.bwrap_harness``, which adds ``--unshare-net`` and an
explicit environment. The assertions are directive-free: they observe what the
child can and cannot do, not what an argv says (E-7 rule 1).

This file is a member of ``BWRAP_HOST_TEST_FILES``; the count of its tests is
pinned in ``BWRAP_HOST_EXPECTED_TESTS`` (``3`` witness tests + this file's).
"""

from __future__ import annotations

import dataclasses
import fcntl
import json
import os
import stat
import sys
import textwrap
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from breezy.runtime.autonomy_sandbox.bwrap import default_roots
from breezy.runtime.autonomy_sandbox.self_probe import self_probe_plan
from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE, BwrapRow, SandboxRoots
from tests.support.bwrap_harness import (
    CHILD_ROOTS_PRELUDE,
    make_roots,
    roots_json,
    run_in_row,
    spawn_in_row,
)

pytestmark = pytest.mark.bwrap_host

ROW = "breezy-autonomy-selftest"
NOTIFY_ROW = "breezy-autonomy-selftest-notify"
PROC_ROW = "breezy-autonomy-selftest-proc"
BIND = "cache/autonomy_selftest"
CRED_ROW = "breezy-autonomy-selftest-cred"
PROD_ROW = "breezy-autonomy-selftest-prod"
CRED_NAME = "cred_a"
CRED_VAR = "CRED_A_FILE"
EXPECTED_TMP_KIB = 262144


@pytest.fixture
def roots(tmp_path: Path) -> SandboxRoots:
    return make_roots(tmp_path)


def _child(roots: SandboxRoots, code: str, *args: str, python: str = sys.executable) -> list[str]:
    return [
        python,
        "-c",
        CHILD_ROOTS_PRELUDE + textwrap.dedent(code),
        roots_json(roots),
        *args,
    ]


def _run(row: str, roots: SandboxRoots, code: str, *args: str, **kwargs: Any) -> dict[str, Any]:
    result = run_in_row(row, _child(roots, code, *args), roots, **kwargs)
    assert result.returncode == 0, f"rc={result.returncode}\n{result.stderr}\n{result.stdout}"
    parsed: dict[str, Any] = json.loads(result.stdout)
    return parsed


def _tree(root: Path) -> set[tuple[str, int]]:
    return {
        (os.path.join(base, name), os.lstat(os.path.join(base, name)).st_ino)
        for base, dirs, files in os.walk(root)
        for name in (*dirs, *files)
    }


PROBE = """
from breezy.runtime.autonomy_sandbox.self_probe import run_self_probe
result = run_self_probe(sys.argv[2], roots=roots)
print(json.dumps({"ok": result.ok, "failures": list(result.failures),
                  "facts": dict(result.facts)}))
"""


def test_self_probe_passes_inside_row_and_fails_with_wrong_row(roots: SandboxRoots) -> None:
    good = _run(ROW, roots, PROBE, ROW)
    assert good["failures"] == [] and good["ok"] is True
    wrong = _run(ROW, roots, PROBE, NOTIFY_ROW)
    assert wrong["failures"] == ["env_row"] and wrong["ok"] is False


def test_selftest_cli_reports_tmp_size_and_exact_home_listing(roots: SandboxRoots) -> None:
    code = """
    from breezy.runtime.autonomy_sandbox import selftest_cli
    raise SystemExit(selftest_cli.main([], roots=roots))
    """
    report = _run(ROW, roots, code)
    assert report["ok"] is True and report["failures"] == []
    assert report["tmp_size_kib"] == EXPECTED_TMP_KIB
    assert report["home_listing"] == [".local"]
    assert report["row"] == ROW


def test_bwrap_probe_state_write_erofs(roots: SandboxRoots) -> None:
    state = roots.data_root / "state"
    before = _tree(state)
    code = """
    import errno
    state = os.path.join(str(roots.data_root), "state")
    out = {}
    attempts = (
        ("tmpfile", state, os.O_TMPFILE | os.O_WRONLY),
        ("create", os.path.join(state, "probe_should_not_exist"), os.O_CREAT | os.O_WRONLY),
    )
    for name, target, flags in attempts:
        try:
            os.open(target, flags, 0o600)
            out[name] = "ok"
        except OSError as exc:
            out[name] = errno.errorcode[exc.errno]
    print(json.dumps(out))
    """
    assert _run(ROW, roots, code) == {"tmpfile": "EROFS", "create": "EROFS"}
    assert _tree(state) == before


def test_bwrap_own_bind_writable(roots: SandboxRoots) -> None:
    code = """
    bind = os.path.join(str(roots.data_root), "cache", "autonomy_selftest")
    fd = os.open(bind, os.O_TMPFILE | os.O_WRONLY, 0o600)
    os.close(fd)
    with open(os.path.join(bind, "made_inside"), "w") as handle:
        handle.write("x")
    os.mkdir(os.path.join(bind, "sub"))
    print(json.dumps({"ok": True}))
    """
    assert _run(ROW, roots, code) == {"ok": True}
    bind = roots.data_root / BIND
    assert (bind / "made_inside").read_text() == "x"
    assert (bind / "sub").is_dir()


def test_bwrap_repo_and_bind_ancestors_erofs(roots: SandboxRoots) -> None:
    code = """
    import errno
    data = str(roots.data_root)
    out = {}
    for label, path in (("repo", str(roots.repo_root)), ("data_root", data),
                        ("cache", os.path.join(data, "cache")),
                        ("registry", os.path.join(data, "registry"))):
        try:
            os.close(os.open(path, os.O_TMPFILE | os.O_WRONLY, 0o600))
            out[label] = "ok"
        except OSError as exc:
            out[label] = errno.errorcode[exc.errno]
    print(json.dumps(out))
    """
    assert _run(ROW, roots, code) == {
        "repo": "EROFS",
        "data_root": "EROFS",
        "cache": "EROFS",
        "registry": "EROFS",
    }


def test_bwrap_home_listing_is_rebinds_only(roots: SandboxRoots) -> None:
    (roots.home / "host_only_secret").mkdir()
    code = "print(json.dumps(sorted(os.listdir(str(roots.home)))))"
    assert json.loads(run_in_row(ROW, _child(roots, code), roots).stdout) == [".local"]


def test_production_home_mount_args_hide_real_home() -> None:
    """L-55: the production roots (the passwd home, no injection) mount a home tmpfs.

    The row has no binds, so the child can only write to its own ``/tmp``. Whatever
    the real home holds, the child must see exactly the wrapper's re-bind components.
    """
    roots = default_roots()
    assert roots.data_root.is_dir(), "the production data root must exist (plan V1)"
    row = dataclasses.replace(
        AUTONOMY_BWRAP_TABLE[ROW],
        name=PROD_ROW,
        units=frozenset({f"{PROD_ROW}.service"}),
        binds=(),
        bus_reads=(),
        bus_snapshot_bind=None,
        bus_snapshot_budget_s=None,
    )
    code = """
    import errno
    out = {"listing": sorted(os.listdir(str(roots.home))), "credentials": {}}
    for rel in (".config/breezy", ".ssh", ".aws", ".gnupg", ".netrc"):
        try:
            os.lstat(os.path.join(str(roots.home), rel))
            out["credentials"][rel] = "visible"
        except OSError as exc:
            out["credentials"][rel] = errno.errorcode[exc.errno]
    print(json.dumps(out))
    """
    # The real home is hidden, so a venv under it is unreachable in a worktree: the base
    # interpreter lives under the re-bound python prefix and the child needs only stdlib.
    python = str(Path(sys.base_prefix) / "bin" / "python3")
    result = run_in_row(PROD_ROW, _child(roots, code, python=python), roots, table={PROD_ROW: row})
    assert result.returncode == 0, f"rc={result.returncode}\n{result.stderr}"
    seen = json.loads(result.stdout)
    assert set(seen["listing"]) == set(self_probe_plan(row, roots).home_listing_allowed)
    assert set(seen["credentials"].values()) == {"ENOENT"}, seen


def test_bwrap_ssh_aws_gnupg_netrc_enoent(roots: SandboxRoots) -> None:
    for rel in (".config/breezy", ".ssh", ".aws", ".gnupg"):
        (roots.home / rel).mkdir(parents=True)
    (roots.home / ".netrc").write_text("machine host\n")
    code = """
    import errno
    out = {}
    for rel in (".config/breezy", ".ssh", ".aws", ".gnupg", ".netrc"):
        try:
            os.lstat(os.path.join(str(roots.home), rel))
            out[rel] = "visible"
        except OSError as exc:
            out[rel] = errno.errorcode[exc.errno]
    print(json.dumps(out))
    """
    seen = _run(ROW, roots, code)
    assert set(seen.values()) == {"ENOENT"}, seen


def test_bwrap_run_has_no_host_sockets(roots: SandboxRoots) -> None:
    code = """
    import errno, socket
    uid = roots.uid
    paths = ["/var/run/docker.sock", "/run/docker.sock", "/run/snapd.socket",
             "/run/snapd-snap.socket", "/var/snap/lxd/common/lxd/unix.socket",
             "/run/lxd-installer.socket", "/run/dbus/system_bus_socket",
             f"/run/user/{uid}/bus", f"/run/user/{uid}/systemd/private"]
    out = {}
    for path in paths:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(path)
            out[path] = "connected"
        except OSError as exc:
            out[path] = errno.errorcode.get(exc.errno, "other")
        finally:
            sock.close()
    print(json.dumps(out))
    """
    seen = _run(ROW, roots, code)
    assert len(seen) == 9
    assert set(seen.values()) == {"ENOENT"}, seen


RUN_WALK = """
import errno
found = []
for base, dirs, files in os.walk("/run"):
    for name in (*dirs, *files):
        found.append(os.path.relpath(os.path.join(base, name), "/run"))
try:
    os.open("/run/x", os.O_CREAT | os.O_WRONLY, 0o600)
    write = "ok"
except OSError as exc:
    write = errno.errorcode[exc.errno]
print(json.dumps({"entries": sorted(found), "write": write}))
"""


def _resolv_target_relative() -> list[str]:
    target = os.path.realpath("/etc/resolv.conf")
    return [os.path.relpath(target, "/run")] if target.startswith("/run/") else []


def _with_ancestors(relative: list[str]) -> list[str]:
    paths: set[str] = set()
    for rel in relative:
        parts = Path(rel).parts
        paths.update("/".join(parts[: i + 1]) for i in range(len(parts)))
    return sorted(paths)


def test_bwrap_run_readonly_and_allowlisted_entries_only(roots: SandboxRoots) -> None:
    seen = _run(ROW, roots, RUN_WALK)
    assert seen["entries"] == _with_ancestors(_resolv_target_relative())
    assert seen["write"] == "EROFS"


def test_bwrap_dns_row_has_only_resolv_file_and_hosts_lookup_works(roots: SandboxRoots) -> None:
    code = """
    import errno, socket
    found = []
    for base, dirs, files in os.walk("/run"):
        for name in files:
            found.append(os.path.relpath(os.path.join(base, name), "/run"))
    infos = socket.getaddrinfo("localhost", 80, proto=socket.IPPROTO_TCP)
    print(json.dumps({"files": sorted(found), "hosts_lookup": len(infos) > 0}))
    """
    seen = _run(ROW, roots, code)
    assert seen["files"] == _resolv_target_relative()
    assert seen["hosts_lookup"] is True


def _hold_flock(path: Path) -> int:
    fd = os.open(path, os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd


def _studies_lock(roots: SandboxRoots) -> Path:
    lock = roots.run_user / "breezy-studies.lock"
    lock.touch(mode=0o600)
    return lock


def test_bwrap_proc_row_reads_host_proc_locks_and_pid_status(roots: SandboxRoots) -> None:
    held = roots.home / "held.lock"
    held.touch()
    _studies_lock(roots)
    fd = _hold_flock(held)
    try:
        code = """
        host_parent = int(sys.argv[2])
        inode = int(sys.argv[3])
        locks = open("/proc/locks").read()
        status = open(f"/proc/{host_parent}/status").read()
        print(json.dumps({"lock_seen": f":{inode} " in locks,
                          "status_name": status.splitlines()[0].startswith("Name:")}))
        """
        seen = _run(PROC_ROW, roots, code, str(os.getpid()), str(os.fstat(fd).st_ino))
    finally:
        os.close(fd)
    assert seen == {"lock_seen": True, "status_name": True}


def test_bwrap_proc_row_host_pid_environ_root_eacces_kill_esrch(roots: SandboxRoots) -> None:
    _studies_lock(roots)
    code = """
    import errno
    own = int(os.readlink("/proc/self"))
    me = os.geteuid()
    target = None
    for name in sorted(n for n in os.listdir("/proc") if n.isdigit()):
        if int(name) == own:
            continue
        try:
            uids = [l for l in open(f"/proc/{name}/status") if l.startswith("Uid:")][0].split()
        except OSError:
            continue
        if int(uids[1]) == me:
            target = int(name)
            break
    out = {"found": target is not None}
    for label, action in (("kill", lambda: os.kill(target, 0)),
                          ("environ", lambda: open(f"/proc/{target}/environ", "rb").read(1)),
                          ("root", lambda: os.listdir(f"/proc/{target}/root"))):
        try:
            action()
            out[label] = "ok"
        except OSError as exc:
            out[label] = errno.errorcode[exc.errno]
    print(json.dumps(out))
    """
    seen = _run(PROC_ROW, roots, code)
    assert seen == {"found": True, "kill": "ESRCH", "environ": "EACCES", "root": "EACCES"}


def test_proc_row_child_namespace_pid_names_other_host_process(roots: SandboxRoots) -> None:
    """The N5 hazard: on a PROC row, ``os.getpid()`` is a namespace pid and ``/proc/<it>``
    names a different host process, so a PROC row must never index ``/proc`` by it."""
    _studies_lock(roots)
    marker = "ns-pid-marker-7f3a"
    code = f"""
    ns_pid = os.getpid()
    host_pid = int(os.readlink("/proc/self"))
    own_cmdline = open("/proc/self/cmdline", "rb").read()
    try:
        other = open(f"/proc/{{ns_pid}}/cmdline", "rb").read()
    except OSError:
        other = b""
    try:
        other_comm = open(f"/proc/{{ns_pid}}/comm").read().strip()
    except OSError:
        other_comm = ""
    print(json.dumps({{"differs": ns_pid != host_pid, "marker_in_own": b"{marker}" in own_cmdline,
                       "marker_in_ns_pid_entry": b"{marker}" in other,
                       "ns_pid_comm_is_not_python": not other_comm.startswith("python")}}))
    """
    seen = _run(PROC_ROW, roots, code)
    assert seen == {
        "differs": True,
        "marker_in_own": True,
        "marker_in_ns_pid_entry": False,
        "ns_pid_comm_is_not_python": True,
    }


def test_selftest_cli_proc_checks_report_host_view(roots: SandboxRoots) -> None:
    lock = _studies_lock(roots)
    host_locks = len(Path("/proc/locks").read_text().splitlines())
    code = """
    from breezy.runtime.autonomy_sandbox import selftest_cli
    raise SystemExit(selftest_cli.main(["--proc-checks"], roots=roots))
    """
    report = _run(PROC_ROW, roots, code)
    assert report["ok"] is True, report
    checks = report["proc_checks"]
    assert abs(checks["locks_lines"] - host_locks) <= 5
    assert checks["kill"] == "ESRCH" and checks["environ"] == "EACCES"
    assert checks["lock_ino"] == os.stat(lock).st_ino
    assert checks["lock_nlink"] == 1


def test_bwrap_studies_lock_rebind_excludes_both_ways(roots: SandboxRoots) -> None:
    lock = _studies_lock(roots)
    probe = """
    import fcntl
    fd = os.open(os.path.join(str(roots.run_user), "breezy-studies.lock"), os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        print(json.dumps({"inside": "acquired"}))
    except BlockingIOError:
        print(json.dumps({"inside": "blocked"}))
    """
    held = _hold_flock(lock)
    try:
        assert _run(PROC_ROW, roots, probe) == {"inside": "blocked"}
    finally:
        os.close(held)
    assert _run(PROC_ROW, roots, probe) == {"inside": "acquired"}
    holder = """
    import fcntl
    fd = os.open(os.path.join(str(roots.run_user), "breezy-studies.lock"), os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    print("READY", flush=True)
    sys.stdin.readline()
    """
    with spawn_in_row(PROC_ROW, _child(roots, holder), roots) as proc:
        assert proc.stdout is not None and proc.stdin is not None
        assert proc.stdout.readline().strip() == "READY"
        outside = os.open(lock, os.O_RDONLY)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(outside, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(outside)
        proc.stdin.write("\n")
        proc.stdin.flush()
        assert proc.wait(timeout=30) == 0


def _credentials_table(roots: SandboxRoots) -> tuple[dict[str, BwrapRow], Path]:
    base = AUTONOMY_BWRAP_TABLE[NOTIFY_ROW]
    row = dataclasses.replace(
        base,
        name=CRED_ROW,
        units=frozenset({f"{CRED_ROW}.service"}),
        exceptions=frozenset({"E7A_R2_RECONCILE"}),
        credential_names=(CRED_NAME,),
        credential_env=MappingProxyType({CRED_VAR: CRED_NAME}),
    )
    directory = roots.run_user / "credentials" / f"{CRED_ROW}.service"
    directory.mkdir(parents=True)
    secret = directory / CRED_NAME
    secret.write_text("not-a-real-secret")
    secret.chmod(0o400)
    directory.chmod(0o500)
    return {CRED_ROW: row}, directory


def test_bwrap_credentials_dir_readonly_only_listed_names(
    roots: SandboxRoots, request: pytest.FixtureRequest
) -> None:
    table, directory = _credentials_table(roots)
    request.addfinalizer(lambda: directory.chmod(0o700))
    code = f"""
    import errno, stat
    directory = os.environ["{CRED_VAR}"].rsplit("/", 1)[0]
    try:
        os.open(os.path.join(directory, "planted"), os.O_CREAT | os.O_WRONLY, 0o600)
        planted = "ok"
    except OSError as exc:
        planted = errno.errorcode[exc.errno]
    print(json.dumps({{"listing": sorted(os.listdir(directory)), "planted": planted,
                      "content": open(os.environ["{CRED_VAR}"]).read(),
                      "var_is_file_in_dir":
                          os.environ["{CRED_VAR}"] == os.path.join(directory, "{CRED_NAME}"),
                      "mode": stat.S_IMODE(os.stat(os.environ["{CRED_VAR}"]).st_mode)}}))
    """
    env = {"CREDENTIALS_DIRECTORY": str(directory)}
    seen = _run(CRED_ROW, roots, code, table=table, env=env)
    assert seen["listing"] == [CRED_NAME]
    assert seen["planted"] == "EROFS"
    assert seen["content"] == "not-a-real-secret"
    assert seen["var_is_file_in_dir"] is True
    assert seen["mode"] == 0o400


def test_bwrap_notify_row_rebinds_notify_socket_node(roots: SandboxRoots) -> None:
    node = roots.run_user / "systemd" / "notify"
    node.parent.mkdir(parents=True)
    os.mknod(node, stat.S_IFSOCK | 0o600)
    code = """
    import stat
    path = os.environ["NOTIFY_SOCKET"]
    print(json.dumps({"is_socket": stat.S_ISSOCK(os.stat(path).st_mode)}))
    """
    seen = _run(NOTIFY_ROW, roots, code, env={"NOTIFY_SOCKET": str(node)})
    assert seen == {"is_socket": True}
    probe = _run(NOTIFY_ROW, roots, PROBE, NOTIFY_ROW, env={"NOTIFY_SOCKET": str(node)})
    assert probe["failures"] == [], probe


def test_bwrap_xdg_cache_home_is_private_tmp(roots: SandboxRoots) -> None:
    code = """
    cache = os.environ["XDG_CACHE_HOME"]
    os.makedirs(cache, exist_ok=True)
    with open(os.path.join(cache, "marker_xdg"), "w") as handle:
        handle.write("x")
    print(json.dumps({"cache": cache, "tmpdir": os.environ["TMPDIR"]}))
    """
    seen = _run(ROW, roots, code)
    assert seen == {"cache": "/tmp/.cache", "tmpdir": "/tmp"}
    assert not Path("/tmp/.cache/marker_xdg").exists()


def test_bwrap_wrapper_provides_private_tmp(roots: SandboxRoots) -> None:
    code = """
    with open("/tmp/marker_private_tmp", "w") as handle:
        handle.write("x")
    st = os.statvfs("/tmp")
    print(json.dumps({"size_kib": st.f_blocks * st.f_frsize // 1024}))
    """
    assert _run(ROW, roots, code) == {"size_kib": EXPECTED_TMP_KIB}
    assert not Path("/tmp/marker_private_tmp").exists()


def test_bwrap_nested_userns_disabled(roots: SandboxRoots) -> None:
    code = """
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.unshare(0x10000000)
    print(json.dumps({"unshare_user_failed": result == -1}))
    """
    assert _run(ROW, roots, code) == {"unshare_user_failed": True}


def test_concurrent_children_share_binds_and_keep_private_tmp(roots: SandboxRoots) -> None:
    code = """
    name = sys.argv[2]
    with open(f"/tmp/marker_{name}", "w") as handle:
        handle.write(name)
    bind = os.path.join(str(roots.data_root), "cache", "autonomy_selftest")
    with open(os.path.join(bind, f"shared_{name}"), "w") as handle:
        handle.write(name)
    print("READY", flush=True)
    sys.stdin.readline()
    print(json.dumps({"tmp": sorted(n for n in os.listdir("/tmp") if n.startswith("marker_"))}))
    """
    with (
        spawn_in_row(ROW, _child(roots, code, "a"), roots) as first,
        spawn_in_row(ROW, _child(roots, code, "b"), roots) as second,
    ):
        for proc in (first, second):
            assert proc.stdout is not None
            assert proc.stdout.readline().strip() == "READY"
        outputs = []
        for proc in (first, second):
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write("\n")
            proc.stdin.flush()
            outputs.append(json.loads(proc.stdout.readline()))
            assert proc.wait(timeout=30) == 0
    assert outputs == [{"tmp": ["marker_a"]}, {"tmp": ["marker_b"]}]
    assert sorted(p.name for p in (roots.data_root / BIND).glob("shared_*")) == [
        "shared_a",
        "shared_b",
    ]


def test_bwrap_child_env_is_explicit_and_has_no_egress_attestation(roots: SandboxRoots) -> None:
    code = "print(json.dumps(sorted(os.environ)))"
    names = json.loads(run_in_row(ROW, _child(roots, code), roots).stdout)
    assert not {n for n in names if n.startswith(("BREEZY_TEST_", "BREEZY_GATE_", "PYTEST"))}
    assert "BREEZY_BWRAP_HOST_PHASE" not in names
    assert {"BREEZY_AUTONOMY_BWRAP_ROW", "TMPDIR", "XDG_CACHE_HOME", "PATH"} <= set(names)
    assert "BREEZY_AUTONOMY_SANDBOX_DEGRADED" not in names


def test_harness_children_have_no_network(roots: SandboxRoots) -> None:
    code = """
    import errno, socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect(("198.51.100.7", 80))
        outcome = "connected"
    except OSError as exc:
        outcome = errno.errorcode.get(exc.errno, "other")
    interfaces = [line.split(":")[0].strip() for line in open("/proc/net/dev").readlines()[2:]]
    print(json.dumps({"connect": outcome, "interfaces": interfaces}))
    """
    seen = _run(ROW, roots, code)
    assert seen["connect"] == "ENETUNREACH"
    assert seen["interfaces"] == ["lo"]
