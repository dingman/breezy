"""Streaming readers for the LAMP monthly ``.gz`` and yearly ``.tar`` archives (H2).

Split out of :mod:`breezy.ingest.mdl_lamp_transport`, which owns the hosts, the
URL gate, the HTTP client and every ``TransportError`` subclass (R18). This
module defines NO ``TransportError`` subclass: where it must refuse a
container it calls the ``refuse`` factory the transport injected (its
``LampArchiveIntegrityError``), and its size/decode/timeout refusals reuse
the existing :mod:`breezy.ingest.http` errors.

Invariants:

* the tar is read in stream mode ``r|`` only; ``extract``/``extractall`` are
  never called and no output path exists, so a member name is only a label;
* only plain regular members (``REGTYPE``/``AREGTYPE``) are accepted -- no
  symlink, hardlink, directory, device, sparse or contiguous member -- and
  traversal, absolute, NUL, backslash and over-long names are refused;
* compressed bytes, member count, member size, per-member and total
  DECOMPRESSED bytes, line length and wall-clock time are all capped, and
  decompressed bytes are counted as they stream (``zlib`` ``max_length``);
* a stream is single-use, and ``sha256`` is released only after the whole
  stream was consumed, drained and validated -- never after an error.
"""

from __future__ import annotations

import codecs
import hashlib
import re
import tarfile
import zlib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final

from breezy.ingest.http import (
    DecodeError,
    OversizeBodyError,
    TransportTimeoutError,
)

__all__ = [
    "DEFAULT_MAX_LINE_CHARS",
    "LampArchiveLimits",
    "LampMonthStream",
    "LampTarMember",
    "LampYearStream",
    "open_month_stream",
    "open_year_stream",
]

#: LAMP lines are well under 200 characters; a line this long is hostile input.
DEFAULT_MAX_LINE_CHARS: Final[int] = 16 * 1024
_CHUNK_SIZE: Final[int] = 64 * 1024
_DECOMPRESS_STEP: Final[int] = 64 * 1024
_MAX_MEMBER_NAME_BYTES: Final[int] = 256
_MAX_PAX_HEADER_BYTES: Final[int] = 64 * 1024
_PLAIN_MEMBER_TYPES: Final[frozenset[bytes]] = frozenset({tarfile.REGTYPE, tarfile.AREGTYPE})

#: ``KNYC   GFS LAMP GUIDANCE  10/06/2026  0130 UTC`` (A0). The station token is
#: not assumed to be an ICAO call sign.
_STATION_HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?P<station>[A-Z0-9]{3,6})\s+(?:GFS\s+)?LAMP\s+GUIDANCE\b"
)

Refuse = Callable[[str], Exception]


@dataclass(frozen=True, slots=True)
class LampArchiveLimits:
    """Byte, count, line and time caps for one streamed archive method."""

    max_compressed_bytes: int
    max_members: int
    max_member_bytes: int
    max_member_decompressed_bytes: int
    max_total_decompressed_bytes: int
    max_line_chars: int = DEFAULT_MAX_LINE_CHARS
    max_wall_seconds: float = 3600.0


class _CountingReader:
    """A file-like over response chunks: caps, digests and counts as it reads."""

    def __init__(
        self,
        chunks: Iterator[bytes],
        *,
        max_bytes: int,
        label: str,
        max_wall_seconds: float,
        monotonic: Callable[[], float],
    ) -> None:
        self._chunks = chunks
        self._max_bytes = max_bytes
        self._label = label
        self._max_wall_seconds = max_wall_seconds
        self._monotonic = monotonic
        self._started_at = monotonic()
        self._buffer = bytearray()
        self._digest = hashlib.sha256()
        self.total = 0
        self.exhausted = False

    def _pull(self) -> bool:
        if self.exhausted:
            return False
        if self._monotonic() - self._started_at > self._max_wall_seconds:
            raise TransportTimeoutError(
                f"Download from {self._label} exceeded its "
                f"{self._max_wall_seconds}-second deadline."
            )
        try:
            chunk = next(self._chunks)
        except StopIteration:
            self.exhausted = True
            return False
        self.total += len(chunk)
        if self.total > self._max_bytes:
            raise OversizeBodyError(
                f"Download from {self._label} exceeded the {self._max_bytes}-byte compressed cap."
            )
        self._digest.update(chunk)
        self._buffer += chunk
        return True

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            raise ValueError("an unbounded read is refused; the stream is size-capped")
        while len(self._buffer) < size and self._pull():
            pass
        taken = bytes(self._buffer[:size])
        del self._buffer[:size]
        return taken

    def drain(self) -> None:
        while self._pull():
            self._buffer.clear()

    def chunks(self, size: int = _CHUNK_SIZE) -> Iterator[bytes]:
        while chunk := self.read(size):
            yield chunk

    def digest(self) -> str:
        return self._digest.hexdigest()


class _DecompressedBudget:
    """Per-member and total decompressed-byte counter, shared across members."""

    def __init__(self, limits: LampArchiveLimits, *, label: str) -> None:
        self._limits = limits
        self._label = label
        self._member = 0
        self._total = 0

    def begin_member(self) -> None:
        self._member = 0

    def add(self, count: int) -> None:
        self._member += count
        self._total += count
        if self._member > self._limits.max_member_decompressed_bytes:
            raise OversizeBodyError(
                f"A member of {self._label} decompressed past the "
                f"{self._limits.max_member_decompressed_bytes}-byte per-member cap."
            )
        if self._total > self._limits.max_total_decompressed_bytes:
            raise OversizeBodyError(
                f"{self._label} decompressed past the "
                f"{self._limits.max_total_decompressed_bytes}-byte total cap."
            )


def _gunzip(chunks: Iterable[bytes], *, budget: _DecompressedBudget, label: str) -> Iterator[bytes]:
    """Incrementally gunzip (concatenated members allowed), counting output."""
    inflater = zlib.decompressobj(zlib.MAX_WBITS | 16)
    fed = False
    try:
        for chunk in chunks:
            data = chunk
            fed = fed or bool(chunk)
            while True:
                out = inflater.decompress(data, _DECOMPRESS_STEP)
                budget.add(len(out))
                if out:
                    yield out
                if inflater.eof:
                    data = inflater.unused_data
                    inflater = zlib.decompressobj(zlib.MAX_WBITS | 16)
                    fed = bool(data)
                    if not data:
                        break
                    continue
                data = inflater.unconsumed_tail
                if not data and len(out) < _DECOMPRESS_STEP:
                    break
    except zlib.error as exc:
        raise DecodeError(f"Invalid gzip data in {label}: {exc}") from exc
    if fed:
        raise DecodeError(f"Truncated gzip data in {label}.")


def _decode_lines(chunks: Iterable[bytes], *, label: str, max_line_chars: int) -> Iterator[str]:
    """Strict UTF-8 line splitter that refuses any line over ``max_line_chars``."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
    pending = ""

    def too_long() -> OversizeBodyError:
        return OversizeBodyError(f"{label} has a line over the {max_line_chars}-character cap.")

    try:
        for chunk in chunks:
            parts = (pending + decoder.decode(chunk)).splitlines(keepends=True)
            pending = parts.pop() if parts and not parts[-1].endswith(("\n", "\r")) else ""
            if len(pending) > max_line_chars:
                raise too_long()
            for line in parts:
                if len(line) > max_line_chars:
                    raise too_long()
                yield line
        pending += decoder.decode(b"", final=True)
    except UnicodeDecodeError as exc:
        raise DecodeError(f"{label} is not valid UTF-8: {exc}") from exc
    if len(pending) > max_line_chars:
        raise too_long()
    if pending:
        yield pending


def _filter_stations(lines: Iterable[str], stations: frozenset[str] | None) -> Iterator[str]:
    """Keep only the wanted stations' blocks; the discard happens per line."""
    if stations is None:
        yield from lines
        return
    keep = False
    for line in lines:
        match = _STATION_HEADER_RE.match(line)
        if match is not None:
            keep = match.group("station") in stations
        if keep:
            yield line


class _SingleUse:
    """``begin`` may be called once; ``sha256`` needs ``finish`` and no error."""

    def __init__(self, reader: _CountingReader, what: str) -> None:
        self._reader = reader
        self._what = what
        self._started = False
        self._complete = False

    def _begin(self) -> None:
        if self._started:
            raise RuntimeError(f"a {self._what} stream is single-use")
        self._started = True

    def _finish(self) -> None:
        self._reader.drain()
        self._complete = True

    @property
    def sha256(self) -> str:
        """Digest of the COMPRESSED bytes; only after a fully validated pass."""
        if not self._complete:
            raise RuntimeError("sha256 is unavailable until the stream is fully consumed")
        return self._reader.digest()


class LampMonthStream(_SingleUse):
    """A monthly ``.gz`` as station-filterable text lines."""

    def __init__(
        self,
        *,
        reader: _CountingReader,
        limits: LampArchiveLimits,
        source_host: str,
        last_modified: str | None,
        url_label: str,
        url: str,
    ) -> None:
        super().__init__(reader, "month")
        self._limits = limits
        self._label = url_label
        self.source_host = source_host
        self.last_modified = last_modified
        self.url = url

    def lines(self, stations: frozenset[str] | None = None) -> Iterator[str]:
        self._begin()
        return self._iterate(stations)

    def _iterate(self, stations: frozenset[str] | None) -> Iterator[str]:
        budget = _DecompressedBudget(self._limits, label=self._label)
        budget.begin_member()
        text = _decode_lines(
            _gunzip(self._reader.chunks(), budget=budget, label=self._label),
            label=self._label,
            max_line_chars=self._limits.max_line_chars,
        )
        yield from _filter_stations(text, stations)
        self._finish()


class LampTarMember:
    """One plain tar member (a monthly gz). ``name`` is a label, never a path."""

    def __init__(
        self,
        *,
        name: str,
        size: int,
        read: Callable[[int], bytes],
        owner: LampYearStream,
        refuse: Refuse,
    ) -> None:
        self.name = name
        self.size = size
        self._read = read
        self._owner = owner
        self._refuse = refuse
        self._used = False

    def lines(self, stations: frozenset[str] | None = None) -> Iterator[str]:
        if self._used:
            raise RuntimeError("a tar member's lines are single-use")
        if self._owner.current_member is not self:
            raise RuntimeError("this tar member is stale: the stream has advanced past it")
        self._used = True
        return self._iterate(stations)

    def _raw(self) -> Iterator[bytes]:
        while True:
            try:
                chunk = self._read(_CHUNK_SIZE)
            except tarfile.TarError as exc:
                raise self._refuse(
                    f"Truncated or malformed tar member {self.name!r}: {exc}"
                ) from exc
            if not chunk:
                return
            yield chunk

    def _iterate(self, stations: frozenset[str] | None) -> Iterator[str]:
        label = f"tar member {self.name!r}"
        budget = self._owner.budget
        budget.begin_member()
        text = _decode_lines(
            _gunzip(self._raw(), budget=budget, label=label),
            label=label,
            max_line_chars=self._owner.limits.max_line_chars,
        )
        yield from _filter_stations(text, stations)


def _unsafe_member_name(name: str) -> bool:
    return (
        not name
        or "\x00" in name
        or "\\" in name
        or name.startswith("/")
        or ".." in PurePosixPath(name).parts
    )


class LampYearStream(_SingleUse):
    """A yearly tar as a one-pass sequence of members (mode ``r|``)."""

    def __init__(
        self,
        *,
        reader: _CountingReader,
        limits: LampArchiveLimits,
        source_host: str,
        last_modified: str | None,
        url_label: str,
        url: str,
        refuse: Refuse,
    ) -> None:
        super().__init__(reader, "year")
        self.limits = limits
        self.budget = _DecompressedBudget(limits, label=url_label)
        self.current_member: LampTarMember | None = None
        self._label = url_label
        self._refuse = refuse
        self.source_host = source_host
        self.last_modified = last_modified
        self.url = url

    def members(self) -> Iterator[LampTarMember]:
        """Yield members in stream order; consume each before advancing."""
        self._begin()
        return self._iterate()

    def _iterate(self) -> Iterator[LampTarMember]:
        try:
            with tarfile.open(fileobj=self._reader, mode="r|") as archive:  # type: ignore[call-overload]
                for count, member in enumerate(archive, start=1):
                    self.current_member = self._checked_member(archive, member, count)
                    yield self.current_member
        except tarfile.TarError as exc:
            raise self._refuse(f"Malformed tar from {self._label}: {exc}") from exc
        self.current_member = None
        self._finish()

    def _checked_member(
        self, archive: tarfile.TarFile, member: tarfile.TarInfo, count: int
    ) -> LampTarMember:
        if count > self.limits.max_members:
            raise OversizeBodyError(
                f"{self._label} has more than {self.limits.max_members} members."
            )
        if _unsafe_member_name(member.name):
            raise self._refuse(f"Unsafe tar member name {member.name!r} in {self._label}.")
        if len(member.name.encode("utf-8", "surrogateescape")) > _MAX_MEMBER_NAME_BYTES:
            raise self._refuse(
                f"Tar member name over {_MAX_MEMBER_NAME_BYTES} bytes in {self._label}."
            )
        pax_bytes = sum(len(key) + len(value) for key, value in member.pax_headers.items())
        if pax_bytes > _MAX_PAX_HEADER_BYTES:
            raise self._refuse(
                f"Tar member {member.name!r} has over {_MAX_PAX_HEADER_BYTES} bytes of pax headers."
            )
        if member.type not in _PLAIN_MEMBER_TYPES:
            raise self._refuse(
                f"Non-plain tar member {member.name!r} (type {member.type!r}) in {self._label}; "
                "only regular files are accepted (no link, directory, device, sparse)."
            )
        if member.size > self.limits.max_member_bytes:
            raise OversizeBodyError(
                f"Tar member {member.name!r} is {member.size} bytes, over the "
                f"{self.limits.max_member_bytes}-byte member cap."
            )
        handle = archive.extractfile(member)
        if handle is None:  # pragma: no cover - plain members always have a handle
            raise self._refuse(f"Unreadable tar member {member.name!r}.")
        return LampTarMember(
            name=member.name,
            size=member.size,
            read=handle.read,
            owner=self,
            refuse=self._refuse,
        )


def open_month_stream(
    chunks: Iterator[bytes],
    *,
    limits: LampArchiveLimits,
    monotonic: Callable[[], float],
    source_host: str,
    last_modified: str | None,
    url: str,
    url_label: str,
) -> LampMonthStream:
    reader = _CountingReader(
        chunks,
        max_bytes=limits.max_compressed_bytes,
        label=url_label,
        max_wall_seconds=limits.max_wall_seconds,
        monotonic=monotonic,
    )
    return LampMonthStream(
        reader=reader,
        limits=limits,
        source_host=source_host,
        last_modified=last_modified,
        url_label=url_label,
        url=url,
    )


def open_year_stream(
    chunks: Iterator[bytes],
    *,
    limits: LampArchiveLimits,
    monotonic: Callable[[], float],
    source_host: str,
    last_modified: str | None,
    url: str,
    url_label: str,
    refuse: Refuse,
) -> LampYearStream:
    reader = _CountingReader(
        chunks,
        max_bytes=limits.max_compressed_bytes,
        label=url_label,
        max_wall_seconds=limits.max_wall_seconds,
        monotonic=monotonic,
    )
    return LampYearStream(
        reader=reader,
        limits=limits,
        source_host=source_host,
        last_modified=last_modified,
        url_label=url_label,
        url=url,
        refuse=refuse,
    )
