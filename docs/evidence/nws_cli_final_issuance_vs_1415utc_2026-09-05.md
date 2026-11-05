# NWS CLI FINAL issuance vs a 14:15 UTC D+1 scoring run (measured 2026-09-05)

**Provenance.** Read-only measurement by an Explore agent using the repo's own
reader (`persistence/catalog.py:511` `read_climate_days`; selection rule
`_select_current_climate_day` :665 ranks max `(is_final, ts_init, revision_seq)`)
over `~/.local/share/breezy/catalog/polymarket_us/<STATION>/data/custom_nws_climate_day/`.
No network, no bot run, no SQLite opened. Coordinator did not re-run the script;
the per-station table is the agent's output as returned.

**Question.** Does the FINAL daily climate report (CLI) for climate day D land in
Breezy's catalog before 14:15 UTC on D+1, the proposed `breezy-score-live-trials`
slot (`docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md`)?

**Fields.** `issuance_time_ns` = product-header issuance instant (primary);
`retrieved_at_ns` = ingest wall-clock (`ts_init`, stamped once at fetch,
`domain/nws_climate_day.py:239`); `is_final` from `classify_issuance`
(`ingest/records.py:308`). `ts_event` is the climate-day END for finals, so it is
not an issuance time and was not used.

**Window.** Catalog begins 2026-08-16 (MDW) / 2026-08-17 (others) — ingest
go-live; earlier days UNVERIFIED (no records). Climate day 2026-09-04 was
preliminary-only at measurement time (its final lands on 09-05): trailing edge,
not a miss.

`delta_h` = FINAL `issuance_time` − 14:15 UTC on D+1 (negative = before the run).

| station | n_days | n_final | prelim_only | min | median | max | %miss | median ingest delta_h | median local issuance |
|---|---|---|---|---|---|---|---|---|---|
| NYC | 19 | 18 | 1 | -7.97 | -7.82 | -7.30 | 0% | -7.48 | 02:25 EDT |
| SFO | 19 | 18 | 1 | -5.83 | -5.73 | -5.48 | 0% | -5.47 | 01:31 PDT |
| MIA | 19 | 18 | 1 | -5.88 | -5.84 | -5.72 | 0% | -5.62 | 04:25 EDT |
| MDW | 20 | 19 | 1 | -7.73 | -7.67 | +5.93 | 5% | -7.43 | 01:35 CDT |
| LAX | 18 | 18 | 0 | -6.02 | -5.90 | -5.33 | 0% | -5.50 | 01:21 PDT |

The one positive outlier is MDW climate day 2026-08-16, issued
2026-08-17T20:11Z with `correction_flag=True`, `revision_seq=1`: a go-live
backfill of a corrected product, not a routine late final. Excluding it, 90/90
finals landed before the run.

**Ingest cadence.** No `breezy-nws-ingest` timer exists; the service is a
long-running poller (`Restart=always`, 300 s, `runtime/settings.py:141`).
Ingest lags issuance by ~0.1–0.4 h.

**Conclusion.** A 14:15 UTC D+1 run catches 98.9% of FINALs in this sample
(100% excluding the go-live backfill); every station's final lands 5.3–8.0 h
before the run; SFO has the thinnest margin (~5.5 h). A FINAL issued after the
run is scored at the next day's run (the scorer is idempotent; tallies are
cumulative), so the cost of a late final is a one-day lag, never a lost trial.
