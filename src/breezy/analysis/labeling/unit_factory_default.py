"""The default ``UnitFactory`` of ``label_run`` (TE-1 WP-A): production deps for the promoted unit.

``factory(args) -> UnitWiring`` keeps the existing ``UnitFactory`` contract. It refuses with
:class:`~breezy.analysis.labeling.unit_wiring.ProducerUnpinned` while ``aut2.label`` is not pinned
to the closure of ``label_run`` (checked FIRST, through the ``unit_wiring`` module attribute so a
test can substitute it), then composes :mod:`~breezy.analysis.labeling.unit_wiring` with the studies
flock. Everything it reads from the host arrives through :class:`FactorySeams`, so a test replaces
each path and the factory body is the production body.

``label_run`` imports this module lazily (inside ``_resolve_factory``): a module-level import
would be a cycle, because this module imports ``UnitWiring`` and ``StudiesFlock`` from it.
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import json
import os
import sys
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from breezy.analysis.autonomy.offline_plugins import OFFLINE_PLUGINS
from breezy.analysis.labeling import unit_wiring
from breezy.analysis.labeling.epoch import C1Epoch
from breezy.analysis.labeling.label_core import LabelRunDeps
from breezy.analysis.labeling.label_run import (
    StudiesFlock,
    UnitContext,
    UnitWiring,
    default_paths,
    snapshot_exec_db,
)
from breezy.analysis.labeling.memory_gate import missing_aut6_reading
from breezy.persistence.family_manifest import (
    FamilyManifest,
    FamilyManifestError,
    load_family_manifest,
)
from breezy.persistence.scored_trial_dedupe import _default_scored_trials_dir, dedupe_scored_trials
from breezy.persistence.scored_trial_store import read_scored_trials_pooled
from breezy.runtime.alert_outbox import default_alerts_root
from breezy.runtime.autonomy_sandbox.bwrap import default_roots
from breezy.runtime.autonomy_sandbox.run_mounts import STUDIES_LOCK_NAME
from breezy.runtime.health import resolve_alert_sink

__all__ = ["FactorySeams", "context_allows", "default_seams", "factory"]

_CGROUP_ROOT = Path("/sys/fs/cgroup")
_PROC_CGROUP = Path("/proc/self/cgroup")


@dataclass(frozen=True)
class FactorySeams:
    """Everything the default factory reads from the host; tests replace each one."""

    data_root: Path
    exec_db: Path
    families_dir: Path
    scored_trials_dir: Path
    catalog_base: Path
    lock_path: Path
    alerts_root: Path
    proc_cgroup_text: str
    cgroup_root: Path
    open_catalog: Callable[[Path, str, str], Any]
    make_sink: Callable[[], object]
    time_ns: Callable[[], int]
    snapshot: Callable[[Path, Path], AbstractContextManager[Path]]


def context_allows(context: UnitContext, *, measure: bool) -> bool:
    """Default mode needs the label unit itself. ``--measure-peak`` additionally accepts the
    transient measurement unit: its ``run-r<hex>.service`` name is what ``systemd-run`` gives ANY
    transient unit (a unit-launched gate included), so it must never unlock the default path."""
    if context.is_label_unit():
        return True
    return measure and context.is_measure_unit()


def _under_pytest() -> bool:
    return "pytest" in sys.modules or bool(os.environ.get("PYTEST_CURRENT_TEST"))


def default_seams(measure: bool = False) -> FactorySeams:
    """The live host's seams. Only the label unit (or, for ``--measure-peak``, its measurement
    unit) may read them, and never a test run.

    ``main`` already refuses outside the unit, but it takes its context as an argument; this check
    reads the REAL process context, so a caller that injects an in-unit context (a test, a stray
    import) still cannot make the production factory touch the live data root, the host studies
    flock or the alert outbox. A process that has imported pytest is refused outright: tests inject
    their own seams, and a perfect context must not turn a test into a live run.
    """
    if _under_pytest():
        raise unit_wiring.HostSeamsRefused("the production seams are never read under pytest")
    if not context_allows(UnitContext.current(), measure=measure):
        raise unit_wiring.HostSeamsRefused("the production seams are read only inside the unit")
    return _host_seams()


def _host_seams() -> FactorySeams:  # pragma: no cover - reads the live host
    from breezy.persistence.catalog import open_station_catalog

    roots = default_roots()
    paths = default_paths(roots.home)
    try:
        proc = _PROC_CGROUP.read_text(encoding="utf-8")
    except OSError:
        proc = ""
    return FactorySeams(
        data_root=paths.data_root,
        exec_db=paths.exec_db,
        families_dir=roots.repo_root / "deploy" / "families",
        scored_trials_dir=_default_scored_trials_dir(),
        catalog_base=roots.data_root / "catalog",
        lock_path=roots.run_user / STUDIES_LOCK_NAME,
        alerts_root=default_alerts_root(),
        proc_cgroup_text=proc,
        cgroup_root=_CGROUP_ROOT,
        open_catalog=open_station_catalog,
        make_sink=resolve_alert_sink,
        time_ns=time.time_ns,
        snapshot=snapshot_exec_db,
    )


#: Manifest kinds whose loss would silently shrink the attribution: FQ and the retired CRH pair.
_REQUIRED_KINDS = frozenset(
    {"forecast_quantile_ladder", "current_rung_hold", "continuous_rung_hold"}
)


def _composition_kind_of(path: Path) -> str | None:
    """The raw ``composition_kind`` of a json file, ``None`` for a non-manifest artefact."""
    try:
        wire = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FamilyManifestError(f"{path.name} is not readable json") from exc
    kind = wire.get("composition_kind") if isinstance(wire, dict) else None
    return kind if isinstance(kind, str) else None


def _load_manifests(families_dir: Path) -> tuple[FamilyManifest, ...]:
    """Every family manifest under ``families_dir``.

    A json that is not a manifest (a boundary artefact) is skipped, as the report's own
    enumeration skips it, but never silently: ``AUT2 MANIFEST_SKIPPED path=<file>`` is printed. A
    file that fails to load and is (or cannot be shown not to be) an FQ or CRH manifest raises,
    because attribution would otherwise lose a family without any signal."""
    manifests: list[FamilyManifest] = []
    for path in sorted(families_dir.glob("*.json")):
        try:
            manifests.append(load_family_manifest(path, allow_draft=True))
        except FamilyManifestError:
            print(f"AUT2 MANIFEST_SKIPPED path={path}")
            if _composition_kind_of(path) in _REQUIRED_KINDS:
                raise
    return tuple(manifests)


def _exec_db_of(args: argparse.Namespace, seams: FactorySeams, data_root: Path) -> Path:
    """``--exec-db`` as given, else a snapshot of the exec store held until the process ends."""
    if args.exec_db is not None:
        return Path(args.exec_db)
    stack = contextlib.ExitStack()
    path = stack.enter_context(
        seams.snapshot(data_root, data_root / "cache" / "label_run_snapshot")
    )
    atexit.register(stack.close)
    return path


def factory(args: argparse.Namespace, seams: FactorySeams | None = None) -> UnitWiring:
    """Production deps for the label unit; raises ``ProducerUnpinned`` while ``aut2.label`` is not
    pinned (the unit then exits 2 ``reason=producer_unpinned`` and writes nothing)."""
    pinned, code_sha = unit_wiring.producer_pin_state()
    if not pinned:
        raise unit_wiring.ProducerUnpinned("aut2.label is not pinned to the label_run closure")
    chosen = (
        seams if seams is not None else default_seams(bool(getattr(args, "measure_peak", False)))
    )
    now_ns = args.now_ns if args.now_ns is not None else chosen.time_ns()
    data_root = Path(args.data_root) if args.data_root is not None else chosen.data_root
    exec_db = _exec_db_of(args, chosen, data_root)
    venue = args.venue
    manifests = _load_manifests(chosen.families_dir)
    families = unit_wiring.family_infos(manifests)
    pooled = read_scored_trials_pooled(chosen.scored_trials_dir)
    scored = {t.trial_id: t for t in dedupe_scored_trials(pooled.rows)[0]}
    lag = unit_wiring.LagRule(
        activation_ns=unit_wiring.activation_ns(data_root, now_ns),
        deadline_of=unit_wiring.fill_deadline_ns(venue),
    )
    planner = unit_wiring.build_planner(
        exec_db=exec_db,
        venue=venue,
        manifests=manifests,
        families=families,
        evidence=C1Epoch(data_root, venue=venue, family_id=args.family),
        scored_trials=scored,
        release_ns=unit_wiring.fill_deadline_ns(venue),
        lag_rule=lag,
    )
    deps = LabelRunDeps(
        data_root=data_root,
        exec_db=exec_db,
        now_ns=now_ns,
        venue=venue,
        registry=OFFLINE_PLUGINS,
        families=lambda: families,
        plan=planner,
        settlements=unit_wiring.StationCatalogSettlements(
            chosen.catalog_base, venue, chosen.open_catalog
        ),
        deliver=unit_wiring.make_deliver(chosen.make_sink(), chosen.alerts_root),
        deadline_ns=unit_wiring.row_deadline_ns(venue),
        lag_start_ns=lag,
        producer_code_sha=code_sha,
        subject_artefact_sha256=None,
    )
    return UnitWiring(
        deps=deps,
        lock=StudiesFlock(chosen.lock_path),
        unit_max_bytes=unit_wiring.unit_memory_max_bytes(
            chosen.proc_cgroup_text, chosen.cgroup_root
        ),
        aut6=missing_aut6_reading(),
        measured_peak_bytes=None,
        proof_window=None,
        slot_ns=args.slot_ns if args.slot_ns is not None else now_ns,
    )
