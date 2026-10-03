"""ARCH-0 seam B (WP-B2b-1): the exact per-row ``/run`` re-bind set.

Plan r5 AC-1.3(7): resolv target, notify socket, studies lock and credentials
directory, each re-bound only when the row asks for it. The wrapper never
creates a bind source: a missing studies lock is 78, never created.
"""

from __future__ import annotations

import dataclasses
import os
import socket
import stat
from collections.abc import Iterator
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from breezy.runtime.autonomy_sandbox.run_mounts import (
    RunMountError,
    RunRebind,
    close_run_rebinds,
    run_rebinds,
)
from breezy.runtime.autonomy_sandbox.table import (
    AUTONOMY_BWRAP_TABLE,
    BwrapRow,
    SandboxRoots,
)

LEAF = "breezy-autonomy-selftest.service"
SECRET = "polymarket_us_secret_key"
RECONCILE = frozenset({"E7A_R2_RECONCILE"})


@pytest.fixture
def roots(tmp_path: Path) -> SandboxRoots:
    run_user = tmp_path / "run" / "user"
    (run_user / "systemd").mkdir(parents=True)
    (run_user / "credentials").mkdir()
    home = tmp_path / "home"
    return SandboxRoots(
        home=home,
        data_root=home / "data",
        repo_root=home / "repo",
        python_prefix=home / "py",
        uid=os.getuid(),
        run_user=run_user,
    )


def _row(**changes: Any) -> BwrapRow:
    base = dataclasses.replace(
        AUTONOMY_BWRAP_TABLE["breezy-autonomy-selftest-notify"],
        exceptions=frozenset(),
        resolves_dns=False,
        units=frozenset({LEAF}),
    )
    return dataclasses.replace(base, **changes)


def _open_fds() -> set[str]:
    return set(os.listdir("/proc/self/fd"))


def _call(
    row: BwrapRow,
    roots: SandboxRoots,
    environ: dict[str, str] | None = None,
    **kwargs: Any,
) -> tuple[RunRebind, ...]:
    return run_rebinds(row, roots, environ or {}, **kwargs)


def _refused(
    row: BwrapRow,
    roots: SandboxRoots,
    code: str,
    environ: dict[str, str] | None = None,
    **kwargs: Any,
) -> None:
    before = _open_fds()
    with pytest.raises(RunMountError) as caught:
        _call(row, roots, environ, **kwargs)
    assert caught.value.code == code
    assert caught.value.exit_status == 78
    assert str(caught.value) == code
    assert _open_fds() == before, "a refused call must not leak the fds it opened"


def _close(rebinds: tuple[RunRebind, ...]) -> None:
    close_run_rebinds(rebinds)


# ---------------------------------------------------------------- no flags


def test_row_with_no_run_needs_has_no_rebinds(roots: SandboxRoots) -> None:
    assert _call(_row(), roots) == ()


# --------------------------------------------------------------------- DNS


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    target_dir = tmp_path / "hostrun" / "systemd" / "resolve"
    target_dir.mkdir(parents=True)
    (target_dir / "stub-resolv.conf").write_text("nameserver 127.0.0.53\n")
    return tmp_path / "hostrun"


def _dns_kwargs(tmp_path: Path, run_dir: Path, resolv: Path) -> dict[str, Any]:
    return {"resolv_conf": resolv, "host_run": run_dir}


def test_dns_row_rebinds_only_the_resolv_target_by_fd(
    roots: SandboxRoots, tmp_path: Path, run_dir: Path
) -> None:
    resolv = tmp_path / "etc-resolv.conf"
    resolv.symlink_to(run_dir / "systemd" / "resolve" / "stub-resolv.conf")
    rebinds = _call(_row(resolves_dns=True), roots, resolv_conf=resolv, host_run=run_dir)
    try:
        (only,) = rebinds
        assert only.kind == "dns"
        assert only.dest == str(run_dir / "systemd" / "resolve" / "stub-resolv.conf")
        assert only.src is None and only.fd is not None
        assert stat.S_ISREG(os.fstat(only.fd).st_mode)
    finally:
        _close(rebinds)


def test_dns_row_with_resolv_outside_run_needs_no_rebind(
    roots: SandboxRoots, tmp_path: Path, run_dir: Path
) -> None:
    resolv = tmp_path / "plain-resolv.conf"
    resolv.write_text("nameserver 1.1.1.1\n")
    assert _call(_row(resolves_dns=True), roots, resolv_conf=resolv, host_run=run_dir) == ()


def test_non_dns_row_ignores_resolv(roots: SandboxRoots, tmp_path: Path, run_dir: Path) -> None:
    resolv = tmp_path / "etc-resolv.conf"
    resolv.symlink_to(run_dir / "systemd" / "resolve" / "stub-resolv.conf")
    assert _call(_row(resolves_dns=False), roots, resolv_conf=resolv, host_run=run_dir) == ()


def test_dns_target_under_run_that_is_not_regular_is_refused(
    roots: SandboxRoots, tmp_path: Path, run_dir: Path
) -> None:
    resolv = tmp_path / "etc-resolv.conf"
    resolv.symlink_to(run_dir / "systemd" / "resolve")  # a directory
    _refused(_row(resolves_dns=True), roots, "dns_target", resolv_conf=resolv, host_run=run_dir)
    resolv.unlink()
    resolv.symlink_to(run_dir / "systemd" / "resolve" / "missing.conf")
    _refused(_row(resolves_dns=True), roots, "dns_target", resolv_conf=resolv, host_run=run_dir)


# ------------------------------------------------------------------- notify


NOTIFY_ROW = {"exceptions": frozenset({"E7A_R2_NOTIFY"})}


@pytest.fixture
def notify_socket(roots: SandboxRoots, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    # AF_UNIX paths cap at ~107 bytes, so bind relative to the directory.
    monkeypatch.chdir(roots.run_user / "systemd")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind("notify")
    yield roots.run_user / "systemd" / "notify"
    sock.close()


def test_notify_socket_is_rebound_by_path(roots: SandboxRoots, notify_socket: Path) -> None:
    rebinds = _call(_row(**NOTIFY_ROW), roots, {"NOTIFY_SOCKET": str(notify_socket)})
    (only,) = rebinds
    assert only.kind == "notify"
    assert only.src == only.dest == str(notify_socket)
    assert only.fd is None


def test_notify_row_requires_the_variable(roots: SandboxRoots) -> None:
    _refused(_row(**NOTIFY_ROW), roots, "notify_missing")
    _refused(_row(**NOTIFY_ROW), roots, "notify_missing", {"NOTIFY_SOCKET": ""})


@pytest.mark.parametrize("value", ["@abstract", "relative/notify", "/run/user/0/systemd/notify"])
def test_notify_socket_outside_the_users_systemd_dir_is_refused(
    roots: SandboxRoots, value: str
) -> None:
    _refused(_row(**NOTIFY_ROW), roots, "notify_path", {"NOTIFY_SOCKET": value})


def test_notify_socket_dotdot_escape_is_refused(roots: SandboxRoots) -> None:
    escape = f"{roots.run_user}/systemd/../../elsewhere"
    _refused(_row(**NOTIFY_ROW), roots, "notify_path", {"NOTIFY_SOCKET": escape})


def test_notify_path_that_is_not_a_socket_or_is_a_symlink_is_refused(
    roots: SandboxRoots, notify_socket: Path
) -> None:
    plain = roots.run_user / "systemd" / "plain"
    plain.write_text("x")
    _refused(_row(**NOTIFY_ROW), roots, "notify_socket", {"NOTIFY_SOCKET": str(plain)})
    link = roots.run_user / "systemd" / "link"
    link.symlink_to(notify_socket)
    _refused(_row(**NOTIFY_ROW), roots, "notify_socket", {"NOTIFY_SOCKET": str(link)})
    _refused(
        _row(**NOTIFY_ROW),
        roots,
        "notify_socket",
        {"NOTIFY_SOCKET": str(roots.run_user / "systemd" / "absent")},
    )


def test_notify_socket_owned_by_someone_else_is_refused(
    roots: SandboxRoots, notify_socket: Path
) -> None:
    other = dataclasses.replace(roots, uid=os.getuid() + 1)
    _refused(_row(**NOTIFY_ROW), other, "notify_owner", {"NOTIFY_SOCKET": str(notify_socket)})


# ------------------------------------------------------------ studies lock


STUDIES_ROW = {"exceptions": frozenset({"E7_STUDIES_LOCK"}), "studies_lock": True}


def _lock(roots: SandboxRoots) -> Path:
    return roots.run_user / "breezy-studies.lock"


def test_studies_lock_is_rebound_by_fd(roots: SandboxRoots) -> None:
    _lock(roots).write_text("")
    _lock(roots).chmod(0o600)
    rebinds = _call(_row(**STUDIES_ROW), roots)
    try:
        (only,) = rebinds
        assert only.kind == "studies_lock"
        assert only.dest == str(_lock(roots))
        assert only.src is None and only.fd is not None
        st = os.fstat(only.fd)
        assert (st.st_dev, st.st_ino) == (_lock(roots).stat().st_dev, _lock(roots).stat().st_ino)
    finally:
        _close(rebinds)


def test_studies_lock_missing_is_78_never_created(roots: SandboxRoots) -> None:
    before = sorted(os.listdir(roots.run_user))
    _refused(_row(**STUDIES_ROW), roots, "studies_lock_missing")
    assert sorted(os.listdir(roots.run_user)) == before
    assert not _lock(roots).exists()
    assert not _lock(roots).is_symlink()


def test_studies_lock_with_extra_hardlink_is_refused(roots: SandboxRoots) -> None:
    _lock(roots).write_text("")
    os.link(_lock(roots), roots.run_user / "second-name")
    assert os.stat(_lock(roots)).st_nlink == 2
    _refused(_row(**STUDIES_ROW), roots, "studies_lock_nlink")


def test_studies_lock_symlink_directory_and_foreign_owner_are_refused(
    roots: SandboxRoots,
) -> None:
    target = roots.run_user / "real-lock"
    target.write_text("")
    _lock(roots).symlink_to(target)
    _refused(_row(**STUDIES_ROW), roots, "studies_lock_not_regular")
    _lock(roots).unlink()
    _lock(roots).mkdir()
    _refused(_row(**STUDIES_ROW), roots, "studies_lock_not_regular")
    _lock(roots).rmdir()
    _lock(roots).write_text("")
    _refused(
        _row(**STUDIES_ROW),
        dataclasses.replace(roots, uid=os.getuid() + 1),
        "studies_lock_owner",
    )


def test_non_studies_row_never_touches_the_lock(roots: SandboxRoots) -> None:
    assert _call(_row(), roots) == ()
    assert not _lock(roots).exists()


# ------------------------------------------------------------- credentials


def _cred_row(*names: str) -> BwrapRow:
    names = names or (SECRET,)
    return _row(
        exceptions=RECONCILE,
        credential_names=names,
        credential_env=MappingProxyType({f"VAR_{i}": n for i, n in enumerate(names)}),
    )


def _make_creds(roots: SandboxRoots, leaf: str = LEAF, *names: str) -> Path:
    directory = roots.run_user / "credentials" / leaf
    directory.mkdir()
    for name in names or (SECRET,):
        path = directory / name
        path.write_text("secret")
        path.chmod(0o400)
    directory.chmod(0o500)
    return directory


@pytest.fixture
def _unlock(roots: SandboxRoots) -> Iterator[None]:
    yield
    for path in (roots.run_user / "credentials").rglob("*"):
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o700)


@pytest.mark.usefixtures("_unlock")
def test_credentials_dir_is_rebound_by_fd(roots: SandboxRoots) -> None:
    directory = _make_creds(roots)
    rebinds = _call(_cred_row(), roots, {"CREDENTIALS_DIRECTORY": str(directory)}, unit=LEAF)
    try:
        (only,) = rebinds
        assert only.kind == "credentials"
        assert only.dest == str(directory)
        assert only.src is None and only.fd is not None
        assert stat.S_ISDIR(os.fstat(only.fd).st_mode)
    finally:
        _close(rebinds)


@pytest.mark.usefixtures("_unlock")
def test_credentials_dir_with_several_names_and_a_template_unit(roots: SandboxRoots) -> None:
    leaf = "breezy-autonomy-selftest@pm_us.service"
    row = dataclasses.replace(
        _cred_row("a_secret", "b_secret"), units=frozenset({"breezy-autonomy-selftest@"})
    )
    directory = _make_creds(roots, leaf, "b_secret", "a_secret")
    _close(_call(row, roots, {"CREDENTIALS_DIRECTORY": str(directory)}, unit=leaf))


@pytest.mark.usefixtures("_unlock")
def test_credentials_env_must_equal_the_unit_credential_dir(roots: SandboxRoots) -> None:
    directory = _make_creds(roots)
    other = roots.run_user / "credentials" / "breezy-other.service"
    other.mkdir()
    for env in (
        {},
        {"CREDENTIALS_DIRECTORY": ""},
        {"CREDENTIALS_DIRECTORY": str(other)},
        {"CREDENTIALS_DIRECTORY": str(directory) + "/"},
        {"CREDENTIALS_DIRECTORY": str(directory / ".." / directory.name)},
        {"CREDENTIALS_DIRECTORY": "/etc"},
    ):
        _refused(_cred_row(), roots, "credentials_path", env, unit=LEAF)


@pytest.mark.usefixtures("_unlock")
def test_credentials_require_the_validated_unit_leaf(roots: SandboxRoots) -> None:
    directory = _make_creds(roots)
    env = {"CREDENTIALS_DIRECTORY": str(directory)}
    _refused(_cred_row(), roots, "credentials_unit", env)
    _refused(_cred_row(), roots, "credentials_unit", env, unit="breezy-other.service")


def test_cgroup_instance_leading_dash_refused(roots: SandboxRoots) -> None:
    row = dataclasses.replace(_cred_row(), units=frozenset({"breezy-autonomy-selftest@"}))
    leaf = "breezy-autonomy-selftest@-rf.service"
    directory = roots.run_user / "credentials" / leaf
    directory.mkdir()
    _refused(row, roots, "credentials_unit", {"CREDENTIALS_DIRECTORY": str(directory)}, unit=leaf)


@pytest.mark.usefixtures("_unlock")
def test_credentials_dir_mode_owner_and_contents_are_exact(roots: SandboxRoots) -> None:
    directory = _make_creds(roots)
    env = {"CREDENTIALS_DIRECTORY": str(directory)}
    row = _cred_row()

    directory.chmod(0o700)
    _refused(row, roots, "credentials_dir_mode", env, unit=LEAF)
    directory.chmod(0o500)

    _refused(
        row,
        dataclasses.replace(roots, uid=os.getuid() + 1),
        "credentials_dir_owner",
        env,
        unit=LEAF,
    )

    directory.chmod(0o700)
    (directory / SECRET).chmod(0o440)
    directory.chmod(0o500)
    _refused(row, roots, "credentials_file", env, unit=LEAF)

    directory.chmod(0o700)
    (directory / SECRET).chmod(0o400)
    (directory / "extra").write_text("x")
    (directory / "extra").chmod(0o400)
    directory.chmod(0o500)
    _refused(row, roots, "credentials_contents", env, unit=LEAF)

    directory.chmod(0o700)
    (directory / "extra").unlink()
    (directory / SECRET).unlink()
    directory.chmod(0o500)
    _refused(row, roots, "credentials_contents", env, unit=LEAF)


@pytest.mark.usefixtures("_unlock")
def test_credential_file_that_is_a_symlink_is_refused(roots: SandboxRoots) -> None:
    directory = roots.run_user / "credentials" / LEAF
    directory.mkdir()
    real = roots.run_user / "real-secret"
    real.write_text("s")
    real.chmod(0o400)
    (directory / SECRET).symlink_to(real)
    directory.chmod(0o500)
    _refused(
        _cred_row(), roots, "credentials_file", {"CREDENTIALS_DIRECTORY": str(directory)}, unit=LEAF
    )


def test_credentials_dir_missing_is_refused_not_created(roots: SandboxRoots) -> None:
    target = roots.run_user / "credentials" / LEAF
    _refused(
        _cred_row(), roots, "credentials_missing", {"CREDENTIALS_DIRECTORY": str(target)}, unit=LEAF
    )
    assert not target.exists()


# ----------------------------------------------------------- order / combos


@pytest.mark.usefixtures("_unlock")
def test_rebinds_come_back_in_dns_notify_studies_credentials_order(
    roots: SandboxRoots, tmp_path: Path, run_dir: Path, notify_socket: Path
) -> None:
    resolv = tmp_path / "etc-resolv.conf"
    resolv.symlink_to(run_dir / "systemd" / "resolve" / "stub-resolv.conf")
    _lock(roots).write_text("")
    directory = _make_creds(roots)
    row = _row(
        resolves_dns=True,
        studies_lock=True,
        exceptions=RECONCILE | {"E7A_R2_NOTIFY", "E7_STUDIES_LOCK"},
        credential_names=(SECRET,),
        credential_env=MappingProxyType({"VAR_0": SECRET}),
    )
    environ = {"NOTIFY_SOCKET": str(notify_socket), "CREDENTIALS_DIRECTORY": str(directory)}
    rebinds = _call(row, roots, environ, unit=LEAF, resolv_conf=resolv, host_run=run_dir)
    try:
        assert [r.kind for r in rebinds] == ["dns", "notify", "studies_lock", "credentials"]
    finally:
        _close(rebinds)


def test_a_late_failure_closes_the_fds_opened_earlier(
    roots: SandboxRoots, tmp_path: Path, run_dir: Path
) -> None:
    resolv = tmp_path / "etc-resolv.conf"
    resolv.symlink_to(run_dir / "systemd" / "resolve" / "stub-resolv.conf")
    row = _row(resolves_dns=True, **STUDIES_ROW)
    _refused(row, roots, "studies_lock_missing", resolv_conf=resolv, host_run=run_dir)


def test_close_run_rebinds_closes_every_fd_and_tolerates_path_binds(
    roots: SandboxRoots,
) -> None:
    _lock(roots).write_text("")
    rebinds = _call(_row(**STUDIES_ROW), roots)
    (only,) = rebinds
    assert only.fd is not None
    close_run_rebinds(rebinds)
    with pytest.raises(OSError):
        os.fstat(only.fd)
    close_run_rebinds((RunRebind(kind="notify", dest="/x", src="/x"),))
