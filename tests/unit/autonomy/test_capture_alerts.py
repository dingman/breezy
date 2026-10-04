"""AUT-1 WP1 part A: the closed alert-event catalogue (r8 section 3.13 rules; r12 section 3.16)."""

import re

import pytest

from breezy.persistence.autonomy.capture_alerts import (
    ABANDONED_EVENT_PREFIX,
    CAPTURE_ALERT_EVENTS,
    CAPTURE_ALERT_SEVERITIES,
    CAPTURE_EVENT_RE,
    HEALED_EVENT_PREFIX,
    abandoned_alert_event,
    heal_alert_event,
    is_capture_alert_event,
)

SHA = "0123456789abcdef" * 4
OTHER_SHA = "fedcba9876543210" * 4
NAME_MAX = 255

#: r12 section 3.16 "Removed with r8's watch and watchdog": none may be in the closed tuple.
REMOVED = (
    "RECORDER_HUNG",
    "RECORDER_STALLED",
    "RECORDER_WRITER_STALL",
    "RECORDER_UNHEALED",
    "RECORDER_INACTIVE",
    "RECORDER_HEARTBEAT_NEVER_SEEN",
    "RECORDER_BYTES_STALE_AWAITING_HEARTBEAT",
    "NWS_INGEST_HUNG",
    "NWS_GATE_NOT_OPEN",
    "CAPTURE_WATCH_STALE",
    "CAPTURE_WRITE_FAILED",
    "CAPTURE_BYTE_CAP",
    "CAPTURE_PAYLOAD_COLLISION",
    "RECORDER_WATCHDOG_KILL",
    "RECORDER_WATCHDOG_STORM",
)


def _regex_form(event: str) -> str:
    """The regex check upper-cases the hex only; the sent string keeps lowercase hex."""
    return event.upper()


def test_capture_alert_events_are_closed_and_filename_safe() -> None:
    """Every event is a bare token matching ``CAPTURE_EVENT_RE`` and safe in
    ``<ts_ns>_<event>.json``; the tuple is closed (no duplicates, no removed r8 event).

    MUTATION: adding ``"CAPTURE/BAD"`` or a lowercase token fails the regex assertion.
    """
    assert CAPTURE_EVENT_RE.pattern == r"^[A-Z0-9_]{1,96}$"
    assert isinstance(CAPTURE_ALERT_EVENTS, tuple)
    assert len(set(CAPTURE_ALERT_EVENTS)) == len(CAPTURE_ALERT_EVENTS)
    for event in (*CAPTURE_ALERT_EVENTS, heal_alert_event(SHA), abandoned_alert_event(SHA)):
        assert CAPTURE_EVENT_RE.match(_regex_form(event)), event
        assert "/" not in event and "." not in event and not re.search(r"\s", event)
        assert len(f"{2**63}_{event}.json") < NAME_MAX
    for removed in REMOVED:
        assert removed not in CAPTURE_ALERT_EVENTS
    for kept in (
        "CAPTURE_PUBLISH_FAILED",
        "CAPTURE_STREAM_TYPE_FLAT",
        "CAPTURE_EPOCH_UNREADABLE",
        "CAPTURE_REFUSED",
        "NBP_CYCLE_MISSED",
        "CAPTURE_DRILL_SKIPPED",
    ):
        assert kept in CAPTURE_ALERT_EVENTS


def test_every_event_has_a_severity() -> None:
    assert set(CAPTURE_ALERT_SEVERITIES) == set(CAPTURE_ALERT_EVENTS)
    assert set(CAPTURE_ALERT_SEVERITIES.values()) <= {"CRITICAL", "WARNING", "INFO"}
    assert CAPTURE_ALERT_SEVERITIES["CAPTURE_VENUE_SILENT"] == "WARNING"
    assert CAPTURE_ALERT_SEVERITIES["CAPTURE_PUBLISH_FAILED"] == "CRITICAL"


def test_heal_alert_event_is_prefix_plus_64_lowercase_hex() -> None:
    event = heal_alert_event(SHA)
    assert event == f"CAPTURE_HEALED_{SHA}"
    assert HEALED_EVENT_PREFIX == "CAPTURE_HEALED_"
    assert len(event) == 79
    assert CAPTURE_EVENT_RE.match(event.upper())


@pytest.mark.parametrize(
    "bad",
    ["", SHA[:63], SHA + "0", SHA.upper(), "g" * 64, "../" + SHA[3:], None, 7],
)
def test_heal_and_abandoned_events_refuse_a_malformed_sha(bad: object) -> None:
    with pytest.raises(ValueError):
        heal_alert_event(bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        abandoned_alert_event(bad)  # type: ignore[arg-type]


def test_abandoned_alert_event_carries_heal_sha_and_never_matches_another_heal() -> None:
    event = abandoned_alert_event(SHA)
    assert event == f"CAPTURE_HEAL_ALERT_ABANDONED_{SHA}"
    assert ABANDONED_EVENT_PREFIX == "CAPTURE_HEAL_ALERT_ABANDONED_"
    assert len(event) == 93
    assert abandoned_alert_event(OTHER_SHA) != event
    assert heal_alert_event(SHA) != event


def test_is_capture_alert_event_accepts_closed_and_prefixed_only() -> None:
    assert is_capture_alert_event("CAPTURE_PUBLISH_FAILED")
    assert is_capture_alert_event(heal_alert_event(SHA))
    assert is_capture_alert_event(abandoned_alert_event(OTHER_SHA))
    assert not is_capture_alert_event("CAPTURE_WRITE_FAILED")
    assert not is_capture_alert_event(f"CAPTURE_HEALED_{SHA.upper()}")
    assert not is_capture_alert_event("CAPTURE_HEALED_" + SHA[:10])
    assert not is_capture_alert_event("")
