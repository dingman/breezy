# AUD-02 — Adopt POST_FORECAST_PHASE as the G-02 plan of record; fold in the CRH calibration-defect finding; A1 is RULED (ii) — enforce it (AUD-02b)

## 1. ID and actionable title

**AUD-02.** No new architecture is proposed here. This item (a) formally
adopts `docs/plans/POST_FORECAST_PHASE_2026-09-20.md` (as amended by its own
security and architecture peer reviews) as the plan of record for gap G-02,
(b) records which of its work packages are ALREADY DONE versus still open,
verified against git history, (c) folds in the 09-20/09-21 finding that the
live pricing model's own calibration table is confirmed invalid — which the
existing plan predates and does not account for — into work package A1's
precondition, and (d) records that the one forcing action is now DONE: **A1 is
RULED and peer-ENDORSED, 2026-09-21** —
`docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`
(Revision 3; review trail
`docs/evidence/reviews/RULING_A1_review_2026-09-21.md`, verdict ENDORSE, no
required change) — as **(ii) STOP TRADING THIS SURFACE**: `pm_us_crh_v4`
may not SEND orders, while the node, quote-tape capture, shadow valuation
and the KILL clock keep running; **(iii) is rejected for now**, (e) carries
that ruling's own stated consequence into buildable scope as **AUD-02b:
enforce the A1 ruling** (§6.5) — the ruling is **UNENFORCED** until a
set-halt path exists and is run — and (f) replaces the now-moot
A1-open-age escalation line with a halt-enforcement status line (§6.4), so
the unenforced interval does not rot silently the way prior undelivered
findings in this repo have.

## 2. Source finding, verdict, class

Gap **G-02** — "No demonstrated edge; live probability is not
forecast-derived; `ForecastLadderStrategy` unimplemented; forecast taker
ruled terminal 09-20" (`AUTONOMY_ROI_AUDIT_2026-09-21.md` lines 37-43,
verdict FALSE/verified). Existing plan of record:
`docs/plans/POST_FORECAST_PHASE_2026-09-20.md` (DRAFT, peer-reviewed by
security + architecture, both returned BUILD/SAFE WITH NAMED CHANGES).
Class: **verification/research-programme gap** — this is not a code defect;
it is an unfinished decision process. PROGRESS.md's standing verdict
already states it plainly: "NO FAMILY HAS A PROVEN EDGE."

**Status change, round 4:** the A1 decision node this item existed to force
has RUN. `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`
(ENDORSED) rules **(ii) STOP TRADING THIS SURFACE**. The unfinished
decision process is therefore closed; what is still open is (a)
ENFORCEMENT of that ruling in code — AUD-02b, §6.5 — and (b) the
downstream work packages in §4 that are not moot under (ii).

## 3. Current behaviour, required behaviour, gap

**Current:** Three named hypotheses are DEAD (forecast taker — terminal per
`RULING_forecast_edge_programme_closes_2026-09-20.md`, Murphy decomposition
`D=-0.01518` CI95 `[-0.03229,-0.00373]`, market resolution 1.98x the
forecast's; maker/resting v5 — folded `CLOSED_NOT_REGISTERED`;
overconfidence-fade — UNDETERMINED/unmeasurable, NO leg never priced). The
surviving live family, `pm_us_crh_v4` (`continuous_rung_hold`), was never one
of the three scored hypotheses — its `p_hold` archive table is a
**climatological persistence estimate**, not a forecast, so the 1.98x result
does not speak to it either way (correctly noted in `DECISION_FUNNEL`). As of
09-20/21 that table is independently CONFIRMED invalid for live use on its
own terms (see AUD-01, §3): NO-side p(miss) is understated (mean +0.094 over
233/240 cells) and the domain reviewer judges the family
**"UNSALVAGEABLE, not merely miscalibrated"** absent real historical venue
ladders, which do not exist. `pm_us_crh_v4` therefore has **no demonstrated
edge on either side** — YES is conservative-but-unmeasured, NO is
confirmed-unsafe.

Of `POST_FORECAST_PHASE`'s work packages: **WP-B0 (alert egress) is DONE**
(`f97c26f feat(wp-b0)`, confirmed `git log`) and **WP-R1 (zero-orders/
all-refused detector) is DONE** (`6aa9d92 feat(wp-r1)`, `e83fc5c
fix(wp-r1)`, confirmed `git log` — this closes the item PROGRESS.md still
lists as "Fix (not yet applied)"; **PROGRESS.md is stale on this point**,
flagged as an assumption/blocker in §12, not corrected here per the planning
brief's prohibition on editing PROGRESS). **Every other work package —
A0/A1 (fee evidence + the θ ruling), B1/B2/B3 (permit-lapse detector/kernel
guard/operational posture), C0/C1/C2 (WS-cap probe, NO-leg capture, frozen-
region readout), WP-D1 (discovery attrition), WP-Q1 (tape-gap root cause),
WP-T1 (offer-tape collapse) — has NO matching commit and is still open.**

**Required behaviour:** per the plan's own stated goal, the programme reaches
either (i) a pre-registered, measurable candidate edge with a positive CI, or
(ii) an honest retirement/halt ruling — not indefinite "trading resumed by
momentum" (the plan's own risk 2, `POST_FORECAST_PHASE §3.2`).

**Concrete gap (RESTATED, round 4 — A1 is RULED):** A1 has now run and
ruled (ii), precisely because its stated precondition could not be met: a
post-θ edge estimate for `pm_us_crh` itself (amendment B-1) is made
STRICTLY HARDER by the calibration-defect finding — a favourable θ
re-estimate cannot produce a trustworthy edge number while the underlying
`p_hold` table is confirmed biased and recalibration-on-gate-pass is ruled
invalid (ruling §3.2-§3.4), and A0's evidence pack is itself unmet (ruling
§3.5). **The remaining gap is therefore no longer decisional but
operational: the ruling is UNENFORCED.** Verified in the ruling's §4 and
re-verified against source this round (§6.5): the halt STATE and its
submit-time VETO already exist and are wired, but the only writers of the
halt key are automatic fill/exit consequences — there is no
build-invocable SET path, so nothing in the repo today prevents
`pm_us_crh_v4` from sending an order the moment pricing legalizes. Today's
zero-take state is an accident of two data-quality gates, not a designed
control.

**Leak-safety, pre-registration, and sample-size protocol — verified present,
not assumed (coordinator requirement, resolved here):** the round-1
mle-reviewer correctly flagged that this plan inherits, but never cites,
whether A0/A1's evaluation protocol is actually leak-safe and
sample-size-ruled. Checked directly against `POST_FORECAST_PHASE_2026-09-20.md`
this round:
- **Pre-registration / leak-safety:** the A1 work-package row (§1) requires,
  for any (iii) re-registration, "**n reset to 0 per L-34**, new
  `d0_climate_day`, new `trial_id_prefix`, fresh LD-OBF α" — i.e. a
  candidate edge cannot be evaluated against stale/mixed trial state; it
  gets a fresh pre-registered trial boundary and a fresh sequential-testing
  alpha budget before any CI is computed. §4 (Binding constraints) restates
  this as a blanket rule: "**Every hypothesis WP carries a pre-registered
  abandonment criterion**."
- **Sample-size rule:** C1's abandonment criterion (§1) is explicit —
  "**21 days** of capture if qualifying events accrue at < 0.25/station-day
  (n≈30 then >8 weeks away)" — and C2 (§1) "Runs only at **n ≥ 30**" with
  acceptance "Station-day-clustered 95% CI on realised NO-leg PnL," CI
  including 0 or a non-positive lower bound closing the hypothesis. This is
  a named, fixed stopping rule, not an ad hoc "look until it looks good."
- **A1's own gate:** "Precondition for (iii): a post-θ edge estimate whose
  CI excludes 0... if A0 cannot produce one, (iii) is abandoned by default
  and (ii) is the answer" — this is the CI-based stopping rule this item's
  §6.2 widened precondition builds on.

**Conclusion: the base plan already guarantees leak-safety, pre-registration,
and a sample-size/stopping rule for any candidate edge before A1 can rule
(iii).** No additional protocol requirement is added here — the specific
sections are now cited (above), closing the mle-reviewer's MINOR finding
without re-litigating the base plan's own peer-reviewed content.

## 4. Priority, rationale, dependencies, execution order

- **AUD-02 (programme status / fold-in): P1.** With A1 now RULED, this
  part no longer blocks a strategic decision; it records the decision and
  re-scopes the downstream work packages under (ii).
- **AUD-02b (enforce the A1 ruling): P0 — re-assessed this round, raised
  from the parent's P1.** Justification, stated as a safety argument rather
  than an urgency claim: (a) the ruling says `pm_us_crh_v4` may not SEND
  orders, and the family CAN send orders today — the veto exists but no
  halt is set, so the prohibition is aspirational (ruling §4, "UNENFORCED";
  review D2 [HIGH]); (b) the only thing stopping it is the accidental
  zero-pricing funnel the ruling itself calls unsafe to rely on, and
  independent in-flight work (AUD-01b's LAX/MDW station-stall diagnosis,
  any observation-feed change) could reopen pricing onto a table confirmed
  biased in 233/240 NO-side cells without anyone re-ruling A1; (c) the cost
  is a CLI mirroring one that already exists, not new gate machinery, so
  the usual "P0 is expensive" counterweight does not apply. A stop that is
  ruled but not enforced is exactly the "correct finding, undelivered"
  shape this repo has already paid for twice. **Round-5 qualification, which
  does not lower the P0 but does constrain the deployment:** this halt is
  order-global, not entry-only — it vetoes the exit seam too
  (`exit_wiring.py:246,269-275`) — so the P0 is "set it as soon as the
  pre-set open-position check (§6.5) says the book is flat AND known", not
  "set it before checking". The check is a read of state the node already
  holds, so it costs no delay when the book is flat. **AUD-02b does not depend on
  AUD-01a** and must not wait for it — AUD-01a's NO-side gate is defence in
  depth for a *future* family, not what makes today's state safe (ruling
  §4, "Permitted").
- **AUD-01a dependency, now historical:** the parent item's original
  dependency existed so A1 would be ruled about a bot whose NO side was
  already gated fail-closed. A1 has now ruled (ii) without waiting, and the
  ruling itself resolves the risk question in the conservative direction,
  so this is no longer a sequencing constraint on either AUD-02 or AUD-02b.
  AUD-01 is UNTOUCHED by this plan (ruling §6).
- **Depends on AUD-03 by id, one-directional (corrected per round-2
  review):** the §6.4 escalation line's OWNERSHIP now lives in AUD-03 §8 as
  a required, conditional acceptance criterion (see §6.4/§8 below, and
  AUD-03's own §8/§12) — this plan specifies the line's content, AUD-03
  implements and enforces it. This creates no cycle: AUD-02 does not require
  AUD-03 to have shipped for AUD-02's own acceptance (§8); AUD-03 does not
  require anything from AUD-02 for its own core funnel-digest acceptance
  either, only for the one conditional bullet it now owns.
- **Execution order** (adopts `POST_FORECAST_PHASE`'s own revised order,
  amendment B, with the two DONE items removed):
  `AUD-02b (enforce the halt — FIRST, ahead of everything else, per its P0)
  → B3 (window posture) → B2 (kernel guard) → WP-D1 (discovery attrition)
  → A0 (fee-drift evidence, now ALSO carrying the calibration-defect
  citation, see §6; under (ii) it is no longer an A1 precondition but
  remains a §7-item-3 precondition of any FUTURE A1-class ruling) →
  B1 (permit-lapse Actor heartbeat, backstop)` — `A1 (the ruling)` is
  removed from this chain: it is DONE,
  with `WP-T1 (offer-tape collapse) parallel` and `WP-Q1 → C0 → C1` gated
  as a rider "only if the post-freeze YES qualifying rate >= 0.25" (already
  measured at 0.125/station-day, 2x BELOW that bar — `POST_FORECAST_PHASE`
  amendment B-2 — so **C is not expected to proceed** absent new
  measurement).

## 5. Scope and explicit exclusions

**In scope:** (a0) **AUD-02b — enforcing the A1 ruling in code (§6.5), the
one executable sub-item in this plan**; (a) this status/fold-in record
itself; (b) one concrete change
to `POST_FORECAST_PHASE_2026-09-20.md`'s A1 work-package row — NOT proposed
as an edit this plan performs (planning-only constraints), but specified
precisely enough that the implementer/coordinator can apply it as a
documented amendment C, parallel to amendments A and B already in that file;
(c) an explicit escalation mechanism for the A1 blocker, routed through
already-shipped infrastructure only, with its enforcement OWNED by AUD-03
(§6.4).

**Excluded, explicitly:**
- **Re-running the forecast-taker hunt.** CLOSED, TERMINAL, by
  pre-registered procedure. Not reopened by this item under any
  circumstance — the brief's own instruction and the ruling's §4 both bind
  this.
- **Deciding A1 itself.** No longer applicable as an exclusion: A1 is
  RULED (ii), ENDORSED
  (`docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`). What
  remains excluded is **RE-deciding A1, or any re-arm**: a future (iii)
  requires a NEW A1-class ruling against a NEW manifest, and no work in
  this plan pre-authorizes it (ruling §7 item 6).
- **Producing the genuinely independent edge estimate.** Owned by
  **AUD-18** (`AUD-18-strategy-design-backtest-iterate-programme.md`), cited
  by id only; see §6.6.
- **The NO-side safety gate itself** — owned by AUD-01a; this plan only
  cites it as a dependency.
- **The daily decision-funnel digest, and enforcement of the A1-open-age
  line's delivery** — owned by AUD-03; this plan only specifies the line's
  content and cites the dependency by id (§4, §6.4). AUD-03's own §8 is the
  acceptance criterion that makes the line's delivery required, not this
  plan's.
- **Building any of C0/C1/C2** beyond what is already specified in
  `POST_FORECAST_PHASE` — no new design work; the existing spec, as amended,
  stands.
- **New alerting infrastructure.** The escalation mechanism in §6.4 reuses
  `resolve_alert_sink`/AUD-03's digest exclusively; no new transport, queue,
  or service is proposed.

## 6. Proposed changes (documentation-only; grounded in inspected evidence)

1. **Amendment C to `POST_FORECAST_PHASE_2026-09-20.md`** (a new section,
   same shape as amendments A/B already in the file): mark WP-B0 and WP-R1
   **DONE**, citing `f97c26f` and `6aa9d92`/`e83fc5c`.
2. **A1's precondition is widened.** Currently (amendment B-1): "a post-θ
   edge estimate for `pm_us_crh` itself." Add: "...and that edge estimate
   must be computed WITHOUT relying on `P_HOLD_LOWER`/`P_HOLD_UPPER` cells
   whose gate-pass conditioning the domain reviewer has ruled a collider
   (`DECISION_FUNNEL_2026-09-20.md`, 'Why "recalibrate on the gate-pass
   subsample" is NOT the remedy') — i.e., A0's fee-drift evidence pack alone
   cannot satisfy A1; a genuinely independent edge estimate is required, and
   if none can be produced without real (non-synthetic) historical venue
   ladders, **(ii) STOP TRADING THIS SURFACE is not merely the default, it
   is very likely the only defensible ruling.**" This is a citation-and-
   precondition change, not new machinery — no code touched.
3. **No other work package is altered.** B1/B2/B3, C0/C1/C2, WP-D1/Q1/T1
   stand as specified and peer-reviewed in the existing plan.
4. **A1-blocker escalation mechanism — content specified here, OWNERSHIP
   resolved to AUD-03 (rewritten per round-2 review; was previously an
   unowned mutual scope note between the two plans).** The `pm_us_crh_v4`
   family carried a named, open BLOCKER (A1) with no cadence or reminder
   when this section was written — the same "correct finding, undelivered" shape that already cost
   this repo a 3-day silent fee halt and an 11-hour silent permit lapse
   (both cited in `POST_FORECAST_PHASE` amendment B-0 as the motivating
   precedent for WP-B0). Rather than build new infrastructure, this item
   specified the content exactly: AUD-03's daily decision-funnel digest
   carries a per-day "A1 open, N days since gap G-02 filed" line whenever
   `pm_us_crh_v4` is the live family and no `family_halted`/re-registration
   ruling doc exists under `docs/evidence/` — i.e. the blocker's age is a
   field the ALREADY-DELIVERED daily digest reports, never a new alert
   path.

   **ROUND-4 SUPERSESSION — the A1-open-age line is MOOT, and what replaces
   it.** Its own stated condition ("no ruling doc exists under
   `docs/evidence/`") is now false: the ruling doc exists, so the line would
   correctly report nothing from the day AUD-03 ships. The requirement it
   was protecting has not gone away, though — it has MOVED from "has the
   decision been made?" to "**has the decision been enforced?**", which is
   the interval AUD-02b closes and during which the family can still send.
   **Replacement content, specified here (one line, same digest, no new
   transport):**

       halt_enforced: yes|no  (family=<sending_family_id>,
                               ruling=docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md,
                               unenforced_days=<N since 2026-09-21>)

   where the value is read from the SAME halt state the veto reads —
   `continuous_family_is_halted(raw)` (`trade_supervisor_core.py:345-356`,
   verified: fail-closed, absent key or the cleared sentinel means NOT
   halted) against `continuous_family_halt_key(...)`
   (`trade_supervisor_core.py:158-174`, verified) — never a doc scrape and
   never a second source of truth. `unenforced_days` stops accruing the day
   the halt is set and reads `no`/`0` thereafter.

   **This replacement is a NAMED DEPENDENCY ON AUD-03, NOT an edit this
   plan performs.** AUD-03 §8 (Revision 3) currently carries the
   A1-open-age line as a REQUIRED, RED-tested acceptance criterion; swapping
   its content for `halt_enforced` requires changing AUD-03's own §6.6/§7
   steps 11-12/§8 text, and this plan does not edit sibling plans. **Stated
   as a dependency:** whoever implements or next revises AUD-03 must replace
   the A1-open-age criterion with the `halt_enforced` criterion above,
   citing this section. **If that AUD-03 change is never made,** the
   fallback is explicit and non-silent: the A1-open-age line ships and
   reports a permanent "not open" — harmless but uninformative — and the
   enforcement status remains visible instead via AUD-02b's own alerted halt
   event and the node log's `family_halt` veto reason (§6.5), which do not
   depend on AUD-03 at all. This is a deliberate downgrade of AUD-03 from
   sole carrier of the visibility obligation to a convenience surface for
   it.

   **Ownership (round-2 correction, coordinator requirement):** the
   round-2 prediction-market-reviewer found this line was specified by both
   plans but REQUIRED by neither — AUD-02's own §8 (Revision 2) stated "does
   not require AUD-03 to have shipped first, only that the requirement is
   on record," and AUD-03's own §8 (Revision 2) did not list it as a
   required criterion either, so both plans could independently reach 100%
   of their own acceptance while the line never shipped. **Resolved: AUD-03
   §8 (Revision 3) now makes this line a REQUIRED, RED-tested acceptance
   criterion, conditional on this plan (AUD-02) having landed by the time
   AUD-03 is implemented** — see AUD-03 §6.6/§7 steps 11-12/§8's new
   required bullet. **This plan (AUD-02) depends on AUD-03 by id for the
   line's actual delivery, one-directionally** — AUD-02's own DONE status
   (§8) does not require AUD-03 to have shipped, only that this
   specification (§6.4) exists for AUD-03 to consume. **Named fallback if
   AUD-03 slips or is never implemented:** AUD-03's own §8/§12 (Revision 3)
   commit to filing a standalone, owned follow-up backlog item for the line
   if AUD-03 is implemented before AUD-02 lands; symmetrically, if AUD-02
   lands and AUD-03 is never implemented at all, the escalation line simply
   never ships (the residual risk the round-2 mle-reviewer named as
   "optional tightening, not a defect in AUD-02's own text" — because AUD-03
   is itself a separate, independently-justified P1 item whose own
   non-implementation is a portfolio-prioritisation question, not a gap in
   either plan's text). Either way, the obligation is now owned and
   enforceable in one identified place (AUD-03 §8) rather than a mutual
   scope note neither plan enforces.

5. **AUD-02b — enforce the A1 ruling (the one executable sub-item; code).**
   **Null hypothesis checked first, per the repo's binding constraint:**
   Nautilus is NOT missing anything here and is not touched — Breezy's
   existing submit-time veto is an injected `submit_veto: Callable[[], str
   | None]` on the Breezy-owned Polymarket.us exec client, not a Nautilus
   class, subclass, or patch. Verified this round against source (every
   file:line below re-read via codegraph this round, not carried from the
   ruling on trust):
   - **The halt STATE exists.** `FAMILY_HALT_KEY = "continuous_rung_hold/halt"`
     (`src/breezy/strategy/current_rung_hold/trial_day_latch.py:291`);
     `TrialDayLatch.is_family_halted` (`:1002`); cleared-sentinel semantics
     `_HALT_CLEARED_MARKER` (`:301`) — the store has no delete, so "cleared"
     is a distinguishable value, and ANY other stored value is halted,
     fail-closed; best-effort payload decode `_decode_halt_payload`
     (`:304-320`) never raises on corrupt bytes.
   - **The VETO exists and is wired.** `family_halt_submit_veto`
     (`src/breezy/strategy/current_rung_hold/composition.py:195-228`)
     returns the literal reason `"family_halt"` when
     `is_family_halted()`; built and threaded at
     `src/breezy/app/trade.py:260` (`submit_veto =
     family_halt_submit_veto(family_halt_latch)`, forwarded at `:316`) —
     verified; consulted synchronously immediately before the permit spend,
     so a non-None reason denies with zero money moved.
   - **The halt is sender-global.** `continuous_family_halt_key`
     (`src/breezy/runtime/trade_supervisor_core.py:158-174`) and
     `CONTINUOUS_FAMILY_HALT_KEY` (`:139`, byte-identical literal, pinned by
     `tests/unit/test_trade_supervisor_cont_self_check.py`): under
     cardinality-1 a halt set for the node's one sender denies
     `pm_us_crh_v4` specifically today.
   - **What is MISSING is only a SET path.** The only writers of the key are
     `TrialDayLatch.record_duplicate_fill` (`trial_day_latch.py:861-915`)
     and `record_ambiguous_exit` (`:968-1000`) — both automatic
     consequences of fill/exit events. The only CLI touching the key is
     `src/breezy/strategy/current_rung_hold/clear_family_halt_cli.py`
     (console script `breezy-clear-family-halt`, `pyproject.toml:287`),
     which only clears (`clear_family_halt` `:70-135`, calling
     `TrialDayLatch.clear_family_halt` `trial_day_latch.py:1031`). **No
     `set` sibling exists** — confirmed by blast-radius query on
     `FAMILY_HALT_KEY` this round.

   **Build: `breezy-set-family-halt`, a mirror of the clear CLI — no new
   mechanism.**
   - New module `src/breezy/strategy/current_rung_hold/set_family_halt_cli.py`,
     console script `breezy-set-family-halt = "...set_family_halt_cli:main"`
     in `pyproject.toml` beside `:287`. It lives in `strategy`, not
     `runtime`, for the same layers-contract reason the clear CLI states
     (`clear_family_halt_cli.py:9-11`); run `lint-imports` after the slice.
   - Argument and guard shape copied from the clear CLI, not re-invented:
     `--reason` with the same `MIN_REASON_LENGTH = 20` validator
     (`clear_family_halt_cli.py:51,54-60`), `--evidence-path` that must be
     an existing file whose sha256 is recorded, never its content
     (`:63-67,102`), `resolve_store_path(env)` (`:97`), `SqliteStateStore`
     (`:104`), and `open_submit_intent_latch` (`:107`) so the tool REFUSES
     while the node holds the flock (`:126-131`). Exit codes mirror the
     clear tool's `EXIT_OK=0` / `EXIT_REFUSED=2` and use the third slot
     (`:46-48`) for "already halted, nothing to do".
   - The write itself is one new `TrialDayLatch` method (e.g.
     `record_policy_halt`) that writes exactly the `FAMILY_HALT_KEY`
     payload shape `record_ambiguous_exit` already writes (`:968-1000`),
     plus `reason`/`evidence_sha256`/`ts_ns` fields, so `is_family_halted`
     (`:1002`), `_decode_halt_payload` (`:304`), the existing clear path,
     and the runtime-side mirror `continuous_family_is_halted`
     (`trade_supervisor_core.py:345-356`) all keep working unchanged. **No
     new state, no new veto, no new key, no Nautilus touch.**
   - The halt event is **logged AND alerted** through the already-shipped
     sink: `resolve_alert_sink(env)` (`src/breezy/runtime/health.py:579-610`)
     — which returns a `TeeAlertSink` (log branch FIRST, webhook second)
     when a webhook is configured — emitted via the module's existing
     contained `emit_alert`, so a failing sink can never undo or mask the
     halt. This matches the WP-B0 alert-egress discipline: a halt event is
     exactly the "correct finding, undelivered" shape B0 exists to prevent.
   - **Store-path pre-flight, MANDATORY, INSIDE the CLI (round-5 defect 1).**
     The clear CLI does NOT do this: `clear_family_halt` resolves its own path
     (`clear_family_halt_cli.py:97`) and opens `SqliteStateStore(store_path)`
     (`:104`) with no comparison against the LIVE node's env — a gap this plan
     closes on the SET side rather than inheriting. Before any write the set
     CLI calls `node_store_path_check(store_path)`
     (`src/breezy/runtime/exec_state_db_path.py:142-182` — value-free, returns
     exactly `MATCH`/`MISMATCH`/`NO_NODE`/`DISCOVERY_FAILED`, pinned by
     `tests/unit/test_exec_state_db_path.py`) and REFUSES (`EXIT_REFUSED`)
     unless the result is `MATCH` or `NO_NODE`, the same accept-set that
     module's own `main` already uses (`:66,212-214`). Without it the CLI can
     resolve a different `POLYMARKET_US_EXEC_STATE_DB` store than the running
     node (stale shell, wrong unit, operator error), write there, exit
     `EXIT_OK` and report "halted" while the node's store is untouched and the
     family can still send. `DISCOVERY_FAILED` refuses too — unknown is not
     MATCH. `strategy` may import `runtime` (only the reverse is forbidden,
     `clear_family_halt_cli.py:9-11`), so the import is legal; re-run
     `lint-imports` on the slice regardless.
   - **Read-only `--status` mode (round-5 defect 2).** A mode that writes
     NOTHING and sends NOTHING: it runs the same `resolve_store_path` +
     `node_store_path_check` pre-flight, opens the store, and prints the
     store-path result plus `is_family_halted()` (`trial_day_latch.py:1002`) —
     the SAME bytes the submit veto reads (`composition.py:195-228`), not a
     separate mirror. This is the market-activity-independent positive control
     §7 step 0d requires: it answers "is the halt enforced in the store the
     live node resolved?" on a day with zero decisions (today: zero decisions
     reach pricing, `DECISION_FUNNEL_2026-09-20.md:8-19,347-354`).
   - **Pre-set open-position check, MANDATORY — the halt vetoes the EXIT seam
     too (round-5 defect 3a).** `submit_exit`
     (`src/breezy/strategy/current_rung_hold/exit_wiring.py:246,269-275`)
     checks `strategy._latch.is_family_halted()` FIRST, records
     `_DIAG_FAMILY_HALT` (`:271`, value `:81`) and returns before building any
     closing order; its own docstring (`:251-254`): "a family halted for ANY
     reason ... never submits another order of either kind". Setting this halt
     therefore ALSO disables the operator-mandated sell-identified-losers exit
     path while it stands. Read-only source for the check — the live venue
     read is the DEFAULT and the node's durable evidence is the FALLBACK, and
     the reason is STALENESS (round-6 defect 1): `StartupPositionEvidence` is
     written only at the END of `_connect` (`_refresh_startup_position_
     evidence`, `client.py:3102-3133`) and after a resolver terminal-zero
     resolution (`:908-910`), never at fill or exit time, and
     `STARTUP_EVIDENCE_KEY` holds "exactly one row, the most recent evidence,
     never a history" (`:398-401`) with no freshness contract — so a node that
     filled or exited after its last reconnect can present a stale
     `net_position` of zero and the check would pass over an actually-open
     position.
     (1) **DEFAULT — the live read-only positions GET** `/v1/portfolio/
     positions` (the path constant `PORTFOLIO_PATH`,
     `scripts/venue/polymarket_us_auth_smoke.py:164`), issued through the
     node's OWN read-only transport
     `PolymarketUSHttpClient.get_authenticated(path, quota_key=...)`
     (`src/breezy/adapters/polymarket_us/http.py:116-135`, returning the raw
     `Mapping[str, Any]` payload): a READ, never an order, and it carries no
     staleness question at all. It does NOT cross the NO-SEND
     execution-egress firewall: that firewall is the OS-level network block
     `scripts/ci/run_tests_no_egress.sh` puts around the TEST suite (`:2`,
     `:55,60,64`), and this is a build-side operator command run in the node's
     own maintenance window — exactly as the existing read-only auth smoke
     already is. `polymarket_us_auth_smoke.py:1019` (`_probe_authenticated`)
     is cited ONLY as proof that a positions GET over this transport is a
     permitted read (`PERMITTED_METHODS = frozenset({"GET"})`, `http.py:64`,
     enforced `:189-192`) — it is a bare connectivity probe that returns
     `"accepted"`/`"REJECTED: <exception>"` and parses NEITHER `positions` NOR
     `eof` (`:1015-1040`), so it is NOT the parsing model and must not be
     copied as one (round-6 defect 1, MATERIAL).
     **Parsing reuses the node's existing parser — no second parser is
     written.** `GetUserPositionsResponse` is CURSOR-paginated (it carries
     `nextCursor` and `eof` beside `positions`), and the node's own durable
     evidence writer already refuses a non-terminal page:
     `PolymarketUSExecutionClient._declared_positions(payload)`
     (`src/breezy/adapters/polymarket_us/exec/client.py:2592-2622`) raises
     `ExecutionReportMappingError`
     (`src/breezy/adapters/polymarket_us/errors.py:208`) unless `positions` is
     PRESENT and a `dict` ("an absent map is not an empty map", `:2595-2605`)
     and `payload.get("eof") is True` ("page 1 is not necessarily the whole
     book … refuse rather than silently truncate", R-4P-1, `:2606-2621`; an
     ABSENT `eof` is UNKNOWN, never `True`). **Reuse seam:**
     `_declared_positions` is a `@staticmethod` on the class at
     `client.py:1085`, so the CLI calls
     `PolymarketUSExecutionClient._declared_positions(payload)` directly — no
     instance, no connection, no I/O, no extraction. The per-slug projection
     follows the SAME shape-drift discipline as
     `_write_startup_position_evidence` (`client.py:3071-3079`): EVERY slug the
     page names is carried, and a slug whose entry is missing or not a
     `Mapping`, or whose `netPosition` is absent, yields `None` = UNKNOWN =
     open = refuse — never a dropped slug and never an assumed zero (the repo
     has a standing history of balance/execution shape drift; the convention at
     this seam is a NAMED `VenuePayloadError` refusal, not a best-effort
     parse). **Consequently: `eof is not True`, a drifted/malformed payload
     shape, or an unparsable slug entry each ⇒ `EXIT_REFUSED` (UNKNOWN = open);
     a truncated or partial page is NEVER read as flat; only an `eof=True` page
     that parses clean and names zero non-zero `net_position` values is
     "flat-and-known".** No test performs the live GET (§7 step 0a tests inject
     a fake reader and run under that gate).
     (2) **FALLBACK, only when the GET cannot run** (credentials unreachable,
     venue unreachable, non-2xx): the node's OWN durable
     `StartupPositionEvidence` (`client.py:917-921` — `ts_ns`, `eof_complete`,
     `position_read_refused`, `positions`; the `slug`/`net_position` snapshot
     `:876-888`), read from the SAME store the set CLI opens under the SAME
     flock, and usable ONLY if it passes BOTH freshness tests:
     (a) **time bound** — `ts_ns` no older than a bound fixed in the
     implementation and PRINTED (the current UTC trading day's node launch, or
     N minutes); older ⇒ UNKNOWN;
     (b) **cross-check against the records that ARE written at fill/exit
     time** — every `DurableFillRecord` reachable from the same store via
     `TrialDayLatch.iter_fill_records(...)` (`trial_day_latch.py:1102-1137`;
     read-only, same store, no venue call) for the instruments the evidence
     itself names, and each trial record's exit provenance `exit_at_ns`
     (`record_exit`, `:918-966`; `TrialDayRecord.exit_at_ns`, `:473`). ANY
     `ts_event` (`client.py:675`) or `exit_at_ns` NEWER than `ts_ns` ⇒
     "position possibly open" ⇒ UNKNOWN. Because the store has no prefix scan
     (`iter_fill_records`'s own docstring), that instrument set cannot be
     proven complete — which is precisely why this path is the fallback and
     not the default.
     **Fail-closed and never silent: UNKNOWN = open = refuse-to-set.**
     `eof_complete is False`, `position_read_refused is True`
     (`client.py:911-915`), a stale `ts_ns`, a newer fill or exit record, or a
     failed GET with no usable fallback each yield UNKNOWN; the CLI exits
     `EXIT_REFUSED` printing the SOURCE used, the VERDICT and a named reason
     token. It never degrades UNKNOWN to "flat" and never proceeds quietly.
     **Sign-agnostic rule: ANY non-zero net position on ANY slug = open.**
     The venue nets a NO holding as a SHORT YES, i.e. a NEGATIVE
     `net_position`, so the comparison is `Decimal(net) != 0` — never `> 0`
     and never a truthiness test on a string. A negative value is an OPEN
     position and refuses exactly as a positive one does; pinned by test (18)
     rather than left as prose (round-6 MINOR, both reviewers).
     **Rule: REFUSE to set while any non-zero `net_position` is present, or
     while the answer is UNKNOWN. There is NO override (round-6 defect 2).**
     The previous "explicit, reasoned acceptance in `--reason`" escape named no
     enforcement mechanism — free text satisfying only `MIN_REASON_LENGTH`
     (`clear_family_halt_cli.py:51,56-58`) — and is REMOVED rather than
     re-specified as a slug-matched flag: with a position open the procedure is
     always the same one (let it settle or exit it first, then set), weather
     positions settle within a day, so the override buys nothing that the plain
     sequence does not, and an unenforceable escape on a safety stop is worth
     less than the KISS rule it weakens. **Do NOT assume flat because the last
     fill was 2026-09-15 and weather markets settle daily — CHECK.** Disclose,
     in `--reason` and in the AUD-02b evidence note, that a LATER-armed exit
     family is blocked identically while the halt stands; the required sequence
     to exit a position under a halt is `breezy-clear-family-halt` (written
     reason + evidence artefact) → let the exit seam submit → re-run
     `breezy-set-family-halt`. There is no exit-only bypass, and this plan does
     not build one — that would be a new hole in the veto.
     **Why the settle-or-exit-first WAIT is acceptable (round-6 MINOR).** The
     wait is the only cost of removing the override, and it is bounded and
     cheap: (a) the exposure is daily-settling weather markets, so any open
     position clears by settlement within a day without any action; (b) the
     family currently takes NOTHING — 100% of decisions die upstream of
     pricing, no decision has ever reached the pricing gate
     (`docs/evidence/DECISION_FUNNEL_2026-09-20.md:1,19`) — so the probability
     of even entering the wait state is near zero; (c) the mechanism can only
     ever refuse too long, never set unsafely. **What the wait COSTS, stated
     honestly: until the halt is set the A1 ruling remains UNENFORCED** — the
     family is un-halted for the duration of the wait, which is precisely the
     status quo this plan is closing, not a new exposure. **If a NEW fill
     occurs during the wait:** nothing special happens and no state is carried
     — the check is not a latch, it simply RE-RUNS on the next invocation, sees
     the new position as open, and refuses again; the halt is set at the FIRST
     flat-and-known moment. **Residual, stated:** a family that filled
     repeatedly could in principle defer the set indefinitely; with (b) above
     this is theoretical today, and the honest bound is that the operator sees
     each refusal's printed source/verdict/reason token and can exit the
     position deliberately rather than waiting.
   - **Supervisor self-check consequence (round-5 defect 3b) — VERIFIED, and
     the round-4 premise CORRECTED.** The r4 review described a WARN alert
     firing "repeatedly (each self-check tick)". Verified against source: it is
     NOT per-tick. SELF_CHECK is a once-per-day scheduled phase
     (`trade_supervisor_core.py:34` `SELF_CHECK_UTC = 17:05`, window closes
     `:45` at 17:10 UTC, latched done by `mark_phase_fired` `:765,777` setting
     `self_check_done` so it cannot re-fire that day), and `_do_self_check` has
     exactly ONE call site (`trade_supervisor.py:1485`). While halted it yields
     `SelfCheckResult.FAIL_CONTINUOUS_FAMILY_HALTED`
     (`trade_supervisor_core.py:276`, returned at `:551-552`) → ONE WARN
     `TRADE_SUPERVISOR_SELF_CHECK_FAIL` carrying the DISTINCT, already-named
     detail `self_check_fail_continuous_family_halted` (`:216`, mapped
     `:293-295`; emitted `trade_supervisor.py:1297-1303`). The "distinct state,
     reported once then daily" the review asked for is what the existing check
     ALREADY does. **Decision: add NO new `SelfCheckResult` and NO dedup
     layer.** Doing so would mean editing the FAIL→detail map and the alert
     predicate `_SELF_CHECK_PASS_RESULTS` (`trade_supervisor.py:1193-1195`) —
     touching a live safety check to make a deliberate stop quieter, the exact
     weakening this plan may not do. **Masking risk, bounded and stated:** the
     halted branch is evaluated LAST in `self_check` (`:499`) — child-exited
     `:535`, multiple flock holders `:537`, not-ready `:539,543`, no-permit
     `:545`, phase0 `:548`, startup evidence `:550` each return FIRST — so a
     halt can never mask a genuine failure; the genuine one wins the result.
     What IS lost while halted is the daily PASS token, i.e. the supervisor can
     no longer say "all clear" in one word. Mitigation, no code change: the
     halt is recorded in the AUD-02b evidence note, carried by the
     `halt_enforced` digest line (§6.4), and readable on demand via the CLI's
     `--status` — so a reader separates ruled-halt from outage without
     silencing anything. Pinned as behaviour by tests (9)-(11) below so a
     future edit cannot change it silently.
   - **No safety, settlement, or contract test is weakened or deleted by any
     of the above**; the change is purely additive.

6. **AUD-18 linkage (by id only — `AUD-18-strategy-design-backtest-iterate-programme.md`).**
   AUD-18 owns A1's missing "genuinely independent edge estimate" (real,
   non-synthetic historical venue ladders; not built on the gate-pass
   `P_HOLD` cells ruled a collider). Its output is an **INPUT to a future
   A1-class ruling, never a self-executing re-arm** (ruling §4, §7 item 6).
   Any re-arm additionally requires: the operator's continuous-hunting
   requirement **HUNT-1** (commit `9ddcb8b`; the live `[12:00,17:00)` LST
   gate is a consequence of `P_HOLD_LOWER` covering `hour_lst` ∈ {12..16}
   only) to be MET, and a **NEW registration** — new family id, new
   `trial_id_prefix`, n reset to 0, fresh LD-OBF α, per
   `POST_FORECAST_PHASE_2026-09-20.md` §A-9 item 2 (the correct source; the
   "per L-34" attribution in the plan's own A1 row is a mis-citation the
   ruling corrects). Nothing in AUD-18 is edited by this plan.

## 7. Ordered implementation or verification steps

The parent item (AUD-02) has no RED/GREEN code step (it is a
research-programme status correction); **AUD-02b does**, and it runs FIRST.
Steps for the coordinator/implementer:

0a. **RED:** write the AUD-02b test set (§6.5), mirroring
    `tests/unit/test_clear_family_halt_cli.py`, in a new
    `tests/unit/test_set_family_halt_cli.py` plus additions where noted, and
    watch each FAIL for the right reason (no such module / no such writer):
    (1) after a set, `TrialDayLatch.is_family_halted()` is True AND
    `family_halt_submit_veto(...)()` returns the literal `"family_halt"`, so
    a submit is refused with a NAMED reason and zero permit slots are spent
    — extend the existing end-to-end proof
    `tests/unit/test_current_rung_hold_ambiguous_resolver.py::test_a_family_halt_veto_denies_wait_class_and_spends_zero_permit_slots`
    rather than writing a parallel one; (2) **idempotent re-set** — a second
    run against an already-halted family exits non-zero-mutating, leaves the
    ORIGINAL halt record byte-identical, and writes no second halt payload;
    (3) **clear restores** — `breezy-clear-family-halt` after a set exits
    `EXIT_OK` and `is_family_halted()` is False, i.e. the existing clear path
    is not broken by the new payload shape; (4) **survives relaunch** — the
    halt is written to the durable SQLite store at `resolve_store_path`
    (`clear_family_halt_cli.py:97,104`), so a FRESH `SqliteStateStore` +
    latch opened after close reads halted True, and the runtime-side
    `continuous_family_is_halted` (`trade_supervisor_core.py:345-356`) agrees
    on the same bytes; (5) **refuses while the node holds the lock** —
    `SubmitIntentLockHeld` → `EXIT_REFUSED`, never a forced write; (6)
    **logged AND alerted** — a fake `AlertSink` captures exactly one halt
    payload naming family, reason and evidence sha256, and a sink that
    RAISES does not undo the halt or change the exit code; (7) **the node,
    quote-tape capture and the tally keep running while halted** — asserted
    by the veto's scope: it is consulted only on the submit path, and no
    capture/tally/shadow path reads `FAMILY_HALT_KEY` (assert the key's
    reader set is exactly the veto, the CLIs and the supervisor self-check).
    (8) **store-path mismatch REFUSES** — with a `proc_root` fixture whose
    fake `breezy-trade` process carries a DIFFERENT
    `POLYMARKET_US_EXEC_STATE_DB` (the shape
    `tests/unit/test_exec_state_db_path.py` already builds), the set CLI exits
    `EXIT_REFUSED`, writes NOTHING (`is_family_halted()` stays False in both
    stores), and its message names the env var, never a path value; `NO_NODE`
    and `MATCH` proceed; `DISCOVERY_FAILED` refuses; (9) **`--status` is a
    read-only positive control** — after a set, `--status` reports halted and
    the store-path result, and asserts zero writes (store bytes identical
    before/after) and zero network calls; before a set it reports not-halted;
    (10) **forced submit is REFUSED with the named reason** — a test-harness
    forced submit (unit/integration level, under
    `scripts/ci/run_tests_no_egress.sh`, NEVER against the venue) against a
    halted store is denied and names `family_halt`, independently of any market
    data; (11) **the exit seam is refused identically** — `submit_exit`
    (`exit_wiring.py:246,269-275`) returns without building an order and
    records `_DIAG_FAMILY_HALT` when the family is halted (pin, not a change);
    (12) **pre-set open-position refusal** — with a `StartupPositionEvidence`
    record carrying a non-zero `net_position`, or with `eof_complete=False`, or
    `position_read_refused=True`, the set CLI REFUSES (`EXIT_REFUSED`) and
    writes nothing; a flat, in-bound, `eof_complete=True`,
    `position_read_refused=False` record proceeds; (13) **stale-but-flat
    evidence REFUSES** — a flat record with `eof_complete=True`,
    `position_read_refused=False` whose `ts_ns` (`client.py:917`) is OLDER than
    the stated bound, with the default live GET unavailable (injected fake
    reader raising), exits `EXIT_REFUSED`, writes nothing, and names the
    staleness token — it never degrades to "flat"; (14) **a durable fill or
    exit NEWER than the evidence REFUSES** — a flat, in-bound record plus one
    `DurableFillRecord` whose `ts_event` (`client.py:675`) exceeds `ts_ns`,
    reachable via `iter_fill_records` (`trial_day_latch.py:1102-1137`), exits
    `EXIT_REFUSED` and writes nothing; likewise a `TrialDayRecord.exit_at_ns`
    (`trial_day_latch.py:473`) newer than `ts_ns`; with every such record OLDER
    than `ts_ns`, the fallback proceeds; (15) **a non-eof live page REFUSES** —
    the injected reader returns a well-formed payload with a `positions` dict
    and NO `eof` key (and, as a second case, `eof: false`), and the set CLI
    exits `EXIT_REFUSED`, writes nothing, and names the truncation token; it
    never reads page 1 as the whole book (pins
    `_declared_positions`'s R-4P-1 branch, `client.py:2606-2621`, on the
    DEFAULT path); (16) **a drifted/malformed live shape REFUSES** — payload
    with `positions` absent, `positions` a list instead of a dict
    (`client.py:2595-2605`), and `eof: "true"` as a STRING rather than the
    JSON boolean each raise `ExecutionReportMappingError`
    (`errors.py:208`) at the CLI boundary and yield `EXIT_REFUSED` with
    nothing written — plus one case where `eof is True` but a named slug's
    entry is not a `Mapping` or carries no `netPosition`, which is UNKNOWN =
    open = refuse, never a dropped slug or an assumed zero
    (`client.py:3071-3079`); (17) **an eof page with zero positions is FLAT**
    — `{"positions": {}, "eof": True}` parses clean, is judged flat-and-known
    from the LIVE source, and the set PROCEEDS, with the printed source naming
    the live GET (the positive half, so the gate is not vacuously refusing);
    (18) **a NEGATIVE `net_position` is an OPEN position** — an `eof=True`
    page naming one slug whose `netPosition` is negative (the venue's netting
    of a NO holding as a short YES) exits `EXIT_REFUSED` and writes nothing,
    identically to the positive case in test (12), proving the comparison is
    sign-agnostic (`!= 0`) and not `> 0`; the same assertion is made on the
    fallback path's `StartupPositionSnapshot.net_position`
    (`client.py:876-888`);
    (19) **no instance, no connection** — with `PolymarketUSExecutionClient.__init__`
    monkeypatched to raise, the CLI's read/parse step still succeeds, proving
    `_declared_positions` is called as a bare `@staticmethod` and the CLI never
    constructs a live exec client. Tests (12)-(19) inject a fake positions
    reader and run under `scripts/ci/run_tests_no_egress.sh` — no test ever
    performs the live GET.
0b. **GREEN:** implement §6.5's CLI + `TrialDayLatch` writer; keep the diff
    additive. Run the repo gate (`scripts/ci/run_tests_no_egress.sh`) and
    `lint-imports`; keep the RED→GREEN output as the change artefact.
0c. **Deploy (the one-time act), with the pre-flight BEFORE and AFTER:**
    (i) run `python -m breezy.runtime.exec_state_db_path --check` (or the set
    CLI's `--status`, which runs the same check) and record the token — abort
    unless `MATCH` or `NO_NODE`; (ii) run the set CLI's own pre-set
    open-position read (§6.5) and record the source, verdict and printed
    reason token — if any non-zero `net_position`, or UNKNOWN (stale evidence,
    a newer durable fill/exit record, or a refused read), do NOT set: there is
    no override, so wait for settlement or exit the position first;
    (iii) run `breezy-set-family-halt` for `pm_us_crh_v4` with `--reason`
    naming the ruling and
    `--evidence-path docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`;
    (iv) re-run the store-path check AFTER the set and record the token again,
    so a store that diverged between the two points is caught rather than
    assumed. The node must not hold the flock at that moment, by the tool's own
    refusal (§6.5) — so this is done in the node's own maintenance/relaunch
    window, not by stopping the node mid-flight from this plan.
0d. **Verify with a POSITIVE CONTROL that does not depend on market
    activity, never from the CLI's own exit code** (round-5 defect 2: the
    previous wording — "the next decision that would have submitted records
    `family_halt`" — passes VACUOUSLY on a no-decision day, and today ZERO
    decisions reach pricing, `DECISION_FUNNEL_2026-09-20.md:8-19,347-354`, so
    it would have proved nothing). Required, in this order: (i) `--status`
    (read-only, sends nothing) reports `MATCH`-or-`NO_NODE` AND halted, read
    from the SAME state the veto reads (`trial_day_latch.py:1002` →
    `composition.py:195-228`); (ii) the test-harness forced submit of §7 step
    0a test (10) is refused naming `family_halt` — run under
    `scripts/ci/run_tests_no_egress.sh`, NEVER against the venue; (iii) the
    alerted halt event appears on the `TeeAlertSink` log branch; (iv) capture
    and the tally lines continue advancing in the same node log; (v) the
    once-daily 17:05Z self-check line is
    `FAIL_CONTINUOUS_FAMILY_HALTED`/`self_check_fail_continuous_family_halted`
    — expected and pre-disclosed (§6.5), not an outage. If a real would-be
    submit does record `family_halt` in the log, record it as CORROBORATION;
    its ABSENCE is not evidence either way. Record every item in the AUD-02b
    evidence note.
0e. **Rollback:** `breezy-clear-family-halt --reason ... --evidence-path ...`
    (existing, unchanged, `clear_family_halt_cli.py:70-135`). Clearing is a
    deliberate build-side act with evidence, never automatic — and clearing
    alone does NOT re-arm anything: a re-arm needs a new A1-class ruling
    (§6.6).
1. Apply Amendment C (§6.1-6.2) to `POST_FORECAST_PHASE_2026-09-20.md` as a
   dated addendum, same convention as amendments A/B.
2. Dispatch B3 → B2 → WP-D1 → A0 in the stated order (each already fully
   specified with acceptance criteria in the existing plan; no re-design
   needed here).
3. **A1 is RULED — no ruling request remains.** Record the disposition
   (ii) and cite
   `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`
   wherever the programme's status is reported. A0's evidence pack is no
   longer an A1 precondition; it is retained as a precondition of any
   FUTURE A1-class ruling (ruling §7 item 3) and keeps its existing
   acceptance criterion unchanged.
4. Carry §6.4's ROUND-4 supersession to whoever implements or next revises
   AUD-03: the REQUIRED bullet in AUD-03's own §8 should become the
   `halt_enforced` line, not the now-moot A1-open-age line. This plan does
   not edit AUD-03; it is a named dependency with a stated fallback (§6.4).
5. **The ruling is (ii), so the re-evaluation branch is the live one:** the
   remaining work packages (B1, WP-T1, the C-branch) are re-evaluated for
   relevance against a family that may not send (a halted family may not
   need a permit-lapse detector tuned to its cadence, for instance). That
   re-evaluation is a small follow-on planning task, not performed here.
   Note explicitly: WP-B0-class alert egress and the KILL clock stay in
   force under (ii) — the ruling halts ORDER SUBMISSION only, not the node,
   capture, shadow valuation or the clock.

## 8. Measurable acceptance criteria and required evidence

- Amendment C is present in `POST_FORECAST_PHASE_2026-09-20.md`, citing both
  commit SHAs, and the widened A1 precondition text is present verbatim.
- A0's evidence pack exists as a dated doc under
  `docs/evidence/venue/polymarket_us/` per the existing A0 acceptance
  criterion (unchanged from the base plan).
- A1 produces a SIGNED ruling doc under `docs/evidence/` (matching the base
  plan's acceptance: "if (iii) a new `family_manifest` +
  RED-first `assert_family_only`... if (i)/(ii) a `family_halted` state +
  test that the node refuses to arm it").
- **AUD-02b acceptance (all required, evidence named):**
  (a) RED→GREEN output for all nineteen tests in §7 step 0a is captured in the
  change artefact, each RED failing for the stated reason;
  (b) `breezy-set-family-halt` exists as a console script and its
  `--reason`/`--evidence-path`/flock-refusal/exit-code behaviour matches
  `clear_family_halt_cli.py`'s, asserted by test, not by inspection;
  (c) the diff adds NO new halt key, state, or veto — assert
  `FAMILY_HALT_KEY`'s reader/writer sets before and after, and that
  `trade_supervisor_core.py:139`'s literal still matches
  `trial_day_latch.py:291` byte-for-byte (the existing pin test still
  passes);
  (d) the one-time set for `pm_us_crh_v4` is executed and evidenced by a
  node-log excerpt showing the alerted halt event AND the `family_halt` veto
  reason on the next would-be submit, with capture and tally lines
  continuing in the same excerpt (§7 step 0d);
  (e) `scripts/ci/run_tests_no_egress.sh` and `lint-imports` pass on the
  slice;
  (f) no safety, settlement or contract test is modified or deleted;
  (g) the set CLI REFUSES on a store-path `MISMATCH`/`DISCOVERY_FAILED` and
  writes nothing, asserted by test (8), and the deployment record carries the
  `node_store_path_check` token from BEFORE and AFTER the set (§7 step 0c
  items (i) and (iv)), each `MATCH` or `NO_NODE`;
  (h) the positive control is recorded: `--status` reports halted from the
  node-resolved store, and the test-harness forced submit is refused naming
  `family_halt` — both independent of market activity, neither run against the
  venue (§7 step 0d items (i)-(ii));
  (i) the pre-set open-position read is recorded with its SOURCE (the default
  live read-only GET, or the durable-evidence fallback together with its
  freshness verdict) and its result: flat-and-known → set; any non-zero
  `net_position`, or UNKNOWN (stale `ts_ns`, a newer durable fill or exit
  record, a refused read, `eof_complete=False`, `position_read_refused=True`)
  → REFUSED, with NO override available (§6.5); the printed source/verdict/
  reason token is quoted in the evidence note — and the token distinguishes
  `LIVE_GET_FAILED:<exception class>` (auth / timeout / non-2xx / payload refusal) from
  `FALLBACK_CHOSEN:<reason>` (live GET never attempted), so a later reader can tell connectivity
  trouble from a design choice, asserted by a case in test (13) for each token — which also states that the exit
  seam is vetoed while the halt stands and records the clear → exit → re-set
  sequence (§6.5); asserted by tests (12)-(14); and, on the DEFAULT live path,
  the payload is parsed through `PolymarketUSExecutionClient._declared_positions`
  (`client.py:2592-2622`) so that `eof is not True` or a drifted shape REFUSES
  and a truncated page is never read as flat, with the flat/open decision
  sign-agnostic (`!= 0`, a NEGATIVE `net_position` is open) — asserted by
  tests (15)-(18);
  (j) the once-daily 17:05Z `FAIL_CONTINUOUS_FAMILY_HALTED` self-check outcome
  is pre-disclosed in the evidence note and pinned by tests (9)-(11); no new
  `SelfCheckResult`, no change to `_SELF_CHECK_PASS_RESULTS`, and no change to
  the FAIL→detail map appears in the diff;
  (k) `--status` performs no write and no network call, asserted by test (9).
- **The parent plan's own acceptance is met once Amendment C is authored (a
  documentation deliverable) and the A1 disposition is recorded (§7 step 3;
  the ruling artefact already exists)** — this plan does not itself produce a trading-code diff,
  and (corrected per round-2 review) its own DONE status is deliberately
  independent of whether AUD-03 has shipped, because the §6.4 escalation
  line's actual delivery and enforcement is AUD-03's acceptance criterion
  (§8, Revision 3), not this plan's. This asymmetry is intentional, not an
  ownership gap: exactly one plan (AUD-03) must be blocked on shipping the
  line; making BOTH plans block on it would create the circular dependency
  the round-2 review confirmed does not exist today.

## 9. Validation: failure cases, integration behaviour, autonomous operation

- **Failure case — AUD-02b never lands (the live risk this round):** the
  ruling stays UNENFORCED, and today's zero-take state remains an ACCIDENT
  of two data-quality gates rather than a control. If either gate is fixed
  by independent work, `pm_us_crh_v4` can send an order onto a confirmed
  biased table with no further human decision. This is the failure case
  AUD-02b's P0 exists to close; it is stated here as the honest interim,
  not as an acceptable steady state.
- **Failure case — the set CLI writes a payload the existing readers reject
  or mis-read:** contained by design — `is_family_halted` is fail-closed
  (anything that is not the cleared sentinel IS halted,
  `trial_day_latch.py:301`) and `_decode_halt_payload` never raises
  (`:304-320`), so a malformed payload halts rather than un-halts. Test (3)
  proves the clear path still works against the new payload, so fail-closed
  never becomes unclearable.
- **Failure case — the tool is run while the node holds the flock:** it
  REFUSES (`EXIT_REFUSED`) rather than writing behind the node's back
  (`clear_family_halt_cli.py:126-131`); test (5).
- **Failure case — the alert sink is down or raises:** the halt still
  happens; `emit_alert`'s containment means a broken reporter can never undo
  it (test (6)). The node-log branch of `TeeAlertSink` runs FIRST, so local
  diagnosability does not depend on the webhook.
- **Failure case — A1 is re-opened informally:** it cannot be. A re-arm
  needs a NEW A1-class ruling plus a new registration plus HUNT-1 (§6.6);
  clearing the halt alone is not a re-arm, and the clear CLI requires a
  written reason and an evidence artefact.
- **Failure case (historical, now resolved) — A1 ruling never happens:** A1
  HAS ruled (ii). The "no family has a proven edge" verdict in PROGRESS.md
  remains true, which is the honest state under (ii). The §6.4 escalation line, now owned and
  enforced by AUD-03 §8, ensures this indefinite state is VISIBLE on every
  digest run rather than silently aging out of attention, closing the
  round-1 "rots silently" risk — with the round-4 correction that the line's
  CONTENT is now `halt_enforced`, not A1-open-age (§6.4), and that its
  delivery is a convenience surface, not the sole carrier: AUD-02b's own
  alerted halt event and the node log carry it independently of AUD-03.
- **Failure case — the CLI writes to a DIFFERENT store than the live node
  (round-5 defect 1):** the previously largest silent hole — a green
  `EXIT_OK`/"halted" over an untouched node store. Closed by the mandatory
  `node_store_path_check` pre-flight inside the CLI (§6.5;
  `exec_state_db_path.py:142-182`), refusing on `MISMATCH` AND
  `DISCOVERY_FAILED`, plus the before/after tokens in §7 step 0c and test (8).
  Residual: `NO_NODE` is accepted (the set is legitimate with no node
  running), so the after-set check is re-run in the node's next window.
- **Failure case — verification passes vacuously on a no-decision day
  (round-5 defect 2):** today ZERO decisions reach pricing
  (`DECISION_FUNNEL_2026-09-20.md:8-19,347-354`), so "the next would-be submit
  logged `family_halt`" can never fire and would have been mistaken for
  enforcement. Closed by §7 step 0d's market-independent positive control
  (`--status` over the node-resolved store + a test-harness forced submit
  refused with the named reason, under `scripts/ci/run_tests_no_egress.sh`,
  never against the venue).
- **Failure case — a position is open when the halt is set (round-5 defect
  3a):** the exit seam is vetoed too (`exit_wiring.py:246,269-275`), so that
  position would have NO automated exit. Closed by the mandatory pre-set
  open-position read and the refuse-to-set-while-open rule (§6.5), with
  UNKNOWN treated as open and NO override (round-6 defect 2): the set simply
  cannot proceed while a position is open or unknown, so the only route is
  let-it-settle-or-exit-first, and thereafter the documented
  clear → exit → re-set sequence, never an exit-only bypass. The same veto will
  block a LATER-armed exit family while the halt stands — disclosed, not
  discovered.
- **Failure case — the position evidence is STALE and reads "flat" (round-6
  defect 1):** `StartupPositionEvidence` is written at the END of `_connect`
  and after a resolver terminal-zero resolution (`client.py:3102-3133`,
  `:398-401,908-910`), never at fill or exit time, so a node that filled or
  exited after its last reconnect could show `net_position` zero and let the
  set proceed over an open position — the exact hole this check exists to
  close, reopened by its own preferred data source. Closed by making the live
  read-only GET the DEFAULT (`polymarket_us_auth_smoke.py:164,1019`) and
  bounding the fallback twice: a `ts_ns` age bound, plus a cross-check against
  the records that ARE written at fill/exit time (`iter_fill_records`,
  `trial_day_latch.py:1102-1137`; `record_exit`, `:918-966`). Stale, newer
  fill, newer exit, or refused read ⇒ UNKNOWN ⇒ REFUSE, printed with its source
  and reason token, never silent; tests (13)-(14), §8(i). Residual, stated: the
  fallback's instrument set cannot be proven complete (the store has no prefix
  scan), which is why it is the fallback and not the default.
- **Failure case — the DEFAULT live GET returns a PARTIAL page (round-6
  MATERIAL):** `GetUserPositionsResponse` is cursor-paginated and this client
  does not follow a cursor, so a first page that happens to show no open
  position but is not `eof=true` would read as "flat" and let the halt proceed
  over an under-reported book — the same silent-truncation class R-4P-1 closed
  on the durable-evidence path, reopened on the now-default live path. Closed
  by parsing the live payload through the SAME
  `PolymarketUSExecutionClient._declared_positions`
  (`client.py:2592-2622`, `@staticmethod` on the class at `:1085`) the node's
  own evidence writer uses: `eof is not True` ⇒ `ExecutionReportMappingError`
  (`errors.py:208`) ⇒ UNKNOWN ⇒ `EXIT_REFUSED`. The same seam closes venue
  SHAPE DRIFT (absent/non-dict `positions`, a string `"true"` for `eof`, a
  non-`Mapping` slug entry or a missing `netPosition`, projected per
  `client.py:3071-3079`): each is a named refusal, never a best-effort parse
  and never an assumed zero. Tests (15)-(17), §8(i). Residual, stated: because
  the cursor is not followed (R-4P-2 deferred), a genuinely multi-page book can
  NEVER be judged flat by this check — it refuses until the book fits one
  terminal page, which is the fail-closed direction.
- **Failure case — a NO holding reads as flat because it nets SHORT:** the
  venue nets a NO leg as a negative (short-YES) `net_position`, so a `> 0` or
  truthiness comparison would pass it over as flat. Closed by the sign-agnostic
  rule "any non-zero net position on any slug = open" (`Decimal(net) != 0`),
  applied on BOTH the live and fallback sources and pinned by test (18) rather
  than carried as prose (round-6 MINOR).
- **Failure case — the wait for settle-or-exit defers the halt (round-6
  MINOR):** with no override, an open position blocks the set. Bounded and
  accepted: weather markets settle daily, and the family reaches pricing on
  zero decisions today (`docs/evidence/DECISION_FUNNEL_2026-09-20.md:1,19`), so
  the wait state is near-unreachable. A NEW fill during the wait changes
  nothing structurally — the check is not a latch; it re-runs, sees the
  position, refuses again, and the halt is set at the first flat-and-known
  moment. Residual, stated plainly: the A1 ruling stays UNENFORCED for the
  duration of the wait (the pre-existing status quo, not a new exposure), and a
  repeatedly-filling family could defer the set indefinitely until the operator
  exits the position deliberately.
- **Failure case — the halt is mistaken for an outage, or masks one (round-5
  defect 3b):** verified bounded. The self-check fires ONCE per day at 17:05Z
  (`trade_supervisor_core.py:34,45,765,777`; single call site
  `trade_supervisor.py:1485`) with a DISTINCT detail
  `self_check_fail_continuous_family_halted` (`:216,293-295`), and the halted
  branch is evaluated LAST (`:551-552`, after `:535,537,539,543,545,548,550`),
  so a genuine failure always wins the result and is never masked. The cost is
  the loss of the daily PASS token while halted — accepted, disclosed in the
  evidence note, and offset by the `halt_enforced` digest line (§6.4) and the
  CLI's `--status`. No existing check is weakened to reduce the noise.
- **Integration:** AUD-02b touches exactly one runtime path — the
  already-wired submit-time veto (`composition.py:195` via
  `app/trade.py:260`) — by supplying the state it reads. Nothing else
  changes; §6.4 adds one field to a digest owned and implemented by AUD-03.
- **Autonomous operation:** once the halt is set, the node's autonomous
  behaviour is: keep running, keep capturing, keep valuing in shadow, keep
  the KILL clock, and refuse every submit with the named reason
  `family_halt` — **every submit of EITHER kind: entry AND exit**
  (`exit_wiring.py:246,269-275`), which is why §6.5's pre-set open-position
  check is mandatory — plus one WARN self-check FAIL per day at 17:05Z with
  the distinct `self_check_fail_continuous_family_halted` detail. The halt NEVER self-clears — clearing is a deliberate
  build-side act with a written reason and an evidence artefact
  (`clear_family_halt_cli.py:13-19`), which is the correct asymmetry for a
  stop.

## 10. Deployment, observability, rollback

**AUD-02b has a real deployment** (§7 steps 0c-0e): the one-time
`breezy-set-family-halt` run for `pm_us_crh_v4`, executed in the node's own
maintenance/relaunch window because the tool refuses while the node holds the
flock; gated by a `node_store_path_check` token BEFORE and AFTER the set and
by the pre-set open-position read (§7 step 0c); verified by the
market-independent positive control of §7 step 0d (`--status` over the
node-resolved store + a forced submit refused naming `family_halt`, under
`scripts/ci/run_tests_no_egress.sh`) together with the node log (alerted halt
event, capture/tally still advancing, and the expected once-daily
`FAIL_CONTINUOUS_FAMILY_HALTED` self-check line), never from the CLI's exit
code alone and never from a would-be-submit log line that a no-decision day
can never produce; rolled back by the existing, unchanged
`breezy-clear-family-halt`. Observability afterwards is the `halt_enforced`
digest line (§6.4, AUD-03-dependent) plus the node log's veto reason and the
once-daily self-check detail, and the CLI's own read-only `--status` on demand
(all three independent of AUD-03). **Rollback caveat, stated because the exit
seam shares this halt:** clearing is ALSO the only way to let a closing order
through — so if a position is open, the sequence is clear → let the exit seam
submit → re-set, each step with its own written reason and evidence artefact;
clearing still re-arms nothing (a re-arm needs a new A1-class ruling, §6.6).

The PARENT item has no deployment — its only artefact is a documentation
amendment. Observability and rollback are not applicable to a planning/status
correction; the actual
work packages this item schedules (A0/A1/B1-B3/C0-C2/WP-D1/Q1/T1) each carry
their own deployment/observability/rollback requirements already specified in
`POST_FORECAST_PHASE_2026-09-20.md` and are not restated here. The §6.4
escalation line's own deployment/observability/rollback is AUD-03's, since
AUD-03 owns, implements, and (per Revision 3) enforces the digest's
acceptance around it.

## 11. Relationship to portfolio-level ROI and evaluation

This item does not itself move ROI directly. It is the governance step that
determines whether further engineering investment in `pm_us_crh_v4` (or any
successor) is justified at all — and that step has now COMPLETED with a
ruling of (ii). Its ROI contribution is therefore loss avoidance, not gain:
AUD-02b prevents unpriced orders from a family with no demonstrated edge and
a confirmed NO-side bias. That is a plausible, not a demonstrated, saving —
no figure is claimed. Forward ROI on this surface now depends entirely on
AUD-18 producing a genuinely independent edge estimate (§6.6), which is a
separate item with its own acceptance criteria. Historically evaluated by:
whether A1 actually ran and produced a signed ruling within a bounded time (operator/strategy-lead
cadence, not specified here, but now VISIBLE via §6.4's digest line, whose
delivery AUD-03 §8 now enforces rather than merely proposes), and — if
(iii) — whether the resulting C2 readout (already gated on a
>=0.25/station-day qualifying rate not currently met) ever produces a CI
strictly above zero. If it never does, the correct portfolio conclusion,
stated plainly by the existing plan's own critical-path note, is "**nothing
arms**" and PM.us daily-high rungs close as a programme.

## 12. Assumptions, unresolved questions, blockers

- **Assumption:** `POST_FORECAST_PHASE_2026-09-20.md`'s peer-reviewed
  content (amendments A and B) remains binding and is not re-litigated here;
  this plan only adds Amendment C. Its leak-safety/pre-registration/sample-
  size protocol was independently verified this round (§3) rather than
  merely assumed.
- **RESOLVED, was the plan's headline BLOCKER: A1 itself.** RULED
  2026-09-21 as **(ii) STOP TRADING THIS SURFACE**, peer-ENDORSED with no
  required change —
  `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`
  (Revision 3), review
  `docs/evidence/reviews/RULING_A1_review_2026-09-21.md`. (iii) is rejected
  for now; (i) is folded into (ii) with a stated reopening path. **No
  strategy-lead blocker remains on this plan.**
- **Open, and the only thing standing between the ruling and reality:**
  AUD-02b is not built. Until it lands AND is run, `pm_us_crh_v4` is NOT
  halted by any mechanism — the honest interim, stated in the present tense
  (ruling §4). This is scoped work in this plan (§6.5/§7), not a blocker on
  someone else.
- **Named dependency (not a blocker):** AUD-03 must swap its REQUIRED §8
  acceptance bullet from the A1-open-age line to the `halt_enforced` line
  (§6.4). Fallback stated there; AUD-02b's visibility does not depend on it.
- **Named dependency (not a blocker): AUD-18** owns the genuinely
  independent edge estimate (§6.6). Its output is an input to a future
  A1-class ruling, never a re-arm.
- **Standing invariant, explicitly NOT a blocker on this plan:**
  live-trading enablement of any future family is operator-only and is not
  requested, valued, or touched here. The operator has stated the budget
  ceiling is already established; the previous "operator, budget-ceiling
  only" blocker bullet is DELETED as stale — it was conditioned on a future
  (iii) arming, moot under (ii), and no value is stated anywhere in this
  plan.
- **Open, flagged not fixed:** `docs/core/PROGRESS.md`'s WP-R1 entry (lines
  103-128) describes the calibration defect as "not yet applied" though the
  fix landed `e83fc5c` on 09-20. This plan is PLANNING ONLY and does not edit
  PROGRESS.md; the coordinator should apply a PROGRESS trim separately.
- **Open:** whether B1/B2/B3/C-branch/WP-D1/Q1/T1 remain the right shape
  given the calibration-defect finding did not exist when they were
  specified — none of them were designed with knowledge that the pricing
  model itself might be retired. Re-scoping them is explicitly deferred
  (§7 step 5), not performed here, to avoid speculative rework ahead of the
  A1 ruling.
- **RESOLVED, was open:** whether `bcb82d6`/`e3e8ac6` register
  `pm_us_crh_v4` consistent with A-9's invariants. The ruling performed the
  check itself (§3.8): clause 1 (θ constant `Decimal("0.06")`) HOLDS; clause
  2 ("new `trial_id_prefix`") is LITERALLY NOT MET but is **by design** —
  prefix-sharing across successive families on one latch is expected, and
  `d0_climate_day` + the predecessor's `terminal_climate_day` are the real
  discriminant, mechanically enforced by `assert_family_only`; clause 4
  HOLDS structurally. **Recorded here so the clause-2 imprecision is not
  re-litigated as a defect later.** Still NOT verified by anyone: clause 3
  (residual sidecar is family-keyed) and clause 5's raw-log re-derivation —
  carried forward as open items for any FUTURE registration, where A-9 item
  2 must be satisfied in full.
- **RESOLVED per round-2 review, was open:** ownership of the §6.4
  escalation line's delivery. Now owned by AUD-03 §8 (Revision 3), with a
  named fallback there if AUD-03 is implemented before this plan lands. See
  §6.4 above.

## 13. Review history

**Round 1** (two independent reviewers; both scored "implementation
specificity" on a /20 scale though the rubric caps that criterion at 15 —
round-1 totals below are as reported by each reviewer and are NOT comparable
to the 20/20/15/20/15/10 rubric; they are superseded by the Revision 2
self-score at the end of this section, which uses the correct caps):

- **mle-reviewer: 85/100 (as reported).** MINOR: the plan widens A1's
  precondition but never cites whether the base plan's own A0/A1 acceptance
  criteria actually require pre-registration, a fixed sample-size rule, and
  leak-safety before any new edge estimate can pass — left as an inherited,
  unstated assumption. MINOR (inherent, not fixable here): no owner/SLA
  named for A1 beyond "strategy lead."
  **Disposition: ACCEPTED, first.** §3 gained a new subsection citing the
  exact `POST_FORECAST_PHASE` sections (A1's row, C1/C2's rows, §4's
  blanket rule) that already guarantee pre-registration (n reset to 0 per
  L-34, fresh trial_id_prefix, fresh LD-OBF α), a fixed sample-size/stopping
  rule (n≥30, 21-day capture abandonment, CI-excludes-zero gate), verified
  directly against current source this round, not merely trusted. Second
  MINOR: **not actionable by this plan** (correctly named by the reviewer as
  inherent) — no change made; it remains a named, not a resolved, gap in
  §12.

- **prediction-market-reviewer: 90/100 (as reported).** MINOR: no
  escalation/expiry mechanism proposed for the A1 blocker, given this
  repo's own prior cost from exactly this "correct finding, undelivered"
  failure shape. MINOR: `bcb82d6`/`e3e8ac6` A-9-consistency question flagged
  open with no named owner.
  **Disposition: ACCEPTED, both.** §6.4 (new) specifies an escalation
  mechanism reusing only already-shipped infrastructure: AUD-03's digest
  (once shipped) carries a per-day "A1 open, N days" line whenever
  `pm_us_crh_v4` is live and unruled — no new alert transport, per the
  brief's "through the existing alert/digest path, no new infrastructure"
  instruction. §12 now names A1 itself as the owner of the A-9-consistency
  check, on a ruling of (iii), per the reviewer's own suggested deferral.

**Revision 2 self-score** (correct caps: 20/20/15/20/15/10):
- Fidelity to audit gap and completeness: 18/20 — now explicitly verifies
  (rather than assumes) the base plan's leak-safety/pre-registration/
  sample-size protocol, and adds the escalation mechanism the brief
  specifically required; still does not re-verify every downstream work
  package line-by-line (unchanged from round 1, reasonable for a status
  item).
- Technical correctness and evidence grounding: 20/20 — every claim,
  including both round-1-required citations, is now grounded in text
  verified directly against current `POST_FORECAST_PHASE_2026-09-20.md`
  source this round.
- Implementation specificity and feasibility: 14/15 — Amendment C text and
  the §6.4 digest-field requirement are both concrete and pasteable/
  specifiable; one point held back because §6.4's exact digest wire-format
  is deliberately left to AUD-03's own implementer.
- Acceptance criteria and validation quality: 18/20 — the new §8 bullet on
  the A1-open-age digest line makes the escalation mechanism itself
  verifiable, not just proposed; the underlying A1-actually-rules criterion
  is still outside this plan's power to guarantee (inherent, not a
  weakness of this plan).
- Autonomous operation, failure handling, recovery: 14/15 — correctly
  treats "A1 never rules" as an acceptable indefinite state, now paired
  with a visibility mechanism instead of a silent one.
- Portfolio alignment, scope, dependencies: 10/10 — explicit dependency on
  AUD-01a stated and justified; escalation mechanism correctly routed
  through AUD-03 rather than inventing new infrastructure, honoring both
  items' independence.

**Revision 2 total: 94/100. Status: NOT READY — round 2 review pending.**

**Round 2** (two independent reviewers, blind, against Revision 2):

- **mle-reviewer: 95/100.** Both round-1 dispositions re-verified. No new
  MATERIAL defect found; specifically checked (and confirmed) that the
  escalation mechanism reuses no new infrastructure, that no new
  pricing/serving claim was introduced, and that no circular dependency
  exists between AUD-02 and AUD-03. Docked 5 points total, all named as
  inherent to this plan's own scope, not defects: fidelity 19/20 ("still
  does not re-verify every downstream work package B1-B3/C0-C2/WP-D1/Q1/T1
  line-by-line, which is reasonable for a status/fold-in item that does not
  touch their content"); implementation specificity 14/15 ("the exact
  digest wire-format for the A1-age line is deliberately left to AUD-03's
  implementer... not a defect, but it does cap specificity for a plan whose
  only executable content is documentation"); acceptance criteria 18/20
  ("the underlying 'A1 actually rules' criterion remains outside this
  plan's power to guarantee by design, correctly named as inherent rather
  than a plan defect"); autonomous operation 14/15 ("unaffected by this
  round's check," carried from round 1's same inherent characterization).
  Required changes to reach 100: "None MATERIAL. Optional tightening only" —
  naming what happens if AUD-03 is never implemented at all, explicitly
  characterized by the reviewer as "a small, explicitly-scoped residual
  risk... not a defect in AUD-02's own text." **Disposition: addressed in
  this revision's §6.4/§12 as the named fallback ("if AUD-02 lands and
  AUD-03 is never implemented at all, the escalation line simply never
  ships") — stated explicitly rather than left implicit, closing even the
  reviewer's own optional suggestion.**
- **prediction-market-reviewer: 84/100.** New MATERIAL finding: the §6.4/§8
  escalation mechanism is specified but UNOWNED — AUD-02's own §8 (Revision
  2) stated its acceptance does not require AUD-03 to have shipped, and
  AUD-03's own §8 (Revision 2) did not list the line as a required
  criterion either, so both plans could independently reach 100% of their
  own stated acceptance while the escalation feature — whose whole purpose
  is preventing the "correct finding, undelivered" failure this repo has
  already paid for twice — never ships. Required change: make it a
  required, testable acceptance criterion in whichever plan implements it,
  with a named fallback if the two plans land out of order.
  **Disposition: ACCEPTED.** §6.4 rewritten (this revision) to state the
  ownership resolution exactly as the coordinator specified: AUD-03 §8
  (Revision 3) now carries the REQUIRED, conditional acceptance criterion;
  this plan (AUD-02) depends on AUD-03 by id, one-directionally, and names
  the fallback (a standalone, owned follow-up ticket filed by AUD-03's
  implementer if AUD-03 lands before AUD-02, per AUD-03 §8/§12) explicitly
  in both §6.4 and §12.

**Withheld-points disposition (coordinator requirement):** the
mle-reviewer's round-2 -5 points are fully itemized above and every one is
explicitly named by the reviewer as inherent to this plan's status-only
scope (re-verification breadth, digest wire-format deferred to AUD-03,
the A1-ruling-itself criterion being outside any plan's power to guarantee,
and an unaffected carry-forward autonomous-operation characterization) —
none names a fixable defect in this plan's own text beyond the optional
tightening already addressed above. The prediction-market-reviewer's -16
points are the single MATERIAL ownership defect, now closed by this
revision's §6.4/§8/§12 rewrite.

**Revision 3 self-score** (correct caps: 20/20/15/20/15/10; conservative):
- Fidelity to audit gap and completeness: 19/20 — the ownership gap is
  closed with an explicit, named resolution (owner, dependency direction,
  and fallback all stated); one point held back for the same inherent
  reason the mle-reviewer named (does not re-verify every downstream WP).
- Technical correctness and evidence grounding: 20/20 — the resolution text
  is cross-checked against AUD-03's own Revision 3 §8/§12 (written in the
  same pass) for consistency; no contradiction between the two plans'
  statements of the same ownership fact.
- Implementation specificity and feasibility: 14/15 — unchanged from
  Revision 2; the digest wire-format remains, correctly, AUD-03's own
  implementer's call.
- Acceptance criteria and validation quality: 19/20 — the §8 bullet now
  states explicitly, not merely implies, that this plan's DONE status is
  intentionally independent of AUD-03's shipping timeline, and why that
  asymmetry (rather than a symmetric mutual dependency) is the correct,
  non-circular resolution; one point held back because the A1-ruling-itself
  criterion remains inherently outside this plan's power, as before.
- Autonomous operation, failure handling, recovery: 14/15 — the "rots
  silently" risk is now closed by an ENFORCED (not merely proposed)
  mechanism on AUD-03's side, with the residual "AUD-03 never lands" case
  now named explicitly rather than left as a gap; one point held back
  because that residual case genuinely leaves the escalation unshipped in
  one scenario, honestly stated rather than resolved away.
- Portfolio alignment, scope, dependencies: 10/10 — the AUD-01a and AUD-03
  dependencies are both stated by id, correctly directional, and
  cross-verified non-circular against AUD-03's own text.

**Revision 3 total: 96/100. Status: NOT READY — round 3 review pending.**

**Round 4 (2026-09-21) — revision log, coordinator-directed, post-ruling.**
No reviewer scored this round; the edits below are factual consequences of a
ruling that was itself independently peer-reviewed. Changes made:
1. **A1 marked RULED (ii), ENDORSED, everywhere it was described as open or
   blocking** — title, §1(d), §2, §3 ("Concrete gap" restated), §4
   (execution order; `A1 (the ruling)` removed from the chain), §5
   (exclusion reworded to "RE-deciding A1"), §6.4, §7 steps 3-5, §8, §9,
   §11, §12 — each citing
   `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` and its
   review trail.
2. **Added §6.5, AUD-02b: enforce the A1 ruling**, as a full buildable scope
   (set-halt CLI mirroring the existing clear CLI on the EXISTING halt
   state/veto; RED-first tests; deployment, verification and rollback in §7
   steps 0a-0e; acceptance in §8; failure cases in §9; deployment in §10).
   Every file:line in §6.5 was re-verified against source this round via
   codegraph, not carried from the ruling on trust.
3. **Added §6.6, the AUD-18 linkage** (by id only): AUD-18 owns the
   genuinely independent edge estimate; its output is an input to a future
   A1-class ruling, never a self-executing re-arm; any re-arm also needs
   HUNT-1 met and a NEW registration per A-9 item 2.
4. **Priority re-assessed:** AUD-02b set to **P0** and ordered first, with
   the safety justification stated in §4; the parent item stays P1. The
   AUD-01a sequencing dependency is recorded as historical.
5. **§6.4's A1-open-age digest requirement declared MOOT** (its condition is
   now false) and replaced in content by a `halt_enforced: yes|no` line read
   from the same halt state the veto reads. Because changing AUD-03's
   REQUIRED §8 bullet would require editing AUD-03, that is recorded as a
   NAMED DEPENDENCY with an explicit fallback, not performed here.
6. **§12 rewritten to list only what genuinely remains.** The A1 blocker is
   marked RESOLVED; the A-9-consistency item is marked RESOLVED with the
   clause-2 finding recorded and clauses 3/5 carried forward; the stale
   "operator, budget-ceiling only" blocker is DELETED (the operator has
   stated the ceiling is established; no value is stated anywhere in this
   plan); live-trading enablement is recorded as a standing operator-only
   invariant, explicitly not a blocker on this plan.
7. **Honest interim stated in §3, §9 and §12:** until AUD-02b lands and is
   run, the ruling is UNENFORCED and today's zero-take state is accidental,
   not designed.
No score is claimed for this round; the readiness status is unchanged from
whatever the review record establishes, and nothing here asserts readiness.

**Round 5 (2026-09-21) — revision log, responding to the two round-4 review
records** (`reviews/AUD-02-r4-silent-failure-hunter.md`, 79/100;
`reviews/AUD-02-r4-prediction-market-reviewer.md`, 80/100). All three MATERIAL
defects were re-verified against source before editing, not taken from the
reviews on trust; every file:line added this round was read this round. Edits
are confined to AUD-02b (§4 P0 qualification, §6.5, §7 steps 0a/0c/0d, §8,
§9, §10) — no renumbering, no scope removed.
1. **Defect 1 (store-path mismatch), FIXED.** §6.5 now REQUIRES
   `node_store_path_check` (`exec_state_db_path.py:142-182`) inside the set
   CLI, refusing unless `MATCH`/`NO_NODE`, and records that the CLEAR CLI does
   NOT do this today (`clear_family_halt_cli.py:97,104`) — a gap closed on the
   set side, not inherited. §7 step 0c runs the check before AND after the
   set; RED test (8) added; §8(g) and a §9 failure case added.
2. **Defect 2 (vacuous verification), FIXED.** §7 step 0d's market-dependent
   check is REPLACED by a positive control that sends nothing: a read-only
   `--status` mode reading the SAME state the veto reads, plus a test-harness
   forced submit that must be refused naming `family_halt`, run under
   `scripts/ci/run_tests_no_egress.sh` and never against the venue. RED tests
   (9)-(10); §8(h),(k); §9 failure case; §10 updated.
3. **Defect 3a (exit seam vetoed too), FIXED and DISCLOSED.** §6.5 adds a
   mandatory pre-set open-position read from the node's own durable
   `StartupPositionEvidence` (`client.py:900-927,401,3120-3132`) with a
   refuse-to-set-while-open rule, UNKNOWN treated as open, the NO-leg sign
   applied, and an explicit "do not assume flat, CHECK" instruction; the
   later-armed-exit consequence and the clear → exit → re-set sequence are
   stated in §6.5, §9, §10; RED tests (11)-(12); §8(i).
4. **Defect 3b (self-check alerts), VERIFIED — and the review's premise
   CORRECTED.** It is NOT "repeatedly, each tick": SELF_CHECK is a once-daily
   17:05Z phase (`trade_supervisor_core.py:34,45,765,777`, one call site
   `trade_supervisor.py:1485`) already carrying a DISTINCT detail
   `self_check_fail_continuous_family_halted` (`:216,293-295`) and evaluated
   LAST (`:551-552`), so it cannot mask a genuine failure. **Decision: accept
   it as-is; add no new `SelfCheckResult` and no dedup layer** — that would
   mean editing `_SELF_CHECK_PASS_RESULTS`/the FAIL→detail map, i.e. weakening
   a live safety check to quieten a deliberate stop. The one real cost (no
   daily PASS token while halted) is stated with its mitigation; pinned by
   tests (9)-(11) and §8(j).
5. **§4, §8(a), §9, §10 re-checked in light of the above:** the P0 stands but
   is qualified by the pre-set position check; the test count is corrected
   from seven to twelve and the §8 lettering extended (a)-(k) with no
   renumbering of existing items.
No score is claimed for this round and no readiness is asserted; round-5 review
is pending.



**Round 6 (2026-09-21) — revision log, responding to the two round-5 review
records** (`reviews/AUD-02-r5-silent-failure-hunter.md`, 84/100;
`reviews/AUD-02-r5-prediction-market-reviewer.md`, 93/100). Both defects were
re-verified against source before editing; every file:line added this round was
read this round. Edits are confined to AUD-02b (§6.5, §7 steps 0a/0c, §8, §9)
— no renumbering, no scope removed.
1. **MATERIAL (stale position evidence), FIXED.** Confirmed in source that
   `StartupPositionEvidence` is written only at the end of `_connect`
   (`client.py:3102-3133`) and on resolver terminal-zero resolution
   (`:908-910`), with one row and no freshness contract (`:398-401`) — so a
   post-reconnect fill or exit is invisible to it. §6.5 now makes the live
   read-only positions GET (`polymarket_us_auth_smoke.py:164,1019`) the
   DEFAULT — justified because it is the only source with no staleness
   question, it is a GET not an order, and it does not cross the NO-SEND
   execution-egress firewall, which is the OS-level block
   `scripts/ci/run_tests_no_egress.sh` (`:2,55,60,64`) places around the TEST
   suite — and demotes the durable evidence to a FALLBACK that is usable only
   when `ts_ns` (`client.py:917`) is inside a stated, printed bound AND no
   `DurableFillRecord.ts_event` (`:675`, reachable via
   `TrialDayLatch.iter_fill_records`, `trial_day_latch.py:1102-1137`) and no
   `TrialDayRecord.exit_at_ns` (`:473`, written by `record_exit`, `:918-966`)
   is newer than it. UNKNOWN = open = refuse, printed with source, verdict and
   reason token, never silent. RED tests (13)-(14) added, §7 step 0c(ii)
   tightened, §8(i) rewritten, and a §9 failure case added; the fallback's
   unprovable instrument-set completeness is stated as a residual, which is
   itself the reason it is not the default.
2. **MINOR (unenforceable override), REMOVED, not re-specified.** The
   "explicit, reasoned acceptance in `--reason`" escape was satisfiable by
   boilerplate meeting only `MIN_REASON_LENGTH`
   (`clear_family_halt_cli.py:51,56-58`). Of the two offered options the KISS
   one is taken: with an open position the procedure is always
   settle-or-exit-first then set (weather positions settle within a day), so a
   slug-matched flag would add a control surface for a case with no legitimate
   use. §6.5, §7 step 0c(ii)-(iii), §8(i) and §9 are made consistent: no
   override exists anywhere in the procedure.
3. **Test count corrected** from twelve to fourteen in §8(a); §8 lettering
   unchanged.
No score is claimed for this round and no readiness is asserted; round-6 review
is pending.


**Round 7 (2026-09-21) — revision log, responding to the two round-6 review
records** (`reviews/AUD-02-r6-silent-failure-hunter.md`, 79/100;
`reviews/AUD-02-r6-prediction-market-reviewer.md`, 95/100). Every file:line
added this round was read this round in source. Edits are confined to AUD-02b
(§6.5, §7 step 0a, §8(a)/(i), §9) — no renumbering, no scope removed.
1. **MATERIAL (the DEFAULT live GET had no pagination/eof-completeness gate),
   FIXED.** Confirmed in source that the previously-cited
   `_probe_authenticated` (`scripts/venue/polymarket_us_auth_smoke.py:1015-1040`)
   is a bare connectivity probe that parses NEITHER `positions` NOR `eof`, so it
   could not support the completeness claim made about it; its citation is
   corrected to what it actually proves (a positions GET over this transport is
   a permitted read: `PERMITTED_METHODS`, `http.py:64`, enforced `:189-192`).
   §6.5(1) now specifies the live read as the node's OWN read-only transport
   `PolymarketUSHttpClient.get_authenticated` (`http.py:116-135`) with the
   payload parsed through the SAME parser the durable-evidence writer uses —
   `PolymarketUSExecutionClient._declared_positions` (`client.py:2592-2622`), a
   `@staticmethod` on the class at `:1085`, so it is called directly with no
   instance, no connection and no second parser — which refuses `eof is not
   True` (R-4P-1, `:2606-2621`) and a foreign `positions` shape
   (`:2595-2605`) with `ExecutionReportMappingError` (`errors.py:208`). Slug
   projection follows the existing shape-drift discipline
   (`client.py:3071-3079`): a missing/non-`Mapping` entry or absent
   `netPosition` is `None` = UNKNOWN = open = refuse, never a dropped slug or
   an assumed zero. A truncated or partial page is never read as flat. RED
   tests (15) non-eof ⇒ refuse, (16) malformed/drifted shape ⇒ refuse, (17)
   `eof=True` with zero positions ⇒ flat ⇒ proceed, added; §8(i) extended and a
   §9 failure case added, with the un-followed cursor (R-4P-2 deferred) stated
   as a fail-closed residual.
2. **MINOR (NO-leg netting untested), FIXED.** The prose caveat is replaced by
   an explicit sign-agnostic RULE — "any non-zero net position on any slug =
   open", `Decimal(net) != 0`, never `> 0` — applied on both the live and
   fallback sources, with RED test (18) asserting a NEGATIVE `net_position`
   (the venue's netting of a NO holding as a short YES) refuses identically to
   a positive one, on the live page and on
   `StartupPositionSnapshot.net_position` (`client.py:876-888`). A §9 failure
   case records the class.
3. **MINOR (settle-or-exit wait acceptability unstated), FIXED.** §6.5 now
   states why the wait is acceptable — daily-settling weather markets bound it,
   the family reaches pricing on zero decisions today
   (`docs/evidence/DECISION_FUNNEL_2026-09-20.md:1,19`), and the mechanism can
   only refuse too long, never set unsafely — and what it costs: the A1 ruling
   stays UNENFORCED for the duration. A NEW fill during the wait is handled
   explicitly: the check is not a latch, it re-runs, refuses again, and the
   halt is set at the first flat-and-known moment; the residual (a repeatedly
   filling family defers the set until the operator exits deliberately) is
   stated rather than hidden. Mirrored in §9.
4. **Test count corrected** from fourteen to eighteen in §8(a); §8 lettering
   unchanged (a)-(k).
No score is claimed for this round and no readiness is asserted; round-7 review
is pending.

**Round 8 (coordinator micro-edit, 2026-09-21).** Two MINORs from `reviews/AUD-02-r7-silent-failure-hunter.md` closed in place: test (19) pins the no-instantiation invariant (§7 step 0a; §8(a) eighteen → nineteen); §8(i) now requires the reason token to distinguish `LIVE_GET_FAILED:<class>` from `FALLBACK_CHOSEN:<reason>`. No other text changed; no score or readiness claimed here.

<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-22) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `ad13a136c8fd65d494de6ca4a41048a53bca9cf085148b4e6ae2bf3a3e5d4c92`
- **Baseline self-score:** 86/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `prediction-market-reviewer` round 8: 100/100 — `reviews/AUD-02-r8-prediction-market-reviewer.md`
  - `silent-failure-hunter` round 8: 100/100 — `reviews/AUD-02-r8-silent-failure-hunter.md`
- **Readiness:** **READY**
- **Unresolved blockers / notes:**
  - None. Both original blockers are resolved: A1 is RULED and peer-ENDORSED (`docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`), and the operator states the budget ceiling is already established.
  - Note: the ruling stays UNENFORCED until sub-item AUD-02b (P0) is built and the halt is set. Live-trading enablement of any future family remains operator-only (standing invariant, not a blocker).
- **Full review history:** 16 records, `reviews/AUD-02-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
