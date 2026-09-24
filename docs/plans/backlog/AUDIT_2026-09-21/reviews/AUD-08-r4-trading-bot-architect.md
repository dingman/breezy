# AUD-08 — Review record (Round 4, FINAL for this cluster)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-08-unattended-station-candidate-register.md
- Plan file sha256: 8a0514478b757b2d91dd2bd9f65d621e759947664570417d5c4e78336546ff46
- Round: 4 · Reviewer: trading-bot-architect (autonomous-loop/pipeline lens)
- Total: 100/100 · Readiness: READY

## Track-record correction applied this round

Round 3's trading-bot-architect record for this plan awarded 100/100 and stated the
`sighting_sink` seam "has exactly one call site" — which missed that
`_shared_polymarket_us_instrument_provider` is `@lru_cache(maxsize=1)` and is called from BOTH
`PolymarketUSLiveDataClientFactory.create` (data) AND `PolymarketUSLiveExecClientFactory.create`
(exec); the architect reviewer found this and the coordinator verified it in source (A8-3). This
round I re-derived the whole cache-key/discriminator question from source myself rather than
trusting either prior verdict.

## Round-3 defect verification (architect's r3 record read; body checked against source, not §13)

| Defect | Verified fixed in body, against source I re-read myself? |
|---|---|
| MATERIAL A8-3 — no recorder-vs-trade-node discriminator reaches `_shared_polymarket_us_instrument_provider`; a sink parameter would change the `@lru_cache(maxsize=1)` key and construct TWO providers | YES, and the fix is sound. Re-read `factories.py:516-521` (`_shared_polymarket_us_instrument_provider`, signature `(client, provider_config, discovery, clock)` — **unchanged**, no sink parameter), `:589-594` (data factory's call) and `:722` (exec factory's call, inside `PolymarketUSLiveExecClientFactory.create`, confirmed by reading `:642-722`) — both calls pass equal-valued arguments, so the cache key is untouched and `maxsize=1` still yields one provider. The discriminator is `config.subscribe_trades` (`config.py:333`, confirmed `subscribe_trades: bool = False` with the exact comment the plan quotes at `:322-332`, and `factories.py:619-622` repeats it verbatim — I re-read both). Resolved only in the data factory's `create`, verified sufficient: `grep -n "add_data_client_factory\|add_exec_client_factory"` on `quote_tape_cli.py` shows only `add_data_client_factory` at `:188` with no `add_exec_client_factory` call anywhere in the file; `trade_cli.py` calls both at `:402`/`:405`. The sink is attached **after** construction (`instrument_provider.attach_sighting_sink(...)`), never passed as a cache-key argument — confirmed `PolymarketUSInstrumentProvider` (`provider.py:262`) is a plain class extending `InstrumentProvider`, not a frozen dataclass, so a post-construction mutable attach is implementable. A14 is extended with clause (iii): drive both `create()`s in one process with equal-valued configs and assert exactly one provider by identity **and** `cache_info().misses == 1` — this is the right test because it fails if the invariant is ever silently broken by a future edit, not just if the discriminator is missing today. |
| MATERIAL A8-4 — `seed_cities` from `default_registry().pairs()` yields the uppercase site key `"NYC"`, not the lowercase `city_token` the register keys on; merge and H1's join both break | YES. Re-read `sites.py:348-350` (`pairs()` returns `self._settlement_sites.keys()`, i.e. site keys), `sites.toml:117,121` (`[sites.polymarket_us.NYC]`, `venue_city_token = "nyc"`), and `config.py:155-183` (`discovery_city_codes_from_registry` derives via `venue_symbology(...).venue_city_token`, refusing non-lowercase at `:214`). The plan's corrected derivation (§6b.3) reuses the identical comprehension body, filtered on the uppercase station code against `SUPPORTED_STATIONS`, yielding exactly `{("polymarket_us","nyc")}` today. `site_for_venue_city_token` (`sites.py:393-401`) keys on `_sites_by_venue_city_token`, populated from `symbology.venue_city_token` (`sites.py:478`) — confirmed the token domain the seed now emits is the domain H1's join actually needs. |
| MATERIAL A8-5 — the seed path's `Sufficiency` value has no stated mapping; A9 has no pass condition | YES. `sufficiency_from_covered_listed_days` is a total function over three named bands, boundary taken from the imported `MIN_STRUCTURAL_DEAD_STATION_DAYS` — re-verified `structural_dead_stop.py:85` (`MIN_STRUCTURAL_DEAD_STATION_DAYS = MIN_AFTERNOON_STATION_DAYS`), the import at `:58` (`MIN_AFTERNOON_STATION_DAYS,` inside the `from ma_prelock_winner_ask_study import (...)` block), the constant `Final[int] = 15` at `ma_prelock_winner_ask_study.py:163`, and the equality pin at `tests/unit/test_structural_dead_stop.py:99`. No second threshold is invented. |
| MINOR a1 — `count_covered_listed_station_days_from_catalog` called positionally (keyword-only) | YES. `catalog_root=catalog_root` now used; signature re-confirmed keyword-only at `structural_dead_stop.py:219-225`. |
| MINOR a2 — `registry/sites.toml` path drift | YES. Grepped the whole file for `registry/sites.toml` not preceded by `src/breezy/` — zero hits. |
| MINOR a3 — two-day fold window shorter than the three-failure escalation tolerance | YES. Replaced with a `last_folded_day` watermark, folds every unpruned sidecar day since the watermark, counts `sidecar_days_lost` for the one residual (outage > 35 days). New criterion A17. |

No round-3 acceptance is falsely claimed in §13; every disposition matches the body.

## Claims verified this round (fresh reads against current source)

| Ref | Claim | Result |
|---|---|---|
| `_shared_polymarket_us_instrument_provider` signature unchanged, both call sites equal-valued | CONFIRMED at `factories.py:516-521,589-594,722`. |
| `quote_tape_cli.py` registers only a data factory | CONFIRMED — `add_data_client_factory` at `:188`, no `add_exec_client_factory` anywhere in the file. |
| `trade_cli.py` registers both | CONFIRMED at `:402,405`. |
| `config.subscribe_trades` comment and default | CONFIRMED verbatim at `config.py:322-333`. |
| `PolymarketUSInstrumentProvider` is a plain mutable class | CONFIRMED at `provider.py:262-281` (`__init__`, not a frozen dataclass). |
| `sites.py:348` `pairs()` returns site keys, not tokens | CONFIRMED. |
| `discovery_city_codes_from_registry` comprehension body | CONFIRMED at `config.py:166-173`, byte-identical to what §6b.3 says the seed derivation reuses. |
| `MIN_STRUCTURAL_DEAD_STATION_DAYS` chain and its test pin | CONFIRMED at `structural_dead_stop.py:58,85`, `ma_prelock_winner_ask_study.py:163`, `test_structural_dead_stop.py:99`. |

## Defects

None found. All three round-3 MATERIAL defects (A8-3, A8-4, A8-5) are genuinely closed, not
re-worded, and each fix was independently re-derived from source this round rather than accepted
on the plan's citation alone — including the exact seam the coordinator's track-record note flagged
(the `lru_cache` cache-key interaction), which now correctly leaves the cache key untouched and
attaches the sink post-construction instead.

## Strengths (credited)

The A8-3 fix does more than patch the immediate hazard: A14 clause (iii) tests the *invariant*
(one provider per process, by identity and by `cache_info().misses`), not just today's discriminator
value, so a future refactor that reintroduces a sink-as-parameter would fail the test even if nobody
remembered why. The A8-4 fix reuses the existing derivation function's comprehension body rather than
inventing a second path to the same token — the right DRY call given `discovery_city_codes_from_registry`
already exists. The A8-5 fix imports the KILL clock's own floor rather than declaring a second
"15 station-days" literal, closing exactly the drift class the source module's own comment warns
against.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | 08a closes the livelock; 08b's one PM.us row (NYC) is now producible end to end; §6c honestly states AUD-08 owns exactly two of eight eligibility steps. |
| Technical correctness and evidence grounding | 20 | 20 | Every citation I re-opened this round is exact, including the two-factory cache-key claim the track record specifically flagged for scrutiny. |
| Implementation specificity and feasibility | 15 | 15 | Discriminator named, resolving `create()` named and its sufficiency verified from the recorder/trade-node registration split, cache key explicitly untouched, sink attach mechanism named with its idempotency and error type, seed derivation given as a reused comprehension, sufficiency mapping given as a total function over a named constant. Nothing is left for the implementer to invent. |
| Acceptance criteria and validation quality | 20 | 20 | A1–A17 objective; A14(iii) is the load-bearing test that would have caught the round-3 hazard; A6, A9, A17 all have real, reachable pass conditions. |
| Autonomous operation, failure handling, recovery | 15 | 15 | Livelock closed with a two-cycle test; the "impossible by construction" interleaving case is now genuinely unreachable via the `lru_cache` path (verified, not merely asserted); watermark-based recovery with a counted residual; flood cap; three-failure alert escalation; one-shot new-candidate alert. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Zero-ROI honesty preserved; H2 declined without residue; abandonment criterion scoped correctly; every out-of-scope step named with an owner. |
| **Total** | **100** | **100** | |

## Required changes to reach 100

None.

## Blockers (recorded, not scored)

- **Operator/strategy-lead, correctly named, does not cap this plan's score:** widening
  `src/breezy/registry/sites.toml` requires that file's own pre-production re-verification gate; a
  candidate record queues and announces it but does not authorise it.
- **Strategy lead, OUTSIDE this backlog, correctly named:** a fifth station has no measured archive
  table.
- **Unresolved but testable, not a blocker:** whether the venue would ever list a 6th city is
  unobserved (§12), which is why 08a is P1 rather than P0.
