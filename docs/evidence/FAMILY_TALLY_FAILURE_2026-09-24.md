# Family tally failure — AUD-05 evidence (2026-09-24)

Read-only. No unit was started or stopped. Authority:
`docs/evidence/RULING_live_family_tally_scope_2026-09-21.md` and
`docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` (sending
halt only; the tally and the KILL clock keep running).

## D-B cause

**Cause (i) is operative. Cause (ii) is not a form mismatch.**

`count_filled_takes` kept only 2-part latch keys (`station/climate_day`).
The live exec store (`exec_polymarket_us.sqlite`, opened `mode=ro`) has 8
`continuous_rung_hold/trial/` keys: 7 are 3-part
(`station/climate_day/instrument_id`) and 1 is 2-part (`MIA/2026-09-13`).
Two rung fills on `MDW/2026-09-15` are two 3-part keys. Every fill's
`instrument_id` equals the latch's `instrument_id`, including the composite
`^no` form (`tc-temp-miahigh-2026-09-15-gte92lt93f^no.POLYMARKET_US` on
both sides). The NO fill was uncounted because its key is 3-part, not
because the id forms differ.

The 2026-09-20 `filled_takes=1 < len(rows)=4` failure is that one 2-part
key against the four 2026-09-15 scored rows, all of which are 3-part.

## (h) `pm_us_crh_cont` store pre-check

`read_scored_trials` on `~/.local/share/breezy/derived/scored_trials/pm_us_crh_cont`
(the directory is eligible: no `mechanism_test_only` marker). 7 rows.
Out of bounds versus cont's own `d0_climate_day=2026-09-12` /
`terminal_climate_day=2026-09-19` (all three are on or after v4's
`d0_climate_day=2026-09-20`):

| climate_day | trial_id |
|---|---|
| 2026-09-21 | `continuous_rung_hold/trial/MIA/2026-09-21/tc-temp-miahigh-2026-09-21-gte88lt89f^no.POLYMARKET_US` |
| 2026-09-21 | `continuous_rung_hold/trial/SFO/2026-09-21/tc-temp-sfohigh-2026-09-21-gte66lt67f.POLYMARKET_US` |
| 2026-09-22 | `continuous_rung_hold/trial/MDW/2026-09-22/tc-temp-mdwhigh-2026-09-22-gte62lt63f^no.POLYMARKET_US` |

The same three rows are also in `pm_us_crh_v4` (n=3). Nothing was deleted
or rewritten. A terminal cont tally is expected to raise
`FamilyBarrierRefusal` on the whole batch. That refusal, with the rows
above, is the terminal evidentiary state. The timer disable is not
contingent on a clean run.

## (i) Champion vs the old counter literal

`deploy/systemd/breezy-trade-supervisor.service` sets
`BREEZY_SENDING_FAMILY_ID=pm_us_crh_v4`. Before this change
`score-live-trials-run.sh` pinned
`FAMILY_MANIFEST` to `deploy/families/pm_us_crh_v2.json`. The wrapper now
resolves the manifest from that unit variable.

## Deploy steps (coordinator, after merge — not run here)

```bash
systemctl --user daemon-reload
systemctl --user enable --now breezy-family-tally@pm_us_crh_v4.timer
# one terminal tally for the retired family; expect FamilyBarrierRefusal
systemctl --user start breezy-family-tally@pm_us_crh_cont.service || true
systemctl --user disable --now breezy-family-tally@pm_us_crh_cont.timer
systemctl --user disable --now breezy-pm-crh-cont-tally.timer || true
systemctl --user disable --now breezy-pm-crh-v2-tally.timer || true
rm -f ~/.config/systemd/user/breezy-pm-crh-cont-tally.timer \
      ~/.config/systemd/user/breezy-pm-crh-cont-tally.service \
      ~/.config/systemd/user/breezy-pm-crh-v2-tally.timer \
      ~/.config/systemd/user/breezy-pm-crh-v2-tally.service
systemctl --user daemon-reload
systemctl --user is-enabled breezy-family-tally@pm_us_crh_v4.timer
systemctl --user is-enabled breezy-family-tally@pm_us_crh_cont.timer
systemctl --user list-timers --all | grep breezy-pm-crh || true
```

No manifest under `deploy/families/` was edited. `pm_us_crh_cont` stays
`REGISTERED`. The v4 sending halt is untouched.

## Fix-2 (2026-09-24): SPLIT THE ARTEFACT — deviation from §6 D-H

The single champion-scoped counter above made `breezy-live-tally` (ENABLED
v1 daily stop; R-5 OPEN) refuse every day: fetch_start 2026-09-20 vs its
v1 literal 2026-09-05. §6 D-H specified ONE resolved-champion counter at
the pre-existing path — **deviation**: `structural_dead_stop.py` now runs
TWICE per 14:15 run: the pre-existing path (`pm_us_crh_v2.json`, fetch_start
2026-09-05, byte-identical to base 161cba8) for `live-tally-run.sh` and this
wrapper's scorer loop; a NEW `covered_listed_station_days_champion_<date>
.json` (champion-resolved, sha-guarded) for `family-tally-v2-run.sh`'s v4
instance and the KILL clock. Cost: ~0.65s/~300MB RSS per invocation
(empty catalog) — the extra daily run is cheap next to a guaranteed page.
No manifest/ruling/enablement state changed.
