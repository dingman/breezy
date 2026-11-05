# MAKER-S2 S-5 perf round: replay-outcome equivalence A/B (2026-10-14)

Result: IDENTICAL. Baseline d563e702 vs optimised 3c45d294 (screen changes in 403196e3, 9e2c626d, e09de765 do not touch the simulate path). Nothing was changed after the hashes matched.

## Day with bids: MDW 2026-10-09 and MDW 2026-10-11 (both run; 5 variants each)
Both days are bid-bearing but NEITHER has a base-pass fill (no day with fills was available among the two): per variant 4 attempts, 4 placed episodes, 0 refused, 0 base fills. The fill path is covered by the synthetic differential tests and the golden fixture hashes (2 fills in `test_maker_stage0_perf_equivalence`), not by this real-data run.

sha256 of the canonical JSON lines of `Episode.to_dict()` (the `episodes.jsonl` row format) and of `StationDaySummary.to_dict()` (the `station_days.csv` row source), identical on both commits for every variant:
| day | variant | episodes sha256 (12) | summary sha256 (12) |
|---|---|---|---|
| 10-09 | primary, overlay, plus60, delta0 | dc822674955f | e6ee2e232a69 |
| 10-09 | poll_lag | e5545215f914 | e6ee2e232a69 |
| 10-11 | primary, overlay, plus60, delta0 | 56d7e70dbf8c | a4045eac314b |
| 10-11 | poll_lag | a162607aa306 | a4045eac314b |
Full 64-hex values are in the run logs of the harness; all 10 (day x variant) pairs matched baseline vs new. (poll_lag differs from the others in episode timing only, identically on both commits.)

## SFO 2026-10-04 (no bids: 0 attempts in all 5 variants)
All 3,994,810 selector decisions (desired, drop_reason, forecast_valid, dropped) fold to the same rolling hash on both commits: 1498446622019923012 (PYTHONHASHSEED=0); the 5-variant outcome digest is 98545a51ba6bac10d030caf2de2e0f8970e6bdc3a19dc2e3f3777862716b4365 on both. Tracker abstentions and wanted-without-book sets were empty on both.

## Method
- Harness (scratch, not committed): calls the real `maker_stage0_replay --bench 4 --stations MDW --days 2026-10-09,2026-10-11` entrypoint with `CatalogSession.read`/`plan` outputs pickled so both commits see byte-identical slices; wraps `simulate_station_day` to hash each result. Baseline tree: `git archive d563e702` into a scratch git repo plus the untracked `deploy/families` manifest.
- Each run under `systemd-run --user --pipe --wait --collect -p MemoryMax=4G -p RuntimeMaxSec=3000 -p LimitNOFILE=524288 --setenv=PYTHONHASHSEED=0` (no studies lock; outside 02:00-02:10Z). RuntimeMaxSec was raised from 2400 because the first (plan) run includes a ~20 min `session.plan()` scan.
- The optimised run also replays the heaviest day a second time (the new repeat row, `repeat_of_first`); the repeat row's five hashes equal the first replay's and are excluded from the comparison above.
- Not verified: base-pass fills on real data (none occur on these days); stress-pass fills were not counted separately (covered by the summary hash).
