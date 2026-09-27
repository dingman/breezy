# EDGE-1 — Fee-drift guard is blind (UNKNOWN never halts, and the wire read is 100% broken)

**Status:** DRAFT r2 · **Date:** 2026-09-27 · **Severity:** HIGH (safety) · **Author:** trading-bot-architect (plan only — no source/test edits, no git, no service changes)

## r1→r2 changes

Coordinator ruling: ADOPT the architect's simpler design (closes all security findings at once). Round 1: domain APPROVE, python APPROVE, architect REQUEST_CHANGES, security REQUEST_CHANGES.

1. **Envelope fallback removed.** `fetch_wire_fee_coefficient` unwraps `{"market": {...}}` only; a flat top-level `feeCoefficient` with no `"market"` key is now `UNKNOWN` (`WireFeeCoefficientError`), never a silent flat-payload read. `_RecordingHttpClient` fixture fixed to the real envelope; the envelope RED test is mandatory, not optional.
2. **Veto redesigned as in-memory, time-based staleness — not a durable key.** New entries are vetoed unless the last `AGREE` was within a staleness bound (≈4h = 2× the 2h probe cadence, absorbing one missed fire without one truly-stale cycle going unnoticed). Vetoed from process boot until the first `AGREE`. This closes security #1 (restart cannot bypass — boot starts vetoed), #3 (a stopped timer ages the last-`AGREE` out, and the check runs at submit time, not on the timer), #2, and architect #3 (no durable key, no `set_fee_unverified`/`clear_fee_unverified` callables, no store, no write-failure path — all removed from the r1 file-by-file plan).
3. **`DISAGREE` never clears the veto** (architect #2) — only `AGREE` refreshes the staleness timestamp. `DISAGREE` keeps its existing, unchanged, durable `record_policy_halt` write.
4. **Entries only, never exits (architect #1).** r1's exec-client `submit_veto` chokepoint (`exec/client.py:4648-4651`) is zero-arg and would deny exits too. Moved to the strategy's own entry path (`_hunt_tick`'s pre-submit gate, alongside the existing `is_family_halted()`/`self._fee_halt` checks at `continuous_strategy.py:1823-1834` — confirm this scaffold at build time via codegraph before wiring, not assumed here) so exits are structurally untouched. New RED test: an exit is submitted while the fee is unverified and is NOT blocked.
5. **Wiring changed to a late-bound holder.** `app/trade.py:~521` builds a single-slot holder before the probe actor exists at `:552`; the holder is populated with the actor's read method once built. `clear_family_halt_cli` does NOT clear this veto — it self-clears only on `AGREE`. Distinct reason string. While A1's halt is set, this veto is redundant (both refuse); stated explicitly, not silently.
6. **Positive live proof added (architect #4).** An INFO line on every probe fire regardless of outcome, e.g. `fee_drift_probe outcome=AGREE wire=… registered=…`; acceptance = grep that line in the node log FILE after the next respawn. Optional pre-deploy one-shot read-only fetch noted, not required.
7. **Alerts revised.** "Fee unverified stale" alert + a 24h reminder (renamed from `..._veto_engaged`/`..._veto_persisting` to reflect staleness framing, not a fire-count). `detail=` on every new/changed alert uses `type(exc).__name__` or numbers only, never `str(exc)` — the exception message embeds the slug (security note).
8. **AC4 test-count fixed** (python note): r1's AC4 said "three" `DISAGREE` tests but the Test strategy section listed five "unchanged-behavior guards." r2 names the exact 3 `DISAGREE`-specific tests AC4 covers and separates the other 2 as independent no-regression guards.
9. **A0 scoping unchanged** — kept as-is from r1 per the ruling.

Disagreement: none. One thing flagged for the build agent rather than resolved here: `continuous_strategy.py:1833-1834` already reads `self._fee_halt` immediately after `is_family_halted()` in `_hunt_tick` — this looks like a pre-existing scaffold for exactly this gate. r1 never mentioned it (it predates this item's own exploration). Confirm via `codegraph_explore "_fee_halt"` at build time before assuming it is unused or already wired to something else — do not take this plan's word for its current behavior.

## Goal & acceptance criteria

1. `fetch_wire_fee_coefficient` correctly parses the venue's real
   `GET /v1/market/slug/{slug}` envelope (`{"market": {...}}`), so a live
   probe fire against a real, open, correctly-fee-tagged market returns
   `AGREE` or `DISAGREE` — never `UNKNOWN` — under normal venue conditions.
   A payload with no `"market"` key at all (flat or otherwise malformed)
   raises `WireFeeCoefficientError` (`UNKNOWN`) — there is no fallback read
   of a top-level field. Testable: a unit test constructs the fixture from
   the ACTUAL captured envelope shape
   (`docs/evidence/venue/polymarket_us/raw/market_open_510636_by_slug.json`),
   not a flattened stand-in, and asserts a parsed `Decimal`; a second test
   asserts a flat/no-`"market"` payload raises cleanly.
2. A staleness-based "fee unverified" submit-veto blocks NEW entry
   submission (never exits) for the affected family whenever the last
   `AGREE` is older than the staleness bound, or there has never been one
   since process boot. It is in-memory only (no durable key, no
   store-write-failure path). Only `AGREE` refreshes the staleness clock.
   `DISAGREE` never clears it (and separately halts, unchanged). Testable:
   boot with no `AGREE` yet → vetoed; an `AGREE` clears it; the veto
   re-engages once the staleness bound elapses with no further `AGREE`; a
   `DISAGREE` after the veto was engaged does NOT clear it.
3. The veto is entry-only: a queued/attempted exit while the veto is
   engaged is NOT blocked by it. Testable: exit submission path exercised
   with the veto engaged, asserts the order is not refused by this check.
4. Crossing into "stale" and remaining stale past an escalation window each
   emit their own distinct, named alert — never silently folded into the
   existing per-fire `fee_drift_probe_unknown` CRITICAL. `detail=` on every
   new/changed alert is `type(exc).__name__` or a number, never `str(exc)`.
   Testable: alert-sink assertions on event names and on `detail=` shape.
5. No change weakens `DISAGREE`'s existing behavior (unconditional durable
   halt via `record_policy_halt`, per-value dedupe, halt-set-failure
   alerting). The three `DISAGREE`-specific tests
   (`test_probe_once_disagrees_alerts_critical_and_halts`,
   `test_probe_once_never_raises_when_the_halt_set_write_itself_fails`,
   `test_disagree_persists_the_halt_through_a_real_trial_day_latch_and_the_veto_then_refuses`)
   keep passing unmodified in substance. Two further, independent
   no-regression guards (`test_an_unknown_never_resets_the_mismatch_dedupe`,
   `test_documented_fee_coefficient_default_is_byte_identical_to_the_pin`)
   also keep passing — listed separately because they guard adjacent
   behavior, not `DISAGREE` itself.
6. Zero new network calls, zero new endpoints, zero new credentials, zero
   new durable store keys; the fix stays inside the already-injected
   `wire_fee_fetcher` / `_PublicReadClient` seam plus one in-process holder.
7. Every probe fire (`AGREE`, `DISAGREE`, or `UNKNOWN`) emits one INFO log
   line naming the outcome and the wire/registered values, so a respawn's
   next fire is provable by a single grep of the node log FILE.
8. Plan explicitly states what does and does not feed Ruling A1 condition 3
   (the A0 evidence pack) and reports A0's *actual current* consecutive-day
   count, not an assumed one.

## Evidence / root cause (file:line)

**The wire read is not "sometimes unknown" — it has NEVER once succeeded.**
`/usr/bin/grep -oh "event=fee_drift_probe_[a-z_]*" ~/.local/share/breezy/logs/breezy-trade-2026*.log`
across every retained trade-node log returns **only** `fee_drift_probe_unknown`
(5 occurrences, all in the current boot `breezy-trade-20260926T165018Z.log`,
one per 2h fire: 16:50, 18:50, 20:50, 22:50, 00:50Z) — never one
`fee_drift_probe_mismatch` or a silent `AGREE`, across the probe's entire
deployed life. A 100% failure rate with an identical exception type on every
fire is the signature of a deterministic code defect, not venue flakiness.

**The HTTP call itself succeeds** (`breezy-trade-20260926T165018Z.log:562-563`):
`status=200`, immediately followed by `WireFeeCoefficientError`. This rules
out wrong endpoint, auth/scope, and rate-limiting — the failure happens
strictly AFTER a successful 200 response, inside payload parsing.

**Root cause: an envelope-unwrap bug** —
`src/breezy/strategy/current_rung_hold/fee_drift_probe.py:184-186` reads
`payload.get(FEE_COEFFICIENT_WIRE_KEY)` directly, but
`GET /v1/market/slug/{slug}` always wraps the market object under a
`"market"` key. Proof, three independent sources: the venue SDK's own
`GetMarketResponse` TypedDict
(`docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/types/markets.py:125-128`);
two real captured payloads (`market_open_510636_by_slug.json`,
`market_closed_15806_by_slug.json`, both `{"market": {..., "feeCoefficient":
0.06, ...}}`); and Breezy's own parser, which already unwraps correctly
(`src/breezy/adapters/polymarket_us/parsing.py:1386`, `:1496`, and
`_parse_fee_coefficient` at `:618-643` reading `market.get("feeCoefficient")`
at `:639`).

**r2 correction to r1's fix shape:** r1 proposed a defensive
fallback-to-raw-`payload` if `"market"` is absent (mirroring
`fee_drift_evidence_pull.py:458`'s `pull_slug` idiom). The coordinator ruling
removes that fallback: a response with no `"market"` envelope is unknown
shape, full stop — it must raise `WireFeeCoefficientError` (`UNKNOWN`), not
silently attempt a flat read that could mis-parse an unrelated field under
the real key name by coincidence. This is a narrower, safer fix than r1's,
at the cost of the (already never-observed) case where the venue might
someday serve a genuinely flat body — that case now correctly surfaces as
`UNKNOWN`/an alert instead of a silent guess.

**Why the unit suite never caught it.**
`tests/unit/test_fee_drift_probe.py:328-337` (`_RecordingHttpClient`) and its
three callers all construct the fixture FLAT — never the real
`{"market": {...}}` envelope. This is a second, independent defect (a
test-fixture/reality gap) that must be fixed alongside the production bug.

**Confirmed non-causes:** venue response shape has not drifted (2026-04-23
and 2026-08-25 captures both show the identical wrapper); not the wrong
endpoint; not auth/scope.

## Options & trade-offs

### (a) Fix the parse — envelope-only, no fallback

Unwrap `payload["market"]` (a `Mapping`) before reading `feeCoefficient`;
if `"market"` is absent or not a `Mapping`, raise `WireFeeCoefficientError`
immediately (`UNKNOWN`) rather than attempting a flat read. This is a
one-line correction of a proven defect, narrowed by the ruling to remove
r1's fallback branch — the probe's job is DETECTION, and an envelope shape
it has never actually seen should surface as "I don't know," never a guess.
`probe_once`'s own bare `except Exception` still catches anything this
raises, so this can never crash the actor.

### (b) Fail-closed policy for sustained UNKNOWN — chosen: in-memory staleness veto (B2'), never the durable halt (B1)

**B1 (rejected, unchanged from r1):** escalating `UNKNOWN` into
`record_policy_halt` — the same durable, operator/peer-ruling-gated write
`DISAGREE` uses — converts ordinary read flakiness (quote-ingest alone timed
out 22 times over 2026-09-24..26) into a halt an operator must ceremonially
clear. Rejected for the same reason r1 rejected it, and for the coordinator's
additional structural reason: any durable key written by this module needs
its own clear-path and write-failure alerting, which is exactly the surface
architect #3 and security #2 flagged.

**B2' (chosen, revised from r1's B2):** a **staleness rule, not a
fire-counter, and in-memory, not durable.** The `FeeDriftProbeActor` tracks
only `_last_agree_at_ns: int | None` (an ordinary Python attribute — no
store, no key). It starts `None` at construction (i.e., at every process
boot). Each `AGREE` sets it to `self.clock.timestamp_ns()`. Nothing else
touches it — `DISAGREE` and `UNKNOWN` both leave it alone. A read-only method
(name TBD by the build agent, e.g. `is_fee_verified(now_ns) -> bool`) returns
`True` iff `_last_agree_at_ns is not None and now_ns - _last_agree_at_ns <=
_FEE_VERIFIED_STALENESS_NS`.

**Why this closes every security finding at once:**
- **#1 (restart bypass):** `_last_agree_at_ns` starts `None` on every boot —
  there is no persisted "last known good" a restart could inherit. A fresh
  boot is vetoed until its own first `AGREE`, unconditionally.
- **#3 (timer stops → veto never engages):** the check is evaluated AT
  SUBMIT TIME against wall/clock elapsed time since the last `AGREE`, not
  driven by the timer firing an event. If the timer itself stops (as
  observed for the unrelated 16:52Z discovery-pull timer on 2026-09-26), the
  last `AGREE` simply ages past the staleness bound and the veto engages on
  its own — no separate liveness check on the timer is needed.
- **#2 / architect #3 (durable key, clear callables, write-failure path):**
  there is no store write at all for this state, so there is no key to name,
  no `set_fee_unverified`/`clear_fee_unverified` callable pair to inject, and
  no write-failure branch to guard or alert on. This removes the entire
  `set_fee_unverified`/`clear_fee_unverified`/new-store-key section of r1's
  file-by-file plan.
- **architect #2 (DISAGREE must not clear it):** only `AGREE` writes
  `_last_agree_at_ns`; `DISAGREE`'s branch is untouched and keeps calling
  `record_policy_halt` exactly as today.

**Staleness bound: ≈4h.** At the existing 2h `DEFAULT_FEE_DRIFT_PROBE_
INTERVAL_SECONDS` cadence, 4h = 2 missed fires. This is the direct
time-based restatement of r1's own `N=2` choice (r1 explicitly flagged
"whether N=2 should instead be a time-based staleness bound" as an open
question — r2 resolves it in favor of time-based, per the ruling). Rationale
unchanged from r1: long enough to absorb one isolated transient read failure
(the kind of flakiness this repo has already measured) without vetoing
trading on a single missed cycle; short enough that a family is never left
both "actively submitting new entries" and "unable to verify its own fee
schedule" for more than one missed interval beyond the first. Robust to a
future cadence change in a way a bare fire-count would not be, which was
exactly r1's own stated reason to prefer this framing once flagged.

**Alerts (both distinct from the existing per-fire `fee_drift_probe_unknown`):**
- `fee_drift_probe_fee_unverified_stale` (CRITICAL) — fired once, the first
  submit-time check (or probe fire — build agent's choice, see Architecture
  below) that observes the staleness bound has been crossed. `detail=` names
  the elapsed seconds since `_last_agree_at_ns` (or "never" as a literal
  string, not an exception message) — a number or a fixed literal, never
  `str(exc)`.
- `fee_drift_probe_fee_unverified_stale_persisting` (CRITICAL) — a 24h
  reminder while still stale, mirroring the existing `_alert_mismatch_
  persisting` idiom (`_MISMATCH_SUPPRESSION_WINDOW_NS`-style window, timed on
  `self.clock.timestamp_ns()`, never wall time), re-arming its own window.
- Clearing (an `AGREE` after staleness had engaged) is logged INFO, not
  alerted — matches this file's existing AGREE-is-silent asymmetry.
- **Security fix, applies to every alert this item touches, old and new:**
  `detail=` must be `type(exc).__name__` or a number/fixed literal — never
  `str(exc)`. The exception message embeds the slug (a market identifier),
  and alert sinks are a wider-audience surface than the trade log.

### (c) Entry-only scope (architect #1) — the veto lives in the strategy's entry path, not the exec-client chokepoint

r1 proposed reading the new state through the exec client's
`submit_veto: Callable[[], str | None]` (the same zero-arg chokepoint
`family_halt_submit_veto` uses, `exec/client.py:4648-4651`,
`composition.py:219-252`). That chokepoint denies **every** order it sees —
it has no concept of entry vs. exit, and `family_halt_submit_veto` is
deliberately family-wide for exactly that reason (a duplicate-fill halt
SHOULD stop exits too). A fee-unverified state is different in kind: it says
"I don't currently trust the fee assumption behind a NEW take," not "stop
touching this family's positions at all" — an unverified fee schedule is not
a reason to refuse to close a position already opened under a fee schedule
that WAS verified at entry time.

**Chosen:** put the check in the strategy's own entry path —
`continuous_strategy.py::_hunt_tick`'s pre-submit gate, in the same
neighborhood as the existing `is_family_halted()` check at `:1823` and the
existing `self._fee_halt` check immediately after it at `:1833-1834` (this
attribute already exists in the file the r1 plan never expanded — confirm
its current wiring via `codegraph_explore "_fee_halt"` before assuming
anything about it; it may already be exactly this gate half-built, or it may
be unrelated). The veto is consulted only on the path that arms a NEW entry
(YES or NO hunt), never on the exit/reconciliation paths, which this module
does not touch at all today and must not start touching for this item.

**RED test required:** an exit order is submitted while the fee-unverified
veto is engaged, and is NOT refused by it (asserts the exit path is
untouched — a regression here would silently reintroduce the "stuck open
position because a read-only detector started blocking exits" failure mode
the readiness-audit lesson already paid for once).

### (d) Do NOT conflate this with A0

Unchanged from r1. A0 (`FEE_DRIFT_EVIDENCE_2026-09-25.md`) explicitly
excludes `FeeDriftProbeActor` samples from its own evidence set regardless
of date (closing rule 1). Fixing the probe does not add a row to A0's table.

## Architecture & data flow

No new component, no new store, no new durable key. A bug fix, an in-memory
staleness attribute on `FeeDriftProbeActor`, and one late-bound holder:

```
FeeDriftProbeActor.probe_once()
  -> _wire_fee_fetcher() -> fetch_wire_fee_coefficient()   [FIXED: unwrap "market", no fallback]
       -> AGREE      -> counters["agree"]++; _last_agree_at_ns = now; INFO log (outcome=AGREE)
                         if was stale: clear-log INFO (not alerted)
       -> DISAGREE    -> existing dedupe/alert/halt path, UNCHANGED; INFO log (outcome=DISAGREE)
                         _last_agree_at_ns UNTOUCHED (does not clear staleness)
       -> UNKNOWN     -> existing _alert_unknown, UNCHANGED; INFO log (outcome=UNKNOWN)

FeeDriftProbeActor.is_fee_verified(now_ns) -> bool
       -> _last_agree_at_ns is not None and now_ns - _last_agree_at_ns <= _FEE_VERIFIED_STALENESS_NS
       -> also responsible for firing the two staleness alerts on the
          transition into/persisting-in the stale state (exact call site —
          inside is_fee_verified vs. a separate checked-on-timer method — is
          a build-time judgment call; either satisfies the ACs above)

app/trade.py (~521, BEFORE the probe is built at ~552):
  holder = _FeeVerifiedHolder()   # single mutable slot, starts "unset"
  ... pass holder.check into the strategy's construction (or wherever
      _hunt_tick's other veto reads are wired) ...
app/trade.py (~552):
  probe = FeeDriftProbeActor(...)
  holder.bind(probe.is_fee_verified)   # late bind, once probe exists

continuous_strategy.py::_hunt_tick (entry path only):
  if self._latch.is_family_halted(): ...             # unchanged
  if self._fee_halt: ...                             # existing — CONFIRM at build time
  if not self._fee_verified_check(now_ns):            # NEW — holder unset OR stale => refuse
      self.diagnostics.record(_DIAG_FEE_UNVERIFIED)   # new diagnostic key, distinct name
      return
  ... existing entry logic, unchanged ...

exit / reconciliation paths: UNTOUCHED — no read of the holder anywhere on
those paths (RED test proves this).
```

Why a holder instead of constructing the probe first: `app/trade.py`
composes the strategy (which needs the read-side callable at construction,
per r1's own observation that the veto site is wired at construction time)
BEFORE it constructs `FeeDriftProbeActor` — the ordering is fixed by the
existing composition sequence (`~521` then `~552`), so the callable the
strategy holds must be indirection over a slot that gets filled in later,
never the actor object itself passed too early. This is the same shape as
any other late-bound Actor reference in this composition root — no new
pattern, just one more instance of it (confirm the existing ordering and
whether a lighter mechanism than a bespoke holder class already exists in
this file via codegraph before writing new plumbing).

## File-by-file plan

- **`src/breezy/strategy/current_rung_hold/fee_drift_probe.py`**
  - Fix `fetch_wire_fee_coefficient` (lines 184-186): unwrap
    `payload.get("market")`; if absent or not a `Mapping`, raise
    `WireFeeCoefficientError` immediately — **no fallback to reading
    `payload` flat** (r1 had one; the ruling removes it). Update the module
    docstring's field-provenance comment to describe the envelope-only read.
  - Add `_last_agree_at_ns: int | None = None` instance state (set at
    `__init__`, never read from or written to any store), a
    `_FEE_VERIFIED_STALENESS_NS` module constant (≈4h, named and commented
    with the "2× cadence" justification above), and an `is_fee_verified`
    (or equivalently named) read method. Update `probe_once`'s three
    branches per the data-flow above — set `_last_agree_at_ns` ONLY on
    `AGREE`; add the one INFO outcome log common to all three branches
    (goal 7); add the two new staleness alerts, both with `detail=` built
    from `type(exc).__name__`/numbers only.
  - No new constructor parameters for store callables — this is the
    concrete removal of r1's `set_fee_unverified`/`clear_fee_unverified`
    plumbing and its two failure-path alerts (`..._veto_set_failed`/
    `..._clear_failed` from r1 are DELETED, not built — there is no write to
    fail).
  - Every existing alert in this module (not just the two new ones) that
    currently builds `detail=` from `str(exc)` must be corrected to
    `type(exc).__name__`/numbers-only if any such call sites exist —
    confirm via `codegraph_explore` scoped to this file before assuming the
    scope is only the two new alerts (security note applies file-wide, not
    item-wide, per the ruling's wording).

- **`src/breezy/app/trade.py`** (composition, ~246-390 and the ~521/~552
  ordering)
  - Add the late-bound holder at `~521`, before the probe is constructed;
    bind it to `probe.is_fee_verified` at `~552`. Confirm the EXACT existing
    ordering and whether the strategy's constructor or a later setter is the
    real wiring point via `codegraph_explore` — the ~521/~552 line numbers
    are the ruling's own citation, not independently re-verified in this
    pass, and must be re-confirmed immediately before editing (file drift
    since 2026-09-27 audit is likely given the pace of recent merges).
  - No new `TrialDayLatch`/store wiring for this item — the holder threads a
    plain callable, not a store handle.
  - State explicitly, in a code comment at the holder's construction site,
    that `clear_family_halt_cli` does not and must not clear this state
    (it self-clears only via a future `AGREE`), and that while the A1
    `policy_halt` is set this veto is redundant with — never a substitute
    for — the existing family-halt veto.

- **`src/breezy/strategy/current_rung_hold/continuous_strategy.py`**
  - `_hunt_tick`: confirm the current behavior of `self._fee_halt` at
    `:1833-1834` (already-existing code this plan did not originate) via
    codegraph before adding a second, possibly-redundant check. If it is
    genuinely unrelated or dead, add the new `is_fee_verified` read
    immediately after the existing `is_family_halted()`/`_fee_halt` checks,
    ahead of every other entry gate, mirroring their placement and their
    `return` shape (a WAIT-style refusal, not an exception). If it turns out
    to already BE this gate (a stale W.I.P. scaffold), reuse it rather than
    adding a parallel one — DRY, per the coding-style rule.
  - Add one new diagnostics key (e.g. `_DIAG_FEE_UNVERIFIED`), distinct from
    `_DIAG_FAMILY_HALT`, so the two refusal reasons are distinguishable in
    the diagnostics summary the same way every other gate in this method
    already is.
  - Exit paths in this file (if any originate here) are asserted, by the new
    RED test, to never read this new check.

- **`tests/unit/test_fee_drift_probe.py`**
  - Fix `_RecordingHttpClient` fixture shape: every existing
    `fetch_wire_fee_coefficient` test constructs
    `{"market": {FEE_COEFFICIENT_WIRE_KEY: "0.06"}}` (or the missing/
    malformed variants nested the same way), not a flat mapping. Mandatory,
    not optional — this is the regression guard for the production defect.
  - New RED tests per Test strategy below, replacing r1's veto-engine tests
    (which assumed a durable key/callable pair) with the staleness-based
    equivalents.

- **`tests/unit/test_app_trade_fee_drift_probe_wiring.py`**
  - Extend with a wiring-level test that the holder is bound to the real
    probe's `is_fee_verified` after composition, and that it starts "unset"
    (i.e., unverified) before the probe fires even once.

- **`tests/unit/test_continuous_rung_hold_*` (exact file — confirm via
  codegraph; likely `test_continuous_rung_hold_strategy.py` or a
  fee-specific sibling)**
  - New RED test: `_hunt_tick` refuses a NEW entry while unverified/stale,
    and records the new diagnostic key.
  - New RED test (architect #1, mandatory): an EXIT submitted while the fee
    is unverified is NOT blocked by this check.

## Test strategy (RED list)

Envelope-fix regression (the core defect):
- `test_fetch_wire_fee_coefficient_unwraps_the_market_envelope` — real
  captured envelope shape → returns the parsed `Decimal`.
- `test_fetch_wire_fee_coefficient_raises_on_a_missing_field` — nested under
  `"market"`, `feeCoefficient` absent → raises.
- `test_fetch_wire_fee_coefficient_raises_on_a_malformed_field` — nested,
  malformed value → raises.
- `test_fetch_wire_fee_coefficient_raises_when_the_market_envelope_is_absent`
  (renamed/tightened from r1's `..._when_market_key_itself_is_missing`) — a
  flat payload with no `"market"` key → raises `WireFeeCoefficientError`
  directly, asserting NO flat-read fallback occurs (this is the mandatory
  RED test the ruling calls out).

Staleness-based fee-unverified veto (new shape, replaces r1's fire-count veto tests):
- `test_a_fresh_boot_is_unverified_until_the_first_agree`
- `test_an_agree_clears_the_stale_state_and_refreshes_the_clock`
- `test_the_veto_reengages_once_the_staleness_bound_elapses_with_no_further_agree`
- `test_a_disagree_does_not_clear_the_stale_state`
- `test_crossing_the_staleness_bound_alerts_exactly_once`
- `test_the_stale_state_persisting_past_the_escalation_window_fires_exactly_one_reminder`
- `test_stale_alert_detail_is_never_the_raw_exception_string` (security)
- (wiring) `test_the_holder_starts_unbound_and_reads_as_unverified_before_the_probe_is_constructed`
- (wiring) `test_the_holder_is_bound_to_the_real_probes_is_fee_verified_after_composition`

Entry-only scope (architect #1, mandatory):
- `test_hunt_tick_refuses_a_new_entry_while_fee_unverified_and_records_the_diagnostic`
- `test_an_exit_submitted_while_fee_unverified_is_not_blocked_by_this_check`

Unchanged-behavior guards (must still pass, asserting no regression):
- `test_probe_once_disagrees_alerts_critical_and_halts`
- `test_probe_once_never_raises_when_the_halt_set_write_itself_fails`
- `test_disagree_persists_the_halt_through_a_real_trial_day_latch_and_the_veto_then_refuses`
- `test_an_unknown_never_resets_the_mismatch_dedupe`
- `test_documented_fee_coefficient_default_is_byte_identical_to_the_pin`

Run via `scripts/ci/run_tests_no_egress.sh`; `lint-imports` after the slice
(this module must still never import `breezy.runtime` beyond what it
already does, and stay invisible to the execution-egress firewall guard
test).

## Execution order & parallelism

Single seam, three file groups — no parallel fan-out needed for the build
itself:
1. RED: fixture-shape fix + envelope-unwrap tests (including the
   no-fallback test) — prove the defect with a failing test against the
   corrected fixture shape.
2. GREEN: the envelope-only `fetch_wire_fee_coefficient` fix.
3. RED: staleness state-machine tests on `FeeDriftProbeActor`.
4. GREEN: `_last_agree_at_ns`/`is_fee_verified`/new alerts.
5. RED→GREEN: `app/trade.py` holder wiring.
6. RED→GREEN: `_hunt_tick` entry-only gate + the exit-is-untouched test.
7. Full gate (`run_tests_no_egress.sh` + `lint-imports`) after every slice,
   per the binding invariant.

## Deploy & verification (what proves it live)

- Node-side change: live only on the next node respawn (never kill the live
  node to deploy). The family is currently HALTED (policy_halt, 09-24
  16:42:30Z, 0 orders flowing), so this fix can wait for the next
  scheduled/hand-triggered respawn without any trading-window cost.
- **Proof of fix, once live:** grep the node log FILE for the new common
  outcome line at every 2h fire —
  `event=fee_drift_probe outcome=AGREE|DISAGREE|UNKNOWN wire=... registered=...`
  — the presence of this line at all (any outcome) proves the parse no
  longer crashes before logging; an `outcome=AGREE` or `outcome=DISAGREE`
  proves the envelope fix specifically. A `fee_drift_probe_fee_unverified_
  stale` alert firing at boot (before the first fire) and clearing after the
  first `AGREE` is the wiring proof for the veto.
- Given `pm_us_crh_v4` is registered at `taker_fee_coefficient = 0.0695` and
  the venue has served `0.0695` since 2026-09-17, the expected steady-state
  outcome post-fix is `AGREE`.

## Risk register

| Risk | Mitigation |
|---|---|
| Removing the flat-payload fallback means a genuinely-flat future venue response is `UNKNOWN` instead of parsed | Deliberate, per the ruling: DETECTION failing closed to "don't know" is safer than a parser guessing at an unproven shape; this has never been observed in two independent captures 4 months apart. |
| Staleness bound (4h) too aggressive/lax | Bounded and self-healing either way (worst case: ~2 missed intervals before veto, or one extra interval of unverified trading if too lax); a future item can retune from lived data once the fix runs correctly for a while. This is the direct restatement of r1's own N=2 trade-off. |
| `_hunt_tick`'s existing `self._fee_halt` check turns out to already be wired to something this item conflicts with | Flagged explicitly above as a build-time codegraph confirmation step before editing — not assumed either way in this plan. |
| Holder pattern introduces a subtle "unbound → always refuse" bug that never clears even after the probe fires | RED test asserts the unbound state reads as unverified AND that binding, once done, is picked up on the very next check — no caching of the pre-bind answer. |
| Test-fixture fix narrows what the fetcher accepts, weakening a currently-passing case | Every existing assertion (return value, exception type) is preserved; only the INPUT shape changes to match reality — a fixture correction, not a loosened assertion. |
| Someone reads "A0 has 1/5 days" as this item's problem to fix | Explicitly scoped out below — A0's timer is healthy and running on its own schedule; this item does not touch it. |

## LESSONS / invariant compliance

- Nautilus Trader untouched; extension stays inside the existing native
  `Actor`/`Clock.set_timer` shape already in place — no new mechanism.
- `allow_short` untouched; no execution-path code touched (this module is
  confirmed, by its own docstring and an existing firewall test, never to
  import anything under `.exec`; the entry-only gate moved this item further
  FROM the exec client than r1's design, not closer to it).
- No safety/settlement/contract test weakened — the `DISAGREE` tests are
  asserted unchanged in substance; the fixture-shape fix tightens realism.
- No operator-reserved cap assigned; no live-trading enablement touched; the
  A1 halt is untouched and this item neither sets nor clears it, and is
  explicitly redundant with (never a substitute for) that halt while it is
  set.
- "A detector without delivery is not a control" (readiness audit lesson):
  the new positive-proof INFO line and the two staleness alerts exist so a
  future "0-for-N-forever" state is provable from a log grep alone, the same
  failure class the alerts-reach-nobody fix already paid for once.
- "Verify agent claims against the artifact": every file:line and log
  excerpt above is drawn from live grep and real captured venue payloads,
  not from this module's own docstring claims.

## Dependencies on other EDGE items

None known. This item is self-contained (one module pair, one composition
wiring point, one strategy entry-path gate, plus tests).

## Ruling A1 condition-3 / A0 tie-in

Unchanged from r1, kept as-is per the ruling.

**A0 and this item are formally independent** — A0's own closing rule
excludes `FeeDriftProbeActor` samples "regardless of date"
(`FEE_DRIFT_EVIDENCE_2026-09-25.md`, closing rule 1). Fixing this probe does
not add a day, a slug, or a value to A0's evidence table.

**A0's actual current state (verified live, not assumed):** the timer is
installed, enabled, and firing daily at 11:10 UTC. 2026-09-25 was an empty
listing (predates the same-day ordering-filter fix; does not count toward
the streak). 2026-09-26 was one COMPLETE day (`markets_listed=60 ok=60`).
**A0 therefore currently has 1 of the required ≥5 CONSECUTIVE complete
days.** Barring another incomplete day, the earliest A0 could close is
2026-09-30. This plan does not change that timeline.

**Per-slug re-pull / maker field:** already covered by A0's own existing
`pull_slug` fallback and independent maker-field recording — no gap.

**Wire-vs-cached-instrument drift:** a real, currently OPEN gap, explicitly
out of this item's scope — flagged as a candidate for a future EDGE/AUD
item, not built here.

**Why this item still matters for re-arm even though it isn't A0.** Ruling
A1's re-arm conditions are a checklist, not a single gate; a re-armed family
with a silently-broken independent fee-drift detector is exactly the
"detector without delivery is not a control" failure mode this repo already
paid for once. This item should land before or alongside any future
A1-class re-arm, as a readiness precondition for trading safely once
re-armed — not as a component of condition 3 itself.

## Confidence self-assessment

**High confidence (root cause, unchanged from r1):** the envelope-unwrap
defect is confirmed by three independent sources plus a live-log signature
(100% failure, always the same exception, always immediately after an HTTP
200) inconsistent with every alternative explanation and consistent with
exactly one (a shallow field read).

**Medium confidence (r2's specific design choices):** the staleness bound
(≈4h) is still a judgment call, now argued from the SAME reasoning as r1's
N=2 rather than new data — there is still no historical data on this probe's
own transient-failure rate once the parse bug is fixed. The exact wiring
mechanics of the late-bound holder (whether a bespoke class or an existing
composition-root pattern already covers this shape) are explicitly left for
build-time codegraph confirmation, not fixed here, as is the current
behavior of `self._fee_halt` at `continuous_strategy.py:1833-1834`.

**Open questions:**
- Whether `self._fee_halt` (`continuous_strategy.py:1833-1834`) is already
  the intended hook for this gate or an unrelated/dead flag — must be
  resolved by the build agent via codegraph before writing the new check,
  not assumed by this plan.
- Exact holder implementation shape (bespoke single-slot class vs. reusing
  an existing late-binding pattern already present in `app/trade.py`'s
  composition root) — left to the build agent.
- Whether the two staleness alerts should be evaluated inside
  `is_fee_verified` itself (checked every `_hunt_tick`) or on the probe's own
  timer cadence (checked every 2h fire) — either satisfies the acceptance
  criteria; the build agent should pick whichever keeps alert-firing
  single-threaded with the rest of `probe_once`'s own alerting, per the
  existing risk-register note on concurrency.

## r2 final amendment (coordinator, round-2 merge). BINDING, overrides anything above.

Round-2 verdicts: the architect APPROVED; security returned REQUEST_CHANGES with a single fix. Round 1 had domain APPROVE and python APPROVE. With AM-1 below applied, all four reviewers have now signed off.

- **AM-1 (security, the clock source).** The submit-time staleness comparison MUST use `self.clock.timestamp_ns()`, the strategy's Nautilus clock, and MUST NOT use `snapshot.ts_event` or any market-data-derived time. Market-data time can lag wall time under feed backlog, which would understate the time since the last AGREE and so extend the "verified" window past its real staleness (fail-open). The probe stamps `_last_agree_at_ns` from its own `self.clock.timestamp_ns()`. In a live node both actors share one LiveClock. Required RED test: `test_fee_staleness_is_computed_on_the_strategy_clock_not_market_data_time`. It feeds a snapshot whose `ts_event` is stale while the strategy clock has advanced past the bound, then asserts the entry is refused.
- **AM-2 (architect note A, defaults).** The new strategy constructor argument (the fee-verified check) defaults to `None`, meaning no check. The strategy is constructed at about 37 sites across 13 files, among them paper replay and about 30 tests. Only the live wiring in `app/trade.py` passes the holder. A wiring test asserts that the live path passes a non-None check and that paper replay does not.
- **AM-3 (architect note B, no probe).** `_build_fee_drift_probe` returns None when no instrument resolves (`trade.py:318-324`). The holder then stays unbound, which reads as unverified, so entries are permanently vetoed. That is safe, because nothing is tradable, and the plan intends it. Test it.
- **AM-4 (architect note C, gate placement).** Create the holder anywhere before strategy composition (`trade.py:~532`); binding happens after the probe is built (`~552`). The build agent must confirm by codegraph whether the NO-side submit (`continuous_strategy.py:2668`) is reached only via `_hunt_tick`. If it is not, put the gate in `_maybe_submit` (`:3286`) instead. That covers entries only and catches both legs. The existing `self._fee_halt` (`:1833-1834`, which is set on a `fee_schedule_mismatch` decision refusal) is a DIFFERENT failure class. Keep it, place the new gate after it, and do not merge the two: merging would make "stale" permanent.
- **An unhandled exception inside the check** aborts that tick before submit. That fails closed and is consistent with the existing unwrapped `_hunt_tick` checks.

**Status: READY for implementation.**
