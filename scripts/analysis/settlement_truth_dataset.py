"""Historical settlement-truth dataset from the held IEM AFOS CLI archive.

WHAT THIS IS
------------
For every ``(station, climate_day)`` covered by the settlement-alignment
archive cache, this script derives the settlement-grade realized daily maximum
temperature -- the value Polymarket.us weather markets settle on -- together
with its provenance, its preliminary-vs-final revision history, and the
inclusive bucket the reading falls in.

It is ANALYSIS ONLY. It never writes to the live ParquetDataCatalog, never
touches an ingestion path, never contacts a venue, and never performs network
I/O: the archive cache is read strictly read-only, and a cache miss is a
refusal, not a fetch.

THE SETTLEMENT PREDICATE
------------------------
``docs/evidence/venue/polymarket_us/THRESHOLD_SEMANTICS_2026-08-25.md``
section 4.2 (lines 210-223):

    For two-token weather slugs ``gte{A}lt{B}f``, the settling predicate is
    ``A <= observed <= B`` (INCLUSIVE on both bounds). The ``lt`` token in
    the slug is venue naming, not the settlement predicate.

Two independent proofs, both in that document:

1. EMPIRICAL (:170-184). The NWS observed high for KNYC on 2026-04-23 was
   exactly 73F, and market 15806 ``tc-temp-nychigh-2026-04-23-gte72lt73f``
   resolved YES (``outcomePrices`` ``["1","0"]``). Under the literal strict
   reading that bucket is ``{72}``, 73 falls outside it, and the market would
   have had to resolve NO. It did not.
2. STRUCTURAL (:186-208). The published ladder steps by 2F -- lower bounds
   66, 68, 70, 72, 74. Under the literal reading, 67/69/71/73 would be covered
   by no market at all. Only the inclusive reading tiles the integers with no
   gap and no overlap.

Single-sided slugs keep their literal reading (:222-223): ``lt66f`` is
``<= 65``, ``gte74f`` is ``>= 74``.

Adopting the literal reading would misprice the entire ladder on 67% of the
captured corpus (:18). This module therefore does NOT re-implement the
predicate: it delegates to
``breezy.domain.weather_bucket_facts.WeatherBucketFacts.contains``, the
already-corroborated closed-interval implementation, so there is exactly one
statement of the rule in the codebase.

WHAT IS NOT DERIVABLE
---------------------
The venue's ladder ANCHOR is a per-market choice, not a property of the
weather. Measured over the committed corpus (680 markets, 112 complete
ladders) the interior lower anchor is odd on 58 ladders and even on 54. So for
a historical day with no captured ladder, WHICH bucket the venue would have
published is NOT derivable from the archive. This dataset therefore emits the
interior bucket under BOTH anchor parities, explicitly labelled, and never
pretends to know which one the venue used. Whether a day's reading would have
landed in a published interior bucket at all (rather than a ``lt``/``gte``
tail bucket) is likewise not derivable.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final
from zipfile import BadZipFile, ZipFile

import pyarrow as pa
import pyarrow.parquet as pq
from settlement_alignment_cache import (
    DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
    require_settlement_alignment_cache_dir,
)
from settlement_alignment_study import (
    afos_url,
    cache_path_for_url,
    issue_utc_from_iem_filename,
    parse_issued_at,
)

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.normalize.classify import (
    ClassificationError,
    classify_issuance,
    has_correction_evidence,
)
from breezy.normalize.cli_parse import CliParseError, parse_cli_product
from breezy.normalize.sanity import CliSanityError
from breezy.registry.sites import SettlementSite, default_registry

VENUE: Final[str] = "polymarket_us"

#: Where the derived dataset lands. Deliberately NOT the live settlement
#: catalog (`~/.local/share/breezy/catalog`) and not a repo path: this is
#: derived research output, regenerable from the archive at any time.
DEFAULT_OUTPUT_DIR: Final[Path] = Path.home() / ".local/share/breezy/derived/settlement-truth"
DEFAULT_LIVE_CATALOG_DIR: Final[Path] = Path.home() / ".local/share/breezy/catalog"
DEFAULT_ARCHIVE_ROOT_DIR: Final[Path] = Path.home() / ".local/share/breezy/archive"

# Observed corpus maximum on 2026-08-30 was 5,294 bytes across 19,507 members.
# 64 KiB leaves >12x headroom for ordinary CLI format drift while refusing
# hostile zip members before decompression and UTF-8 decode.
MAX_ARCHIVE_MEMBER_BYTES: Final[int] = 64 * 1024
MAX_ARCHIVE_COMPRESSION_RATIO: Final[float] = 100.0

#: Citation for the predicate this module applies. Kept as data so a report
#: cannot state the rule without stating where it came from.
SETTLEMENT_PREDICATE_EVIDENCE: Final[str] = (
    "docs/evidence/venue/polymarket_us/THRESHOLD_SEMANTICS_2026-08-25.md:170-223"
)
SETTLEMENT_PREDICATE_STATEMENT: Final[str] = (
    "gte{A}lt{B}f settles YES iff A <= observed_tmax_f <= B (both bounds "
    "INCLUSIVE); lt{N}f settles YES iff observed_tmax_f <= N-1; gte{N}f "
    "settles YES iff observed_tmax_f >= N. The slug's `lt` token is venue "
    "naming, not the settlement predicate."
)

STATUS_FINAL: Final[str] = "FINAL"
STATUS_PRELIMINARY_ONLY: Final[str] = "PRELIMINARY_ONLY"
STATUS_NO_PRODUCT: Final[str] = "NO_PRODUCT"
STATUS_FINAL_TMAX_SENTINEL: Final[str] = "FINAL_TMAX_SENTINEL"
STATUS_AMBIGUOUS_FINAL: Final[str] = "AMBIGUOUS_FINAL"

#: Placeholders for the predicate-only path. `WeatherBucketFacts.contains`
#: reads neither field; they exist so the one corroborated implementation of
#: the rule can be reused without a parallel copy of the comparison.
_PREDICATE_PLACEHOLDER_STATION: Final[str] = "PREDICATE-ONLY"
_PREDICATE_PLACEHOLDER_DAY: Final[dt.date] = dt.date(1970, 1, 1)

#: WMO abbreviated heading, e.g. `CDUS41 KOKX 240617`.
_WMO_HEADING_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<ttaaii>[A-Z]{4}\d{2})\s+(?P<office>[A-Z]{4})\s+(?P<ddhhmm>\d{6})"
)
#: IEM zip member name, e.g. `CLINYC_202604240617.txt`.
_MEMBER_STAMP_RE: Final[re.Pattern[str]] = re.compile(r"_(?P<stamp>\d{12})\.txt$")


class SettlementTruthError(ValueError):
    """Base class for every refusal this module raises."""


class ArchiveRefusalError(SettlementTruthError):
    """An archived product could not be admitted as this station's CLI."""


class ArchiveDigestError(SettlementTruthError):
    """Archived bytes did not match the digest they were expected to carry."""


class ArchiveMemberSafetyError(SettlementTruthError):
    """A zip member exceeds the bounded archive safety envelope."""


class ArchiveSelectionError(SettlementTruthError):
    """Multiple admitted products cannot be ordered into one truth row."""


class ArchiveCoverageError(SettlementTruthError):
    """A declared archive window is not present in the read-only cache."""


# ---------------------------------------------------------------------------
# The settlement predicate
# ---------------------------------------------------------------------------


def bucket_facts(
    *,
    lower_f: int | None,
    upper_f: int | None,
    station: str = _PREDICATE_PLACEHOLDER_STATION,
    climate_day: dt.date = _PREDICATE_PLACEHOLDER_DAY,
) -> WeatherBucketFacts:
    """Build the closed interval a weather bucket settles on.

    Bounds are the slug's decoded bounds as
    ``breezy.adapters.polymarket_us.symbology`` records them: ``lt{N}f`` ->
    ``(None, N - 1)``, ``gte{N}f`` -> ``(N, None)``, ``gte{A}lt{B}f`` ->
    ``(A, B)``. The interval is CLOSED at both finite ends.
    """
    if lower_f is None and upper_f is None:
        raise SettlementTruthError("a bucket needs at least one finite bound")
    if lower_f is not None and upper_f is not None and lower_f > upper_f:
        raise SettlementTruthError(f"lower bound {lower_f} exceeds upper bound {upper_f}")
    return WeatherBucketFacts(
        settlement_station=station,
        climate_day=climate_day,
        measure=Measure.HIGH,
        lower_f=lower_f,
        upper_f=upper_f,
    )


def settles_yes(tmax_f: int, *, lower_f: int | None, upper_f: int | None) -> bool:
    """THE settlement predicate: does ``tmax_f`` settle this bucket YES?

    See the module docstring for the evidence. Delegates to
    ``WeatherBucketFacts.contains`` so the rule has exactly one implementation.
    """
    return bucket_facts(lower_f=lower_f, upper_f=upper_f).contains(tmax_f)


def interior_bucket(tmax_f: int, *, anchor_parity: int) -> tuple[int, int]:
    """The 2F-wide interior ladder bucket containing ``tmax_f``.

    ``anchor_parity`` is the parity of the ladder's interior lower bounds. It
    is NOT derivable from the archive -- the captured corpus splits 58 odd /
    54 even across 112 complete ladders -- so the caller must state which
    ladder it means. Both are emitted in the dataset.
    """
    if anchor_parity not in (0, 1):
        raise SettlementTruthError(f"anchor_parity must be 0 or 1, got {anchor_parity!r}")
    lower = tmax_f - ((tmax_f - anchor_parity) % 2)
    return lower, lower + 1


def interior_bucket_slug(lower_f: int) -> str:
    """The venue slug bounds token for an interior bucket ``[A, A+1]``.

    The token reads ``gte{A}lt{A+1}f`` -- inner span 1 on 455/455 captured
    interior markets -- while the bucket it names is the CLOSED interval
    ``[A, A+1]``, two degrees wide (display width 2 on 455/455).
    """
    return f"gte{lower_f}lt{lower_f + 1}f"


# ---------------------------------------------------------------------------
# Archive windows held in the read-only cache
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArchiveWindow:
    """One AFOS retrieval that is present in the settlement-alignment cache."""

    city: str
    cli_location: str
    start: dt.date
    end: dt.date
    limit: int

    @property
    def url(self) -> str:
        return afos_url(self.cli_location, self.start, self.end, limit=self.limit)

    def days(self) -> tuple[dt.date, ...]:
        span = (self.end - self.start).days
        return tuple(self.start + dt.timedelta(days=offset) for offset in range(span + 1))


#: The 2026 tail windows were fetched by the archive-vs-catalog validation
#: bridge with a different `limit` and per-city start dates. Enumerated
#: verbatim rather than derived, because they are not a regular grid.
_VALIDATION_WINDOW_STARTS: Final[Mapping[str, dt.date]] = {
    "NYC": dt.date(2026, 8, 17),
    "SFO": dt.date(2026, 8, 17),
    "MIA": dt.date(2026, 8, 17),
    "LAX": dt.date(2026, 8, 17),
    "MDW": dt.date(2026, 8, 16),
}
_VALIDATION_WINDOW_END: Final[dt.date] = dt.date(2026, 8, 23)
_STATION_YEARS: Final[tuple[int, ...]] = (2021, 2022, 2023, 2024, 2025)


def archive_windows(cities: Sequence[str] | None = None) -> tuple[ArchiveWindow, ...]:
    """Every AFOS window the settlement-alignment cache is known to hold.

    Coverage is NOT contiguous: the station-year windows end 2025-12-31 and
    the next held window starts 2026-08-16/17. Everything in between is absent
    from the archive and is reported as such, never interpolated.
    """
    registry = default_registry()
    windows: list[ArchiveWindow] = []
    for venue, city in registry.pairs():
        if venue != VENUE:
            continue
        if cities is not None and city not in cities:
            continue
        cli_location = registry.settlement_site(venue, city).cli_location
        for year in _STATION_YEARS:
            windows.append(
                ArchiveWindow(
                    city=city,
                    cli_location=cli_location,
                    start=dt.date(year, 1, 1),
                    end=dt.date(year, 12, 31),
                    limit=3_000,
                )
            )
        start = _VALIDATION_WINDOW_STARTS.get(cli_location)
        if start is not None:
            windows.append(
                ArchiveWindow(
                    city=city,
                    cli_location=cli_location,
                    start=start,
                    end=_VALIDATION_WINDOW_END,
                    limit=500,
                )
            )
    return tuple(windows)


def window_zip_path(cache_dir: Path, window: ArchiveWindow) -> Path:
    """The content-addressed cache path for ``window``; refuses on a miss."""
    path = cache_path_for_url(cache_dir, window.url, suffix=".zip")
    if not path.is_file():
        raise ArchiveCoverageError(
            f"{window.city} {window.start}..{window.end}: archive window absent from the "
            f"read-only cache (expected {path}); this run performs no network I/O"
        )
    return path


def archive_digest_sidecar_path(cache_dir: Path) -> Path:
    """Per-cache sha256sum manifest path for cached archive files."""
    return cache_dir.with_suffix(".sha256")


def read_archive_digest_sidecar(cache_dir: Path) -> dict[str, str]:
    """Read the cache-level sha256sum sidecar.

    The sidecar is per zip/cache file, not per zip member. A missing or
    malformed entry is a refusal because proceeding would silently downgrade
    provenance from verified archive bytes to "whatever is currently on disk."
    """
    path = archive_digest_sidecar_path(cache_dir)
    if not path.is_file():
        raise ArchiveDigestError(
            f"archive digest sidecar is missing: {path}; refusing to use unchecked cache bytes"
        )

    digests: dict[str, str] = {}
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise ArchiveDigestError(f"{path}:{line_no}: malformed sha256 sidecar line")
        digest, name = parts
        if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise ArchiveDigestError(f"{path}:{line_no}: malformed sha256 digest {digest!r}")
        digests[Path(name).name] = digest.lower()
    return digests


def expected_zip_digest(zip_path: Path, digests: Mapping[str, str]) -> str:
    """Return the expected digest for one cached zip, refusing on omissions."""
    expected = digests.get(zip_path.name)
    if expected is None:
        raise ArchiveDigestError(
            f"{zip_path.name}: no entry in {archive_digest_sidecar_path(zip_path.parent)}; "
            "refusing to use unchecked archive bytes"
        )
    return expected


def verify_zip_digest(zip_path: Path, expected_sha256: str) -> None:
    """Verify the cached zip before any member is decompressed or parsed."""
    actual = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    if actual != expected_sha256:
        raise ArchiveDigestError(
            f"{zip_path}: sha256 {actual} does not match sidecar digest {expected_sha256}; "
            "refusing to read members"
        )


# ---------------------------------------------------------------------------
# Reading archived products
# ---------------------------------------------------------------------------


def iem_member_to_product_text(member_bytes: bytes) -> str:
    """Frame an IEM AFOS zip member as the parser's expected transmission.

    ``check_structural_allowlist`` expects line 0 to be the blank transmission
    leader and line 1 to be the WMO transmission sequence. An IEM member
    starts directly at the sequence line, so exactly one newline is prepended.

    The real sequence is PRESERVED. ``settlement_alignment_study``'s
    ``split_iem_afos_products`` rewrites it to ``000``; that predates the
    widened structural gate (``cli_parse.check_structural_allowlist`` now
    accepts 1-6 digits) and it destroys provenance. Nothing else is altered,
    so ``sha256`` of the original member bytes stays meaningful.
    """
    return "\n" + member_bytes.decode("utf-8")


def iem_product_id(member_name: str, product_text: str) -> str:
    """The IEM product identifier, e.g. ``202604240617-KOKX-CDUS41-CLINYC``.

    Built from the member name's issuance stamp plus the WMO abbreviated
    heading and AWIPS PIL carried in the product itself. IEM assigns no UUID;
    this is the archive's own stable handle for the transmission.
    """
    stamp_match = _MEMBER_STAMP_RE.search(member_name)
    if stamp_match is None:
        raise ArchiveRefusalError(
            f"member name {member_name!r} carries no _YYYYMMDDHHMM.txt issuance stamp"
        )
    lines = product_text.split("\n")
    if len(lines) < 4:
        raise ArchiveRefusalError(f"member {member_name!r} is too short to carry a WMO header")
    heading = _WMO_HEADING_RE.match(lines[2].strip())
    if heading is None:
        raise ArchiveRefusalError(
            f"member {member_name!r} line 3 is not a WMO abbreviated heading: {lines[2]!r}"
        )
    pil = lines[3].strip()
    return f"{stamp_match.group('stamp')}-{heading.group('office')}-{heading.group('ttaaii')}-{pil}"


def wmo_transmission_sequence(product_text: str, member_name: str) -> str:
    """Return the real WMO transmission sequence preserved from the archive."""
    lines = product_text.split("\n")
    if len(lines) < 2:
        raise ArchiveRefusalError(f"member {member_name!r} is too short to carry a WMO sequence")
    return lines[1].strip()


@dataclass(frozen=True, slots=True)
class ArchiveIssuance:
    """One archived CLI transmission, parsed and provenance-stamped."""

    station: str
    city: str
    climate_day: dt.date
    issuance: str
    tmax_f: int | None
    tmin_f: int | None
    tavg_f: int | None
    tmax_flag: str | None
    issued_at_utc: dt.datetime
    wmo_transmission_sequence: str
    wmo_bbb: str | None
    is_correction_bbb: bool
    correction_text_evidence: bool
    product_id: str
    raw_sha256: str
    source_zip: str
    source_member: str

    @property
    def is_final(self) -> bool:
        return self.issuance == "FINAL"


@dataclass(frozen=True, slots=True)
class ArchiveRefusal:
    """A product the archive held that this build refused to admit."""

    city: str
    source_zip: str
    source_member: str
    error_type: str
    message: str


def issuance_from_member(
    *,
    city: str,
    site: SettlementSite,
    member_bytes: bytes,
    member_name: str,
    source_zip: str,
    expected_sha256: str | None = None,
) -> ArchiveIssuance:
    """Parse one archive member into an :class:`ArchiveIssuance`.

    ``sha256`` is computed over the VERBATIM member bytes and, when
    ``expected_sha256`` is supplied, verified BEFORE the parsed value is
    allowed to exist -- the skill's "verify the digest before any later
    settlement use" rule, applied at the point of use rather than trusted.
    """
    digest = hashlib.sha256(member_bytes).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ArchiveDigestError(
            f"{source_zip}#{member_name}: sha256 {digest} does not match the expected "
            f"{expected_sha256}; refusing to use these bytes"
        )

    try:
        product_text = iem_member_to_product_text(member_bytes)
    except UnicodeDecodeError as exc:
        raise ArchiveRefusalError(f"{source_zip}#{member_name}: undecodable bytes: {exc}") from exc

    try:
        parsed = parse_cli_product(
            product_text,
            cli_location=site.cli_location,
            body_header_regex=site.body_header_regex,
        )
        issuance = classify_issuance(product_text)
    except (CliParseError, CliSanityError, ClassificationError) as exc:
        raise ArchiveRefusalError(
            f"{source_zip}#{member_name}: {type(exc).__name__}: {exc}"
        ) from exc

    issued_at = issue_utc_from_iem_filename(member_name) or parse_issued_at(product_text)
    if issued_at is None:
        raise ArchiveRefusalError(
            f"{source_zip}#{member_name}: no issuance instant in the member name or the "
            "product's ISSUED line"
        )

    return ArchiveIssuance(
        station=site.cli_location,
        city=city,
        climate_day=parsed.summary_date,
        issuance=issuance,
        tmax_f=parsed.tmax.value_f,
        tmin_f=parsed.tmin.value_f,
        tavg_f=parsed.tavg.value_f,
        tmax_flag=None if parsed.tmax.sentinel == "NONE" else parsed.tmax.sentinel,
        issued_at_utc=issued_at,
        wmo_transmission_sequence=wmo_transmission_sequence(product_text, member_name),
        wmo_bbb=parsed.wmo_bbb,
        is_correction_bbb=parsed.is_correction_bbb,
        correction_text_evidence=has_correction_evidence(product_text),
        product_id=iem_product_id(member_name, product_text),
        raw_sha256=digest,
        source_zip=source_zip,
        source_member=member_name,
    )


def read_window_issuances(
    *,
    zip_path: Path,
    city: str,
    site: SettlementSite,
    expected_zip_sha256: str | None = None,
) -> tuple[tuple[ArchiveIssuance, ...], tuple[ArchiveRefusal, ...]]:
    """Read every member of one cached AFOS zip, read-only.

    Refusals are COLLECTED, never swallowed: each one is returned so the
    coverage report can count it and name the member it came from.

    Iteration is over ``infolist()``, NOT ``namelist()``. The IEM archives
    carry DUPLICATE member names -- 21 of them across the held corpus -- where
    two distinct transmissions landed in the same PIL-and-minute filename.
    ``ZipFile.read(name)`` resolves a duplicated name to the LAST entry only,
    so a name-keyed read silently discards one of the two products (and reads
    the survivor twice). Reading each ``ZipInfo`` directly sees both; the
    digest dedupe then collapses them only if their bytes are genuinely equal.
    """
    issuances: list[ArchiveIssuance] = []
    refusals: list[ArchiveRefusal] = []
    if expected_zip_sha256 is not None:
        verify_zip_digest(zip_path, expected_zip_sha256)
    try:
        archive = ZipFile(zip_path)
    except BadZipFile as exc:
        raise ArchiveCoverageError(f"{zip_path}: not a readable zip archive: {exc}") from exc
    with archive:
        for info in sorted(archive.infolist(), key=lambda item: item.filename):
            member_name = info.filename
            try:
                _check_archive_member_safety(info)
                member_bytes = archive.read(info)
                issuances.append(
                    issuance_from_member(
                        city=city,
                        site=site,
                        member_bytes=member_bytes,
                        member_name=member_name,
                        source_zip=zip_path.name,
                    )
                )
            except SettlementTruthError as exc:
                refusals.append(
                    ArchiveRefusal(
                        city=city,
                        source_zip=zip_path.name,
                        source_member=member_name,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    )
                )
    return tuple(issuances), tuple(refusals)


def _check_archive_member_safety(info: Any) -> None:
    """Refuse hostile zip members before decompression."""
    if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
        raise ArchiveMemberSafetyError(
            f"{info.filename}: decompressed size {info.file_size} exceeds "
            f"{MAX_ARCHIVE_MEMBER_BYTES} byte cap"
        )
    if info.file_size == 0:
        return
    if info.compress_size <= 0:
        raise ArchiveMemberSafetyError(
            f"{info.filename}: compressed size {info.compress_size} cannot be ratio-checked"
        )
    ratio = info.file_size / info.compress_size
    if ratio > MAX_ARCHIVE_COMPRESSION_RATIO:
        raise ArchiveMemberSafetyError(
            f"{info.filename}: compression ratio {ratio:.1f} exceeds "
            f"{MAX_ARCHIVE_COMPRESSION_RATIO:.1f} cap"
        )


# ---------------------------------------------------------------------------
# Settlement-truth rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SettlementTruthRow:
    """One ``(station, climate_day)`` settlement-truth record."""

    station: str
    city: str
    climate_day: dt.date
    status: str
    is_final: bool
    tmax_f: int | None
    tmin_f: int | None
    tavg_f: int | None
    tmax_flag: str | None
    had_correction: bool
    preliminary_tmax_f: int | None
    preliminary_differed: bool | None
    preliminary_delta_f: int | None
    total_issuance_count: int
    final_issuance_count: int
    final_tmax_revised: bool
    final_is_correction_bbb: bool
    correction_text_evidence: bool
    revision_seq: int | None
    wmo_transmission_sequence: str | None
    wmo_bbb: str | None
    product_id: str | None
    raw_sha256: str | None
    issued_at_utc: dt.datetime | None
    source_zip: str | None
    source_member: str | None
    within_expected_window: bool
    interior_bucket_lower_even_f: int | None
    interior_bucket_upper_even_f: int | None
    interior_bucket_slug_even: str | None
    interior_bucket_lower_odd_f: int | None
    interior_bucket_upper_odd_f: int | None
    interior_bucket_slug_odd: str | None
    settlement_grade_within_window: bool
    settlement_grade_including_spillover: bool

    @property
    def settlement_grade(self) -> bool:
        """Settlement-grade within the declared archive window."""
        return self.settlement_grade_within_window


def _issuance_order(issuance: ArchiveIssuance) -> tuple[dt.datetime, str, int]:
    return issuance.issued_at_utc, issuance.product_id, int(issuance.wmo_transmission_sequence)


def _dedupe_by_digest(issuances: Sequence[ArchiveIssuance]) -> tuple[ArchiveIssuance, ...]:
    """Dedupe on ``sha256(raw_text)``, never on the product identifier.

    IEM re-transmissions of identical text get a new stamp and therefore a new
    product id, so keying on the id would count one transmission twice. A
    CORRECTION carries different text, hashes differently, and survives.
    """
    seen: dict[str, ArchiveIssuance] = {}
    for issuance in sorted(issuances, key=_issuance_order):
        seen.setdefault(issuance.raw_sha256, issuance)
    return tuple(sorted(seen.values(), key=_issuance_order))


def _empty_row(
    *, station: str, city: str, climate_day: dt.date, within: bool
) -> SettlementTruthRow:
    return SettlementTruthRow(
        station=station,
        city=city,
        climate_day=climate_day,
        status=STATUS_NO_PRODUCT,
        is_final=False,
        tmax_f=None,
        tmin_f=None,
        tavg_f=None,
        tmax_flag=None,
        had_correction=False,
        preliminary_tmax_f=None,
        preliminary_differed=None,
        preliminary_delta_f=None,
        total_issuance_count=0,
        final_issuance_count=0,
        final_tmax_revised=False,
        final_is_correction_bbb=False,
        correction_text_evidence=False,
        revision_seq=None,
        wmo_transmission_sequence=None,
        wmo_bbb=None,
        product_id=None,
        raw_sha256=None,
        issued_at_utc=None,
        source_zip=None,
        source_member=None,
        within_expected_window=within,
        interior_bucket_lower_even_f=None,
        interior_bucket_upper_even_f=None,
        interior_bucket_slug_even=None,
        interior_bucket_lower_odd_f=None,
        interior_bucket_upper_odd_f=None,
        interior_bucket_slug_odd=None,
        settlement_grade_within_window=False,
        settlement_grade_including_spillover=False,
    )


def _selection_refusal(
    *, city: str, source_zip: str, source_member: str, message: str
) -> ArchiveRefusal:
    return ArchiveRefusal(
        city=city,
        source_zip=source_zip,
        source_member=source_member,
        error_type=ArchiveSelectionError.__name__,
        message=message,
    )


def _ambiguous_final_refusal(
    *, city: str, climate_day: dt.date, finals: Sequence[ArchiveIssuance]
) -> ArchiveRefusal | None:
    by_identity: dict[tuple[dt.datetime, str, str], list[ArchiveIssuance]] = defaultdict(list)
    for issuance in finals:
        by_identity[
            (issuance.issued_at_utc, issuance.product_id, issuance.wmo_transmission_sequence)
        ].append(issuance)

    for tied in by_identity.values():
        tmax_values = {issuance.tmax_f for issuance in tied}
        if len(tmax_values) <= 1:
            continue
        first = tied[0]
        members = ",".join(sorted({issuance.source_member for issuance in tied}))
        digests = ",".join(sorted(issuance.raw_sha256 for issuance in tied))
        return _selection_refusal(
            city=city,
            source_zip=first.source_zip,
            source_member=members,
            message=(
                f"{city} {climate_day.isoformat()}: differing final tmax values "
                f"{sorted(tmax_values, key=str)} share "
                f"issued_at={first.issued_at_utc.isoformat()}, "
                f"product_id={first.product_id}, wmo_transmission_sequence="
                f"{first.wmo_transmission_sequence}; raw_sha256={digests}; refusing to select"
            ),
        )
    return None


def _build_day_row(
    *,
    station: str,
    city: str,
    climate_day: dt.date,
    day_issuances: Sequence[ArchiveIssuance],
    within: bool,
    selection_refusals: list[ArchiveRefusal] | None = None,
) -> SettlementTruthRow:
    ordered = _dedupe_by_digest(day_issuances)
    finals = tuple(issuance for issuance in ordered if issuance.is_final)
    preliminaries = tuple(issuance for issuance in ordered if not issuance.is_final)

    # The preliminary that mattered: the last one issued BEFORE the first
    # final, mirroring `preliminary_final_revision_rate_study.select_revision_pair`.
    if finals:
        before_final = tuple(
            issuance
            for issuance in preliminaries
            if issuance.issued_at_utc < finals[0].issued_at_utc
        )
    else:
        before_final = preliminaries
    preliminary = before_final[-1] if before_final else None

    ambiguous_refusal = _ambiguous_final_refusal(city=city, climate_day=climate_day, finals=finals)
    if ambiguous_refusal is not None:
        if selection_refusals is not None:
            selection_refusals.append(ambiguous_refusal)
        selected = None
        status = STATUS_AMBIGUOUS_FINAL
    elif not finals:
        selected = None
        status = STATUS_PRELIMINARY_ONLY
    else:
        # Latest final wins: a CCA/CCB correction is issued after the final it
        # supersedes, which is exactly the supersession rule in
        # `breezy.domain.selection` (is_final, then time, then revision).
        selected = finals[-1]
        status = STATUS_FINAL if selected.tmax_f is not None else STATUS_FINAL_TMAX_SENTINEL

    final_tmax_values = {issuance.tmax_f for issuance in finals}
    final_tmax_revised = len(final_tmax_values) > 1

    tmax_f = selected.tmax_f if selected is not None else None
    preliminary_tmax_f = preliminary.tmax_f if preliminary is not None else None
    preliminary_differed: bool | None = None
    preliminary_delta_f: int | None = None
    if preliminary_tmax_f is not None and tmax_f is not None:
        preliminary_differed = preliminary_tmax_f != tmax_f
        preliminary_delta_f = preliminary_tmax_f - tmax_f

    even_bucket = None if tmax_f is None else interior_bucket(tmax_f, anchor_parity=0)
    odd_bucket = None if tmax_f is None else interior_bucket(tmax_f, anchor_parity=1)
    even_lower, even_upper = even_bucket if even_bucket is not None else (None, None)
    odd_lower, odd_upper = odd_bucket if odd_bucket is not None else (None, None)

    revision_seq = None
    if selected is not None:
        revision_seq = ordered.index(selected) + 1
    settlement_grade_including_spillover = status == STATUS_FINAL and tmax_f is not None
    settlement_grade_within_window = settlement_grade_including_spillover and within

    return SettlementTruthRow(
        station=station,
        city=city,
        climate_day=climate_day,
        status=status,
        is_final=selected is not None,
        tmax_f=tmax_f,
        tmin_f=selected.tmin_f if selected is not None else None,
        tavg_f=selected.tavg_f if selected is not None else None,
        tmax_flag=selected.tmax_flag if selected is not None else None,
        had_correction=bool(
            final_tmax_revised or (selected is not None and selected.is_correction_bbb)
        ),
        preliminary_tmax_f=preliminary_tmax_f,
        preliminary_differed=preliminary_differed,
        preliminary_delta_f=preliminary_delta_f,
        total_issuance_count=len(ordered),
        final_issuance_count=len(finals),
        final_tmax_revised=final_tmax_revised,
        final_is_correction_bbb=bool(selected is not None and selected.is_correction_bbb),
        correction_text_evidence=any(issuance.correction_text_evidence for issuance in ordered),
        revision_seq=revision_seq,
        wmo_transmission_sequence=(
            selected.wmo_transmission_sequence if selected is not None else None
        ),
        wmo_bbb=selected.wmo_bbb if selected is not None else None,
        product_id=selected.product_id if selected is not None else None,
        raw_sha256=selected.raw_sha256 if selected is not None else None,
        issued_at_utc=selected.issued_at_utc if selected is not None else None,
        source_zip=selected.source_zip if selected is not None else None,
        source_member=selected.source_member if selected is not None else None,
        within_expected_window=within,
        interior_bucket_lower_even_f=even_lower,
        interior_bucket_upper_even_f=even_upper,
        interior_bucket_slug_even=None if even_lower is None else interior_bucket_slug(even_lower),
        interior_bucket_lower_odd_f=odd_lower,
        interior_bucket_upper_odd_f=odd_upper,
        interior_bucket_slug_odd=None if odd_lower is None else interior_bucket_slug(odd_lower),
        settlement_grade_within_window=settlement_grade_within_window,
        settlement_grade_including_spillover=settlement_grade_including_spillover,
    )


def build_truth_rows(
    *,
    city: str,
    station: str,
    issuances: Iterable[ArchiveIssuance],
    expected_days: Iterable[dt.date],
    selection_refusals: list[ArchiveRefusal] | None = None,
) -> tuple[SettlementTruthRow, ...]:
    """Assemble the per-day settlement-truth rows for one station.

    Every expected day yields a row even when the archive holds nothing for
    it: a missing day is DATA, reported as ``NO_PRODUCT``, never a silent
    absence. Days observed outside the expected grid are also emitted, flagged
    ``within_expected_window=False``.
    """
    by_day: dict[dt.date, list[ArchiveIssuance]] = defaultdict(list)
    for issuance in issuances:
        if issuance.station != station:
            raise SettlementTruthError(
                f"issuance for station {issuance.station!r} passed to a {station!r} build; "
                "station substitution is prohibited"
            )
        by_day[issuance.climate_day].append(issuance)

    expected = frozenset(expected_days)
    rows = [
        _build_day_row(
            station=station,
            city=city,
            climate_day=day,
            day_issuances=by_day[day],
            within=day in expected,
            selection_refusals=selection_refusals,
        )
        if day in by_day
        else _empty_row(station=station, city=city, climate_day=day, within=day in expected)
        for day in sorted(expected | frozenset(by_day))
    ]
    return tuple(rows)


# ---------------------------------------------------------------------------
# Coverage and correction statistics
# ---------------------------------------------------------------------------


def coverage_summary(rows: Sequence[SettlementTruthRow]) -> dict[str, Any]:
    """Honest coverage and correction accounting for a set of rows."""
    status_counts: Counter[str] = Counter(row.status for row in rows)
    settlement_grade_within_window = [row for row in rows if row.settlement_grade_within_window]
    settlement_grade_including_spillover = [
        row for row in rows if row.settlement_grade_including_spillover
    ]
    outside_expected_window_settlement_grade = [
        row
        for row in settlement_grade_including_spillover
        if not row.within_expected_window
    ]
    missing = [
        row.climate_day.isoformat()
        for row in rows
        if row.status == STATUS_NO_PRODUCT and row.within_expected_window
    ]
    preliminary_only = [
        row.climate_day.isoformat() for row in rows if row.status == STATUS_PRELIMINARY_ONLY
    ]
    comparable_within_window = [
        row for row in settlement_grade_within_window if row.preliminary_differed is not None
    ]
    revised_within_window = [row for row in comparable_within_window if row.preliminary_differed]
    comparable_including_spillover = [
        row
        for row in settlement_grade_including_spillover
        if row.preliminary_differed is not None
    ]
    revised_including_spillover = [
        row for row in comparable_including_spillover if row.preliminary_differed
    ]
    days = [row.climate_day for row in rows]
    return {
        "rows": len(rows),
        "settlement_grade_rows_within_window": len(settlement_grade_within_window),
        "settlement_grade_rows_including_spillover": len(settlement_grade_including_spillover),
        "outside_expected_window_settlement_grade_rows": len(
            outside_expected_window_settlement_grade
        ),
        "status_counts": dict(status_counts),
        "first_climate_day": min(days).isoformat() if days else None,
        "last_climate_day": max(days).isoformat() if days else None,
        "missing_days": missing,
        "missing_day_count": len(missing),
        "preliminary_only_days": preliminary_only,
        "preliminary_only_count": len(preliminary_only),
        "preliminary_final_comparable_within_window": len(comparable_within_window),
        "preliminary_final_revised_within_window": len(revised_within_window),
        "preliminary_final_revision_rate_within_window": (
            len(revised_within_window) / len(comparable_within_window)
            if comparable_within_window
            else None
        ),
        "preliminary_final_comparable_including_spillover": len(
            comparable_including_spillover
        ),
        "preliminary_final_revised_including_spillover": len(
            revised_including_spillover
        ),
        "preliminary_final_revision_rate_including_spillover": (
            len(revised_including_spillover) / len(comparable_including_spillover)
            if comparable_including_spillover
            else None
        ),
        "preliminary_revision_delta_histogram_within_window": dict(
            sorted(
                Counter(row.preliminary_delta_f for row in revised_within_window).items(),
                key=str,
            )
        ),
        "preliminary_revision_delta_histogram_including_spillover": dict(
            sorted(
                Counter(row.preliminary_delta_f for row in revised_including_spillover).items(),
                key=str,
            )
        ),
        "final_correction_bbb_rows": sum(1 for row in rows if row.final_is_correction_bbb),
        "final_tmax_revised_rows": sum(1 for row in rows if row.final_tmax_revised),
        "had_correction_rows": sum(1 for row in rows if row.had_correction),
        "correction_text_evidence_rows": sum(1 for row in rows if row.correction_text_evidence),
        "multi_final_days": sum(1 for row in rows if row.final_issuance_count > 1),
        "outside_expected_window_rows": sum(1 for row in rows if not row.within_expected_window),
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_ARROW_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("station", pa.string(), nullable=False),
        pa.field("city", pa.string(), nullable=False),
        pa.field("climate_day", pa.date32(), nullable=False),
        pa.field("status", pa.string(), nullable=False),
        pa.field("is_final", pa.bool_(), nullable=False),
        pa.field("tmax_f", pa.int32(), nullable=True),
        pa.field("tmin_f", pa.int32(), nullable=True),
        pa.field("tavg_f", pa.int32(), nullable=True),
        pa.field("tmax_flag", pa.string(), nullable=True),
        pa.field("had_correction", pa.bool_(), nullable=False),
        pa.field("preliminary_tmax_f", pa.int32(), nullable=True),
        pa.field("preliminary_differed", pa.bool_(), nullable=True),
        pa.field("preliminary_delta_f", pa.int32(), nullable=True),
        pa.field("total_issuance_count", pa.int32(), nullable=False),
        pa.field("final_issuance_count", pa.int32(), nullable=False),
        pa.field("final_tmax_revised", pa.bool_(), nullable=False),
        pa.field("final_is_correction_bbb", pa.bool_(), nullable=False),
        pa.field("correction_text_evidence", pa.bool_(), nullable=False),
        pa.field("revision_seq", pa.int32(), nullable=True),
        pa.field("wmo_transmission_sequence", pa.string(), nullable=True),
        pa.field("wmo_bbb", pa.string(), nullable=True),
        pa.field("product_id", pa.string(), nullable=True),
        pa.field("raw_sha256", pa.string(), nullable=True),
        pa.field("issued_at_utc", pa.timestamp("ns", tz="UTC"), nullable=True),
        pa.field("source_zip", pa.string(), nullable=True),
        pa.field("source_member", pa.string(), nullable=True),
        pa.field("within_expected_window", pa.bool_(), nullable=False),
        pa.field("interior_bucket_lower_even_f", pa.int32(), nullable=True),
        pa.field("interior_bucket_upper_even_f", pa.int32(), nullable=True),
        pa.field("interior_bucket_slug_even", pa.string(), nullable=True),
        pa.field("interior_bucket_lower_odd_f", pa.int32(), nullable=True),
        pa.field("interior_bucket_upper_odd_f", pa.int32(), nullable=True),
        pa.field("interior_bucket_slug_odd", pa.string(), nullable=True),
        pa.field("settlement_grade_within_window", pa.bool_(), nullable=False),
        pa.field("settlement_grade_including_spillover", pa.bool_(), nullable=False),
    ]
)

_CSV_FIELDS: Final[tuple[str, ...]] = tuple(field.name for field in _ARROW_SCHEMA)

_REFUSAL_FIELDS: Final[tuple[str, ...]] = (
    "city",
    "source_zip",
    "source_member",
    "error_type",
    "message",
)


def _field_mapping(record: object, names: Sequence[str]) -> dict[str, Any]:
    """Read named fields off a frozen record by attribute access.

    `dataclasses.asdict` is deliberately NOT used anywhere in this module.
    `tests/unit/test_polymarket_us_credential_serialization.py` keeps a closed
    allowlist of `asdict` call sites because `asdict` deep-copies field values
    and bypasses hand-written `__repr__`/`__reduce__` hooks; a shallow
    `getattr` read carries none of that hazard and needs no waiver.
    """
    return {name: getattr(record, name) for name in names}


def rows_to_table(rows: Sequence[SettlementTruthRow]) -> pa.Table:
    columns: dict[str, list[Any]] = {name: [] for name in _CSV_FIELDS}
    for row in rows:
        for name in _CSV_FIELDS:
            columns[name].append(getattr(row, name))
    return pa.table(columns, schema=_ARROW_SCHEMA)


def write_dataset(rows: Sequence[SettlementTruthRow], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / "settlement_truth.parquet"
    csv_path = output_dir / "settlement_truth.csv"
    pq.write_table(rows_to_table(rows), parquet_path)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_CSV_FIELDS))
        writer.writeheader()
        for row in rows:
            record = _field_mapping(row, _CSV_FIELDS)
            writer.writerow(
                {
                    name: (
                        ""
                        if record[name] is None
                        else record[name].isoformat()
                        if isinstance(record[name], dt.date | dt.datetime)
                        else record[name]
                    )
                    for name in _CSV_FIELDS
                }
            )
    return {"parquet": parquet_path, "csv": csv_path}


def write_refusals(refusals: Sequence[ArchiveRefusal], output_dir: Path) -> Path:
    path = output_dir / "refused_products.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(_REFUSAL_FIELDS))
        writer.writeheader()
        for refusal in refusals:
            writer.writerow(_field_mapping(refusal, _REFUSAL_FIELDS))
    return path


def validate_requested_cities(
    cities: Sequence[str] | None, registry: Any
) -> tuple[str, ...] | None:
    """Validate --city values against the registry before any output write."""
    if cities is None:
        return None
    known = {city for venue, city in registry.pairs() if venue == VENUE}
    requested = tuple(dict.fromkeys(cities))
    unknown = sorted(set(requested) - known)
    if unknown:
        raise SettlementTruthError(
            f"unknown --city value(s) for {VENUE}: {', '.join(unknown)}; "
            f"known cities: {', '.join(sorted(known))}"
        )
    if not requested:
        raise SettlementTruthError("empty --city selection; refusing to write an empty dataset")
    return requested


def _path_within_or_equal(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_output_dir(output_dir: Path) -> Path:
    """Refuse writes into the live catalog or read-only archive cache root."""
    resolved = output_dir.expanduser().resolve(strict=False)
    live_catalog = DEFAULT_LIVE_CATALOG_DIR.expanduser().resolve(strict=False)
    archive_root = DEFAULT_ARCHIVE_ROOT_DIR.expanduser().resolve(strict=False)
    if _path_within_or_equal(resolved, live_catalog):
        raise SettlementTruthError(
            f"--output-dir {resolved} is inside the live catalog {live_catalog}; refusing"
        )
    if _path_within_or_equal(resolved, archive_root):
        raise SettlementTruthError(
            f"--output-dir {resolved} is inside the archive cache {archive_root}; refusing"
        )
    return resolved


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", default=str(DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--city", action="append", default=None)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    registry = default_registry()
    requested_cities = validate_requested_cities(args.city, registry)
    output_dir = validate_output_dir(Path(args.output_dir))
    cache_dir = require_settlement_alignment_cache_dir(args.cache_dir)
    archive_digests = read_archive_digest_sidecar(cache_dir)
    windows = archive_windows(requested_cities)
    if not windows:
        raise SettlementTruthError(
            "selected cities produced zero archive windows; refusing to write"
        )
    by_city: dict[str, list[ArchiveWindow]] = defaultdict(list)
    for window in windows:
        by_city[window.city].append(window)

    all_rows: list[SettlementTruthRow] = []
    all_refusals: list[ArchiveRefusal] = []
    per_city: dict[str, dict[str, Any]] = {}

    for city, city_windows in sorted(by_city.items()):
        site = registry.settlement_site(VENUE, city)
        issuances: list[ArchiveIssuance] = []
        expected_days: set[dt.date] = set()
        window_report: list[dict[str, Any]] = []
        for window in sorted(city_windows, key=lambda item: item.start):
            zip_path = window_zip_path(cache_dir, window)
            expected_sha256 = expected_zip_digest(zip_path, archive_digests)
            window_issuances, window_refusals = read_window_issuances(
                zip_path=zip_path,
                city=city,
                site=site,
                expected_zip_sha256=expected_sha256,
            )
            issuances.extend(window_issuances)
            all_refusals.extend(window_refusals)
            expected_days.update(window.days())
            window_report.append(
                {
                    "start": window.start.isoformat(),
                    "end": window.end.isoformat(),
                    "zip": zip_path.name,
                    "members": len(window_issuances) + len(window_refusals),
                    "admitted": len(window_issuances),
                    "refused": len(window_refusals),
                }
            )

        rows = build_truth_rows(
            city=city,
            station=site.cli_location,
            issuances=issuances,
            expected_days=sorted(expected_days),
            selection_refusals=all_refusals,
        )
        all_rows.extend(rows)
        summary = coverage_summary(rows)
        summary["windows"] = window_report
        summary["station"] = site.cli_location
        per_city[city] = summary

    all_rows.sort(key=lambda row: (row.station, row.climate_day))
    paths = write_dataset(all_rows, output_dir)
    refusal_path = write_refusals(all_refusals, output_dir)

    report: dict[str, Any] = {
        "generated_at_utc": dt.datetime.now(tz=dt.UTC).isoformat(),
        "settlement_predicate": SETTLEMENT_PREDICATE_STATEMENT,
        "settlement_predicate_evidence": SETTLEMENT_PREDICATE_EVIDENCE,
        "cache_dir": str(cache_dir),
        "output_dir": str(output_dir),
        "overall": coverage_summary(all_rows),
        "per_city": per_city,
        "refused_products": len(all_refusals),
    }
    coverage_path = output_dir / "coverage.json"
    coverage_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(report["overall"], indent=2, sort_keys=True))
    print(f"parquet: {paths['parquet']}")
    print(f"csv:     {paths['csv']}")
    print(f"coverage:{coverage_path}")
    print(f"refusals:{refusal_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
