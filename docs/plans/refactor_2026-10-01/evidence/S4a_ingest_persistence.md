# S4a — ingest / persistence / domain / normalize / registry / features: Nautilus-ownership evidence
HEAD 60290e9d, worktree `emdash-refactor-y4qj4`. NautilusTrader 1.231.0 (`.venv/.../nautilus_trader`, abbreviated NT below; paths relative to it).
Method: static read + grep only. No tests, no `lint-imports`, no systemd run. Tags: CONFIRMED = read in source at cited line this session; HYPOTHESIS = inferred / not executed.
Paths below are relative to `src/breezy/` unless prefixed `NT:`/`tests/`/`docs/`.

## 0. Headline findings (ranked)
| # | Finding | Tag |
|---|---|---|
| 1 | Hand-written `Data` + strict encoder/decoder over native `register_arrow` is a justified EXTENSION; `@customdataclass` from_arrow routes via from_dict (NT:model/custom.py:152-153) so drift guard cannot be bolted on without overriding anyway. Keep. | CONFIRMED |
| 2 | `ParquetDataCatalog` is used natively for NwsClimateDay/NwsRawProduct (`persistence/catalog.py:422` write_records). The wrapper adds: per-station root, flock single-writer, read-back skip detection — none exist in NT. Keep. | CONFIRMED |
| 3 | Native `Cache` cannot replace `SqliteStateStore`: only Redis backs it (NT:system/kernel.py:310-329, cache/cache.pyx:1704-1708, 2853). Decline is evidence-backed and contract-pinned. | CONFIRMED |
| 4 | Largest avoidable duplication: the timer->`run_coroutine_threadsafe`->supervised-future bridge is copied in 5 actors (4 in ingest; NBS vs NBP bodies differ by 2 log strings). | CONFIRMED |
| 5 | `StateStore` Protocol declared 4x (gate.py:287, product_index.py:220, gaps.py:185, runtime/submit_intent.py:43); 2 of 3 ingest users re-invent a "manifest key" because the KV store has no scan. | CONFIRMED |
| 6 | Atomic-write helper reimplemented 6 ways with different durability (fsync/no-fsync, fixed vs pid vs mkstemp tmp name). | CONFIRMED |
| 7 | Production-unwired code: `NbmForecastActor`+`nbm_forecast_parse` (NBS), `IemMosFallbackTransport`, `build_archived_climate_day` writer, `archived_selection` have no src/scripts caller (tests/docs only). | CONFIRMED (static) / intent HYPOTHESIS |
| 8 | Only 2 upward-import debts in this seam; both removable (health value types; `QuoteTapeGap` Data type placement). | CONFIRMED |
| 9 | `nws-cli-settlement` SKILL line 176 "Use pyIEM — Do NOT hand-roll" is stale: `docs/plans/WEATHER_INGESTION_PROPOSAL.md:118-122` records the reversal; `normalize/cli_parse.py` is deliberately hand-written; pyiem is `backfill` extra only (pyproject.toml:43). Fix the skill, not the code. | CONFIRMED |
| 10 | Native `StreamingFeatherWriter` subscribes `"*"` on the bus (NT:system/kernel.py:604, persistence/writer.py:169-206) so published custom Data could be tape-recorded natively; current observation/forecast persistence is bespoke (JSONL sidecar / catalog helper). Candidate only for NON-settlement streams. | HYPOTHESIS |

## A. Ownership table
Legend: CLEAR = boundary unambiguous; EXTENDS = Breezy code layered on a native API; UNCLEAR = needs decision.
| Module(s) (LOC) | Nautilus owns | Breezy hand-authored | Status |
|---|---|---|---|
| `domain/{nws_climate_day,nws_raw_product,station_observation,forecast_point,archived_*}.py` (1,400 class LOC) | `Data` base, ts_event/ts_init contract, `register_arrow` (NT:serialization/arrow/serializer.py:89), catalog write/read | Field set, `__init__` validation, `schema()/to_dict/from_dict` per class (each field listed 4x: init/to_dict/from_dict/schema), ts_init=retrieved_at_ns semantics | EXTENDS |
| `domain/strict_arrow.py:85,125` | `register_arrow(encoder,decoder)` hook | Drift-raising encoder/decoder (NT's `dicts_to_record_batch` prints+swallows, serializer.py:379) | EXTENDS |
| `domain/{climate_day,temperature,wmo,season,validation,instrument_leg}.py` | nothing | LST climate day, C-tenths->F, BBB correction token, leg derivation | CLEAR (Breezy) |
| `domain/{selection,archived_selection}.py` | nothing (NT replays by ts_init, no supersession) | max(is_final, ts_init, revision_seq) per (station, climate_day) | CLEAR (Breezy) |
| `normalize/*` (1,226) | nothing | CLI parse, classify prelim/final, sanity, units | CLEAR (Breezy) |
| `registry/*` (582) | nothing | sites.toml loader, settlement clock | CLEAR (Breezy) |
| `persistence/catalog.py:341-560` | `ParquetDataCatalog.write_data/query`, `_make_path` (NT:parquet.py:2465), disjoint-interval check (:382-389) | per-station root path safety, `flock` writer lock (:800), read-back verdict (:422), as-of readers | EXTENDS |
| `persistence/catalog.py:961-1202` (filesystem probe, mountinfo parse) | nothing | NFS/CIFS refusal for flock | CLEAR (Breezy); misplaced in file |
| `persistence/{feather_read,feather_preflight,preflight_memo,catalog_column_scan}.py` (1,216) | feather write (`StreamingFeatherWriter`), `convert_stream_to_data`, parquet files | coalesced reader, truncation verdicts, memo, column-projected scan | EXTENDS (justified, §B) |
| `persistence/quote_tape_gaps.py:19` | `catalog.query(data_cls=QuoteTapeGap)` | consumer-side partition guard; `QuoteTapeGap` type lives in `adapters/polymarket_us/tape_records.py:55` | EXTENDS; UNCLEAR placement |
| `persistence/archive_cache.py` (525) | nothing | content-addressed raw IEM CSV cache + manifest, fsync+flock | CLEAR (Breezy) |
| `persistence/{nbp_derived_store,scored_trial_store,external_capital_flows,station_candidates,residual_fills,realized_draws}.py` (2,291) | nothing (not `Data`; analysis/evidence outputs) | own parquet/json/jsonl writers+readers | CLEAR (Breezy) but see §B |
| `persistence/{exit_gate,live_orders_gate,exit_tags,family_manifest,gs_boundary_artefact,mechanism_test_guard}.py` (1,481) | `Order.tags` only | safety allowlist gates, sha-pinned artefacts | CLEAR (Breezy); "persistence" is a layer-placement name, not a storage role |
| `ingest/*_actor.py` (4 actors) | `Actor`, `Clock.set_timer(start_time=)` (native stagger), `publish_data` (NT:common/actor.pyx:2813), lifecycle | cross-thread bridge, supervision, resume cursor, completeness deadline | EXTENDS |
| `ingest/http.py`, `probe_transport.py`, `*_transport.py` | `nautilus_pyo3.HttpClient` exists but ctor is `(default_headers, header_keys, keyed_quotas, default_quota, timeout_secs, proxy_url)` (NT:core/nautilus_pyo3.pyi:5417) — no redirect/TLS/size-cap control | httpx hardened transport (host allowlist, no redirects, 128 KiB cap, digest+receipt stamp) | CLEAR (Breezy) |
| `ingest/gate.py, routing.py, gaps.py, product_index.py, shared_state.py` (4,939) | nothing models "climate day expected but missing" | settlement gate state machine, routing table, gap ledger, first-write-wins index | CLEAR (Breezy) |
| `runtime/sqlite_store.py:88` (adjacent) | `Cache.add(key,bytes)` memory-only w/o Redis | SQLite KV | CLEAR (justified) |
| `features/__init__.py` (0 LOC) | — | empty | pinned only by pyproject.toml:161 + tests/unit/test_test_safety_tooling_config.py:133 |

## B. Custom persistence outside the catalog — could Nautilus own it with EQUAL guarantees?
Facts about NT catalog write (CONFIRMED, NT:persistence/catalog/parquet.py): `_write_chunk` writes directly to final path via `pq.write_table(where=parquet_file)` (:391-395) — NOT temp+rename; exact-name collision = `print` + return (:379); partial range overlap = `ValueError` (:382-389) unless `skip_disjoint_check`; filename is the ts_init range; `delete_data_range(identifier=None)` is a substring-match no-op for flat custom types (:1428-1432); dataset schema inferred from first fragment (:2145); NT `CacheConfig.database` supports only `redis` (kernel.py:312-329).
| Store (file:line) | Today's mechanism / guarantees | Could catalog/Cache own it? Concrete differences | Verdict |
|---|---|---|---|
| Gate/gap/product-index/intent state — `runtime/sqlite_store.py:88`, keys in `ingest/gate.py:287`, `gaps.py:636`, `product_index.py:360` | SQLite, COMMIT before return, thread-confined (:128), per-key overwrite; gap + product manifests faked over KV | `Cache.add/get` = in-memory dict unless Redis (cache.pyx:1704-1708,2853). Catalog is append-only parquet, cannot do per-key overwrite/first-write-wins/CAS. | NO (CONFIRMED). Fix is internal: real tables (HYPOTHESIS), not Nautilus |
| `persistence/archive_cache.py:319` raw IEM payloads | tmp+fsync+`os.replace`+dir fsync; manifest = truth; flock | Catalog stores `Data` rows, not opaque request/response bytes; no content-address/manifest; non-atomic write | NO (CONFIRMED) |
| `persistence/nbp_derived_store.py:291,353` derived NBP rows | parquet partition per cycle, tmp+rename (no fsync, fixed `.tmp` name), dedupe `max(LastModified, raw_sha256)`, JSON manifest + failure ledger | Rows are not `Data`; catalog dedupe = none (silent skip on equal range, ValueError on overlap); rewrite-by-partition is the point | NO (CONFIRMED). Could be `ForecastPoint` rows — HYPOTHESIS, but dedupe/rewrite semantics differ |
| `persistence/scored_trial_store.py:94` | one parquet per score run, mkstemp+`os.replace`, reader dedupes `(trial_id, max score_seq)` | Catalog would add disjoint-interval constraint, non-atomic write, first-fragment schema inference | NO (CONFIRMED) |
| `persistence/external_capital_flows.py:243` | `O_EXCL` create + fsync, unlink on failure; never overwrites | catalog disjoint check ~ equal, but write non-atomic | NO (value too low; JSON evidence) |
| `persistence/station_candidates.py:261,507` JSONL sidecar + register | append + atomic rewrite w/ fsync | not time-series Data | NO |
| `persistence/residual_fills.py:140` jsonl reader | read-only of `excluded_fills.jsonl` | n/a | NO |
| `ingest/observation_sidecar.py` raw obs JSONL, byte-capped, best-effort | diagnostic, never raises | Native streaming writer could record `StationObservation` bus traffic (HYPOTHESIS, kernel.py:604, writer.py:169-206); but loses raw-payload field and byte cap | PARTIAL candidate |
| Quote tape (runtime, adjacent) | Native `StreamingConfig` (node_config.py:606) + native `convert_stream_to_data` | Already native. Breezy adds read-side only | Already native |
| `ingest/nws_actor.py:1390` settlement records | catalog `write_records` | Already catalog | Already native |
Differences matrix for the two real catalog users:
| Property | NT catalog | Breezy wrapper adds |
|---|---|---|
| Atomicity | none (direct write) | read-back verdict (catalog.py:422-500); torn file would fail parquet read (HYPOTHESIS) |
| Dedupe | none; equal range silently skipped (:379) | skipped-vs-written reported; actor nudges `retrieved_at_ns` to `existing_max+1` (nws_actor.py:1436-1437) — storage quirk mutates a provenance timestamp (CONFIRMED) |
| Schema evolution | first-fragment inference (:2145), silent coercion | strict decoder raises (strict_arrow.py:125-172); known gap: later-fragment drift (docstring :35-46) |
| Query by ts range | native `start/end` | as-of readers `read_climate_day_as_of_settlement` (catalog.py:552) |
| Rotation/retention | none (consolidate_* optional) | none; whole-catalog read per persist (nws_actor.py:1395) assumed small (~730 rec/yr/station, docstring :70-83) |
| Station isolation | `identifier_function` needs `instrument_id` (:332) | one root per (venue, city); keeps native delete a no-op by construction |

## C. Duplication candidates
### C1. Breezy re-implementing NT 1.231.0 (symbol pairs)
| Breezy | NT native | Behavioural difference | Substitution risk | Verdict |
|---|---|---|---|---|
| `SqliteStateStore` (`runtime/sqlite_store.py:88`) | `Cache.add/get` (cache.pyx:1704,2853) | NT durable only via Redis; Breezy sync-COMMIT file | Needs Redis service; get never reads DB after warm-load | keep |
| `persistence/feather_read.py` `BatchCoalescer` | `ParquetDataCatalog._read_feather_file` (parquet.py:2787-2799) | NT `read_all()` ~48x memory (measured per docstring); returns None on truncation (:2799) | reimplements reader; native has no batch API (grep `read_next_batch/iter_batches` = 0 hits in NT) | keep (CONFIRMED) |
| `feather_preflight.py` | none (native returns None -> `continue`, parquet.py:2642-2646) | truncation verdicts | none | keep |
| `runtime/quote_tape_ingest_cli.py:817` "Breezy mirror of convert_stream_to_data" (adjacent) | `convert_stream_to_data` | coalesced read, preflight; pinned by `tests/contract/test_quote_tape_ingest_native_pin.py` | drift on NT bump | keep, pinned |
| `ingest/http.py` | `nautilus_pyo3.HttpClient` | see §A | n/a | keep |
| `ingest/*actor` bridge | `Actor.run_in_executor` returns TaskId (actor.pyx:1047), result unreachable | NT cannot host work whose result is needed | n/a | keep concept, dedupe copies |
| cursor/validators in `SharedIngestState.store` | `Actor.on_save/on_load` | NT save only from kernel.stop (docstring nws_actor.py:38-41; contract-pinned) | n/a | keep |
| Per-station warm-start read | `DataEngine._query_catalog` | NT loop `break`s at first catalog with data (data/engine.pyx:2194,2269-2270) -> stations 2..N would read station 1 | silent wrong data | keep decline (CONFIRMED F3). F1 (metadata dropped) NOT re-verified: engine.pyx:2278+ builds DataResponse with `request.data_type` |
No Breezy symbol found re-implementing `Clock.set_timer`, stagger (`start_time=` is native), or `publish_data`.
### C2. Intra-Breezy duplicates in this seam
| Duplicate | Locations | Difference | Guard | Disposition |
|---|---|---|---|---|
| Timer->threadsafe-submit->`_on_poll_done`->`_record_task_death` | nbm_forecast_actor.py:246-287, nbm_quantile_actor.py:340-381 (diff = 2 log strings), nws_observation_actor.py:226-267 (16-line diff), nws_actor.py:778, strategy/current_rung_hold/fee_drift_probe.py:356-370 | log text; observation variant | tests/contract/test_live_timer_thread_affinity.py | consolidate (one mixin/helper) |
| `on_start`/`on_stop`/`_arm_timer`/`_stagger_start_time`/`inflight`/`poll_timer_armed` | same 3 actors | timer name only | per-actor tests | consolidate |
| `StateStore` Protocol x4 | gate.py:287, product_index.py:220, gaps.py:185, runtime/submit_intent.py:43 | none (each says "structurally identical, declared here to avoid import") | `ClosableStateStore` gate.py:1499 | consolidate to one leaf module |
| `BulletinFetcher` Protocol x2 | nbm_forecast_actor.py:100, nbm_quantile_actor.py:154 | method name + result type | — | simplify (callable alias) |
| Correction alphabet | `domain/wmo.py:20` `^CC[A-Z]$` vs `normalize/classify.py:32` whole-text superset | alphabet identical by test | tests/unit/test_normalize_correction_signal_agreement.py | consolidate alphabet constant; keep two predicates (different scopes) |
| Live vs archived record + selector | domain/nws_climate_day.py vs archived_climate_day.py (+raw_product, selection) | ts_init semantics; archive-only fields; deliberate isinstance barrier | pyproject.toml forbidden contract (lines ~114-140), tests/unit/test_archive_import_contract.py | retain intent; but see C3 |
| `leg_of` | adapters/polymarket_us/symbology.py:289 delegates to domain/instrument_leg.py | none (delegation) | tests/contract/test_instrument_leg_layer_agreement_contract.py | fine |
| Climate-day arithmetic | domain/climate_day.py:30 is the one source; ingest/records.py:363, gaps.py:392, registry/settlement_clock.py all call `standard_time_zone` | none | tests/unit/test_normalize_climate_day.py | already consolidated; stale docstring gaps.py:408-410 claims actor still has a copy (actor calls gaps at nws_actor.py:2176) |
| Atomic temp+rename | archive_cache.py:319 (pid tmp, fsync file+dir), nbp_derived_store.py:296,355 (fixed `.tmp`, no fsync), scored_trial_store.py:107 (mkstemp, no fsync), station_candidates.py:507 (mkstemp, fsync file only), external_capital_flows.py:269 (`O_EXCL`, fsync, unlink), runtime/health.py:322 | durability differs | per-store tests | consolidate (BEHAVIOUR CHANGE if fsync added) |
| Manifest-over-KV | gaps.py:136-137,636-658, product_index.py:113,347-409 | tamper handling differs | tests/unit/test_ingest_gaps.py, test_ingest_product_index.py | replace by scan-capable store (see F) |
### C3. Dead / unwired (static, src+scripts grep, CONFIRMED)
| Symbol | LOC | Evidence |
|---|---|---|
| `ingest/nbm_forecast_actor.py` `NbmForecastActor` | 402 | only `NbmQuantileActor` is mounted (app/trade.py:43,750); sole other src refs are docstrings (fee_drift_probe.py:34,322,356) |
| `ingest/nbm_forecast_parse.py` | 276 | sole importer is the unmounted actor |
| `ingest/iem_mos_fallback_transport.py` `IemMosFallbackTransport` | 235 | importers: tests only |
| `ingest/archive_records.py` `build_archived_climate_day` | 95 | no caller in src/scripts; `domain/archived_selection.py` (83) no importer; only reader `persistence/archive_catalog.py:76` used by scripts/analysis/settlement_truth_dataset.py |
Live (kept): `nbm_forecast_transport.py` is the base class of `nbm_quantile_transport.py`; `nbm_forecast_data_type.py` is the shared DataType factory used by quantile actor + strategy.
Total unwired candidate ~1,090 LOC (HYPOTHESIS that intent is "parked", not "dead").

## D. Avoidable abstraction / coupling (quantified)
| Item | Count / location | Tag |
|---|---|---|
| import-linter `ignore_imports` rows naming seam | 2 of 4 (pyproject.toml:105 `ingest.nws_actor -> runtime.health`; :107 `persistence.quote_tape_gaps -> adapters.polymarket_us.tape_records`) | CONFIRMED |
| Row 1 mechanics | `nws_actor.py:197` TYPE_CHECKING import + call-time `_health()` (:331-355) used 2x (:1806, :1880...) to hide the upward edge. `runtime/health.py` imports nothing from breezy (docstring :15; value types GapSummary:154, HealthSnapshot:243, AlertPayload:351, AlertCondition(Key):706-724, AlertState:746). Moving these value types below `ingest` removes the row and the function-level import. | CONFIRMED |
| Row 2 mechanics | `QuoteTapeGap(Data)` defined at adapters/polymarket_us/tape_records.py:55; that module imports `breezy.settlement.exit_guard` and `adapters.polymarket_us.symbology` (:43-44). `persistence` may import `settlement` per layer order, so only `symbology.leg_of`/adapter import blocks a move (domain/instrument_leg.py already has the pure copy). | HYPOTHESIS (not tried) |
| Modules > 800 lines | 6: nws_actor 2422, gate 1654, persistence/catalog 1202, gaps 1176, http 947, routing 870. Code-only lines (excl. docstring/comments/blank): nws_actor 1020, gate 780, routing 409, gaps 498, http 351, catalog 331. catalog.py = 603 docstring lines + 241 lines of unrelated filesystem-probe code. | CONFIRMED |
| Functions > 50 lines | 56 in seam (ast count). Worst: nws_actor `_alert_conditions` 188, `_poll_cycle` 168, `_emit_health` 129, `_prepare_product` 124; records.py `build_climate_day` 124, `build_raw_product` 104; gaps `reconcile` 214; gate `record_forbidden_403` 108, `assert_state_store_durable` 112; cli_parse `parse_cli_product` 141; family_manifest `load_family_manifest` 176; gs_boundary `load_boundary_artefact` 100; domain `__init__`s 56-97 | CONFIRMED |
| One-implementation Protocols | StateStore x4 (impl: `SqliteStateStore` + `gate.InMemoryStateStore` :303 + test fakes); BulletinFetcher x2; ObservationFetcher (nws_observation_config.py:53); ObservationSidecarWriter (nws_observations.py:55); SightingSink (station_candidates.py:214, impl `FileSightingSink`); WriteOutcomeLike (routing.py:371, justified by Nautilus-free stance + contract test); ArrowRecord (strict_arrow.py:59) | CONFIRMED |
| Cycles | none found at module scope in the seam; the sole cycle was historical (nws_actor `_health` docstring) | CONFIRMED (grep), not graph-verified |
| Stale docs | `persistence/__init__.py:1-6` says "single submodule" (has 22); `ingest/gaps.py:408-410`; SKILL pyIEM line | CONFIRMED |
| `features/` | empty package, kept alive by layer contract + 1 test | CONFIRMED |

## E. Invariants to preserve (with pinning tests)
| Invariant | Where enforced | Pinning tests |
|---|---|---|
| Prelim vs final discriminated ONLY by `VALID TODAY AS OF ... LOCAL TIME.`; never issuanceTime or REPORT/SUMMARY wording | normalize/classify.py (`classify_issuance`) | tests/unit/test_normalize_classify.py |
| Climate day = local STANDARD time, fixed offset, never DST/UTC | domain/climate_day.py:30-53; ingest/records.py:363; registry/sites.py | tests/unit/test_normalize_climate_day.py, test_forecast_txn_climate_day*.py |
| Final-record `ts_event` = end of climate day in LST; `ts_init` = `retrieved_at_ns` (not a ctor param) | domain/nws_climate_day.py (docstring), ingest/records.py:225 | tests/unit/test_domain_nws_climate_day.py, test_ingest_records.py |
| Correction = new record with strictly later ts_init; select max(is_final, ts_init, revision_seq); `is_superseded` never consulted | domain/selection.py:68, archived_selection.py:30; nws_actor.py:1416-1440 revision_seq | tests/unit/test_domain_selection.py, test_domain_archived_selection.py, tests/contract/test_catalog_write_interval_contract.py |
| Positional BBB correction vs whole-text advisory share alphabet | domain/wmo.py:20, normalize/classify.py:32 | tests/unit/test_normalize_correction_signal_agreement.py |
| Per-city body-header regex guard (office collision) | normalize/cli_parse.py (`check_structural_allowlist` :428), registry | tests/unit/test_normalize_cli_parse_allowlist.py, test_normalize_cross_city_rejection.py, test_normalize_cli_parse_cities.py |
| Physical sanity bounds incl. diurnal range | normalize/sanity.py | tests/unit/test_normalize_sanity.py |
| Dedupe: first-write-wins `product_uuid -> raw_sha256`; sha256 over raw bytes at receipt | ingest/product_index.py:482, ingest/http.py | tests/unit/test_ingest_product_index.py, test_ingest_nws_actor.py |
| Crash between mark and persist loses nothing; restart resumes by tuple cursor `(ts_init, class, raw_sha256)` | nws_actor.py `record_cursor` (:1485-1500), SharedIngestState | tests/integration/test_ingest_crash_between_mark_and_persist.py, test_runtime_restart_resume.py |
| Catalog: one root per (venue, city); no delete path; single flock writer; read-back skip detection; refuse network FS | persistence/catalog.py:341,422,800,1116 | tests/unit/test_persistence_catalog.py, tests/contract/test_persistence_partitioning.py, test_catalog_nws_records.py |
| Strict schema drift refusal (cols + types) | domain/strict_arrow.py | tests/unit/test_domain_strict_arrow.py, tests/contract/test_catalog_nws_records.py |
| No pyo3 catalog; no `chunk_size` streaming for Cython custom data | persistence | tests/contract/test_persistence_pyo3_catalog_decline.py, test_persistence_streaming_replay.py |
| Cache is memory-only without Redis (justifies SQLite) | runtime/sqlite_store.py, node_config.py:228 | tests/contract/test_nautilus_cache_durability_contract.py |
| Timer callbacks run on a Rust thread w/o loop; raises are discarded (L-16) | all actors | tests/contract/test_live_timer_thread_affinity.py |
| Tape sufficiency/gaps: catalog `data/` != captured tape `live/<instance>` (L-20); truncated feather = TRUNCATED not "0 rows"; `catalog.instruments()` is a multiset (L-31) | persistence/feather_preflight.py, quote_tape_gaps.py | tests/unit/test_feather_preflight.py, tests/contract/test_quote_tape_truncation_preflight.py, test_quote_tape_unclean_shutdown.py, tests/unit/test_quote_tape_gap_loader.py, test_quote_tape_consumer_contract.py |
| Archive base disjoint from settlement base; settlement/strategy never import archived records or NBP derived store | persistence/archive_catalog.py:25, pyproject forbidden contract | tests/unit/test_archive_import_contract.py, test_persistence_archive_catalog.py |
| ingest never leaks UA/contact into source | ingest/http.py | tests/unit/test_live_nws_ingest_no_personal_contact.py |
| Safety gates are source-literal allowlists, not data | persistence/exit_gate.py, live_orders_gate.py | tests/unit/test_persistence_exit_gate.py, test_fq_live_orders_gate.py |
| L-23: a config snapshot is not the effective runtime — the journal is | runtime/health.py snapshot (:279) | docs/core/LESSONS.md:1038 (no test located; HYPOTHESIS that health.py is affected) |

## F. Dispositions
| Subsystem | Requirement served | Disposition | Why / verified extension point | Behaviour differences / migration risk | Boundary |
|---|---|---|---|---|---|
| domain records (6 `Data` types) | Settlement-grade, drift-safe Arrow records | RETAIN; SIMPLIFY boilerplate (HYPOTHESIS: shared field-spec -> generate schema/to_dict/from_dict) | `register_arrow(encoder,decoder)`, `Data` | Generated code must keep strict decoding; risk = silent schema change -> catalog fragments break (strict decoder would raise, which is the guard) | NT owns serialization hook; Breezy owns field set |
| `strict_arrow.py` | drift refusal | RETAIN | NT prints and swallows (serializer.py:379) | none | Breezy |
| catalog.py write/read/lock | append-only per-station settlement store | RETAIN; SPLIT filesystem-probe (241 lines) into own module | `ParquetDataCatalog` native | none if re-exported | NT storage, Breezy invariants |
| `ts_init` nudge (nws_actor.py:1436) | avoid exact-range skip | RETAIN until a design removes ts_init=retrieved_at coupling; note as debt | NT filename = ts range | changing ts_init semantics is a REPLAY/BEHAVIOUR CHANGE | boundary leak |
| nws_actor.py (2,422) | CLI poll/persist/publish/health | SIMPLIFY: extract bridge mixin, health emission + `_alert_conditions` (188 lines) into own module | `Actor`, `Clock.set_timer` already native | pure refactor, replay tests required (tests/unit/test_ingest_nws_actor*.py, integration restart tests) | Breezy |
| Actor bridge x5 | thread bridge L-16 | CONSOLIDATE into one helper | `Actor` has none (actor.pyx:1047 unusable) | tests/contract/test_live_timer_thread_affinity.py must hold; logging text changes (harmless) | Breezy |
| StateStore x4 + manifests | durable gate/gap/index/intent state | CONSOLIDATE protocol now; REPLACE KV+manifest with scan-capable SQLite tables (HYPOTHESIS) | NT Cache needs Redis (kernel.py:312-329) so NOT Nautilus | BEHAVIOUR/MIGRATION CHANGE: on-disk live gate state format; rollback needs dual-read; do last | Breezy |
| Atomic writers x6 | crash-safe artefacts | CONSOLIDATE into `atomic_write_bytes` (leaf, stdlib) | none native | BEHAVIOUR CHANGE if fsync added to nbp/scored stores (slower, safer) | Breezy |
| http.py / probe_transport / transports | hardened untrusted fetch | RETAIN | pyo3 HttpClient lacks controls (pyi:5417) | none | Breezy |
| probe_transport.py (626) | evidence-probe containment; subclass base of nws_observation_transport | RETAIN; HYPOTHESIS split (probe-evidence vs base transport) | — | — | Breezy |
| NBS chain (nbm_forecast_actor/parse, iem_mos_fallback) ~1,090 LOC | forecast fallback/primary (unmounted) | REMOVE or PARK on a branch after owner confirms (open Q1); keep `nbm_forecast_transport` + data_type | static grep | removal breaks 3 test files + test_archive_import_contract | Breezy |
| Archived CLI pair + archive_records/selection/catalog | backfill truth | RETAIN read side (one consumer); REMOVE/PARK writer builder `archive_records.py` pending Q2 | static grep | forbidden-import contract rows reference them (pyproject.toml ~:121-126) | Breezy |
| persistence file stores (nbp_derived, scored_trial, flows, candidates, residual, realized) | evidence/analysis I/O | RETAIN; regroup into `persistence/evidence/` sub-package (naming only) | not Nautilus Data | import-path churn only; pyproject forbidden rows name `breezy.persistence.nbp_derived_store` | Breezy |
| exit_gate/live_orders_gate/exit_tags/family_manifest/gs_boundary | order-permission split gates | RETAIN; regroup `persistence/gates/` | source-literal allowlist design | do not weaken tests | Breezy |
| feather_read/preflight/memo/column_scan | tape ingest safety | RETAIN | native reader returns None on truncation (parquet.py:2799) | pinned by native-pin contract tests | NT writes, Breezy reads |
| quote_tape_gaps + `QuoteTapeGap` placement | tape gap semantics | SIMPLIFY: relocate type or loader to remove ignore row (HYPOTHESIS) | catalog query native | none functional | split |
| `runtime.health` value types | alerts | MOVE value types below ingest to drop ignore row 1 | file imports nothing from breezy | pure move | Breezy |
| observation_sidecar | MIA ambiguity diagnosis | RETAIN; optional native-streaming evaluation (HYPOTHESIS) | StreamingFeatherWriter `"*"` subscribe (kernel.py:604) | native path = feather stream + conversion hazards (L-20), loses raw payload & byte cap | maybe NT |
| normalize / registry / domain pure fns | settlement logic | RETAIN | none native | none | Breezy |
| `features/` | placeholder | REMOVE only with pyproject.toml:161 + test_test_safety_tooling_config.py:133 edits | — | contract edit | — |
| Skill `nws-cli-settlement` line 176 | doc | FIX (docs only) | WEATHER_INGESTION_PROPOSAL.md:118 | none | — |
Flagged as BEHAVIOUR CHANGES (not pure refactors): fsync additions; state-store schema migration; any change to ts_init / nudge semantics; removing unwired chains (test + contract edits); health type relocation changes `lint-imports` config.
Suggested order (lowest risk first): doc/skill fix -> StateStore protocol dedupe -> actor bridge helper -> catalog.py split -> health types move -> atomic-write helper -> nws_actor split -> unwired-chain decision -> state-store tables (last).

## G. Open questions
1. Is the NBS deterministic chain (`NbmForecastActor`, `nbm_forecast_parse`, `IemMosFallbackTransport`) intentionally parked for a later family, or superseded by NBP? (static only; no docs checked for status.)
2. Is the archived-CLI backfill (`ArchivedClimateDay` writer) still planned (docs/plans/CLI_BACKFILL_PLAN.md)? Writer has no caller.
3. DataEngine F1 claim (response drops metadata) in nws_actor.py docstring was not re-verified; engine.pyx:2278+ builds the response from `request.data_type`. Only F3 (first-catalog `break`) confirmed.
4. Is later-fragment schema drift (strict_arrow.py:35-46 residual hole) acceptable, or should `pds.dataset(schema=...)` be enforced upstream? Not modifiable in NT; only reachable via query-side wrapper.
5. Does a torn parquet file from a mid-write crash fail loudly on read? (NT writes in place, parquet.py:391; HYPOTHESIS, not executed.)
6. `lint-imports` and the full test suite were NOT run; no cycle proof beyond grep.
7. Can `ts_init` keep meaning "received at" while avoiding the +1ns nudge (e.g., a separate catalog partitioning key)? Design question for the plan peers.
8. Operator-only caps untouched; nothing here requires an operator decision.
