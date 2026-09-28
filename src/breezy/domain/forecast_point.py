"""`ForecastPoint` -- one issuance of one model cycle's forecast for one window.

Pattern
-------
A hand-written `nautilus_trader.core.data.Data` subclass with explicit
``ts_event``/``ts_init`` properties, ``to_dict``/``from_dict``, a ``schema()``
classmethod, and **exactly one** ``register_arrow`` call at module scope --
the same in-tree pattern as :mod:`breezy.domain.station_observation`
(``station_observation.py:255-261``), for the same reason: ``@customdataclass``
routes ``from_arrow`` through ``from_dict``, which lets a vanished column
arrive as a dataclass default rather than raising. It also cannot express
``float | None`` at all -- the decorator supports exactly eight annotations
(``model/custom.py:245-254``) and rejects the union at class-definition time,
while ``value_f`` is nullable by design (see "Absences" below).

L-1 verdict (null hypothesis: Nautilus already provides this)
-------------------------------------------------------------
NATIVE AND SUFFICIENT for serialization. ``register_arrow``
(``serialization/arrow/serializer.py:89``) takes the class, an explicit
``pa.Schema``, an encoder and a decoder, and ``ArrowSerializer`` then round-trips
the type through the catalog with no Breezy machinery. Nothing here
reimplements it; this module only supplies the four arguments.

NATIVE BUT INSUFFICIENT for partitioning, and the gap is recorded here so the
later catalog seam is unambiguous. ``ParquetDataCatalog``'s
``identifier_function`` (``persistence/catalog/parquet.py:320-336``) keys on
``Instrument`` -> ``bar_type`` -> ``instrument_id`` -> **else flat**, so a
custom type without ``instrument_id`` writes flat to
``data/custom_forecast_point/`` and two stations in one catalog root cannot be
separated.

**Decision: per-station catalog roots, NOT an `instrument_id` field.** A
NOAA model output is not a traded instrument; minting a synthetic
``InstrumentId`` for one would bind the forecast archive to venue symbology
(which is per-rung, per-day and venue-specific) and would make a
``ForecastPoint`` look tradeable to any standard Nautilus consumer. One
``ParquetDataCatalog`` root per station is the native workaround and costs
nothing this seam needs. Climate day stays a **query filter** on
``valid_start_ns``/``valid_end_ns``, never a partition key. Do **not** invent a
second parquet writer.

NOT NATIVE at all: point-in-time (as-of) selection over reissued records.
Nautilus replays by ``ts_init`` and has no notion of a corrected bulletin
superseding an earlier one for the same forecast. :func:`select_as_of` and
:func:`latest_as_of` below are that rule, and they are pure functions over
records -- no new storage layer, no second writer.

Corrections are first-class
----------------------------
Upstream reissues and corrects bulletins. ``(station, model, model_version,
variable, cycle_runtime_ns, valid_start_ns, valid_end_ns)`` -- the
:class:`ForecastPointKey` -- identifies the FORECAST; ``issuance_seq``
identifies WHICH ISSUANCE of it, and the pair is the record's identity
(:attr:`ForecastPoint.record_key`). So:

* a correction is a DISTINCT record carrying its OWN, later vintage -- it can
  never overwrite or masquerade as the original;
* an idempotent re-ingest produces an identical ``record_key`` and is
  collapsed by :func:`latest_as_of`, so a calibration fit cannot
  double-weight the point;
* a later issuance stamped with a vintage at or before an earlier one's is
  refused outright, because that combination is precisely hindsight.

The selection rule, stated once: **at instant T, among the records sharing a
join key, take the one with the greatest ``available_at_ns <= T``** (ties
broken by the greater ``issuance_seq``). A correction is therefore invisible
to any join taken before its own vintage.

The vintage is point-in-time truth
-----------------------------------
``available_at_ns`` is the instant this issuance first became knowable to
Breezy: ``cycle_runtime_ns + measured_publication_lag_ns`` (plan section 3.2).
It is an explicit, required constructor input with no default, and the sum is
ENFORCED so the separately stored lag stays auditable -- a lag later found
wrong can be re-derived and corrected without a full re-ingest, and a lag that
contradicts its own vintage is refused rather than stored.

``measured_publication_lag_ns`` must reach a per-model floor
(`MINIMUM_PUBLICATION_LAG_NS`). A zero lag is not a conservative fallback: it
grants roughly an hour of look-ahead, positioned exactly across the
publication repricing window this family trades, which is the single most
profitable-looking and most fictional value the field can take.

The vintage is **never** derived from ``ts_init``, from a clock, or from
``ingested_at_ns``. The derivation runs one way only: measured vintage ->
``ts_init``. ``available_at_ns`` is also carried as its own Arrow column, so
the archive stays readable without trusting a Nautilus-defined field whose
meaning a future change may legitimately revisit; ``from_dict`` refuses a
fragment where the two disagree.

``ingested_at_ns`` is separate provenance: when Breezy actually saw the
bytes. It is what distinguishes "we knew this live" from "this was backfilled
under a modelled vintage", and it is never used in a decision.

``ts_event`` is ``cycle_runtime_ns`` -- the cycle's own issuance instant.
Neither timestamp is a constructor parameter under its Nautilus name, so
neither can be re-stamped.

Absences
--------
``value_f`` is NULL only for a genuine absence, and an absence must name its
cause (`FORECAST_ABSENCE_REASONS`): a sentinel in the bulletin, a cycle that
published nothing for the window, or a parser that could not read it. Those
are three different facts and must not collapse into one NULL -- a parser
defect silently recorded as a publication gap would corrupt every coverage
statistic built on this archive. Pairing the nullable value with a
non-null-when-absent reason also closes the residual read-side hole
``strict_arrow`` documents (a legitimate NULL in isolation).

Non-finite values (``nan``, ``inf``) are REFUSED, not mapped to ``None``. NaN
is the missing marker of every pandas/numpy parser that will feed the ingest
seam, and one NaN makes every downstream mean and sigma NaN -- but recoding it
as an absence would erase exactly the distinction above. The ingest seam must
declare what it found.

No transport
------------
This module is the pure domain type and performs no I/O of any kind: it names
no remote host, opens no connection, reads no file, reads no clock, and knows
nothing about which upstream source produced a point. Retrieval lives in its
own seam under :mod:`breezy.ingest`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from itertools import pairwise
from typing import Any, Final, NamedTuple

import pyarrow as pa
from nautilus_trader.core.data import Data
from nautilus_trader.serialization.arrow.serializer import register_arrow

from breezy.domain.strict_arrow import make_strict_decoder, make_strict_encoder
from breezy.domain.validation import require_int, require_optional_float, require_text

#: Revision of this record layout. Bumped whenever the Arrow schema changes.
FORECAST_POINT_SCHEMA_VERSION: Final[int] = 1

#: The models Breezy ingests, per plan section 3.5. A whitelist rather than
#: free text: a typo'd or unexpected model name would otherwise be archived
#: and then quietly split a station's calibration sample in two.
#:
#: WIDEN this tuple to admit a new model; never relax it to accept anything.
FORECAST_MODELS: Final[tuple[str, ...]] = ("NBM_NBS", "GFS_MOS")

#: Smallest publication lag accepted per model, in nanoseconds.
#:
#: These are DEFAULT-DETECTORS, not measurements. Their job is to catch a lag
#: that was never measured (0), was measured in the wrong unit, or was
#: negated -- not to validate a genuine measurement. Each is therefore set far
#: below the observed publication behaviour so a legitimately fast cycle is
#: never rejected: NBM text bulletins post roughly 55-80 minutes after cycle
#: time (floor 20 minutes) and GFS MOS bulletins roughly three hours after
#: (floor 60 minutes). A model admitted to `FORECAST_MODELS` without a floor
#: here would silently reinstate the zero-lag hazard, so the two sets are
#: required to match.
MINIMUM_PUBLICATION_LAG_NS: Final[dict[str, int]] = {
    "NBM_NBS": 20 * 60 * 1_000_000_000,
    "GFS_MOS": 60 * 60 * 1_000_000_000,
}

#: The "no value published" codes used by the upstream text products.
#: Compared exactly -- ``-98.9`` and ``998.9`` are genuine readings.
#:
#: ``variable`` deliberately has no equivalent whitelist: plan section 3.5 fixes
#: the model alphabet and says nothing about closing the variable alphabet,
#: and the ingest seam that learns a second variable is the one that should
#: decide its membership rule.
FORECAST_VALUE_SENTINELS: Final[tuple[float, ...]] = (-99.0, 999.0)

#: Why a record carries no value. Closed alphabet -- see "Absences" above.
FORECAST_ABSENCE_REASONS: Final[tuple[str, ...]] = (
    "sentinel",
    "not_published",
    "parse_failure",
)


class ForecastPointKey(NamedTuple):
    """The identity of a FORECAST, shared by every issuance of it.

    Reissues and corrections of the same forecast share this key and differ
    only in `ForecastPoint.issuance_seq` and vintage, which is what makes the
    as-of rule expressible at all.
    """

    station: str
    model: str
    model_version: str
    variable: str
    cycle_runtime_ns: int
    valid_start_ns: int
    valid_end_ns: int


def is_forecast_sentinel(value: Any) -> bool:
    """Return whether `value` is one of the missing-value sentinel codes."""
    coerced = require_optional_float(value, "value_f")

    if coerced is None or not math.isfinite(coerced):
        return False

    return coerced in FORECAST_VALUE_SENTINELS


def forecast_value_or_none(value: Any) -> float | None:
    """Return `value` as a finite `float`, or `None` for a missing-value sentinel.

    The single home of the sentinel mapping. ``None`` passes through unchanged
    (an upstream parser that already resolved the absence should not have to
    re-encode it as a sentinel to get the same answer).

    Raises
    ------
    TypeError
        If `value` is neither `None` nor a real number. A sentinel arriving as
        the string ``"-99"`` is a parser defect and is surfaced, not coerced.
    ValueError
        If `value` is not finite. See the module docstring: `nan` is a parser
        artefact, not a published absence, and must not be silently recoded as
        one.

    """
    coerced = require_optional_float(value, "value_f")

    if coerced is None:
        return None

    if not math.isfinite(coerced):
        raise ValueError(
            f"`value_f` must be finite, was {coerced!r}; a non-finite value is a "
            f"parser artefact, never a forecast, and is refused rather than "
            f"recoded as a published absence",
        )

    return None if coerced in FORECAST_VALUE_SENTINELS else coerced


class ForecastPoint(Data):
    """One issuance of one model cycle's forecast of one variable over one window.

    Parameters
    ----------
    station : str
        The ICAO station id the forecast is for (e.g. ``"KMIA"``). Normalised
        to upper case with surrounding whitespace stripped: this is a join
        key, and ``" kmia "`` must not become a second archive key that splits
        one station's calibration sample.
    model : str
        The producing model, one of `FORECAST_MODELS`. Whitespace-stripped but
        NOT case-folded -- the alphabet is closed, and admitting ``"nbm_nbs"``
        would be a relaxation rather than a normalisation.
    model_version : str
        The model revision (e.g. ``"4.2"``). Part of the join key: NBM 4.0 and
        4.2 are different skill regimes under one model name, and a
        calibration sample straddling the upgrade has nothing to split on
        without this.
    variable : str
        The forecast variable (e.g. ``"TXN"``).
    cycle_runtime_ns : int
        UNIX nanoseconds of the model cycle's issuance instant. Becomes
        ``ts_event``.
    valid_start_ns : int
        UNIX nanoseconds at which the forecast's validity window opens.
    valid_end_ns : int
        UNIX nanoseconds at which it closes. Must not precede
        `valid_start_ns`; equal bounds denote an instantaneous window.
    value_f : float or None
        The forecast value in degrees Fahrenheit, or ``None`` for an absence.
        A sentinel (`FORECAST_VALUE_SENTINELS`) is mapped to ``None`` here
        rather than stored; a non-finite value is refused.
    issuance_seq : int
        ``0`` for the original bulletin, incrementing for each reissue or
        correction of the SAME forecast. Never negative.
    measured_publication_lag_ns : int
        The measured delay between `cycle_runtime_ns` and publication. Stored
        in its own column so the vintage stays auditable, and required to
        reach this model's `MINIMUM_PUBLICATION_LAG_NS` floor.
    available_at_ns : int
        **The vintage.** ``cycle_runtime_ns + measured_publication_lag_ns``,
        required and explicit; the equality is enforced. Never defaulted,
        never derived from a clock, from ``ts_init`` or from
        `ingested_at_ns` -- see the module docstring.
    ingested_at_ns : int
        When Breezy actually saw the bytes. Provenance only, never used in a
        decision; it is what separates "knew it live" from "backfilled".
    absence_reason : str or None
        Required exactly when `value_f` resolves to ``None``, and forbidden
        otherwise. One of `FORECAST_ABSENCE_REASONS`. Defaults to
        ``"sentinel"`` when a sentinel was supplied, because in that case the
        cause was observed rather than assumed.
    schema_version : int
        Revision of this record layout.

    """

    def __init__(
        self,
        *,
        station: str,
        model: str,
        model_version: str,
        variable: str,
        cycle_runtime_ns: int,
        valid_start_ns: int,
        valid_end_ns: int,
        value_f: float | None,
        issuance_seq: int,
        measured_publication_lag_ns: int,
        available_at_ns: int,
        ingested_at_ns: int,
        absence_reason: str | None = None,
        schema_version: int = FORECAST_POINT_SCHEMA_VERSION,
    ) -> None:
        self.station = require_text(station, "station").strip().upper()
        self.model = require_text(model, "model").strip()
        self.model_version = require_text(model_version, "model_version").strip()
        self.variable = require_text(variable, "variable").strip().upper()
        self.cycle_runtime_ns = require_int(cycle_runtime_ns, "cycle_runtime_ns")
        self.valid_start_ns = require_int(valid_start_ns, "valid_start_ns")
        self.valid_end_ns = require_int(valid_end_ns, "valid_end_ns")
        self.value_f = forecast_value_or_none(value_f)
        self.issuance_seq = require_int(issuance_seq, "issuance_seq")
        self.measured_publication_lag_ns = require_int(
            measured_publication_lag_ns,
            "measured_publication_lag_ns",
        )
        self.available_at_ns = require_int(available_at_ns, "available_at_ns")
        self.ingested_at_ns = require_int(ingested_at_ns, "ingested_at_ns")
        self.absence_reason = _resolved_absence_reason(
            absence_reason,
            value_f=value_f,
            parsed=self.value_f,
        )
        self.schema_version = require_int(schema_version, "schema_version")

        if self.model not in FORECAST_MODELS:
            raise ValueError(
                f"`model` must be one of {FORECAST_MODELS}, was {self.model!r}",
            )

        floor = MINIMUM_PUBLICATION_LAG_NS[self.model]
        if self.measured_publication_lag_ns < floor:
            raise ValueError(
                f"`measured_publication_lag_ns` ({self.measured_publication_lag_ns}) "
                f"is below the {self.model} floor of {floor} ns; a zero or "
                f"implausibly small lag grants look-ahead across the publication "
                f"repricing window and is refused rather than stored",
            )

        if self.available_at_ns != self.cycle_runtime_ns + self.measured_publication_lag_ns:
            raise ValueError(
                f"`available_at_ns` ({self.available_at_ns}) must equal "
                f"`cycle_runtime_ns` + `measured_publication_lag_ns` "
                f"({self.cycle_runtime_ns} + {self.measured_publication_lag_ns} = "
                f"{self.cycle_runtime_ns + self.measured_publication_lag_ns}); a stored "
                f"lag that contradicts its own vintage cannot be audited",
            )

        if self.issuance_seq < 0:
            raise ValueError(
                f"`issuance_seq` must not be negative, was {self.issuance_seq}",
            )

        if self.valid_end_ns < self.valid_start_ns:
            raise ValueError(
                f"`valid_end_ns` ({self.valid_end_ns}) must not precede "
                f"`valid_start_ns` ({self.valid_start_ns})",
            )

        if self.ingested_at_ns < self.cycle_runtime_ns:
            raise ValueError(
                f"`ingested_at_ns` ({self.ingested_at_ns}) must not precede "
                f"`cycle_runtime_ns` ({self.cycle_runtime_ns}); a cycle cannot be "
                f"ingested before it ran",
            )

        self._ts_event = self.cycle_runtime_ns
        self._ts_init = self.available_at_ns

    @property
    def ts_event(self) -> int:
        """UNIX nanoseconds of the model cycle's issuance (`cycle_runtime_ns`)."""
        return self._ts_event

    @property
    def ts_init(self) -> int:
        """UNIX nanoseconds at which Breezy could first know this (`available_at_ns`)."""
        return self._ts_init

    @property
    def join_key(self) -> ForecastPointKey:
        """The forecast this record is an issuance of."""
        return ForecastPointKey(
            station=self.station,
            model=self.model,
            model_version=self.model_version,
            variable=self.variable,
            cycle_runtime_ns=self.cycle_runtime_ns,
            valid_start_ns=self.valid_start_ns,
            valid_end_ns=self.valid_end_ns,
        )

    @property
    def record_key(self) -> tuple[Any, ...]:
        """This record's identity: the forecast, plus which issuance of it."""
        return (*self.join_key, self.issuance_seq)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"station={self.station!r}, "
            f"model={self.model!r}/{self.model_version}, "
            f"variable={self.variable!r}, "
            f"value_f={self.value_f}, "
            f"absence_reason={self.absence_reason!r}, "
            f"issuance_seq={self.issuance_seq}, "
            f"valid_start_ns={self.valid_start_ns}, "
            f"valid_end_ns={self.valid_end_ns}, "
            f"cycle_runtime_ns={self.cycle_runtime_ns}, "
            f"available_at_ns={self.available_at_ns})"
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the record as Arrow-native values, keyed in `schema()` order."""
        return {
            "station": self.station,
            "model": self.model,
            "model_version": self.model_version,
            "variable": self.variable,
            "cycle_runtime_ns": self.cycle_runtime_ns,
            "valid_start_ns": self.valid_start_ns,
            "valid_end_ns": self.valid_end_ns,
            "value_f": self.value_f,
            "absence_reason": self.absence_reason,
            "issuance_seq": self.issuance_seq,
            "measured_publication_lag_ns": self.measured_publication_lag_ns,
            "available_at_ns": self.available_at_ns,
            "ingested_at_ns": self.ingested_at_ns,
            "schema_version": self.schema_version,
            "ts_event": self._ts_event,
            "ts_init": self._ts_init,
        }

    @classmethod
    def from_dict(cls, values: dict[str, Any]) -> ForecastPoint:
        """Rebuild a record from `to_dict` output.

        Every key is read by direct subscript: a missing column raises
        `KeyError` here rather than silently adopting a default.

        The vintage and the cycle instant are read from their OWN columns,
        never from ``ts_init``/``ts_event``. Those are then checked to agree;
        a fragment where they diverge was written by something that did not
        honour this module's one-way derivation and is refused rather than
        resolved in either direction.
        """
        cycle_runtime_ns = values["cycle_runtime_ns"]
        vintage = values["available_at_ns"]
        init_instant = values["ts_init"]
        event_instant = values["ts_event"]

        if vintage != init_instant:
            raise ValueError(
                f"`available_at_ns` ({vintage}) disagrees with `ts_init` "
                f"({init_instant}); the vintage must equal the record's init instant",
            )

        if cycle_runtime_ns != event_instant:
            raise ValueError(
                f"`cycle_runtime_ns` ({cycle_runtime_ns}) disagrees with `ts_event` "
                f"({event_instant})",
            )

        return cls(
            station=values["station"],
            model=values["model"],
            model_version=values["model_version"],
            variable=values["variable"],
            cycle_runtime_ns=cycle_runtime_ns,
            valid_start_ns=values["valid_start_ns"],
            valid_end_ns=values["valid_end_ns"],
            value_f=values["value_f"],
            issuance_seq=values["issuance_seq"],
            measured_publication_lag_ns=values["measured_publication_lag_ns"],
            available_at_ns=vintage,
            ingested_at_ns=values["ingested_at_ns"],
            absence_reason=values["absence_reason"],
            schema_version=values["schema_version"],
        )

    @classmethod
    def schema(cls) -> pa.Schema:
        """Return the explicit Arrow schema for this record type.

        ``value_f`` and ``absence_reason`` are the only nullable columns, and
        they are nullable in opposite cases: exactly one of the pair is set on
        every record, so a coerced NULL contradicts its partner.
        """
        return pa.schema(
            [
                pa.field("station", pa.string(), nullable=False),
                pa.field("model", pa.string(), nullable=False),
                pa.field("model_version", pa.string(), nullable=False),
                pa.field("variable", pa.string(), nullable=False),
                pa.field("cycle_runtime_ns", pa.int64(), nullable=False),
                pa.field("valid_start_ns", pa.int64(), nullable=False),
                pa.field("valid_end_ns", pa.int64(), nullable=False),
                pa.field("value_f", pa.float64(), nullable=True),
                pa.field("absence_reason", pa.string(), nullable=True),
                pa.field("issuance_seq", pa.int64(), nullable=False),
                pa.field("measured_publication_lag_ns", pa.int64(), nullable=False),
                pa.field("available_at_ns", pa.int64(), nullable=False),
                pa.field("ingested_at_ns", pa.int64(), nullable=False),
                pa.field("schema_version", pa.int64(), nullable=False),
                pa.field("ts_event", pa.int64(), nullable=False),
                pa.field("ts_init", pa.int64(), nullable=False),
            ],
        )


def _resolved_absence_reason(
    absence_reason: str | None,
    *,
    value_f: Any,
    parsed: float | None,
) -> str | None:
    """Return the validated absence reason for a record, or `None`.

    Defaults to ``"sentinel"`` when the caller supplied a sentinel: in that
    case the cause is OBSERVED in the bulletin, not assumed. Every other
    absence must be declared, because "published nothing" and "the parser
    could not read it" are different facts that must not share a NULL.
    """
    if parsed is not None:
        if absence_reason is not None:
            raise ValueError(
                f"`absence_reason` must be `None` when `value_f` is present, "
                f"was {absence_reason!r}",
            )
        return None

    if absence_reason is None:
        if is_forecast_sentinel(value_f):
            return "sentinel"
        raise ValueError(
            "`absence_reason` is required when `value_f` is absent; a NULL value "
            f"with no declared cause is indistinguishable from schema drift "
            f"(expected one of {FORECAST_ABSENCE_REASONS})",
        )

    reason = require_text(absence_reason, "absence_reason").strip()
    if reason not in FORECAST_ABSENCE_REASONS:
        raise ValueError(
            f"`absence_reason` must be one of {FORECAST_ABSENCE_REASONS}, was {reason!r}",
        )
    return reason


def _validated_issuances(points: Iterable[ForecastPoint]) -> list[ForecastPoint]:
    """Return the distinct issuances of ONE forecast, refusing incoherent input.

    Three refusals, each a silent corruption if allowed through:

    * a mixed join key -- selecting across two different forecasts would
      return a confidently wrong answer;
    * two records sharing a ``record_key`` but not their content -- a
      correction written under the original's sequence number, which would
      make the archive's answer depend on iteration order;
    * a later issuance whose vintage does not strictly postdate every earlier
      one -- a corrected value claiming the original's vintage, which is
      exactly hindsight injection.

    An exact duplicate (same ``record_key``, same content) is an idempotent
    re-ingest and collapses to one record, so a calibration fit cannot
    double-weight the point.
    """
    unique: dict[tuple[Any, ...], ForecastPoint] = {}

    for point in points:
        key = point.record_key
        existing = unique.get(key)
        if existing is None:
            unique[key] = point
            continue
        if existing.to_dict() != point.to_dict():
            raise ValueError(
                f"two records share `record_key` {key!r} but differ in content; a "
                f"correction must carry its own `issuance_seq`, never the "
                f"original's",
            )

    issuances = list(unique.values())
    if not issuances:
        return issuances

    join_keys = {point.join_key for point in issuances}
    if len(join_keys) != 1:
        raise ValueError(
            f"every record must share one join key, found {len(join_keys)}: {sorted(join_keys)!r}",
        )

    ordered = sorted(issuances, key=lambda point: point.issuance_seq)
    for earlier, later in pairwise(ordered):
        if later.available_at_ns <= earlier.available_at_ns:
            raise ValueError(
                f"`issuance_seq` {later.issuance_seq} has vintage "
                f"{later.available_at_ns}, which does not postdate issuance "
                f"{earlier.issuance_seq}'s vintage {earlier.available_at_ns}; a "
                f"reissue may not claim an earlier issuance's vintage",
            )

    return issuances


def select_as_of(
    points: Iterable[ForecastPoint],
    *,
    as_of_ns: int,
) -> ForecastPoint | None:
    """Return the issuance knowable at `as_of_ns`, or `None` if none was.

    THE point-in-time rule: among records sharing a join key, the one with the
    greatest ``available_at_ns <= as_of_ns`` (ties broken by the greater
    ``issuance_seq``). The bound is inclusive -- a bulletin published at ``T``
    was knowable at ``T``.

    A correction is therefore invisible to any join taken before its own
    vintage, which is the property every forecast-edge measurement rests on.
    All records must describe ONE forecast; use :func:`latest_as_of` for a
    mixed collection.
    """
    require_int(as_of_ns, "as_of_ns")
    knowable = [
        point for point in _validated_issuances(points) if point.available_at_ns <= as_of_ns
    ]

    if not knowable:
        return None

    return max(knowable, key=lambda point: (point.available_at_ns, point.issuance_seq))


def latest_as_of(
    points: Iterable[ForecastPoint],
    *,
    as_of_ns: int,
) -> dict[ForecastPointKey, ForecastPoint]:
    """Apply :func:`select_as_of` per join key over a mixed collection.

    A join key with nothing published by `as_of_ns` is OMITTED rather than
    mapped to ``None``: a caller iterating the result must not be able to read
    an absence as a value.
    """
    require_int(as_of_ns, "as_of_ns")

    grouped: dict[ForecastPointKey, list[ForecastPoint]] = {}
    for point in points:
        grouped.setdefault(point.join_key, []).append(point)

    selected = {key: select_as_of(group, as_of_ns=as_of_ns) for key, group in grouped.items()}
    return {key: point for key, point in selected.items() if point is not None}


# Registered exactly once, at module scope.
register_arrow(
    data_cls=ForecastPoint,
    schema=ForecastPoint.schema(),
    encoder=make_strict_encoder(ForecastPoint.schema()),
    decoder=make_strict_decoder(ForecastPoint, ForecastPoint.schema()),
)
