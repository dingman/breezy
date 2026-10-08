"""AUT-6 catalogue literals for the read-only closure lint and the bwrap self-probe.

Plan r15 section 3.1 (E-7 rules 3 and 4, E-7a rule 4), section 3.1.1 and the r10/r11 allowlist
rules: a literal ``AUT6_WRITE_AUTHORITY`` (one row per AUT-6 entry point: the only places it may
write, as paths under ``~/.local/share/breezy/``, and the process calls it may make), the lint's
per-entry-point floor, the self-probe paths, the rollback-journal stores and the read allowlist.
``tests/unit/test_autonomy_readonly_closure.py`` judges each entry point's import closure against
them. A bwrap row (``AUTONOMY_BWRAP_TABLE``) enforces the write scope at the OS level; these
literals are the defence-in-depth lint's input and are never described as enforced for the
unwrapped lines (E-7a rule 5).

Data only. Process calls name no in-sandbox ``systemctl`` read: those arrive through the bus
snapshot pre-line (E-7e(h)). Later work packages add their own rows beside these.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, NamedTuple


class AuthorityRow(NamedTuple):
    """What one entry point may write and which process calls it may make."""

    writes: tuple[str, ...]
    process_calls: tuple[str, ...] = ()


class SelfProbe(NamedTuple):
    """One row's self-probe paths, relative to the data root (section 3.1.1, AE3).

    ``negative`` directories must refuse a create with exactly ``EROFS``; ``positive`` directories
    must accept a create and an unlink. The probe file is ``.aut6_bwrap_probe_<invocation_id>``.
    """

    negative: tuple[str, ...]
    positive: tuple[str, ...]


_ALERTS: Final = "evidence/alerts/**"
_PROBE_FILE: Final = ".aut6_bwrap_probe_*"

AUT6_SELF_PROBE_PATHS: Final[MappingProxyType[str, SelfProbe]] = MappingProxyType(
    {
        # derived from AUTONOMY_BWRAP_TABLE["breezy-autonomy-alert-redeliver"]: the bind is
        # evidence/alerts, so state/, registry/ and its unbound parent evidence/ must refuse.
        "breezy-autonomy-alert-redeliver": SelfProbe(
            negative=("state", "registry", "evidence"),
            positive=("evidence/alerts/.bwrap_probe",),
        ),
    }
)

AUT6_WRITE_AUTHORITY: Final[MappingProxyType[str, AuthorityRow]] = MappingProxyType(
    {
        "breezy-autonomy-producer-intraday#evaluate": AuthorityRow(
            ("derived/verdicts/**", _ALERTS, "cache/aut6_intraday_exec_snapshot/")
        ),
        "breezy-autonomy-producer-intraday#demand": AuthorityRow(
            ("registry/demand/<venue>/", _ALERTS)
        ),
        "breezy-autonomy-producer-daily": AuthorityRow(
            ("derived/verdicts/**", _ALERTS, "cache/aut6_daily_exec_snapshot/")
        ),
        "breezy-autonomy-health": AuthorityRow(
            ("evidence/unit_health/**", "derived/verdicts/**", _ALERTS)
        ),
        "breezy-autonomy-alert-redeliver": AuthorityRow((_ALERTS,)),
        "breezy-autonomy-canary": AuthorityRow((_ALERTS,)),
        "breezy-check-alerts": AuthorityRow((_ALERTS,)),
        "node-sinks": AuthorityRow((_ALERTS,)),
        # the shared self-probe code: only the probe files named in AUT6_SELF_PROBE_PATHS
        "bwrap-self-probe": AuthorityRow(
            tuple(
                rel + "/" + _PROBE_FILE
                for probe in AUT6_SELF_PROBE_PATHS.values()
                for rel in (*probe.negative, *probe.positive)
            )
        ),
        "breezy-autonomy-failed@": AuthorityRow((_ALERTS,)),
    }
)

#: Minimum call sites each entry point's closure must hold, so a lint that judges nothing cannot
#: pass (the M2 floor). The test sums the real call counts of the entry point's modules.
AUT6_LINT_MIN_JUDGED_SITES: Final[MappingProxyType[str, int]] = MappingProxyType(
    {
        "breezy-autonomy-alert-redeliver": 170,
        "breezy-check-alerts": 140,
        "node-sinks": 110,
    }
)

#: Stores whose connections are rollback-journal (not WAL), so AUT-6 may open them in place.
#: None at WP1: AUT-6 opens no SQLite store here.
AUT6_ROLLBACK_JOURNAL_STORES: Final[frozenset[str]] = frozenset()

#: The dotted calls a NON-writer closure may make from the I/O modules (r10, AC6). Any other call
#: rooted in ``os``, ``shutil``, ``tempfile``, ``subprocess``, ``sqlite3``, ``fcntl``, ``socket``,
#: ``ctypes`` or ``importlib`` fails. ``open`` and ``os.open`` are further limited to read forms.
AUT6_READ_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "open",
        "os.open",
        "os.read",
        "os.close",
        "os.fsync",
        "os.stat",
        "os.lstat",
        "os.fstat",
        "os.path.lexists",
        "os.path.exists",
        "os.path.join",
        "fcntl.flock",
    }
)

#: Builtins a closure may call without an allowlist entry; ``print`` is stdout only.
AUT6_PURE_BUILTINS: Final[frozenset[str]] = frozenset(
    {
        "abs", "all", "any", "bool", "bytes", "callable", "dict", "enumerate", "float",
        "frozenset", "getattr", "hasattr", "id", "int", "isinstance", "iter", "len", "list", "max",
        "memoryview", "min", "next", "object", "print", "range", "repr", "reversed", "set",
        "sorted", "str", "sum", "super", "tuple", "type", "zip",
    }
)  # fmt: skip
