# AUT-1 r8: Nautilus-native pressure test (2026-10-03)

Four independent read-only checks were run against the nautilus_trader 1.231.0 source, the Breezy code and live data. A fifth check, a docs lookup, had no access to the docs tool, so its output was discarded.

**Result:** r8 §2 claims there is "nothing to reuse" for the decision record and the payload store. That claim is refuted. READY is withdrawn, and a native-first r9 is owed.

| r8 component | Finding | r9 disposition |
|---|---|---|
| Refusal reason per decision | EXISTS. `SHADOW_DECISION` lines (`strategy/forecast_quantile_ladder/strategy.py:564-581`), about 2.2M per day; funnel counts (`decision_funnel.py:116`, `app/trade.py:773`) | Reuse |
| Numeric inputs per decision (p_hat, ask, margin, forecast ref, artefact sha) | ABSENT on refusals. Takes carry only p_hat and ev | One `@customdataclass` `DecisionRecord`, published via `publish_data`, plus `StreamingConfig` on the trade node's own catalog root (`system/kernel.py:508,587-611`). This replaces the custom JSONL writer |
| Depth10 at decision | EXISTS in the recorder tape `order_book_depths` (`runtime/node_config.py:289,606`) | Store a reference `(instrument_id, ts_event)`. Copy only when the tape lacks the frame |
| Forecast inputs | Persisted by the NBP ingest | Store a reference `(station, cycle_ns)`. Drop the payload store unless a gap is proven |
| Order / fill / position chain | NATIVE: `Order.tags` plus streamed `OrderInitialized`/`OrderFilled`/position events. Not enabled (`node_config.py:962,970`). Fills are already durable in `DurableFillRecord` | Enable streaming for these types and drop the custom records |
| Cancel / deny | The native stream cannot write these types (`persistence/writer.py:248-251`) | Small msgbus subscriber |
| Settlement | ABSENT in a live node | Custom record that reuses `read_climate_day_including_corrections` |
| Recorder alive but not capturing | Connection-level detection is native; process-level is absent | systemd `WatchdogSec` + `sd_notify`, sent only while the counters advance, with `Restart=on-watchdog`. Drop the custom watch and watchdog pair |
| NBP feed silent | ABSENT | A check on the existing actor timer |
| Per-instrument freshness | NATIVE: `Cache.quote_tick(iid).ts_init` | Drop `FrameClock`. Verify first that the cache is populated before the handler runs |
| fsync durability | The native stream flushes about every 1 s and never fsyncs | Accept. The loss is bounded, and the completeness audit counts it against the independent `SHADOW_DECISION` denominator |
