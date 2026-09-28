"""Operator tool to SET the family-wide halt (AUD-02b: enforce the A1
ruling, ``docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md``).

Mirrors ``clear_family_halt_cli.py``'s shape (``--reason``/``--evidence-path``,
the same flock via ``open_submit_intent_latch``, the same ``resolve_store_path``)
and writes exactly the per-family halt key payload shape
``TrialDayLatch.record_ambiguous_exit`` already writes, via
``TrialDayLatch.record_policy_halt``: no new state, no new veto, no new key.

Lives in the ``strategy`` layer, not ``runtime``, for the same layers-contract
reason ``clear_family_halt_cli.py`` states -- ``strategy`` may import
``runtime`` and ``adapters`` (both sit below it); the reverse is forbidden.

**AUD-02b AMENDMENT (2026-09-21, converged design + peer review) -- the
durable-evidence FALLBACK IS REMOVED.** The pre-set open-position read has
exactly ONE source now: a live, read-only positions GET. Two independent,
verified reasons killed the fallback rather than fixing it:

1. Plan §6.5 clause (b)'s ``TrialDayRecord.exit_at_ns`` cross-check is
   unreachable from a bare slug: the only readers of ``TrialDayRecord``,
   ``TrialDayLatch.record``/``record_with_legacy_fallback``
   (``trial_day_latch.py:684,699``), require ``station`` AND ``climate_day``
   as separate arguments that ``StartupPositionSnapshot`` (``slug``/
   ``net_position`` only, ``exec/client.py:976-979,3079``) cannot supply.
2. The clause (a) half that WAS implemented (the ``DurableFillRecord``
   cross-check, since deleted) was MIS-KEYED and could never fire in
   production: the fill-record lookup used read
   ``FILL_INDEX_KEY_PREFIX + <instrument_id>``,
   where the writer keys by ``record.instrument_id`` = the FULL Nautilus
   instrument id (e.g. ``tc-temp-sfohigh-2026-09-21-gte70f.POLYMARKET_US``,
   ``...^no.POLYMARKET_US`` for the NO leg -- ``exec/client.py:2892,3644``),
   while ``_write_startup_position_evidence`` records the BARE venue slug
   (``exec/client.py:3079``). Bare slug != instrument-id key, so the check
   was structurally inert; the deleted test hid this by seeding both sides
   under the same invented string.

A slug->station/climate-day route DOES exist (``symbology.parse_weather_slug``
+ a station registry, used at ``continuous_strategy.py:1041-1047``,
``composition.py:283-294``) but reusing it here would require THREE new
pieces this tool has no config for (a station-scope gate, a slug->leg-aware
``key_instrument_id`` construction -- undecidable from a bare slug, since the
venue nets a NO holding as a negative on the BASE slug -- and a second
slug->instrument-id conversion to repair defect 2 above). That is new
machinery under an operator halt tool, specified nowhere in the plan; this
change does not invent it.

Checked and confirmed UNAFFECTED by this removal: the strategy's own
never-arm walk, ``continuous_strategy._run_never_arm_walk``, keys its own
reads by the FULL instrument id throughout -- the mis-keying above was
confined entirely to this now-deleted CLI-side code, never a wider live bug.

**Operational consequence, stated plainly:** with the live GET unavailable
(credential/venue outage), the family halt CANNOT be set from this tool.
That is the correct, conservative direction under the plan's own rule
(``UNKNOWN = open = refuse-to-set``): the halt also vetoes
``exit_wiring.submit_exit``, so a false FLAT would strand an open position
with its only automated exit disabled. An unavailable halt is recoverable by
retry once the GET works again; a stranded position is not. If the family
must stop trading before the GET recovers, the operator path is to stop the
trade node instead -- that does not veto the exit seam.

Guards beyond mirroring the clear CLI, because SETTING a halt is the
higher-consequence direction:

* ``node_store_path_check`` pre-flight -- refuses on ``MISMATCH`` or
  ``DISCOVERY_FAILED``.
* ``--status``: read-only, writes nothing, sends nothing.
* The mandatory pre-set open-position read described above. Sign-agnostic
  (``!= 0`` on every slug -- the venue nets a NO holding as a NEGATIVE,
  short-YES ``net_position``); no override.
* A read-back through ``is_family_halted()`` immediately after the write,
  under the SAME held latch -- see ``EXIT_READBACK_FAILED``.
* The halt event is logged AND alerted (WP-B0 discipline); a sink that
  raises can never undo the halt (``emit_alert`` contains it), and its
  failure is separately surfaced on stderr (see ``_ObservedSink``) rather
  than silently swallowed -- the readiness-audit "detector without
  delivery" shape, surfaced rather than repeated.

Plan-test mapping (§7 step 0a), as shipped: tests (13) "stale-fallback" and
(14) "newer-fill" are RETIRED along with the fallback they exercised and
RE-EXPRESSED here as "live GET failure => REFUSED, never flat", one test per
failure class (transport error, auth error, malformed JSON, schema drift).
Every other plan-numbered test keeps its original meaning.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final, TextIO

from breezy.adapters.polymarket_us.errors import ExecutionReportMappingError
from breezy.adapters.polymarket_us.exec.client import PolymarketUSExecutionClient
from breezy.adapters.polymarket_us.exec.endpoints import (
    PORTFOLIO_POSITIONS_PATH,
    PRIVATE_READ_QUOTA_KEY,
)
from breezy.runtime.exec_state_db_path import (
    EXEC_STATE_DB_ENV_VAR,
    ExecStateDbNotConfiguredError,
    NodeStorePathCheckResult,
    node_store_path_check,
    resolve_store_path,
)
from breezy.runtime.health import AlertPayload, AlertSink, emit_alert, resolve_alert_sink
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    SubmitIntentLockError,
    SubmitIntentLockHeld,
    SubmitIntentLockNotHeld,
    open_submit_intent_latch,
)
from breezy.strategy.current_rung_hold.family_id_arg import (
    FamilyIdArgError,
    resolve_continuous_family_arg,
)
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    decode_family_halt_state,
    open_trial_day_latch,
    read_family_halt_rows_readonly,
)

logger = logging.getLogger(__name__)

EXIT_OK: Final[int] = 0
EXIT_REFUSED: Final[int] = 2
EXIT_ALREADY_HALTED: Final[int] = 3
#: P3(iv): the write succeeded but the immediate read-back through
#: `is_family_halted()` did not observe it -- an undefined-safety state, not
#: a plain refusal (nothing was refused; the STORE state is now unknown to
#: this process). Distinct from `EXIT_REFUSED` on purpose: a caller scripting
#: against exit codes must not treat this the same as "nothing happened".
EXIT_READBACK_FAILED: Final[int] = 4

#: Below this, a `--reason` is presumed to be a placeholder, not evidence.
#: Identical to `clear_family_halt_cli.MIN_REASON_LENGTH`, not imported from
#: it: the two tools' argument validation is independent by design.
MIN_REASON_LENGTH: Final[int] = 20

SOURCE_LIVE: Final[str] = "LIVE_GET"

VERDICT_FLAT: Final[str] = "FLAT_AND_KNOWN"
VERDICT_OPEN: Final[str] = "OPEN"
VERDICT_UNKNOWN: Final[str] = "UNKNOWN"

_NEXT_OPEN_POSITION: Final[str] = (
    "NEXT: breezy-clear-family-halt (written reason + evidence) -> let the "
    "exit seam submit -> re-run breezy-set-family-halt."
)
_NEXT_LIVE_GET_UNAVAILABLE: Final[str] = (
    "NEXT: the venue positions GET is the ONLY accepted evidence of flatness "
    "(AUD-02b P1: the durable-evidence fallback was removed). Restore venue "
    "reachability and re-run. Do NOT hand-set the halt. If the family must "
    "stop trading before the GET recovers, stop the trade node instead -- "
    "that is the operator path, and it does not veto the exit seam."
)


def _reason_type(value: str) -> str:
    stripped = value.strip()
    if len(stripped) < MIN_REASON_LENGTH:
        raise argparse.ArgumentTypeError(
            f"--reason must be at least {MIN_REASON_LENGTH} characters"
        )
    return stripped


def _evidence_path_type(value: str) -> Path:
    path = Path(value)
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"--evidence-path does not exist: {value}")
    return path


@dataclass(frozen=True, slots=True)
class PositionCheckResult:
    """The pre-set open-position read's outcome -- exactly three shapes now
    that the fallback is removed: ``(LIVE_GET, FLAT_AND_KNOWN,
    "eof_page_all_zero")``, ``(LIVE_GET, OPEN, "non_zero_net_position")``, or
    ``(LIVE_GET, UNKNOWN, "LIVE_GET_FAILED:<ExceptionClassName>" |
    "LIVE_PAGE_REJECTED:<detail>")``. ``source`` is retained (rather than
    dropped) so a caller need not special-case a single-source result today
    against a future amendment that adds one back.
    """

    source: str
    verdict: str
    token: str


class _ObservedSink:
    """P3(viii): wrap the resolved `AlertSink` so a delivery failure is
    surfaced on stderr WITHOUT changing `emit_alert`'s own containment.

    `emit_alert` (`health.py`) already catches `BaseException` and logs it --
    that containment is preserved unchanged (`health.py` is out of this
    seam's touch-set). This wrapper's `emit` re-raises AFTER recording
    `failed = True`, so `emit_alert`'s own `except BaseException` still fires
    exactly as it does for any other sink, and the caller here can then ask
    "did delivery fail?" without doing its own try/except around a sink it
    does not own.
    """

    def __init__(self, inner: AlertSink) -> None:
        self._inner = inner
        self.failed = False

    def emit(self, payload: AlertPayload) -> None:
        try:
            self._inner.emit(payload)
        except BaseException:
            self.failed = True
            raise


def _positions_from_live_payload(payload: Mapping[str, Any]) -> dict[str, Decimal] | None:
    """Reuse the node's own parser -- no second parser is written.

    Returns ``None`` (UNKNOWN) when a named slug's entry is missing or
    malformed. Raises :class:`ExecutionReportMappingError` (propagated from
    :meth:`PolymarketUSExecutionClient.declared_positions`, a bare
    ``@staticmethod`` -- no instance, no connection, no I/O) when the page
    itself is not a well-shaped, terminal (``eof: true``) page.
    """
    positions = PolymarketUSExecutionClient.declared_positions(payload)
    result: dict[str, Decimal] = {}
    for slug, entry in positions.items():
        if not isinstance(entry, Mapping):
            return None
        net_raw = entry.get("netPosition")
        if net_raw is None:
            return None
        try:
            result[slug] = Decimal(str(net_raw))
        except InvalidOperation:
            return None
    return result


def check_pre_set_position(
    *,
    positions_reader: Callable[[], Mapping[str, Any]],
) -> PositionCheckResult:
    """The mandatory pre-set open-position read (plan §6.5, AUD-02b
    amendment P1). The live positions GET is the ONLY accepted evidence of
    flatness -- see the module docstring for why the durable-evidence
    fallback was removed rather than repaired.

    Sign-agnostic throughout: the comparison is ``Decimal(net) != 0``, never
    ``> 0`` -- the venue nets a NO holding as a negative, short-YES
    ``net_position``. Fail-closed and never silent: any read failure or any
    drifted/malformed shape REFUSES; there is no override.
    """
    try:
        payload = positions_reader()
    except Exception as exc:
        # P3(v): a programming bug (AttributeError/TypeError) must be
        # distinguishable from an ordinary transport/auth failure. Verified
        # safe to log in full (type + traceback, not just the type), and the
        # scope is wider than the HTTP transport alone: `positions_reader`
        # here can be `_default_live_positions_reader`, which can ALSO raise
        # `SettingsError` from `factories.exec_config_from_env`/the
        # `config.venue` guard above -- neither carries a secret either.
        # Every exception the transport can raise
        # (`VenueTransportError`/`VenueAuthError`/`VenueRateLimitError`/
        # `GatewayForbiddenError`/`VenueStatusError`, `http.py:190-246`) is
        # built from `format_request_context(method, url, status_code)` and
        # an explicit byte COUNT on a bad body ("content withheld",
        # `http.py:252`) -- never a signed header, a credential, or a query
        # string (this GET sends none). `SettingsError`'s messages name only
        # config field names and observed types (never a value read from the
        # config), and both `PolymarketUSDataClientConfig` and
        # `PolymarketUSExecClientConfig` are asserted, at import time, to
        # carry no secret-bearing field at all via
        # `credentials.assert_config_type_excludes_secrets`
        # (`config.py:535,671`) -- so no config object reachable here could
        # embed one even if a future message tried to. The printed TOKEN a
        # caller sees stays the class name only, regardless.
        logger.exception("live positions GET failed")
        return PositionCheckResult(
            SOURCE_LIVE,
            VERDICT_UNKNOWN,
            f"LIVE_GET_FAILED:{type(exc).__name__}",
        )
    try:
        positions = _positions_from_live_payload(payload)
    except ExecutionReportMappingError as exc:
        return PositionCheckResult(SOURCE_LIVE, VERDICT_UNKNOWN, f"LIVE_PAGE_REJECTED:{exc}")
    if positions is None:
        return PositionCheckResult(
            SOURCE_LIVE,
            VERDICT_UNKNOWN,
            "LIVE_PAGE_REJECTED:slug_entry_invalid",
        )
    if any(net != 0 for net in positions.values()):
        return PositionCheckResult(SOURCE_LIVE, VERDICT_OPEN, "non_zero_net_position")
    return PositionCheckResult(SOURCE_LIVE, VERDICT_FLAT, "eof_page_all_zero")


def _default_live_positions_reader(env: Mapping[str, str]) -> Mapping[str, Any]:
    """Production default: a real, read-only positions GET.

    Reuses the EXACT production wiring -- ``factories.exec_config_from_env``
    plus the shared HTTP client factory the node itself uses, both through
    their PUBLIC names -- rather than a second credential/transport
    implementation or a private-name reach-through. Never exercised by a
    test: every test in ``tests/unit/test_set_family_halt_cli.py`` injects
    its own ``positions_reader``. This path only runs for the operator's
    own, separately-scheduled step 0c invocation.
    """
    from nautilus_trader.common.component import LiveClock

    from breezy.adapters.polymarket_us import factories as _factories
    from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig
    from breezy.runtime.settings import SettingsError

    config = _factories.exec_config_from_env(env)
    venue_config = config.venue
    # Type-narrowing / defence-in-depth, not a fix for a reachable latent
    # defect: `PolymarketUSExecClientConfig.__post_init__` (config.py:635-639)
    # already raises `SettingsError` if `venue` is not a
    # `PolymarketUSDataClientConfig`, so `exec_config_from_env` can never
    # actually return a config with a bad `venue` here. This guard exists so
    # mypy (and a future reader) sees the narrowing explicitly, mirroring the
    # identical check `PolymarketUSLiveExecClientFactory.create`
    # (factories.py ~:692-696) already performs for the same reason.
    if venue_config is None or not isinstance(venue_config, PolymarketUSDataClientConfig):
        raise SettingsError(
            "PolymarketUSExecClientConfig.venue must be a "
            f"PolymarketUSDataClientConfig; got {type(venue_config).__name__}"
        )
    client = _factories.shared_polymarket_us_http_client(venue_config, LiveClock())
    return asyncio.run(
        client.get_authenticated(PORTFOLIO_POSITIONS_PATH, quota_key=PRIVATE_READ_QUOTA_KEY)
    )


def set_family_halt(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    positions_reader: Callable[[], Mapping[str, Any]] | None = None,
    alert_sink: AlertSink | None = None,
    proc_root: Path = Path("/proc"),
) -> int:
    """Run the set tool. Returns 0 set / 2 refused / 3 already halted /
    4 read-back failed (see ``EXIT_READBACK_FAILED``)."""
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    source = os.environ if env is None else env

    parser = argparse.ArgumentParser(prog="breezy-set-family-halt")
    parser.add_argument(
        "--status",
        action="store_true",
        help="read-only: report the halt state and store-path check; writes and sends nothing",
    )
    parser.add_argument("--family-id", required=True, help="continuous-rung-hold family id")
    parser.add_argument(
        "--families-dir",
        type=Path,
        default=Path("deploy/families"),
        help="directory containing registered family manifests",
    )
    parser.add_argument(
        "--reason",
        type=_reason_type,
        help=f"non-trivial written justification, at least {MIN_REASON_LENGTH} characters",
    )
    parser.add_argument(
        "--evidence-path",
        type=_evidence_path_type,
        help="path to an existing evidence artefact; only its sha256 is recorded",
    )
    args = parser.parse_args(argv)
    if not args.status and (args.reason is None or args.evidence_path is None):
        parser.error("--reason and --evidence-path are required unless --status is given")
    try:
        resolve_continuous_family_arg(args.family_id, args.families_dir)
    except FamilyIdArgError as exc:
        print(f"breezy-set-family-halt: {exc}; refused", file=err)
        return EXIT_REFUSED

    # P3(ii): hash the evidence FIRST -- before the store, the flock, or any
    # GET -- mirroring clear_family_halt_cli.py:94-104. An unreadable file
    # refuses cleanly with no store ever opened.
    evidence_sha256: str | None = None
    if not args.status:
        try:
            evidence_sha256 = hashlib.sha256(args.evidence_path.read_bytes()).hexdigest()
        except OSError as exc:
            print(
                f"breezy-set-family-halt: --evidence-path unreadable "
                f"({type(exc).__name__}); refused. "
                "NEXT: point --evidence-path at a readable file and re-run.",
                file=err,
            )
            return EXIT_REFUSED

    try:
        store_path = resolve_store_path(source)
    except ExecStateDbNotConfiguredError as exc:
        print(
            f"breezy-set-family-halt: {exc}; refused. "
            f"NEXT: set {EXEC_STATE_DB_ENV_VAR} to the node's own absolute store path and re-run.",
            file=err,
        )
        return EXIT_REFUSED

    path_check: NodeStorePathCheckResult = node_store_path_check(store_path, proc_root=proc_root)
    if path_check == "DISCOVERY_FAILED":
        print(
            f"breezy-set-family-halt: store-path check {path_check} against "
            f"{EXEC_STATE_DB_ENV_VAR}; refused. "
            "NEXT: this means the node's /proc environment could not be read "
            "(permissions, or this shell runs as a different user than the "
            "node) -- it is NOT an env-var mismatch. Re-run as the user that "
            "owns the trade node, or confirm no node is running, then re-run.",
            file=err,
        )
        return EXIT_REFUSED
    if path_check != "MATCH" and path_check != "NO_NODE":
        print(
            f"breezy-set-family-halt: store-path check {path_check} against "
            f"{EXEC_STATE_DB_ENV_VAR}; refused. "
            "NEXT: confirm this shell's exec-state-db env var matches the live "
            "node's (or that no node is running), then re-run.",
            file=err,
        )
        return EXIT_REFUSED

    if args.status:
        try:
            legacy_raw, family_raw = read_family_halt_rows_readonly(store_path, args.family_id)
            reading = decode_family_halt_state(args.family_id, legacy_raw, family_raw)
        except Exception as exc:  # noqa: BLE001 - any read-only status failure REFUSES
            print(
                f"breezy-set-family-halt: status unreadable ({type(exc).__name__}); refused",
                file=err,
            )
            return EXIT_REFUSED
        print(
            "breezy-set-family-halt: "
            f"store_path={path_check} family_id={args.family_id} halted={reading.halted} "
            f"source={reading.source} legacy={reading.legacy}",
            file=out,
        )
        return EXIT_OK

    store = SqliteStateStore(store_path)
    check: PositionCheckResult | None = None
    try:
        try:
            with open_submit_intent_latch(store, store_path) as intent_latch:
                trial_latch = open_trial_day_latch(
                    intent_latch,
                    key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
                    family_id=args.family_id,
                )
                halted = trial_latch.is_family_halted()

                if halted:
                    print("breezy-set-family-halt: already halted; nothing to do", file=out)
                    return EXIT_ALREADY_HALTED

                reader = (
                    positions_reader
                    if positions_reader is not None
                    else (lambda: _default_live_positions_reader(source))
                )
                check = check_pre_set_position(positions_reader=reader)
                if check.verdict == VERDICT_OPEN:
                    print(
                        "breezy-set-family-halt: refused, pre-set open-position check "
                        f"source={check.source} verdict={check.verdict} reason={check.token}",
                        file=err,
                    )
                    print(f"breezy-set-family-halt: {_NEXT_OPEN_POSITION}", file=err)
                    return EXIT_REFUSED
                if check.verdict != VERDICT_FLAT:
                    print(
                        "breezy-set-family-halt: refused, pre-set open-position check "
                        f"source={check.source} verdict={check.verdict} reason={check.token}",
                        file=err,
                    )
                    print(f"breezy-set-family-halt: {_NEXT_LIVE_GET_UNAVAILABLE}", file=err)
                    return EXIT_REFUSED

                assert evidence_sha256 is not None  # narrows for mypy; set above, non-status path
                now_ns = time.time_ns()
                trial_latch.record_policy_halt(
                    reason=args.reason,
                    evidence_sha256=evidence_sha256,
                    ts_ns=now_ns,
                )

                # P3(iv): read back through the SAME chokepoint the veto
                # itself reads, under the SAME held latch, before declaring
                # success.
                if not trial_latch.is_family_halted():
                    print(
                        "breezy-set-family-halt: WROTE the halt but the read-back "
                        "through is_family_halted() says NOT halted -- the veto "
                        "may not be armed. "
                        "NEXT: run --status; if it reports halted=False, treat the "
                        "family as UNPROTECTED and stop the trade node.",
                        file=err,
                    )
                    return EXIT_READBACK_FAILED
        except SubmitIntentLockHeld:
            print(
                "breezy-set-family-halt: the node holds the lock; refused. "
                "NEXT: wait for the node's maintenance window and re-run.",
                file=err,
            )
            return EXIT_REFUSED
        except SubmitIntentLockNotHeld:
            print(
                "breezy-set-family-halt: lock not held; refused. "
                "NEXT: this is an internal ordering error, not an operator action -- "
                "report it rather than retrying blindly.",
                file=err,
            )
            return EXIT_REFUSED
        except SubmitIntentLockError as exc:
            print(
                f"breezy-set-family-halt: lock infrastructure failure "
                f"({type(exc).__name__}); refused. "
                'NEXT: this is not "the node is running" -- check the store path '
                "and filesystem, then re-run.",
                file=err,
            )
            return EXIT_REFUSED
    finally:
        store.close()

    resolved_sink = alert_sink if alert_sink is not None else resolve_alert_sink(source)
    observed_sink = _ObservedSink(resolved_sink)
    assert check is not None  # narrows for mypy; set on every path that reaches here
    emit_alert(
        observed_sink,
        AlertPayload(
            severity="WARN",
            event="family_halt_set",
            site="breezy-set-family-halt",
            detail=(
                f"family_id={args.family_id} reason={args.reason} evidence_sha256={evidence_sha256}"
            ),
        ),
    )
    if observed_sink.failed:
        print(
            "breezy-set-family-halt: halt IS set, but the alert sink FAILED -- "
            "nobody was told. "
            "NEXT: check the alert egress configuration; the halt itself needs no action.",
            file=err,
        )
    print(
        f"breezy-set-family-halt: halted, position_check_source={check.source}",
        file=out,
    )
    return EXIT_OK


def main(
    argv: list[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    positions_reader: Callable[[], Mapping[str, Any]] | None = None,
    alert_sink: AlertSink | None = None,
    proc_root: Path = Path("/proc"),
) -> int:
    """Console-script entrypoint."""
    return set_family_halt(
        argv,
        env=env,
        stdout=stdout,
        stderr=stderr,
        positions_reader=positions_reader,
        alert_sink=alert_sink,
        proc_root=proc_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
