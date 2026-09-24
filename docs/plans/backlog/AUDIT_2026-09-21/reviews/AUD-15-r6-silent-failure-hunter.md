# AUD-15 — Round 6 review (silent-failure-hunter, ruling-application delta)

**Plan file:** AUD-15-failing-study-units-fix-or-retire-and-alert.md
**SHA256:** 45f00e04d057ee4810c659619cb75c26d07c50d69f5f74b9ef1223f4c7d69618 (verified via `sha256sum`)
**Round:** 6 (delta, not peer-scored — reviewed fresh per coordinator brief)
**Reviewer:** silent-failure-hunter (independent, blind)

## Inputs read

`docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md` RULING 1 (§1.1-1.5) and
the Revision 2 addendum §A1 (supersedes §1.4 item 4). Plan diff (+307/-215). Source:
`deploy/systemd/mb-daily-run.sh`, `offer-gate-daily-run.sh`, three timers, `ma_prelock_winner_ask_study.py`,
`current_rung_hold_monitor_hypothetical_hold.py`.

## Claims verified against source

| Claim | Status |
|---|---|
| `breezy-mb-daily.timer` fires `13:30:00 UTC`; `breezy-position-monitor-report.timer` `15:00:00 UTC`; `breezy-exit-window-study.timer` `15:20:00 UTC` | CONFIRMED, exact `OnCalendar` lines |
| `ASOS_FETCH_START: Final[dt.date] = dt.date(2026, 8, 30)` at `ma_prelock_winner_ask_study.py:184` | CONFIRMED, exact line |
| Flock idiom `flock -n 9 || { say "SKIPPED..."; exit 0; }` at `mb-daily-run.sh:81` / `offer-gate-daily-run.sh:70` — identical in both wrappers, and the plan cites `mb-daily-run.sh:80-81` as the idiom to copy | CONFIRMED, byte-identical in both files |
| Retired wrappers' only side effects: the ASOS refresh call, their own study output file(s), and a log — no other shared state written | CONFIRMED by reading both scripts in full |
| Scripts excluded from deletion (`cli_basis_offer_gate_scan.py`, `ma_prelock_winner_ask_study.py`, `mb_current_rung_edge_study.py`) | CONFIRMED present in §5 exclusions |
| `current_rung_hold_monitor_hypothetical_hold.py` imports `nautilus_trader.model.data.OrderBookDepth10` and `nautilus_trader.persistence.catalog.parquet.ParquetDataCatalog` at module scope | CONFIRMED — the plan's §12 fallback ("resolve it through `current_rung_hold_monitor_hypothetical_hold`'s own helpers instead") does not actually avoid a `nautilus_trader` import; both candidate modules import it. Minor evidence-grounding imprecision, not scored as a defect below: these are data-model/parquet imports, not a live-node bootstrap, so the practical cost is likely small — but the plan frames the fallback as if it side-steps "importing Nautilus," which it does not. |

## MATERIAL defect — the new staleness check is structurally blind to the flock-contention skip path, the most realistic cause of a missed refresh

The coordinator's question — "a skipped refresh is SILENT unless the staleness alert catches it — does it?" — traces to a concrete, verified gap.

§6 describes the new wrapper's staleness check as running **"after the refresh returns"**: *"The wrapper, after the refresh returns, resolves the consumer's own cache path... compares its epoch mtime against now..."* The wrapper's flock guard is specified to copy the **existing idiom verbatim**: `flock -n 9 || { say "SKIPPED..."; exit 0; }` (`mb-daily-run.sh:81`) — confirmed above to be a single line that, on contention, **exits the script immediately, before the refresh subprocess is ever invoked**. The refresh call in both existing wrappers comes several lines *after* this guard, never before it.

Composing these two facts: on a night the shared studies flock is held (contention with another job — plausibly `k1-daily`, per §12's own "k1-daily was mid-run at audit time" note, or any future study sharing the lock), the wrapper exits 0 at the flock line. It never reaches the refresh call, and therefore never reaches the "after the refresh returns" freshness-check block. **The staleness alert cannot fire on the exact night it would need to.**

This is not merely a delayed-detection gap — it is worse than that, and worse than the coordinator's framing of "is the 36h threshold right" implies the plan should be attacked on, because **the check design makes it structurally impossible for a flock-skip to ever be detected, regardless of duration**: on any *later* night the flock is free, the refresh subprocess runs and (on success) rewrites the cache file with a fresh mtime **before** the freshness check evaluates it — so the check that follows sees a freshly-written file and finds nothing stale, permanently erasing the evidence that an earlier night (or nights) was skipped. The only way this design's staleness check can ever fire at all is the ONE scenario the plan explicitly names and tests — the refresh subprocess runs (flock acquired) but reports a documented fetch **shortfall** (§9: "the refresh's shortfall path exits 0... the staleness WARN is what fires") — which leaves the file's mtime unchanged and is therefore observable. The flock-contention scenario, which is materially at least as plausible (it is the exact mechanism the shared-flock serialization exists to invoke, and the new unit is scheduled at 13:30Z specifically to avoid one class of contention while remaining exposed to any other job — e.g. k1-daily — that might still be running then), produces **zero signal, on any night, ever**, under the design as specified.

Consequently the "36 h threshold" question the coordinator asks is close to moot: the threshold's correctness is irrelevant to the flock-skip path, because that path never reaches the comparison at all. Against the *shortfall* path alone the threshold is reasonably chosen (daily 13:30Z cadence, one missed successful write plus slack, well ahead of the 15:00Z/15:20Z consumers), but that is the smaller half of the risk this mechanism was built to close.

**Required change:** move the freshness check outside the flock-guarded body (or otherwise make it unconditional on the refresh subprocess having run) so it evaluates the consumer's cache mtime on **every** invocation of the wrapper, including a flock-skip — this is the only placement that can catch a contention-caused silent gap, mirroring the check's own explicit purpose. Add a RED test that holds the shared flock during a scheduled invocation and asserts the staleness WARN can still fire (on a subsequent check, once the cache genuinely crosses the threshold) — the currently-specified `test_the_asos_refresh_wrapper_alerts_on_a_stale_consumer_cache` (§7 step 7c), as described, ages the cache and checks for a WARN without stating whether the flock-contention path is exercised, so it would not by itself catch a regression to the current design.

## Other attack points — cleared

- **13:30Z timing**: correctly ahead of both consumers (15:00Z, 15:20Z) by 90/110 minutes on a night the refresh runs — confirmed against the three timers' exact `OnCalendar` values. No retry exists before either consumer fires if 13:30Z is skipped, which is exactly what makes the flock-skip gap above consequential rather than academic.
- **Anchor not forked**: `ASOS_FETCH_START` exists at the exact cited line (`:184`); the plan's RED pin imports it rather than restating the literal, closing the fork risk the ruling's §A1(iii) names.
- **Scripts stay undeleted**: confirmed in §5's exclusions, matching ruling §1.4 item 3 exactly.
- **No other side effect of the two retired wrappers dropped silently**: read both wrapper scripts in full — their only outputs are the ASOS refresh, their own already-established-unread study artefacts, and a log file. Nothing else is written or touched.

## Per-criterion points

| Criterion | Cap | Points | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | The ruling (RULING 1 plus the A1 addendum) is applied completely and correctly in every section it touches; the fix-path withdrawal, the module-deletion exclusion, and the narrowed re-home scope (fixed-window only, not the rolling invocation) are all faithful to the ruling text. |
| Technical correctness and evidence grounding | 20 | 20 | Every citation checked this session (timers, anchor, flock idiom, wrapper contents) is accurate. The defect above is a design/architecture gap, not a misstated fact. |
| Implementation specificity and feasibility | 15 | **11** | **MATERIAL defect above**: the freshness check's placement relative to the flock guard leaves the mechanism unable to detect the most plausible real-world cause of a missed refresh. This is the load-bearing new content of this revision, and it does not close the gap it was written to close. |
| Acceptance criteria and validation quality | 20 | **17** | Items 10-12 are otherwise well-specified (epoch-mtime, not existence; a delivered artefact, not a log line), but none exercises the flock-contention path, so the specified acceptance suite could pass in full while carrying the blind spot above. |
| Autonomous operation, failure handling, recovery | 15 | **10** | This criterion is where the defect lands hardest: the entire justification for building this alert ("the same detection-without-delivery shape this item exists to close") is defeated for the scenario most likely to actually occur in a shared-flock environment. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unaffected — cost avoidance is now realised rather than hypothetical, exclusions correctly scoped, no invented figure. |
| **Total** | **100** | **88** | |

## Required changes (summary)

1. Restructure the wrapper so the consumer-cache freshness check runs **unconditionally**, independent of whether the flock was acquired and the refresh subprocess actually ran — not only "after the refresh returns."
2. Add a RED test that holds the shared flock during a scheduled invocation and confirms the staleness mechanism remains capable of firing once the cache genuinely crosses the threshold, rather than being silently bypassed on every contention night.

## Blockers

None. R-1/R-2-equivalent rulings for 15b/15c are RULED and peer-ENDORSED; this is a build-side design gap inside an already-buildable increment, fixable within the plan's own scope.
