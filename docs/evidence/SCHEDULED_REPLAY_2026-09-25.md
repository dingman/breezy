# AUD-09b scheduled replay runner — first real run, 2026-09-25

**MECHANISM TEST — NO VERDICT.** Settlement joins the highest `revision_seq`
FINAL CLI record, unpublished at decision time. Every row in this evidence
carries `validity="MECHANISM_ONLY"`, written from the one named constant
`REPLAY_VALIDITY` (`src/breezy/analysis/replay_results.py`), until AUD-11
(look-ahead) and AUD-12 (costs) land.

**Second caveat (RULING `RULING_replay_evidence_citability_and_promotion_
criteria_2026-09-21.md` Q1 item 8).** The underlying parquet `trial_id` is
NOT family-scoped — a shape two REGISTERED families would share. This row
carries `family_id`/`manifest_sha256`; the (absent, here) parquet does not.

## Census re-run (schema v3)

The on-disk `replay_sufficiency.jsonl` was schema v1 (stale, predating the
merged Stage A/B date-scoping and overlap-winner work). Backed up to
`replay_sufficiency_v1_backup_2026-09-25.jsonl` (scratchpad) and
regenerated cold, under the studies lock:

```
systemd-run --user --slice=breezy-studies.slice -p MemoryMax=6G --wait --collect \
  -E PYTHONPATH=/home/jon/breezy-a09run/src \
  /usr/bin/flock -w 600 "$XDG_RUNTIME_DIR/breezy-studies.lock" \
  /home/jon/breezy/.venv/bin/python scripts/analysis/replay_sufficiency_census.py
```

Result: exit 0, peak memory 5.9–6.0G (near the 6G cold cap; this was a
**cold, first-ever v3 run** with no `instance_spans.jsonl` cache — B26's
warm-run budget (<3GB) applies to the nightly unit, not this one-time
migration). 127 rows: **90 SUFFICIENT / 37 INSUFFICIENT**. Among
`SUPPORTED_STATIONS = (LAX, MDW, MIA, SFO)`, `2026-09-01` is SUFFICIENT for
all four, `window_complete=True`, `coverage_kind="WHOLE"` — i.e.
`is_replayable_whole_day()` admits it for every supported station.

## Target selection

`select_target` picked **LAX 2026-09-01** — the oldest `is_replayable_
whole_day()` row, tie-broken by `SUPPORTED_STATIONS` order (`LAX` is index
0). This differs from the base plan's own "expected SFO" note, which
predates the amendment's Stage A/B rule; the plan itself says the census
must name the day "by rule, never by hand" — this is that rule's real
output.

## The one real run

```
systemd-run --user --slice=breezy-studies.slice -p MemoryMax=3G --wait --collect \
  -E PYTHONPATH=/home/jon/breezy-a09run/src \
  /usr/bin/flock -w 3600 "$XDG_RUNTIME_DIR/breezy-studies.lock" \
  /home/jon/breezy/.venv/bin/python scripts/analysis/replay_daily_runner.py \
    --quote-catalog ~/.local/share/breezy/catalog/quote_tape/polymarket_us \
    --weather-catalog-root ~/.local/share/breezy/catalog \
    --family-manifest /home/jon/breezy-a09run/deploy/families/pm_us_crh_v4.json \
    --output-root ~/.local/share/breezy/derived \
    --python /home/jon/breezy/.venv/bin/python
```

Run at 07:18–07:37 UTC 2026-09-25 (outside the protected window
`[16:35Z, 01:15Z)` and off every named busy tick). The first attempt waited
on the shared `breezy-studies.lock`, held by a legitimate sibling agent's
`aud07_live_rule_crossing_sim.py` Monte Carlo run (`breezy-a07m1c`
worktree) — correct multi-agent lock discipline, not a defect; the
attempt's own 600s `flock` wait timed out (exit 1, no row written), and a
second attempt with a 3600s wait acquired the lock once the sibling job
finished.

**Result:** `COMPLETED`, exit 0.

| Field | Value |
|---|---|
| station / climate_day | LAX / 2026-09-01 |
| tape_instance_id | `5a111bca-c349-49d7-94bc-948649485ac8` |
| strategy / lag_minutes | continuous_rung_hold / 30 |
| family_id | pm_us_crh_v4 |
| manifest_sha256 | `2bdfc28a2a69e48d6a23f9ed468c18a7729903af68c80cc75582ae2ddc998d94` — **equals `sha256sum deploy/families/pm_us_crh_v4.json`** (B20) |
| manifest_taker_fee_coefficient / engine_required_fee_coefficient | 0.0695 / 0.0695 |
| engine_params_source | FAMILY_MANIFEST (AUD-19b's `--family-manifest` flag landed after the base plan; see runner module docstring) |
| params_match | **True** — re-verifies B16's plan-era expectation of `False`; AUD-19b + the fee-theta fix make the engine's readback equal the manifest's registered value on today's tree |
| window_complete / coverage_kind | True / WHOLE |
| trials / fills | 0 / 0 — a real MECHANISM_ONLY zero-trade day, not a defect (`refusal_counts`: `outside_decision_window`=48363, `fee_schedule_mismatch`=1) |
| wall_s (engine only) | 61.4s |
| peak_rss_bytes (engine only, RUSAGE_CHILDREN delta) | 156,930,048 (~150 MB) |
| Service runtime / CPU / memory peak (whole unit, incl. lock wait) | 9m23s / 1m13s / 1.7G |

B9 (SP-4 Increment F) discharged via the `COMPLETED` shape.
B5/B26 baseline: peak RSS well under 3GB; wall clock for the replay itself
(excluding lock-wait) was ~62s, consistent with the plan's own n=1
~80s/~674MB prior estimate.

## Output artefacts (sha256)

| Path | sha256 |
|---|---|
| `~/.local/share/breezy/derived/replay/replay_results.jsonl` | `82b47e08f946d70fa30ee498d64b9582d8c0e8b455a061462f6681666c406eec` |
| `~/.local/share/breezy/derived/replay/replay_sufficiency.jsonl` (v3) | `5e48b1c7e96ff7eea8ee8adea8ad2b9e3b55e9ea3b4801f310ee6128a548007e` |
| `~/.local/share/breezy/derived/replay/replay_drift.jsonl` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (empty — no prior terminal rows to drift against) |
| `~/.local/share/breezy/derived/paper_replay/scored_trials/v3/LAX/2026-09-01/lag_30/family_params.json` | driver-written sidecar, matches the result row field-for-field |

No `scored_trials_*.parquet` was written — zero scored trials this day
(the driver only writes the parquet `if scored:`).

## Deferred (owned elsewhere, per the amendment)

- Stage B overlap-winner rule / `excluded_fragments`: **already merged**
  into `feat/data-capture-and-risk` ahead of this item (schema v3 in place);
  no Stage 0 H-A/H-B/H-C classification was re-run here — out of this
  item's scope (owned by the AUD-09a branch history).
- AUD-10 (`C-VALIDITY`/`C-PAIRED`, drift-file consumption), AUD-11
  (look-ahead), AUD-12 (costs), AUD-19a/b (already-landed `--family-
  manifest`), AUD-08b (H1 register) — by id, per plan §12/§10 item 10.
- The timer is installed but **NOT enabled** — the plan gates enablement
  on a non-BLOCKED row (satisfied here) **and** B26 (a warm census + one
  replay fitting <900s/<3GB — not separately re-measured this session
  because the census re-run above was necessarily cold). Enabling is left
  to a follow-on session/operator action once a warm-cache timing is
  measured.
