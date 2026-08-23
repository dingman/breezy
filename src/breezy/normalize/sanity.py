"""Physical sanity bounds for parsed CLI temperature values.

PURE module: no I/O, no clock access, no `nautilus_trader` import, no
global state.

`domain/validation.py` states that physical-plausibility bounds belong to
the normalization layer, which runs before a record is built. This is
that layer. It closes the hole between "the text parsed" and "the value
settles money": a CLI product reporting a maximum of 250 F, a minimum of
-300 F, or a 200-degree diurnal range is not a settlement datum, it is a
malformed remote product or a parser defect, and it must fail LOUDLY
rather than settle quietly.

WHY A SEPARATE ERROR TYPE
-------------------------
`CliSanityError` is deliberately NOT a `CliParseError`. The settlement
gate routes `GateReason.SANITY_VIOLATION` and `GateReason.PARSER_FAILURE`
to different reason codes with different audit trails, and an existing
``except CliParseError`` handler would otherwise swallow a sanity
violation and record the wrong cause. Both are `ValueError`, so a caller
that catches `ValueError` at the never-crash boundary still catches both.

CALIBRATION PHILOSOPHY -- err WIDE
----------------------------------
The target is *physically impossible*, never merely *unusual*. Breezy
settles on LAX, MDW, MIA, NYC and SFO. A bound tight enough to reject a
genuine Chicago cold snap or a Miami heat record would take the bot
offline exactly when the market is most interesting -- the guard would
become the outage. Every bound below is therefore justified against a
value that has actually been RECORDED, with deliberate headroom above it,
and every bound is inclusive at its limit.

Per-bound justification is on each constant. Widen these if reality ever
argues for it; never narrow them toward "what we usually see".
"""

from __future__ import annotations

from breezy.normalize.units import TemperatureReadingF


class CliSanityError(ValueError):
    """A parsed value is physically impossible.

    Distinct from `breezy.normalize.cli_parse.CliParseError` on purpose,
    and NOT a subclass of it: the text parsed correctly, so this is not a
    parser failure. The settlement gate routes the two to different
    reason codes (`SANITY_VIOLATION` vs `PARSER_FAILURE`).
    """


ABSOLUTE_MAX_F = 140
"""Upper bound, inclusive, on any published temperature field.

The highest air temperature ever reliably measured anywhere on Earth is
134 F (Death Valley, CA, 1913-07-10); the highest modern instrumented
readings sit near 130 F. 140 F is above every value ever recorded on the
planet, so a value beyond it cannot be a surface air temperature.

Headroom against reality at our five sites: the hottest all-time record
among them is roughly 110 F (LAX) / 109 F (Chicago Midway), so this bound
sits ~30 F above anything these stations can physically produce, and
still above a hypothetical new US national record.

Decision (settled): `nws-cli-settlement` suggests 130 F, but that figure
sits BELOW the attested US/world record of 134 F -- it bounds "unusual",
not "impossible". 140 F is kept as the deliberately wider figure: it
stays above the all-time world record with margin, so a genuine
once-in-a-century heat event at one of our five sites is recorded rather
than halting trading on a false sanity violation. This reconciles the two
layers' figures by design rather than by drift; no further reconciliation
is pending.
"""

ABSOLUTE_MIN_F = -100
"""Lower bound, inclusive, on any published temperature field.

The lowest temperature ever recorded in the United States is -80 F
(Prospect Creek, AK, 1971-01-23); the lower-48 record is -70 F (Rogers
Pass, MT, 1954). -100 F sits 20 F below the US record and ~73 F below the
coldest value any of our five sites has ever seen (about -27 F at Chicago
Midway). It matches the floor `nws-cli-settlement` specifies, so the
layers agree.
"""

MAX_DIURNAL_RANGE_F = 130
"""Upper bound, inclusive, on ``MAXIMUM - MINIMUM`` for one climate day.

NOT redundant with the per-field envelope, and this is the whole
justification for its existence: the envelope alone permits a 240-degree
span (140 paired with -100), because it never looks at the two values
TOGETHER. A column-shift or a corrupted row that pairs a real maximum
with another row's minimum produces two individually-plausible values and
one impossible pair. Only a joint bound catches that.

Calibrated against the largest single-day temperature range ever recorded
on Earth: 100 F at Browning, MT, 1916-01-23/24 (+44 F to -56 F). 130 F is
30 F beyond the world record, and roughly triple the largest range any of
our five sites can produce (~40-45 F at Chicago Midway). It is a bound on
the physically impossible, not on the locally unusual.

This is the one bound where over-fitting was a live risk. It is set from
the world record rather than from the sites' observed ranges precisely so
it can never become the constraint that halts a real record-breaking day.
"""


def _check_envelope(value: int | None, label: str) -> None:
    """Bound one field to the physical envelope, both sides.

    The envelope is two-sided for every field, including MAXIMUM: a daily
    maximum of -300 F is exactly as impossible as one of 250 F. Applying
    the same envelope to all three fields is deliberate -- every one of
    them is a surface air temperature in degrees Fahrenheit, so they share
    one physical range. Per-field asymmetry (e.g. "a maximum can never be
    below freezing") would be over-fitting to these five sites' climates
    rather than to physics.
    """
    if value is None:
        return

    if value > ABSOLUTE_MAX_F:
        raise CliSanityError(
            f"{label} of {value} F exceeds the physical bound of {ABSOLUTE_MAX_F} F "
            "(above the highest temperature ever recorded on Earth); refusing to "
            "treat a physically impossible value as settlement data"
        )

    if value < ABSOLUTE_MIN_F:
        raise CliSanityError(
            f"{label} of {value} F is below the physical bound of {ABSOLUTE_MIN_F} F "
            "(below the lowest temperature ever recorded in the US); refusing to "
            "treat a physically impossible value as settlement data"
        )


def _check_not_above(
    lower: int | None, upper: int | None, lower_label: str, upper_label: str
) -> None:
    """Assert ``lower <= upper`` when both values are present.

    Equality is ACCEPTED: a flat, fog-locked marine-layer day rounds to
    the same whole degree for both extremes at SFO, and CLI publishes
    whole degrees. Only a strict inversion is impossible.
    """
    if lower is None:
        return

    if upper is None:
        return

    if lower > upper:
        raise CliSanityError(
            f"{lower_label} of {lower} F exceeds {upper_label} of {upper} F; a "
            "minimum cannot exceed a maximum and an average cannot fall outside "
            "them -- this is a column shift or a corrupted product, not a reading"
        )


def _check_diurnal_range(tmax_f: int | None, tmin_f: int | None) -> None:
    """Bound the joint span the per-field envelope cannot see."""
    if tmax_f is None:
        return

    if tmin_f is None:
        return

    span = tmax_f - tmin_f
    if span > MAX_DIURNAL_RANGE_F:
        raise CliSanityError(
            f"diurnal range of {span} F (MAXIMUM {tmax_f} F, MINIMUM {tmin_f} F) "
            f"exceeds the physical bound of {MAX_DIURNAL_RANGE_F} F (the largest "
            "single-day range ever recorded on Earth is 100 F); both endpoints are "
            "individually plausible, so this is a corrupted pair"
        )


def check_physical_sanity(
    *,
    tmax: TemperatureReadingF,
    tmin: TemperatureReadingF,
    tavg: TemperatureReadingF,
) -> None:
    """Validate parsed CLI temperatures against physical sanity bounds.

    Returns `None` on success and raises `CliSanityError` on the first
    violation -- never a partial or advisory result, because the caller's
    only correct response to any violation is to halt settlement for the
    site.

    A sentinel-bearing reading (`value_f is None`) is checked for nothing
    and is never imputed: an absent value is a known-unknown that the
    settlement gate handles separately, not a zero.

    Checks run cheapest-and-most-local first: the per-field envelope, then
    mutual ordering, then the joint diurnal range. Ordering precedes the
    range check so an inverted pair is reported as an inversion rather
    than as a negative span.
    """
    tmax_f = tmax.value_f
    tmin_f = tmin.value_f
    tavg_f = tavg.value_f

    _check_envelope(tmax_f, "MAXIMUM")
    _check_envelope(tmin_f, "MINIMUM")
    _check_envelope(tavg_f, "AVERAGE")

    # tmin <= tavg <= tmax. The CLI AVERAGE row is definitionally the mean
    # of the day's MAXIMUM and MINIMUM, so a value outside the closed
    # interval they bound is arithmetically impossible, not merely odd.
    _check_not_above(tmin_f, tmax_f, "MINIMUM", "MAXIMUM")
    _check_not_above(tavg_f, tmax_f, "AVERAGE", "MAXIMUM")
    _check_not_above(tmin_f, tavg_f, "MINIMUM", "AVERAGE")

    _check_diurnal_range(tmax_f, tmin_f)
