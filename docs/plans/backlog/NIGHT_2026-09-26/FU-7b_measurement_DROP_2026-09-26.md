## Scope

**In scope:** FU-7b (was FU-7 item 6, "ingest R4"). The concern: day-D instrument definitions stay in the live recorder instance's open `binary_option` feather file until the 09:00Z rotation plus the next ingest. A node boot before that ingest therefore cannot resolve day D from the ParquetDataCatalog. This plan measures that exposure, checks Nautilus for a native way to land part of a live stream, weighs the three options, and recommends one.

**Out of scope (named so nothing is dropped silently):**
- The ING-2 S1 review finding "live-instance defs type marked after one closed file blocks later defs files" (`ING-2_S1_review_r1.md:8`). It is a separate backlog item.
- The real day-D exposure that this measurement found: 16:50Z boots refused for zero instruments because ingest had failed (see M3). It belongs to ING-2 and L-49. It is reported here but not fixed here.
- Any change to the supervisor schedule, the permit, the operator caps, `allow_short`, or the NO-SEND firewall.
- Resolving instruments from a live venue pull at boot. That would be a new egress path and a redesign.

**Recommendation: (iii) DROP, with written reopen triggers. No source change.** Evidence is below.

### Measurements (read-only; every item was read in this session)
- **M1: no boot has ever happened in the exposure window.**
  - There are 53 node logs: `~/.local/share/breezy/logs/breezy-trade-*.log`, 09-04 → 09-26.
  - Boot times are either 16:50–20:15Z, or three hand relaunches on 09-12 at 02:04, 02:23 and 02:26Z.
  - Zero boots fall between 03:00Z and 16:40Z.
  - At 02:0xZ every station is still before local-standard midnight, so "today" was 09-11. Its definitions were already in the catalog, and none of the three logs contains "resolved 0".
- **M2: the supervisor structurally cannot spawn in the window.**
  - `next_due` returns a spawning phase only for LAUNCH or RELAUNCH_CHECK in [16:50, 17:00)Z, or MIDDAY_WATCH in [17:10Z, 01:00Z next day). Sources: `src/breezy/runtime/trade_supervisor_core.py:1005-1030`, `:987`, `:33-36`.
  - Supervisor restarts at 05:18, 07:10 and 08:37Z on 09-25 (`breezy-trade-supervisor.log:251-255`) spawned nothing. The next `launched` line is 16:50:34Z (`:259`).
  - This invariant is already pinned by `tests/unit/test_trade_supervisor.py:1847-1848` (03:00Z → Phase.NONE), `:1902-1903` and `:1958` (01:00Z next day ends MIDDAY_WATCH).
  - The only way into the window is a hand relaunch.
- **M3: every "resolved 0 instruments" failure is an ingest failure, not R4.**
  - Failed boots: 09-04 17:21Z, 09-07 16:50Z, 09-24 18:38Z, 09-25 16:50Z (log grep; each ends "refusing to start").
  - All four are at or after 16:50Z. By then the rotated instance is quiet and ingest-eligible, so R4 cannot be the cause.
  - L-49 (`docs/core/LESSONS.md:1546`) documents the 09-24 cause: an ingest memory ceiling kept the catalog stuck at 09-23.
  - Side finding for the backlog, not this item: on 09-25 the supervisor logged `relaunch_declined reason=exit cause is not transient` (`supervisor.log:260`). A zero-instrument refusal is never retried, so one ingest stall costs the whole day.
- **M4 (b): the 16:50Z boot gets day-D definitions only from the catalog.**
  - `build_continuous_rung_hold_strategies` reads `ParquetDataCatalog(catalog_root).instruments()` unfiltered (`src/breezy/strategy/current_rung_hold/composition.py:337-339`, `:643-646`). It raises `NoTradableInstrumentsError` when every station resolves 0.
  - `catalog_root` is `BREEZY_TRADE_CATALOG_ROOT=.../catalog/quote_tape/polymarket_us` (`~/.config/breezy/breezy-trade.env:7`).
  - `today_by_station` is the local-standard climate day per station (`src/breezy/app/trade.py:230-238`).
  - The venue provider's discovery cycle runs about 30 s after composition (AUD-02 r3, `…AUD-02_WP-D1_plan_r2_2026-09-26.md:170`), so it cannot rescue composition.
  - Inference: since 16:50Z boots succeed, day D must be listed on D-1 (about 09:45Z, `deploy/systemd/README.md:753-754`). It is then rotated out at 09:00Z on day D and ingested before 16:50Z.
- **M5: the actual exposure window is narrower than "03–09Z".**
  - It opens at each station's local-standard midnight: roughly 05Z for MIA, 06Z for MDW, 08Z for LAX and SFO. These are standard US offsets, not re-verified against the registry.
  - It closes at the first ingest after rotation that clears the 30-minute grace: rotation at 09:00Z (`breezy-quote-tape-rotate.timer:26`), ingest every 15 minutes (`breezy-quote-tape-ingest-frequent.timer:21`), grace in `quote_tape_ingest_cli.py:79-80`. That puts the close at about 09:45Z, not 09:15Z.
  - The live instance's definitions are per-identifier files that rotate in bursts. In instance `e3ede3ca`, the filename timestamps are about 09:00Z, then +18h (about 03:00Z). The recorder writes definitions only on discovery cycles, so Nautilus SCHEDULED_DATES rotation fires on the first write after 00:00Z (`nautilus_trader/persistence/writer.py:280-284`, `:331-345`). This explains the brief's "03Z". It is inferred from filenames only.
- **M6: a boot in the window would have no trading value.**
  - The hunt window opens at local hours 10–11, about 15–19Z (memory: hunt-window-opens-after-repricing).
  - STOP_PRIOR SIGTERMs any node at 16:40Z (`trade_supervisor_core.py:33`).
  - The failure is loud or visible: all stations at 0 exits 2 (`composition.py:645-646`); a partial boot logs a per-station WARNING "skipping %s; resolved 0 instruments" (`:685-691`).

## L-1 null-hypothesis verdict (installed Nautilus file:line)

**Verdict: Nautilus has no native way to land a partial or intact prefix of a live stream. The gap is real, but it only matters if a build were justified, and M1–M6 say it is not.**
- `ParquetDataCatalog._read_feather_file` does `pa.ipc.open_stream(f).read_all()` and returns `None` on `ArrowInvalid`/`OSError` (`.venv/lib/python3.13/site-packages/nautilus_trader/persistence/catalog/parquet.py:2788-2800`). One torn trailing message drops the whole file, and there is no prefix reader.
- `convert_stream_to_data` skips `None` tables and converts whole files only (`parquet.py:2604-2654`).
- `_convert_feather_table_to_parquet` raises on non-disjoint intervals (`parquet.py:2687-2693`). This is why Breezy's own definition dedupe path exists (`quote_tape_ingest_cli.py:61-68`, `:531-541`).
- `StreamingFeatherWriter` exposes only a flush interval (`writer.py:578-594`) and close-on-rotation (`writer.py:351-373`, `:385-400`). There is no reader-side API for a file still being written.
- Option (i) would therefore need a Breezy-side prefix reader, most likely a reuse of the salvage path (`quote_tape_salvage.py`, cited by `ING-2_S1_plan_r4_DELIVERED.md:12`). It would also relax the module's own "hard safety property" (`quote_tape_ingest_cli.py:70-97`).

## Acceptance Criteria

1. The DROP decision is recorded in PROGRESS.md FU-7b and the NIGHT_2026-09-26 FU-7 row 6, citing M1–M6 with file:line. The coordinator writes this through the doc path; this plan writes nothing.
2. Reopen triggers are written verbatim next to the DROP:
   - (T1) any `breezy-trade-*.log` whose first line falls in [05:00Z, 09:45Z) and contains "resolved 0 instruments" or "skipping … resolved 0 instruments";
   - (T2) any change to `STOP_PRIOR_UTC`, `LAUNCH_UTC` or `midday_watch_window_end` that lets a spawn happen in 01:00–16:40Z;
   - (T3) an operator ruling to trade before local hour 10, or a boot policy earlier than 16:50Z;
   - (T4) a change of `today_by_station` away from local-standard climate day.
3. The existing pins stay green and unedited: `test_trade_supervisor.py:1847-1848`, `:1902-1903`, `:1958`. The full gate `scripts/ci/run_tests_no_egress.sh` passes, with no diff under `src/`.
4. The side finding in M3 (zero-instrument refusal is non-transient and never relaunched) is filed as a new backlog item linked to ING-2 and L-49. It is not solved here.
5. The hand-relaunch runbook gains one line: "A hand relaunch between a station's local-standard midnight and ~09:45Z cannot resolve that station's day D; wait for the first post-09:00Z-rotation ingest (`breezy-quote-tape-ingest-frequent` ≥ 09:45Z) or boot after 16:50Z." Docs only.

## Edge Cases & NFRs

- **Partial-station boot (05–08Z):** the eastern stations resolve 0 while LAX and SFO resolve D-1. Composition skips them with a WARNING (`composition.py:685-691`) instead of refusing. This is degraded but visible, and T1 catches it.
- **Supervisor restarted inside the window:** Phase.NONE, no spawn (M2, pinned).
- **A node that stays alive across local midnight:** it keeps the day it was composed for and never re-resolves, so R4 does not apply. Its permit has already expired: 10h TTL from 16:50Z, and midday relaunches are capped at the first-boot expiry (`trade_supervisor.py` A-1).
- **The listing moves earlier or later than ~09:45Z D-1:** the 16:50Z boot is unaffected as long as the listing is before 09:00Z on day D. If a future listing lands after 09:00Z on day D, every 16:50Z boot would fail. M3's zero-instrument alerting would surface that immediately, and it would be a different, larger item.
- **Non-functional:** DROP adds no ingest CPU or memory, which is relevant given L-49, and keeps live-write avoidance intact.

## Design & Data Flow (with options considered + why chosen)

Flow today: the recorder writes definitions into the live instance, one file per identifier. The 09:00Z `try-restart` closes that instance. The */15 ingest converts it about 45 minutes later through the definition dedupe path (`quote_tape_ingest_cli.py:61-68`). The 16:50Z boot then reads `catalog.instruments()` and buckets by local climate day (`composition.py:342-403`).

| Option | What | Cost / risk | Benefit given M1–M6 | Verdict |
|---|---|---|---|---|
| (i) Land the intact prefix of the open definitions file | Prefix reader (salvage) feeding the `(instrument_id, ts_init)` dedupe, no marker | Relaxes the hard property at `:70-97`. The tail of a live buffer is byte-identical to a truncated file (`:73-76`). Needs a new reader, since Nautilus has none (L-1). Adds a second full read of the live instance every 15 minutes. HIGH review burden (architect, python and prediction-market). | Unlocks boots that have never happened and would not trade (M1, M6) | Rejected |
| (i′) Convert marker-closed older definitions files in the live instance | Change `_convert_one_definition_type` (`:1354-1356`) to per-file markers so closed files land while the newest stays skipped | Does not relax live-write avoidance, because the closed files end with an EOS marker. It does touch the marker semantics that the ING-2 S1 review flagged. Only covers the window after the ~03Z burst rotation (M5, inferred). MEDIUM. | Same zero benefit | Rejected now; **preferred design if T1–T4 fire** |
| (ii) Relaunch guard in code | Supervisor or `app/trade.py` refuses or warns when day-D definitions are absent | The supervisor already cannot spawn there (M2, pinned). A guard in `app/trade.py` would duplicate the existing loud refusal and WARNING (`composition.py:645-646`, `:685-691`). | None beyond what exists | Rejected (YAGNI). A docs-only runbook line (AC5) covers hand relaunches. |
| (iii) DROP with reopen triggers | Docs only | None | Honest: no measured exposure | **Chosen** |

## File-by-File Plan (abs path | new/modified | exact change)

| Path | New/modified | Change |
|---|---|---|
| /home/jon/breezy/docs/core/PROGRESS.md | modified (coordinator) | FU-7b → DROPPED, with the M1–M6 one-liners and reopen triggers T1–T4 (AC1, AC2) |
| /home/jon/breezy/docs/plans/backlog/NIGHT_2026-09-26/FU-7_plan_r1_2026-09-26.md | modified (coordinator) | Row 6 / `:70`: record DROP, name (i′) as the preferred design if reopened, and correct the window to "local-std midnight → ~09:45Z" |
| /home/jon/breezy/docs/core/PROGRESS.md | modified (coordinator) | New backlog item: "zero-instrument boot refusal is classified non-transient and never relaunched; one ingest stall = lost day" (evidence: `breezy-trade-supervisor.log:259-260`, the four log files) → linked to ING-2 and L-49 (AC4) |
| /home/jon/breezy/docs/plans/R8_OPERATOR_RUNBOOK.md (hand-relaunch section) | modified (coordinator) | Add the one runbook line from AC5 |
| src/, tests/, deploy/ | none | No change |

## Test Strategy

- There are no new tests, and nothing needs to be RED: there is no behaviour change. Adding a guard test would pin code that does not exist.
- The existing pins carry the safety of the DROP and must stay green unedited:
  - `tests/unit/test_trade_supervisor.py:1847-1848`: 03:00Z → Phase.NONE. If this goes red, T2 has fired.
  - `:1902-1903`: Phase.NONE at 03:00Z in the second state fixture.
  - `:1958`: 01:00Z next day closes MIDDAY_WATCH.
- Gate: `scripts/ci/run_tests_no_egress.sh`, with the exit code read (pytest-q memory) and `lint-imports`.
- Failure path: if a reviewer proves an in-window boot path exists (for example a timer I did not read), reopen with design (i′). Its RED tests would be:
  - `test_closed_definition_files_in_live_instance_land_while_newest_stays_open`: RED because `:1355-1356` skips the whole type.
  - `test_live_newest_definitions_file_is_never_read`: characterisation of the hard property.
  - `test_per_file_definition_marker_does_not_block_later_closed_files`: RED on the ING-2 S1 review finding.

## Deploy / Host Steps

None. There are no unit, timer or env changes, and the node does not need a restart.

## Risk Register

- **[LOW] An unmeasured boot path exists** (for example an agent's hand `systemd-run` in 05–09:45Z). Mitigation: T1 is a log grep; the failure is loud (exit 2) or WARNING-visible; the runbook line covers hand relaunches.
- **[LOW] The M5 rotation timing (~03Z burst) is inferred from filenames.** It affects only the reopened design (i′), not the DROP.
- **[MED, out of scope] The M3 non-transient classification** turns any ingest stall into a lost trading day. It is filed separately (AC4). This is where the real day-D exposure is.
- **[LOW] The listing moves to after 09:00Z on day D.** Every 16:50Z boot would then fail loudly. That would be a separate, larger item.

## LESSONS Compliance

- L-1 / L-47 / "validate Nautilus before planning": gap proven at `parquet.py:2788-2800`, `:2604-2654`, `writer.py:578-594`. No build proposed.
- L-49: M3 is attributed to ingest memory, not R4. No ingest CPU or memory is added.
- L-42 / L-33: the reopen tests would use a real `StreamingFeatherWriter`. Not triggered now.
- "Check what data a blocker actually used" / "counterfactuals need a mechanism": the brief's "03–09Z boot misses day D" is a prediction with zero observed instances; the measurement replaced it.
- "Plan must reach the goal state": the goal is "no trading day lost to missing definitions". That is advanced by AC4, which routes the measured cause, not by R4.
- Safety tests, operator caps, `allow_short`, NO-SEND and PREREG are untouched.
- Caveat: I read only the L-49 header and body. I did not grep all `## L-` headers.

## Confidence

**HIGH** for DROP. The node logs (53 files), the supervisor source and its pins, and the composition source were all read directly. None shows an in-window boot, and the supervisor cannot produce one.

Unknowns:
1. The exact per-station standard offsets were not re-read from the registry.
2. The ~03Z rotation burst is inferred from feather filename timestamps, not verified against the recorder config beyond `node_config.py:396`.
3. The listing on D-1 is inferred from 16:50Z boot success, not from a catalog `ts_init` query. I had no Python execution: a read-only `catalog.instruments()` min-`ts_init` per climate day would confirm it.
4. Whether any agent-driven hand relaunch outside the log directory has occurred. Mitigated because hand relaunches mirror `spawn_node` and write the same log files (memory: hand-relaunch mechanics).