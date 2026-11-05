# AUD-15 round-7 delta review — trading-bot-architect

Plan: AUD-15-failing-study-units-fix-or-retire-and-alert.md
SHA256: c2a31c72a89be1b3ee01b93e63888ed3bad0ac2492b80615932f27dc626247fc
Round: 7 (delta, FINAL for this cluster)
Reviewer: trading-bot-architect (blind)

## Verified against source

**Flock control-flow fix.** `mb-daily-run.sh:81` confirmed `flock -n 9 || { say "SKIPPED ...";
exit 0; }`, with the refresh call at `:85-86` — after that early exit. The revision's forbidden
pattern is real and its replacement (`if flock -n 9; then <refresh>; else say "SKIPPED-LOCK ...";
fi`, freshness check after the `if/else` unconditionally) closes it. `SKIPPED-INFRA`/`exit 75` at
`:79-80` confirmed unchanged.

**36h→daily-rotation rationale.** `default_asos_fetch_end()` (`ma_prelock_winner_ask_study.py:168`)
confirmed `return today if today is not None else dt.date.today()`; `ASOS_FETCH_END` (`:185`)
confirmed built from it. `refresh_window` (`asos_recent_refresh.py:115-121`) confirmed returns
`(today - lookback_days, today)`. `cache_path_for_url` (`settlement_alignment_study.py:343-344`)
confirmed `sha256(url)`; `asos_url` takes `start`/`end` dates as arguments — the cache key is
therefore genuinely date-dependent and rotates daily, exactly as claimed. The consumer's
`SystemExit` on a cache miss (`current_rung_hold_monitor_hypothetical_hold.py:169`) and its
window-keyed cache read (`:164-166`) both confirmed. This is rigorous, falsifiable grounding, not
an assertion — the threshold withdrawal is correctly derived, not merely asserted.

**Enumeration — I grepped the tree independently rather than trusting the plan's list.**
`/usr/bin/grep -rln` for both unit names and both wrapper names across `.py`/`.md` found every
file the plan's 7d-bis cites, and I read each cited test region directly:
- `_HEAVY_TIMERS`/`_HEAVY_SERVICES`/`_WRAPPERS`/`_WRAPPER_OUTPUT_ENV_VAR`/`_WRAPPER_LOG_FILENAME`
  (`test_analysis_units_serialized.py:359-392`) CONFIRMED exact, literal expected sets — these
  would break as claimed.
- `_A20_SCOPE` (`:674-681`) CONFIRMED to include `deploy/systemd/breezy-offer-gate-daily.timer`
  under a live `path.is_file()` assertion (`:700`) — deleting the file breaks this test, not
  merely a stale reference. `_A20_RESIDUAL` (`:682-696`) CONFIRMED to include
  `breezy-mb-daily.timer` under a live `.read_text()` call (`:712-713`) — deleting the file raises
  `FileNotFoundError` there. Both are genuine, previously-real breaks, correctly caught.
- `test_deploy_timer_hours.py:116` re-confirmed (my own round-6 finding, now fixed by 7d-bis).
- `test_analysis_units_memory_capped.py`'s `_EXISTING_UNITS` mechanism (`:43-44`) CONFIRMED to be
  a live filter (`[name for name in _CANDIDATE_UNITS if (_DEPLOY_DIR / name).is_file()]`), so the
  plan's "verified safe, no edit" claim for the *retired* names is correct. **Citation drift, MINOR:**
  the plan cites `_EXISTING_UNITS` at `:25-27`; that range is actually `_CANDIDATE_UNITS`'s
  opening lines, and `_EXISTING_UNITS` itself is at `:43-44`. Immaterial to the claim's substance.
- The two "comment-only" citations (`test_ma_prelock_winner_ask_study.py:392`,
  `test_mb_current_rung_edge_study.py:618`) confirmed non-assertion prose.

## Defect found — the coordinator's own check point, verified real

**The new `breezy-asos-refresh` unit is never evaluated for entry into
`test_analysis_units_memory_capped.py`'s coverage list, despite declaring its own ceilings that no
test currently verifies for it.** `_CANDIDATE_UNITS` (`:29-40`) is confirmed to be a **curated,
non-exhaustive** list — it includes not only the three heavy studies but also
`breezy-family-tally@.service`, `breezy-live-tally.service`, `breezy-score-live-trials.service`,
`breezy-quote-tape-ingest.service`, while **excluding** `breezy-position-monitor-report.service`
and `breezy-exit-window-study.service`. So membership is a real, non-mechanical editorial decision
this repo already makes per-unit, not "every unit on `breezy-studies.slice`" and not "every heavy
study." The plan's 7d-bis explicitly reasons about the *heavy* tables (`_HEAVY_TIMERS` etc.) and
states why the new unit is correctly excluded from them ("it is not a heavy study"), but for
`test_analysis_units_memory_capped.py` — whose own docstring states its scope as "every **nightly
analysis unit**," a broader category the new HTTP-GET-and-write job on the same slice plausibly
falls into — the plan only states "Verified SAFE, no edit" for the retirement's effect on the
*existing* names. It never asks or answers whether the new unit should be **added**. §6 commits
the new unit to `MemoryHigh=512M`/`MemoryMax=1G`, but as written, no automated test checks that
declaration holds, that `MemoryHigh < MemoryMax`, or that it stays within the 16G incident-response
ceiling — the exact protections `_EXISTING_UNITS`'s three parametrized tests provide every other
member. This is the concrete instance of "must enter those tables so it inherits the protections"
that the coordinator asked me to verify, and the plan does not do it.

**Required change:** add one sentence to §7 step 7d-bis (or a new sub-step) explicitly deciding
whether `breezy-asos-refresh.service` joins `_CANDIDATE_UNITS`. Given it shares
`breezy-studies.slice` and declares its own cgroup ceilings in this same commit, the defensible
default is **yes, add it** — the three parametrized checks are cheap and the unit trivially passes
them (512M < 1G ≤ 16G) — with a one-line reason if the author instead chooses to treat it like
`position-monitor-report`/`exit-window-study` (excluded) rather than like
`breezy-family-tally@`/`breezy-live-tally` (included). Either answer is acceptable; the plan
currently gives neither.

**MINOR, non-blocking:** several `docs/plans/*.md` narrative files
(`SCOPE_STOP_AND_OPS_SERIALIZE_2026-09-12.md`, `FORECAST_EDGE_FAMILY_Rev5_2026-09-18.md`,
`SCORER_TALLY_BCA_BRIEF_2026-09-04.md`, `FORECAST_TO_LEARNING_WORK_BREAKDOWN_2026-09-18.md`,
`CURRENT_RUNG_HOLD_BLUEPRINT_2026-09-04.md`) reference the retired unit names in prose and are not
enumerated in 7d-bis. None are pytest-enforced, so "full gate green" is unaffected, and most
concern already-superseded programmes (the forecast-edge family is itself TERMINAL) — this is
documentation hygiene, not a gate-blocking gap, and I checked one live-looking lead
(`SCOPE_STOP_AND_OPS_SERIALIZE_2026-09-12.md:118` cites a `tests/unit/test_deploy_disabled_timers.py`
that does not exist in the tree, so it is a dead reference to an abandoned prior design, not a
current constraint). Not scored as material.

## Sweep of the rest

No other regression found. The three RED tests at 7c correctly target the flock-held path (the
actual round-6 defect) rather than re-testing the already-working stale/missing case; the
same-day-fetch no-false-alarm test (7c-iii) is the correct complement to a boundary defined
without an hour constant. §8 items 13-15 and §9's new failure cases are internally consistent with
the mechanism changes.

## Per-criterion scoring

| Criterion | Cap | Points | Rationale |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | Both round-6 defects closed thoroughly, with the fix mechanisms independently re-derived from source and verified sound. Deducted 1 for the narrative-doc completeness gap (non-blocking, named above). |
| Technical correctness and evidence grounding | 20 | 18 | Every load-bearing citation for both fixes re-verified from source and correct, including the two genuinely live-breaking assertions in `_A20_SCOPE`/`_A20_RESIDUAL` I confirmed independently. Deducted 2 for the unaddressed `test_analysis_units_memory_capped.py` coverage question — a real fact about the tree this revision's own enumeration pass should have surfaced. |
| Implementation specificity and feasibility | 15 | 13 | The wrapper's control flow and the freshness rule are now fully literal. Deducted 2 for the same coverage-table gap: the new unit's own declared ceilings are unverified by any named test. |
| Acceptance criteria and validation quality | 20 | 19 | Items 13-15 correctly target the two round-6 defects with falsifiable tests, including the regression pin for the flock-held path. Deducted 1: no acceptance item covers whether the new unit's memory ceilings are automatically checked. |
| Autonomous operation, failure handling and recovery | 15 | 14 | The contention-night blind spot is closed and detected same-day, 90 minutes ahead of the first consumer; the infra-failure path is unchanged and still reaches `failed`. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unchanged; no operator-reserved value touched. |
| **Total** | **100** | **93** | |

## Required changes

One: decide and state, in §7 step 7d-bis, whether `breezy-asos-refresh.service` is added to
`test_analysis_units_memory_capped.py`'s `_CANDIDATE_UNITS`, given that list is curated (not
"every slice member") and the new unit is the first to ship its own memory ceilings in this
commit without any test verifying them.

## Blockers

None. Both fix-or-retire rulings remain RULED and peer-ENDORSED.
