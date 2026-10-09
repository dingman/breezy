"""The ``aut6.health`` producer's C4 verdict writer (plan r15 sections 3.4.1 and 3.11; P6-13).

The health pass hands every meta-detector result and the fold-unreadable #26 FAIL to a
``host_verdict`` sink. This sink turns each into a ``HEALTH`` ``verdict/v1`` file:

* identity: ``Verdict.verdict_id`` hashes the body without ``produced_at_ns``; ``valid_until_ns``
  is slot-anchored (the timer slot start plus ``HEALTH_VALIDITY_S``), so a recompute in the same
  slot dedupes to ``EXISTS_EQUAL`` and a different body under one id is refused;
* refresh: written when the outcome changed or the last write for ``(subject, detector)`` is older
  than ``REFRESH_S``; the last write is a replaced ``seen/verdict_<subject>_<detector>.json``;
* subject: the fold's sole sender, else ``_host``; host-wide detectors have no other subject;
* class: ``declare_without_ruling`` (``no_policy_ruling``), ``metrics.cause_class`` from the
  catalogue, and metrics reduced to the verdict charset (no paths, ids or spaces);
* code identity: ``producer_code_sha`` is the pinned closure hash; an unpinned producer never
  builds this writer (``autonomy_health_cli`` refuses to run).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Final

from breezy.persistence.autonomy.canonical import CanonicalTypeError, decimal_str
from breezy.persistence.autonomy.detector_catalog import declare_without_ruling, verdict_row
from breezy.persistence.autonomy.paths import AutonomyPaths
from breezy.persistence.autonomy.verdict import (
    ActionClass,
    Assumption,
    MetricValue,
    Verdict,
    VerdictKind,
    VerdictOutcome,
    write_verdict,
)
from breezy.runtime.unit_health_store import NS, HealthStore, safe_key
from breezy.runtime.unit_health_types import HostVerdict

__all__ = [
    "HEALTH_PRODUCER_ID",
    "HEALTH_VALIDITY_S",
    "REFRESH_S",
    "HealthVerdictWriter",
    "slot_start_ns",
]

HEALTH_PRODUCER_ID: Final = "aut6.health"
#: ``INTRADAY_VALIDITY_S`` = ``ATTEST_VERDICT_VALIDITY_H`` (8 h); the producer refuses above 26 h.
HEALTH_VALIDITY_S: Final = 28_800
#: ``INTRADAY_REFRESH_S`` = ``INTRADAY_ATTEST_VERDICT_PERIOD_MIN`` (60 min).
REFRESH_S: Final = 3_600
_SLOT_S: Final = 600
_SLOT_OFFSET_S: Final = 60  # ``OnCalendar=*:01/10``
_MAX_TEXT: Final = 128
_NAME_UNSAFE: Final = re.compile(r"[^a-z0-9_]")
_TEXT_UNSAFE: Final = re.compile(r"[^A-Za-z0-9_:.()=,-]")
_OUTCOMES: Final = {o.value: o for o in VerdictOutcome}
_ACTIONS: Final = {a.value: a for a in ActionClass}


def slot_start_ns(ts_ns: int) -> int:
    """The start of the 10-minute health slot (``:01``, ``:11``, ...) that contains ``ts_ns``."""
    seconds = ts_ns // NS - _SLOT_OFFSET_S
    return (seconds // _SLOT_S * _SLOT_S + _SLOT_OFFSET_S) * NS


def _metric_name(raw: str) -> str:
    name = _NAME_UNSAFE.sub("_", raw.lower())[:64]
    return name if name[:1].isalpha() else f"m_{name}"[:64]


def _metric_value(raw: str) -> MetricValue:
    try:
        number = Decimal(raw)
        if decimal_str(number) == raw:
            return number  # text that is a canonical decimal is a decimal on the wire
    except (InvalidOperation, CanonicalTypeError):
        pass
    text = _TEXT_UNSAFE.sub("_", raw)[:_MAX_TEXT]
    return text or "none"


def verdict_metrics(
    metrics: Mapping[str, str], cause_class: str
) -> tuple[tuple[str, MetricValue], ...]:
    """Sorted, unique, charset-clean metrics plus ``cause_class`` (every verdict carries it)."""
    merged: dict[str, MetricValue] = {"cause_class": cause_class}
    for raw_name, raw_value in sorted(metrics.items()):
        name = _metric_name(str(raw_name))
        if name not in merged:
            merged[name] = _metric_value(str(raw_value))
    return tuple(sorted(merged.items()))


class HealthVerdictWriter:
    """The ``host_verdict`` sink: ``writer(HostVerdict)`` writes (or skips) one HEALTH verdict."""

    def __init__(
        self,
        paths: AutonomyPaths,
        store: HealthStore,
        *,
        code_sha: str,
        subject: Callable[[], str],
    ) -> None:
        self._paths = paths
        self._store = store
        self._code_sha = code_sha
        self._subject = subject

    def __call__(self, result: HostVerdict) -> None:
        row = verdict_row(result.detector)
        outcome = _OUTCOMES[result.outcome]
        subject = self._subject()
        key = safe_key(f"verdict_{subject}_{result.detector}")
        last = self._store.read_seen(key) or {}
        if not self._due(last, outcome, result.ts_ns):
            return
        declared = declare_without_ruling(result.detector)
        slot = slot_start_ns(result.ts_ns)
        write_verdict(
            self._paths,
            Verdict(
                kind=VerdictKind.HEALTH,
                subject_family_id=subject,
                outcome=outcome,
                detector=result.detector,
                declared_action_class=_ACTIONS[declared.declared_action_class],
                produced_at_ns=result.ts_ns,
                valid_until_ns=slot + HEALTH_VALIDITY_S * NS,
                producer_code_sha=self._code_sha,
                metrics=verdict_metrics(result.metrics, row.cause),
                assumptions=(Assumption.NO_POLICY_RULING,),
            ),
        )
        self._store.write_seen(
            key, {"outcome": outcome.value, "ts_ns": result.ts_ns, "detector": result.detector}
        )

    @staticmethod
    def _due(last: Mapping[str, object], outcome: VerdictOutcome, ts_ns: int) -> bool:
        stamp = last.get("ts_ns")
        if type(stamp) is not int or last.get("outcome") != outcome.value:
            return True
        return ts_ns - stamp >= REFRESH_S * NS
