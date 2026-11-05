# RULING — failing study units, the session order-count ceiling, and the exit-seam prerequisites (2026-09-21)

Status: ENDORSED 2026-09-21 — independent peer review ENDORSE, no required change, on the text as amended by the Revision 2 addendum at the end of this file (`docs/evidence/reviews/RULING_study_ceiling_exit_review_2026-09-21.md`). Rulings delegated to engineering peers by the operator.
Scope: three independent clusters, ruled separately. Read-only session; no code, unit, config or plan
was edited, no service started or stopped, no study run.

---

## RULING 1 — AUD-15b / AUD-15c: both units RETIRE, with a binding re-homing condition

### 1.1 Questions ruled (verbatim, `docs/plans/backlog/AUDIT_2026-09-21/AUD-15-...md` §12)

> "**Is the CLI-basis candidate #2 offer-gate scan still a live measurement?** Its output has no
> consumer identified in the audit window and has not been written since 09-12. Retire or fix."
> "**Are M_A (pre-lock winner-ask) and M_B (current-rung archive-vs-tape edge) still live
> measurements?** They must be ruled **separately**…"

### 1.2 Evidence (each verified this session)

| # | Fact | Citation |
|---|---|---|
| E1 | The offer-gate unit's own subject is the **CLI-basis candidate #2** scan | `deploy/systemd/breezy-offer-gate-daily.service:2,16,18` |
| E2 | CLI-basis / `cli_settlement_print_lock` is a **lock** family, refuted: winner rung 0 asks / 3332 rows, 5 stations | `docs/core/LESSONS.md:449,456` (L-9) |
| E3 | Standing verdict: "**Lock strategies DEAD (L-9)**" | `docs/core/PROGRESS.md:30` |
| E4 | Nothing reads `offer_gate_latest.md`. The only reference in the repo is the wrapper that **writes** it | `deploy/systemd/offer-gate-daily-run.sh:87`; repo-wide search for `offer_gate_latest` returns that line only |
| E5 | The scan **module** is imported as a library by other work (`classify_instance`, `InstanceVerdict`, `station_days_only_on_corrupt_tape`, `QUALIFYING_HEADROOM`, `CONTAMINATED_STATIONS`) | `docs/plans/backlog/AUDIT_2026-09-21/AUD-09-...md:318-330`; `scripts/analysis/cli_basis_setup_win_rate_study.py:72`; `scripts/analysis/whole_tape_paper_replay.py:30` |
| E6 | M_A is the **SS2/SS3 pre-lock winner-ask** measurement — the same lock programme as E2/E3 | `deploy/systemd/breezy-mb-daily.service:2-3` |
| E7 | M_B is the **archive-vs-tape current-rung edge** measurement | `deploy/systemd/breezy-mb-daily.service:3` |
| E8 | That exact measurement class is the one ruled dead: the archive table's formal "+0.53 edge" settled two degrees away; the discriminating statistic is realized outcomes, not the archive | `docs/core/LESSONS.md:999-1003` |
| E9 | The forecast-edge programme is **TERMINAL on this surface, by pre-registered procedure** (09-20) | `docs/evidence/RULING_forecast_edge_programme_closes_2026-09-20.md:4` |
| E10 | `pm_us_crh_rest_v5` folded **CLOSED_NOT_REGISTERED** 09-20 | `docs/core/PROGRESS.md:84`; `docs/plans/POST_FORECAST_PHASE_2026-09-20.md:17,53` |
| E11 | Neither `M_A`, `M_B`, `offer-gate` nor `CLI-basis` appears **anywhere** in the current `docs/core/PROGRESS.md` — no open item, no standing verdict, no backlog row depends on either study's output | searched `docs/core/PROGRESS.md`, 0 matches |
| E12 | M_B's module is load-bearing as a **registered analysis definition** (break-even, band partition, `n>=60` floor) and is pinned byte-unmodified while PREREG v1 is live | `docs/specs/PREREG_v1_current_rung_hold_2026-09-04.md:28,43,98`; `docs/specs/PREREG_v1_kalshi_..._DRAFT_2026-09-04.md:24`; `src/breezy/settlement/current_rung_hold_v2.py:10,32,80` |
| E13 | **The two wrappers under retirement are the ONLY two schedulers of `asos_recent_refresh.py`** | `deploy/systemd/offer-gate-daily-run.sh:80`; `deploy/systemd/mb-daily-run.sh:86` (repo-wide, these are the only invocations) |
| E14 | A **live-path** consumer depends on that nightly refresh: the hypothetical-hold monitor reads the cache "the nightly `asos_recent_refresh.py --since` refresh populates — never by fetching itself"; the exit-window study is cache-only on the same posture | `scripts/analysis/current_rung_hold_monitor_hypothetical_hold.py:158`; `scripts/analysis/current_rung_hold_exit_window_study.py:22,150` |

### 1.3 Options considered

(a) **Fix both** (reconcile `MemoryHigh`, split mb-daily) — spends engineering to make a study with no
consumer finish faster; AUD-15 §4 itself calls this the wrong order. (b) **Leave open** — the status
quo burns ~1.5 h CPU nightly and pushes a 31 GB host into 3.8–5.2 G of swap beside the live node, the
exact contention class of the 2026-09-11 K1 incident; not acceptable. (c) **Retire both** — chosen.
(d) **Retire and also delete the scripts** — REJECTED on E5/E12: it would break AUD-09's import and
mutate a registered analysis definition.

### 1.4 RULING

1. **AUD-15b — `breezy-offer-gate-daily`: RETIRE.** Decision-table rows 1 **and** 2 both fire (no
   consumer, E4/E11; family dead by standing verdict, E2/E3). Disable and remove the timer, unit and
   wrapper. **Do not run the §7 step 1(e) cgroup diagnostic** — it exists only to choose a `MemoryHigh`
   for a fix path this ruling removes; not running a 12 G study is the strongest form of the
   one-heavy-job-at-a-time discipline.
2. **AUD-15c — `breezy-mb-daily`: RETIRE, both studies, for different reasons.** **M_A** on rows 1+2
   (lock programme, E6/E2/E3). **M_B** on row 2 (E7/E8/E9 — it measures the archive-vs-tape edge that
   the 09-20 ruling closed as TERMINAL). The unit split question (row 5) is therefore moot.
3. **`scripts/analysis/cli_basis_offer_gate_scan.py`, `ma_prelock_winner_ask_study.py` and
   `mb_current_rung_edge_study.py` are NOT deleted and NOT edited.** Retirement removes *scheduled
   execution*, never the modules: E5 (imported by AUD-09's census and two studies) and E12 (M_B is a
   registered analysis definition; editing it would be a PREREG change by the back door).
4. **BINDING CONDITION — re-home the ASOS refresh in the same commit.** E13/E14: retiring both
   wrappers deletes the only nightly `asos_recent_refresh.py` invocation, and a **live-path** nightly
   consumer reads that cache without fetching. Retirement without re-homing converts a dead study's
   removal into a silent data outage on the exit/monitor path — the failure class this backlog exists
   to close. The refresh moves to a surviving enabled timer's wrapper (or its own minimal unit), with
   a RED-first pin: `test_an_enabled_timer_still_invokes_the_asos_recent_refresh`. **No retirement
   commit may merge without it.**
5. **AUD-15a is unaffected and stays P1.** After retirement it still covers `k1-daily`,
   `exit-window-study`, `family-tally@`, `score-live-trials`, `position-monitor-report` and the
   re-homed refresh.

### 1.5 Strongest argument against, and why it loses

*"M_B's outputs define PREREG v1/v2 constants, so the study is live."* It loses because those specs
cite the **module's source lines** (E12), not the nightly artefact; freezing the module preserves every
registered semantic while the nightly run adds nothing. *"The 09-20 closure was about the forecast
family, not M_B."* It loses on E8: the closed programme's central object is precisely the archive
table M_B computes, and LESSONS.md:999-1003 records that its formal edge did not survive contact with
settlement.

---

## RULING 2 — AUD-06b BLOCKER-C (R-12) and BLOCKER-D: both are BUILD-SIDE. Neither is an operator question.

### 2.1 Questions ruled (verbatim, AUD-06b §12)

> "**BLOCKER-C (operator, pre-existing, unavoidable): R-12** … the operator must rule whether the count
> ceiling is kept (derived from daily / venue lot minimum) or dropped so the dollar budget is the only
> day stop."
> "**BLOCKER-D (operator…):** with qty derived from the per-position cap, one order can spend the whole
> cap instead of ~$0.30. Is the current per-position value still the intended per-order spend?"

### 2.2 Evidence

- **The contract names exactly two operator controls and states the ceilings are derived:** "Two
  reserved controls: **maximum daily budget** and **maximum per POSITION**… The three session ceilings
  **derive** from the two caps at permit mint (`safety.py:552-608`). **Everything else is build-side.**"
  (`docs/core/PROGRESS.md:19-24`).
- **The count ceiling is a pure function of the two caps**, with no independent value:
  `_derived_session_order_count()` = `floor(daily / position)`, `max(1, …)`
  (`src/breezy/adapters/polymarket_us/safety.py:591-606`).
- **An explicit env override exists** (`_session_count`, `safety.py:621-625`); using it would create a
  third operator-supplied value and is therefore forbidden by the same contract line.
- **R-12's premise is a qty=1 artefact**: "can exhaust BEFORE the dollar budget under the 09-14
  per-order ruling (**many orders below the cap**)" (`docs/core/PROGRESS.md:75`).
- **AUD-06b removes that premise**: `qty = min(floor_cent_safe(cap/ask/lot)·lot, …)` sizes each order
  *to* the per-position cap (AUD-06b §3 "Required", §6 D1), so `floor(daily/position)` is exactly the
  number of cap-sized orders the daily budget affords — the two ceilings bind together.
- **The per-position cap already IS the per-order authorisation**: enforced per grant by
  `DailySpendLedger.authorize_order_cost` (`PROGRESS.md:21-22`), and AUD-06b consumes it only through
  that seam, never as a number (§5).
- **Refusals name the precondition, never a value** — the existing discipline that lets this be ruled
  without touching any cap (`src/breezy/runtime/order_enablement.py:86-92`).

### 2.3 RULING

1. **R-12 / BLOCKER-C is CLOSED as build-side. The derived session order-count ceiling is KEPT.**
   It carries no operator-supplied value — it is a *derived safety bound* over the two caps
   (`safety.py:591-606`, `PROGRESS.md:23`). Dropping it would delete a live safety bound to make a
   money-moving path more permissive, which the binding backlog constraints forbid
   (`PROGRESS.md:39-42`). **The dollar ledger remains the binding economic control; the count ceiling
   is a fail-closed second bound that can only ever stop the day EARLIER, never authorise more spend.**
2. **No explicit session-count override may be set.** `_session_count`'s env path
   (`safety.py:621-625`) stays unused: setting it would introduce a third operator-reserved value in
   violation of `PROGRESS.md:19-24`. A pin test should assert the override is absent from every
   shipped unit/env template.
3. **Named residual, and the one change it requires.** Depth- or lot-clamped orders can still cost less
   than the cap, so the count ceiling can still bind before the dollar budget. That is acceptable
   (fail-closed: it refuses, it never over-spends) **provided it is legible**: the day-stop path must
   distinguish, by a **distinct dimensionless refusal reason and alert event**, a session stopped on
   the count ceiling from one stopped on the dollar ledger — otherwise a truncated trading day is
   indistinguishable from a quiet market, which is the diagnosis gap already on record for the no-trade
   days. This is build-side and carries no value.
4. **BLOCKER-D is CLOSED as build-side / no-op.** The per-position cap's semantics are unchanged by
   AUD-06b: it authorises per order today and after sizing, through the same ledger seam. "Is the
   current value still the intended per-order spend?" asks the operator to re-affirm a VALUE they have
   already set; the operator owns the value, not a build gate, and posing it would make the operator an
   input to a decision the contract assigns to us. If the operator ever wants a different ceiling they
   edit `operator.env` — no plan, artefact or gate is implicated. **No value is stated, proposed or
   implied anywhere in this ruling.**
5. **This closure does NOT unblock AUD-06b.** BLOCKER-A (AUD-06a's validated envelope) and BLOCKER-B
   (AUD-02's family-scoped demonstrated edge) stand untouched and remain the binding gates; sizing an
   unproven edge multiplies a negative expectation (AUD-06b §3). Closing C and D removes two
   *mis-classified* gates, not the two real ones.

### 2.4 Strongest argument against, and why it loses

*"A ceiling that can stop the trading day early is an economic decision, so it belongs to the operator."*
It loses on two grounds. First, the ceiling is not an independent lever: it is arithmetic over values
the operator has already set, so "ruling" it can only mean either keeping a derived bound or deleting a
safety bound — and the second is prohibited. Second, its effect is strictly conservative: it can only
reduce spend below an already-authorised ceiling, so deferring to the operator buys no protection while
leaving a build item blocked indefinitely.

---

## RULING 3 — AUD-07: one genuine evidence blocker, one sequencing dependency, one blocker peers close now

### 3.1 Questions ruled (verbatim, AUD-07 coordinator status block, `:678-681`)

> "Unresolved blockers: — Exit corpus is frozen until trading resumes (evidence unavailable). — PREREG
> v4 for the exit family plus the operator positive control. — AUD-06a boundary result."

### 3.2 RULING

1. **"Exit corpus frozen until trading resumes" — GENUINE unavailable-evidence blocker, but it blocks
   the ARMING DECISION ONLY, not AUD-07.** The plan's own §12 BLOCKER-1 and §4/§11 already say every
   measurement fix (findings B, B2, C1–C3, D) is executable today at N=5; the coordinator status block
   states it unqualified and therefore over-blocks the item. Reclassify as an **arming-gate
   precondition**, and leave AUD-07 executable now.
2. **"PREREG v4 plus the operator positive control" — SPLIT; both halves are peer-closable in part.**
   - **(a) A PREREG v4 DRAFT for `pm_us_crh_exit_v4` CAN be authored now**, as a DRAFT artefact under
     `docs/specs/`, without data peeking. Precedent: `docs/specs/PREREG_v5_crh_rest_DRAFT_2026-09-16.md`
     and `PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md` — DRAFT specs are routine and are not
     registrations. **Binding conditions:** every parameter is **inherited with provenance** from
     `POSITION_EXIT_EXECUTION_2026-09-16.md` Rev 2 §2/§4 (boundary re-solved from unchanged inputs; the
     unchanged R-THREAT/R-DEAD gates); **no parameter, endpoint, boundary, window or firing threshold
     may be chosen, tuned or justified against the N=5 exit corpus** — that is peeking, and the N=5
     readings (R-DEAD 0/5, R-THREAT 1/5) are arming-gate reads, never design inputs; `d0_climate_day`
     stays unpinned; `status: DRAFT_NOT_REGISTERED`; `n` resets to 0 at registration (`POST_FORECAST_PHASE_2026-09-20.md` §A-9 item 2; coordinator correction — the shared brief mis-cited L-34).
     **Registration remains a separate, later act** and is not authorised by this ruling.
   - **(b) The 1-lot positive control is NOT an operator UI step and is NOT operator-only.** Repo
     practice is explicit: the positive control is a bot-driven job whose "operator residue is **one
     command** … No UI clicks, no hand-placed order, no hand cancel, no manual flatness check", and it
     "assigns none of" the reserved controls (`docs/plans/OP_SEQ_BOT_POSITIVE_CONTROL_2026-09-04.md:7,118`).
     The exit-side control at `POSITION_EXIT_EXECUTION_2026-09-16.md:333-336` is likewise a bot action —
     arm one station-day, exit one 1-contract position, verify venue-side — and the 09-16 authorising
     operator ruling states that "Everything below the two budget caps is build-side and decided here"
     (`:8-12`). **Reclassify BLOCKER-2 as: PREREG v4 registration (ruling-decidable) + sequencing behind
     BLOCKER-1 and behind §4 steps 1–2**, with operator residue = the already-granted live enablement
     and the two already-set caps, i.e. **nothing new**.
   - **Conservative guard, binding:** the positive control may not run before (i) §4 step 1's preview
     capture retires the reducing-vs-opening question (`:322-328` — "If the preview cannot distinguish
     reducing from opening, this step is NOT retired and step 3 stays blocked"), (ii) step 2's mapping
     ruling is written, and (iii) v4 is actually REGISTERED. AUD-07 itself still arms nothing;
     `exit_gate.py` keeps an empty diff.
3. **"AUD-06a boundary result" — SEQUENCING behind another backlog item, not unavailable evidence.**
   AUD-07 §7 step 7 can mint and pin provisional shas today while the manifest stays
   `DRAFT_NOT_REGISTERED`; only **registration** must wait on AUD-06a. Downgrade from blocker to a
   named dependency on the registration step.

### 3.3 Strongest argument against, and why it loses

*"Drafting PREREG v4 while the N=5 results are already known is post-hoc design."* It loses only if the
draft's parameters are chosen with those results in view — which condition 2(a) forbids explicitly by
requiring inheritance-with-provenance from Rev 2. The alternative, waiting for trading to resume before
writing any spec, is worse: it guarantees the spec gets written under time pressure at the moment a
position exists, which is exactly when peeking is hardest to resist.

---

## Consequences — exact text changes (do NOT edit; for the owning sessions)

**AUD-15** — §12: replace both BLOCKER bullets with "RULED 2026-09-21
(`docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md`): **retire both units**;
offer-gate on decision-table rows 1+2, M_A on rows 1+2, M_B on row 2." §5: add to *In scope* —
"**re-home `asos_recent_refresh.py` onto a surviving enabled timer in the same commit**, with a RED pin";
add to *Explicitly excluded* — "**deleting or editing `cli_basis_offer_gate_scan.py`,
`ma_prelock_winner_ask_study.py` or `mb_current_rung_edge_study.py`** (imported by AUD-09; M_B is a
registered PREREG v1/v2 analysis definition)". §7 15b/15c: strike step 1(e), the positive control and
the polling-loop orchestration as moot under retire; keep steps 3, 4 and 7. §8: strike items 4 and 6;
add "the re-homed ASOS refresh is proven to run from an enabled timer".

**AUD-06b** — §4: delete BLOCKER-C and BLOCKER-D from the dependency list (BLOCKER-A/B stand). §12:
replace both bullets with "**RULED build-side 2026-09-21** (ruling above): the derived session
order-count ceiling is KEPT as a fail-closed bound over the two caps; the dollar ledger is the binding
control; no session-count override may be set; the per-position cap already IS the per-order
authorisation and its semantics are unchanged." Add one §7 RED test:
`test_a_session_stopped_on_the_derived_order_count_ceiling_is_named_distinctly_from_a_budget_stop`
(dimensionless, no value).

**AUD-07** — Coordinator status block: replace "Exit corpus is frozen until trading resumes (evidence
unavailable)" with "…blocks the ARMING DECISION only; every measurement fix is executable at N=5";
replace the PREREG/positive-control bullet with "PREREG v4 **DRAFT authorable now** under the
no-peeking conditions of the 09-21 ruling; registration is a later act; the 1-lot positive control is a
**bot-automated** step sequenced behind BLOCKER-1 and §4 steps 1–2, **not** an operator gate"; downgrade
the AUD-06a bullet to "dependency on the registration step". §12 BLOCKER-2: strike "operator-only hard
gate". §7: add step 7b — author the v4 DRAFT spec with per-parameter provenance and an explicit
"no parameter derived from the N=5 corpus" attestation.

## What would overturn each ruling

1. A named, in-repo consumer that *reads* `offer_gate_latest.md` or an M_A/M_B artefact and feeds a
   live decision; or a standing verdict re-opening the lock or archive-edge programme. A restored
   `asos_recent_refresh` schedule that is *not* in the retirement commit does not overturn it — it
   violates it.
2. Evidence that the derived count ceiling can authorise spend **above** the dollar ledger (it cannot,
   by `safety.py:591-606`), or an operator instruction changing the contract at `PROGRESS.md:19-24`.
3. A venue or PREREG constraint making a DRAFT spec itself a registration; or a preview capture (§4
   step 1) that cannot distinguish reducing from opening — which re-blocks the positive control on
   evidence, exactly as `POSITION_EXIT_EXECUTION_2026-09-16.md:327-328` already provides.

## Genuinely operator-only residue

Only the **VALUES** of maximum daily budget and maximum per position, and **live-trading enablement**.
Nothing in these three rulings requires a new operator value, and none is stated, proposed or implied.

_Saved verbatim by the coordinator (the `architect` peer has no file-write tool), with the one marked citation correction._

---

## Revision 2 addendum (supersedes the text it names)

Written after independent peer review (`docs/evidence/reviews/RULING_study_ceiling_exit_review_2026-09-21.md`).
Every citation below was re-verified against the tree this session. No operator value is stated anywhere.

### A1 — SUPERSEDES Ruling 1 §1.4 item 4 (and the §8 line in its Consequences)

The review is correct and the original wording was dangerously coarse: "the refresh" is two different
invocations with two different cache keys.

- **Rolling:** `deploy/systemd/offer-gate-daily-run.sh:80` runs `asos_recent_refresh.py` with **no
  `--since`**, i.e. `DEFAULT_LOOKBACK_DAYS = 3` (`scripts/analysis/asos_recent_refresh.py:91`).
- **Fixed-window:** `deploy/systemd/mb-daily-run.sh:86-87` runs it `--since "$ASOS_FETCH_START_ANCHOR"`,
  the anchor declared at `mb-daily-run.sh:36-38` and duplicated from
  `ma_prelock_winner_ask_study.ASOS_FETCH_START` ("update both together if it ever changes").
- **Only the fixed-window invocation feeds the live path.** The consumer keys on
  `cache_path_for_url(cache_dir, asos_url(id, ASOS_FETCH_START, ASOS_FETCH_END))` and says so:
  "the SAME window `mb_current_rung_edge_study.py` uses and the nightly `asos_recent_refresh.py --since`
  refresh populates — never by this run's own `--start`/`--end`"
  (`scripts/analysis/current_rung_hold_monitor_hypothetical_hold.py:156-168`;
  `current_rung_hold_exit_window_study.py:16-22`).

**RULING A1.** (i) The invocation that must be re-homed is **exactly `asos_recent_refresh.py --since
<ASOS_FETCH_START anchor>` (the mb-daily form)**, not "the refresh". (ii) The offer-gate **rolling
3-day invocation is NOT kept**: no consumer of that key was found, and re-homing it would be the
silent-failure trap the review names — the fixed-window file already exists, so a wrong re-home never
raises the loud cache-miss (`monitor_hypothetical_hold.py:169-170` `SystemExit`) and instead feeds an
ever-staler file forever. (iii) The anchor must not be forked into a third copy: the re-homed wrapper
imports or asserts equality with `ma_prelock_winner_ask_study.ASOS_FETCH_START`.
**RED pin, restated (replaces `test_an_enabled_timer_still_invokes_the_asos_recent_refresh`):**
`test_an_enabled_timer_invokes_the_since_anchored_asos_refresh_and_the_consumer_cache_key_is_fresh` —
asserts (a) a wrapper reachable from an **enabled** timer invokes `asos_recent_refresh.py` with
`--since` whose value equals `ASOS_FETCH_START`, and (b) a **freshness** check on the consumer's own
resolved cache path — epoch-mtime comparison, not existence (existence is what fails silently; measure
with epoch mtimes, never a `find -newermt` zero).

### A2 — ADDS to Ruling 2 §2.2/§2.3 (named residual R2-a), and SUPERSEDES §2.3 point 4's "no-op"

**R2-a, disclosed.** The dollar side reseeds durably across a relaunch — `DailySpendLedger.seed_spent`
(`operator_controls.py:306-331`) and `seed_permit_budget_from_prior_spend` for the permit's notional
(`safety.py:781-792`) — while a fresh mint sets `remaining_order_count` to the **full** derived ceiling
every time (`safety.py:735-738`), and the docstring is explicit that seeding never touches the
order-count budget, "which counts orders this permit itself authorises, not prior-process spend"
(`:786-789`). With the documented 3×/day mid-day relaunch, **the count ceiling is per-PROCESS, not
per-DAY.** **RULING:** the **dollar ledger remains the only per-DAY bound** — that is unchanged and is
what the earlier "can only ever stop the day earlier, never authorise more spend" claim rests on, and
it survives, because a relaunch restores order *count*, never spend authority. **Per-process is
ACCEPTED as fail-closed** and the count is **not** made durable by this ruling: doing so would add new
durable state to the permit seam — the highest-consequence seam in the repo — for protection the
dollar ledger already provides. **Two conditions:** (1) the distinct refusal/alert event required by
§2.3 point 3 must name the bound as the **session (this-process) order-count** ceiling, so a
count-stop can never be read as a day stop; (2) the per-process semantics are stated in AUD-06b §12
rather than filed as a new item. Making order count a per-day control would be a **new durable-state
design, filed separately — it is not an operator value and never becomes one.**

**BLOCKER-D closure is CONDITIONAL, not a no-op.** Closure stands only if AUD-06b emits a distinct,
dimensionless, **valueless** event — e.g. `ORDER_SIZED_TO_POSITION_CAP` — logged **and** delivered
through the existing alert sink, deduped to the **first** live order sized to the per-position cap
under the new sizing path, carrying no qty, price, cost or fee (D6-R). Without it the qty=1→cap-sized
transition is a silent behaviour change; with it, no operator input is needed and no value is restated.

### A3 — ADDS to Ruling 3 §3.2.2(b): the authorisation chain, stated explicitly

`pm_us_crh_exit_v4` is a **new, separately-manifested family** (`deploy/families/pm_us_crh_exit_v4.json`,
`DRAFT_NOT_REGISTERED`; gated independently by `persistence/exit_gate.py:55`). The 09-16 operator ruling
is **class-scoped, not family-scoped** — "once losing positions are identified that they get sold …
Everything below the two budget caps is build-side and decided here"
(`docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md:8-12`) — which is precisely why arming an exit rule
on a new family raises **no new operator residue**. Stated plainly so no future reader stretches it:
**live-trading ENABLEMENT of `pm_us_crh_exit_v4`, if and when it is registered, remains operator-only**
under the standing invariant that no item may touch live-trading enablement (`docs/core/PROGRESS.md:39-42`).
Nothing in Ruling 3 grants, anticipates or substitutes for that.

### A4 — Consequences: the lines that change

- **AUD-15 §5 (In scope):** "re-home the **`--since <ASOS_FETCH_START anchor>`** invocation of
  `asos_recent_refresh.py`"; add to *Excluded*: "the offer-gate rolling 3-day invocation is retired
  with its wrapper, not re-homed". **§8:** the new acceptance item is the A1 pin, including the
  **consumer-cache-key freshness** assertion — existence alone is not acceptance.
- **AUD-06b §12:** the R-12 bullet gains residual **R2-a** verbatim (per-process vs per-day, with
  `safety.py:735-738,786-789` and `operator_controls.py:306-331`); the BLOCKER-D bullet reads
  "**CLOSED build-side, CONDITIONAL on the `ORDER_SIZED_TO_POSITION_CAP` event**". **§7:** add
  `test_the_first_cap_sized_order_emits_a_valueless_sized_to_cap_event_once`; the point-3 test name
  becomes `..._session_process_order_count_ceiling_...`. **§8:** both events are acceptance items.
- **AUD-07 §7 step 7b / §12 BLOCKER-2:** add the A3 sentence — new separately-manifested family;
  09-16 authorisation is class-scoped; **enablement stays operator-only**.

_Addendum saved verbatim by the coordinator._
