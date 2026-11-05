# AUD-15 — Decide fix-or-retire for the two timing-out study units, and make a failed study unit alert

## 1. ID and actionable title

**AUD-15** — `breezy-mb-daily.service` and `breezy-offer-gate-daily.service` have been failing
on `TimeoutStartSec` for days. Diagnose each from its own journal and unit file, rule
**fix or retire per unit on evidence**, and close the structural hole underneath both: **no
study unit in `deploy/systemd/` declares `OnFailure=`, so a failed nightly study alerts nobody.**

## 2. Source finding and class

- **Gap:** G-14 (`docs/evidence/AUTONOMY_ROI_AUDIT_2026-09-21.md:91-93`). Verdict **FALSE**;
  V that both units are in failed state, **A for the cause**.
- **Class:** **autonomous-operation failure** (a scheduled job fails silently, indefinitely),
  with a **verification gap** on whether either study is still worth running.

**Evidence collected read-only for this plan (2026-09-21).** The causes are now measured and
they are **different for the two units** — a single shared fix would be wrong.

**`breezy-offer-gate-daily.service` — failing EVERY day, at least 09-16 → 09-20:**

| Date | Outcome | CPU / wall | Memory peak |
|---|---|---|---|
| 09-16 | timeout | 13m50s / 30m | 12.2 G (**swap 4.7 G**) |
| 09-17 | timeout | 13m49s / 30m | 12.2 G (**swap 3.8 G**) |
| 09-18 | timeout | 15m01s / 30m | 12.2 G (**swap 5.2 G**) |
| 09-19 | timeout | 14m20s / 30m | 12.2 G (**swap 4.0 G**) |
| 09-20 | timeout | 14m26s / 30m | 12.2 G (**swap 3.8 G**) |

The unit sets `MemoryHigh=12G` / `MemoryMax=16G`
(`deploy/systemd/breezy-offer-gate-daily.service:41-42`) and the scan peaks at **12.2 G —
above `MemoryHigh`**. `MemoryHigh` is a *throttle*, not a kill: the cgroup is put under heavy
reclaim pressure and pushed into swap. The signature is in the CPU figure — **~14 min of CPU
over 30 min of wall clock, every single run.** Roughly half the budget is spent waiting on
reclaim/swap, not computing. `TimeoutStartSec=1800` (`:81`) then fires.

**The shipped unit comment corroborates the diagnosis, and its own arithmetic is backwards.**
`breezy-offer-gate-daily.service:35-36` reads: *"at 14.7G, 17.3G, 15.3G over 7-9 min wall
clock. MemoryHigh=12G/MemoryMax=16G matches the sibling tape studies: well above this unit's
measured range…"* — **12 G is below 14.7-17.3 G, not above it.** The cap was set below this
unit's own recorded working set and the comment asserting otherwise is arithmetically wrong on
its face. (Round-1 review found this independently and correctly noted it is stronger evidence
than the round-1 plan claimed. Verified again this session by reading the unit file.)
**The per-unit contrast, stated accurately — revision 2's "opposite truth value" framing was
wrong and is withdrawn.** Round-2 review caught the plan quoting `breezy-mb-daily.service`
selectively, and re-reading the unit file confirms it: the comment cites **three** peaks, not
two — `breezy-mb-daily.service:36-37` reads *"the last three completed runs peaked at **14.3G**,
10.1G, 11.6G over 14-35 min wall clock"* — and **14.3G exceeds `MemoryHigh=12G`** (`:43`), the
same directional error this plan correctly identifies on the offer-gate unit. So mb-daily's
"well above this unit's measured range" is **correct for 2 of the 3 runs it cites, wrong for the
third**, not simply "correct". The plan's earlier quote dropped the value that falsified it; that
is a citation-accuracy defect and is fixed here, not explained away.

**What the two comments do and do not show, precisely:**

| Unit | Cited peaks | vs `MemoryHigh=12G` (throttle) | vs `MemoryMax=16G` (OOM-kill) |
|---|---|---|---|
| offer-gate (`:34-35`) | 14.7G, 17.3G, 15.3G | **all three above** | **17.3G above** |
| mb-daily (`:36-37`) | 14.3G, 10.1G, 11.6G | 14.3G above; two below | all three below |

The contrast is real but **quantitative, not categorical**: offer-gate's every cited run was in
throttle territory and one exceeded even the hard `MemoryMax`, whereas mb-daily has one
historical excursion above the throttle and none near the kill ceiling. What neither comment
shows is *when* those runs happened relative to today's failures — both were measured `--since
2026-09-08`, i.e. **before** the measured window in the tables here — so neither is evidence
about the current failure and neither can carry a diagnosis on its own. They are corroboration
at best; §7 step 1(e)'s direct cgroup read is the measurement.

Downstream consequence: `~/.local/share/breezy/offer_gate/offer_gate_latest.md` was last
written **2026-09-12**. Nine days with no output.

**`breezy-mb-daily.service` — a different failure, and a progressive one:**

| Date | M_A done | M_B done | Outcome | Memory peak |
|---|---|---|---|---|
| 09-16 | — | — | Finished, 42m14s wall | 9.0 G |
| 09-17 | 13:36:23 | 14:10:17 | Finished, 39m50s | 11.7 G |
| 09-18 | 13:37:17 | 14:14:31 | Finished, 44m04s | 12.0 G (swap 80 K) |
| 09-19 | 13:39:31 | — | **timeout** | 12.0 G (swap 32 K) |
| 09-20 | 13:40:07 | — | **timeout** | 11.9 G |

`TimeoutStartSec=3600` (`breezy-mb-daily.service:62`). M_A now finishes ~10 min in (up from
~6 min on 09-17), and M_B no longer fits in the remaining ~50 min. Wall clock has climbed
39m → 44m → >60m across four days while the memory peak sat flat. **This is workload growth
against a fixed budget** — the quote tape both studies read grows every day — not a
memory-throttle problem. Swap is negligible here (80 K, 32 K).

**Does the corrected 14.3G reading change this diagnosis? No — and here is why, stated so a
reviewer can falsify it rather than take it.** The 14.3G peak is from the comment's `--since
2026-09-08` window, *before* the five measured days above; inside the measured window the peaks
are 9.0 / 11.7 / 12.0 / 12.0 / 11.9 G — at or below `MemoryHigh=12G`, never near `MemoryMax=16G`
— and swap is 80 K / 32 K, four to five **orders of magnitude** below offer-gate's 3.8-5.2 **G**.
Reclaim pressure that produces kilobytes of swap is not what turns a 44-minute run into a
60-minute timeout; a 14 min CPU / 30 min wall split is (offer-gate's signature), and mb-daily
does not show it. The load-bearing evidence for mb-daily was always the wall-clock series and the
swap figures, never the unit comment, and it is unchanged. **The honest residual:** the 12.0 G
peaks sit *at* the throttle boundary, so a marginal, secondary throttle contribution cannot be
excluded from these numbers alone. That is precisely what §7 step 1(e) measures, and it is now a
falsifiable condition rather than an assumption — see §6's 15c paragraph.

**The structural hole, verified:** `/usr/bin/grep -rl OnFailure deploy/systemd/` matches only
wrapper `.sh` files and `README.md` — **`OnFailure=` appears in no `.service` unit.** Both
units also carry a deliberate `# No Restart=` comment. A timeout is therefore terminal and
silent: no retry, no alert, no journal escalation. `systemctl --user list-units` shows three
units in `failed` (`breezy-mb-daily`, `breezy-offer-gate-daily`, and
`breezy-family-tally@pm_us_crh_cont` — the last is G-04, outside this item).

## 3. Current behaviour, required behaviour, concrete gap

**Current.** Two daily study units start, burn 30–60 minutes of a 31 GB host, get SIGTERMed by
systemd, and land in `failed`. Nothing alerts. The offer-gate scan has produced no artefact
since 09-12 and nobody noticed for nine days.

**Required.** Each unit is either (a) demonstrably able to complete inside a stated budget, or
(b) retired with its timer disabled and its status recorded. In both cases, **any study unit
that ends in `failed` produces a delivered alert.**

**Concrete gap.** Three things: a cgroup limit set below a measured working set; a fixed time
budget against a monotonically growing input; and a missing `OnFailure=` on every study unit.

## 4. Priority, rationale, dependencies, execution order

**Priority: 15a = P1, 15b = P2, 15c = P2.**

- **15a (alert on unit failure) is P1** and is the only part that is unconditionally correct
  regardless of what is ruled about the studies. It is the same class of defect as the alerts
  already fixed by `f97c26f`: detection existed (systemd knows the unit failed) and delivery
  did not. It also protects every *other* study unit, including the family-tally unit that is
  G-04's subject.
- **15b/15c (per-unit fix-or-retire) are P2**: both units measure families whose live status is
  contested, so spending engineering to make a possibly-dead study finish faster is the wrong
  order. Ruling first, remediation second.

**Dependencies.** 15a depends on the alert egress shipped in `f97c26f` (**already merged**).
AUD-14b reuses the same sink for a different process; neither blocks the other.

**The two rulings 15b/15c waited on are RULED and peer-ENDORSED (2026-09-21):**
`docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md` RULING 1 §1.4 as
amended by its **Revision 2 addendum §A1** (review trail:
`docs/evidence/reviews/RULING_study_ceiling_exit_review_2026-09-21.md`). **Both units RETIRE** —
offer-gate on decision-table rows 1+2, M_A on rows 1+2, M_B on row 2 — with a **binding
same-commit re-homing condition** on the `--since`-anchored ASOS refresh (§6). 15b and 15c are
therefore **executable now**, and are no longer evidence-then-ruling work: the fix path they were
scoped around is removed, so their remaining content is retirement + re-home + the freshness pin.

**Execution order:** 15a → 15b ‖ 15c, where 15b and 15c **land as ONE commit** — the re-home
condition binds them together (both wrappers are deleted in it, and the surviving invocation is
re-homed in it).

## 5. Scope and explicit exclusions

**In scope:**
- **AUD-15a** — an `OnFailure=` alert path for every study unit in `deploy/systemd/`.
- **AUD-15b** — `breezy-offer-gate-daily`: **RETIRE** scheduled execution (timer, unit, wrapper),
  per the 09-21 ruling.
- **AUD-15c** — `breezy-mb-daily`: **RETIRE** scheduled execution (timer, unit, wrapper) for
  **both** studies, M_A and M_B, per the 09-21 ruling.
- **The binding same-commit re-home (ruling §A1):** exactly the invocation
  `asos_recent_refresh.py --since <ASOS_FETCH_START anchor>` — the
  `deploy/systemd/mb-daily-run.sh:36-38,86-87` form — moves onto a surviving **enabled** timer's
  wrapper or its own minimal unit, with the §A1 RED pin, **in the retirement commit itself**.
- **A runtime staleness alert for the re-homed refresh** (§6). Checked, and stated as the ruling
  asked: **15a does NOT cover this.** 15a fires on `OnFailure=`, i.e. only when a unit reaches
  `failed`; the shipped refresh call sites treat a shortfall as fail-soft and continue
  (`mb-daily-run.sh:86-90`, `offer-gate-daily-run.sh:80-84`), so a refresh that fetches nothing
  exits 0 and the unit succeeds — while the consumer's **current-UTC-day** cache key is left
  unwritten. That key rotates daily (`ASOS_FETCH_END = dt.date.today()`, §6), so the miss does
  **not** age quietly in place: it surfaces 90 minutes later as a hard `SystemExit` cache miss in
  the 15:00Z consumer (`scripts/analysis/current_rung_hold_monitor_hypothetical_hold.py:169-170`).
  What 15a leaves open is therefore not an *undetected* outage but an **undelivered, badly-located**
  one — the unit reports success, and the only signal is a crash inside an unrelated downstream
  script that an operator must trace back to an upstream refresh. That is the same
  detection-without-delivery shape this item exists to close, so the re-home ships its own
  freshness check and alert, 90 minutes ahead of the first consumer.

**Explicitly excluded:**
- `breezy-family-tally@pm_us_crh_cont.service` (also `failed`). That is **G-04**, a different
  gap with a different cause (no unit tallies the live `pm_us_crh_v4` at all). 15a's
  `OnFailure=` will *cover* it incidentally; AUD-15 must not attempt to fix it.
- `breezy-k1-daily.service` — observed `activating start` at audit time, i.e. currently
  running, not failed. Out of scope except as one of the uniformly-treated study units 15a
  wires.
- **Raising `MemoryMax` on any unit.** The 2026-09-11 K1 incident (17.6 G peak, no ceiling,
  host into swap while the live node ran) is why every study unit is capped at all, per both
  units' own headers. A per-unit `MemoryHigh` may be *reconciled with its measured working
  set*; the host-protection principle is not negotiable and `Slice=breezy-studies.slice`
  (`:46` / `:48`) stays.
- Changing any study's statistical method, window definition, or output schema. A study that
  needs its *method* changed to finish is a retire candidate, not a tuning candidate.
- The protected-window scheduling rules (`deploy/systemd/README.md`, "Protected window and
  serialization") and the shared studies flock. Both are load-bearing; neither is at fault
  here (`flock -n` is non-blocking and exits 0 on contention, so it cannot cause a timeout).
- **Deleting or editing `scripts/analysis/cli_basis_offer_gate_scan.py`,
  `ma_prelock_winner_ask_study.py` or `mb_current_rung_edge_study.py`.** Retirement removes
  *scheduled execution*, never the modules. The offer-gate scan module is imported as a library
  elsewhere (ruling E5), and `mb_current_rung_edge_study.py` is a **registered PREREG v1/v2
  analysis definition** (ruling E12) — editing it would be a PREREG change by the back door.
  `ma_prelock_winner_ask_study.py` additionally remains the **single source of the ASOS anchor**
  (`ASOS_FETCH_START`, `:184`, exported at `:115`), which the re-home depends on.
- **Re-homing the offer-gate rolling 3-day invocation** (`offer-gate-daily-run.sh:80`, no
  `--since`, i.e. `DEFAULT_LOOKBACK_DAYS = 3` at `asos_recent_refresh.py:91`). Ruling §A1(ii):
  it is retired **with** its wrapper, not re-homed — no consumer of that cache key was found, and
  re-homing it would feed the fixed-window consumer a key it never reads while suppressing the
  loud cache-miss that would otherwise surface the mistake.
- **The `MemoryHigh` reconciliation, the unit split, and the `memory.events` cgroup diagnostic.**
  All were fix-path work; the ruling removes the fix path (§1.4 item 1 is explicit: *do not run
  the §7 step 1(e) cgroup diagnostic*). Marked WITHDRAWN BY RULING in place below.
- **Auto-retry of a failed study.** `# No Restart=` is deliberate: a study that OOM-throttles
  or overruns will do so again, and retrying it inside the protected window is host contention
  with the live node. 15a reports; it never re-runs.

## 6. Proposed changes grounded in inspected code/config

**Native mechanism.** None from Nautilus — this is systemd unit configuration and the existing
`breezy.runtime.health` alert sink. The null hypothesis is satisfied the other way round: the
alerting mechanism already exists (`AlertPayload`/`emit_alert`/`resolve_alert_sink`,
`runtime/health.py:351,579,668`, plus the webhook sink wired by `f97c26f`) and must be
**reused, not rebuilt**. `OnFailure=` is itself the systemd-native, cause-agnostic trigger: it
fires on any `failed` result — timeout, OOM-kill, non-zero exit — so one notifier covers all
three without special-casing.

**15a — `OnFailure=` for study units. Specified concretely.**

- **One template unit** `deploy/systemd/breezy-study-failed@.service`, `Type=oneshot`,
  `Slice=breezy-studies.slice`, no `Restart=`, no `OnFailure=` of its own, taking the failed
  unit's name as its instance:
  `ExecStart=%h/…/breezy-study-failed --unit %i` — a console entry point over a small
  `src/breezy/runtime/` module, **not** an inline `python -c` and **not** a new shell wrapper.
  (This is the one place AUD-15 anticipates an `src/` change; it is the notifier itself, not a
  study.)
- **One line added to each study `.service`:** `OnFailure=breezy-study-failed@%n.service`.
  `%n` expands to the failing unit's full name, so the instance carries the identity.
- **The payload is fixed-shape:** `severity="WARN"`, a single `event="study_unit_failed"`,
  `site="global"` (a unit is host-wide, matching `DEGRADED_ALERT_SITE`'s convention at
  `component_health_watch.py:110`), and `detail` a **fixed enum string** per the supervisor's
  contract (`TRADE_NODE_DAILY_RELAUNCH_2026-09-04.md:151-153`) — never exception text, never
  journal text, never a value-bearing string. The failed unit's name travels as its own
  structured field on the log line, not inside `detail`.
  WARN, not CRITICAL: a study is not the trading path, and CRITICAL is reserved in this repo
  for conditions that mean the node is not trading (`component_health_watch.py:101-105`).
- **No `EnvironmentFile=`, no credential, no egress beyond the existing sink.** These study
  units deliberately carry no venue credential (both unit headers say so) and the notifier must
  not become the first one that does. The only environment it reads is
  `BREEZY_ALERT_WEBHOOK_URL`, via `resolve_alert_sink()`.
- The notifier must never raise into systemd: `emit_alert` already contains every sink failure
  by contract (`health.py:668-689`), and the entry point returns 0 unconditionally.

**15b / 15c — RULED RETIRE. The fix path below is WITHDRAWN BY RULING.**
The fix-or-retire call was a strategy-lead question; it was ruled on 2026-09-21
(`docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md` §1.4, endorsed) and
this plan no longer carries it as open. The decision table is retained **as the ruling's own
attribution vocabulary** — the ruling cites its rows — not as a live decision procedure:

| Observation from the evidence pack | Implied disposition | Status |
|---|---|---|
| No consumer found for the study's output anywhere in `docs/`, `scripts/`, `deploy/` | **Retire candidate on that ground alone**, independent of runtime | **FIRED** for offer-gate and M_A (ruling E4/E11) |
| A standing verdict in `PROGRESS.md` calls the study's family dead | **Retire candidate** | **FIRED** for offer-gate, M_A (E2/E3) and M_B (E8/E9) |
| Consumer exists, family live, unit completes once `MemoryHigh` is reconciled | Fix candidate (i): limit reconciliation | **WITHDRAWN BY RULING — moot** |
| Consumer exists, family live, unit still overruns on an unbounded input | Retire candidate, not a budget candidate | Moot; retirement reached by rows 1+2 instead |
| Consumer exists, family live, two studies in one unit, one still completes (M_A) | Fix candidate (ii): split the unit | **WITHDRAWN BY RULING — moot** (§1.4 item 2) |

**15b — offer-gate: WITHDRAWN BY RULING.** The `MemoryHigh` reconciliation described in earlier
revisions is not shipped. §2's measured diagnosis stands as the record of *why the unit was
failing*; it is no longer the input to a remediation.

**15c — mb-daily: WITHDRAWN BY RULING.** The input-growth/throttle discrimination, its
falsifiable `memory.events` condition, the offer-gate positive control and the polling-loop
orchestration are all **WITHDRAWN BY RULING** — they existed only to choose a `MemoryHigh` or a
unit split for a fix path the ruling removes (§1.4 item 1 forbids running the diagnostic at all;
not running a 12 G study is the strongest form of one-heavy-job-at-a-time). Retained above in
§2 as the measured record of the failure, and nowhere as work.

**The one thing that IS built: the ASOS re-home (ruling §A1) — binding, same commit.**

*What moves.* Exactly `asos_recent_refresh.py --since "$ASOS_FETCH_START_ANCHOR"` — the
invocation at `deploy/systemd/mb-daily-run.sh:86-87` with the anchor declared at `:36-38`
(`ASOS_FETCH_START_ANCHOR=2026-08-30`, comment: *"ma_prelock_winner_ask_study.py:ASOS_FETCH_START
-- fixed anchor, update both together if it ever changes"*). Its key is the one a **live-path**
consumer reads without fetching: `cache_path_for_url(cache_dir, asos_url(id, ASOS_FETCH_START,
ASOS_FETCH_END))` at `scripts/analysis/current_rung_hold_monitor_hypothetical_hold.py:166-168`,
documented at `:156-164` as *"the SAME window `mb_current_rung_edge_study.py` uses and the nightly
`asos_recent_refresh.py --since` refresh populates"*, with a hard `SystemExit` on a miss at
`:169-170`. `current_rung_hold_exit_window_study.py:16-24` reads the same fixed-window key and
defaults to `--obs-source cache`.

*Host chosen, and why — **its own minimal unit**, `breezy-asos-refresh.service` +
`breezy-asos-refresh.timer` at `OnCalendar=*-*-* 13:30:00 UTC`,
`Slice=breezy-studies.slice`, `Type=oneshot`, the shared studies `flock` preamble copied from the
surviving wrappers, modest ceilings in the light-unit band (`MemoryHigh=512M`/`MemoryMax=1G`, the
`breezy-position-monitor-report.service:33-34` band — this is an HTTP GET + file write, not a
tape scan), `TimeoutStartSec=600`, no `EnvironmentFile`, no `Restart=`, and the 15a
`OnFailure=breezy-study-failed@%n.service` line.* The two candidate re-home hosts were the two
surviving consumers, and both were rejected on their own declared posture:

| Candidate | Enabled timer | Why rejected |
|---|---|---|
| `breezy-position-monitor-report` | 15:00Z (`breezy-position-monitor-report.timer:21`) | Its unit states it *"holds no venue credential and opens no socket"* (`:13-14`). The refresh is an outbound IEM HTTP GET; hosting it there inverts a documented invariant of a unit on the live-monitor path. |
| `breezy-exit-window-study` | 15:20Z (`breezy-exit-window-study.timer:20`) | Cache-only by design (`current_rung_hold_exit_window_study.py:16-24`), and it runs **after** the 15:00Z consumer — re-homing there would leave the earlier consumer reading a day-old cache every day. |

A new unit is the smallest correct extension here precisely because the refresh must run
**before both** consumers and must own the socket neither of them wants. 13:30Z is the slot
`breezy-mb-daily.timer:30` vacates, is 90 min ahead of the earliest consumer, and is outside the
`[16:35Z, 01:15Z)` no-start protected window (`deploy/systemd/README.md:937-939`). The wrapper
takes the shared studies flock and exits 0 on contention, so it never contends with a heavy
study or with the node — but it **must not copy `mb-daily-run.sh:81` verbatim**. That line is
`flock -n 9 || { say "SKIPPED ..."; exit 0; }`: a single early `exit 0` **before** the refresh
call at `:86-87`, so on a contention night the script leaves at `:81` and every later block —
including the freshness check — is skipped. The new wrapper keeps the same *outcome* (skip, not
kill; exit 0) and changes the *control flow*: the lock result is **captured**, not acted on by
`exit`:
`if flock -n 9; then <refresh>; else say "SKIPPED-LOCK -- another study holds the studies lock; \
asos refresh not attempted this invocation"; fi`, with the `SKIPPED-INFRA`/`exit 75` paths at
`:79-80` kept exactly as they are (a lock-infrastructure failure is a real failure and must still
reach `failed` and 15a). The freshness check then runs **after** that `if/else`, on every path.

*The anchor is not forked (ruling §A1(iii)).* After this commit the anchor exists in exactly two
places, as it does today: the module constant `ma_prelock_winner_ask_study.ASOS_FETCH_START`
(`:184`) and the new wrapper's `ASOS_FETCH_START_ANCHOR`, carrying the same
"update both together" comment — `mb-daily-run.sh`'s copy is deleted in the same commit, so the
count does not rise. Equality is asserted mechanically by the pin below, not by the comment.

*Freshness alert (no ruling required; it closes the gap §5 names).* **The check is
UNCONDITIONAL — it is not inside the refresh path.** It runs on **every scheduled invocation of
the wrapper**, whether the flock was acquired or not and whether the refresh subprocess ran,
succeeded, reported a shortfall, or was never invoked; a lock-skip additionally logs its own
named reason (`SKIPPED-LOCK`, above) so the skip is visible in the journal in its own right.
Placing the check after the refresh *returns* would make it unreachable on exactly the night it
is needed — the contention night — and, worse, self-erasing: a later successful night rewrites
the cache before the check reads it, so a skipped night would leave no evidence at any time.
The wrapper resolves the consumer's own cache path by the consumer's own function and compares
its **epoch mtime** against the current UTC day for each station spec; if the resolved path is
**missing**, or its mtime falls **before 00:00:00Z of the current UTC day**, it emits **one** WARN
through the shipped sink — `resolve_alert_sink()` / `emit_alert()` / `AlertPayload`
(`src/breezy/runtime/health.py:579,668,351`), `event="asos_cache_stale"`, `site="global"`,
`detail` a **fixed enum string**, no path, no count, no timestamp in `detail` — and still exits 0.
Exit 0 is deliberate: the refresh *ran*, so `failed` would be the wrong status, and routing this
through `OnFailure=` would collapse a distinct condition into 15a's `study_unit_failed` enum.
Epoch-mtime comparison, never existence alone: the mtime leg is what keeps the rule correct if the
key ever stops rotating (an anchor change) — that is the only condition under which a
present-but-old file can exist at all; but on *this* key **missing is itself a stale verdict**,
for the reason derived next.

***The 36 h threshold chosen in revision 6 is WITHDRAWN. It was unreachable, and the consumers'
real tolerance is zero missed nights.*** Re-examined against the cadence and the consumers, as
round 6 required. Verified: `ASOS_FETCH_END: Final[dt.date] = default_asos_fetch_end()`
(`ma_prelock_winner_ask_study.py:185`) returns `dt.date.today()` (`:168-179`), and the refresh
builds the same window — `refresh_window` returns `[today - lookback, today]` with the lookback
derived from `--since` (`asos_recent_refresh.py:115-135`, applied at `:153-156`). The cache key is
`sha256` of the URL (`settlement_alignment_study.py:343-345`) and the URL carries **both** dates,
so **the key rotates every UTC day**. Two consequences:

- **A 36 h threshold is dead code on this key.** A file under today's key can only have been
  written today, so an *existing* resolved path is never older than ~24 h and can never cross
  36 h. The only leg that could ever have fired was "missing" — the threshold's value was
  irrelevant, which is why "is 36 h right" was the wrong question to answer with slack.
- **The consumers tolerate zero missed nights, not one.** A missed refresh does not hand them a
  day-old file; it hands them **no file for today's key** — a hard `SystemExit` cache miss in the
  15:00Z live-path consumer (`current_rung_hold_monitor_hypothetical_hold.py:169-170`, keyed at
  `:166-168`) and a missing-input report in the 15:20Z consumer under its default
  `--obs-source cache` (`current_rung_hold_exit_window_study.py:16-24`). A rule that stays quiet
  through one missed night would stay quiet through the only night that breaks them.

**The rule therefore carries no hour constant at all:** stale ⟺ *the path resolved for the
consumer's **current-UTC-day** key is missing, or its epoch mtime predates 00:00:00Z of that day*
— i.e. "no refresh has written this key today". It fires at 13:30Z, **90 minutes ahead of the
first consumer**, on the same day the miss occurs. The current-UTC-day boundary is used rather
than "later than this invocation's start" deliberately: the exit-window study may legitimately
populate the same key earlier in the day under `--obs-source fetch`, which is fresh data and must
not raise a false WARN. If the key ever stops rotating (an anchor change), the same rule still
fires on a stale mtime, so nothing silently degrades to existence-only.

**No `src/` change is anticipated in 15b/15c** beyond reusing the existing sink.

## 7. Ordered verification and implementation steps

**AUD-15a**
1. **Delivery re-verification as a recorded step:** confirm `BREEZY_ALERT_WEBHOOK_URL` is
   configured and a WARN is delivered end to end, and paste the evidence line. A notifier with
   no destination is the defect this item is fixing, reproduced.
2. RED: unit-file pins (the repo already pins unit content — see
   `tests/unit/test_trade_supervisor_phase1_unit.py` and the existing `test(deploy)` pins) ::
   `test_every_study_unit_declares_an_onfailure_handler`, enumerating the `.service` files in
   `deploy/systemd/` that have a sibling `.timer`, so a future study unit added without
   `OnFailure=` fails the suite.
3. RED: `test_the_study_failure_notifier_carries_no_environmentfile_and_no_credential`,
   `test_the_notifier_declares_no_onfailure_and_no_restart` (the alert-loop guard),
   `test_the_notifier_alert_detail_is_a_fixed_enum_and_carries_no_unit_text`.
4. RED (the wrapper exit contract — see §9; this replaces round 1's `OnFailure`-level exit-0
   test): `test_the_wrapper_exits_0_only_on_lock_contention_and_75_on_lock_infrastructure`,
   asserted against `offer-gate-daily-run.sh:53-59` and `mb-daily-run.sh`'s stated intent. The
   risk being pinned is the **inverse** of round 1's: not that a healthy skip alerts, but that
   a wrapper masks a genuine failure as exit 0 and so never reaches `failed` at all.
5. GREEN: add the template unit, the notifier entry point, and the `OnFailure=` lines.
6. Verify with `systemd-analyze --user verify` producing **empty output** — the repo's own
   stated pass condition (`deploy/systemd/README.md` section 2).
7. Live proof: trigger a controlled failure of a **non-trading** study unit and show the
   delivered alert artefact (not a log line).

**AUD-15b / AUD-15c (retire + re-home — ONE commit). Step numbering is preserved; the
fix-path steps are struck in place.**
1. ~~Evidence pack per unit, items (a)–(e) including the live `memory.events` read, the
   offer-gate positive control and the polling-loop orchestration.~~ **WITHDRAWN BY RULING**
   (§1.4 item 1 — the diagnostic existed only to pick a `MemoryHigh` for a fix path that is gone,
   and the ruling forbids running it).
2. ~~Quote both units' header comments in full in the evidence note.~~ **WITHDRAWN BY RULING** —
   the corrected quotes remain in §2 as the record; no evidence note is produced.
3. **KEPT.** State, per study, who consumes its output — already established by the ruling
   (E4/E11: nothing reads `offer_gate_latest.md`; no M_A/M_B artefact has a reader) — and
   **re-confirm it at execution time** against the tree being committed, because a consumer added
   since 09-21 is the ruling's own stated overturn condition.
4. **KEPT.** Re-read `docs/core/PROGRESS.md` "Standing verdicts that gate future work" and quote
   the current verdict text verbatim in the commit message. Do not cite a remembered verdict.
5. ~~Map findings onto the decision table and submit the fix-or-retire question as a ruling.~~
   **WITHDRAWN BY RULING — answered.** Record instead the ruling's own row attribution:
   offer-gate rows 1+2, M_A rows 1+2, M_B row 2.
6. ~~Under fix: RED-first unit pins, change the one limit the evidence names, three consecutive
   successful runs.~~ **WITHDRAWN BY RULING — there is no fix path.**
7. **KEPT and extended — the retirement, with the re-home in the SAME commit.** In order:
   - **7a RED (the binding pin, ruling §A1):**
     `test_an_enabled_timer_invokes_the_since_anchored_asos_refresh_and_the_consumer_cache_key_is_fresh`.
     It asserts **(a)** a wrapper reachable from an **enabled** timer (resolved from the
     `.timer`/`.service`/`ExecStart` chain in `deploy/systemd/`, not from a hard-coded unit name)
     invokes `asos_recent_refresh.py` with `--since`, **(b)** that `--since` value equals
     `ma_prelock_winner_ask_study.ASOS_FETCH_START` (`:184`) — imported, so a fork of the anchor
     fails the suite — and **(c)** a **freshness** check on the consumer's **own resolved cache
     path**, built through the consumer's own key
     (`current_rung_hold_monitor_hypothetical_hold.py:166-168`), by **epoch-mtime** comparison,
     never existence. RED before the re-home lands, for the right reason: today no enabled timer
     will carry the `--since` form once both wrappers are deleted.
   - **7b RED:** `test_no_retired_study_unit_timer_or_wrapper_remains` — the three files per unit
     are gone and no `.timer` references a missing `.service`; and
     `test_the_offer_gate_rolling_asos_invocation_is_not_re_homed` (the `--since`-less form
     appears in no surviving wrapper), pinning ruling §A1(ii).
   - **7c RED (three tests, because the check must be unconditional):**
     (i) `test_the_asos_refresh_wrapper_alerts_on_a_stale_consumer_cache` — a resolved cache path
     that is missing, or whose mtime predates 00:00:00Z of the current UTC day, produces exactly
     one WARN with the fixed-enum `detail`, and the wrapper still exits 0.
     (ii) `test_the_staleness_check_still_runs_when_the_studies_flock_is_held` — **the regression
     pin for this round's defect.** The test **holds the shared studies flock** (the
     `$XDG_RUNTIME_DIR/breezy-studies.lock` fd-9 lock the existing wrapper suite already takes —
     `tests/unit/test_analysis_units_serialized.py:752-779` is the working fixture to copy),
     invokes the wrapper once, and asserts **all** of: the refresh subprocess was **not** run; a
     `SKIPPED-LOCK` line with its named reason is logged; the `asos_cache_stale` WARN **still
     fires** when the consumer's current-day key is absent; and the wrapper exits **0**. A wrapper
     that keeps `mb-daily-run.sh:81`'s bare `exit 0` fails this test at the WARN assertion — which
     is the point: the revision-6 design passed test (i) while being structurally incapable of
     ever firing on a contention night.
     (iii) `test_the_staleness_check_is_quiet_when_the_key_was_written_earlier_today` — a resolved
     path whose mtime is today but earlier than the invocation (the legitimate
     `--obs-source fetch` case, `current_rung_hold_exit_window_study.py:16-24`) produces **no**
     WARN, pinning the current-UTC-day boundary against a tighter "later than this run's start"
     rule that would false-alarm.
   - **7d GREEN:** add `breezy-asos-refresh.service`/`.timer`/`asos-refresh-run.sh` (§6), then
     `systemctl --user disable --now breezy-offer-gate-daily.timer breezy-mb-daily.timer`,
     delete the two units, the two timers and the two wrappers.
     **Never leave a disabled timer with an orphan unit** — the
     `breezy-pm-crh-{cont,v2}-tally` orphans already in `not-found`/`failed` are the anti-pattern
     (G-04). Enable and start the new timer; `systemctl --user daemon-reload`.
   - **7d-bis (SAME commit, mandatory — the gate does not go green without it):** update every
     test that pins a retired unit **by name**. These are **inventory pins** — assertions that a
     file is present in `deploy/systemd/` — and updating them to the post-retirement truth is
     **not** weakening a safety, settlement or contract test: no behavioural guarantee, no venue
     or money path, and no PREREG artefact is involved, and the collision, slice, flock and
     protected-window *rules* they enforce all stay in force, applied to the surviving set plus
     the new unit. Enumerated and verified this revision:
     - `tests/unit/test_deploy_timer_hours.py:116` — `assert "breezy-mb-daily.timer" in names`
       inside `test_every_timer_file_is_parsed_by_this_test` (`:107-117`). Repoint to
       `breezy-asos-refresh.timer`; the sibling pins at `:115` (`breezy-live-tally.timer`) and
       `:117` (`breezy-score-live-trials.timer`) are unaffected. The collision test itself scans
       the tree (`_all_timer_files()`), so the vacated-and-reclaimed 13:30Z tick needs no change —
       and `test_1415_utc_is_owned_by_exactly_one_timer` (`:120-133`) is untouched.
     - `tests/unit/test_analysis_units_serialized.py` — the three literal expected sets and every
       restatement/consumer of them, all of which `assert ... .is_file()` or `read_text()` on a
       deleted path: `_HEAVY_TIMERS` (`:359-365`, restated `:567-571`), `_HEAVY_SERVICES`
       (`:366-372`, restated `:623-627`), `_WRAPPERS` (`:373-379`, restated `:756`),
       `_WRAPPER_OUTPUT_ENV_VAR` (`:386-387`), `_WRAPPER_LOG_FILENAME` (`:391-392`),
       `test_the_offer_gate_unit_still_passes_the_systemd_home_specifier` (`:659-671`),
       `test_the_offer_gate_wrapper_requires_its_output_dir_as_an_argument` (`:813-819`),
       `_A20_SCOPE` (`:674-681`, read at `:700`) and `_A20_RESIDUAL` (`:682-696`, read at
       `:712-713`). After retirement the heavy sets are `{breezy-k1-daily.*}` plus
       `k1-daily-run.sh`; the new light unit is **not** added to them (it is not a heavy study),
       and the A-20 sets drop the two retired names while keeping their surviving members and the
       `combined_text` assertions at `:708-710`.
     - **`tests/unit/test_analysis_units_memory_capped.py` — one edit, decided here.** The two
       retired names at `:31-32` need **no** edit: `_CANDIDATE_UNITS` (`:29-41`) is filtered by
       `_EXISTING_UNITS = [name for name in _CANDIDATE_UNITS if (_DEPLOY_DIR / name).is_file()]`
       (`:43-45`), so a deleted unit narrows the parametrisation rather than failing it, and
       `test_candidate_unit_exists_or_is_explicitly_skippable` (`:88-94`) is a tautology by
       construction. But `_CANDIDATE_UNITS` is a **curated** list, not "every unit on
       `breezy-studies.slice`": it includes `breezy-family-tally@.service`,
       `breezy-live-tally.service`, `breezy-score-live-trials.service` and
       `breezy-quote-tape-ingest.service` while excluding `breezy-position-monitor-report.service`
       and `breezy-exit-window-study.service`, so membership is a per-unit editorial decision this
       plan must make. **DECIDED: `breezy-asos-refresh.service` JOINS `_CANDIDATE_UNITS`, in this
       same commit** — a unit that declares its own ceilings must have them pinned, and §6 gives
       this one `MemoryHigh=512M`/`MemoryMax=1G`, which no named test currently checks. **The entry
       is only exercised if the unit file exists**, because `_EXISTING_UNITS` filters on
       `is_file()`: 7d-bis therefore runs **after** step 7a has written
       `deploy/systemd/breezy-asos-refresh.service` to disk, and the edit is confirmed live — not
       silently filtered out — by the three parametrised tests reporting the **new name** in
       `pytest -v` output: `test_nightly_analysis_unit_has_a_memory_max_ceiling` (`:102-110`),
       `test_nightly_analysis_unit_has_a_memory_high_below_memory_max` (`:112-124`) and
       `test_nightly_analysis_unit_cites_the_2026_09_11_k1_incident` (`:127-135`). The first two
       pass trivially (`512M < 1G ≤ 16G`); the third requires the new unit's header comment to cite
       `2026-09-11` and `k1-daily`, so step 7a writes that citation into the unit file rather than
       leaving 7d-bis to discover it red. **Comment-only, no assertion:**
       `tests/unit/test_ma_prelock_winner_ask_study.py:392`,
       `tests/unit/test_mb_current_rung_edge_study.py:618`.
     - `deploy/systemd/README.md` — the `breezy-mb-daily` section (`:388-455`) and the inventory
       lines naming the retired units (`:322`, `:439`, `:477`, `:490-495`, `:526`, `:541`,
       `:545`, `:554`, `:681`, `:922-923`, `:947`, `:950`, `:962`, `:979-980`, `:1001`, `:1007`)
       are updated to record the retirement and to document the new unit at 13:30Z. README edits
       must preserve the strings the A-20 test reads (`:708-710`).
     - **Accepted doc drift, named rather than fixed:** `ma_prelock_winner_ask_study.py:169-177`
       states that `deploy/systemd/breezy-mb-daily.timer` advances the window. It is wrong after
       this commit, and §8 item 9 requires a **zero diff** to that module (ruling §1.4 item 3), so
       it stays. The new unit's README entry records that the advancer is now
       `breezy-asos-refresh.timer` and that this docstring is stale by ruling.
   - **7e:** `systemd-analyze --user verify` on the new unit → **empty output**
     (`deploy/systemd/README.md` section 2).
   - **7f:** record the retirement, the row attribution and the re-home in the commit message,
     citing the ruling artefact path. No new evidence note is required; the ruling is the record.

## 8. Acceptance criteria and required evidence

1. **15a:** `systemd-analyze --user verify` empty; the new pin tests green; a **delivered**
   out-of-process alert artefact from one deliberately-failed study unit. A log line is not
   acceptance — that is exactly the gap `f97c26f` was raised to close.
2. **15a:** `systemctl --user list-units --all 'breezy-*'` enumerated, and every unit with a
   sibling timer shown to declare `OnFailure=`. The notifier template itself appears in this
   enumeration, which is how its *own* failure stays visible (§9).
3. **15a:** the recorded delivery re-verification line from §7 step 1.
4. ~~**15b/15c:** a dated evidence note per unit carrying the five items of §7 step 1, the live
   `memory.events` read, the pre-read prediction, the offer-gate positive control, the sampling
   cadence and the `READ_FAILED` handling.~~ **WITHDRAWN BY RULING** (§1.4 item 1 — the
   diagnostic is not run).
5. **15b/15c:** each unit's disposition is recorded against a **named row of §6's decision
   table**, quoting the ruling's own attribution (offer-gate 1+2, M_A 1+2, M_B 2) and the ruling
   artefact path, in the retirement commit message.
6. ~~**15b/15c under fix:** three consecutive `Finished` runs with peaks from `MemoryPeak` and a
   re-read `high` counter.~~ **WITHDRAWN BY RULING** — there is no fix path.
7. **15b/15c under retire:** `systemctl --user list-timers --all` shows both timers **gone**
   (not merely inactive), `systemctl --user list-units --all 'breezy-*'` shows no `not-found`
   and no `failed` unit for either name, and the ruling artefact exists at the cited path.
8. Full gate `scripts/ci/run_tests_no_egress.sh` green; `lint-imports` + `mypy` clean.
9. **Negative requirements:** `git diff` shows no `MemoryMax` increase on any surviving unit, no
   change to `Slice=breezy-studies.slice`, and **no `TimeoutStartSec` increase** — a longer
   timeout is a longer silent failure, not a fix. Additionally, and now load-bearing:
   **`git diff` shows zero changes to `cli_basis_offer_gate_scan.py`,
   `ma_prelock_winner_ask_study.py` and `mb_current_rung_edge_study.py`** (ruling §1.4 item 3),
   and **no surviving wrapper invokes `asos_recent_refresh.py` without `--since`** (§A1(ii)).
10. **The §A1 pin is green and is the acceptance for the re-home:**
    `test_an_enabled_timer_invokes_the_since_anchored_asos_refresh_and_the_consumer_cache_key_is_fresh`,
    with **all three** assertions — enabled-timer reachability, `--since` equal to
    `ma_prelock_winner_ask_study.ASOS_FETCH_START`, and the **epoch-mtime freshness** check on the
    consumer's resolved cache path. **Existence alone is not acceptance** (ruling §A4).
11. **Live proof of the re-home, post-merge:** the new timer fires; its journal shows
    `asos refresh ok`; and the consumer's resolved cache path has an **epoch mtime later than the
    unit's start** — quoted as two epoch integers, never a `find -newermt` result. A run in which
    the mtime did not advance is a failed re-home, not a passing deployment.
12. **The staleness alert is proven delivered**, not logged: with the consumer's current-day key
    absent (or its mtime set before 00:00:00Z of the current UTC day) in a scratch cache dir, one
    WARN `asos_cache_stale` arrives at the sink and the wrapper still exits 0.
13. **The staleness check is proven unconditional:** §7 step 7c(ii) is green — with the shared
    studies flock **held** for the whole invocation, the wrapper runs no refresh, logs
    `SKIPPED-LOCK` with its named reason, **still** delivers the `asos_cache_stale` WARN, and
    exits 0; and 7c(iii) is green (no WARN when the key was written earlier the same day). A
    passing item 12 with a failing item 13 is the revision-6 design and is **not** acceptance.
14. **The inventory pins are updated in the retirement commit** (§7 step 7d-bis): the pins at
    `test_deploy_timer_hours.py:116` and the enumerated sets/consumers in
    `test_analysis_units_serialized.py` name the post-retirement truth — both retired timers
    **absent**, `breezy-asos-refresh.timer` **present** at 13:30Z, no tick collision — and
    `git log`/the commit message record that this is an **inventory pin for retired units, not a
    weakened safety, settlement or contract test**. Item 8's "full gate green" is unreachable
    without this and the two are verified together, in one run of
    `scripts/ci/run_tests_no_egress.sh`. **Included in this item:**
    `breezy-asos-refresh.service` is present in `test_analysis_units_memory_capped.py`'s
    `_CANDIDATE_UNITS` (`:29-41`) and the `pytest -v` node ids show the new name under
    `test_nightly_analysis_unit_has_a_memory_max_ceiling`,
    `test_nightly_analysis_unit_has_a_memory_high_below_memory_max` and
    `test_nightly_analysis_unit_cites_the_2026_09_11_k1_incident` — an entry added but filtered out
    by `_EXISTING_UNITS` (`:43-45`) because the unit file was not written first is **not**
    acceptance, since it verifies nothing.
15. **Negative:** `git diff` shows **zero** changes to `scripts/analysis/ma_prelock_winner_ask_study.py`
    even though its `:169-177` docstring is left stale by this commit (item 9 / ruling §1.4 item 3);
    the staleness is recorded in `deploy/systemd/README.md` instead.

## 9. Validation

**Failure cases.**
- **The notifier unit itself fails** → it has no `OnFailure=`, so it dies quietly in the
  journal. That is the correct fail-closed shape; an alerting loop is worse than a missed
  alert, and a test pins the absence of a self-referential `OnFailure=`. **Residual, named:**
  a notifier that cannot start means a study failure goes unannounced. It is not invisible —
  the notifier instance lands in `failed` and appears in the §8 item 2 enumeration — but
  nothing pages on it. Closing that would need a second-order watchdog, which is out of scope
  and would reintroduce the loop this design refuses.
- **A study "fails" because the shared flock was held** → the wrapper exits **0** on that path
  (`offer-gate-daily-run.sh:53-59`), the unit never enters `failed`, and `OnFailure=`
  structurally cannot fire. Round-1 review correctly noted an `OnFailure`-level test of this is
  vacuous. The real risk is the **inverse** and is what §7 15a step 4 now pins: a wrapper that
  swallows a *genuine* failure into exit 0 would make the unit look healthy forever. The test
  is therefore on the wrapper's exit contract (0 = lock contention only; 75 = lock
  infrastructure), not on the notifier.
- **Alert sink unreachable** → contained by `emit_alert` (`health.py:668-689`); the notifier
  returns 0 regardless, so it never leaves the instance `activating` or `failed` for a delivery
  problem.
- **A study is killed by `MemoryMax` (OOM) rather than timing out** → `OnFailure=` is
  cause-agnostic and fires identically. No special-casing.
- **The re-home is wrong, so the refresh writes a key no consumer reads** — the named failure
  mode of this commit. Its shape is **not** an ageing file: the consumer's key hashes a URL
  carrying both window dates and therefore rotates every UTC day (§6), so a wrong re-home leaves
  **today's key never written**, and the 15:00Z consumer raises its loud `SystemExit`
  (`scripts/analysis/current_rung_hold_monitor_hypothetical_hold.py:169-170`, keyed at `:166-168`)
  on essentially the first day the wrong wiring ships — not after a period of quiet accumulation.
  The 13:30Z WARN remains the leg that carries the value, for two reasons independent of
  detection: it is delivered through the alert sink **90 minutes earlier**, leaving lead time to
  intervene before either consumer runs, and it is a **dedicated, unambiguous signal about the
  refresh's own health** rather than a crash in an unrelated consumer script that an operator must
  trace upstream. Closed on two independent legs: the §A1 pin's **epoch-mtime** assertion on the
  consumer's own resolved path (build time) and the wrapper's runtime `asos_cache_stale` WARN
  (every night). Existence checks are excluded by name on both legs. **Provenance, recorded not
  re-litigated:** the endorsed ruling's addendum
  (`docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md`, §A1, `:285-288`)
  described this mode as the file that *"already exists ... and instead feeds an ever-staler file
  forever"*, written before the daily rotation was established in revision 7; that is a factual
  refinement which **strengthens** §A1's re-homing condition (the miss is louder and same-day, so
  the pin it mandates is easier to satisfy, never weaker) and changes none of its decisions, so the
  ruling stands unedited.
- **The shared studies flock is held at 13:30Z, so the refresh never runs** — the round-6
  design's blind spot, now closed. The wrapper does not `exit 0` at the lock line: it logs
  `SKIPPED-LOCK` with its named reason and falls through to the **unconditional** freshness
  check, which finds no file under the consumer's current-UTC-day key and delivers one
  `asos_cache_stale` WARN, 90 minutes before the 15:00Z consumer would have hit
  `current_rung_hold_monitor_hypothetical_hold.py:169-170`. Pinned by §7 step 7c(ii). The
  previously-specified "check after the refresh returns" could not fire on this path at all, and
  a later successful night would have overwritten the evidence that it had happened.
- **A lock-infrastructure failure (no lock dir / unopenable lock)** → unchanged from the existing
  idiom (`mb-daily-run.sh:79-80`): `SKIPPED-INFRA` and **exit 75**, so the unit reaches `failed`
  and 15a's `OnFailure=` fires. Only *contention* is exit 0.
- **The refresh fetches nothing but exits 0** (its documented fail-soft shortfall path,
  `mb-daily-run.sh:86-90`) → the unit succeeds, so `OnFailure=` correctly does not fire; the
  staleness WARN is what fires. This is precisely why 15a alone was insufficient (§5).
- **The anchor moves in `ma_prelock_winner_ask_study.py`** → the §A1 pin imports the constant and
  fails on the next run, rather than the wrapper drifting silently against the consumer's key.
- **Two retired units' `OnFailure=` lines disappear with them** → 15a's enumerating pin test must
  count units *present in the tree*, not a frozen list, or it goes red on a correct retirement.

**Integration behaviour.** The trading node is deliberately **uncapped** and lives outside
`breezy-studies.slice` (both study unit headers state this). Nothing in AUD-15 may touch the
node, the supervisor, or the protected window. A study change that shifts a run into
`[16:35Z, 01:15Z)` violates the README's protected-window rule and is a defect. The notifier
runs inside `breezy-studies.slice` so a pathological notifier cannot contend with the node.

**Autonomous operation.**
- **Detection:** after 15a the claim "we would know if a scheduled job stopped working" becomes
  true for studies, across all three failure classes (timeout, OOM-kill, non-zero exit), for
  every current and future unit with a sibling timer — the pin test makes the coverage
  self-maintaining rather than a one-time sweep.
- **Recovery:** deliberately none. `# No Restart=` stays; a study that overruns will overrun
  again, and retrying it inside the protected window is host contention with the live node —
  the 2026-09-11 K1 incident is the recorded cost of exactly that.
- **The better autonomous outcome may be retirement.** A retired study is a strictly better
  steady state than a study that burns an hour of a 31 GB host every night, pushes it into
  multi-gigabyte swap, and is never read. 15b/15c exist to make that outcome reachable on
  evidence rather than by neglect.

## 10. Deployment, observability, rollback

- Unit files are installed by symlink (`Loaded: … ; linked`), so deployment is
  `systemctl --user daemon-reload` plus, for a retirement, `disable --now` on the timer.
- Observability: the `OnFailure=` alert is the observability. No new log stream, no new file.
- **The retirement and the re-home are ONE commit** (ruling §1.4 item 4: *"No retirement commit
  may merge without it"*). Deploying half of it — deleting the wrappers without the new timer —
  is the silent data outage the condition exists to prevent.
- **Post-deploy verification, in order:** (1) `systemctl --user daemon-reload`; (2)
  `systemctl --user list-timers --all` shows `breezy-asos-refresh.timer` present and enabled and
  both retired timers **absent**; (3) `systemctl --user list-units --all 'breezy-*'` shows no
  `failed` and no `not-found`; (4) after the first 13:30Z fire, the journal shows
  `asos refresh ok` and the consumer's resolved cache path's **epoch mtime is later than the unit
  start** (§8 item 11); (5) the 15:00Z and 15:20Z consumers run without a cache miss.
- Rollback: 15a is purely additive — remove the `OnFailure=` lines, the template unit and the
  notifier entry point. **The retirement is not trivially reversible** (unit files are deleted),
  so `git revert` of the single commit must restore both units, both timers, both wrappers *and*
  remove the new refresh unit atomically — which is exactly why it must not be split. Verify a
  revert leaves precisely one scheduler of the `--since` refresh, never zero and never two
  (re-run the §A1 pin after any revert). The ruling artefact records the re-open trigger: a named
  in-repo consumer that reads an offer-gate or M_A/M_B artefact and feeds a live decision.

## 11. Relationship to portfolio-level ROI

**Demonstrated: none.** Neither study has produced a figure that changed a trading decision in
the audit window; the offer-gate scan has produced no output at all since 09-12.

**Plausible, and separated as such:**
- **Cost avoided is real and measurable now:** these two units together consume roughly 1.5
  hours of CPU and put a 31 GB host into multi-gigabyte swap every night to produce nothing.
  Retiring a dead study is a direct, verifiable reduction in host contention with the live
  node — and the 2026-09-11 K1 incident is on record as what host contention costs.
- **Both studies are now ruled DEAD** (09-21), so the cost avoided is realised rather than
  hypothetical: ~1.5 h of nightly CPU and 3.8-5.2 G of swap beside the live node stop, on the two
  units' own measured figures in §2. The replacement is a single HTTP GET in the light-unit band.
- **The only surviving value is the ASOS cache the live-path monitor and the exit-window study
  read.** Preserving it is the point of the re-home; losing it would have been a direct
  degradation of the exit seam, not a saving.

**Evaluated by:** §8's acceptance items. AUD-15 makes **no** profitability claim.

## 12. Assumptions, unresolved questions, blockers

**BLOCKERS: NONE REMAIN. Both are RULED and peer-ENDORSED (2026-09-21).**
- ~~Is the CLI-basis candidate #2 offer-gate scan still a live measurement?~~ **RULED
  (`docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md` §1.4 item 1):
  RETIRE**, decision-table rows 1 **and** 2 (no consumer, E4/E11; lock family dead by standing
  verdict, E2/E3).
- ~~Are M_A and M_B still live measurements?~~ **RULED separately, as required (§1.4 item 2):
  RETIRE both.** M_A on rows 1+2 (same lock programme, E6/E2/E3); M_B on row 2 (it measures the
  archive-vs-tape edge closed as TERMINAL on 09-20, E7/E8/E9). The unit-split question is moot.
- Review trail: `docs/evidence/reviews/RULING_study_ceiling_exit_review_2026-09-21.md` — ENDORSE,
  no required change, on the text as amended by the Revision 2 addendum (§A1), which supersedes
  §1.4 item 4 and narrows the re-home to the `--since`-anchored invocation.

**What genuinely remains — no readiness is claimed here.** 15a was never blocked and is still
unbuilt. 15b/15c are now buildable, and their residual risk is the re-home, not the retirement:
the pin, the alert and the post-deploy mtime check (§8 items 10-12) have **not been executed**,
and the epoch-mtime freshness leg in particular has never been run against the consumer's real
resolved path. ~~The `36 h` threshold is this plan's choice, not a ruled value, and is the one
number a reviewer should attack.~~ **WITHDRAWN in revision 7:** the threshold was unreachable on
a key that rotates daily, and the rule now carries **no hour constant** — it compares the
resolved current-UTC-day key's mtime against that day's 00:00:00Z (§6). What a reviewer should
attack instead is the *rotation premise* itself: if `ASOS_FETCH_END`
(`ma_prelock_winner_ask_study.py:185` → `dt.date.today()`, `:168-179`) were ever pinned to a
fixed date, "missing" would stop being the dominant signal and the mtime leg would carry the
whole check alone.

**Assumptions to re-verify at execution time:**
- `BREEZY_ALERT_WEBHOOK_URL` is configured and WARNs are delivered (`f97c26f`). §7 15a step 1
  makes this a recorded step rather than an assumption.
- ~~The 12.2 G peak is the scan's working set and not an artefact of concurrent load; the cgroup
  read in a quiet window settles it before any limit is touched.~~ **MOOT under the ruling** — no
  limit is touched and no study is run. §2's figures stand as the record of the failure only.
- **The consumer's cache key is resolvable from the wrapper without importing the heavy study
  module.** `ma_prelock_winner_ask_study.py` imports Nautilus and several sibling studies at
  module scope (`:87`, `:75-101`) though it is import-safe (`__main__` guard at `:825`); the pin
  test may import it freely, but if the *wrapper's* freshness check cannot resolve the path
  cheaply, it resolves it through `current_rung_hold_monitor_hypothetical_hold`'s own helpers
  instead — never by re-deriving the URL by hand, which would fork the key.
- `k1-daily` was mid-run at audit time; confirm its state before enumerating units, so it is not
  mis-recorded as healthy or failed.

**Unresolved (not blocking):** whether M_A and M_B should be split into two units. That is a
consequence of the ruling (§6 decision table, row 5), not a precondition for it.

## 13. Review history

**Baseline self-score (2026-09-21, author): 90/100.** Named weaknesses: refuses to settle which
families are dead; throttle mechanism inferred rather than read from `memory.events`; 15b/15c
not single-pass executable.

### Round 1 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| trading-bot-architect (`AUD-15-r1-trading-bot-architect.md`) | 90/100 | **None found.** Independently confirmed the `OnFailure=` hole by grep. |
| silent-failure-hunter (`AUD-15-r1-silent-failure-hunter.md`) | 91/100 | **None found.** Independently confirmed the unit files, the wrapper exit contract, and the offer-gate comment's backwards arithmetic. |

**Dispositions — every defect and every named required change, both reviewers:**

| # | Reviewer | Item | Disposition |
|---|---|---|---|
| 1 | hunter | Cite the offer-gate unit's self-contradictory comment ("well above" when 12 G is below 14.7-17.3 G) as corroborating evidence | **ACCEPTED, and extended.** Re-verified this session by reading `breezy-offer-gate-daily.service:35-36,41-42`. §2 now quotes it and states the arithmetic error. Extended beyond the request: `breezy-mb-daily.service:37-38` cites 10.1/11.6 G against the same 12 G, where "well above" *is* correct — the same sentence has opposite truth values on the two units, which is itself the evidence that the two failures are different. §7 15b/15c step 2 makes quoting it a deliverable. |
| 2 | architect + hunter | Re-measure the throttle diagnosis with a direct cgroup `memory.events`/`memory.stat` read in a quiet window before touching `MemoryHigh` | **ACCEPTED.** Promoted from a §12 caution to a named evidence-pack deliverable (§7 15b/15c step 1e) and an acceptance item (§8 items 4 and 6, the latter requiring the `high` counter to stop climbing after a fix). |
| 3 | hunter | MINOR — the "exit 0 must not alert" tests are over-specified: an exit-0 unit never enters `failed`, so `OnFailure=` structurally cannot fire | **ACCEPTED, and the test was re-aimed rather than deleted.** The reviewer is right that the `OnFailure`-level assertion is vacuous. But the wrapper's exit contract still needs pinning for the **inverse** risk: a wrapper that masks a genuine failure as exit 0 makes the unit look healthy forever — a silent failure of exactly the class this item exists to close. §7 15a step 4 and §9 now state that inversion explicitly and pin the contract at the wrapper (`offer-gate-daily-run.sh:53-59`), not at the notifier. |
| 4 | (author, round 1 §13) | 15b/15c not executable in one pass — the largest specificity cost | **ACCEPTED (self-raised, now largely closed).** §6 adds a **pre-specified decision table** mapping each evidence observation to its implied disposition, so the ruler answers a bounded question instead of commissioning research, and §8 item 5 requires each unit's disposition to name the row it lands on. The ruling itself stays a BLOCKER and is not pre-empted. 15a is additionally specified down to the literal unit name, `%n`/`%i` expansion, entry-point shape, severity, event name, site and `detail` contract. |
| 5 | (round 2, unprompted) | No `TimeoutStartSec` guard | **ADDED.** §6 and §8 item 9 forbid shipping a raised `TimeoutStartSec` as the fix for either unit — it converts a 30-minute silent failure into a 60-minute one. Round 1 said this in prose; it is now a negative acceptance criterion with a `git diff` check, matching the existing `MemoryMax`/slice guards. |
| 6 | (round 2, unprompted) | The notifier's own failure was stated but its residual was not named | **ADDED.** §9 names it explicitly: the notifier instance lands in `failed` and appears in §8 item 2's enumeration, but nothing pages on it; closing that needs a second-order watchdog, which is out of scope and reintroduces the alert loop this design refuses. |

**Rejections:** none. Both records' findings were verified against the artefact and
incorporated; the one MINOR that was arguably dismissible (disposition 3) was accepted as a
correct criticism and its test re-aimed rather than dropped.

**Points withheld in round 1 without a named change — round 2 must justify or award.** Both
records reported **no material defects** while withholding 10 and 9 points respectively:
architect 18/19/12/18/14/9, hunter 18/19/13/18/14/9. Only the specificity deduction (12-13/15)
came with a stated reason — 15b/15c's evidence-then-ruling shape, which the brief itself
mandates — and neither record named a change that would recover the fidelity, technical,
acceptance or portfolio points. **The specificity reason is now addressed on its own terms**
(§6's decision table + the fully literal 15a spec), without pre-deciding a ruling the brief
forbids this plan to make. Round 2 should either award those criteria or name the specific
change that would recover them.

**Revision 2 self-score (honest, post-revision):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Both named units covered with distinct, measured diagnoses; the structural `OnFailure=` gap the audit did not name is added and independently confirmed. G-14's "may already be dead families" question is still routed to a ruling — correct per the brief, and now bounded by a decision table. |
| Technical correctness and evidence grounding | 20 | 19 | Unit limits, timeouts, slice, the grep result and both header comments re-read from the artefact this session. The throttle mechanism is still an inference until the `memory.events` read lands — which is now a required deliverable rather than a caveat. |
| Implementation specificity and feasibility | 15 | 14 | 15a is literal end to end (unit name, `%n`/`%i`, entry point, severity, event, site, `detail` contract, the four pin tests). 15b/15c are bounded by the decision table; the ruling itself is still a gate, by design. |
| Acceptance criteria and validation quality | 20 | 19 | Nine items: `systemd-analyze` empty, three consecutive runs, a *delivered* artefact, the cgroup counter check, decision-table attribution, and three negative `git diff` guards (`MemoryMax`, slice, `TimeoutStartSec`). |
| Autonomous operation, failure handling, recovery | 15 | 14 | Cause-agnostic coverage of all three failure classes, a self-maintaining pin test, no alert loop, no auto-retry (reasoned), wrapper masking pinned, and the notifier's own residual named with why it is not closed. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Cost-avoidance on measured numbers only; G-04 routed to its owner rather than absorbed; every exclusion names its reason. |
| **Total** | **100** | **95** | |

### Round 2 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| silent-failure-hunter (`AUD-15-r2-silent-failure-hunter.md`) | **94/100** | None MATERIAL. 1 MINOR: the mb-daily comment quote is selectively partial and the "opposite truth value" contrast overstates. |
| trading-bot-architect (`AUD-15-r2-trading-bot-architect.md`) | **100/100** | None. Re-read both unit files and scored technical correctness 20/20, explicitly endorsing the two-peak mb-daily reading. |

**The two records contradict each other on exactly one claim, and the reviewer who scored LOWER
is right.** The architect read `breezy-mb-daily.service` "in full" and reported `:37-38` as
citing "10.1G, 11.6G … here the comment is correct (12 > 11.6)", awarding 20/20 for evidence
grounding on that basis. The hunter read the same file and found a third peak. Coordinator
verification of the file settles it — `breezy-mb-daily.service:36-37` reads *"the last three
completed runs peaked at 14.3G, 10.1G, 11.6G over 14-35 min wall clock"*, and `MemoryHigh=12G`
is at `:43`. **14.3G > 12G.** The hunter is correct; the architect independently reproduced the
plan's own omission, which is what a shared partial quote does to two readers. The 100/100 is
not treated as evidence.

**Dispositions — every defect and every required change, both reviewers:**

| # | Reviewer | Item | Disposition |
|---|---|---|---|
| 1 | hunter | **MINOR** — quote all three mb-daily peaks and restate the contrast as "correct for 2 of 3", not "opposite truth value" | **ACCEPTED IN FULL.** §2's framing is withdrawn by name. The corrected quote carries all three peaks with the 14.3G first, and a table now states both units' peaks against **both** ceilings separately, because the two ceilings mean different things: offer-gate's three runs are all above `MemoryHigh=12G` and one (17.3G) is above the hard `MemoryMax=16G`; mb-daily's are one above `MemoryHigh` and none near `MemoryMax`. The contrast is quantitative, not categorical. |
| 2 | coordinator-required | Does the corrected reading change the mb-daily diagnosis (input growth vs memory throttle)? | **CHECKED, and NO — with the reasoning now stated falsifiably in §2 rather than assumed.** The 14.3G peak predates the measured failure window (the comment was measured `--since 2026-09-08`); inside that window the peaks are 9.0/11.7/12.0/12.0/11.9 G with swap of 80 K and 32 K — four to five orders of magnitude below offer-gate's 3.8-5.2 G. The wall-clock series and the swap figures always carried the diagnosis; the unit comment never did. **Two things changed anyway:** (a) §2 now names the honest residual — the 12.0 G peaks sit *at* the throttle boundary, so a marginal secondary throttle cannot be excluded from these numbers alone; (b) §6's 15c paragraph turns that into a **falsifiable condition on §7 step 1(e)**: `memory.events` `high` ≈ 0 confirms input growth and leaves the fix set unchanged, while a materially non-zero `high` **amends** the diagnosis to "input growth plus marginal throttle" and pulls decision-table row (i) (`MemoryHigh` reconciliation) into 15c's remediation. A result contradicting the plan is recorded as a finding. |
| 3 | hunter/coordinator | The evidence-note step quoted only offer-gate's comment | **ACCEPTED.** §7 15b/15c step 2 now requires **both** comments quoted **in full, never a subset**, with the explicit note that both predate the failure window and are corroboration only — step 1(e) is the measurement. Quoting selectively is the mechanism that produced this defect; the instruction now forbids it. |
| 4 | architect | 100/100, no required changes | **NOT AWARDED** — see the contradiction above. Its confirmations of the round-1 dispositions, the `OnFailure=` structural gap, and the offer-gate arithmetic are accepted; its mb-daily reading is not. |

**Rejections:** none. The architect's mb-daily claim is superseded by direct file verification
rather than rejected on judgment.

**Revision 3 self-score (conservative):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Unchanged: both units get distinct measured diagnoses, the un-named `OnFailure=` structural gap is added, G-04 routed to its own item. |
| Technical correctness and evidence grounding | 20 | **17** | Every unit-file citation is now re-read and quoted whole, with peaks tabulated against both ceilings. Deducted 3, not 1: the plan shipped a truncated quote that *reversed* the sign of its own corroborating evidence and then induced an independent reviewer to reproduce the error — a citation-integrity failure, not a typo. The mb-daily throttle contribution is bounded by argument and not yet by the cgroup counter. |
| Implementation specificity and feasibility | 15 | 14 | 15a remains fully literal; 15c now carries an explicit if/then on the `memory.events` `high` counter instead of a single unconditional diagnosis. Quiet-window scheduling for the cgroup read is still the executor's. |
| Acceptance criteria and validation quality | 20 | 19 | Unchanged item set, now with a falsifiable amendment condition attached to item 4/6's cgroup read. Three-consecutive-runs acceptance still lands days after merge. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Unchanged: cause-agnostic `OnFailure=` coverage, no alert loop, no auto-retry (reasoned), wrapper masking pinned, notifier residual named. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unchanged: cost-avoidance on measured numbers only; every exclusion names its reason. |
| **Total** | **100** | **93** | |

### Round 3 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| trading-bot-architect (`AUD-15-r3-trading-bot-architect.md`) | **94/100** | **None found.** Independently re-derived the corrected peak table from both unit files and confirmed the round-2 citation defect genuinely fixed. |
| silent-failure-hunter (`AUD-15-r3-silent-failure-hunter.md`) | **89/100** | **1 MATERIAL** — the `memory.events` `high` falsifier names no literal read path and no positive control, so a zero is indistinguishable from a broken measurement. |

**Readiness is the LOWER, 89.** Recorded explicitly: **the architect's 94 named no defect and
required no change** ("no MATERIAL defects found this round... the deduction reflects that the
measurement has not yet happened, which no further plan text can substitute for"). Per this
backlog's standing rule a score without a nameable defect is not evidence of correctness — and
this item is the case in point, since the hunter, reading the same artefact, found a MATERIAL
defect sitting inside the very measurement the architect's own deduction pointed at. The 94 is
therefore treated as a miss, not as corroboration.

**Dispositions — every defect and every required change, both reviewers:**

| # | Reviewer | Item | Disposition |
|---|---|---|---|
| 1 | hunter | **MATERIAL** — no literal cgroup path/command is named, and for a `--user` oneshot under `breezy-studies.slice` the read can target the wrong path or race the cgroup's teardown; a zero would then be a failed read reported as a measurement | **ACCEPTED IN FULL, and settled by measurement rather than by prose — the reviewer's own open question ("can it be zero merely because the counter went away with the unit?") is now answered YES, with evidence.** Read-only this revision: `systemctl --user show breezy-mb-daily.service -p Type -p RemainAfterExit -p ActiveState -p ControlGroup` returns `Type=oneshot`, `RemainAfterExit=no`, `ActiveState=failed`, **`ControlGroup=` empty** — the per-unit cgroup is gone, so `memory.events` is unreadable after exit and **no** `systemctl show` property exposes its `high` counter. The same command shows `MemoryPeak=12884615168` and `MemorySwapPeak=0` (offer-gate: `11061796864` / `92901376`), which **do** persist — so §6 and §7 step 1(e) now split the two explicitly: peaks post-hoc from `MemoryPeak`/`MemorySwapPeak`, `high` **only** from a live read. The literal read is spelled: `systemctl --user show <unit> -p ControlGroup --value` while active, then `cat /sys/fs/cgroup<path>/memory.events`, with delegation confirmed first (`.../user@1000.service/cgroup.controllers` and `cgroup.subtree_control` both list `cpu memory pids` — verified) and the method proven on a currently-active unit (`breezy-trade-supervisor.service` returned a real counter table). A post-exit `high 0` is now defined in the plan as a **failed read**, never a zero. |
| 2 | hunter | **MATERIAL (same defect, second half)** — no positive control: if offer-gate's own `high` reads ≈0 despite its swap evidence, the instrument cannot see a non-zero value and mb-daily's ≈0 proves nothing | **ACCEPTED IN FULL and made binding, not advisory.** §6 adds the control with its direction of failure stated: offer-gate's `high` must be **predicted non-zero before the read** (from its 3.8-5.2 G swap and ~14 min CPU against `MemoryHigh=12G`) and must **read** non-zero by the same method in the same session before mb-daily's ≈0 is trusted. A ≈0 control is defined as **methodology invalid — a recorded measurement defect — not "mb-daily is fine"**, mb-daily's zero then carries no evidential weight, and decision-table row (i) may **not** be excluded on it. §7 step 1(e) carries the same precondition and §8 item 4 makes a control-failed note non-acceptance for the 15c diagnosis. |
| 3 | architect | **No defect named**; full marks withheld only because the measurement has not yet happened | **NOT AWARDED — recorded as a miss**, with the reasoning above. The one substantive thing this record did establish — an independent re-derivation of the corrected mb-daily/offer-gate peak arithmetic from the unit files — is accepted as confirmation that the round-2 citation defect is closed, and nothing in this revision touches that passage. |
| 4 | hunter | Confirmed the `OnFailure=` gap, the 11 timer-backed units, the wrapper-exit inversion test and the `TimeoutStartSec` negative guard all hold on an independent read | **NOTED**, no change required. |

**Rejections:** none.

**Revision 4 self-score (conservative — the item's own arbiter measurement was, until this
revision, specified in a way that could have returned a meaningless zero):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Unchanged: both units get distinct measured diagnoses, the un-named `OnFailure=` structural gap is added, G-04 routed to its own item. |
| Technical correctness and evidence grounding | 20 | **17** | Unit-file citations quoted whole and independently re-derived by a reviewer; the read-method claims in §6 are now measured on this host (`ControlGroup=` empty post-exit, `MemoryPeak` persisting, delegation present, a live positive read) rather than asserted. Deducted 3, unchanged: the plan previously shipped a truncated quote that reversed its own evidence's sign, and the mb-daily throttle contribution is still bounded by argument until the live counter is actually read. |
| Implementation specificity and feasibility | 15 | **14** | 15a fully literal; the arbiter read is now literal too — path resolution, delegation check, liveness requirement, the post-hoc property split, and the control's pass/fail consequence. Deducted 1: scheduling the quiet window, and the fact that the control read requires catching offer-gate mid-run, remain the executor's. |
| Acceptance criteria and validation quality | 20 | 19 | Item 4 now requires the resolved `ControlGroup` path, the pre-read prediction and the control reading, and item 6 pins which figure comes from which source. Three-consecutive-runs acceptance still lands days after merge. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Unchanged: cause-agnostic `OnFailure=` coverage, no alert loop, no auto-retry (reasoned), wrapper masking pinned, notifier residual named. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unchanged: cost-avoidance on measured numbers only; every exclusion names its reason. |
| **Total** | **100** | **93** | |

### Round 4 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| trading-bot-architect (`AUD-15-r4-trading-bot-architect.md`) | **94/100** | **None found**, MATERIAL or MINOR. Re-ran the arbiter command live on this host and confirmed the plan's transcript byte-for-byte. |
| silent-failure-hunter (`AUD-15-r4-silent-failure-hunter.md`) | **88/100** | **1 MATERIAL** — the live `memory.events` read names WHAT to read and WHEN it is valid, but no actor, no cadence, no teardown-race rule, and no comparability requirement between the control read and the diagnostic read. |

**Readiness is the LOWER, 88.** The split repeats this item's own pattern for the third
consecutive round and is recorded as such: **the architect's 94 named no defect and required no
change**, while the hunter, reading the same artefact, found a MATERIAL defect inside the very
measurement the architect had just verified was correctly *specified as a command*. The
architect's own record anticipates the objection — it notes the quiet-window scheduling residual
and then declines to deduct for it a second time — which is exactly how a live-read orchestration
gap stays open across rounds. Per this backlog's standing rule a score without a nameable defect
is not evidence of correctness; the 94 is treated as a miss on this point, and its one substantive
contribution (the live re-run of `systemctl --user show` confirming `ControlGroup=` empty,
`MemoryPeak`/`MemorySwapPeak` persisting, on **this** host, **this** session) is accepted as
independent confirmation that §6's arbiter claim is true.

**Dispositions — every defect and every required change, both reviewers:**

| # | Reviewer | Item | Disposition |
|---|---|---|---|
| 1 | hunter | **MATERIAL** — §7 15b/15c step 1(e) specifies the two static commands but names nobody who performs the live read during an unattended 30–60-minute timer-triggered run | **ACCEPTED IN FULL, and answered literally.** Verified from the artefacts this revision: `TimeoutStartSec=1800` (`breezy-offer-gate-daily.service:81`) and `TimeoutStartSec=3600` (`breezy-mb-daily.service:62`) — runs of very different length, as the reviewer says; both units are `Slice=breezy-studies.slice` (`:46`/`:48`); the no-start rule is `[16:35Z, 01:15Z)` (`deploy/systemd/README.md:939`). §7 step 1(e) now names the actor and the mode: **a one-off DIAGNOSTIC by the implementer at implementation time**, who **starts the unit itself** with `systemctl --user start <unit>.service` rather than waiting for the timer, so the start instant is known and the sampler is running before the cgroup exists. **A permanent sampler was considered and rejected against YAGNI** and stated as such: standing instrumentation to answer a question asked once would also put a second process inside `breezy-studies.slice` during the runs it is measuring. The host constraints are carried into the step as binding — one heavy study at a time, never inside the 16:35Z protected window, never while another study holds the shared studies flock, and therefore **two units = two sequential windows, never concurrent**. Starting a unit is explicitly flagged as an execution-time action; this planning task starts nothing. |
| 2 | hunter | **MATERIAL (same defect, second part)** — no polling cadence and no teardown-race handling: the `show`→`cat` pair is not atomic, and the plan does not say whether a failed `cat` is a dropped sample or a zero | **ACCEPTED IN FULL.** §7 step 1(e) specifies a **bounded polling loop** started alongside the unit: every **30 s** until the unit leaves `active` or a hard cap of **75 minutes**, appending a **timestamped** `memory.events`/`memory.stat` block per sample to a scratch file, never overwritten. The teardown rule is stated in the direction the reviewer required: an empty `ControlGroup=` or a failing `cat` is recorded as **`READ_FAILED`** with its timestamp and **ends the loop** — **never written as `high 0`** — and the reading used is the **last successful pre-teardown sample**, quoted with its timestamp and its offset from start. A run whose loop produced no successful sample **has measured nothing and is re-run**, which closes the residual path by which a torn-down cgroup could still be reported as a real reading. |
| 3 | hunter | **MATERIAL (same defect, third part)** — `memory.events`' `high` is cumulative, so a single sample at an unstated moment in a 30-minute run is not comparable with one from a 60+-minute run; the binding control rule could then accept a false negative | **ACCEPTED IN FULL, at both sites.** §6's positive-control block now states the counter's semantics explicitly (cumulative over the cgroup's lifetime, not a gauge) and fixes the compared quantity: the **final cumulative `high` of each run** — the last good sample — **reported with that run's duration** and the sample's offset from start, **both units sampled at the same 30 s cadence and both carried to their own run's end**. §7 step 1(e) carries the identical rule, and the §6 binding rule is restated in full so it can no longer be read as "somewhere during an active run": offer-gate's final `high` must be materially non-zero **by this same procedure** before mb-daily's ≈ 0 counts for anything. §12's assumption line no longer leaves the quiet window to the executor. |
| 4 | hunter | Required: §8 item 4 must record the cadence and the last-good-sample handling, or an executor satisfies its letter with one early under-reporting snapshot | **ACCEPTED.** §8 item 4 now makes the orchestration itself acceptance: the cadence actually used, the timestamped sample series (or at minimum the last good sample with its timestamp and offset), each unit's run duration, and any `READ_FAILED` samples shown **as** `READ_FAILED` and never as `0`. It states explicitly that a single undated snapshot, or a control read taken by a different method or at a different phase of its run than the diagnostic read, **does not satisfy the item**. §8 item 6's post-fix re-measure inherits the same cadence and last-good-sample rule. |
| 5 | architect | No defect found; the arbiter claim re-verified live on this host; the decision table's refusal to let `TimeoutStartSec` be raised as a disguised fix confirmed mechanically checked by §8 item 9 | **NOTED — confirmations accepted, the score NOT awarded** (see above). Nothing in this revision touches the passages it confirmed. |

**Rejections:** none. The MATERIAL defect was reproduced against the unit files and the README
before editing.

**Revision 5 self-score (conservative — this item's own arbiter measurement has now been found
under-specified in TWO successive rounds, first in where it reads and now in how and when it
samples; the counter it turns on has still never been read):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Unchanged: both units get distinct measured diagnoses, the un-named `OnFailure=` structural gap is added, G-04 routed to its own item. |
| Technical correctness and evidence grounding | 20 | **17** | §6's arbiter claim is now independently re-run on this host by a reviewer, and the unit/README citations underpinning the new orchestration (`:81`, `:62`, `:46`/`:48`, `README.md:939`) were read this revision. Deducted 3, unchanged: the plan once shipped a truncated quote that reversed its own evidence's sign, and the mb-daily throttle contribution is still bounded by argument until the live counter is actually read. |
| Implementation specificity and feasibility | 15 | **13** | The arbiter read is now literal end to end — actor, trigger, cadence, cap, scratch file, teardown rule, last-good-sample rule, comparison quantity, and the host constraints that sequence the two windows. Deducted 2, one MORE than revision 4: the specificity of this exact step was scored 14 while a MATERIAL gap sat inside it, which is evidence about this plan's self-assessment of the step, not only about the gap; and the loop itself is scaffolding the implementer still has to write. |
| Acceptance criteria and validation quality | 20 | **18** | Item 4 now rejects an undated snapshot and requires the cadence, the series, the durations and the `READ_FAILED` markers; item 6 inherits the same rule. Deducted 2: three-consecutive-runs acceptance still lands days after merge, and every 15b/15c acceptance item remains downstream of two strategy-lead rulings. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Unchanged, and not implicated by this round's defect — the diagnostic is build-time scaffolding, deliberately not a permanent unit, so it adds nothing to the unattended surface. Cause-agnostic `OnFailure=` coverage, no alert loop, no auto-retry (reasoned), wrapper masking pinned, notifier residual named. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unchanged: cost-avoidance on measured numbers only; every exclusion names its reason. |
| **Total** | **100** | **91** | |

### Round 5 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| silent-failure-hunter (`reviews/AUD-15-r5-silent-failure-hunter.md`) | **100/100** | None. |
| trading-bot-architect (`reviews/AUD-15-r5-trading-bot-architect.md`) | **100/100** | None. |

Both records scored the revision-5 text in full. Neither is treated as evidence that the item is
finished: the revision they scored was built around a fix-or-retire question that the 09-21
ruling has since **answered in the other direction**, which retires most of the text they
endorsed. The two unanimous 100s are recorded, and the round-6 self-score below is *lower*, not
higher, because a large, previously-unreviewed surface (the re-home) has just entered the plan.

### Round 6 — revision after the 09-21 ruling

| Change | Source | Where |
|---|---|---|
| Both BLOCKERs closed as **RULED: retire both units** | `RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md` §1.4 items 1-2 (ENDORSED) | §4, §12 |
| Fix-path content struck in place as **WITHDRAWN BY RULING**, numbering preserved: the `memory.events` diagnostic, the positive control, the polling orchestration, the `MemoryHigh` reconciliation, the unit split | §1.4 item 1 (*"Do not run the §7 step 1(e) cgroup diagnostic"*) | §5, §6, §7 steps 1/2/5/6, §8 items 4/6, §12 |
| The three study **modules excluded from deletion and edit**, with the PREREG reason | §1.4 item 3 (E5/E12) | §5, §8 item 9 |
| **Binding same-commit re-home** of exactly `asos_recent_refresh.py --since <ASOS_FETCH_START>`; the offer-gate rolling invocation retired, not re-homed; the anchor not forked | Revision 2 addendum §A1 (i)/(ii)/(iii) — supersedes §1.4 item 4 | §5, §6, §7 step 7a-7d |
| Host chosen and justified: **own minimal unit at 13:30Z**, both surviving-consumer hosts rejected on their declared posture | this revision, from the unit files and timers | §6 |
| §A1 RED pin with the **epoch-mtime consumer-cache freshness** leg; existence explicitly non-acceptance | §A1, §A4 | §7 step 7a, §8 items 10-11 |
| **Runtime staleness alert added** after checking 15a's coverage — 15a fires only on `failed`, and the refresh's shortfall path exits 0 | this revision | §5, §6, §7 step 7c, §8 item 12, §9 |
| One-commit deployment, ordered post-deploy verification, revert semantics | §1.4 item 4 (*"No retirement commit may merge without it"*) | §10 |
| Cost avoidance reclassified from plausible to **realised**; the surviving value named | §1.4 items 1-2 + E14 | §11 |

**Revision 6 self-score (conservative — the ruling removed a large verified surface and replaced
it with a smaller UNVERIFIED one):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Both named units disposed of, the structural `OnFailure=` gap retained, G-04 still routed out. Unchanged. |
| Technical correctness and evidence grounding | 20 | **17** | Every new file:line (the anchor, the invocation, the consumer's key and `SystemExit`, both candidate hosts' postures, the timers' `OnCalendar`, the sink entry points) re-read this revision. Deducted 3: the plan's historical citation defect stands on the record, and the re-home's central claim — that this wrapper writes the key that consumer reads — is verified by reading, never yet by a run. |
| Implementation specificity and feasibility | 15 | **13** | The re-home is literal: unit name, slot, slice, ceilings, timeout, flock idiom, anchor handling, three RED tests. Deducted 2: the `36 h` threshold is chosen not derived, and the wrapper's cheap resolution of the consumer's cache path is specified as a fallback rather than settled. |
| Acceptance criteria and validation quality | 20 | **18** | Items 10-12 add the pin, a post-deploy mtime advance and a delivered staleness alert; existence checks excluded by name on both legs. Deducted 2: acceptance item 11 lands only after the first 13:30Z fire, and item 12 needs a contrived aged cache. |
| Autonomous operation, failure handling, recovery | 15 | 14 | The re-home's silent-stale mode is closed on two independent legs and named in §9; the fail-soft exit-0 path is covered by the new alert rather than by `OnFailure=`. Deducted 1: a wrong-but-fresh cache (right mtime, wrong content) is still outside both legs. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Cost avoidance now realised on measured figures; the surviving live-path value preserved by the binding condition; every exclusion names its reason. |
| **Total** | **100** | **91** | |

### Round 6 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| silent-failure-hunter (`reviews/AUD-15-r6-silent-failure-hunter.md`) | **88/100** | **1 MATERIAL** — the freshness check sits after the refresh returns, so a flock-skip bypasses it entirely and no later night can recover the evidence. |
| trading-bot-architect (`reviews/AUD-15-r6-trading-bot-architect.md`) | **94/100** | **1 MATERIAL** — `test_deploy_timer_hours.py:116` hard-pins `breezy-mb-daily.timer`, so the retirement commit makes an existing test fail and §8 item 8's "full gate green" is unreachable. |

**Readiness is the LOWER, 88.** Both records named a real, reproduced defect this round — the
first time in this item's history that the architect's higher score carried one — so neither is
treated as a miss.

**Dispositions — every defect and every required change, both reviewers:**

| # | Reviewer | Item | Disposition |
|---|---|---|---|
| 1 | hunter | **MATERIAL** — the freshness check runs only "after the refresh returns", so on a flock-contention night the wrapper exits at the lock line and the check never executes; a later successful night then rewrites the cache before the check reads it, erasing the evidence permanently | **ACCEPTED IN FULL, and the control flow is now specified rather than inherited.** Reproduced against source: `mb-daily-run.sh:81` is `flock -n 9 \|\| { say "SKIPPED ..."; exit 0; }` and the refresh call is at `:86-87`, i.e. after it. §6 now forbids copying that line verbatim: the lock result is **captured** (`if flock -n 9; then <refresh>; else say "SKIPPED-LOCK ..."; fi`), the `SKIPPED-INFRA`/exit-75 paths at `:79-80` are kept unchanged, and the freshness check runs **after** the `if/else`, on **every** invocation. §9 adds the contention night as a named, closed failure case; §8 item 13 makes the unconditionality itself acceptance. |
| 2 | hunter | Required: a RED test that holds the shared flock during an invocation and proves `asos_cache_stale` can still fire | **ACCEPTED.** §7 step 7c is now three tests: (i) the stale/missing WARN, (ii) `test_the_staleness_check_still_runs_when_the_studies_flock_is_held` — holds the fd-9 `breezy-studies.lock` (reusing the working fixture at `tests/unit/test_analysis_units_serialized.py:752-779`) and asserts no refresh ran, `SKIPPED-LOCK` logged, the WARN **still** delivered, exit 0 — and (iii) the no-false-alarm case. §8 item 13 states that a green item 12 with a red item 13 **is** the revision-6 design and is not acceptance. |
| 3 | hunter/coordinator | Re-examine the 36 h threshold against the 13:30Z cadence and the 15:00Z/15:20Z consumers — justify it or change it | **CHANGED, and the number removed entirely.** Verified this revision: `ASOS_FETCH_END = default_asos_fetch_end()` → `dt.date.today()` (`ma_prelock_winner_ask_study.py:185`, `:168-179`); the refresh builds `[since, today]` (`asos_recent_refresh.py:115-135,153-156`); the key is `sha256` of a URL carrying both dates (`settlement_alignment_study.py:343-345`) — **the key rotates daily**. So (a) 36 h was unreachable, since a file under today's key can never be older than ~24 h, and (b) the consumers' tolerance is **zero** missed nights, not one: a missed refresh is a hard `SystemExit` cache miss at `current_rung_hold_monitor_hypothetical_hold.py:169-170` (15:00Z) and a missing input at `current_rung_hold_exit_window_study.py:16-24` (15:20Z), not a stale read. The rule is now "missing, or mtime before 00:00:00Z of the current UTC day" — no hour constant, fires 90 min ahead of the first consumer, and deliberately tolerant of a legitimate same-day `--obs-source fetch` write (pinned by 7c(iii)). |
| 4 | architect | **MATERIAL** — `assert "breezy-mb-daily.timer" in names` (`test_deploy_timer_hours.py:116`) is a live assertion that the retirement commit breaks, and no step or acceptance item names the file | **ACCEPTED, and the enumeration extended well beyond the one line.** New §7 step **7d-bis** (same commit) plus §8 item 14. Searching the tree for every name-level pin found more: `test_analysis_units_serialized.py`'s `_HEAVY_TIMERS` (`:359-365`, restated `:567-571`), `_HEAVY_SERVICES` (`:366-372`, restated `:623-627`), `_WRAPPERS` (`:373-379`, restated `:756`), `_WRAPPER_OUTPUT_ENV_VAR` (`:386-387`), `_WRAPPER_LOG_FILENAME` (`:391-392`), `test_the_offer_gate_unit_still_passes_the_systemd_home_specifier` (`:659-671`), `test_the_offer_gate_wrapper_requires_its_output_dir_as_an_argument` (`:813-819`), `_A20_SCOPE` (`:674-681`, read `:700`), `_A20_RESIDUAL` (`:682-696`, read `:712-713`) — each of which `is_file()`s or `read_text()`s a path the commit deletes. Verified **safe, no edit**: `test_analysis_units_memory_capped.py:31-32` (filtered through `_EXISTING_UNITS`, `:25-27`). Comment-only: `test_ma_prelock_winner_ask_study.py:392`, `test_mb_current_rung_edge_study.py:618`. Doc table: `deploy/systemd/README.md:388-455` and the inventory lines listed in 7d-bis. The plan states plainly that these are **inventory pins for retired units — not a weakened safety, settlement or contract test**. |
| 5 | architect | Confirmed the tick-collision test scans the tree, so retire-and-reclaim of 13:30Z is structurally correct; no other regression across the six hunks | **NOTED**, no change. 7d-bis records that `_all_timer_files()`-based collision checking and `test_1415_utc_is_owned_by_exactly_one_timer` (`:120-133`) need no edit. |
| 6 | hunter | Evidence-grounding imprecision (not scored): the §12 fallback "resolve it through `current_rung_hold_monitor_hypothetical_hold`'s own helpers" does not avoid a `nautilus_trader` import — both candidate modules import it at module scope | **ACCEPTED as a correction to the fallback's stated rationale**, recorded here rather than by re-writing §12's assumption: the fallback's justification is *cheapness of key resolution*, not avoidance of a Nautilus import, and both candidates do import `nautilus_trader` data-model/parquet symbols at module scope. Nothing in the build depends on the discarded framing. |

### Round 7 — revision after round-6 peer review

| Change | Source | Where |
|---|---|---|
| Freshness check made **unconditional** on every invocation; the `flock` early-`exit 0` idiom explicitly **not** copied; lock-skip logged as `SKIPPED-LOCK` with a named reason; `SKIPPED-INFRA`/exit-75 unchanged | r6 hunter MATERIAL | §6, §9 |
| **36 h threshold withdrawn**; rule re-derived from the daily-rotating cache key and the consumers' zero-missed-night tolerance: missing, or mtime before 00:00:00Z of the current UTC day | r6 hunter + coordinator | §6, §12 |
| Three RED tests at 7c, including the **flock-held** regression pin and the same-day-fetch no-false-alarm case | r6 hunter required change | §7 step 7c, §8 item 13 |
| New step **7d-bis**: update every by-name inventory pin in the SAME retirement commit, enumerated and verified; stated plainly as an inventory pin, not a weakened safety/settlement/contract test | r6 architect MATERIAL | §7 step 7d-bis, §8 item 14 |
| Accepted doc drift named: `ma_prelock_winner_ask_study.py:169-177` stays stale under the zero-diff rule | this revision | §7 step 7d-bis, §8 item 15 |

**Revision 7 self-score (conservative — the two defects closed here were both invisible to this
plan's own author for a full revision, and the re-home has still never run):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Unchanged: both units disposed of, the structural `OnFailure=` gap retained, G-04 routed out. |
| Technical correctness and evidence grounding | 20 | **17** | The cache-key rotation, the consumers' hard-miss behaviour and every pin cited in 7d-bis were read from source this revision. Deducted 3, unchanged: the historical citation defect stands, and the re-home's central claim is still verified by reading, never by a run. |
| Implementation specificity and feasibility | 15 | **13** | The wrapper's control flow is now specified literally rather than inherited from an idiom that contradicted it, and the pin updates are enumerated file:line. Deducted 2: the revision-6 text specified a mechanism that could not fire on its most likely path while scoring itself 13 here, which is evidence about this plan's self-assessment; and the wrapper's cheap key resolution is still a fallback rather than settled. |
| Acceptance criteria and validation quality | 20 | **18** | Items 13-15 add unconditionality, the pin update and the zero-diff negative. Deducted 2: items 11-13 still land only after the first 13:30Z fire or on a contrived cache. |
| Autonomous operation, failure handling, recovery | 15 | **13** | The contention night is now detected same-day, 90 min ahead of the first consumer, and the infra path still reaches `failed`. Deducted 2: a wrong-but-fresh cache (right mtime, wrong content) remains outside both legs, and the WARN is not repeated if it is missed. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unchanged. |
| **Total** | **100** | **90** | |

### Round 7 — peer review

| Reviewer | Score | Material defects |
|---|---|---|
| silent-failure-hunter (`reviews/AUD-15-r7-silent-failure-hunter.md`) | **98/100** | None MATERIAL. 1 required change — §5 and §9 still described the superseded "ages silently" failure shape, contradicting §6's own daily-rotation analysis added in the same revision. |
| trading-bot-architect (`reviews/AUD-15-r7-trading-bot-architect.md`) | **93/100** | 1 required change — the plan never decided whether the new `breezy-asos-refresh.service` joins `test_analysis_units_memory_capped.py`'s **curated** `_CANDIDATE_UNITS`, so the ceilings §6 gives it are verified by no test. 1 MINOR citation drift (`_EXISTING_UNITS` cited `:25-27`, actually `:43-45`); 1 MINOR, non-blocking: retired unit names survive in five non-enforced `docs/plans/*.md` narratives. |

Both reviewers independently re-verified the round-7 fixes against source (the captured-`flock`
control flow, the daily rotation and the 7d-bis enumeration) and found them sound; neither raised a
blocker.

### Round 8 — revision after round-7 peer review

| Change | Source | Where |
|---|---|---|
| **Superseded "silent staleness" language corrected everywhere it survived.** §5 ("the consumer's cache ages silently") and §9 ("goes stale silently" / "never raises the consumer's loud `SystemExit`" / "feeds an ever-older file") now state the accurate shape: the key rotates daily, so a wrong or skipped refresh leaves **today's key missing** and the 15:00Z consumer fails **loudly** (`scripts/analysis/current_rung_hold_monitor_hypothetical_hold.py:169-170`) on essentially the first day. §6's mtime-leg rationale re-based on the same fact. | r7 hunter required change | §5, §6, §9 |
| **The 13:30Z alert's value restated on its real grounds** — 90 minutes of lead time before the first consumer, and a dedicated unambiguous signal about the refresh's own health instead of a downstream crash to trace upstream — rather than on "nothing else would detect it". | r7 hunter | §5, §9 |
| **Provenance note added, ruling untouched:** the endorsed ruling's §A1 (`:285-288`) described the mode as an ever-staler existing file, before the daily rotation was established; that is a factual refinement which strengthens §A1's re-homing condition and changes none of its decisions. | r7 hunter + coordinator | §9 |
| **DECIDED: `breezy-asos-refresh.service` joins `_CANDIDATE_UNITS`** (`test_analysis_units_memory_capped.py:29-41`) in the same commit, because it declares `MemoryHigh=512M`/`MemoryMax=1G` and nothing else pins them; with the `_EXISTING_UNITS` `is_file()` filter (`:43-45`) named explicitly so the entry is ordered after 7a and proven exercised by node id, not silently filtered out. | r7 architect required change | §7 step 7d-bis, §8 item 14 |
| MINOR citation drift corrected: `_EXISTING_UNITS` is `:43-45`, not `:25-27`. | r7 architect MINOR | §7 step 7d-bis |

**Not adopted:** the architect's second MINOR (retired unit names surviving in five
non-pytest-enforced `docs/plans/*.md` narratives). Those documents are historical records of
superseded programmes, none is read by a test, and rewriting them is outside this item's scope;
the retirement is recorded in `deploy/systemd/README.md`, which is the live inventory.

**Latest score:** 90 (revision 7 self-score, unchanged by this documentation-consistency revision;
revision 8 adds one real test-coverage commitment). Round-7 peer: 98 (hunter) / 93 (architect),
neither naming a MATERIAL defect or a blocker — the lower, **93**, is the readiness figure.
Round-6 peer: 88 / 94, both naming a MATERIAL defect, both dispositioned above. Round-5: 100 /
100 — on text the ruling has since superseded. Round-4: 94 / 88; round-3: 94 / 89; round-2: 94 /
100.
**Readiness: revision 8 has had no peer review of its own. It changes no mechanism — the two
round-7 fixes reviewers verified against source are untouched — and its one substantive addition
(the `_CANDIDATE_UNITS` entry) is an explicit answer to a reviewer-required decision. Nothing here
has run.**
**Blockers: NONE.** The two fix-or-retire rulings are RULED and ENDORSED
(`docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md`, review trail
`docs/evidence/reviews/RULING_study_ceiling_exit_review_2026-09-21.md`). 15a was never blocked.
Nothing in this plan has been implemented.


<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-22) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `3b46e14d8e322887ad886f618d677f2c117b6c23e3d61beb3f7312bb52dc38b7`
- **Baseline self-score:** 90/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `silent-failure-hunter` round 8: 100/100 — `reviews/AUD-15-r8-silent-failure-hunter.md`
  - `trading-bot-architect` round 8: 100/100 — `reviews/AUD-15-r8-trading-bot-architect.md`
- **Readiness:** **READY**
- **Unresolved blockers / notes:**
  - None. Fix-or-retire is RULED and peer-ENDORSED (`docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md` RULING 1 + addendum A1): both units retire and the `--since` ASOS refresh is re-homed in the same commit.
- **Full review history:** 16 records, `reviews/AUD-15-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
