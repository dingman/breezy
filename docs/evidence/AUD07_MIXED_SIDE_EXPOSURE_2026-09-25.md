# AUD-07 amendment Stage M0 — mixed-side exposure census (read-only, 2026-09-25)

**Scope (plan §4 M0):** every family in `deploy/families/` whose `status ==
"REGISTERED"` and whose tally has ever run through `family_tally_v2.py` (the
`breezy-family-tally@` wrapper), never assumed -- enumerated below.
**Method:** artefact files read with `/usr/bin/ls`/`/usr/bin/grep`
(positive control run first against each file: a `grep -c` for a
byte guaranteed present, confirming the tool is not blind under the
dot-directory), never Glob/Grep (tool-blindness risk noted in plan §3).
Mixed-side counts computed read-only via `read_scored_trials` +
`stratum_row_from_scored_trial` (no writer invoked). Halt state read via a
read-only (`mode=ro`) sqlite connection. **No live state written.**

## Family enumeration (`deploy/families/*.json`)

| file | `family_id` | `status` | `composition_kind` | `trial_id_prefix` |
|---|---|---|---|---|
| `gs_boundary_pm_us_crh_v2.json` | *(none -- boundary artefact, not a family manifest)* | -- | -- | -- |
| `kalshi_crh_v1.json` | kalshi_crh_v1 | DRAFT_NOT_REGISTERED | current_rung_hold | `kalshi:current_rung_hold/trial/` |
| `pm_us_crh_cont.json` | pm_us_crh_cont | **REGISTERED** | continuous_rung_hold | `continuous_rung_hold/trial/` |
| `pm_us_crh_exit_v4.json` | pm_us_crh_exit_v4 | DRAFT_NOT_REGISTERED | current_rung_hold | `current_rung_hold_exit_v4/trial/` |
| `pm_us_crh_v2.json` | pm_us_crh_v2 | **REGISTERED** | current_rung_hold | `current_rung_hold/trial/` |
| `pm_us_crh_v4.json` | pm_us_crh_v4 | **REGISTERED** | continuous_rung_hold | `continuous_rung_hold/trial/` |

Three REGISTERED families are in scope: **pm_us_crh_v2**, **pm_us_crh_cont**,
**pm_us_crh_v4**. `pm_us_crh_cont` and `pm_us_crh_v4` share the identical
`continuous_rung_hold/trial/` prefix -- `pm_us_crh_cont` carries a
`terminal_climate_day` (`2026-09-19`, see below) and is the closed
predecessor; `pm_us_crh_v4` is its open successor. `kalshi_crh_v1` and
`pm_us_crh_exit_v4` are DRAFT_NOT_REGISTERED -- excluded by the plan's own
scoping rule ("every REGISTERED family").

## Positive control

```
$ /usr/bin/grep -c "family_id" deploy/families/pm_us_crh_v2.json
1
$ /usr/bin/ls /home/jon/.local/share/breezy/derived/ | wc -l
159
```
Both tools return non-empty, non-zero results against a directory
containing dot-free filenames -- not blind here.

## Per-family: latest tally artefact (verbatim lines)

### pm_us_crh_v2

Latest rendered artefact: `family_tally_v2_pm_us_crh_v2_2026-09-23.md`
(daily cadence is current; `2026-09-24`/`2026-09-25` skipped only for a
missing score-live-trials marker, not a tally failure -- see wrapper log
below).

```
row count: 0 (excluded: 0)
**CONTINUE** -- fewer than one completed look so far (n < look_step)
structural-dead stop (v1 section 5:105-106): 10 covered-listed station-day(s), 1 filled Take(s), evaluable and not fired.
| look | n | t | S | I | b_eff | b_fut | verdict |
|---:|---:|---:|---:|---:|---:|---:|---|
```
(look table has a header row only -- **zero looks fired**.) `n draws = 0`.

Wrapper log tail (`family_tally_v2.log`):
```
2026-09-23T17:20:05Z family tally v2 (pm_us_crh_v2) ok
2026-09-24T17:20:00Z FAMILY TALLY V2 (pm_us_crh_v2) SKIPPED -- no score-live-trials success marker for 2026-09-24
```

### pm_us_crh_cont

Latest **successfully rendered** artefact:
`family_tally_v2_pm_us_crh_cont_2026-09-16.md` (every run since has
crashed -- see below; the report has not refreshed past 2026-09-16).

```
row count: 3 (excluded: 0)
**CONTINUE** -- fewer than one completed look so far (n < look_step)
| look | n | t | S | I | b_eff | b_fut | verdict |
|---:|---:|---:|---:|---:|---:|---:|---|
```
(look table header only -- **zero looks fired** as of the last artefact
that actually rendered.) `n draws (rendered) = 3` rows / distinct
station-days at that point.

**Finding (uncovered by the plan's §3 framing): the CLI has been RUN FAILED
every day since 2026-09-19**, so no fresher artefact exists at all. Two
distinct causes, both verbatim from `family_tally_v2.log`:

1. **2026-09-19 through 2026-09-22** -- the descriptive Wilson-stratum
   helper (never the registered LD-OBF sequential statistic) is side-blind
   and raises on any NO-leg row once one entered the store:
   ```
   File "/home/jon/breezy/scripts/analysis/family_tally_v2.py", line 648, in build_family_tally_v2
       pooled = build_stratum_v2("pooled", pooled_rows) if pooled_rows else None
   File "/home/jon/breezy/src/breezy/settlement/current_rung_hold_v2.py", line 419, in build_stratum_v2
       raise ValueError(
   ValueError: build_stratum_v2() is side-blind and refuses any row with side != 'yes' until it is made side-aware (fix-first review of 87278dd, item 3)
   ```
2. **2026-09-23** (current) -- `assert_family_only`'s terminal-climate-day
   barrier now refuses a later-dated row belonging to the successor family
   (expected/correct refusal semantics, but uncaught -- it aborts the whole
   CLI run rather than excluding the one row and rendering):
   ```
   File "/home/jon/breezy/src/breezy/settlement/family_barrier.py", line 87, in assert_family_only
       raise FamilyBarrierRefusal(
   breezy.settlement.family_barrier.FamilyBarrierRefusal: 'continuous_rung_hold/trial/MIA/2026-09-21/tc-temp-miahigh-2026-09-21-gte88lt89f^no.POLYMARKET_US': climate_day '2026-09-21' follows the family's terminal climate day '2026-09-19'; this family is closed and the row belongs to its successor
   ```

Both are pre-existing defects in `family_tally_v2.py`'s reporting/barrier
layers, **outside Stage M0/M1a/M1b scope** (M1b's extraction touches only
`run_sequential_looks`, never `build_stratum_v2` or `assert_family_only`).
Recorded here because they are load-bearing for "is any verdict at risk":
since **no artefact has rendered for `pm_us_crh_cont` since 2026-09-16**,
the registered sequential test for this family has not been evaluated at
all in the last 9 days -- consistent with, but stronger than, the plan's
"no verdict can have fired" (the tally cannot currently even RUN to find
out). This does not change any LD-OBF verdict (see halt state below: v4,
the open successor, is HALTED from sending; v2 is unaffected; cont's own
last live verdict, 2026-09-16, was CONTINUE with zero looks).

### pm_us_crh_v4

**No rendered artefact exists at all.** `find` across
`~/.local/share/breezy/derived` for `*crh_v4*` returns only the raw scored-
trial store directory, never a `family_tally_v2_pm_us_crh_v4_*.md` file, and
`grep -c pm_us_crh_v4 family_tally_v2.log` returns **0** -- the wrapper has
never once invoked the CLI for this family id. `systemctl --user list-timers`
confirms: `breezy-family-tally@pm_us_crh_v4.timer` next-fires tomorrow
17:20 UTC with **no last-trigger time** (a freshly-installed timer that has
not yet ticked). This is a coverage gap, not a computed CONTINUE: report as
**MISSING**, not as "zero looks fired by measurement" (L-35 discipline --
distinguish a counter that cannot yet have moved from one that is dead).

## Mixed-side station-day count (`stratum_row_from_scored_trial`, read-only)

Computed directly off each family's own `read_scored_trials(store_dir)`
output (current on-disk store, not the stale rendered artefact), grouped by
`(station, climate_day)`, sides derived exactly as
`stratum_row_from_scored_trial` derives them (never re-implemented):

| family | n_scored_rows (current store) | ever held a NO leg | distinct station-days | mixed-side station-days |
|---|---:|---|---:|---:|
| pm_us_crh_v2 | 0 | No | 0 | 0 |
| pm_us_crh_cont | 7 | **Yes** | 6 | **0** |
| pm_us_crh_v4 | 3 | **Yes** | 3 | **0** |

No mixed-side (YES+NO same station-day) draw exists in either continuous-
family store today. Every NO-leg row observed sits on a station-day with no
sibling YES fill.

## Halt state (read-only sqlite, `mode=ro`)

```python
sqlite3.connect("file:.../exec_polymarket_us.sqlite?mode=ro", uri=True)
```

Key `continuous_rung_hold/halt` (shared by the `continuous_rung_hold`
composition kind, i.e. both `pm_us_crh_cont` and `pm_us_crh_v4`):

```json
{"detail": "Ruling A1 2026-09-21: pm_us_crh_v4 may not SEND orders; node, capture and KILL clock keep running", "evidenceSha256": "754e5cbef13e2896854dc99391e6c64923fe7813ccd03909b7a8fef898b87353", "reason": "policy_halt", "tsNs": 1790268150964821245, "v": 1}
```

No `current_rung_hold/halt` key exists in the same store -- `pm_us_crh_v2`
is not halted.

## Summary against plan §3

- **No LD-OBF verdict has fired for any in-scope family.** `pm_us_crh_v2`
  and `pm_us_crh_cont` both last rendered `CONTINUE` with an empty look
  table (zero looks); `pm_us_crh_v4` has never rendered at all.
- **`pm_us_crh_v4` is HALTED** from sending (Ruling A1, 2026-09-21,
  confirmed verbatim above); the node, capture and KILL clock continue.
- **`pm_us_crh_cont`'s tally pipeline is currently broken** (RUN FAILED
  daily since 2026-09-19, two distinct causes, both outside this stage's
  scope) -- its last successful artefact is 9 days stale. This does not
  put a verdict at risk (the last live verdict was CONTINUE, zero looks),
  but the coordinator should track it as a separate defect (candidate:
  side-aware `build_stratum_v2`, and a caught/reported
  `FamilyBarrierRefusal` in `main()`).
- **No mixed-side station-day exists in any in-scope family's live store
  today** -- the M2 gate (branch V/I) has no live population to validate
  against yet; M1's characterisation tests below use synthetic fixtures
  per the plan, not live data.
