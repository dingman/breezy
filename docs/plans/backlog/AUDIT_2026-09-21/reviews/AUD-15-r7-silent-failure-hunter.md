# AUD-15 — Round 7 review (silent-failure-hunter, delta on round-6 defects)

**Plan file:** AUD-15-failing-study-units-fix-or-retire-and-alert.md
**SHA256:** c2a31c72a89be1b3ee01b93e63888ed3bad0ac2492b80615932f27dc626247fc (verified via `sha256sum`)
**Round:** 7 (delta)
**Reviewer:** silent-failure-hunter (independent, blind)

## Verification of the unconditional-check fix (round-6 MATERIAL defect)

§6 now specifies the lock result is **captured**, not acted on by `exit`: `if flock -n 9; then <refresh>; else say "SKIPPED-LOCK -- ..."; fi`, explicitly forbidding a verbatim copy of `mb-daily-run.sh:81`'s `flock -n 9 || { ...; exit 0; }`. The freshness check runs "after that `if/else`, on every path." §7 step 7c(ii) (`test_the_staleness_check_still_runs_when_the_studies_flock_is_held`) holds the shared flock for the whole invocation and asserts: no refresh subprocess ran, `SKIPPED-LOCK` logged, the `asos_cache_stale` WARN **still fires**, exit 0. This is a genuine, correctly-targeted fix — it addresses the exact mechanism (single early `exit` bypassing everything downstream) I traced last round, not merely a restatement of intent. §8 item 13 makes the unconditionality itself acceptance and explicitly states "a passing item 12 with a failing item 13 is the revision-6 design and is not acceptance," closing the regression risk of silently reverting to the old shape.

## Verification of the daily-key-rotation claim

| Claim | Status |
|---|---|
| `default_asos_fetch_end()` returns `dt.date.today()` | CONFIRMED, `ma_prelock_winner_ask_study.py:168-179`, `ASOS_FETCH_END: Final[dt.date] = default_asos_fetch_end()` at `:185` |
| `refresh_window(*, today, lookback_days)` returns `(today - lookback_days, today)` — end is always "today" | CONFIRMED, `asos_recent_refresh.py:115-124`; used at `:153` (`start, end = refresh_window(...)`) |
| `cache_path_for_url` = `sha256(url.encode()).hexdigest()` | CONFIRMED, `settlement_alignment_study.py:342-344` (plan cites `:343-345`, off by one line, immaterial) |
| `asos_url(iem_asos_id, start, end)` — both dates are part of the URL, hence the hash | CONFIRMED, def at `:408` |
| Monitor's cache-miss raises `SystemExit` | CONFIRMED, `current_rung_hold_monitor_hypothetical_hold.py:168-169` (`if not raw_path.exists(): raise SystemExit(...)`) — plan cites `:169-170`, off by one, immaterial |
| Exit-window study defaults `--obs-source cache`, reports "a missing input, never fabricated" on a cache miss | CONFIRMED, `current_rung_hold_exit_window_study.py:16-24` |

The rotation claim is correct: since the fixed-window key's `end` is always "today" (evaluated fresh at each process's own start), a file under **today's specific hash** can only ever have been written today. This genuinely makes the withdrawn 36h threshold dead code (an existing resolved path is never >~24h old) and correctly reduces the consumer tolerance to zero missed nights. The withdrawn-threshold rule (missing, or mtime before 00:00:00Z UTC of the current day) is airtight against the 13:30Z check time and the 15:00Z/15:20Z consumers: a successful 13:30Z write always postdates that day's midnight, so no false alarm; any file from a prior day predates it, so no missed detection. **UTC-midnight is the correct boundary** — it is exactly the day-partition the rotation itself uses (`dt.date.today()`), not an independently-chosen number.

## New defect — the corrected daily-rotation understanding was not propagated to two sibling passages, which still describe the superseded "silent staleness" failure shape

The coordinator's specific question — is the plan's earlier "fails silently stale" language now corrected everywhere — resolves to **no**. Two passages elsewhere in the plan retain the pre-rotation-discovery framing and are now technically inconsistent with §6/§12's own corrected model:

1. **§5** (scope, unchanged this round): *"...a refresh that fetches nothing exits 0, the unit succeeds, and the consumer's cache **ages silently**."*
2. **§9** (unchanged this round): *"**The re-home is wrong and the cache goes stale silently**... The fixed-window file already exists, so a wrong key **never raises the consumer's loud `SystemExit`**; it just **feeds an ever-older file**."*

Both describe a "slow staleness accumulation" failure shape that the plan's own §6 rotation analysis (added this round) has since disproven for this specific cache key. Because the key rotates daily, a wrong re-home (or any sustained refresh failure) does **not** leave an aging-but-present file — it leaves **today's specific key permanently absent**, which is exactly the "missing" leg of the rule §6 defines two sections earlier, and which — per my own re-derivation above — would in fact trip the consumer's `SystemExit` on essentially the **first** day the wrong wiring ships (today's key was never written under the wrong invocation; yesterday's differently-hashed file does not satisfy today's lookup), not after some accumulation period. §9's own claim that a wrong key "never raises the consumer's loud SystemExit" is the opposite of what the rotation analysis two paragraphs prior establishes for the runtime WARN's own resolved path.

This does **not** weaken the actual protection: both named legs (the build-time §A1 pin and the runtime WARN) still close the "wrong re-home" case, and — read correctly — they close it *faster* than the stale prose claims. This is a technical-correctness/internal-consistency defect (the coordinator's own framing: "is the language now corrected everywhere"), not a functional gap in the mechanism itself.

**Required change:** rewrite §5's "ages silently" clause and §9's "goes stale silently"/"never raises... SystemExit"/"feeds an ever-older file" bullet to state the corrected failure shape — a wrong or skipped refresh leaves **today's specific key missing**, not an aging file present — consistent with §6's rotation analysis, so a future reader does not reconstruct the wrong mental model from the nearest bullet they happen to read.

## Does the 13:30Z alert still add value under the corrected understanding? Yes.

Even though a genuine miss would now also surface as a loud `SystemExit` in the 15:00Z consumer's own run, the 13:30Z WARN remains valuable for two independent reasons: (1) it delivers through the alert sink **90 minutes earlier**, giving an operator lead time to intervene (e.g. a manual refresh) before either downstream consumer actually runs and fails/reports a missing input; (2) it is a **dedicated, unambiguous signal about the refresh's own health**, decoupled from whichever alerting (if any) the downstream consumer scripts carry on their own crash paths — an operator seeing `asos_cache_stale` knows immediately where the fault is, rather than having to trace a `SystemExit` in an unrelated script back to an upstream cache-population failure.

## Verification of §7d-bis (architect's round-6 defect, checked for regression)

Spot-checked `test_deploy_timer_hours.py:116` and the `test_analysis_units_serialized.py` enumeration (`_HEAVY_TIMERS`, `_HEAVY_SERVICES`, `_WRAPPERS`, the two named unit-specific tests, `_A20_SCOPE`/`_A20_RESIDUAL`) — the file:line citations are internally consistent with the round-6 architect record and this revision correctly separates them from `test_analysis_units_memory_capped.py:31-32` (filtered, no edit needed) and the two comment-only references. No regression found in this hunk.

## Per-criterion points

| Criterion | Cap | Points | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | Ruling applied completely; both round-6 MATERIAL defects addressed at their root cause. |
| Technical correctness and evidence grounding | 20 | **18** | Every new citation (rotation mechanics, SystemExit line, flock idiom) verified accurate. Deducted 2: the corrected understanding this round establishes is not propagated to two sibling passages (§5, §9), which now contradict it. |
| Implementation specificity and feasibility | 15 | 15 | The wrapper's control flow is fully literal (captured lock result, named `SKIPPED-LOCK` reason, unconditional check placement); the 7d-bis inventory-pin enumeration is file:line exhaustive. |
| Acceptance criteria and validation quality | 20 | 20 | Items 13-15 make unconditionality, the pin update, and the zero-diff negative all falsifiable; 7c(ii)/(iii) close the regression and false-alarm risks respectively. |
| Autonomous operation, failure handling, recovery | 15 | 15 | The round-6 blind spot (flock-skip silently bypassing detection) is genuinely and robustly closed, verified against source; the lock-infrastructure path still correctly reaches `failed`/`OnFailure=`. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unaffected. |
| **Total** | **100** | **98** | |

## Required changes (summary)

1. Update §5's and §9's "ages silently"/"goes stale silently"/"never raises... SystemExit"/"feeds an ever-older file" language to match §6's own daily-rotation analysis: a wrong or skipped refresh leaves today's specific key **missing**, not an existing file slowly aging.

## Blockers

None. R-1/R-2-equivalent rulings for 15b/15c remain RULED and peer-ENDORSED; this is a documentation-consistency gap inside an already-sound mechanism.
