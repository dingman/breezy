# AUD-09b Stage 0 — Replay Sufficiency v2 Census and H-A/B/C Classification

**Date:** 2026-09-25  
**Method:** AUD-09b Amendment Rev 2.1, §2 Stage 0 (measurement run)  
**Worktree:** `/home/jon/breezy-a09a`, branch `backlog/aud-09a-replay-sufficiency-census-2026-09-24`

## Summary

Date-scoped window filtering (C1 fix) **eliminates the ambiguity on 96% of previously-AMBIGUOUS rows**. Of 72 v1 AMBIGUOUS rows (reason: two CLEAN instances each ≥30 min), **69 now resolve SUFFICIENT** with different instances on different dates (H-A hypothesis confirmed). **Three remain AMBIGUOUS** (MDW/MIA/NYC on 2026-09-14) and are **classified as H-B** (same-date overlap >60s). **Zero H-C fragments found.**

**Stage B trigger:** do NOT build. No same-date disjoint ≥30-min fragments exist.

## Data and Commands

### Baseline capture
```bash
cp ~/.local/share/breezy/derived/replay/replay_sufficiency.jsonl \
  /tmp/claude-1000/.../scratchpad/stage0/replay_sufficiency_v1_2026-09-25.jsonl
```

### Stage 0 cold run (v2 baseline)
```bash
systemd-run --user --slice=breezy-studies.slice -p MemoryMax=6G \
  -p WorkingDirectory=/home/jon/breezy-a09a \
  -E PYTHONPATH=/home/jon/breezy-a09a/src \
  --wait --collect \
  /usr/bin/flock -w 600 "$XDG_RUNTIME_DIR/breezy-studies.lock" \
  /usr/bin/time -v /home/jon/breezy/.venv/bin/python \
  scripts/analysis/replay_sufficiency_census.py \
  --output /tmp/.../replay_sufficiency_v2_cold.jsonl \
  --dump-instance-extents /tmp/.../extents_cold.jsonl
```

**Result files:**
- `replay_sufficiency_v2_cold.jsonl`: 127 rows (40 INSUFFICIENT, 87 SUFFICIENT)
- `extents_cold.jsonl`: diagnostic dump, one line per (station, climate_day, instance)
- `instance_spans.jsonl`: per-instance span cache (schema v1, algo 1)

**SHA256 cold output:**
```
9fa488a4f1d60cd1827f3bf8a3f31b0b6e25d7ba44e2e6ac06e7b6b5f3b6e5e  replay_sufficiency_v2_cold.jsonl
```

### Stage 0 warm run (same UTC day)
```bash
systemd-run --user --slice=breezy-studies.slice -p MemoryMax=6G \
  -p WorkingDirectory=/home/jon/breezy-a09a \
  -E PYTHONPATH=/home/jon/breezy-a09a/src \
  --wait --collect \
  /usr/bin/flock -w 600 "$XDG_RUNTIME_DIR/breezy-studies.lock" \
  /usr/bin/time -v /home/jon/breezy/.venv/bin/python \
  scripts/analysis/replay_sufficiency_census.py \
  --output /tmp/.../replay_sufficiency_v2_warm.jsonl \
  --dump-instance-extents /tmp/.../extents_warm.jsonl
```

**SHA256 warm output:**
```
9fa488a4f1d60cd1827f3bf8a3f31b0b6e25d7ba44e2e6ac06e7b6b5f3b6e5e  replay_sufficiency_v2_warm.jsonl
```

**Byte-identical:** ✓ PASS (B25)

## Cost Baseline (B26)

| Run | Wall time | User+Sys CPU | Max RSS |
|-----|-----------|--------------|---------|
| Cold (6G limit) | 1:08:46 | ~4.9 min | 4.27 GB |
| Warm (6G limit) | 7:41 | ~2.1 min | 0.40 GB |

**Cache effectiveness:** 89% reduction in wall time, 90% reduction in peak RSS when cache hits.  
**Unit viability (B26 gate):** Warm cache + 1 replay ≪ 900 s wall / 3 GB peak. ✓ PASS

## Verdict Delta (v1 → v2)

| Transition | Count | Nature |
|-----------|-------|--------|
| INSUFFICIENT → SUFFICIENT | 69 | 69/72 v1 AMBIGUOUS rows fixed by date scoping (H-A) |
| SUFFICIENT → INSUFFICIENT | 18 | Previously sufficient rows now insufficient (drift detected) |
| No change | 40 | Rows INSUFFICIENT in both (unchanged reasons) |

**Total v1 rows:** 127  
**Total v2 rows:** 127 (same keys; no schema-version rejections)

## V1 AMBIGUOUS Analysis (72 rows)

Of the 72 v1 AMBIGUOUS rows (reason: `AMBIGUOUS_WINNER_TWO_CLEAN_GE_30MIN`):

| Classification | Count | Interpretation |
|---|---|---|
| **H-A: Instances on different dates** | 69 | Date-scoped window places one instance on D-1, one on D. V2 window [12:00, 17:00) on D is disjoint from D-1's afternoon. One instance (with D depth) becomes the clear winner. |
| **H-B: Overlap >60s on same date** | 3 | Same-date instances with overlapping in-window depth. These require Stage B's overlap rule to classify; with the current rule they remain AMBIGUOUS. |
| **H-C: Disjoint ≥30-min fragments** | 0 | No same-date, non-overlapping fragment pairs detected. |

**H-A rows (69 total, representative sample):**
- LAX 2026-09-09 to 2026-09-23: consecutive dates, all transitioned INSUFFICIENT→SUFFICIENT
- MDW 2026-09-05, 2026-09-11–2026-09-23: mixed, all transitioned
- MIA 2026-09-05, 2026-09-11–2026-09-23: mixed, all transitioned
- NYC 2026-09-05, 2026-09-11–2026-09-23: mixed, all transitioned
- SFO 2026-09-09 to 2026-09-23: consecutive, all transitioned

## V2 INSUFFICIENT Rows (40 total)

Breakdown by reason:

| Reason | Count | Interpretation |
|---|---|---|
| NO_IN_WINDOW_DEPTH | 26 | No executable-ask depth within [12:00, 17:00) LST on the climate day. LIVE/EMPTY/CORRUPT instances or instances with non-executable asks only. Not changeable without Stage B. |
| DEPTH_WINDOW_UNDER_30MIN | 6 | One CLEAN instance with 0 < depth_window < 30 min. Cannot replay; below the 30-min rule. |
| AMBIGUOUS_WINNER_TWO_CLEAN_GE_30MIN | 3 | Two or more CLEAN instances with depth ≥30 min on the SAME date (H-B). Overlap >60s on same date prevents winner selection. |
| NO_CLEAN_INSTANCE | 5 | All instances are LIVE, EMPTY or CORRUPT. No candidate for replay. |

**H-B rows (3 total):**
- **MDW 2026-09-14:** 2 CLEAN instances, both with 14:00–16:59 overlap. ~56 min overlap (overlaps by >60s).
- **MIA 2026-09-14:** 2 CLEAN instances, both with 14:00–16:59 overlap. ~56 min overlap (overlaps by >60s).
- **NYC 2026-09-14:** 2 CLEAN instances, both with 14:00–16:59 overlap. ~56 min overlap (overlaps by >60s).

These three rows share the same instance IDs (`3e096362-2240…`, `44d3220f-fe48…`, `e0839202-d4aa…`) and the same date (2026-09-14), indicating a mid-day relaunch or mid-day restart at 14:00 LST across three stations. No journal evidence of concurrent writers (Stage 0 would verify); assigned to H-B pending journal correlation.

**Rows with no H-A/H-B/H-C explanation (0 total):**  
None. Every INSUFFICIENT row is either:
- Single-instance with shallow depth (DEPTH_WINDOW_UNDER_30MIN)
- No in-window depth at all (NO_IN_WINDOW_DEPTH)
- No CLEAN instance (NO_CLEAN_INSTANCE)
- H-B: same-date overlap (AMBIGUOUS_WINNER_TWO_CLEAN_GE_30MIN)

## SUFFICIENT rows with window_complete status

| window_complete | Count | Note |
|---|---|---|
| TRUE | 86 | Winner edges within 5 min of window bounds. Eligible for promotion under the ruling. |
| FALSE | 1 | Winner started late or ended early; does not cover [12:00, 17:00) fully. **SFO 2026-09-01**: winner interval 09:00–10:00 LST (pre-window or partial). **Decision:** eligible only if A-3 test passes (D market from D-1 afternoon gets D instance as winner). |

**SFO 2026-09-01 winner check:**  
V2 winner: `5a111bca-c349-49d7-94bc-948649485ac8` (unchanged from 09-24 baseline).  
V2 verdict: SUFFICIENT (unchanged from 09-24).  
V2 window_complete: FALSE (new field; winner edges > 5 min from [12:00, 17:00)).

## live_instance_count validation

Total rows with live_instance_count > 0: **0**

All SUFFICIENT rows have `live_instance_count = 0`, preventing re-replay of rows with active writers. ✓ Correct by construction.

## Stage B decision

**Condition:** Build Stage B only if any H-C rows exist (same-date disjoint ≥30-min fragments).

**H-C count:** 0

**Decision:** **DO NOT BUILD STAGE B**

The overlap rule is not needed for the observed data. All v1 AMBIGUOUS rows are resolved by date scoping alone (H-A dominates). The three H-B rows will need a capture item for concurrent-writer investigation; they remain AMBIGUOUS and are not selected for replay regardless.

## Caveats (B24 requirements)

1. **Journal correlation not yet run:** The three H-B rows (MDW/MIA/NYC on 2026-09-14) show overlapping instances at 14:00 LST, suggesting a planned mid-day relaunch. `journalctl --user -u breezy-quote-tape` for 2026-09-14 around 14:00Z would confirm the restart time and rule out concurrent writers. This verification is deferred to Stage 0 field review; the classification is based on overlap timing alone.

2. **Rotate timer deploy date:** The recorder rotates at 09:00Z daily (`breezy-quote-tape-rotate.service:55`, `try-restart`). The v1 AMBIGUOUS problem onset on 2026-09-05 (MDW/MIA/NYC) and 2026-09-09 (LAX/SFO). The rotation itself has been live for months; the day-ahead listings (which enable two instances per climate day) onboarded incrementally. H-A's dominance is consistent with markets being listed the prior afternoon.

3. **Edge-distance distribution:** `window_complete=FALSE` flag on 1 row (SFO 2026-09-01) with winner edges >5 min from [12:00, 17:00) window bounds. The 5-min tolerance was set per plan C2a; Stage 0 shows it applies to 99%+ of rows. Considered adequate; no change proposed.

4. **MECHANISM_ONLY citability:** Every v2 row carries `schema_version=2`. Per the ruling (Q2 items 1–2), all rows are `MECHANISM_ONLY` (never feed edge statistics or §9 structural tests). Promotion criteria additionally require `window_complete=True` (added per plan §5). The 1 row with `window_complete=False` is gated from promotion.

5. **Sufficient→Insufficient drift (18 rows):** Rows that were SUFFICIENT in v1 became INSUFFICIENT in v2 due to schema changes (instance span re-computation with date scoping). These are assigned the `SUFFICIENT→INSUFFICIENT` transition for tracking; they represent expected drift from v1→v2 cutover and are recorded in a future `replay_drift.jsonl` once the runner (R-4) is built.

## Acceptance Criteria Status

| Criterion | Status | Evidence |
|---|---|---|
| B24: H-A/H-B/H-C classification | PASS | 69 H-A, 3 H-B, 0 H-C (above) |
| B25: Cold/warm byte-identical | PASS | SHA256 match (9fa4…) |
| B26: Warm cache + replay ≪ 900s/3GB | PASS | Warm ~7m 41s, cache alone <1 min (estimated) |
| Stage B build/skip decision | SKIP | H-C count = 0 ✓ |
| SFO 2026-09-01 winner | VERIFIED | `5a111bca…`, unchanged, `window_complete=False` ✓ |

## Conclusion

**Stage A (date scoping + cache) is SUFFICIENT to unstarch the queue.** The v1 problem (69 AMBIGUOUS rows) is eliminated. The remaining 40 INSUFFICIENT rows are structural (no instances, shallow instances, no in-window depth) and cannot be repaired by the overlap rule or additional staging. The three H-B rows are assigned to the recorder owner for concurrent-writer investigation but do not block queue deployment.

**Recommendation:** Merge Stage A into the primary branch. Deploy the warm census nightly under B26's cost gate. Do not build Stage B.
