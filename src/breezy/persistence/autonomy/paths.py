"""Autonomy storage paths (ARCH-0 AC 25 `paths`; plan "Paths" table).

Every autonomy path is built by :class:`AutonomyPaths` (production root) or
:class:`ShadowPaths` (the ``registry-shadow/`` root). They are distinct,
unrelated classes: a role check reads the class-level ``is_shadow`` attribute and
never uses ``isinstance``. The two share one layout, defined once in a private
base. Each component is validated against an ``re.ASCII`` ``\\A...\\Z`` pattern
(or ``date.fromisoformat`` with a round trip) before it is joined, so a builder
can never yield a path that escapes the root.

Builders only compute paths. All I/O goes through ``single_read``'s openat walk.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Final

from breezy.persistence.autonomy.wire import SHA256_RE, WireRefusalReason, WireRefused

#: Component patterns (plan "Paths" table). The family pattern is the
#: intersection of ``settings._FAMILY_ID_RE`` and ``trial_day_latch.FAMILY_ID_PATTERN``
#: (V19); both are test-asserted to accept it.
VENUE_RE: Final[re.Pattern[str]] = re.compile(r"\A[a-z0-9_]{1,32}\Z", re.ASCII)
FAMILY_RE: Final[re.Pattern[str]] = re.compile(r"\A[a-z0-9_]{1,64}\Z", re.ASCII)
#: Kept equal to ``family_manifest._COMPOSITION_KINDS`` (test-asserted; not imported: layering).
MODEL_CLASS_RE: Final[re.Pattern[str]] = re.compile(
    r"\A(?:current_rung_hold|continuous_rung_hold|forecast_ladder|forecast_quantile_ladder)"
    r":[a-z_]{1,48}\Z",
    re.ASCII,
)
#: A journal kind is a bare name: it can hold no separator.
JOURNAL_KIND_RE: Final[re.Pattern[str]] = re.compile(r"\A[a-z0-9_]{1,48}\Z", re.ASCII)

SEQ_DIGITS: Final[int] = 10
_SEQ_MAX: Final[int] = 10**SEQ_DIGITS - 1


def _refuse(reason: WireRefusalReason, field: str) -> WireRefused:
    # The detail names the field only, never the offending value or a path.
    return WireRefused(reason, field)


def _match(value: object, pattern: re.Pattern[str], field: str) -> str:
    if not isinstance(value, str):
        raise _refuse(WireRefusalReason.WRONG_TYPE, field)
    if pattern.fullmatch(value) is None:
        raise _refuse(WireRefusalReason.BAD_VALUE, field)
    return value


def venue_component(value: object) -> str:
    return _match(value, VENUE_RE, "venue")


def family_component(value: object) -> str:
    return _match(value, FAMILY_RE, "family_id")


def model_class_component(value: object) -> str:
    return _match(value, MODEL_CLASS_RE, "model_class")


def journal_kind_component(value: object) -> str:
    return _match(value, JOURNAL_KIND_RE, "kind")


def sha_component(value: object, field: str = "sha256") -> str:
    return _match(value, SHA256_RE, field)


def date_component(value: object) -> str:
    """An ISO ``YYYY-MM-DD`` date; compact and week forms are refused by the round trip."""
    if not isinstance(value, str):
        raise _refuse(WireRefusalReason.WRONG_TYPE, "date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise _refuse(WireRefusalReason.BAD_VALUE, "date") from None
    if parsed.isoformat() != value:
        raise _refuse(WireRefusalReason.BAD_VALUE, "date")
    return value


def seq_component(value: object, field: str = "seq") -> int:
    if isinstance(value, bool):
        raise _refuse(WireRefusalReason.BOOL_AS_INT, field)
    if not isinstance(value, int):
        raise _refuse(WireRefusalReason.WRONG_TYPE, field)
    if not 1 <= value <= _SEQ_MAX:
        raise _refuse(WireRefusalReason.BAD_VALUE, field)
    return value


class _Layout:
    """The one storage layout, relative to a registry root."""

    __slots__ = ("_root",)

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path):
            raise _refuse(WireRefusalReason.WRONG_TYPE, "root")
        if not root.is_absolute() or "\0" in str(root):
            raise _refuse(WireRefusalReason.BAD_VALUE, "root")
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self._root)!r})"

    def __eq__(self, other: object) -> bool:
        return (
            type(other) is type(self) and isinstance(other, _Layout) and other._root == self._root
        )

    def __hash__(self) -> int:
        return hash((type(self).__name__, self._root))

    # registry/
    def registry_db(self) -> Path:
        return self._root / "registry" / "registry.sqlite"

    def engine_lock(self) -> Path:
        return self._root / "registry" / "engine.lock"

    def family_file(self, family_id: str) -> Path:
        return self._root / "registry" / "families" / f"{family_component(family_id)}.json"

    def demand_dir(self, venue: str) -> Path:
        return self._root / "registry" / "demand" / venue_component(venue)

    def heartbeat_file(self, venue: str) -> Path:
        return self._root / "registry" / "heartbeat" / f"{venue_component(venue)}.json"

    def drill_marker(self) -> Path:
        return self._root / "registry" / "drill" / "marker.json"

    # evidence/
    def export_dir(self) -> Path:
        return self._root / "evidence" / "registry"

    def export_file(self, venue: str, day: str, *, hwm_export_seq: int | None = None) -> Path:
        suffix = (
            "" if hwm_export_seq is None else f"_hwm{seq_component(hwm_export_seq, 'export_seq')}"
        )
        name = f"registry_{venue_component(venue)}_{date_component(day)}{suffix}.jsonl"
        return self.export_dir() / name

    def journal_dir(self, venue: str, kind: str) -> Path:
        return (
            self._root
            / "evidence"
            / "journal"
            / venue_component(venue)
            / journal_kind_component(kind)
        )

    def journal_file(self, venue: str, kind: str, seq: int) -> Path:
        return self.journal_dir(venue, kind) / f"{seq_component(seq):0{SEQ_DIGITS}d}.json"

    # derived/
    def verdict_dir(self, family_id: str, day: str) -> Path:
        return (
            self._root / "derived" / "verdicts" / family_component(family_id) / date_component(day)
        )

    def verdict_file(self, family_id: str, day: str, verdict_id: str) -> Path:
        return self.verdict_dir(family_id, day) / f"{sha_component(verdict_id, 'verdict_id')}.json"

    def artefact_dir(self, model_class: str, sha: str) -> Path:
        return (
            self._root
            / "derived"
            / "artefacts"
            / model_class_component(model_class)
            / sha_component(sha)
        )

    def artefact_file(self, model_class: str, sha: str) -> Path:
        return self.artefact_dir(model_class, sha) / "artefact.json"

    def root_record(self, model_class: str, sha: str, family_id: str) -> Path:
        """E-14: one ``root/v1`` record per family, beside the shared ``artefact.json``."""
        return self.artefact_dir(model_class, sha) / "roots" / f"{family_component(family_id)}.json"


class AutonomyPaths(_Layout):
    """The production registry root (``~/.local/share/breezy/``)."""

    __slots__ = ()
    is_shadow: Final[bool] = False


class ShadowPaths(_Layout):
    """The ``registry-shadow/`` root: same layout, deliberately an unrelated type."""

    __slots__ = ()
    is_shadow: Final[bool] = True


def default_data_root() -> Path:
    """The production data root. For entry points only; library code takes a root."""
    return Path.home() / ".local" / "share" / "breezy"
