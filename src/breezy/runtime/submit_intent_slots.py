"""Pure codec for the EXEC-PAR slot table and the breaker record (WP2; inert).

This module only parses and renders JSON documents. It imports nothing from
``submit_intent`` (which re-exports its public names) and performs no I/O.

Slot table at ``CURRENT_INTENT_KEY``:

* v1: the single intent record, optionally carrying an extra ``cooloff`` key
  (v1 readers ignore unknown keys);
* v2: ``{"v":2,"slots":{<key>:<record>},"raw_slots":{<key>:<base64>},
  "cooloff":{<slug>:<until_ns>}}``. ``raw_slots`` holds the canonical JSON
  text of unreadable slots as strict base64.

Every structural defect raises :class:`SlotTableError`; the caller maps it to
whole-table corruption (fail closed).
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Final

__all__ = [
    "BREAKER_ABSENT_GRACE_NS",
    "BREAKER_FUTURE_SKEW_NS",
    "BREAKER_HEARTBEAT_MAX_AGE_NS",
    "BREAKER_KEY",
    "BREAKER_RESOLVER_PASS_MAX_AGE_NS",
    "DEFAULT_COOLOFF_NS",
    "BreakerRecord",
    "ParsedTable",
    "SlotTableError",
    "canonical_text",
    "decode_raw_slot",
    "encode_breaker",
    "encode_raw_slot",
    "encode_v2",
    "is_valid_slot_key",
    "parse_breaker",
    "parse_table",
]

BREAKER_KEY: Final[str] = "exec/polymarket_us/intent/breaker"
_NS_PER_SECOND: Final[int] = 1_000_000_000
#: Plan r5 section 3.6: heartbeat age 60 s, resolver-pass age 600 s (2 x the
#: 300 s backoff cap), absent-record grace 60 s after boot; cool-off 120 s.
BREAKER_HEARTBEAT_MAX_AGE_NS: Final[int] = 60 * _NS_PER_SECOND
BREAKER_RESOLVER_PASS_MAX_AGE_NS: Final[int] = 600 * _NS_PER_SECOND
BREAKER_ABSENT_GRACE_NS: Final[int] = 60 * _NS_PER_SECOND
#: A heartbeat or resolver-pass stamp further than this ahead of "now" is a
#: clock fault, not freshness, and counts as stale.
BREAKER_FUTURE_SKEW_NS: Final[int] = 5 * _NS_PER_SECOND
DEFAULT_COOLOFF_NS: Final[int] = 120 * _NS_PER_SECOND

_SLOT_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^(?:[A-Za-z0-9._-]{1,128}|\?:[0-9a-f]{32})$")


class SlotTableError(Exception):
    """A slot table or breaker document is structurally invalid."""


@dataclass(frozen=True, slots=True)
class ParsedTable:
    """A structurally valid table, records still undecoded.

    ``version`` 1: ``v1_record`` is the intent payload. Version 2:
    ``slots`` maps key to the raw JSON value and ``raw_slots`` maps key to the
    decoded canonical bytes of an unreadable slot.
    """

    version: int
    cooloff: tuple[tuple[str, int], ...]
    v1_record: dict[str, object] | None = None
    slots: tuple[tuple[str, object], ...] = ()
    raw_slots: tuple[tuple[str, bytes], ...] = ()


def canonical_text(value: object) -> bytes:
    """The canonical JSON text of ``value`` (sorted keys), UTF-8 encoded."""
    return json.dumps(value, sort_keys=True).encode("utf-8")


def encode_raw_slot(text: bytes) -> str:
    return base64.b64encode(text).decode("ascii")


def decode_raw_slot(value: object) -> bytes:
    """Strict base64 decode; anything else is table corruption."""
    if not isinstance(value, str):
        raise SlotTableError("raw slot is not a string")
    try:
        return base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error):
        raise SlotTableError("raw slot is not strict base64") from None


def _json_object(raw: bytes) -> dict[str, object]:
    try:
        decoded: object = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise SlotTableError("not UTF-8 JSON") from None
    if not isinstance(decoded, dict):
        raise SlotTableError("not a JSON object")
    return decoded


def _int_of(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SlotTableError("not an integer")
    return value


def _parse_cooloff(value: object) -> tuple[tuple[str, int], ...]:
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise SlotTableError("cooloff is not an object")
    pairs: list[tuple[str, int]] = []
    for slug, until in value.items():
        if not isinstance(slug, str) or not slug:
            raise SlotTableError("cooloff slug")
        pairs.append((slug, _int_of(until)))
    return tuple(sorted(pairs))


def is_valid_slot_key(key: str) -> bool:
    """Whether ``key`` matches ``[A-Za-z0-9._-]{1,128}|\\?:[0-9a-f]{32}`` (no path characters)."""
    return _SLOT_KEY_RE.fullmatch(key) is not None


def _check_key(key: str) -> str:
    if not is_valid_slot_key(key):
        raise SlotTableError("slot key")
    return key


def parse_table(raw: bytes) -> ParsedTable:
    """Parse a v1 or v2 table document or raise :class:`SlotTableError`."""
    payload = _json_object(raw)
    version = _int_of(payload.get("v"))
    cooloff = _parse_cooloff(payload.get("cooloff"))
    if version == 1:
        return ParsedTable(version=1, cooloff=cooloff, v1_record=payload)
    if version != 2:
        raise SlotTableError("unknown table version")
    slots_in = payload.get("slots")
    raw_in = payload.get("raw_slots")
    if not isinstance(slots_in, dict) or not isinstance(raw_in, dict):
        raise SlotTableError("v2 shape")
    slots = tuple(sorted((_check_key(k), v) for k, v in slots_in.items()))
    raw_slots = tuple(sorted((_check_key(k), decode_raw_slot(v)) for k, v in raw_in.items()))
    keys = [k for k, _ in slots] + [k for k, _ in raw_slots]
    if len(set(keys)) != len(keys) or not keys:
        raise SlotTableError("v2 keys")
    return ParsedTable(version=2, cooloff=cooloff, slots=slots, raw_slots=raw_slots)


def encode_v2(
    slots: dict[str, dict[str, object]],
    raw_slots: dict[str, bytes],
    cooloff: dict[str, int],
) -> bytes:
    """Render a v2 table. Unreadable slots are re-emitted byte-identically."""
    document: dict[str, object] = {
        "v": 2,
        "slots": slots,
        "raw_slots": {key: encode_raw_slot(text) for key, text in raw_slots.items()},
        "cooloff": cooloff,
    }
    return canonical_text(document)


@dataclass(frozen=True, slots=True)
class BreakerRecord:
    """``{"v":1,"halted":null|{"reason","ts_ns"},"hb_ns","resolver_pass_ns"}``."""

    halted_reason: str | None
    halted_ts_ns: int | None
    hb_ns: int
    resolver_pass_ns: int
    #: M3: a failed force-K1 flag write. Encoded only when True, so records
    #: that never set it stay byte-identical and old records decode False.
    flag_write_failed: bool = False

    @property
    def is_halted(self) -> bool:
        return self.halted_reason is not None


def encode_breaker(record: BreakerRecord) -> bytes:
    halted: dict[str, object] | None = None
    if record.halted_reason is not None:
        halted = {"reason": record.halted_reason, "ts_ns": record.halted_ts_ns}
    document: dict[str, object] = {
        "v": 1,
        "halted": halted,
        "hb_ns": record.hb_ns,
        "resolver_pass_ns": record.resolver_pass_ns,
    }
    if record.flag_write_failed:
        document["flag_write_failed"] = True
    return canonical_text(document)


def parse_breaker(raw: bytes) -> BreakerRecord:
    payload = _json_object(raw)
    if _int_of(payload.get("v")) != 1:
        raise SlotTableError("breaker version")
    halted = payload.get("halted")
    reason: str | None = None
    ts_ns: int | None = None
    if halted is not None:
        if not isinstance(halted, dict):
            raise SlotTableError("breaker halted")
        raw_reason = halted.get("reason")
        if not isinstance(raw_reason, str) or not raw_reason:
            raise SlotTableError("breaker halted reason")
        reason = raw_reason
        ts_ns = _int_of(halted.get("ts_ns"))
    flag_failed = payload.get("flag_write_failed", False)
    if not isinstance(flag_failed, bool):
        raise SlotTableError("breaker flag_write_failed")
    return BreakerRecord(
        halted_reason=reason,
        halted_ts_ns=ts_ns,
        hb_ns=_int_of(payload.get("hb_ns")),
        resolver_pass_ns=_int_of(payload.get("resolver_pass_ns")),
        flag_write_failed=flag_failed,
    )
