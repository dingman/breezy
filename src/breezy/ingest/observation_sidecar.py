"""Bounded best-effort JSONL sidecar for raw NWS observation readings.

2026-09-16 GAP fix (first live-day observability postmortem): a MIA
``observation_ambiguous`` refusal (a whole-degree-C reading, no METAR
``T`` group -> the running max collapsed to an interval straddling two
rungs; see ``nws_observations.py::_decode_reading`` and
``running_extreme.py``) could not be diagnosed to its cause after the
fact -- did the API drop ``rawMessage``, or did the station genuinely
report no tenths? No raw payload was ever persisted to check.

Mirrors ``breezy.strategy.current_rung_hold.offer_tape.OfferTape``'s
sidecar pattern in spirit -- best-effort ``mkdir``, best-effort append, a
per-climate-day byte cap that stops disk writes without ever raising --
but is purpose-built for this module's own row shape and lives in
``ingest`` deliberately: ``strategy`` sits ABOVE ``ingest`` in the
``lint-imports`` layer contract, so this module never imports
``OfferTape`` and ``OfferTape`` never imports this.

One row per successfully DECODED reading
(``nws_observations._decode_reading`` returning a reading, never a drop
reason) -- see ``nws_observations.nws_observation_rows_to_station_
observations``, this module's one caller. ``append`` never raises out of
that caller's decode loop: every disk operation here is caught and
counted, matching ``OfferTape.append``'s own contract.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    "DEFAULT_OBSERVATION_SIDECAR_MAX_BYTES",
    "ObservationSidecar",
    "ObservationSidecarRow",
]

logger = logging.getLogger(__name__)

#: PROVISIONAL (2026-09-16 GAP fix) -- matches ``OfferTape``'s own
#: ``DEFAULT_OFFER_TAPE_SIDECAR_MAX_BYTES``. Revisit once a live day's real
#: observation-sidecar volume is measured; one row per successfully decoded
#: reading per station per ~300s poll is far sparser than the offer tape's
#: per-eligible-snapshot rate, so 64 MiB is expected to be a very high
#: ceiling here, not a tight one.
DEFAULT_OBSERVATION_SIDECAR_MAX_BYTES: Final[int] = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ObservationSidecarRow:
    """One successfully decoded raw NWS observation reading.

    ``observed_at``, ``temp_c_raw`` and ``raw_message`` are carried
    VERBATIM as received off the wire (never rounded, never
    re-interpreted); ``is_metar``/``precision_c_tenths``/``temp_c_tenths``
    are the caller's own already-decoded values (never re-derived here, so
    this row can never itself become a second decode path);
    ``source_url_path`` and ``fetched_at_ns`` are transport provenance.
    """

    station: str
    #: Raw ``properties.timestamp`` string, exactly as received.
    observed_at: str
    #: Raw ``properties.temperature.value``, exactly as received (may be
    #: ``None``, an ``int``, or a ``float``).
    temp_c_raw: float | int | None
    #: Raw ``properties.rawMessage``, exactly as received. Never ``None``
    #: on this row -- a decoded reading with no METAR text carries ``""``.
    raw_message: str
    is_metar: bool
    precision_c_tenths: int
    temp_c_tenths: int
    #: The fetch URL's path ONLY -- no query string, no credentials. The
    #: NWS observations endpoint carries neither in its query today; this
    #: is a structural guarantee, not a fact about the one endpoint in use.
    source_url_path: str
    fetched_at_ns: int

    def to_dict(self) -> dict[str, object]:
        """Field-by-field serialization -- never ``dataclasses.asdict``.

        Matches ``OfferTapeRecord.to_dict``'s own reasoning (that module's
        docstring): explicit, named fields are reviewable at a glance for
        anything credential-shaped, even though this record carries no
        credential-bearing field today.
        """
        return {
            "station": self.station,
            "observed_at": self.observed_at,
            "temp_c_raw": self.temp_c_raw,
            "raw_message": self.raw_message,
            "is_metar": self.is_metar,
            "precision_c_tenths": self.precision_c_tenths,
            "temp_c_tenths": self.temp_c_tenths,
            "source_url_path": self.source_url_path,
            "fetched_at_ns": self.fetched_at_ns,
        }


class ObservationSidecar:
    """Bounded, best-effort JSONL append -- see the module docstring.

    ``path=None`` (the default) disables the sidecar entirely: ``append``
    becomes a no-op. Construction never raises: an unwritable/missing
    parent directory is caught and counted, exactly like ``OfferTape``'s
    own H1 review-finding fallback.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        max_bytes: int = DEFAULT_OBSERVATION_SIDECAR_MAX_BYTES,
    ) -> None:
        if max_bytes < 1:
            raise ValueError("observation sidecar max_bytes must be >= 1")
        self._max_bytes = max_bytes
        self._errors = 0
        self._capped = 0
        self._cap_logged = False
        self._path: Path | None = None
        #: Bytes already on disk at THIS path -- a process restart mid-day
        #: resumes the cap from the real on-disk size (mirrors
        #: ``OfferTape``'s own 2026-09-16 fix).
        self._bytes_written = 0
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                self._errors += 1
                logger.exception(
                    "ObservationSidecar: failed to create sidecar directory for %s; "
                    "falling back to disabled",
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
        """Count of sidecar setup/append disk failures."""
        return self._errors

    @property
    def capped(self) -> int:
        """Count of rows refused by the byte cap (never a disk error)."""
        return self._capped

    def append(self, row: ObservationSidecarRow) -> None:
        """Best-effort JSONL append. Never raises."""
        if self._path is None:
            return
        line = json.dumps(row.to_dict(), sort_keys=True)
        encoded = line.encode("utf-8") + b"\n"
        if self._bytes_written + len(encoded) > self._max_bytes:
            self._capped += 1
            if not self._cap_logged:
                self._cap_logged = True
                logger.warning(
                    "ObservationSidecar: sidecar %s reached its %d-byte cap; further "
                    "rows are dropped",
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
            logger.exception("ObservationSidecar: failed to append to %s", self._path)
            return
        self._bytes_written += len(encoded)
