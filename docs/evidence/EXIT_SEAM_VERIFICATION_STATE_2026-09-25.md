# Exit-seam verification state — 2026-09-25

AUD-07 §7 step 0 (read-only evidence). Nothing armed, started, stopped or
modified in the collection of this evidence. Scope: original plan steps
0–6 only (B/B2, C1–C3, D, the standing AUD-04 reconciliation). Steps 7,
7b, 7c, 8, 9 are out of scope for this pass (7/7b gated on the Stage M
ruling per the 2026-09-25 amendment).

## Finding A — the gate is closed; both L-22 halves visible (re-verified, unchanged)

`src/breezy/persistence/exit_gate.py:55` still carries
`_EXIT_RULE_REGISTERED_FAMILIES = frozenset({"pm_us_crh_exit_v4"})`, byte
identical to the plan's citation — this item does not touch this file
(diff will be empty at merge). `deploy/families/pm_us_crh_exit_v4.json` is
still `DRAFT_NOT_REGISTERED`, still carries no `exit_rule` key, and still
carries the all-zero placeholder shas. Step 7 (registration-package
minting) is out of scope for this pass (gated behind Stage M per the
amendment) — the manifest is unchanged.

## Finding B — step-0 table drift (re-verified against the LAST SUCCESSFUL nightly run)

Rev 2 Appendix A.3 (run `20260916_initial`) vs. the last artefact the
nightly timer actually completed, `2026-09-20_nightly` (see Finding D below
for why later nights produced no artefact at all):

| Metric | Rev 2 A.3 (`20260916_initial`) | `2026-09-20_nightly` |
|---|---|---|
| `sum_r_best_pnl` | −0.44 | −0.0400 |
| `threatened_before_exit_side_emptied` | 1/5 | 1/5 |
| `dead_before_exit_side_emptied` | 0/5 | 0/5 |
| `median_minutes_last_executable_to_dead` | +93 | +50.28 |
| `median_minutes_last_executable_to_threatened` | (not tabulated as a summary stat in A.3; the one qualifying row is MIA NO 18:22Z vs 19:36Z) | −74.119… |
| `depth_source` | staged for 4/5 rows ("the parquet catalog is stranded before the fills, ING-1") | `catalog` for all 5/5 rows |

**Cause, established from the artefact rather than assumed:** the 09-20
Markdown table's `depth_source` column reads `catalog` on every row. Rev 2
A.3 explicitly recorded candidate (i) — "the staged-Depth10 substitution …
has since been replaced by real catalog rows" — and this is exactly what
the current artefact shows: zero `staged` rows remain. The parquet
converter caught up on the ING-1 backlog between 09-16 and 09-20, so the
CURRENT run replays every position against the real committed catalog
instead of the recorder's raw staging tape. This is candidate (i), not
(ii) (an IEM cache refresh) or (iii) (a code change to the study since
09-16) — no code change to `exit_window_core.py`/`exit_window_report.py`
lies between those two runs' git history that would alter R-BEST/R-DEAD
pricing, and the depth-source column is a direct, non-inferential
signature of exactly the (i) substitution.

Sample size is unchanged (N=5, same five positions, same `trial_id`s) — the
divergence is a data-quality improvement (real captured order-book depth
replacing staged fallback frames), not a population change. See Finding D
for the negative-median closing check (this file's finding, not
re-derived here).

## Finding C — LOCATED, and fixed this pass (commit `f95f63d`)

**C1 (family binding).** Confirmed exactly as the plan describes:
`_DEFAULT_MONITORED_FAMILY_ID = "pm_us_crh_cont"`
(`position_monitor_nightly_report.py:119`, pre-fix) was used because the
wrapper's `ARGS` block never passed the optional `--family-manifest`. Fixed
this pass: the wrapper now enumerates every REGISTERED, `venue=polymarket_us`
manifest under `deploy/families/` (today: `pm_us_crh_v2`, `pm_us_crh_v4`,
`pm_us_crh_cont` — three, not one) and runs the report once per family; an
unbound run now renders `UNBOUND (no manifest supplied)`. `pm_us_crh_v4`
and `pm_us_crh_cont` share `trial_id_prefix="continuous_rung_hold/trial/"`
(AUD-05 D-D, re-verified today by reading both manifests) — a trial
matching both is now reported `AMBIGUOUS_FAMILY` rather than picked.

**C2/C3 (position universe) — UPDATED FINDING, drift from the 09-21 record.**
The 09-21 plan text states "there is no `monitor/` directory at all."
Verified TODAY, read-only:

```
$ ls ~/.local/share/breezy/catalog/quote_tape/monitor/summaries
position_monitor_summaries_20260922T164011274098669Z.parquet
```

The `monitor/summaries` directory **now exists** and contains **one** row:
`trial_id=continuous_rung_hold/trial/SFO/2026-09-21/tc-temp-sfohigh-2026-09-21-gte66lt67f.POLYMARKET_US`,
`settled_pnl=None`, `settled_held=None` (still open/unsettled). The path
matches `composition.py:563,663`'s derivation exactly
(`monitor_root = catalog_root.parent / "monitor"`,
`summaries_dir = monitor_root / "summaries"`), confirming this is a real
write by the live monitor, not a path/permission artefact.

**C3 determination: branch (a) — the monitor legitimately writes summaries
only when a position closes (or is flushed on stop), and closes are rare —
not branch (b), a path/permission defect.** The existence of exactly one
real summary, at the exact composition-derived path, with plausible
content (a real live trial_id, monitor_seq=1), refutes a path/permission
failure: the write path works. The N=5 exit-corpus fills (2026-09-13/15)
predate this summary store's only entry (2026-09-21) and are drawn from a
DIFFERENT source entirely (`read_filled_trials_state_db`, the durable
fill ledger) — so the monitor-summaries universe and the exit-window-study
universe remain two different, non-overlapping population as of today,
exactly as C2 describes. This is why C2's fix (state the universe
explicitly, plus an independent ledger count) is the correct remedy
regardless of the exact historical count: it is generic to N=0 or N=1.

## Finding D — the exit-window-study TIMER ITSELF has failed for 3 consecutive nights (NEW, discovered this pass)

Read-only from `~/.local/share/breezy/derived/exit_window_study.log` and
`journalctl --user -u breezy-exit-window-study.service`:

| Date (UTC) | Result | Cause |
|---|---|---|
| 2026-09-20 | OK | — |
| 2026-09-21 | OK | — |
| 2026-09-22 15:20:18Z | **FAILED, exit 1** | `httpx.HTTPStatusError: 429 Too Many Requests` from IEM mesonet ASOS, uncaught, propagated to `main()` |
| 2026-09-23 15:20:19Z | **FAILED, exit 1** | same |
| 2026-09-24 15:20:57Z | **FAILED, exit 1** | same |

`~/.local/share/breezy/derived/exit_window_study/2026-09-{21,22,23,24}_nightly/`
are each empty directories (`mkdir -p` ran; `main()` never reached the
JSON/Markdown write). This is a MORE severe instance of exactly the
"a job that cannot progress must say so" gap Finding D (D8-style corpus
alert) is built to close — except here the job did not even reach the
point of computing `n_positions_new_since_previous_run`, it crashed first.

**Root-cause status, checked against the code actually in this worktree
(base `937edec`, byte-identical to the deployed
`/home/jon/breezy` tree in the affected region, verified by diff):** the
call site (`run_exit_window_study`, `_station_asos_text` under
`--obs-source fetch`) is ALREADY wrapped in
`try: ... except (httpx.HTTPStatusError, httpx.TransportError): failed_fetches += 1; missing.append(...); continue`
in the code as it stands today. The historical tracebacks cite a line
number (482) that does not match this call's current absolute line
(524) in either tree, indicating the crashes on 09-22–09-24 ran against an
OLDER revision of this file that either lacked this except clause or had
it at a different scope; a later, already-merged commit appears to have
already added the protection this item would otherwise have had to build.
**This is reported as-is, not re-verified live** (re-running the study is
out of scope for read-only evidence collection and would require a network
fetch this environment's egress firewall blocks in tests) — the 15:20 UTC
2026-09-25 run (not yet due at the time of writing) is the first
opportunity to confirm whether the fix holds. Recorded here so the
`EXIT_CORPUS_FROZEN` alert (steps 3–4, this item) is evaluated against a
job that may still occasionally fail outright, not only one that
legitimately produces zero new positions.

## Enabled-timer inventory (read-only, `systemctl --user list-timers --all`)

| Timer | Next | Last |
|---|---|---|
| `breezy-score-live-trials.timer` | 2026-09-25 14:15 UTC | 2026-09-24 14:15 UTC |
| `breezy-position-monitor-report.timer` | 2026-09-25 15:00 UTC | 2026-09-24 15:00 UTC |
| `breezy-exit-window-study.timer` | 2026-09-25 15:20 UTC | 2026-09-24 15:20 UTC (FAILED, see Finding D) |
| `breezy-family-tally@pm_us_crh_v2.timer` | 2026-09-25 17:20 UTC | 2026-09-24 17:20 UTC |
| `breezy-family-tally@pm_us_crh_v4.timer` | 2026-09-25 17:20 UTC | never fired yet |
| `breezy-portfolio-roi.timer` | 2026-09-25 17:40 UTC | 2026-09-24 17:40 UTC |

## Finding B — reconciled table (step 6, closed)

The reconciled table over the last successful nightly run
(`2026-09-20_nightly`, N=5, same five `trial_id`s as Rev 2 Appendix A.3),
with the per-row `delta_i` classification (`classify_threatened_delta`,
commit `6bd52ef`) added as the required closing check before this table may
be trusted (§6 B2):

| position | leg | fill | first THREATENED | last executable exit | `delta_i` classification | hold pnl | R-BEST |
|---|---|---|---|---|---|---|---|
| MDW [80,81] 09-15 | YES | 0.11 | — | 18:07Z | no signal (THREATENED never confirmed) | −0.12 | exit @0.11 → −0.02 |
| MDW [82,83] 09-15 | YES | 0.24 | — | none after fill (catalog) | no signal | −0.25 | exited@0.41 → +0.15 |
| MIA 09-13 | YES | 0.70 | — | 15:35Z | no signal | +0.30 | exit @0.99 → +0.29 |
| MIA [92,93] 09-15 | NO | 0.09 | 18:22Z | 19:36Z | **THREATENED_BEFORE_EXIT_SIDE_EMPTIED** (`delta_i` = 18:22 − 19:36 = −74.12 min) | −0.09 | exit @0.06 → −0.03 |
| SFO [71,72] 09-15 | YES | 0.44 | — | 20:12Z | no signal | −0.45 | exit @0.02 → −0.43 |

**Every row's classification is individually explained** (AC#4's
requirement): four rows never confirmed THREATENED at all ("no signal" is
not a delta of zero and is not counted either way); the one row that did
(MIA NO leg) classifies `BEFORE_EXIT_SIDE_EMPTIED` — this is the single
documented R-THREAT firing, already characterised in Rev 2 Appendix A.3 as
"THREATENED before the exit side emptied 1/5, correct in sign (+0.02 vs
hold)" (its R-THREAT outcome: `exited@0.02 pnl=-0.0700`, still better than
the `-0.09` hold loss). **The "negative-median anomaly" was never an
anomaly**: `−74.12` is exactly this one row's `delta_i` in minutes (the
only row with both timestamps defined, so the "median" of a one-element
sample is that element), and a negative value is the CORRECT, gate-relevant
sign under the polarity this item verifies from the evidence (see the
commit message on `classify_threatened_delta` for the full derivation and
the note that the plan's own prose stated the opposite polarity).

**Gate reading, per row (Rev 2's unchanged gates, restated here since Rev 3
itself is out of this item's scope):** R-THREAT: 1 of 5 qualifying rows
(gate ≥ 3) — **does not arm**. R-DEAD: 0 of 5 rows ever confirm DEAD before
the exit side empties (`dead_before_exit_side_emptied=0/5`, unchanged from
Rev 2) — **does not arm**. Both gate readings are unchanged from Rev 2's
own conclusion; reconciling the drift (finding B) did not change which
gates pass.

**Provenance of this table:** `2026-09-20_nightly/exit_window_study.{json,md}`
(the last artefact the timer wrote before the 09-22–09-24 crashes in
Finding D); `depth_source=catalog` for all 5 rows confirms candidate (i)
(the ING-1 staged→catalog substitution) as the cause of the Σ figures'
drift from Rev 2 Appendix A.3, as stated above under Finding B.

## Summary of what this pass changes vs. what it leaves alone

- **Changed:** C1 (family binding, wrapper enumeration), C2/C3 (stated
  universe + independent ledger count) — commit `f95f63d`.
- **Not changed by this item, recorded honestly:** the exit-window-study
  crash (Finding D above) is a pre-existing condition, not newly introduced
  or newly fixed by this item; the `EXIT_CORPUS_FROZEN` alert being added
  in steps 3–4 detects a job that stops producing NEW positions, and
  (as a byproduct, since the ladder only advances on a run that reaches the
  summary-writing step) will stay silent across a run that crashes before
  writing a summary at all — a residual limitation named honestly per the
  plan's own §9 "Autonomous operation" discipline, not solved here.
- `exit_gate.py`: unchanged. No order placed, no family registered, no
  gate opened, no positive control run, no live-trading enablement touched.
