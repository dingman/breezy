# RULING_MAKER-S2_second_look_licence_2026-10-16
Status: DRAFT. Licence under RULING_MAKER-S2_second_look_SEARCH_declaration_2026-10-16 (sha bc15908052ff223abc889859133edb4645d4a6642b5fae559c0101251df9a05b).
## 1. Licensed reads (exhaustive)
1. One verdict scoring pass over block days: NBP 13Z/19Z D−1 and 01Z D; tape incl. Depth10 and DepthTruncation; the pinned truth CSV and the pinned cross-check.
2. --bench 4 and 8 on block days.
3. Verify-first on 2026-06-30 at CODE_SHA.
4. WP0 direction check and SFO positive control on block days.
5. --tail-csv ~/.local/share/breezy/derived/maker_stage0/tail/tail-20261016T062622Z/tail_reliability.csv (sha 6749a92133e54a89bd3c21c1ffb079ea335704eb9ccbba30978d5bd16f2be35d; fallback: the committed sidecar copy, same sha) — annotation only; no new NBP read.
--tail-only is not licensed (refused for a v2 block).
## 2. Frozen set
```FROZEN_DATE_SET_V2
stations: LAX MDW MIA SFO
block_first_day: 2026-10-14
trigger_day: <FILL>
trigger_rows_path: <FILL repo-relative>
trigger_rows_sha256: <FILL>
census_days_path: <FILL>
census_days_sha256: <FILL>
truth_csv_path: <FILL>
truth_csv_sha256: <FILL>
cross_check_path: <FILL>
cross_check_sha256: <FILL>
last_final_day: <FILL ≥ trigger_day>
dates:
<FILL: block_first_day .. min(trigger_day, last_final_day, 2026-11-15)>
```
## 3. Re-run rule
The text of amendment §3 (:71-77) is copied here verbatim; the addendum name is RULING_MAKER-S2_second_look_addendum_2026-10-16.md. Residual post-claim voids (all non-result): S-2 direction, S-7 Δ bound, S-5 RSS abort, RTMAX/OOM/host kill, unexpected exceptions.
## 4. Provenance
The §0 precondition quotes of Doc A, the read-ledger sha256, trigger_close.json sha256, the sealed-stdout paths. CODE_SHA is recorded in the run manifest and the closing ledger line, not here.
