"""ARCH-0 seam B (WP-B2b-2): the unit-file lint (plan r5 AC-5, E-7a rule 1).

Every owned or row-listed unit must exec through the wrapper in the exact
``timeout -k`` -> (``flock``) -> wrapper -> row shape, with the three permitted
``ExecStartPre`` forms in order. The lint is proven non-vacuous with fixture
units that each break one rule, and the real ``deploy/systemd`` directory must
lint clean. The wrapper file itself is never parsed as a unit.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from breezy.runtime.autonomy_sandbox.table import AUTONOMY_BWRAP_TABLE, BwrapRow
from breezy.runtime.autonomy_sandbox.unit_lint import (
    DEFAULT_TIMEOUT_START_SEC,
    WRAPPER_PATH,
    LintError,
    lint_units,
    parse_unit,
    start_phase_bound_s,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SELFTEST = AUTONOMY_BWRAP_TABLE["breezy-autonomy-selftest"]
NOTIFY = AUTONOMY_BWRAP_TABLE["breezy-autonomy-selftest-notify"]
PROC = AUTONOMY_BWRAP_TABLE["breezy-autonomy-selftest-proc"]
PLAIN = BwrapRow(
    name="breezy-autonomy-t1",
    owner_plan="T",
    units=frozenset({"breezy-autonomy-t1.service"}),
    binds=("cache/t1",),
    entry_modules=("x",),
    resolves_dns=False,
    network="none",
)
FAILED = BwrapRow(
    name="breezy-autonomy-failed",
    owner_plan="T",
    units=frozenset({"breezy-autonomy-failed@"}),
    binds=("cache/failed",),
    entry_modules=("x",),
    resolves_dns=False,
    network="none",
)
RECON = BwrapRow(
    name="breezy-autonomy-recon",
    owner_plan="T",
    units=frozenset({"breezy-autonomy-recon.service"}),
    binds=("cache/recon",),
    entry_modules=("x",),
    resolves_dns=True,
    network="egress",
    exceptions=frozenset({"E7A_R2_RECONCILE"}),
    credential_names=("polymarket_us_secret_key",),
    credential_env=MappingProxyType({"POLYMARKET_US_SECRET_KEY_FILE": "polymarket_us_secret_key"}),
)
RECORDER = BwrapRow(
    name="breezy-recorder",
    owner_plan="T",
    units=frozenset({"breezy-recorder.service"}),
    binds=("cache/rec",),
    entry_modules=("x",),
    resolves_dns=False,
    network="none",
)
TPL = BwrapRow(
    name="breezy-tpl",
    owner_plan="T",
    units=frozenset({"breezy-tpl@"}),
    binds=("cache/tpl",),
    entry_modules=("x",),
    resolves_dns=False,
    network="none",
)
TABLE: Mapping[str, BwrapRow] = MappingProxyType(
    {row.name: row for row in (*AUTONOMY_BWRAP_TABLE.values(), PLAIN, FAILED, RECON, RECORDER, TPL)}
)
TOUCH = "-/usr/bin/timeout -k 1 4 /usr/bin/touch %t/breezy-studies.lock"
INSTALL = "/usr/bin/timeout -k 1 4 /usr/bin/install -d -m 0700 %h/.local/share/breezy/cache"
CHMOD = "/usr/bin/timeout -k 1 4 /usr/bin/chmod 0700 %h/.local/share/breezy/cache"
SNAPSHOT = f"-/usr/bin/timeout -k 2 13 {WRAPPER_PATH} --bus-snapshot breezy-autonomy-selftest"


def _exec(
    row: str, *, k: str = "5s", t: str = "50s", flock: str = "", cmd: str = "/usr/bin/true"
) -> str:
    return f"/usr/bin/timeout -k {k} {t} {flock}{WRAPPER_PATH} {row} {cmd}"


def _unit(
    exec_start: str | Sequence[str],
    *,
    pre: Sequence[str] = (),
    post: Sequence[str] = (),
    stop_post: Sequence[str] = (),
    unit_lines: Sequence[str] = (),
    service_lines: Sequence[str] = (),
    timeout: str | None = "60",
) -> str:
    starts = [exec_start] if isinstance(exec_start, str) else list(exec_start)
    lines = ["[Unit]", "Description=fixture", *unit_lines, "", "[Service]", "Type=oneshot"]
    if timeout is not None:
        lines.append(f"TimeoutStartSec={timeout}")
    lines += [f"ExecStartPre={p}" for p in pre]
    lines += [f"ExecStart={s}" for s in starts]
    lines += [f"ExecStartPost={p}" for p in post]
    lines += [f"ExecStopPost={p}" for p in stop_post]
    lines += list(service_lines)
    return "\n".join(lines) + "\n"


def _write(root: Path, files: Mapping[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def _lint(root: Path, files: Mapping[str, str], **kwargs: Any) -> tuple[LintError, ...]:
    _write(root, files)
    return lint_units(root, kwargs.pop("table", TABLE), **kwargs)


def _rules(errors: Sequence[LintError]) -> set[str]:
    return {error.rule for error in errors}


GOOD_FAILED = _unit(_exec("breezy-autonomy-failed"))
GOOD_T1 = _unit(
    _exec("breezy-autonomy-t1"), unit_lines=("OnFailure=breezy-autonomy-failed@%n.service",)
)
GOOD_FILES = {
    "breezy-autonomy-t1.service": GOOD_T1,
    "breezy-autonomy-failed@.service": GOOD_FAILED,
}


# ------------------------------------------------------------------ positives


def test_good_units_lint_clean(tmp_path: Path) -> None:
    assert _lint(tmp_path, GOOD_FILES) == ()


def test_real_deploy_units_lint_clean_and_lint_is_not_vacuous(tmp_path: Path) -> None:
    assert lint_units(REPO_ROOT / "deploy" / "systemd", AUTONOMY_BWRAP_TABLE) == ()
    assert _lint(tmp_path, {"breezy-autonomy-t1.service": _unit("/usr/bin/true")}) != ()


def test_wrapper_file_never_parsed_as_unit(tmp_path: Path) -> None:
    files = {**GOOD_FILES, "breezy-autonomy-bwrap": "this is [not] a unit\nExecStart=/bin/false\n"}
    assert _lint(tmp_path, files) == ()


def test_wrapper_script_in_the_real_deploy_dir_is_not_linted_as_a_unit() -> None:
    assert (REPO_ROOT / "deploy" / "systemd" / "breezy-autonomy-bwrap").is_file()
    assert lint_units(REPO_ROOT / "deploy" / "systemd", AUTONOMY_BWRAP_TABLE) == ()


# ------------------------------------------------------------ exec line shapes


@pytest.mark.parametrize(
    "files",
    [
        {"breezy-autonomy-t1.service": _unit("/usr/bin/true")},
        {
            "breezy-autonomy-t1.service": _unit(
                _exec("breezy-autonomy-t1"), stop_post=["/usr/bin/true"]
            )
        },
        {
            "breezy-autonomy-t1.service": GOOD_T1,
            "breezy-autonomy-t1.service.d/override.conf": "[Service]\nExecStart=/usr/bin/true\n",
        },
    ],
    ids=["execstart", "execstoppost", "dropin"],
)
def test_every_autonomy_unit_execs_through_wrapper(
    tmp_path: Path, files: Mapping[str, str]
) -> None:
    assert "not_wrapped" in _rules(_lint(tmp_path, {**GOOD_FILES, **files}))


def test_wrapped_execstoppost_is_accepted_but_any_dropin_exec_is_drop_in_exec(
    tmp_path: Path,
) -> None:
    files = {
        **GOOD_FILES,
        "breezy-autonomy-t1.service": _unit(
            _exec("breezy-autonomy-t1"),
            stop_post=[_exec("breezy-autonomy-t1", cmd="/usr/bin/false")],
        ),
    }
    assert _lint(tmp_path, files) == ()
    files["breezy-autonomy-t1.service.d/reset.conf"] = (
        "[Service]\nExecStart=\nExecStart=" + _exec("breezy-autonomy-t1") + "\n"
    )
    assert "drop_in_exec" in _rules(_lint(tmp_path, files))


def test_dropin_directory_for_a_template_unit_is_in_scope(tmp_path: Path) -> None:
    files = {
        **GOOD_FILES,
        "breezy-autonomy-failed@.service.d/x.conf": "[Service]\nExecStart=/bin/true\n",
    }
    assert "not_wrapped" in _rules(_lint(tmp_path, files))


@pytest.mark.parametrize(
    "exec_start",
    [
        f"{WRAPPER_PATH} breezy-autonomy-t1 /usr/bin/true",
        f"/usr/bin/timeout -k 5s 50s /usr/bin/true {WRAPPER_PATH} breezy-autonomy-t1",
        f"{WRAPPER_PATH} /usr/bin/timeout -k 5s 50s breezy-autonomy-t1 /usr/bin/true",
        f"/usr/bin/flock -w 5 %t/l /usr/bin/timeout -k 5s 50s {WRAPPER_PATH} breezy-autonomy-t1 x",
        f"/usr/bin/timeout -k 5s 50s {WRAPPER_PATH} /usr/bin/flock -w 5 %t/l breezy-autonomy-t1 x",
        f"/usr/bin/timeout 50s {WRAPPER_PATH} breezy-autonomy-t1 x",
        f"/usr/bin/timeout -k 5s {WRAPPER_PATH} breezy-autonomy-t1 x",
        f"timeout -k 5s 50s {WRAPPER_PATH} breezy-autonomy-t1 x",
        "/usr/bin/timeout -k 5s 50s /usr/bin/env FOO=1 " + WRAPPER_PATH + " breezy-autonomy-t1 x",
        "/usr/bin/timeout -k 5s 50s /tmp/breezy-autonomy-bwrap breezy-autonomy-t1 x",
        f"/usr/bin/timeout -k 5s 50s {WRAPPER_PATH}",
    ],
    ids=[
        "no-timeout",
        "command-before-wrapper",
        "wrapper-before-timeout",
        "flock-before-timeout",
        "flock-after-wrapper",
        "timeout-without-k",
        "timeout-missing-duration",
        "relative-timeout",
        "env-interposed",
        "wrong-wrapper-path",
        "no-row",
    ],
)
def test_wrapper_lines_order_timeout_flock_wrapper(tmp_path: Path, exec_start: str) -> None:
    files = {**GOOD_FILES, "breezy-autonomy-t1.service": _unit(exec_start)}
    assert _rules(_lint(tmp_path, files)) & {"not_wrapped", "wrapper_order"}


def test_wrapper_line_with_flock_is_accepted(tmp_path: Path) -> None:
    flock = "/usr/bin/flock -w 600 %t/breezy-studies.lock "
    files = {
        **GOOD_FILES,
        "breezy-autonomy-t1.service": _unit(_exec("breezy-autonomy-t1", flock=flock)),
    }
    assert _lint(tmp_path, files) == ()
    flock_n = "/usr/bin/flock -n %t/x.lock "
    files["breezy-autonomy-t1.service"] = _unit(_exec("breezy-autonomy-t1", flock=flock_n))
    assert _lint(tmp_path, files) == ()


def test_wrapper_lines_name_existing_row_listing_the_unit(tmp_path: Path) -> None:
    unknown = {**GOOD_FILES, "breezy-autonomy-t1.service": _unit(_exec("breezy-autonomy-ghost"))}
    assert "unknown_row" in _rules(_lint(tmp_path, unknown))
    other_row = {**GOOD_FILES, "breezy-autonomy-t1.service": _unit(_exec("breezy-autonomy-recon"))}
    assert "row_not_listing_unit" in _rules(_lint(tmp_path / "b", other_row))


def test_template_unit_must_be_listed_by_the_row_as_name_at(tmp_path: Path) -> None:
    wrong = {
        **GOOD_FILES,
        "breezy-autonomy-failed@.service": _unit(_exec("breezy-autonomy-t1")),
    }
    assert "row_not_listing_unit" in _rules(_lint(tmp_path, wrong))


@pytest.mark.parametrize("prefix", ["+", "!", "!!", "-+", "+-", "@+"])
def test_wrapped_lines_have_no_plus_or_bang_prefix(tmp_path: Path, prefix: str) -> None:
    files = {
        **GOOD_FILES,
        "breezy-autonomy-t1.service": _unit(prefix + _exec("breezy-autonomy-t1")),
    }
    assert "exec_prefix" in _rules(_lint(tmp_path, files))


@pytest.mark.parametrize("prefix", ["@", "-", ":", "|", "+", "!", "-:", "@-"])
@pytest.mark.parametrize("where", ["exec_start", "stop_post"])
def test_execstart_and_execstoppost_allow_no_prefix_character_at_all(
    tmp_path: Path, prefix: str, where: str
) -> None:
    line = prefix + _exec("breezy-autonomy-t1")
    text = (
        _unit(line)
        if where == "exec_start"
        else _unit(_exec("breezy-autonomy-t1"), stop_post=[line])
    )
    files = {**GOOD_FILES, "breezy-autonomy-t1.service": text}
    assert "exec_prefix" in _rules(_lint(tmp_path, files))


@pytest.mark.parametrize("prefix", ["@", ":", "|", "+", "!", "-:", "@-"])
def test_execstartpre_forbids_every_prefix_but_the_exact_dash_forms(
    tmp_path: Path, prefix: str
) -> None:
    for index, line in enumerate((INSTALL, TOUCH.removeprefix("-"), SNAPSHOT.removeprefix("-"))):
        row = (
            "breezy-autonomy-selftest-proc" if line.endswith("lock") else "breezy-autonomy-selftest"
        )
        files = _selftest_files([prefix + line], row=row)
        assert "exec_prefix" in _rules(_lint(tmp_path / f"{index}", files)), line
    assert "exec_prefix" in _rules(
        _lint(tmp_path / "dash", _selftest_files(["-" + INSTALL, SNAPSHOT]))
    )


@pytest.mark.parametrize("key", ["ExecStop", "ExecReload", "ExecCondition"])
def test_other_exec_directives_are_forbidden_on_fully_linted_units(
    tmp_path: Path, key: str
) -> None:
    text = _unit(_exec("breezy-autonomy-t1"), service_lines=[f"{key}=/usr/bin/true"])
    errors = _lint(tmp_path, {**GOOD_FILES, "breezy-autonomy-t1.service": text})
    assert "exec_directive_forbidden" in _rules(errors)


# ----------------------------------------------------- B6-R5: semicolons


@pytest.mark.parametrize("tail", [" ; /bin/evil", " ;/bin/evil", " \\; /bin/evil", " a;b"])
def test_semicolon_in_a_wrapped_exec_line_is_red(tmp_path: Path, tail: str) -> None:
    unit = "breezy-autonomy-t1"
    for index, text in enumerate(
        (
            _unit(_exec(unit, cmd="/bin/true" + tail)),
            _unit(_exec(unit), stop_post=[_exec(unit, cmd="/bin/true" + tail)]),
        )
    ):
        errors = _lint(tmp_path / f"{index}", {**GOOD_FILES, "breezy-autonomy-t1.service": text})
        assert "exec_semicolon" in _rules(errors)


def test_semicolon_in_an_execstartpre_line_is_red(tmp_path: Path) -> None:
    evil = "/usr/bin/timeout -k 1 4 /usr/bin/install -d x ; /bin/evil"
    assert "exec_semicolon" in _rules(_lint(tmp_path, _selftest_files([evil, SNAPSHOT])))
    chmod = "/usr/bin/timeout -k 1 4 /usr/bin/chmod 0700 x ;/bin/evil"
    assert "exec_semicolon" in _rules(_lint(tmp_path / "b", _selftest_files([chmod, SNAPSHOT])))
    snap = SNAPSHOT + " ; /bin/evil"
    assert "exec_semicolon" in _rules(_lint(tmp_path / "c", _selftest_files([snap])))


def test_semicolon_in_a_line_only_wrapper_line_is_red(tmp_path: Path) -> None:
    text = _unit(_exec("breezy-recorder", cmd="/bin/true ; /bin/evil"))
    files = {**GOOD_FILES, "breezy-recorder.service": text}
    errors = _lint(tmp_path, files, wrapper_line_only_units=LINE_ONLY_RECORDER)
    assert "exec_semicolon" in _rules(errors)


def test_semicolon_in_a_line_only_wrapper_execstartpre_is_red(tmp_path: Path) -> None:
    pre = _exec("breezy-recorder", cmd="/bin/true ; /bin/evil")
    text = _unit(_exec("breezy-recorder"), pre=[pre])
    files = {**GOOD_FILES, "breezy-recorder.service": text}
    errors = _lint(tmp_path, files, wrapper_line_only_units=LINE_ONLY_RECORDER)
    assert "exec_semicolon" in _rules(errors)


LINE_ONLY_RECORDER = MappingProxyType({"breezy-recorder.service": "AUT-1 r12 stop hook"})


# ----------------------------------------------- B6-R6: instances and drop-ins


def test_instance_file_of_a_listed_template_gets_the_full_lint(tmp_path: Path) -> None:
    files = {**GOOD_FILES, "breezy-tpl@a.service": _unit("/bin/evil")}
    errors = _lint(tmp_path, files)
    assert "not_wrapped" in _rules(errors)
    assert any(error.unit == "breezy-tpl@a.service" for error in errors)
    good = _unit(_exec("breezy-tpl"))
    assert _lint(tmp_path / "ok", {**GOOD_FILES, "breezy-tpl@a.service": good}) == ()


@pytest.mark.parametrize(
    "path",
    [
        "breezy-tpl@a.service.d/o.conf",
        "breezy-tpl@.service.d/o.conf",
        "breezy-.service.d/o.conf",
        "breezy-autonomy-.service.d/o.conf",
        "service.d/o.conf",
        "breezy-autonomy-t1.service.d/o.conf",
    ],
)
@pytest.mark.parametrize(
    "body",
    [
        "[Service]\nExecStart=/bin/evil\n",
        "[Service]\nExecStart=\n",
        "[Service]\nExecStartPre=/bin/evil\n",
        "[Service]\nExecStartPost=/bin/evil\n",
        "[Service]\nExecStop=/bin/evil\n",
        "[Service]\nExecStopPost=/bin/evil\n",
        "[Service]\nExecReload=/bin/evil\n",
        "[Service]\nExecCondition=/bin/evil\n",
    ],
)
def test_any_exec_directive_in_an_in_scope_dropin_is_drop_in_exec(
    tmp_path: Path, path: str, body: str
) -> None:
    errors = _lint(tmp_path, {**GOOD_FILES, path: body})
    assert "drop_in_exec" in _rules(errors)


def test_dropins_that_reach_no_in_scope_unit_or_set_no_exec_are_ignored(tmp_path: Path) -> None:
    files = {
        **GOOD_FILES,
        "breezy-other.service.d/o.conf": "[Service]\nExecStart=/bin/true\n",
        "zzz-.service.d/o.conf": "[Service]\nExecStart=/bin/true\n",
        "breezy-.service.d/env.conf": "[Service]\nEnvironment=A=1\n",
        "breezy-autonomy-t1.service.d/mem.conf": "[Service]\nMemoryMax=1G\n",
    }
    assert _lint(tmp_path, files) == ()


# ------------------------------------------------------------ ExecStartPost, OnFailure


def test_no_execstartpost_on_owned_units(tmp_path: Path) -> None:
    files = {
        **GOOD_FILES,
        "breezy-autonomy-t1.service": _unit(_exec("breezy-autonomy-t1"), post=["/usr/bin/true"]),
    }
    assert "execstartpost" in _rules(_lint(tmp_path, files))
    wrapped_post = {
        **GOOD_FILES,
        "breezy-autonomy-t1.service": _unit(
            _exec("breezy-autonomy-t1"), post=[_exec("breezy-autonomy-t1")]
        ),
    }
    assert "execstartpost" in _rules(_lint(tmp_path / "b", wrapped_post))


def test_every_autonomy_onfailure_target_is_in_scope_and_wrapped(tmp_path: Path) -> None:
    ghost = {
        **GOOD_FILES,
        "breezy-autonomy-t1.service": _unit(
            _exec("breezy-autonomy-t1"), unit_lines=("OnFailure=breezy-other.service",)
        ),
    }
    assert "onfailure_scope" in _rules(_lint(tmp_path, ghost))
    unwrapped_target = {**GOOD_FILES, "breezy-autonomy-failed@.service": _unit("/usr/bin/true")}
    errors = _lint(tmp_path / "b", unwrapped_target)
    assert "not_wrapped" in _rules(errors)
    assert any(error.unit == "breezy-autonomy-failed@.service" for error in errors)


def test_every_target_of_a_multi_target_onfailure_is_checked(tmp_path: Path) -> None:
    files = {
        **GOOD_FILES,
        "breezy-autonomy-t1.service": _unit(
            _exec("breezy-autonomy-t1"),
            unit_lines=("OnFailure=breezy-autonomy-failed@%n.service breezy-other.service",),
        ),
    }
    assert "onfailure_scope" in _rules(_lint(tmp_path, files))


def test_owned_unit_naming_study_failed_notifier_is_red(tmp_path: Path) -> None:
    files = {
        **GOOD_FILES,
        "breezy-autonomy-t1.service": _unit(
            _exec("breezy-autonomy-t1"), unit_lines=("OnFailure=breezy-study-failed@%n.service",)
        ),
    }
    errors = _lint(tmp_path, files)
    assert "onfailure_study_failed" in _rules(errors)
    assert any("breezy-study-failed@" in error.message for error in errors)


def test_onfailure_list_reset_and_continuation_are_parsed(tmp_path: Path) -> None:
    text = _unit(
        _exec("breezy-autonomy-t1"),
        unit_lines=(
            "OnFailure=breezy-other.service",
            "OnFailure=",
            "OnFailure=breezy-autonomy-failed@%n.service",
        ),
    )
    assert _lint(tmp_path, {**GOOD_FILES, "breezy-autonomy-t1.service": text}) == ()


# ------------------------------------------------------------ notify, credentials


def test_notify_rows_require_notifyaccess_all(tmp_path: Path) -> None:
    name = "breezy-autonomy-selftest-notify.service"
    exec_start = _exec("breezy-autonomy-selftest-notify")
    assert "notify_access" in _rules(_lint(tmp_path, {name: _unit(exec_start)}))
    main_only = _unit(exec_start, service_lines=["NotifyAccess=main"])
    assert "notify_access" in _rules(_lint(tmp_path / "b", {name: main_only}))
    ok = _unit(exec_start, service_lines=["NotifyAccess=all"])
    assert _lint(tmp_path / "c", {name: ok}) == ()


def test_reconcile_units_loadcredential_per_name(tmp_path: Path) -> None:
    name = "breezy-autonomy-recon.service"
    exec_start = _exec("breezy-autonomy-recon")
    good = _unit(exec_start, service_lines=["LoadCredential=polymarket_us_secret_key:/x/key"])
    assert _lint(tmp_path, {name: good}) == ()
    missing = _unit(exec_start)
    assert "loadcredential" in _rules(_lint(tmp_path / "b", {name: missing}))
    twice = _unit(
        exec_start,
        service_lines=[
            "LoadCredential=polymarket_us_secret_key:/x/key",
            "LoadCredential=polymarket_us_secret_key:/y/key",
        ],
    )
    assert "loadcredential" in _rules(_lint(tmp_path / "c", {name: twice}))
    extra = _unit(
        exec_start,
        service_lines=[
            "LoadCredential=polymarket_us_secret_key:/x/key",
            "LoadCredential=other:/x/other",
        ],
    )
    assert "loadcredential" in _rules(_lint(tmp_path / "d", {name: extra}))


# ------------------------------------------------------------ ExecStartPre forms


def _selftest_files(
    pre: Sequence[str], *, timeout: str | None = "60", row: str = "breezy-autonomy-selftest"
) -> dict[str, str]:
    return {
        f"{row}.service": _unit(
            _exec(row),
            pre=pre,
            timeout=timeout,
            service_lines=["NotifyAccess=all"] if row.endswith("notify") else [],
        )
    }


def test_execstartpre_only_bounded_install_or_chmod(tmp_path: Path) -> None:
    ok = _selftest_files([INSTALL, CHMOD, SNAPSHOT])
    assert _lint(tmp_path, ok) == ()
    for index, bad in enumerate(
        [
            "/usr/bin/true",
            "/usr/bin/install -d -m 0700 %h/x",
            "/usr/bin/timeout -k 1 5 /usr/bin/install -d %h/x",
            "/usr/bin/timeout -k 2 4 /usr/bin/install -d %h/x",
            "/usr/bin/timeout -k 1 4 /usr/bin/rm -rf %h/x",
            "/usr/bin/timeout -k 1 4 /bin/sh -c 'install -d x'",
            "-" + INSTALL,
            "/usr/bin/timeout -k 1 4 /usr/bin/install %h/x",
            "/usr/bin/timeout -k 1 4 /usr/bin/install -d %t/breezy-studies.lock",
        ]
    ):
        errors = _lint(tmp_path / f"bad{index}", _selftest_files([INSTALL, bad, SNAPSHOT]))
        assert "pre_form" in _rules(errors), bad


def _proc_files(pre: Sequence[str]) -> dict[str, str]:
    return _selftest_files(pre, row="breezy-autonomy-selftest-proc")


def test_studies_lock_rows_precreate_with_touch_not_install(tmp_path: Path) -> None:
    files = _proc_files
    assert _lint(tmp_path, files([INSTALL, TOUCH])) == ()
    assert "pre_lock_form" in _rules(_lint(tmp_path / "a", files([INSTALL])))
    as_install = (
        "-/usr/bin/timeout -k 1 4 /usr/bin/install -m 0600 /dev/null %t/breezy-studies.lock"
    )
    assert _rules(_lint(tmp_path / "b", files([as_install]))) & {"pre_form", "pre_lock_form"}
    as_install_d = "/usr/bin/timeout -k 1 4 /usr/bin/install -d %t/breezy-studies.lock"
    assert _rules(_lint(tmp_path / "c", files([as_install_d]))) & {"pre_form", "pre_lock_form"}
    assert "pre_form" in _rules(_lint(tmp_path / "d", files([TOUCH.removeprefix("-")])))
    assert "pre_form" in _rules(
        _lint(tmp_path / "e", files([TOUCH.replace("-k 1 4", "-k 1 9")]))
    ), "touch must be exactly timeout -k 1 4"
    assert "pre_lock_form" in _rules(_lint(tmp_path / "f", files([TOUCH, TOUCH])))


def test_touch_is_refused_on_rows_without_studies_lock(tmp_path: Path) -> None:
    assert "pre_lock_form" in _rules(_lint(tmp_path, _selftest_files([TOUCH])))


def test_bus_snapshot_execstartpre_requires_dash_prefix_budget_timeout_and_last(
    tmp_path: Path,
) -> None:
    assert SELFTEST.bus_snapshot_budget_s == 10
    assert _lint(tmp_path, _selftest_files([SNAPSHOT])) == ()
    variants = {
        "no_dash": SNAPSHOT.removeprefix("-"),
        "wrong_kill_after": SNAPSHOT.replace("-k 2 13", "-k 3 13"),
        "budget_not_b_plus_3": SNAPSHOT.replace("-k 2 13", "-k 2 12"),
        "budget_too_large": SNAPSHOT.replace("-k 2 13", "-k 2 14"),
        "wrong_row": SNAPSHOT.replace("selftest", "selftest-proc"),
        "wrong_flag": SNAPSHOT.replace("--bus-snapshot", "--snapshot"),
        "wrong_wrapper": SNAPSHOT.replace(WRAPPER_PATH, "/tmp/breezy-autonomy-bwrap"),
        "not_timeout": SNAPSHOT.replace("/usr/bin/timeout -k 2 13 ", ""),
        "extra_arg": SNAPSHOT + " extra",
    }
    for label, line in variants.items():
        errors = _lint(tmp_path / label, _selftest_files([line]))
        assert _rules(errors) & {"pre_snapshot", "pre_form"}, label
    not_last = _selftest_files([SNAPSHOT, INSTALL])
    assert "pre_order" in _rules(_lint(tmp_path / "not_last", not_last))


def test_bus_rows_require_the_snapshot_line_and_other_rows_refuse_it(tmp_path: Path) -> None:
    assert "pre_snapshot" in _rules(_lint(tmp_path, _selftest_files([INSTALL])))
    notify = _selftest_files([SNAPSHOT], row="breezy-autonomy-selftest-notify")
    assert "pre_snapshot" in _rules(_lint(tmp_path / "b", notify))


def test_pre_lines_must_follow_install_then_touch_then_snapshot(tmp_path: Path) -> None:
    assert _lint(tmp_path, _selftest_files([INSTALL, CHMOD, SNAPSHOT])) == ()
    files = _proc_files
    assert "pre_order" in _rules(_lint(tmp_path / "a", files([TOUCH, INSTALL])))


def test_execstartpre_reset_clears_earlier_lines(tmp_path: Path) -> None:
    text = _unit(
        _exec("breezy-autonomy-t1"),
        service_lines=["ExecStartPre=/usr/bin/true", "ExecStartPre="],
    )
    assert _lint(tmp_path, {**GOOD_FILES, "breezy-autonomy-t1.service": text}) == ()


# ------------------------------------------------------------ bounds


def test_execstartpre_bound_below_timeoutstartsec(tmp_path: Path) -> None:
    two = [INSTALL]  # bound 5
    assert "pre_bound" in _rules(
        _lint(tmp_path / "eq", _selftest_files([INSTALL, SNAPSHOT], timeout="15"))
    )
    assert _lint(tmp_path / "ok", _selftest_files([INSTALL, SNAPSHOT], timeout="20")) == ()
    assert "pre_bound" in _rules(
        _lint(tmp_path / "five", _selftest_files(two + [SNAPSHOT], timeout="5"))
    )
    assert "pre_bound" in _rules(
        _lint(tmp_path / "min", _selftest_files([SNAPSHOT], timeout="15s"))
    )
    assert _lint(tmp_path / "mins", _selftest_files([SNAPSHOT], timeout="1min")) == ()
    assert "pre_bound" in _rules(
        _lint(tmp_path / "us", _selftest_files([SNAPSHOT], timeout="15000000us"))
    )


@pytest.mark.parametrize(
    ("timeout", "ok"),
    [
        ("19", False),
        ("19s", False),
        ("19999ms", False),
        ("20", True),
        ("20s", True),
        ("1min", True),
    ],
)
def test_bus_rows_need_timeoutstartsec_of_budget_plus_ten(
    tmp_path: Path, timeout: str, ok: bool
) -> None:
    """B9-R3: the selftest row's budget is 10 s, so ``TimeoutStartSec`` must be >= 20 s."""
    errors = _lint(tmp_path, _selftest_files([SNAPSHOT], timeout=timeout))
    assert (errors == ()) is ok
    if not ok:
        assert "pre_bound" in _rules(errors)


def test_missing_timeoutstartsec_uses_the_systemd_default(tmp_path: Path) -> None:
    assert DEFAULT_TIMEOUT_START_SEC == 90
    assert _lint(tmp_path, _selftest_files([INSTALL, SNAPSHOT], timeout=None)) == ()


def test_timeoutstartsec_unparsable_or_infinity(tmp_path: Path) -> None:
    assert "pre_bound" in _rules(_lint(tmp_path / "a", _selftest_files([SNAPSHOT], timeout="soon")))
    assert _lint(tmp_path / "b", _selftest_files([SNAPSHOT], timeout="infinity")) == ()


def test_start_phase_bound_sums_pre_lines(tmp_path: Path) -> None:
    path = _write(tmp_path, _selftest_files([INSTALL, SNAPSHOT]))
    assert start_phase_bound_s(path / "breezy-autonomy-selftest.service") == 5 + 15
    proc = _write(
        tmp_path / "p", _selftest_files([INSTALL, TOUCH], row="breezy-autonomy-selftest-proc")
    )
    assert start_phase_bound_s(proc / "breezy-autonomy-selftest-proc.service") == 10
    none = _write(tmp_path / "n", {"breezy-autonomy-t1.service": GOOD_T1})
    assert start_phase_bound_s(none / "breezy-autonomy-t1.service") == 0


def test_start_phase_bound_ignores_lines_cleared_by_a_reset(tmp_path: Path) -> None:
    text = _unit(
        _exec("breezy-autonomy-t1"),
        service_lines=["ExecStartPre=" + INSTALL, "ExecStartPre=", "ExecStartPre=" + INSTALL],
    )
    path = _write(tmp_path, {"breezy-autonomy-t1.service": text}) / "breezy-autonomy-t1.service"
    assert start_phase_bound_s(path) == 5


# ------------------------------------------------------------ scope


def test_every_autonomy_service_file_in_scope(tmp_path: Path) -> None:
    files = {**GOOD_FILES, "breezy-autonomy-stray.service": _unit("/usr/bin/true")}
    errors = _lint(tmp_path, files)
    assert "tripwire" in _rules(errors)
    assert any(error.unit == "breezy-autonomy-stray.service" for error in errors)


def test_owned_units_have_files(tmp_path: Path) -> None:
    owned = frozenset({"breezy-autonomy-ghost.service"})
    row = dataclasses.replace(PLAIN, name="breezy-autonomy-ghost", units=owned)
    table = {**TABLE, row.name: row}
    errors = lint_units(_write(tmp_path, GOOD_FILES), table, owned_units=owned)
    assert "owned_no_file" in _rules(errors)
    ok = lint_units(
        _write(
            tmp_path / "b",
            {**GOOD_FILES, "breezy-autonomy-ghost.service": _unit(_exec("breezy-autonomy-ghost"))},
        ),
        table,
        owned_units=owned,
    )
    assert ok == ()


LINE_ONLY = MappingProxyType({"breezy-recorder.service": "AUT-1 r12 stop hook"})
LABEL = BwrapRow(
    name="breezy-label-x",
    owner_plan="T",
    units=frozenset({"breezy-label-x.service"}),
    binds=("cache/label",),
    entry_modules=("x",),
    resolves_dns=False,
    network="none",
)
LABEL_TABLE: Mapping[str, BwrapRow] = MappingProxyType({**TABLE, LABEL.name: LABEL})


def test_row_unit_outside_the_autonomy_prefix_gets_the_full_lint(tmp_path: Path) -> None:
    bad = {**GOOD_FILES, "breezy-label-x.service": _unit("/usr/bin/true")}
    errors = _lint(tmp_path, bad, table=LABEL_TABLE)
    assert "not_wrapped" in _rules(errors)
    assert any(error.unit == "breezy-label-x.service" for error in errors)
    post = _unit(_exec("breezy-label-x"), post=["/usr/bin/true"])
    errors = _lint(
        tmp_path / "b", {**GOOD_FILES, "breezy-label-x.service": post}, table=LABEL_TABLE
    )
    assert "execstartpost" in _rules(errors)


def test_wrapper_line_only_unit_lints_only_its_wrapper_lines(tmp_path: Path) -> None:
    recorder_shaped = _unit(
        _exec("breezy-recorder"),
        pre=["/usr/bin/true"],
        post=["/usr/bin/true"],
        unit_lines=["OnFailure=breezy-study-failed@%n.service"],
    )
    files = {**GOOD_FILES, "breezy-recorder.service": recorder_shaped}
    assert _lint(tmp_path, files, wrapper_line_only_units=LINE_ONLY) == ()
    # the same file without the exemption is a full-lint failure
    full = _lint(tmp_path, files)
    assert {"execstartpost", "onfailure_study_failed", "pre_form"} <= _rules(full)
    bad_wrapper = _unit(f"{WRAPPER_PATH} breezy-recorder /usr/bin/true")
    errors = _lint(
        tmp_path / "b",
        {**GOOD_FILES, "breezy-recorder.service": bad_wrapper},
        wrapper_line_only_units=LINE_ONLY,
    )
    assert _rules(errors) & {"not_wrapped", "wrapper_order"}
    wrong_row = _unit(_exec("breezy-autonomy-t1"))
    errors = _lint(
        tmp_path / "c",
        {**GOOD_FILES, "breezy-recorder.service": wrong_row},
        wrapper_line_only_units=LINE_ONLY,
    )
    assert "row_not_listing_unit" in _rules(errors)


def test_label_unit_listed_as_wrapper_line_only_lints_only_wrapper_lines(tmp_path: Path) -> None:
    line_only = MappingProxyType({"breezy-label-x.service": "AUT-2 r7 label"})
    text = _unit(_exec("breezy-label-x"), post=["/usr/bin/true"])
    files = {**GOOD_FILES, "breezy-label-x.service": text}
    assert _lint(tmp_path, files, table=LABEL_TABLE, wrapper_line_only_units=line_only) == ()


def test_unit_naming_the_wrapper_but_in_no_row_is_red(tmp_path: Path) -> None:
    files = {**GOOD_FILES, "breezy-stray.service": _unit(_exec("breezy-autonomy-t1"))}
    errors = _lint(tmp_path, files)
    assert "wrapper_unit_not_in_row" in _rules(errors)
    assert any(error.unit == "breezy-stray.service" for error in errors)


def test_unwrapped_residual_unit_must_not_name_the_wrapper(tmp_path: Path) -> None:
    residual = MappingProxyType({"breezy-autonomy-drill.service": "E-7a rule 5 residual"})
    clean = {**GOOD_FILES, "breezy-autonomy-drill.service": _unit("/usr/bin/true")}
    assert _lint(tmp_path, clean, residual_units=residual) == ()
    naming = {**GOOD_FILES, "breezy-autonomy-drill.service": _unit(_exec("breezy-autonomy-t1"))}
    errors = _lint(tmp_path / "b", naming, residual_units=residual)
    assert "residual_wrapped" in _rules(errors)


def test_timer_and_dropin_files_outside_scope_are_ignored(tmp_path: Path) -> None:
    files = {
        **GOOD_FILES,
        "breezy-other.service": _unit("/usr/bin/true"),
        "breezy-other.timer": "[Timer]\nOnCalendar=daily\n",
        "breezy-other.service.d/x.conf": "[Service]\nExecStart=/usr/bin/true\n",
    }
    assert _lint(tmp_path, files) == ()


def test_table_validation_errors_are_not_swallowed(tmp_path: Path) -> None:
    broken = dataclasses.replace(PLAIN, tmpfs_size_bytes=-1)
    with pytest.raises(ValueError):
        lint_units(_write(tmp_path, GOOD_FILES), {broken.name: broken})


# ------------------------------------------------------------ parser


def test_parse_unit_handles_comments_continuations_sections_and_resets() -> None:
    text = (
        "# comment\n; also comment\n[Unit]\nOnFailure=a.service \\\n  b.service\n"
        "[Service]\nExecStart=/bin/a\nExecStart=\nExecStart=/bin/b\n"
    )
    unit = parse_unit(text)
    assert unit.values("Service", "ExecStart") == ["/bin/b"]
    assert unit.values("Unit", "OnFailure") == ["a.service b.service"]
    assert unit.values("Service", "Nothing") == []
