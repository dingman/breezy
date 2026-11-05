# AUD-10 — Review record (Round 4, FINAL for this cluster)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: 3d1c9b58a6bab2816df5f028bdb69367a43abcd3bb259b011a504a1ff4e85755
- Round: 4 · Reviewer: trading-bot-architect (promotion-gate/risk-architecture lens)
- Total: 100/100 · Readiness: READY

## Round-3 defect verification (architect's r3 record read; body checked against source, not §13)

| Defect | Verified fixed, against source I re-read myself? |
|---|---|
| MATERIAL 10-4 — `C-KILL`'s input was named only by producing script, no path/keys/reader/staleness rule, while its absence refused the whole run — and a **stale** file would read "not tripped", silently permissive; same under-binding at lower stakes for `C-ESTIMATOR`/`C-N` | YES, and thoroughly. §6b.3 gains a full binding table, re-derived from deployment this round: `score-live-trials-run.sh:118-127` `rm -f`s and rewrites `covered_listed_station_days_<UTC-day>.json` via `structural_dead_stop.py --output`, exiting 1 on counter failure (I re-read `:110-165` and confirmed the `rm -f` + non-zero-exit-on-failure shape at `:118-127`). Six keys, atomic write — I re-read `_write_output_json` at `structural_dead_stop.py:297-326` and the `--output` argparse help text at `:189-192`, both exact. `count_filled_takes` — I re-read `fill_time_count.py:101-118`: `Returns None -- fail closed, never zero -- when source_path is absent or cannot be read`, confirmed exact. `structural_dead()` — I re-read `:110-130`: `evaluable = filled_takes is not None`, `fired = evaluable and count >= MIN... and filled_takes == 0`, so `evaluable=False` really does force `structural_dead=False` and the plan's "never reads `structural_dead` without first asserting `evaluable`" rule is the only correct reading of that function. `KILL_CLOCK_MAX_AGE_SECONDS = 26*3600` with staleness refusing identically to absence — this is the one property that most needed catching and it is now genuinely fail-closed, with C17 giving it six fixtures (one per refusal arm). The "identical call" claim for `count_filled_takes(family_prefix=manifest.trial_id_prefix, since_climate_day=manifest.d0_climate_day)" — I checked `family_tally_v2.py:1290-1297` calls it with `since_climate_day=args.fill_since_climate_day`, and confirmed at `:1273` that `args.fill_since_climate_day` is asserted equal to `manifest.d0_climate_day` before the call, so the plan's claim of an identical call is correct, not merely similar. `C-ESTIMATOR`/`C-N` now name the artefact directory and its sidecars rather than producing scripts. |
| MINOR c1 — "four documented refusals" under-counted `combine_station_day`'s reachable raises by three | YES. I re-read `current_rung_hold_v2.py:183-336` myself: `StationDayAdmissionRefusal(ValueError)` at `:184`; `_MixedDayMissingRungKeyRefusal` at `:230`; `_SameRungOppositeSidesRefusal` at `:237`; and inside `_fold_same_rung_rows`, three further distinct `StationDayAdmissionRefusal` raises at differing `entry_ask`, differing `fee`, and disagreeing `held` — all confirmed present and distinct, for seven reachable shapes total plus the empty-rows `ValueError`. C15 is restated over all seven and additionally pins `StationDayAdmissionRefusal.__bases__`, which is the right defence against the catch silently losing coverage of a future subclass. |
| MINOR c2 — the §10 boot-log line (composed stations + manifest family_id) had no acceptance criterion | YES. New C18, folded into the existing C3 golden composition test rather than a standalone test — the cheapest correct home, since that test already composes the live manifest. |

No round-3 acceptance is falsely claimed; every disposition matches the body against source I
re-derived independently rather than trusted from the plan's own citation.

## Claims verified this round (fresh reads against current source)

| Ref | Claim | Result |
|---|---|---|
| `score-live-trials-run.sh:118-127` writes the six-key counter JSON, exits 1 on failure | CONFIRMED. |
| `structural_dead_stop.py:297-326` atomic `mkstemp`+`os.replace` write | CONFIRMED. |
| `structural_dead_stop.py:110-130` `structural_dead()` fail-closed semantics | CONFIRMED — `evaluable=False` forces `structural_dead=False`, and the docstring states this explicitly. |
| `fill_time_count.py:101-118` `count_filled_takes` returns `None`, never `0`, on an unreadable source | CONFIRMED verbatim in the docstring. |
| `family_tally_v2.py:1273,1290-1297` — `since_climate_day` asserted equal to `manifest.d0_climate_day` before the identical call the plan cites | CONFIRMED. |
| `current_rung_hold_v2.py:184,230,237,269-336` — seven reachable `StationDayAdmissionRefusal`/`ValueError` raise sites, base-class hierarchy | CONFIRMED. |

## Defects

None found. The round-3 MATERIAL defect (10-4) — the one this lens cares most about, since a
silently-permissive KILL-clock read is exactly the "healthy node, silently unable to trade" class
this whole audit exists to close — is closed correctly: the fix does not merely name a file, it
threads the fail-closed property (`evaluable is False` ⇒ refuse, never read `structural_dead` on its
own) through to a concrete test (C17, six arms). The honest residual — no deployed unit writes a
machine-readable KILL *verdict*, so this plan re-derives it from two machine-readable inputs and
pins the derivation equal via C17 — is named as a dependency rather than hidden, exactly as the
brief requires for a genuinely unresolvable-by-this-plan gap.

## Strengths (credited)

`C-KILL`'s "stale ⇒ refuse identically to absent" rule is the single most load-bearing correctness
property in this cluster of three plans, because it is the one place a permissive silent failure
would have reintroduced the exact class of incident (`venue-drift-kills-the-node-silently`,
`a-healthy-node-can-still-be-unable-to-trade`) this whole audit exists to close — and it is now a
tested property (C17), not an assumption. `C-VALIDITY`'s `params_match` clause and `C-PAIRED`'s
`INERT` (never `false`) distinction are both direct, mechanically-enforced controls on this repo's
single most expensive recurring error class (a statistic attached to the wrong family). 10a's
per-site disposition table closes REG-1 completely, including the guard-narrowing repair that
prevents a narrowed manifest from booting with zero strategies silently.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | 10a closes REG-1 across all six sites and the zero-strategy hazard it would have opened; 10b now binds all eight promotion predicates to real artefacts. |
| Technical correctness and evidence grounding | 20 | 20 | Every citation I independently re-opened this round is exact, including the deployment-layer chain (timer, wrapper, script, atomic write) the round-3 defect required be traced end to end. |
| Implementation specificity and feasibility | 15 | 15 | The input that gates the entire nightly run is now specified to path, key set, reader, staleness constant and refusal-reason alphabet; the refusal set is corrected to all seven reachable shapes with the base-class contract stated explicitly. |
| Acceptance criteria and validation quality | 20 | 20 | C17's six arms make the stale-and-permissive failure a test, not a hope; C15 covers all seven refusal shapes plus the class hierarchy; C18 pins the last previously-unpinned observable. |
| Autonomous operation, failure handling, recovery | 15 | 15 | A stale or unevaluable KILL clock now refuses rather than reading as permission — the exact silent-halt class this audit targets, closed with a test. Three hard refusals, content-hash idempotency, read-only posture on both KILL inputs. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Zero-ROI honesty; correctness benefit named as correctness, not return; both strategy-lead blockers retained verbatim; arming, the two operator-reserved caps and the NO-SEND path untouched; the new KILL binding is read-only on both artefacts. |
| **Total** | **100** | **100** | |

## Required changes to reach 100

None.

## Blockers (recorded, not scored)

- **Build, named with an owner:** `C-PAIRED` cannot evaluate until `current_rung_hold_paper_replay.py`
  gains `--family-manifest`. No plan change can resolve it.
- **Dependency, named rather than papered over:** no deployed unit writes a machine-readable KILL
  *verdict* (only the counter JSON is machine-readable); this plan re-derives the verdict and pins
  the derivation equal via C17. If a later item publishes a machine-readable tally verdict, `C-KILL`
  should read it and drop the re-derivation.
- **Strategy lead (score-capping for 10b's correctness, not its build):** whether R5-7/R5-8, written
  for the closed forecast programme, transfer unchanged to a `continuous_rung_hold` family, and what
  champion/challenger means at admissible n = 0. No plan change can resolve it — correctly recorded
  as a ruling, not a design decision.
- **Operator:** arming, live-trading enablement, the two reserved caps. Untouched; no code in this
  item reads, writes or proposes a value for them.
