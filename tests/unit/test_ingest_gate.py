"""Tests for the per-site settlement gate (src/breezy/ingest/gate.py).

Governing rule under test: enrichment degrades, settlement halts. See
docs/plans/WEATHER_INGESTION_PROPOSAL.md §6 for the failure table this file
pins, and §0 decision 5 for the ACIS auto-resume rule.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

import pytest

from breezy.ingest.gate import (
    _GLOBAL_KEY,
    CachePersistenceConfig,
    CachePersistenceMisconfiguredError,
    GateBlockedError,
    GateReason,
    GateState,
    InMemoryStateStore,
    SettlementGate,
    StateStore,
    _site_key,
    assert_cache_persistence_configured,
    cache_persistence_config_from,
)

VENUE = "polymarket_us"
CITY = "NYC"
OTHER_CITY = "SFO"


class _FakeClock:
    """Injected monotonic-ish clock: nanoseconds, manually advanced."""

    def __init__(self, start_ns: int = 0) -> None:
        self._now_ns = start_ns

    def __call__(self) -> int:
        return self._now_ns

    def advance(self, delta_ns: int) -> None:
        self._now_ns += delta_ns


def _gate(store: InMemoryStateStore | None = None, clock: _FakeClock | None = None) -> tuple[SettlementGate, InMemoryStateStore, _FakeClock]:
    store = store if store is not None else InMemoryStateStore()
    clock = clock if clock is not None else _FakeClock()
    return SettlementGate(store=store, clock=clock), store, clock


# ---------------------------------------------------------------------------
# Default-BLOCKED / persistence
# ---------------------------------------------------------------------------


def test_default_state_before_any_poll_is_blocked() -> None:
    gate, _, _ = _gate()
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.NEVER_POLLED


def test_restart_with_empty_store_still_yields_blocked() -> None:
    gate1, _store, clock = _gate()
    gate1.status(VENUE, CITY)  # touch, but never a successful poll

    gate2, _, _ = _gate(store=InMemoryStateStore(), clock=clock)
    assert gate2.status(VENUE, CITY).state is GateState.BLOCKED


def test_restart_with_persisted_store_restores_prior_blocked_state() -> None:
    gate1, store, clock = _gate()
    gate1.record_successful_poll(VENUE, CITY)
    gate1.record_parser_failure(VENUE, CITY, detail="unparseable headline")
    assert gate1.status(VENUE, CITY).state is GateState.BLOCKED

    gate2, _, _ = _gate(store=store, clock=clock)
    status = gate2.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.PARSER_FAILURE


def test_restart_with_persisted_store_restores_prior_open_state() -> None:
    gate1, store, clock = _gate()
    gate1.record_successful_poll(VENUE, CITY)
    assert gate1.status(VENUE, CITY).state is GateState.OPEN

    gate2, _, _ = _gate(store=store, clock=clock)
    assert gate2.status(VENUE, CITY).state is GateState.OPEN


def test_sites_are_independent() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    assert gate.status(VENUE, CITY).state is GateState.OPEN
    assert gate.status(VENUE, OTHER_CITY).state is GateState.BLOCKED


# ---------------------------------------------------------------------------
# require_open re-checked at use time
# ---------------------------------------------------------------------------


def test_require_open_raises_when_blocked() -> None:
    gate, _, _ = _gate()
    with pytest.raises(GateBlockedError):
        gate.require_open(VENUE, CITY)


def test_require_open_raises_when_degraded() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_transient_failure(VENUE, CITY)
    gate.record_transient_failure(VENUE, CITY)
    gate.record_transient_failure(VENUE, CITY)
    assert gate.status(VENUE, CITY).state is GateState.DEGRADED
    with pytest.raises(GateBlockedError):
        gate.require_open(VENUE, CITY)


def test_require_open_passes_when_open() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.require_open(VENUE, CITY)  # must not raise


def test_require_open_error_carries_status() -> None:
    gate, _, _ = _gate()
    with pytest.raises(GateBlockedError) as exc_info:
        gate.require_open(VENUE, CITY)
    assert exc_info.value.status.venue == VENUE
    assert exc_info.value.status.city == CITY
    assert exc_info.value.status.state is GateState.BLOCKED


def test_require_open_is_rechecked_not_cached_after_block() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.require_open(VENUE, CITY)
    gate.record_parser_failure(VENUE, CITY, detail="bad")
    with pytest.raises(GateBlockedError):
        gate.require_open(VENUE, CITY)


# ---------------------------------------------------------------------------
# Transient failures: 429 / 5xx / timeout — DEGRADED after 3, BLOCKED at window
# ---------------------------------------------------------------------------


def test_transient_failures_below_threshold_stay_open() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_transient_failure(VENUE, CITY)
    gate.record_transient_failure(VENUE, CITY)
    assert gate.status(VENUE, CITY).state is GateState.OPEN


def test_transient_failures_degrade_after_three() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    for _ in range(3):
        gate.record_transient_failure(VENUE, CITY)
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.DEGRADED
    assert status.reason is GateReason.TRANSIENT_FAILURE


def test_transient_failures_block_when_final_window_elapses() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    for _ in range(3):
        gate.record_transient_failure(VENUE, CITY)
    gate.record_transient_failure(VENUE, CITY, final_window_elapsed=True)
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.TRANSIENT_WINDOW_ELAPSED


def test_successful_poll_clears_transient_failure_state() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    for _ in range(4):
        gate.record_transient_failure(VENUE, CITY)
    gate.record_successful_poll(VENUE, CITY)
    assert gate.status(VENUE, CITY).state is GateState.OPEN


# ---------------------------------------------------------------------------
# 403 — classified by the gate itself from persisted, cross-restart history
# plus a caller-reported cross-site burst signal (never a process-lifetime
# flag, and never a caller-supplied is_ua_trap bool -- see the redesign
# note on record_forbidden_403). UA-trap blocks ALL sites; abuse degrades
# only the offending one.
# ---------------------------------------------------------------------------


def test_403_before_any_site_has_ever_succeeded_is_classified_as_ua_trap() -> None:
    """Cold start: no site tracked by this gate has EVER had a persisted
    successful poll, so a 403 is presumed to be the User-Agent itself being
    rejected -- blocking every site, including one never even seen before.
    """
    gate, _, _ = _gate()
    gate.record_forbidden_403(VENUE, CITY, detail="403 on first-ever request")
    assert gate.status(VENUE, CITY).state is GateState.BLOCKED
    assert gate.status(VENUE, OTHER_CITY).state is GateState.BLOCKED
    assert gate.status(VENUE, "MIA").state is GateState.BLOCKED
    assert gate.status(VENUE, CITY).reason is GateReason.UA_TRAP_403


def test_403_after_any_site_has_succeeded_degrades_only_the_offending_site() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_successful_poll(VENUE, OTHER_CITY)
    gate.record_forbidden_403(VENUE, CITY, detail="abuse block")
    assert gate.status(VENUE, CITY).state is GateState.DEGRADED
    assert gate.status(VENUE, OTHER_CITY).state is GateState.OPEN


def test_prior_success_is_read_from_persisted_cross_restart_state() -> None:
    """A fresh SettlementGate instance (process restart) backed by a store
    that already recorded a successful poll in a PRIOR instance must not
    re-treat the next 403 as a cold start -- 'prior success' is the
    persisted global flag, never a process-lifetime bool that resets on
    every restart.
    """
    gate1, store, clock = _gate()
    gate1.record_successful_poll(VENUE, CITY)
    gate1.record_successful_poll(VENUE, OTHER_CITY)

    gate2, _, _ = _gate(store=store, clock=clock)
    gate2.record_forbidden_403(VENUE, OTHER_CITY, detail="403 in the new process")
    assert gate2.status(VENUE, OTHER_CITY).state is GateState.DEGRADED
    assert gate2.status(VENUE, CITY).state is GateState.OPEN


def test_cross_site_burst_rearms_ua_trap_detection_even_after_prior_success() -> None:
    """A genuine UA-trap onset mid-session (mailbox unreachable, NWS
    blocklists the UA) must not be misclassified as independent per-site
    abuse blocks just because some site succeeded earlier in this process.
    A caller-reported burst of same-cause 403s across multiple cities
    re-arms trap detection regardless of any single site's own history.
    """
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_successful_poll(VENUE, OTHER_CITY)
    gate.record_forbidden_403(
        VENUE, CITY, detail="403 burst detected across cities", cross_site_burst_detected=True
    )
    assert gate.status(VENUE, CITY).state is GateState.BLOCKED
    assert gate.status(VENUE, OTHER_CITY).state is GateState.BLOCKED
    assert gate.status(VENUE, "MIA").state is GateState.BLOCKED
    assert gate.status(VENUE, CITY).reason is GateReason.UA_TRAP_403


def test_restart_with_persisted_store_restores_ua_trap_global_block() -> None:
    gate1, store, clock = _gate()
    gate1.record_forbidden_403(VENUE, CITY, detail="cold-start 403")

    gate2, _, _ = _gate(store=store, clock=clock)
    status = gate2.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.UA_TRAP_403


def test_ua_trap_block_can_be_manually_cleared() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_forbidden_403(VENUE, CITY, detail="mid-session onset", cross_site_burst_detected=True)
    gate.acknowledge_ua_trap_resolved(detail="UA fixed and redeployed")
    assert gate.status(VENUE, CITY).state is GateState.OPEN


# ---------------------------------------------------------------------------
# Parser failure / sanity-bound violation / ambiguous headline / oversize
# ---------------------------------------------------------------------------


def test_parser_failure_blocks_site() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_parser_failure(VENUE, CITY, detail="CliParseError")
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.PARSER_FAILURE


def test_sanity_bound_violation_blocks_site() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_sanity_violation(VENUE, CITY, detail="tmax_f=250")
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.SANITY_VIOLATION


def test_ambiguous_headline_blocks_site() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_ambiguous_headline(VENUE, CITY, detail="no VALID TODAY line, no date")
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.AMBIGUOUS_HEADLINE


def test_oversize_body_or_parse_timeout_blocks_site() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_oversize_or_parse_timeout(VENUE, CITY, detail="body exceeded 128 KiB")
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.OVERSIZE_OR_PARSE_TIMEOUT


# ---------------------------------------------------------------------------
# Cross-check unavailable — DEGRADED, then BLOCKED inside the conflict window
# ---------------------------------------------------------------------------


def test_cross_check_unavailable_degrades_site() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_cross_check_unavailable(VENUE, CITY, detail="ACIS timeout")
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.DEGRADED
    assert status.reason is GateReason.CROSS_CHECK_UNAVAILABLE


def test_cross_check_unavailable_blocks_inside_conflict_window() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_cross_check_unavailable(VENUE, CITY, detail="ACIS timeout")
    gate.record_cross_check_unavailable(
        VENUE, CITY, detail="still down at review deadline", conflict_window_elapsed=True
    )
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.CROSS_CHECK_WINDOW_ELAPSED


def test_cross_check_available_resumes_site() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_cross_check_unavailable(VENUE, CITY, detail="ACIS timeout")
    gate.record_cross_check_available(VENUE, CITY)
    assert gate.status(VENUE, CITY).state is GateState.OPEN


# ---------------------------------------------------------------------------
# ACIS disagreement — halts the station, auto-resumes on agreement
# ---------------------------------------------------------------------------


def test_acis_disagreement_blocks_station() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_acis_disagreement(VENUE, CITY, detail="CLI=72 ACIS=68")
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.ACIS_DISAGREEMENT


def test_acis_agreement_auto_resumes_station() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_acis_disagreement(VENUE, CITY, detail="CLI=72 ACIS=68")
    gate.record_acis_agreement(VENUE, CITY, detail="revised ACIS=72")
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.OPEN
    assert status.reason is GateReason.ACIS_RESUMED


def test_successful_poll_does_not_clear_acis_disagreement() -> None:
    """ACIS resume is autonomous but requires explicit agreement -- a mere
    successful poll of the CLI product must not silently un-halt a station
    that ACIS still disagrees with.
    """
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_acis_disagreement(VENUE, CITY, detail="CLI=72 ACIS=68")
    gate.record_successful_poll(VENUE, CITY)
    assert gate.status(VENUE, CITY).state is GateState.BLOCKED


# ---------------------------------------------------------------------------
# Ingest task death
# ---------------------------------------------------------------------------


def test_ingest_task_death_blocks_site() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_task_death(VENUE, CITY, detail="unhandled exception in poll loop")
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.TASK_DEATH


def test_successful_poll_clears_task_death() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_task_death(VENUE, CITY, detail="died")
    gate.record_successful_poll(VENUE, CITY)
    assert gate.status(VENUE, CITY).state is GateState.OPEN


# ---------------------------------------------------------------------------
# Redirect integrity alarm (3xx) / client-error defect (400) -- site-scoped
# hard blocks, per coordinator ruling on §6 ambiguity 2.
# ---------------------------------------------------------------------------


def test_redirect_integrity_alarm_blocks_site() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_redirect_integrity_alarm(VENUE, CITY, detail="302 on /products/CLINYC")
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.REDIRECT_INTEGRITY_ALARM


def test_redirect_integrity_alarm_is_site_scoped_not_global() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_successful_poll(VENUE, OTHER_CITY)
    gate.record_redirect_integrity_alarm(VENUE, CITY, detail="302 on /products/CLINYC")
    assert gate.status(VENUE, CITY).state is GateState.BLOCKED
    assert gate.status(VENUE, OTHER_CITY).state is GateState.OPEN


def test_successful_poll_clears_redirect_integrity_alarm() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_redirect_integrity_alarm(VENUE, CITY, detail="302")
    gate.record_successful_poll(VENUE, CITY)
    assert gate.status(VENUE, CITY).state is GateState.OPEN


def test_client_error_defect_blocks_site() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_client_error_defect(VENUE, CITY, detail="400 malformed request")
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.CLIENT_ERROR_DEFECT


def test_client_error_defect_is_site_scoped_not_global() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_successful_poll(VENUE, OTHER_CITY)
    gate.record_client_error_defect(VENUE, CITY, detail="400 malformed request")
    assert gate.status(VENUE, CITY).state is GateState.BLOCKED
    assert gate.status(VENUE, OTHER_CITY).state is GateState.OPEN


def test_successful_poll_clears_client_error_defect() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_client_error_defect(VENUE, CITY, detail="400")
    gate.record_successful_poll(VENUE, CITY)
    assert gate.status(VENUE, CITY).state is GateState.OPEN


def test_restart_with_persisted_store_restores_redirect_integrity_alarm() -> None:
    gate1, store, clock = _gate()
    gate1.record_successful_poll(VENUE, CITY)
    gate1.record_redirect_integrity_alarm(VENUE, CITY, detail="302")

    gate2, _, _ = _gate(store=store, clock=clock)
    status = gate2.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.REDIRECT_INTEGRITY_ALARM


def test_restart_with_persisted_store_restores_client_error_defect() -> None:
    gate1, store, clock = _gate()
    gate1.record_successful_poll(VENUE, CITY)
    gate1.record_client_error_defect(VENUE, CITY, detail="400")

    gate2, _, _ = _gate(store=store, clock=clock)
    status = gate2.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.CLIENT_ERROR_DEFECT


# ---------------------------------------------------------------------------
# Final CLI overdue -- data completeness, distinct from liveness. A site
# that keeps polling cleanly (preliminaries) but never receives the final
# must NOT be cleared by record_successful_poll, or the block is laundered
# away on every successful preliminary poll.
# ---------------------------------------------------------------------------

CLIMATE_DAY_TODAY = "2026-08-21"
CLIMATE_DAY_YESTERDAY = "2026-08-20"


def test_final_overdue_blocks_site() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_final_overdue(VENUE, CITY, CLIMATE_DAY_TODAY, deadline_ns=28_800_000_000_000)
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.FINAL_CLI_OVERDUE


def test_final_overdue_is_logged_at_critical(caplog: pytest.LogCaptureFixture) -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    with caplog.at_level(logging.INFO, logger="breezy.ingest.gate"):
        gate.record_final_overdue(VENUE, CITY, CLIMATE_DAY_TODAY, deadline_ns=28_800_000_000_000)
    assert any(record.levelno == logging.CRITICAL for record in caplog.records)


def test_successful_poll_does_not_clear_final_overdue() -> None:
    """The core laundering guard: a site polling cleanly every five minutes
    (successful preliminary polls) but never receiving the final must stay
    BLOCKED past the deadline -- liveness is not data completeness.
    """
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_final_overdue(VENUE, CITY, CLIMATE_DAY_TODAY, deadline_ns=28_800_000_000_000)
    gate.record_successful_poll(VENUE, CITY)  # e.g. another clean preliminary poll
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED


def test_final_received_clears_overdue_block_for_matching_climate_day() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_final_overdue(VENUE, CITY, CLIMATE_DAY_TODAY, deadline_ns=28_800_000_000_000)
    status = gate.record_final_received(VENUE, CITY, CLIMATE_DAY_TODAY)
    assert status.state is GateState.OPEN
    assert status.reason is GateReason.FINAL_RECEIVED


def test_final_received_for_a_different_climate_day_does_not_clear_the_block() -> None:
    """A final arriving for yesterday must not clear an overdue block for
    today -- the block is keyed by the specific climate day, not just site.
    """
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_final_overdue(VENUE, CITY, CLIMATE_DAY_TODAY, deadline_ns=28_800_000_000_000)
    status = gate.record_final_received(VENUE, CITY, CLIMATE_DAY_YESTERDAY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.FINAL_CLI_OVERDUE


def test_final_received_is_a_noop_when_nothing_is_overdue() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    status = gate.record_final_received(VENUE, CITY, CLIMATE_DAY_TODAY)
    assert status.state is GateState.OPEN
    assert status.reason is GateReason.SUCCESSFUL_POLL


def test_final_overdue_is_site_scoped_not_global() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_successful_poll(VENUE, OTHER_CITY)
    gate.record_final_overdue(VENUE, CITY, CLIMATE_DAY_TODAY, deadline_ns=28_800_000_000_000)
    assert gate.status(VENUE, CITY).state is GateState.BLOCKED
    assert gate.status(VENUE, OTHER_CITY).state is GateState.OPEN


def test_restart_with_persisted_store_restores_final_overdue_block() -> None:
    gate1, store, clock = _gate()
    gate1.record_successful_poll(VENUE, CITY)
    gate1.record_final_overdue(VENUE, CITY, CLIMATE_DAY_TODAY, deadline_ns=28_800_000_000_000)

    gate2, _, _ = _gate(store=store, clock=clock)
    status = gate2.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.FINAL_CLI_OVERDUE


# ---------------------------------------------------------------------------
# Write integrity violation -- a non-empty WriteOutcome.skipped (full or
# partial) is a dedicated integrity event, not silence between a skipped
# write and an OPEN gate.
# ---------------------------------------------------------------------------


def test_write_integrity_violation_blocks_site() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_write_integrity_violation(VENUE, CITY, detail="1 of 2 records skipped")
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.WRITE_INTEGRITY_VIOLATION


def test_write_integrity_violation_is_logged_at_critical(caplog: pytest.LogCaptureFixture) -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    with caplog.at_level(logging.INFO, logger="breezy.ingest.gate"):
        gate.record_write_integrity_violation(VENUE, CITY, detail="skipped")
    assert any(record.levelno == logging.CRITICAL for record in caplog.records)


def test_successful_poll_clears_write_integrity_violation() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_write_integrity_violation(VENUE, CITY, detail="skipped")
    gate.record_successful_poll(VENUE, CITY)
    assert gate.status(VENUE, CITY).state is GateState.OPEN


def test_restart_with_persisted_store_restores_write_integrity_violation() -> None:
    gate1, store, clock = _gate()
    gate1.record_successful_poll(VENUE, CITY)
    gate1.record_write_integrity_violation(VENUE, CITY, detail="skipped")

    gate2, _, _ = _gate(store=store, clock=clock)
    status = gate2.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.WRITE_INTEGRITY_VIOLATION


# ---------------------------------------------------------------------------
# Transport integrity alarm -- a rejected Content-Encoding (decompression
# would desync the digest from the wire bytes) routes somewhere deliberate
# rather than falling through to generic task-death supervision.
# ---------------------------------------------------------------------------


def test_transport_integrity_alarm_blocks_site() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_transport_integrity_alarm(VENUE, CITY, detail="Content-Encoding: gzip rejected")
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.TRANSPORT_INTEGRITY_ALARM


def test_transport_integrity_alarm_is_logged_at_critical(caplog: pytest.LogCaptureFixture) -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    with caplog.at_level(logging.INFO, logger="breezy.ingest.gate"):
        gate.record_transport_integrity_alarm(VENUE, CITY, detail="bad encoding")
    assert any(record.levelno == logging.CRITICAL for record in caplog.records)


def test_successful_poll_clears_transport_integrity_alarm() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_transport_integrity_alarm(VENUE, CITY, detail="bad encoding")
    gate.record_successful_poll(VENUE, CITY)
    assert gate.status(VENUE, CITY).state is GateState.OPEN


def test_restart_with_persisted_store_restores_transport_integrity_alarm() -> None:
    gate1, store, clock = _gate()
    gate1.record_successful_poll(VENUE, CITY)
    gate1.record_transport_integrity_alarm(VENUE, CITY, detail="bad encoding")

    gate2, _, _ = _gate(store=store, clock=clock)
    status = gate2.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.TRANSPORT_INTEGRITY_ALARM


# ---------------------------------------------------------------------------
# Freshness watchdog — injected clock, never wall-clock
# ---------------------------------------------------------------------------


def test_freshness_watchdog_stays_open_before_degraded_threshold() -> None:
    gate, _, clock = _gate()
    gate.record_successful_poll(VENUE, CITY)
    clock.advance(1)
    status = gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000)
    assert status.state is GateState.OPEN


def test_freshness_watchdog_degrades_after_threshold() -> None:
    gate, _, clock = _gate()
    gate.record_successful_poll(VENUE, CITY)
    clock.advance(1_500)
    status = gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000)
    assert status.state is GateState.DEGRADED
    assert status.reason is GateReason.STALE_DEGRADED


def test_freshness_watchdog_blocks_after_final_threshold() -> None:
    gate, _, clock = _gate()
    gate.record_successful_poll(VENUE, CITY)
    clock.advance(2_500)
    status = gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.STALE_BLOCKED


def test_freshness_watchdog_full_escalation_sequence() -> None:
    gate, _, clock = _gate()
    gate.record_successful_poll(VENUE, CITY)

    clock.advance(500)
    assert gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000).state is GateState.OPEN

    clock.advance(600)  # total 1_100
    assert gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000).state is GateState.DEGRADED

    clock.advance(1_000)  # total 2_100
    assert gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000).state is GateState.BLOCKED


def test_freshness_watchdog_recovers_when_fresh_poll_lands() -> None:
    gate, _, clock = _gate()
    gate.record_successful_poll(VENUE, CITY)
    clock.advance(1_500)
    gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000)
    assert gate.status(VENUE, CITY).state is GateState.DEGRADED

    gate.record_successful_poll(VENUE, CITY)
    assert gate.status(VENUE, CITY).state is GateState.OPEN


def test_freshness_watchdog_is_a_noop_when_never_polled() -> None:
    gate, _, clock = _gate()
    clock.advance(10_000)
    status = gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.NEVER_POLLED


def test_freshness_watchdog_clears_stale_flags_once_fresh_again_without_explicit_poll_call() -> None:
    """Re-checking freshness after a poll already cleared staleness must not
    re-flag it, and must not emit a spurious transition when nothing changed.
    """
    gate, _, clock = _gate()
    gate.record_successful_poll(VENUE, CITY)
    clock.advance(1_500)
    gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000)
    assert gate.status(VENUE, CITY).state is GateState.DEGRADED

    # A fresh poll clears staleness; checking freshness again immediately
    # (elapsed=0) must observe OPEN and must not toggle anything further.
    gate.record_successful_poll(VENUE, CITY)
    status = gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000)
    assert status.state is GateState.OPEN


def test_freshness_watchdog_does_not_auto_clear_stale_flags_without_a_real_poll() -> None:
    """Widening the thresholds on a later check_freshness call must NOT, by
    itself, restore a site to OPEN. Freshness is defined by a recent
    successful poll -- there is no other legitimate recovery path.

    This pins the fix for a CRITICAL fail-open: the previous implementation
    cleared staleness (and logged it as GateReason.SUCCESSFUL_POLL --
    a poll that never happened) whenever the *current* elapsed time fell
    back under a threshold, without any new verified poll. That recovery
    branch is deleted entirely; only record_successful_poll may reopen a
    site.
    """
    gate, _, clock = _gate()
    gate.record_successful_poll(VENUE, CITY)
    clock.advance(1_500)
    gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000)
    assert gate.status(VENUE, CITY).state is GateState.DEGRADED

    status = gate.check_freshness(VENUE, CITY, degraded_after_ns=5_000, blocked_after_ns=10_000)
    assert status.state is GateState.DEGRADED
    assert status.reason is GateReason.STALE_DEGRADED


# ---------------------------------------------------------------------------
# Clock regression -- a non-monotonic clock is itself a safety event
# ---------------------------------------------------------------------------


def test_clock_regression_does_not_reopen_a_stale_blocked_site(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """CRITICAL fail-open regression test: a stale-BLOCKED site, re-checked
    after the clock has moved backward past the last successful poll, must
    never reach OPEN, and the audit log must never record a SUCCESSFUL_POLL
    that did not happen.
    """
    gate, _, clock = _gate()
    gate.record_successful_poll(VENUE, CITY)
    clock.advance(2_500)
    gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000)
    assert gate.status(VENUE, CITY).state is GateState.BLOCKED

    clock.advance(-5_000)  # clock steps backward past the original poll time
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="breezy.ingest.gate"):
        status = gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000)

    assert status.state is not GateState.OPEN
    assert status.state is GateState.BLOCKED
    assert status.reason is not GateReason.SUCCESSFUL_POLL
    assert not any("reason=successful_poll" in record.message for record in caplog.records)


def test_clock_regression_produces_dedicated_reason_and_blocks_site() -> None:
    gate, _, clock = _gate()
    gate.record_successful_poll(VENUE, CITY)
    clock.advance(-1)  # clock steps backward, even by a single nanosecond
    status = gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.CLOCK_REGRESSION


def test_clock_regression_is_logged_at_critical_severity(caplog: pytest.LogCaptureFixture) -> None:
    gate, _, clock = _gate()
    gate.record_successful_poll(VENUE, CITY)
    clock.advance(-1)
    with caplog.at_level(logging.INFO, logger="breezy.ingest.gate"):
        gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000)
    assert any(
        record.levelno == logging.CRITICAL and "clock_regression" in record.message
        for record in caplog.records
    )


def test_successful_poll_clears_clock_regression() -> None:
    gate, _, clock = _gate()
    gate.record_successful_poll(VENUE, CITY)
    clock.advance(-1)
    gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000)
    assert gate.status(VENUE, CITY).state is GateState.BLOCKED

    clock.advance(1_000)  # move forward past the original poll time again
    gate.record_successful_poll(VENUE, CITY)
    assert gate.status(VENUE, CITY).state is GateState.OPEN


# ---------------------------------------------------------------------------
# Persist-then-cache ordering -- the in-memory view must never advance
# ahead of the durable one
# ---------------------------------------------------------------------------


class _FailOnSetStore:
    """A StateStore whose `set()` starts succeeding, then raises from a
    chosen call onward -- used to prove a failed persist cannot leave the
    in-memory cache ahead of the (unwritten) durable state.
    """

    def __init__(self, *, fail_from_call: int) -> None:
        self._data: dict[str, bytes] = {}
        self._set_calls = 0
        self._fail_from_call = fail_from_call

    def get(self, key: str) -> bytes | None:
        return self._data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self._set_calls += 1
        if self._set_calls >= self._fail_from_call:
            raise RuntimeError("simulated persistence failure")
        self._data[key] = value


def test_store_set_failure_does_not_advance_cache_past_durable_state() -> None:
    """CRITICAL fail-open regression test: if store.set() raises during a
    blocking transition, the in-memory cache must not already reflect that
    transition -- otherwise a halt that never durably landed still reads as
    blocked for the life of this process, while a restart (reading only the
    store) would silently resume trading with no verified successful poll
    since the real failure.
    """
    # record_successful_poll performs two writes the first time any site
    # ever succeeds: the site entry itself, then the persisted, cross-restart
    # "any site ever succeeded" global latch (see record_forbidden_403).
    # Both must land before the 3rd set() -- the actual failing write under
    # test -- raises.
    store: StateStore = _FailOnSetStore(fail_from_call=3)
    clock = _FakeClock()
    gate = SettlementGate(store=store, clock=clock)

    gate.record_successful_poll(VENUE, CITY)  # 1st + 2nd set() succeed -> OPEN, durable
    assert gate.status(VENUE, CITY).state is GateState.OPEN

    with pytest.raises(RuntimeError):
        gate.record_task_death(VENUE, CITY, detail="died")  # 3rd set() raises

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.OPEN
    assert status.reason is GateReason.SUCCESSFUL_POLL


def test_store_set_failure_on_global_block_does_not_advance_cache() -> None:
    store: StateStore = _FailOnSetStore(fail_from_call=1)
    clock = _FakeClock()
    gate = SettlementGate(store=store, clock=clock)

    with pytest.raises(RuntimeError):
        gate.record_forbidden_403(VENUE, CITY, detail="UA rejected")  # cold start -> trap

    assert gate.status(VENUE, CITY).state is GateState.BLOCKED  # default, not global-blocked
    assert gate.status(VENUE, CITY).reason is GateReason.NEVER_POLLED


# ---------------------------------------------------------------------------
# blocking_causes() -- a derived, read-only accessor answering "why is this
# site blocked/degraded RIGHT NOW", distinct from GateStatus.reason/detail
# ("what was the last transition EVENT"). Stores nothing, sets nothing.
# ---------------------------------------------------------------------------


def test_blocking_causes_is_empty_when_open() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    assert gate.blocking_causes(VENUE, CITY) == ()


def test_blocking_causes_is_never_polled_before_any_poll() -> None:
    gate, _, _ = _gate()
    assert gate.blocking_causes(VENUE, CITY) == (GateReason.NEVER_POLLED,)


def test_reason_is_last_event_while_blocking_causes_is_current_root_cause() -> None:
    """This is the documentation of why both GateStatus.reason and
    blocking_causes() exist: they answer different questions. 'reason' is
    the last transition EVENT (a poll genuinely succeeded); blocking_causes
    is WHY the site is still not OPEN right now (ACIS still disagrees).
    """
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_acis_disagreement(VENUE, CITY, detail="CLI=72 ACIS=68")
    gate.record_successful_poll(VENUE, CITY)  # e.g. another clean preliminary poll

    status = gate.status(VENUE, CITY)
    assert status.reason is GateReason.SUCCESSFUL_POLL
    assert status.state is GateState.BLOCKED
    assert gate.blocking_causes(VENUE, CITY) == (GateReason.ACIS_DISAGREEMENT,)


def test_blocking_causes_reports_all_concurrent_causes() -> None:
    """The concurrent case is the whole point: clearing one of two active
    causes leaves the site blocked, and an operator who sees only one would
    think their fix failed.
    """
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_acis_disagreement(VENUE, CITY, detail="CLI=72 ACIS=68")
    gate.record_final_overdue(VENUE, CITY, CLIMATE_DAY_TODAY, deadline_ns=28_800_000_000_000)

    causes = gate.blocking_causes(VENUE, CITY)
    assert GateReason.ACIS_DISAGREEMENT in causes
    assert GateReason.FINAL_CLI_OVERDUE in causes
    assert len(causes) == 2

    # Clearing only one must not silently make the site look OPEN.
    gate.record_acis_agreement(VENUE, CITY, detail="revised ACIS=72")
    causes_after = gate.blocking_causes(VENUE, CITY)
    assert causes_after == (GateReason.FINAL_CLI_OVERDUE,)
    assert gate.status(VENUE, CITY).state is GateState.BLOCKED


def test_blocking_causes_orders_most_severe_first() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_acis_disagreement(VENUE, CITY, detail="x")  # BLOCKED-tier
    gate.record_cross_check_unavailable(VENUE, CITY, detail="y")  # DEGRADED-tier

    causes = gate.blocking_causes(VENUE, CITY)
    assert GateReason.ACIS_DISAGREEMENT in causes
    assert GateReason.CROSS_CHECK_UNAVAILABLE in causes
    assert causes.index(GateReason.ACIS_DISAGREEMENT) < causes.index(GateReason.CROSS_CHECK_UNAVAILABLE)


def test_blocking_causes_includes_global_ua_trap_reason() -> None:
    gate, _, _ = _gate()
    gate.record_forbidden_403(VENUE, CITY, detail="cold start")  # global trap
    causes = gate.blocking_causes(VENUE, CITY)
    assert GateReason.UA_TRAP_403 in causes


def test_blocking_causes_global_trap_combines_with_a_site_level_cause() -> None:
    gate, _, _ = _gate()
    gate.record_successful_poll(VENUE, CITY)
    gate.record_parser_failure(VENUE, CITY, detail="x")
    # cross_site_burst_detected=True: this site already succeeded once, so
    # classification needs the burst signal (not cold start) to reach a
    # global trap here -- see the UA-trap redesign.
    gate.record_forbidden_403(VENUE, CITY, detail="burst detected", cross_site_burst_detected=True)
    causes = gate.blocking_causes(VENUE, CITY)
    assert GateReason.UA_TRAP_403 in causes
    assert GateReason.PARSER_FAILURE in causes


def test_blocking_causes_never_writes_to_the_store() -> None:
    """Purely derived: no store.set() call, no matter what it finds."""

    class _NoSetStore:
        def __init__(self, source: StateStore) -> None:
            self._source = source

        def get(self, key: str) -> bytes | None:
            return self._source.get(key)

        def set(self, key: str, value: bytes) -> None:
            raise AssertionError("blocking_causes() must never call store.set()")

    seed_store = InMemoryStateStore()
    seed_gate = SettlementGate(store=seed_store, clock=_FakeClock())
    seed_gate.record_successful_poll(VENUE, CITY)
    seed_gate.record_parser_failure(VENUE, CITY, detail="x")

    readonly_gate = SettlementGate(store=_NoSetStore(seed_store), clock=_FakeClock())
    causes = readonly_gate.blocking_causes(VENUE, CITY)  # must not raise
    assert GateReason.PARSER_FAILURE in causes


# ---------------------------------------------------------------------------
# Property: state and blocking_causes() are always mutually consistent --
# empty exactly when OPEN, non-empty exactly when not -- across every
# recorder method this module exposes. This is the invariant that makes the
# accessor trustworthy, and exactly what would silently rot when a future
# recorder is added without updating blocking_causes() to match.
# ---------------------------------------------------------------------------


def _setup_open(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)


def _setup_cold_start_ua_trap(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_forbidden_403(VENUE, CITY, detail="cold start")


def _setup_abuse_403(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_forbidden_403(VENUE, CITY, detail="abuse")


def _setup_transient_degraded(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    for _ in range(3):
        gate.record_transient_failure(VENUE, CITY)


def _setup_transient_blocked(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    for _ in range(3):
        gate.record_transient_failure(VENUE, CITY)
    gate.record_transient_failure(VENUE, CITY, final_window_elapsed=True)


def _setup_parser_failure(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_parser_failure(VENUE, CITY, detail="x")


def _setup_sanity_violation(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_sanity_violation(VENUE, CITY, detail="x")


def _setup_ambiguous_headline(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_ambiguous_headline(VENUE, CITY, detail="x")


def _setup_oversize(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_oversize_or_parse_timeout(VENUE, CITY, detail="x")


def _setup_cross_check_degraded(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_cross_check_unavailable(VENUE, CITY, detail="x")


def _setup_cross_check_blocked(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_cross_check_unavailable(VENUE, CITY, detail="x")
    gate.record_cross_check_unavailable(VENUE, CITY, detail="y", conflict_window_elapsed=True)


def _setup_cross_check_resumed_open(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_cross_check_unavailable(VENUE, CITY, detail="x")
    gate.record_cross_check_available(VENUE, CITY)


def _setup_acis_disagreement(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_acis_disagreement(VENUE, CITY, detail="x")


def _setup_acis_resumed_open(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_acis_disagreement(VENUE, CITY, detail="x")
    gate.record_acis_agreement(VENUE, CITY, detail="y")


def _setup_task_death(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_task_death(VENUE, CITY, detail="x")


def _setup_redirect(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_redirect_integrity_alarm(VENUE, CITY, detail="x")


def _setup_client_error(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_client_error_defect(VENUE, CITY, detail="x")


def _setup_clock_regression(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    clock.advance(-1)
    gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000)


def _setup_stale_degraded(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    clock.advance(1_500)
    gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000)


def _setup_stale_blocked(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    clock.advance(2_500)
    gate.check_freshness(VENUE, CITY, degraded_after_ns=1_000, blocked_after_ns=2_000)


def _setup_final_overdue(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_final_overdue(VENUE, CITY, CLIMATE_DAY_TODAY, deadline_ns=1)


def _setup_final_received_open(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_final_overdue(VENUE, CITY, CLIMATE_DAY_TODAY, deadline_ns=1)
    gate.record_final_received(VENUE, CITY, CLIMATE_DAY_TODAY)


def _setup_write_integrity(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_write_integrity_violation(VENUE, CITY, detail="x")


def _setup_transport_integrity(gate: SettlementGate, clock: _FakeClock) -> None:
    gate.record_successful_poll(VENUE, CITY)
    gate.record_transport_integrity_alarm(VENUE, CITY, detail="x")


_CONSISTENCY_SETUPS: list[tuple[str, Callable[[SettlementGate, _FakeClock], None]]] = [
    ("open_after_first_poll", _setup_open),
    ("cold_start_ua_trap", _setup_cold_start_ua_trap),
    ("abuse_403_degraded", _setup_abuse_403),
    ("transient_degraded", _setup_transient_degraded),
    ("transient_blocked", _setup_transient_blocked),
    ("parser_failure", _setup_parser_failure),
    ("sanity_violation", _setup_sanity_violation),
    ("ambiguous_headline", _setup_ambiguous_headline),
    ("oversize_or_timeout", _setup_oversize),
    ("cross_check_degraded", _setup_cross_check_degraded),
    ("cross_check_blocked", _setup_cross_check_blocked),
    ("cross_check_resumed_open", _setup_cross_check_resumed_open),
    ("acis_disagreement", _setup_acis_disagreement),
    ("acis_resumed_open", _setup_acis_resumed_open),
    ("task_death", _setup_task_death),
    ("redirect_integrity_alarm", _setup_redirect),
    ("client_error_defect", _setup_client_error),
    ("clock_regression", _setup_clock_regression),
    ("stale_degraded", _setup_stale_degraded),
    ("stale_blocked", _setup_stale_blocked),
    ("final_overdue", _setup_final_overdue),
    ("final_received_open", _setup_final_received_open),
    ("write_integrity_violation", _setup_write_integrity),
    ("transport_integrity_alarm", _setup_transport_integrity),
]


@pytest.mark.parametrize(
    "setup", [fn for _, fn in _CONSISTENCY_SETUPS], ids=[name for name, _ in _CONSISTENCY_SETUPS]
)
def test_state_and_blocking_causes_are_always_consistent(
    setup: Callable[[SettlementGate, _FakeClock], None],
) -> None:
    gate, _, clock = _gate()
    setup(gate, clock)
    status = gate.status(VENUE, CITY)
    causes = gate.blocking_causes(VENUE, CITY)
    if status.state is GateState.OPEN:
        assert causes == ()
    else:
        assert len(causes) >= 1
        assert status.state in (GateState.BLOCKED, GateState.DEGRADED)


# ---------------------------------------------------------------------------
# Corrupt persisted bytes -- must fail safe AND stay inside the
# GateBlockedError contract (never a bare decode exception out of
# status()/require_open())
# ---------------------------------------------------------------------------

_CORRUPT_SITE_PAYLOADS = [
    pytest.param(b"\xff\xfe not valid utf-8", id="invalid_utf8"),
    pytest.param(b"{not valid json", id="invalid_json_syntax"),
    pytest.param(
        json.dumps({"last_reason": "totally_unknown_reason"}).encode("utf-8"),
        id="unknown_gate_reason",
    ),
    pytest.param(
        json.dumps({"last_reason": "never_polled", "unexpected_field": 1}).encode("utf-8"),
        id="unexpected_key",
    ),
]


@pytest.mark.parametrize("raw", _CORRUPT_SITE_PAYLOADS)
def test_corrupt_persisted_site_bytes_fail_safe_to_blocked(raw: bytes) -> None:
    store = InMemoryStateStore()
    store.set(_site_key(VENUE, CITY), raw)
    gate = SettlementGate(store=store, clock=_FakeClock())

    status = gate.status(VENUE, CITY)  # must not raise
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.CORRUPT_PERSISTED_STATE


def test_corrupt_persisted_site_bytes_logged_at_critical(caplog: pytest.LogCaptureFixture) -> None:
    store = InMemoryStateStore()
    store.set(_site_key(VENUE, CITY), b"not json at all")
    gate = SettlementGate(store=store, clock=_FakeClock())

    with caplog.at_level(logging.INFO, logger="breezy.ingest.gate"):
        gate.status(VENUE, CITY)

    assert any(record.levelno == logging.CRITICAL for record in caplog.records)


def test_corrupt_persisted_site_bytes_require_open_raises_gate_blocked_error_not_a_decode_error() -> (
    None
):
    """Every other blocked path funnels through GateBlockedError -- the type
    the Actor catches around require_open(). Corrupt bytes must stay inside
    that same contract rather than crashing the caller with a raw
    JSONDecodeError/ValueError/TypeError.
    """
    store = InMemoryStateStore()
    store.set(_site_key(VENUE, CITY), b"{not valid json")
    gate = SettlementGate(store=store, clock=_FakeClock())

    with pytest.raises(GateBlockedError):
        gate.require_open(VENUE, CITY)


def test_corrupt_persisted_global_bytes_fails_closed_blocking_all_sites(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Corrupted GLOBAL bytes must fail toward blocking, not toward
    neutral/unblocked -- silently defaulting the UA-trap flag to False would
    reopen every site with no verified fix, the same silent-reopen failure
    mode the clock-regression fix exists to prevent.
    """
    store = InMemoryStateStore()
    store.set(_GLOBAL_KEY, b"{corrupt")
    gate = SettlementGate(store=store, clock=_FakeClock())

    with caplog.at_level(logging.INFO, logger="breezy.ingest.gate"):
        status_a = gate.status(VENUE, CITY)
        status_b = gate.status(VENUE, OTHER_CITY)

    assert status_a.state is GateState.BLOCKED
    assert status_b.state is GateState.BLOCKED
    assert status_a.reason is GateReason.CORRUPT_PERSISTED_STATE
    assert any(record.levelno == logging.CRITICAL for record in caplog.records)


def test_corrupt_persisted_global_bytes_can_be_manually_cleared() -> None:
    store = InMemoryStateStore()
    store.set(_GLOBAL_KEY, b"{corrupt")
    gate = SettlementGate(store=store, clock=_FakeClock())
    gate.record_successful_poll(VENUE, CITY)
    assert gate.status(VENUE, CITY).state is GateState.BLOCKED  # globally blocked

    gate.acknowledge_ua_trap_resolved(detail="verified corruption was transient store noise")
    assert gate.status(VENUE, CITY).state is GateState.OPEN


# ---------------------------------------------------------------------------
# Cache-database startup assertion
#
# Measured against the installed nautilus_trader==1.231.0 tree (not
# assumed) -- see the module docstring / assert_cache_persistence_configured
# for the exact file:line citations. Two corrections from an earlier draft:
#
# 1. save_state/load_state live on NautilusKernelConfig
#    (nautilus_trader/system/config.py), NOT on ActorConfig or
#    StrategyConfig -- both carry neither field. An assertion built against
#    "actor_config.save_state" either always raises against a real
#    ActorConfig, or was never exercised against one.
# 2. Even with save_state/load_state/database all correct, Cache._general
#    (which backs this module's StateStore via Cache.add/Cache.get) is
#    repopulated from the database on restart ONLY through
#    ExecutionEngine.load_cache() -> Cache.cache_general(), which the
#    kernel invokes ONLY when exec_engine.load_cache is True AND
#    cache.flush_on_start is False. Miss either and a UA-trap global halt
#    -- the exact thing this module exists to make survive a crash-loop --
#    is silently lost on restart.
# ---------------------------------------------------------------------------


def test_cache_persistence_assertion_passes_when_fully_configured() -> None:
    config = CachePersistenceConfig(
        save_state=True, load_state=True, database=object(), load_cache=True, flush_on_start=False
    )
    assert_cache_persistence_configured(config)  # must not raise


def test_cache_persistence_assertion_fails_when_database_unset() -> None:
    config = CachePersistenceConfig(
        save_state=True, load_state=True, database=None, load_cache=True, flush_on_start=False
    )
    with pytest.raises(CachePersistenceMisconfiguredError, match="database"):
        assert_cache_persistence_configured(config)


def test_cache_persistence_assertion_fails_when_save_state_false() -> None:
    config = CachePersistenceConfig(
        save_state=False, load_state=True, database=object(), load_cache=True, flush_on_start=False
    )
    with pytest.raises(CachePersistenceMisconfiguredError, match="save_state"):
        assert_cache_persistence_configured(config)


def test_cache_persistence_assertion_fails_when_load_state_false() -> None:
    config = CachePersistenceConfig(
        save_state=True, load_state=False, database=object(), load_cache=True, flush_on_start=False
    )
    with pytest.raises(CachePersistenceMisconfiguredError, match="load_state"):
        assert_cache_persistence_configured(config)


def test_cache_persistence_assertion_fails_when_load_cache_false() -> None:
    """ExecEngineConfig.load_cache=False: ExecutionEngine.load_cache() is
    never invoked at all, so Cache.cache_general() never runs.
    """
    config = CachePersistenceConfig(
        save_state=True, load_state=True, database=object(), load_cache=False, flush_on_start=False
    )
    with pytest.raises(CachePersistenceMisconfiguredError, match="load_cache"):
        assert_cache_persistence_configured(config)


def test_cache_persistence_assertion_fails_when_flush_on_start_true() -> None:
    """CacheConfig.flush_on_start=True: kernel.py's own gating
    (`not flush_on_start`) skips ExecutionEngine.load_cache() even though
    load_cache=True and a database is configured.
    """
    config = CachePersistenceConfig(
        save_state=True, load_state=True, database=object(), load_cache=True, flush_on_start=True
    )
    with pytest.raises(CachePersistenceMisconfiguredError, match="flush_on_start"):
        assert_cache_persistence_configured(config)


def test_cache_persistence_assertion_fails_when_all_five_unset() -> None:
    config = CachePersistenceConfig(
        save_state=False, load_state=False, database=None, load_cache=False, flush_on_start=True
    )
    with pytest.raises(CachePersistenceMisconfiguredError):
        assert_cache_persistence_configured(config)


class _FakeKernelConfig:
    """Models NautilusKernelConfig (e.g. TradingNodeConfig), which is
    where save_state/load_state actually live -- measured at
    nautilus_trader/system/config.py:122-123. Deliberately NOT named
    "ActorConfig": that was the bug.
    """

    def __init__(self, save_state: bool, load_state: bool) -> None:
        self.save_state = save_state
        self.load_state = load_state


class _FakeCacheConfig:
    def __init__(self, database: object | None, flush_on_start: bool = False) -> None:
        self.database = database
        self.flush_on_start = flush_on_start


class _FakeExecEngineConfig:
    def __init__(self, load_cache: bool) -> None:
        self.load_cache = load_cache


def test_cache_persistence_config_from_real_shaped_objects() -> None:
    kernel_config = _FakeKernelConfig(save_state=True, load_state=True)
    cache_config = _FakeCacheConfig(database=object(), flush_on_start=False)
    exec_engine_config = _FakeExecEngineConfig(load_cache=True)
    config = cache_persistence_config_from(kernel_config, cache_config, exec_engine_config)
    assert_cache_persistence_configured(config)  # must not raise


def test_cache_persistence_config_from_detects_unset_database() -> None:
    kernel_config = _FakeKernelConfig(save_state=True, load_state=True)
    cache_config = _FakeCacheConfig(database=None)
    exec_engine_config = _FakeExecEngineConfig(load_cache=True)
    config = cache_persistence_config_from(kernel_config, cache_config, exec_engine_config)
    with pytest.raises(CachePersistenceMisconfiguredError, match="database"):
        assert_cache_persistence_configured(config)


def test_cache_persistence_config_from_detects_flush_on_start() -> None:
    kernel_config = _FakeKernelConfig(save_state=True, load_state=True)
    cache_config = _FakeCacheConfig(database=object(), flush_on_start=True)
    exec_engine_config = _FakeExecEngineConfig(load_cache=True)
    config = cache_persistence_config_from(kernel_config, cache_config, exec_engine_config)
    with pytest.raises(CachePersistenceMisconfiguredError, match="flush_on_start"):
        assert_cache_persistence_configured(config)


def test_cache_persistence_config_from_detects_load_cache_false() -> None:
    kernel_config = _FakeKernelConfig(save_state=True, load_state=True)
    cache_config = _FakeCacheConfig(database=object())
    exec_engine_config = _FakeExecEngineConfig(load_cache=False)
    config = cache_persistence_config_from(kernel_config, cache_config, exec_engine_config)
    with pytest.raises(CachePersistenceMisconfiguredError, match="load_cache"):
        assert_cache_persistence_configured(config)


def test_cache_persistence_config_from_missing_kernel_attrs_raises() -> None:
    class _Empty:
        pass

    with pytest.raises(CachePersistenceMisconfiguredError):
        cache_persistence_config_from(
            _Empty(), _FakeCacheConfig(database=object()), _FakeExecEngineConfig(load_cache=True)
        )


def test_cache_persistence_config_from_missing_cache_database_attr_raises() -> None:
    class _Empty:
        pass

    with pytest.raises(CachePersistenceMisconfiguredError):
        cache_persistence_config_from(
            _FakeKernelConfig(True, True), _Empty(), _FakeExecEngineConfig(load_cache=True)
        )


def test_cache_persistence_config_from_missing_flush_on_start_attr_raises() -> None:
    class _CacheConfigMissingFlushOnStart:
        def __init__(self) -> None:
            self.database = object()

    with pytest.raises(CachePersistenceMisconfiguredError):
        cache_persistence_config_from(
            _FakeKernelConfig(True, True),
            _CacheConfigMissingFlushOnStart(),
            _FakeExecEngineConfig(load_cache=True),
        )


def test_cache_persistence_config_from_missing_exec_engine_attrs_raises() -> None:
    class _Empty:
        pass

    with pytest.raises(CachePersistenceMisconfiguredError):
        cache_persistence_config_from(
            _FakeKernelConfig(True, True), _FakeCacheConfig(database=object()), _Empty()
        )


# ---------------------------------------------------------------------------
# UA-trap survival across a simulated restart, through the REAL
# Cache.add/Cache.get/cache_general() repopulation semantics -- not a
# hand-rolled store that always returns what was set. Measured:
# Cache.add() write-throughs to the database immediately when one is
# configured (cache/cache.pyx:1686-1707); a NEW process's Cache._general
# is populated from that database ONLY by cache_general()
# (cache/cache.pyx:279-304), reached ONLY from ExecutionEngine.load_cache()
# (execution/engine.pyx:774-793), invoked ONLY when
# `config.exec_engine.load_cache and not flush_on_start`
# (system/kernel.py:465-467, where flush_on_start also requires
# config.cache is not None).
# ---------------------------------------------------------------------------


class _SimulatedNautilusCache:
    """A StateStore double modeling the measured Cache semantics above,
    including the restart-repopulation gating -- not just "whatever was
    set is still there," which every hand-rolled InMemoryStateStore-style
    fake trivially (and unrealistically) guarantees.
    """

    def __init__(self, database: dict[str, bytes] | None) -> None:
        self._general: dict[str, bytes] = {}
        self._database = database  # None models CacheConfig.database unset

    def get(self, key: str) -> bytes | None:
        return self._general.get(key)

    def set(self, key: str, value: bytes) -> None:
        self._general[key] = value
        if self._database is not None:
            self._database[key] = value  # Cache.add()'s write-through

    def restart(self, *, load_cache: bool, flush_on_start: bool) -> _SimulatedNautilusCache:
        """A fresh Cache for a new process, sharing the same persistent
        database (if any) -- modeling ExecutionEngine.load_cache() /
        Cache.cache_general() exactly as gated by system/kernel.py.
        """
        new_cache = _SimulatedNautilusCache(database=self._database)
        if self._database is not None and load_cache and not flush_on_start:
            new_cache._general = dict(self._database)
        return new_cache


def test_ua_trap_survives_simulated_restart_when_fully_configured() -> None:
    database: dict[str, bytes] = {}
    cache1 = _SimulatedNautilusCache(database=database)
    gate1 = SettlementGate(store=cache1, clock=_FakeClock())
    gate1.record_forbidden_403(VENUE, CITY, detail="cold start")  # global UA-trap
    assert gate1.status(VENUE, CITY).state is GateState.BLOCKED

    cache2 = cache1.restart(load_cache=True, flush_on_start=False)
    gate2 = SettlementGate(store=cache2, clock=_FakeClock())
    status = gate2.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.UA_TRAP_403


def test_ua_trap_is_laundered_by_restart_when_flush_on_start_true() -> None:
    """Documents the exact failure the 5-condition assertion exists to
    catch at deploy time: with flush_on_start=True, kernel.py's own gating
    skips cache_general() even though load_cache=True and a database is
    configured, so the global block is silently gone after restart.
    """
    database: dict[str, bytes] = {}
    cache1 = _SimulatedNautilusCache(database=database)
    gate1 = SettlementGate(store=cache1, clock=_FakeClock())
    gate1.record_forbidden_403(VENUE, CITY, detail="cold start")
    assert gate1.status(VENUE, CITY).state is GateState.BLOCKED

    cache2 = cache1.restart(load_cache=True, flush_on_start=True)
    gate2 = SettlementGate(store=cache2, clock=_FakeClock())
    status = gate2.status(VENUE, CITY)
    # The global latch is lost -- but the SITE itself still independently
    # defaults to BLOCKED (never polled), so this must not be mistaken for
    # "restart is safe regardless."
    assert status.reason is not GateReason.UA_TRAP_403
    assert status.state is GateState.BLOCKED  # site-level default, not the global latch


def test_ua_trap_is_laundered_by_restart_when_load_cache_false() -> None:
    database: dict[str, bytes] = {}
    cache1 = _SimulatedNautilusCache(database=database)
    gate1 = SettlementGate(store=cache1, clock=_FakeClock())
    gate1.record_forbidden_403(VENUE, CITY, detail="cold start")

    cache2 = cache1.restart(load_cache=False, flush_on_start=False)
    gate2 = SettlementGate(store=cache2, clock=_FakeClock())
    assert gate2.status(VENUE, CITY).reason is not GateReason.UA_TRAP_403


def test_ua_trap_is_laundered_by_restart_when_database_unset() -> None:
    cache1 = _SimulatedNautilusCache(database=None)
    gate1 = SettlementGate(store=cache1, clock=_FakeClock())
    gate1.record_forbidden_403(VENUE, CITY, detail="cold start")

    cache2 = cache1.restart(load_cache=True, flush_on_start=False)
    gate2 = SettlementGate(store=cache2, clock=_FakeClock())
    assert gate2.status(VENUE, CITY).reason is not GateReason.UA_TRAP_403


# ---------------------------------------------------------------------------
# _load_global must read through the store on every access, never cache --
# otherwise the global latch fails to block sites served by sibling
# SettlementGate instances (one per Actor, per (venue, city)) sharing the
# same store, which defeats the entire reason the latch is global.
# ---------------------------------------------------------------------------


def test_global_ua_trap_block_is_visible_across_sibling_gate_instances() -> None:
    """Models 5 Actors, each constructing its own SettlementGate over a
    shared store. Actor A's gate sets the global UA-trap; Actor B's ALREADY
    -CONSTRUCTED gate (with its own, separately-cached view, if caching
    existed) must see it on its very next read -- not only after being
    reconstructed.
    """
    store = InMemoryStateStore()
    clock = _FakeClock()
    gate_a = SettlementGate(store=store, clock=clock)  # Actor A's own instance
    gate_b = SettlementGate(store=store, clock=clock)  # Actor B's own instance

    gate_a.record_successful_poll(VENUE, "MIA")
    gate_b.record_successful_poll(VENUE, OTHER_CITY)
    assert gate_b.status(VENUE, OTHER_CITY).state is GateState.OPEN

    # gate_b already read the (not-yet-blocked) global entry once above --
    # a caching implementation would now be stuck on that stale view.
    # cross_site_burst_detected=True: MIA's own earlier poll already
    # latched any_site_ever_succeeded, so a plain 403 here would classify
    # as a per-site abuse block rather than a global trap -- the burst
    # signal is what a real cross-site UA-trap onset looks like anyway.
    gate_a.record_forbidden_403(
        VENUE, "MIA", detail="burst detected", cross_site_burst_detected=True
    )

    # gate_b must observe the block on its NEXT read, with no reconstruction.
    assert gate_b.status(VENUE, OTHER_CITY).state is GateState.BLOCKED
    with pytest.raises(GateBlockedError):
        gate_b.require_open(VENUE, OTHER_CITY)


def test_site_level_persist_before_cache_ordering_is_unaffected() -> None:
    """Confirms the earlier persist-before-cache fix for the SITE path is
    untouched by making the global path read-through: a failing store.set()
    during a site-level transition must still leave the in-memory site
    cache exactly at the last durably-persisted state.
    """
    store: StateStore = _FailOnSetStore(fail_from_call=3)
    clock = _FakeClock()
    gate = SettlementGate(store=store, clock=clock)

    gate.record_successful_poll(VENUE, CITY)
    assert gate.status(VENUE, CITY).state is GateState.OPEN

    with pytest.raises(RuntimeError):
        gate.record_task_death(VENUE, CITY, detail="died")

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.OPEN
    assert status.reason is GateReason.SUCCESSFUL_POLL


# ---------------------------------------------------------------------------
# InMemoryStateStore itself
# ---------------------------------------------------------------------------


def test_in_memory_state_store_round_trips() -> None:
    store = InMemoryStateStore()
    assert store.get("missing") is None
    store.set("k", b"v")
    assert store.get("k") == b"v"
