"""Unit tests for `ForecastPoint` -- WP-12 Seam A.

Mirrors `tests/unit/test_domain_station_observation.py`: the hand-written
`Data` subclass pattern, its timestamp semantics, the strict `from_dict`
decode path, and the single module-scope ``register_arrow`` call.

The load-bearing sections are the vintage guards. Every forecast-edge number
this project will ever produce is a claim about what Breezy COULD have known
at decision time, and that claim is only as good as ``available_at_ns``. Three
distinct ways to destroy it are pinned here:

* deriving the vintage from ``ts_init`` or a clock (section 3),
* a zero or implausibly small publication lag, which grants look-ahead across
  exactly the publication repricing window (section 4),
* a CORRECTION reissued under the original's vintage, or an as-of join that
  can see a record published after the as-of instant (section 7).

Each is proved non-vacuous by a mutation in the task record.
"""

from __future__ import annotations

import ast
import inspect
import math
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from breezy.domain.forecast_point import (
    FORECAST_ABSENCE_REASONS,
    FORECAST_MODELS,
    FORECAST_POINT_SCHEMA_VERSION,
    FORECAST_VALUE_SENTINELS,
    MINIMUM_PUBLICATION_LAG_NS,
    ForecastPoint,
    ForecastPointKey,
    forecast_value_or_none,
    is_forecast_sentinel,
    latest_as_of,
    select_as_of,
)
from breezy.domain.strict_arrow import SchemaDriftError

_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _ROOT / "src/breezy/domain/forecast_point.py"

#: 2026-09-18T12:00:00Z -- an NBM 12Z cycle issuance instant.
_CYCLE_RUNTIME_NS = 1_789_041_600_000_000_000
#: The measured publication lag for that cycle (~1h05m), per plan section 3.2.
_PUBLICATION_LAG_NS = 3_900_000_000_000
_AVAILABLE_AT_NS = _CYCLE_RUNTIME_NS + _PUBLICATION_LAG_NS
#: The TXN validity window the cycle forecasts (a 00Z period end).
_VALID_START_NS = _CYCLE_RUNTIME_NS + 12 * 3_600_000_000_000
_VALID_END_NS = _VALID_START_NS + 6 * 3_600_000_000_000
#: Live ingest: seen shortly after publication.
_INGESTED_AT_NS = _AVAILABLE_AT_NS + 30_000_000_000


def make_point(**overrides: Any) -> ForecastPoint:
    kwargs: dict[str, Any] = {
        "station": "KMIA",
        "model": "NBM_NBS",
        "model_version": "4.2",
        "variable": "TXN",
        "cycle_runtime_ns": _CYCLE_RUNTIME_NS,
        "valid_start_ns": _VALID_START_NS,
        "valid_end_ns": _VALID_END_NS,
        "value_f": 88.0,
        "issuance_seq": 0,
        "measured_publication_lag_ns": _PUBLICATION_LAG_NS,
        "available_at_ns": _AVAILABLE_AT_NS,
        "ingested_at_ns": _INGESTED_AT_NS,
    }
    kwargs.update(overrides)
    if "available_at_ns" not in overrides and (
        "cycle_runtime_ns" in overrides or "measured_publication_lag_ns" in overrides
    ):
        kwargs["available_at_ns"] = (
            kwargs["cycle_runtime_ns"] + kwargs["measured_publication_lag_ns"]
        )
    return ForecastPoint(**kwargs)


# ---------------------------------------------------------------------------
# 1. Arrow round-trip through the registered serializer
# ---------------------------------------------------------------------------


def test_a_point_survives_the_registered_arrow_round_trip() -> None:
    """`register_arrow` serialize -> deserialize preserves every field."""
    from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

    original = make_point()

    batch = ArrowSerializer.serialize(original, ForecastPoint)
    (restored,) = ArrowSerializer.deserialize(ForecastPoint, pa.Table.from_batches([batch]))

    assert restored.to_dict() == original.to_dict()
    assert restored.station == "KMIA"
    assert restored.model == "NBM_NBS"
    assert restored.model_version == "4.2"
    assert restored.variable == "TXN"
    assert restored.cycle_runtime_ns == _CYCLE_RUNTIME_NS
    assert restored.valid_start_ns == _VALID_START_NS
    assert restored.valid_end_ns == _VALID_END_NS
    assert restored.value_f == 88.0
    assert restored.absence_reason is None
    assert restored.issuance_seq == 0
    assert restored.measured_publication_lag_ns == _PUBLICATION_LAG_NS
    assert restored.available_at_ns == _AVAILABLE_AT_NS
    assert restored.ingested_at_ns == _INGESTED_AT_NS
    assert restored.ts_event == original.ts_event
    assert restored.ts_init == original.ts_init


def test_a_missing_value_survives_the_arrow_round_trip_as_none() -> None:
    """`value_f=None` is a legitimate value, not an encoding failure.

    An absence means "this cycle published nothing for this window". That is
    information; it must reach the catalog as NULL, paired with the reason,
    rather than as a number a later fit would average in.
    """
    from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

    original = make_point(value_f=None, absence_reason="not_published")
    assert original.value_f is None

    batch = ArrowSerializer.serialize(original, ForecastPoint)
    (restored,) = ArrowSerializer.deserialize(ForecastPoint, pa.Table.from_batches([batch]))

    assert restored.value_f is None
    assert restored.absence_reason == "not_published"
    assert restored.to_dict() == original.to_dict()


def test_exactly_the_two_absence_columns_are_nullable() -> None:
    """`value_f` is paired with `absence_reason`, closing the strict-Arrow hole.

    ``strict_arrow`` documents one residual read-side hole: a genuinely
    nullable column whose NULL is legitimate in isolation. Pairing the value
    with a non-null-when-absent reason makes a coerced NULL contradict its
    partner, so the constructor catches what the decoder cannot.
    """
    schema = ForecastPoint.schema()
    nullable = {name for name in schema.names if schema.field(name).nullable}

    assert nullable == {"value_f", "absence_reason"}


def test_a_dropped_column_raises_schema_drift_rather_than_defaulting() -> None:
    from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

    batch = ArrowSerializer.serialize(make_point(), ForecastPoint)
    dropped = pa.Table.from_batches([batch]).drop_columns(["available_at_ns"])

    with pytest.raises(SchemaDriftError):
        ArrowSerializer.deserialize(ForecastPoint, dropped)


# ---------------------------------------------------------------------------
# 2. Value parsing: sentinels, non-finite, and the absence reason
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sentinel", [-99, -99.0, 999, 999.0])
def test_the_sentinels_parse_to_none(sentinel: float) -> None:
    assert forecast_value_or_none(sentinel) is None
    assert is_forecast_sentinel(sentinel) is True


@pytest.mark.parametrize("value", [88.0, 88, 0.0, -98.9, 998.9, 99.0, -999.0])
def test_a_genuine_value_is_preserved_as_a_float(value: float) -> None:
    parsed = forecast_value_or_none(value)
    assert parsed == float(value)
    assert isinstance(parsed, float)
    assert is_forecast_sentinel(value) is False


def test_none_passes_through_the_helper() -> None:
    assert forecast_value_or_none(None) is None
    assert is_forecast_sentinel(None) is False


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf")],
)
def test_a_non_finite_value_is_refused_by_the_helper(value: float) -> None:
    """NaN is pandas/numpy's missing marker and must not masquerade as a reading.

    One NaN turns every downstream mean and sigma into NaN; one `inf` does
    worse. Refused rather than mapped to `None`, because a NaN arriving from a
    parser is a PARSER DEFECT, and silently recoding it as a published absence
    would erase the distinction `absence_reason` exists to keep.
    """
    with pytest.raises(ValueError, match="finite"):
        forecast_value_or_none(value)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_value_never_reaches_a_record(value: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        make_point(value_f=value)


@pytest.mark.parametrize("sentinel", [-99, -99.0, 999, 999.0])
def test_a_sentinel_passed_to_the_constructor_becomes_none(sentinel: float) -> None:
    """The record never stores a sentinel as if it were a temperature."""
    point = make_point(value_f=sentinel)

    assert point.value_f is None
    assert point.to_dict()["value_f"] is None
    assert point.absence_reason == "sentinel"


def test_a_genuine_value_reaches_the_record_unchanged() -> None:
    assert make_point(value_f=88.0).value_f == 88.0
    assert make_point(value_f=88).value_f == 88.0


def test_a_non_numeric_value_is_refused() -> None:
    with pytest.raises(TypeError):
        make_point(value_f="88")


def test_an_absence_must_name_its_reason() -> None:
    """A NULL value with no reason is indistinguishable from drift. Refused."""
    with pytest.raises(ValueError, match="absence_reason"):
        make_point(value_f=None)


def test_a_present_value_may_not_carry_an_absence_reason() -> None:
    with pytest.raises(ValueError, match="absence_reason"):
        make_point(value_f=88.0, absence_reason="not_published")


@pytest.mark.parametrize("reason", sorted(FORECAST_ABSENCE_REASONS))
def test_each_absence_reason_is_accepted(reason: str) -> None:
    point = make_point(value_f=None, absence_reason=reason)
    assert point.absence_reason == reason
    assert point.value_f is None


def test_an_unknown_absence_reason_is_refused() -> None:
    with pytest.raises(ValueError, match="absence_reason"):
        make_point(value_f=None, absence_reason="dog_ate_it")


def test_the_absence_reason_separates_a_publication_gap_from_a_parser_defect() -> None:
    """Three different causes, three different records -- never one NULL."""
    published_nothing = make_point(value_f=None, absence_reason="not_published")
    parser_failed = make_point(value_f=None, absence_reason="parse_failure")
    sentinel_row = make_point(value_f=-99)

    assert published_nothing.absence_reason != parser_failed.absence_reason
    assert sentinel_row.absence_reason == "sentinel"


# ---------------------------------------------------------------------------
# 3. THE LEAKAGE GUARD: `available_at_ns` is point-in-time truth
# ---------------------------------------------------------------------------


def test_available_at_ns_is_a_required_explicit_constructor_input() -> None:
    """Never defaulted, never optional, never inferred -- the caller measures it."""
    parameters = inspect.signature(ForecastPoint.__init__).parameters

    assert "available_at_ns" in parameters
    parameter = parameters["available_at_ns"]
    assert parameter.default is inspect.Parameter.empty
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY

    kwargs = {
        key: value
        for key, value in make_point().to_dict().items()
        if key in parameters and key != "available_at_ns"
    }
    with pytest.raises(TypeError):
        ForecastPoint(**kwargs)


def test_there_is_no_ts_init_or_ts_event_constructor_parameter() -> None:
    """The timestamps derive from measured instants; they cannot be re-stamped."""
    parameters = inspect.signature(ForecastPoint.__init__).parameters

    assert "ts_init" not in parameters
    assert "ts_event" not in parameters

    with pytest.raises(TypeError):
        make_point(ts_init=1)
    with pytest.raises(TypeError):
        make_point(ts_event=1)


def test_available_at_ns_is_exactly_the_measured_vintage_not_a_clock_reading() -> None:
    """Plan 3.2: `cycle_runtime_ns + measured_publication_lag_ns`, never "now"."""
    point = make_point()

    assert point.available_at_ns == _CYCLE_RUNTIME_NS + _PUBLICATION_LAG_NS
    assert point.measured_publication_lag_ns == _PUBLICATION_LAG_NS


def test_the_vintage_must_equal_the_cycle_plus_the_measured_lag() -> None:
    """The stored lag is auditable BECAUSE the sum is enforced, not assumed.

    Without this, the lag column would be decorative: a caller could store a
    20-minute lag beside a vintage reflecting 65 minutes, and a later audit
    that recomputed the vintage from the lag would silently shift every point.
    """
    with pytest.raises(ValueError, match="measured_publication_lag_ns"):
        ForecastPoint(
            station="KMIA",
            model="NBM_NBS",
            model_version="4.2",
            variable="TXN",
            cycle_runtime_ns=_CYCLE_RUNTIME_NS,
            valid_start_ns=_VALID_START_NS,
            valid_end_ns=_VALID_END_NS,
            value_f=88.0,
            issuance_seq=0,
            measured_publication_lag_ns=_PUBLICATION_LAG_NS,
            available_at_ns=_AVAILABLE_AT_NS + 1,
            ingested_at_ns=_INGESTED_AT_NS,
        )


def test_two_points_differing_only_in_vintage_keep_their_own_vintages() -> None:
    """The field varies independently of every other input, including ts_event."""
    early = make_point(measured_publication_lag_ns=1_800_000_000_000)
    late = make_point(measured_publication_lag_ns=7_200_000_000_000)

    assert early.available_at_ns != late.available_at_ns
    assert early.ts_event == late.ts_event == _CYCLE_RUNTIME_NS
    assert early.to_dict()["available_at_ns"] == _CYCLE_RUNTIME_NS + 1_800_000_000_000
    assert late.to_dict()["available_at_ns"] == _CYCLE_RUNTIME_NS + 7_200_000_000_000


def test_from_dict_reads_the_vintage_from_its_own_column() -> None:
    """Mutating only the `ts_init` column cannot move the vintage silently."""
    values = make_point().to_dict()
    values["ts_init"] = _AVAILABLE_AT_NS + 999_000_000_000

    with pytest.raises(ValueError, match="available_at_ns"):
        ForecastPoint.from_dict(values)


# --- the source-level guard, and the evasions it must survive ---------------

#: Identifiers whose value reflects WHEN A RECORD WAS MATERIALISED rather than
#: when its forecast became knowable. The vintage may not be computed from any
#: of them, directly or through a local.
_HINDSIGHT_NAMES = frozenset(
    {
        "ts_init",
        "ts_event",
        "_ts_init",
        "_ts_event",
        "ingested_at_ns",
        "now",
        "now_ns",
        "time",
        "time_ns",
        "utcnow",
        "monotonic",
        "clock",
        "timestamp_ns",
    },
)

_VINTAGE_ATTR = "available_at_ns"


def _init_functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "__init__"
    ]


def _referenced_names(node: ast.AST) -> set[str]:
    names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
    names |= {child.attr for child in ast.walk(node) if isinstance(child, ast.Attribute)}
    return names


def vintage_guard_violations(source: str) -> list[str]:
    """Return every way `source` could let the vintage follow a materialisation time.

    Deliberately whole-module and flow-sensitive rather than a single pinned
    statement. The realistic refactor is not "assign ts_init to the vintage" --
    nobody writes that -- it is computing the value into a LOCAL one line
    earlier and leaving the pinned assignment textually innocent. Locals are
    therefore tainted transitively, in statement order, and `setattr`,
    annotated assignment and a second `__init__` are all treated as evasions
    rather than as absence of a violation.
    """
    tree = ast.parse(source)
    violations: list[str] = []

    inits = _init_functions(tree)
    if len(inits) != 1:
        violations.append(f"expected exactly one `__init__`, found {len(inits)}")
        return violations
    init = inits[0]

    for node in ast.walk(init):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"setattr", "getattr", "vars", "exec", "eval"}
        ):
            violations.append(
                f"line {node.lineno}: dynamic attribute access `{node.func.id}` in `__init__`",
            )

    tainted: set[str] = set()
    vintage_assignments: list[tuple[int, set[str]]] = []

    for statement in ast.walk(init):
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign):
            targets, value = list(statement.targets), statement.value
        elif isinstance(statement, ast.AnnAssign | ast.AugAssign):
            targets, value = [statement.target], statement.value
        else:
            continue
        if value is None:
            continue

        referenced = _referenced_names(value)
        carries_hindsight = bool(referenced & (_HINDSIGHT_NAMES | tainted))

        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr == _VINTAGE_ATTR:
                vintage_assignments.append((statement.lineno, referenced))
            elif isinstance(target, ast.Name):
                if carries_hindsight:
                    tainted.add(target.id)
                else:
                    tainted.discard(target.id)

    if len(vintage_assignments) != 1:
        violations.append(
            f"expected exactly one assignment to `self.{_VINTAGE_ATTR}`, "
            f"found {len(vintage_assignments)}",
        )

    for lineno, referenced in vintage_assignments:
        forbidden = referenced & (_HINDSIGHT_NAMES | tainted)
        if forbidden:
            violations.append(
                f"line {lineno}: vintage derived from {sorted(forbidden)}",
            )
        if _VINTAGE_ATTR not in referenced:
            violations.append(
                f"line {lineno}: vintage assignment does not reference the "
                f"`{_VINTAGE_ATTR}` parameter",
            )

    return violations


def test_the_constructor_never_derives_the_vintage_from_a_materialisation_time() -> None:
    """Stated syntactically: `ts_init == available_at_ns` holds BY DESIGN.

    No value-level assertion can distinguish the correct direction (measured
    vintage -> `ts_init`) from the hindsight-injecting one, so the direction
    is asserted over the source.
    """
    assert vintage_guard_violations(_MODULE_PATH.read_text()) == []


def _module_source(*lines: str) -> str:
    """Join `lines` into a module source, so no entry needs implicit concatenation."""
    return "\n".join(lines) + "\n"


_EVASIONS: list[tuple[str, str]] = [
    (
        "plain assignment from ts_init",
        _module_source(
            "class P:",
            "    def __init__(self, *, available_at_ns, ts):",
            "        self._ts_init = ts",
            "        self.available_at_ns = self._ts_init",
        ),
    ),
    (
        "annotated assignment overwriting an innocent one",
        _module_source(
            "class P:",
            "    def __init__(self, *, available_at_ns, ts_init):",
            "        self.available_at_ns = available_at_ns",
            "        self.available_at_ns: int = ts_init",
        ),
    ),
    (
        "setattr beside an innocent assignment",
        _module_source(
            "class P:",
            "    def __init__(self, *, available_at_ns, ts_init):",
            "        self.available_at_ns = available_at_ns",
            "        setattr(self, 'available_at_ns', ts_init)",
        ),
    ),
    (
        "the parameter itself rebound from ts_init",
        _module_source(
            "class P:",
            "    def __init__(self, *, available_at_ns, ts_init):",
            "        available_at_ns = ts_init",
            "        self.available_at_ns = require_int(available_at_ns, 'available_at_ns')",
        ),
    ),
    (
        "laundered through a local that still names the parameter",
        _module_source(
            "class P:",
            "    def __init__(self, *, available_at_ns, ts_init):",
            "        available_at_ns = max(available_at_ns, ts_init)",
            "        self.available_at_ns = available_at_ns",
        ),
    ),
    (
        "a second __init__ shadowing the pinned one",
        _module_source(
            "class P:",
            "    def __init__(self, *, available_at_ns):",
            "        self.available_at_ns = available_at_ns",
            "class Q:",
            "    def __init__(self, *, available_at_ns):",
            "        self.available_at_ns = ts_init",
        ),
    ),
    (
        "computed into a local first",
        _module_source(
            "class P:",
            "    def __init__(self, *, available_at_ns, ts_init):",
            "        vintage = ts_init",
            "        self.available_at_ns = vintage",
        ),
    ),
    (
        "laundered through two locals",
        _module_source(
            "class P:",
            "    def __init__(self, *, available_at_ns, ts_init):",
            "        a = ts_init",
            "        b = a",
            "        self.available_at_ns = b",
        ),
    ),
    (
        "derived from the ingest instant",
        _module_source(
            "class P:",
            "    def __init__(self, *, available_at_ns, ingested_at_ns):",
            "        self.available_at_ns = ingested_at_ns",
        ),
    ),
    (
        "no assignment at all",
        _module_source(
            "class P:",
            "    def __init__(self, *, available_at_ns):",
            "        pass",
        ),
    ),
]


@pytest.mark.parametrize(("evasion", "source"), _EVASIONS)
def test_the_vintage_guard_catches_each_known_evasion(evasion: str, source: str) -> None:
    assert vintage_guard_violations(source) != [], evasion


def test_the_vintage_guard_leaves_the_honest_shape_alone() -> None:
    """Non-vacuity in the other direction: a correct `__init__` passes."""
    source = (
        "class P:\n"
        "    def __init__(self, *, available_at_ns, cycle_runtime_ns):\n"
        "        self.cycle_runtime_ns = cycle_runtime_ns\n"
        "        self.available_at_ns = require_int(available_at_ns, 'available_at_ns')\n"
        "        self._ts_init = self.available_at_ns\n"
    )

    assert vintage_guard_violations(source) == []


def test_the_module_never_reads_a_clock() -> None:
    """No clock import, no clock call -- the vintage cannot come from "now"."""
    tree = ast.parse(_MODULE_PATH.read_text())

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported.isdisjoint({"time", "datetime", "calendar"})

    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert called.isdisjoint({"now", "utcnow", "time_ns", "time", "monotonic", "timestamp"})


# ---------------------------------------------------------------------------
# 4. The publication-lag floor
# ---------------------------------------------------------------------------


def test_a_zero_publication_lag_is_refused() -> None:
    """A lag-measurement bug that defaults to 0 grants ~65 minutes of look-ahead.

    That window is exactly the publication repricing window this family trades
    in, so a zero lag is not a conservative fallback -- it is the single most
    profitable-looking and most fictional value the field can take.
    """
    with pytest.raises(ValueError, match="measured_publication_lag_ns"):
        make_point(measured_publication_lag_ns=0)


@pytest.mark.parametrize("model", sorted(MINIMUM_PUBLICATION_LAG_NS))
def test_a_lag_below_the_model_floor_is_refused(model: str) -> None:
    floor = MINIMUM_PUBLICATION_LAG_NS[model]

    with pytest.raises(ValueError, match="measured_publication_lag_ns"):
        make_point(model=model, measured_publication_lag_ns=floor - 1)


@pytest.mark.parametrize("model", sorted(MINIMUM_PUBLICATION_LAG_NS))
def test_a_lag_at_the_model_floor_is_accepted(model: str) -> None:
    floor = MINIMUM_PUBLICATION_LAG_NS[model]

    point = make_point(model=model, measured_publication_lag_ns=floor)

    assert point.measured_publication_lag_ns == floor
    assert point.available_at_ns == _CYCLE_RUNTIME_NS + floor


def test_every_whitelisted_model_declares_a_positive_floor() -> None:
    """A model with no floor would silently reinstate the zero-lag hazard."""
    assert set(MINIMUM_PUBLICATION_LAG_NS) == set(FORECAST_MODELS)
    assert all(floor > 0 for floor in MINIMUM_PUBLICATION_LAG_NS.values())


def test_a_negative_lag_is_refused() -> None:
    with pytest.raises(ValueError, match="measured_publication_lag_ns"):
        make_point(measured_publication_lag_ns=-1)


# ---------------------------------------------------------------------------
# 5. Model whitelist, model version, and the ingest instant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model", ["NBM_NBS", "GFS_MOS", "NBM_NBP"])
def test_each_whitelisted_model_is_accepted(model: str) -> None:
    assert make_point(model=model, measured_publication_lag_ns=4 * 3_600_000_000_000).model == model


@pytest.mark.parametrize("model", ["NAM_MOS", "HRRR", "nbm_nbs", "NBM", "", "ECMWF"])
def test_an_unknown_model_is_refused(model: str) -> None:
    with pytest.raises(ValueError, match="model"):
        make_point(model=model)


def test_the_model_version_is_required_and_distinguishes_skill_regimes() -> None:
    """NBM 4.0 and 4.2 are different skill regimes under one model name.

    Without a version marker a calibration sample straddling the upgrade pools
    two distributions and has nothing to split on afterwards.
    """
    assert make_point(model_version="4.0").model_version == "4.0"
    assert make_point(model_version="4.2").model_version == "4.2"

    with pytest.raises(ValueError):
        make_point(model_version="  ")
    with pytest.raises(TypeError):
        make_point(model_version=None)

    assert make_point(model_version="4.0").join_key != make_point(model_version="4.2").join_key


def test_the_ingest_instant_is_separate_from_the_vintage() -> None:
    """"Did know live" is not "backfilled with a modelled vintage"."""
    live = make_point(ingested_at_ns=_AVAILABLE_AT_NS + 30_000_000_000)
    backfilled = make_point(ingested_at_ns=_AVAILABLE_AT_NS + 400 * 86_400_000_000_000)

    assert live.available_at_ns == backfilled.available_at_ns
    assert live.ingested_at_ns != backfilled.ingested_at_ns
    assert "ingested_at_ns" in ForecastPoint.schema().names


def test_an_ingest_instant_before_the_cycle_is_refused() -> None:
    with pytest.raises(ValueError, match="ingested_at_ns"):
        make_point(ingested_at_ns=_CYCLE_RUNTIME_NS - 1)


# ---------------------------------------------------------------------------
# 5b. NBM_NBP admission (SL-1)
# ---------------------------------------------------------------------------

#: Minimum measured v5.0 NBP publication lag across the 13Z/19Z/01Z cycles,
#: rounded down to 5 minutes, per the SL-3 lag census
#: [VER `docs/evidence/NBP_LAG_CENSUS_2026-09-29.md`, records sha256
#: d31d6436ffda7e24f40c0e2f264caf205c8ff448ef2e9df2722c67bf933ac731].
_NBM_NBP_FLOOR_NS = 60 * 60 * 1_000_000_000

#: The seven NBM v5.0 quantile/summary variables Breezy archives for NBP.
_NBP_QUANTILE_VARIABLES = (
    "TXN_Q10",
    "TXN_Q25",
    "TXN_Q50",
    "TXN_Q75",
    "TXN_Q90",
    "TXN_MEAN",
    "TXN_SD",
)


def test_the_model_whitelist_and_the_floor_table_share_exactly_one_key_set() -> None:
    """A model admitted without a floor would reinstate the zero-lag hazard."""
    assert set(FORECAST_MODELS) == set(MINIMUM_PUBLICATION_LAG_NS)


@pytest.mark.parametrize("variable", _NBP_QUANTILE_VARIABLES)
def test_each_nbp_quantile_variable_survives_the_arrow_round_trip(variable: str) -> None:
    from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

    original = make_point(
        model="NBM_NBP",
        variable=variable,
        measured_publication_lag_ns=_NBM_NBP_FLOOR_NS,
    )

    batch = ArrowSerializer.serialize(original, ForecastPoint)
    (restored,) = ArrowSerializer.deserialize(ForecastPoint, pa.Table.from_batches([batch]))

    assert restored.to_dict() == original.to_dict()
    assert restored.model == "NBM_NBP"
    assert restored.variable == variable


def test_a_lag_below_the_nbp_floor_is_refused() -> None:
    """59 minutes is one below the 60-minute NBP floor.

    The SL-3 census measured a minimum of 61.05 minutes across the 13Z/19Z/01Z
    cycles, rounded down to 5 minutes
    [VER `docs/evidence/NBP_LAG_CENSUS_2026-09-29.md`, records sha256
    d31d6436ffda7e24f40c0e2f264caf205c8ff448ef2e9df2722c67bf933ac731].
    """
    with pytest.raises(ValueError, match="measured_publication_lag_ns"):
        make_point(model="NBM_NBP", measured_publication_lag_ns=59 * 60 * 1_000_000_000)


def test_a_lag_at_the_nbp_floor_is_accepted() -> None:
    point = make_point(model="NBM_NBP", measured_publication_lag_ns=_NBM_NBP_FLOOR_NS)

    assert point.model == "NBM_NBP"
    assert point.measured_publication_lag_ns == _NBM_NBP_FLOOR_NS


# ---------------------------------------------------------------------------
# 6. Identity, normalisation and the join key
# ---------------------------------------------------------------------------


def test_the_station_is_normalised_so_one_station_is_one_key() -> None:
    """`" kmia "` and `"KMIA"` must not become two archive keys.

    These fields ARE the join key here, so a whitespace or case difference
    silently splits one station's calibration sample in two. Normalised on the
    way in, scoped to this record type.
    """
    assert make_point(station=" kmia ").station == "KMIA"
    assert make_point(station=" kmia ").join_key == make_point(station="KMIA").join_key


def test_surrounding_whitespace_is_stripped_from_every_text_join_field() -> None:
    point = make_point(station=" KMIA ", model=" NBM_NBS ", variable=" TXN ", model_version=" 4.2 ")

    assert point.station == "KMIA"
    assert point.model == "NBM_NBS"
    assert point.variable == "TXN"
    assert point.model_version == "4.2"


def test_the_station_must_be_non_empty_text() -> None:
    with pytest.raises(ValueError):
        make_point(station="   ")
    with pytest.raises(TypeError):
        make_point(station=None)


def test_the_join_key_is_the_forecast_identity_across_reissues() -> None:
    """The key names the FORECAST; `issuance_seq` names which issuance of it."""
    original = make_point(issuance_seq=0)
    correction = make_point(
        issuance_seq=1,
        value_f=91.0,
        measured_publication_lag_ns=_PUBLICATION_LAG_NS + 3_600_000_000_000,
    )

    assert original.join_key == correction.join_key
    assert isinstance(original.join_key, ForecastPointKey)
    assert original.record_key != correction.record_key


def test_the_record_key_is_the_join_key_plus_the_issuance() -> None:
    point = make_point(issuance_seq=2)

    assert point.record_key == (*point.join_key, 2)


@pytest.mark.parametrize("field", ["station", "model", "model_version", "variable"])
def test_a_differing_text_field_yields_a_different_join_key(field: str) -> None:
    other = make_point(**{field: "KSFO" if field == "station" else "GFS_MOS"}) if field in {
        "station",
        "model",
    } else make_point(**{field: "OTHER"})

    assert other.join_key != make_point().join_key


def test_a_negative_issuance_sequence_is_refused() -> None:
    with pytest.raises(ValueError, match="issuance_seq"):
        make_point(issuance_seq=-1)


# ---------------------------------------------------------------------------
# 7. Corrections and the as-of selection rule
# ---------------------------------------------------------------------------


def _original() -> ForecastPoint:
    return make_point(issuance_seq=0, value_f=88.0)


def _correction(lag_extra_ns: int = 3_600_000_000_000, value_f: float = 91.0) -> ForecastPoint:
    return make_point(
        issuance_seq=1,
        value_f=value_f,
        measured_publication_lag_ns=_PUBLICATION_LAG_NS + lag_extra_ns,
    )


def test_a_correction_is_a_distinct_record_with_its_own_later_vintage() -> None:
    """NOAA reissues bulletins. A correction never overwrites the original."""
    original, correction = _original(), _correction()

    assert correction.issuance_seq > original.issuance_seq
    assert correction.available_at_ns > original.available_at_ns
    assert correction.record_key != original.record_key


def test_a_reissue_may_not_claim_the_originals_vintage() -> None:
    """The hindsight injection this section exists to stop.

    A corrected value stamped with the ORIGINAL vintage is indistinguishable
    from prescience: an as-of join at the original's publication instant would
    return a number nobody could have seen for another hour.
    """
    points = [_original(), _correction(lag_extra_ns=0, value_f=91.0)]

    with pytest.raises(ValueError, match="issuance_seq"):
        select_as_of(points, as_of_ns=_AVAILABLE_AT_NS + 86_400_000_000_000)


def test_as_of_selects_the_greatest_vintage_at_or_before_the_instant() -> None:
    original, correction = _original(), _correction()
    points = [correction, original]  # deliberately unsorted

    selected = select_as_of(points, as_of_ns=correction.available_at_ns)

    assert selected is correction
    assert selected.value_f == 91.0


def test_a_correction_is_invisible_to_an_as_of_join_before_its_vintage() -> None:
    """The load-bearing assertion of the whole seam.

    One nanosecond before the correction was published, the only answer is the
    original. Any implementation that returns the correction here has injected
    hindsight into every backtest that uses it.
    """
    original, correction = _original(), _correction()

    selected = select_as_of([original, correction], as_of_ns=correction.available_at_ns - 1)

    assert selected is original
    assert selected.value_f == 88.0


def test_as_of_returns_none_before_anything_was_published() -> None:
    original = _original()

    assert select_as_of([original], as_of_ns=original.available_at_ns - 1) is None


def test_as_of_includes_a_record_published_exactly_at_the_instant() -> None:
    """The bound is `<=`: a point published at T WAS knowable at T."""
    original = _original()

    assert select_as_of([original], as_of_ns=original.available_at_ns) is original


def test_as_of_refuses_a_mixed_join_key() -> None:
    """Silently picking across two different forecasts would be a wrong answer."""
    with pytest.raises(ValueError, match="join key"):
        select_as_of([_original(), make_point(station="KSFO")], as_of_ns=_AVAILABLE_AT_NS)


def test_as_of_of_an_empty_input_is_none() -> None:
    assert select_as_of([], as_of_ns=_AVAILABLE_AT_NS) is None


def test_an_idempotent_reingest_does_not_double_weight_the_point() -> None:
    """Two identical rows are ONE observation, not two.

    Writing the same bulletin twice must not let a calibration fit count that
    point twice -- the record has an identity, and the as-of selection is
    defined on it.
    """
    once = _original()
    again = _original()

    assert once.record_key == again.record_key
    assert select_as_of([once, again], as_of_ns=_AVAILABLE_AT_NS) is not None
    assert len(latest_as_of([once, again], as_of_ns=_AVAILABLE_AT_NS)) == 1


def test_two_records_sharing_an_identity_but_not_their_content_are_refused() -> None:
    """A correction written under the original's sequence is a contradiction."""
    contradicting = make_point(issuance_seq=0, value_f=91.0)

    with pytest.raises(ValueError, match="record_key"):
        select_as_of([_original(), contradicting], as_of_ns=_AVAILABLE_AT_NS)


def test_latest_as_of_groups_by_join_key_and_applies_the_same_rule() -> None:
    miami_original, miami_correction = _original(), _correction()
    san_francisco = make_point(station="KSFO", value_f=70.0)

    at_publication = latest_as_of(
        [miami_original, miami_correction, san_francisco],
        as_of_ns=miami_correction.available_at_ns - 1,
    )
    later = latest_as_of(
        [miami_original, miami_correction, san_francisco],
        as_of_ns=miami_correction.available_at_ns,
    )

    assert at_publication[miami_original.join_key] is miami_original
    assert later[miami_correction.join_key] is miami_correction
    assert at_publication[san_francisco.join_key] is san_francisco


def test_latest_as_of_omits_a_key_with_nothing_published_yet() -> None:
    original = _original()

    assert latest_as_of([original], as_of_ns=original.available_at_ns - 1) == {}


# ---------------------------------------------------------------------------
# 8. Ordering invariants
# ---------------------------------------------------------------------------


def test_an_inverted_validity_window_is_refused() -> None:
    with pytest.raises(ValueError, match="valid_end_ns"):
        make_point(valid_start_ns=_VALID_END_NS, valid_end_ns=_VALID_START_NS)


def test_an_instantaneous_validity_window_is_accepted() -> None:
    point = make_point(valid_start_ns=_VALID_START_NS, valid_end_ns=_VALID_START_NS)
    assert point.valid_start_ns == point.valid_end_ns


@pytest.mark.parametrize(
    "field",
    [
        "cycle_runtime_ns",
        "valid_start_ns",
        "valid_end_ns",
        "available_at_ns",
        "ingested_at_ns",
        "measured_publication_lag_ns",
        "issuance_seq",
    ],
)
def test_every_instant_must_be_an_int(field: str) -> None:
    with pytest.raises(TypeError):
        make_point(**{field: 1.0})


# ---------------------------------------------------------------------------
# 9. The record shape itself
# ---------------------------------------------------------------------------

_SCHEMA_COLUMNS = [
    "station",
    "model",
    "model_version",
    "variable",
    "cycle_runtime_ns",
    "valid_start_ns",
    "valid_end_ns",
    "value_f",
    "absence_reason",
    "issuance_seq",
    "measured_publication_lag_ns",
    "available_at_ns",
    "ingested_at_ns",
    "schema_version",
    "ts_event",
    "ts_init",
]


def test_the_schema_columns_are_the_plan_fields_plus_the_pit_provenance() -> None:
    assert list(ForecastPoint.schema().names) == _SCHEMA_COLUMNS


@pytest.mark.parametrize("missing_column", _SCHEMA_COLUMNS)
def test_from_dict_raises_on_a_missing_column(missing_column: str) -> None:
    values = make_point().to_dict()
    del values[missing_column]

    with pytest.raises(KeyError):
        ForecastPoint.from_dict(values)


def test_from_dict_round_trips_to_dict() -> None:
    original = make_point()
    restored = ForecastPoint.from_dict(original.to_dict())
    assert restored.to_dict() == original.to_dict()


def test_a_schema_version_change_is_visible_on_the_record() -> None:
    """Not a restatement of the constant: the value must reach the ARCHIVE."""
    assert make_point().to_dict()["schema_version"] == FORECAST_POINT_SCHEMA_VERSION
    assert ForecastPoint.from_dict(make_point().to_dict()).schema_version == (
        FORECAST_POINT_SCHEMA_VERSION
    )


def test_the_repr_names_the_station_model_vintage_and_issuance() -> None:
    text = repr(make_point(issuance_seq=3))
    assert "ForecastPoint(" in text
    assert "KMIA" in text
    assert "NBM_NBS" in text
    assert str(_AVAILABLE_AT_NS) in text
    assert "issuance_seq=3" in text


def test_the_record_carries_no_instrument_id() -> None:
    """Design decision, pinned: per-station catalog roots, not `instrument_id`.

    `ParquetDataCatalog` partitions on `instrument_id` when the attribute is
    present (`persistence/catalog/parquet.py:320-336`). Adding one here would
    mint a synthetic venue identifier for a NOAA model output that is not
    traded, and would bind the archive layout to venue symbology. The later
    catalog seam therefore uses ONE catalog root per station. If that choice
    is ever revisited, this test is the place it must be revisited.
    """
    assert not hasattr(make_point(), "instrument_id")
    assert "instrument_id" not in ForecastPoint.schema().names


def test_module_registers_arrow_exactly_once() -> None:
    """Record mutant: adding a second module-scope `register_arrow` call.

    A second call wins in the global registry but leaves `cls._schema`
    unchanged -- a permanent silent divergence between what `to_arrow` uses
    and what the catalog writes.
    """
    tree = ast.parse(_MODULE_PATH.read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "register_arrow"
    ]
    assert len(calls) == 1


#: Tokens that name a transport or a remote host. Matched against IMPORTS and
#: non-docstring string literals only -- never against prose, where an ordinary
#: English "requests" or a cited URL in a docstring would fire a false block.
_TRANSPORT_TOKENS = ("http", "nomads", "mesonet", "requests", "urllib", "socket", "aiohttp")


def test_the_module_imports_no_transport_and_names_no_host() -> None:
    """Seam A is the pure domain type: no network, no hosts, no transport."""
    tree = ast.parse(_MODULE_PATH.read_text())

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    for name in imported:
        assert not any(token in name.lower() for token in _TRANSPORT_TOKENS), name

    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]

    for literal in literals:
        assert not any(token in literal.lower() for token in _TRANSPORT_TOKENS), literal


def test_the_transport_scan_would_catch_a_real_import_or_host() -> None:
    """Non-vacuity, and proof the narrowing did not defang the rule."""
    for source in (
        "import requests\n",
        "from urllib.request import urlopen\n",
        'HOST = "nomads.ncep.noaa.gov"\n',
    ):
        tree = ast.parse(source)
        names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        } | {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert any(
            token in name.lower() for name in names for token in _TRANSPORT_TOKENS
        ), source


def test_a_docstring_mentioning_requests_does_not_trip_the_scan() -> None:
    """The defect the narrowing fixes: prose is not a transport."""
    tree = ast.parse('"""This module answers requests over no socket at all."""\n')
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    docstring = ast.get_docstring(tree)

    assert docstring is not None
    assert literals == [docstring]


def test_the_sentinels_are_exact_and_neighbouring_values_are_not() -> None:
    """Behavioural, not a restatement: the comparison must be exact equality."""
    for sentinel in FORECAST_VALUE_SENTINELS:
        assert forecast_value_or_none(sentinel) is None
        assert forecast_value_or_none(math.nextafter(sentinel, 0.0)) is not None
