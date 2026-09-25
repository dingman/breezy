"""F-2 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md): a bounded, best-effort JSONL
sidecar for the hourly ``crh_diag_hourly_v1`` diagnostics rows
``ContinuousRungHoldStrategy`` emits from ``_maybe_roll_diagnostics``.

``DiagnosticsSummarySink`` mirrors ``OfferTape``'s own sidecar discipline
(``offer_tape.py:395-430``) byte-for-byte in behaviour: the in-memory side
(here, nothing -- this sink is disk-only, since the strategy itself keeps
the last-emitted baseline) is irrelevant, but every disk-facing property
is the same -- best-effort (a setup or append failure never raises into the
caller), byte-capped (``max_bytes``, one WARN when it is first reached,
further rows dropped from disk only), and resume-from-stat (a process
restart mid-day continues the cap from the file's REAL on-disk size rather
than re-zeroing it).

``delta`` is a pure ``Mapping[str, int] -> Mapping[str, int] -> dict[str,
int]`` helper for the ``diagnostics``/``refusals`` counter dicts: the
result carries every key seen in ``cur`` (a key that only ever appears in
``prev`` -- impossible for a monotonic counter dict, but handled anyway --
is simply absent, never negative)."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Final

__all__ = [
    "DEFAULT_DIAGNOSTICS_SUMMARY_MAX_BYTES",
    "DiagnosticsSummarySink",
    "delta",
]

logger = logging.getLogger(__name__)

#: F-2 Design (STALL_FOLLOWUPS_F1_F4_2026-09-24.md): "``DiagnosticsSummarySink
#: (path | None, max_bytes=4 MiB)``" -- one hourly-cadence row per process per
#: UTC hour is orders of magnitude smaller than the offer tape's per-tick
#: volume, so 4 MiB comfortably covers a full trading day even across a
#: multi-day restart before the F-3 retention timer rotates it.
DEFAULT_DIAGNOSTICS_SUMMARY_MAX_BYTES: Final[int] = 4 * 1024 * 1024


def delta(prev: Mapping[str, int], cur: Mapping[str, int]) -> dict[str, int]:
    """The per-key increase from ``prev`` to ``cur``, one key per name in
    ``cur``. Never negative (a decreasing counter would mean a coding bug
    upstream, not a valid delta) -- clamped to 0 defensively rather than
    raising, since this pure helper must never crash the hourly emission it
    feeds.
    """
    return {key: max(0, value - prev.get(key, 0)) for key, value in cur.items()}


class DiagnosticsSummarySink:
    """Bounded, best-effort JSONL sidecar. Disk-only: there is no in-memory
    buffer to fall back to (unlike ``OfferTape``) because the strategy
    itself already holds the only copy that matters -- the last-emitted
    baseline used to compute the NEXT delta. A sidecar failure here means
    "this hour's row never reached disk", never "the strategy lost its own
    counters".
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        max_bytes: int = DEFAULT_DIAGNOSTICS_SUMMARY_MAX_BYTES,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("diagnostics summary sink max_bytes must be >= 1")
        self._max_bytes = max_bytes
        self._errors = 0
        self._capped = 0
        self._cap_logged = False
        self._path: Path | None = None
        self._bytes_written = 0
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                self._errors += 1
                logger.exception(
                    "DiagnosticsSummarySink: failed to create sidecar directory for "
                    "%s; falling back to in-memory only (rows are dropped)",
                    path,
                )
            else:
                self._path = path
                try:
                    self._bytes_written = path.stat().st_size
                except OSError:
                    self._bytes_written = 0

    @property
    def errors(self) -> int:
        return self._errors

    @property
    def capped(self) -> int:
        """Count of rows refused by the byte cap -- mirrors ``OfferTape.
        sidecar_capped``."""
        return self._capped

    def append(self, row: Mapping[str, object]) -> None:
        """Best-effort append. Never raises: a missing ``path`` (no sidecar
        configured), a byte-cap hit, or an ``OSError`` on the actual write
        are all silently counted, never propagated -- this is called from
        ``ContinuousRungHoldStrategy._run_observability``'s own containment,
        but stays safe to call directly (e.g. from a test) too.
        """
        if self._path is None:
            return
        line = json.dumps(dict(row), sort_keys=True)
        encoded = line.encode("utf-8") + b"\n"
        prospective_bytes = self._bytes_written + len(encoded)
        if prospective_bytes > self._max_bytes:
            self._capped += 1
            if not self._cap_logged:
                self._cap_logged = True
                logger.warning(
                    "DiagnosticsSummarySink: sidecar %s reached its %d-byte cap; "
                    "further rows are dropped",
                    self._path,
                    self._max_bytes,
                )
            return
        try:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")
        except OSError:
            self._errors += 1
            logger.exception("DiagnosticsSummarySink: failed to append to %s", self._path)
            return
        self._bytes_written += len(encoded)
