"""ARCH-0 seam B (WP-B2b-1): the autonomy sandbox table and ``validate_table``.

Every rule has a failing fixture, so a rule that is silently dropped turns a
named test red (plan r5, "Test Strategy"). Rows are built by
``dataclasses.replace`` from the shipped selftest row; nothing here touches the
filesystem or bwrap.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

import pytest

from breezy.runtime.autonomy_sandbox import table as table_module
from breezy.runtime.autonomy_sandbox.table import (
    ALTERNATE_BIND_BASES,
    AUTONOMY_BWRAP_TABLE,
    AUTONOMY_OWNED_UNITS,
    CONFIG_RO_ALLOWLIST,
    CREDENTIAL_ENV_DENIED_EXACT,
    CREDENTIAL_ENV_DENIED_PREFIXES,
    KNOWN_EXCEPTIONS,
    NOTIFIER_FALLBACK_ROWS,
    RUN_TRANSIENT_SHOW_ARGV,
    UNWRAPPED_RESIDUAL_UNITS,
    WRAPPER_LINE_ONLY_UNITS,
    BusRead,
    BwrapRow,
    PositiveProbe,
    TableError,
    unit_matches_row,
    validate_table,
)

SYSTEMCTL = "/usr/bin/systemctl"
SELFTEST = "breezy-autonomy-selftest"
SECRET_NAME = "polymarket_us_secret_key"
SECRET_ENV = "POLYMARKET_US_SECRET_KEY_FILE"
RECONCILE = frozenset({"E7A_R2_RECONCILE"})


def _row(name: str = SELFTEST) -> BwrapRow:
    return AUTONOMY_BWRAP_TABLE[name]


def _plain(**changes: Any) -> BwrapRow:
    """The selftest row with the bus surface stripped, then ``changes`` applied."""
    stripped = {"bus_reads": (), "bus_snapshot_bind": None, "bus_snapshot_budget_s": None}
    return dataclasses.replace(_row(), **{**stripped, **changes})


def _with(**changes: Any) -> BwrapRow:
    return dataclasses.replace(_row(), **changes)


def _table(*rows: BwrapRow) -> Mapping[str, BwrapRow]:
    return MappingProxyType({row.name: row for row in rows})


def _invalid(row: BwrapRow, match: str | None = None) -> None:
    with pytest.raises(TableError, match=match):
        validate_table(_table(row))


def _read(*tail: str, verb: str = "show") -> BusRead:
    return BusRead("r", (SYSTEMCTL, "--user", verb, *tail))


# --------------------------------------------------------------- shipped table


def test_shipped_table_validates() -> None:
    validate_table()


def test_shipped_table_has_exactly_the_seam_b_stop_hook_and_capture_rows() -> None:
    assert set(AUTONOMY_BWRAP_TABLE) == {
        "breezy-autonomy-selftest",
        "breezy-autonomy-selftest-notify",
        "breezy-autonomy-selftest-proc",
        "breezy-quote-tape.stop-hook",
        "breezy-capture-settlement",
        "breezy-capture-audit",
        "breezy-capture-live-proof",
    }
    assert all(name == row.name for name, row in AUTONOMY_BWRAP_TABLE.items())


def test_selftest_row_shape() -> None:
    row = _row("breezy-autonomy-selftest")
    assert row.binds == ("cache/autonomy_selftest",)
    assert row.resolves_dns is True
    assert row.bus_snapshot_bind == "cache/autonomy_selftest"
    assert row.bus_snapshot_budget_s == 10
    assert [read.name for read in row.bus_reads] == ["self_show"]
    assert row.bus_reads[0].argv == (
        SYSTEMCTL,
        "--user",
        "show",
        "-p",
        "Id,ActiveState",
        "--",
        "breezy-autonomy-selftest.service",
    )
    assert row.exceptions == frozenset()


def test_selftest_notify_row_shape() -> None:
    row = _row("breezy-autonomy-selftest-notify")
    assert row.exceptions == {"E7A_R2_NOTIFY"}
    assert row.resolves_dns is False
    assert row.binds == ("cache/autonomy_selftest",)
    assert row.bus_reads == ()


def test_selftest_proc_row_shape() -> None:
    row = _row("breezy-autonomy-selftest-proc")
    assert row.exceptions == {"E7A_R2_PROC", "E7_STUDIES_LOCK"}
    assert row.host_proc is True
    assert row.studies_lock is True
    assert row.resolves_dns is False
    assert row.binds == ("cache/autonomy_selftest",)


def test_every_shipped_row_matches_its_own_unit_name() -> None:
    for name, row in AUTONOMY_BWRAP_TABLE.items():
        # A ``unit.label`` row (the AUT-1 stop hook) names its unit by the stem before the dot.
        assert unit_matches_row(row, f"{name.split('.', 1)[0]}.service")


# -------------------------------------------------------------- module constants


def test_known_exceptions_exact() -> None:
    assert KNOWN_EXCEPTIONS == frozenset(
        {
            "E7A_R2_PROC",
            "E7A_R2_NOTIFY",
            "E7A_R2_RECONCILE",
            "E7B_EVAL_OFFLINE_ADAPTER_MODULES",
            "E7_CONFIG_DIR",
            "E7_STUDIES_LOCK",
            "E7_FIXTURE_ROOT",
        }
    )
    assert len(KNOWN_EXCEPTIONS) == 7


def test_constants_have_the_seam_b_values() -> None:
    assert dict(ALTERNATE_BIND_BASES) == {"aut4_fixture": ".local/share/breezy-autonomy-fixture"}
    assert NOTIFIER_FALLBACK_ROWS == frozenset()
    assert AUTONOMY_OWNED_UNITS == frozenset()
    assert dict(UNWRAPPED_RESIDUAL_UNITS) == {}
    assert CREDENTIAL_ENV_DENIED_EXACT == frozenset(
        {
            "PATH",
            "HOME",
            "TMPDIR",
            "GLIBC_TUNABLES",
            "GCONV_PATH",
            "LOCPATH",
            "NOTIFY_SOCKET",
            "CREDENTIALS_DIRECTORY",
            "BASH_ENV",
            "NODE_OPTIONS",
        }
    )
    assert CREDENTIAL_ENV_DENIED_PREFIXES == (
        "XDG_",
        "LD_",
        "PYTHON",
        "BREEZY_AUTONOMY_",
        "SSL_CERT_",
    )
    assert RUN_TRANSIENT_SHOW_ARGV == (
        SYSTEMCTL,
        "--user",
        "show",
        "-p",
        "Id,Description,ExecStart,InvocationID,Result,Transient",
        "--",
        "run-*.service",
    )


def test_no_bus_action_or_user_bus_surface() -> None:
    assert not [label for label in KNOWN_EXCEPTIONS if "BUS" in label]
    fields = {field.name for field in dataclasses.fields(BwrapRow)}
    assert not [name for name in fields if "bus_action" in name or "user_bus" in name]
    for verb in ("kill", "start", "stop", "restart", "try-restart"):
        _invalid(_with(bus_reads=(_read("--", "breezy-x.service", verb=verb),)))
    _invalid(_with(bus_reads=(BusRead("r", ("/usr/bin/systemd-run", "--user", "true")),)))


# --------------------------------------------------------------------- bus grammar


@pytest.mark.parametrize(
    "argv",
    [
        (SYSTEMCTL, "--user", "show", "-p", "Id,ActiveState", "--", "breezy-x.service"),
        (SYSTEMCTL, "--user", "show", "--property=Id,Result", "--", "breezy-x@y_z.service"),
        (SYSTEMCTL, "--user", "show", "-p", "Id", "--value", "--", "{instance}"),
        (SYSTEMCTL, "--user", "list-units", "--failed", "--all", "--plain", "--no-legend"),
        (SYSTEMCTL, "--user", "list-units", "--state=failed", "--type=service", "--no-pager"),
        (SYSTEMCTL, "--user", "list-timers", "--all", "--", "breezy-*.timer"),
        RUN_TRANSIENT_SHOW_ARGV,
    ],
)
def test_bus_read_valid_grammar_accepted(argv: tuple[str, ...]) -> None:
    validate_table(_table(_with(bus_reads=(BusRead("r", argv),))))


@pytest.mark.parametrize(
    "tail",
    [
        ("--", "breezy-*"),
        ("--", "breezy-x.service"),
        ("--value", "--", "breezy-x.service"),
        ("--all", "--plain", "--", "breezy-x.service"),
        ("-p", "Id"),
        ("--property=Id",),
        ("-p", "Id", "--value"),
        (),
    ],
    ids=[
        "glob",
        "unit",
        "value-only",
        "bare-options",
        "p-no-units",
        "prop-no-units",
        "p-value",
        "bare",
    ],
)
def test_show_requires_a_property_and_double_dash_units(tail: tuple[str, ...]) -> None:
    """B9-R1: an unbounded ``show`` would dump ``Environment=`` and the credentials."""
    _invalid(_with(bus_reads=(_read(*tail),)), match="show")


@pytest.mark.parametrize(
    "tail",
    [
        ("-p", "Id", "--", "breezy-x.service"),
        ("--property=Id,Result", "--", "breezy-x.service"),
        ("--value", "-p", "Id", "--", "breezy-x.service"),
    ],
)
def test_show_with_a_property_and_units_is_accepted(tail: tuple[str, ...]) -> None:
    validate_table(_table(_with(bus_reads=(_read(*tail),))))


@pytest.mark.parametrize(
    "argv",
    [
        (),
        (SYSTEMCTL,),
        ("systemctl", "--user", "show", "--", "breezy-x.service"),
        ("/bin/systemctl", "--user", "show", "--", "breezy-x.service"),
        (SYSTEMCTL, "--system", "show", "--", "breezy-x.service"),
        (SYSTEMCTL, "show", "--user", "--", "breezy-x.service"),
        (SYSTEMCTL, "--user", "is-active", "--", "breezy-x.service"),
        (SYSTEMCTL, "--user", "daemon-reload"),
        (SYSTEMCTL, "--user", "show", "--no-block", "--", "breezy-x.service"),
        (SYSTEMCTL, "--user", "show", "--host=other", "--", "breezy-x.service"),
        (SYSTEMCTL, "--user", "show", "-pId", "--", "breezy-x.service"),
        (SYSTEMCTL, "--user", "show", "--property=Id;x", "--", "breezy-x.service"),
    ],
)
def test_bus_read_other_verbs_binaries_and_options_refused(argv: tuple[str, ...]) -> None:
    _invalid(_with(bus_reads=(BusRead("r", argv),)))


@pytest.mark.parametrize(
    "tail",
    [
        ("-p", "Id", "ActiveState", "--", "breezy-x.service"),
        ("-p", "Id;kill", "--", "breezy-x.service"),
        ("-p", "Id ActiveState", "--", "breezy-x.service"),
        ("-p", "Id2", "--", "breezy-x.service"),
        ("-p", "", "--", "breezy-x.service"),
        ("-p", "--", "breezy-x.service"),
        ("-p",),
    ],
)
def test_bus_read_dash_p_takes_one_property_token(tail: tuple[str, ...]) -> None:
    _invalid(_with(bus_reads=(_read(*tail),)))


@pytest.mark.parametrize(
    "tail",
    [
        ("breezy-x.service",),
        ("-p", "Id", "breezy-x.service"),
        ("-p", "Id", "--"),
        ("-p", "Id", "--", "--", "breezy-x.service"),
        ("-p", "Id", "--", "breezy-x.service", "--", "breezy-y.service"),
        ("-p", "Id", "--", "sshd.service"),
        ("-p", "Id", "--", "-all"),
        ("-p", "Id", "--", "breezy-x.service", "--all"),
        ("-p", "Id", "--", "breezy-x;rm"),
        ("-p", "Id", "--", "breezy-$x.service"),
        ("-p", "Id", "--", "{instance}x"),
        ("-p", "Id", "--", "breezy-X.service"),
    ],
)
def test_bus_read_units_follow_double_dash(tail: tuple[str, ...]) -> None:
    _invalid(_with(bus_reads=(_read(*tail),)))


@pytest.mark.parametrize(
    "tail",
    [
        ("-p", "Id,Description,ExecStart,InvocationID,Result,Transient", "--", "run-*"),
        ("-p", "Id", "--", "run-*.service"),
        ("-p", "Id", "--", "run-*"),
        ("-p", "Id", "--", "run-1234.service"),
        ("-p", "Id,Description,ExecStart,InvocationID,Result,Transient", "--", "run-*.mount"),
        ("-p", "Id,Description,ExecStart,InvocationID,Result", "--", "run-*.service"),
    ],
)
def test_run_transient_show_argv_is_only_run_form(tail: tuple[str, ...]) -> None:
    _invalid(_with(bus_reads=(_read(*tail),)))


def test_bus_read_names_unique() -> None:
    read = _row().bus_reads[0]
    _invalid(_with(bus_reads=(read, read)), match="unique")


# -------------------------------------------------------------- bus snapshot rules


@pytest.mark.parametrize(
    "bind",
    ["data/x", "cachefoo/x", "cache", "cache/", "registry/cache/x", None],
)
def test_bus_snapshot_bind_must_be_cache_bind(bind: str | None) -> None:
    binds = ("cache/autonomy_selftest", *([bind] if bind else []))
    _invalid(_with(binds=binds, bus_snapshot_bind=bind))


def test_bus_snapshot_bind_must_be_in_binds() -> None:
    _invalid(_with(bus_snapshot_bind="cache/other"))


def test_bus_snapshot_bind_absent_when_no_reads() -> None:
    _invalid(_plain(bus_snapshot_bind="cache/autonomy_selftest"))
    _invalid(_plain(bus_snapshot_budget_s=10))


@pytest.mark.parametrize("budget", [0, -1, 1, 2, 3, 4, 26, 100, None, True, "10", 10.0])
def test_bus_snapshot_budget_range_and_required_with_reads(budget: Any) -> None:
    _invalid(_with(bus_snapshot_budget_s=budget))


@pytest.mark.parametrize("budget", [5, 10, 25])
def test_bus_snapshot_budget_bounds_accepted(budget: int) -> None:
    """B9-R5: the floor is 5 s (a budget of 1 s would skip every read)."""
    validate_table(_table(_with(bus_snapshot_budget_s=budget)))


def _reads(count: int) -> tuple[BusRead, ...]:
    return tuple(
        BusRead(f"r{i}", (SYSTEMCTL, "--user", "show", "-p", "Id", "--", "breezy-x.service"))
        for i in range(count)
    )


@pytest.mark.parametrize(
    ("count", "budget"),
    [(1, 5), (2, 5), (3, 7), (4, 8), (4, 25), (10, 17), (10, 25)],
)
def test_budget_covers_two_seconds_plus_one_and_a_half_per_read(count: int, budget: int) -> None:
    validate_table(_table(_with(bus_reads=_reads(count), bus_snapshot_budget_s=budget)))


@pytest.mark.parametrize(
    ("count", "budget"),
    [(3, 5), (3, 6), (4, 7), (5, 9), (10, 16), (15, 24), (16, 25)],
)
def test_budget_below_two_plus_one_and_a_half_per_read_is_refused(count: int, budget: int) -> None:
    _invalid(_with(bus_reads=_reads(count), bus_snapshot_budget_s=budget), match="budget")


# ------------------------------------------------------------------ credential_env


def _credential_row(env: Mapping[str, str], names: tuple[str, ...] = (SECRET_NAME,)) -> BwrapRow:
    return _plain(
        exceptions=RECONCILE,
        credential_names=names,
        credential_env=MappingProxyType(dict(env)),
    )


def test_credential_row_valid() -> None:
    validate_table(_table(_credential_row({SECRET_ENV: SECRET_NAME})))


def test_credential_env_biconditional_and_values_equal_names() -> None:
    # names without env, env without names, and the label without either
    _invalid(_credential_row({}))
    _invalid(_plain(exceptions=RECONCILE))
    _invalid(
        _plain(
            credential_env=MappingProxyType({SECRET_ENV: SECRET_NAME}),
            exceptions=frozenset(),
        )
    )
    _invalid(
        _plain(
            credential_names=(SECRET_NAME,),
            credential_env=MappingProxyType({SECRET_ENV: SECRET_NAME}),
        ),
        match="E7A_R2_RECONCILE",
    )
    # values must equal the set of names, in both directions
    _invalid(_credential_row({SECRET_ENV: "some_other_name"}))
    _invalid(_credential_row({SECRET_ENV: SECRET_NAME}, names=(SECRET_NAME, "second")))
    _invalid(_credential_row({SECRET_ENV: SECRET_NAME, "OTHER_FILE": "extra"}))
    # duplicate names are refused
    _invalid(_credential_row({SECRET_ENV: SECRET_NAME}, names=(SECRET_NAME, SECRET_NAME)))
    # several names, one variable each, is fine
    validate_table(
        _table(
            _credential_row(
                {SECRET_ENV: SECRET_NAME, "OTHER_FILE": "second"}, names=("second", SECRET_NAME)
            )
        )
    )


@pytest.mark.parametrize("key", ["lower", "1LEADING", "HAS-DASH", "HAS SPACE", ""])
def test_credential_env_key_shape(key: str) -> None:
    _invalid(_credential_row({key: SECRET_NAME}))


@pytest.mark.parametrize(
    "key",
    [
        "PATH",
        "HOME",
        "TMPDIR",
        "XDG_RUNTIME_DIR",
        "XDG_CACHE_HOME",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHON",
        "BREEZY_AUTONOMY_BWRAP_ROW",
        "BREEZY_AUTONOMY_SANDBOX_DEGRADED",
        "GLIBC_TUNABLES",
        "GCONV_PATH",
        "LOCPATH",
        "NOTIFY_SOCKET",
        "CREDENTIALS_DIRECTORY",
        "BASH_ENV",
        "NODE_OPTIONS",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    ],
)
def test_credential_env_key_denylist(key: str) -> None:
    _invalid(_credential_row({key: SECRET_NAME}), match="denied")


@pytest.mark.parametrize("key", [SECRET_ENV, "PATHS", "HOME_DIR", "XDG", "LDX", "BREEZY_OTHER"])
def test_credential_env_key_outside_denylist_is_valid(key: str) -> None:
    validate_table(_table(_credential_row({key: SECRET_NAME})))


# ------------------------------------------------- B6-R3 bus properties, B6-R2 config


@pytest.mark.parametrize(
    "tail",
    [
        ("-p", "Environment", "--", "breezy-x.service"),
        ("-p", "Id,LoadCredential", "--", "breezy-x.service"),
        ("-p", "EnvironmentFiles", "--", "breezy-x.service"),
        ("--property=Id,LoadCredential", "--", "breezy-x.service"),
        ("--property=PassEnvironment", "--", "breezy-x.service"),
        ("-p", "SetCredential", "--", "breezy-x.service"),
    ],
)
def test_bus_read_environment_and_credential_properties_refused(tail: tuple[str, ...]) -> None:
    _invalid(_with(bus_reads=(_read(*tail),)))


def test_config_ro_allowlist_is_exact() -> None:
    assert frozenset({".config/systemd/user"}) == CONFIG_RO_ALLOWLIST


def _config_row(**changes: Any) -> BwrapRow:
    return _with(exceptions=_row().exceptions | {"E7_CONFIG_DIR"}, **changes)


def test_config_dir_on_allowlist_with_label_is_valid() -> None:
    validate_table(_table(_config_row(config_ro_dirs=(".config/systemd/user",))))
    validate_table(_table(_config_row(config_ro_binds=(".config/systemd/user",))))


@pytest.mark.parametrize("field", ["config_ro_binds", "config_ro_dirs"])
def test_config_entry_without_the_label_refused(field: str) -> None:
    _invalid(_with(**{field: (".config/systemd/user",)}), match="E7_CONFIG_DIR")


@pytest.mark.parametrize("field", ["config_ro_binds", "config_ro_dirs"])
@pytest.mark.parametrize("rel", [".ssh", ".config/systemd", ".config/systemd/user/x", ".config"])
def test_config_entry_off_the_allowlist_refused(field: str, rel: str) -> None:
    _invalid(_config_row(**{field: (rel,)}), match="allowlist")


# --------------------------------------------------------- exception label biconditionals


def test_host_proc_iff_proc_label() -> None:
    _invalid(_plain(host_proc=True))
    _invalid(_plain(exceptions=frozenset({"E7A_R2_PROC"})))
    validate_table(_table(_plain(host_proc=True, exceptions=frozenset({"E7A_R2_PROC"}))))


def test_studies_lock_iff_studies_label() -> None:
    _invalid(_plain(studies_lock=True))
    _invalid(_plain(exceptions=frozenset({"E7_STUDIES_LOCK"})))


def test_alternate_base_iff_fixture_label() -> None:
    _invalid(_plain(bind_base="aut4_fixture"))
    _invalid(_plain(exceptions=frozenset({"E7_FIXTURE_ROOT"})))
    validate_table(
        _table(_plain(bind_base="aut4_fixture", exceptions=frozenset({"E7_FIXTURE_ROOT"})))
    )


def test_unknown_alternate_base_and_unknown_label_refused() -> None:
    _invalid(_plain(bind_base="nope", exceptions=frozenset({"E7_FIXTURE_ROOT"})))
    _invalid(_plain(exceptions=frozenset({"E7_USER_BUS"})), match="unknown")


# ------------------------------------------------------------------ structural rules


@pytest.mark.parametrize(
    "binds",
    [
        ("/abs/path",),
        ("cache/../state",),
        ("cache//x",),
        ("cache/./x",),
        ("",),
        (".",),
        ("state",),
        ("state/x",),
        ("cache/x", "cache/x"),
        ("cache/x", "cache/x/y"),
        ("cache/x/y", "cache/x"),
    ],
)
def test_binds_must_be_normalised_relative_distinct_and_not_nested(binds: tuple[str, ...]) -> None:
    _invalid(_plain(binds=binds))


@pytest.mark.parametrize("size", [0, -5, True, "256", 1.5])
def test_tmpfs_size_malformed_refused(size: Any) -> None:
    _invalid(_plain(tmpfs_size_bytes=size))


def test_tmpfs_size_valid_and_none() -> None:
    validate_table(_table(_plain(tmpfs_size_bytes=1 << 20)))
    validate_table(_table(_plain(tmpfs_size_bytes=None)))


@pytest.mark.parametrize("name", ["Breezy-x", "x", "breezy-", "breezy-a b", "breezy-x/y"])
def test_row_name_must_match_the_row_grammar(name: str) -> None:
    _invalid(_plain(name=name, units=frozenset()))


def test_table_key_must_equal_row_name() -> None:
    with pytest.raises(TableError, match="key"):
        validate_table(MappingProxyType({"breezy-other": _row()}))


@pytest.mark.parametrize(
    "units", [frozenset(), frozenset({"breezy-x"}), frozenset({"sshd.service"})]
)
def test_units_must_be_non_empty_breezy_services_or_templates(units: frozenset[str]) -> None:
    _invalid(_plain(units=units))


def test_positive_probe_keys_must_be_binds_and_kind_known() -> None:
    validate_table(
        _table(
            _plain(
                positive_probe=MappingProxyType(
                    {"cache/autonomy_selftest": PositiveProbe("subdir")}
                )
            )
        )
    )
    _invalid(_plain(positive_probe=MappingProxyType({"cache/zzz": PositiveProbe("subdir")})))
    _invalid(
        _plain(positive_probe=MappingProxyType({"cache/autonomy_selftest": PositiveProbe("write")}))
    )


def test_empty_table_refused() -> None:
    with pytest.raises(TableError):
        validate_table(MappingProxyType({}))


# ------------------------------------------------------------------ unit-name matching


@pytest.mark.parametrize(
    ("leaf", "expected"),
    [
        ("breezy-tpl@pm_us.service", True),
        ("breezy-tpl@a@b.c-d_e.service", True),
        ("breezy-tpl@-x.service", False),
        ("breezy-tpl@.service", False),
        ("breezy-tpl@.x.service", False),
        ("breezy-tpl@A.service", False),
        ("breezy-tpl@x/y.service", False),
        ("breezy-tpl@" + "a" * 202 + ".service", False),
        ("breezy-tpl@" + "a" * 201 + ".service", True),
        ("breezy-tpl.service", False),
        ("breezy-tpl@x.timer", False),
        ("breezy-other@x.service", False),
    ],
)
def test_unit_matches_template_row(leaf: str, expected: bool) -> None:
    row = _plain(name="breezy-tpl", units=frozenset({"breezy-tpl@"}))
    assert unit_matches_row(row, leaf) is expected


# ------------------------------------------------------------------ residual units


def test_unwrapped_residual_units_disjoint_and_cited() -> None:
    table = _table(_row())
    row_unit = f"{SELFTEST}.service"
    cite = "E-7a rule 5 residual: drill runs unwrapped"
    validate_table(table, residual_units=MappingProxyType({"breezy-drill.service": cite}))
    # disjoint from the row units
    with pytest.raises(TableError, match="disjoint"):
        validate_table(table, residual_units=MappingProxyType({row_unit: cite}))
    # disjoint from the owned units
    with pytest.raises(TableError, match="disjoint"):
        validate_table(
            table,
            owned_units=frozenset({"breezy-drill.service"}),
            residual_units=MappingProxyType({"breezy-drill.service": cite}),
        )
    # every residual carries a rule-5 citation
    for bad in ("", "no citation here", "  "):
        with pytest.raises(TableError, match="cit"):
            validate_table(table, residual_units=MappingProxyType({"breezy-drill.service": bad}))


def test_module_exposes_no_state_changing_bus_verbs() -> None:
    allowed = table_module.BUS_READ_VERBS
    assert allowed == frozenset({"show", "list-units", "list-timers"})


# ------------------------------------------------------- wrapper-line-only units


def test_wrapper_line_only_units_subset_of_row_units_and_disjoint() -> None:
    assert set(WRAPPER_LINE_ONLY_UNITS) == {"breezy-quote-tape.service"}
    table = AUTONOMY_BWRAP_TABLE
    row_unit = next(iter(next(iter(table.values())).units))
    cite = MappingProxyType({row_unit: "AUT-1 r12 stop hook"})
    validate_table(table, wrapper_line_only_units=cite)
    with pytest.raises(TableError):
        validate_table(
            table, wrapper_line_only_units=MappingProxyType({"breezy-x.service": "AUT-1"})
        )
    with pytest.raises(TableError):
        validate_table(table, owned_units=frozenset({row_unit}), wrapper_line_only_units=cite)
    with pytest.raises(TableError):
        validate_table(
            table,
            residual_units=MappingProxyType({row_unit: "E-7a rule 5"}),
            wrapper_line_only_units=cite,
        )
    with pytest.raises(TableError):
        validate_table(table, wrapper_line_only_units=MappingProxyType({row_unit: ""}))
