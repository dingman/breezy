# AUD-10 — Round 1 review (trading-bot-architect, promotion-gate/risk-architecture lens)

plan id: AUD-10
plan file sha256: 9e7b9d5c2a4775aa34339acf541e833b70afa2593e6e64b090ab6f6d0201f3a8
round: 1
reviewer: trading-bot-architect (independent, adversarial)

## Claims verified

| Ref | Plan claim | Verdict |
|---|---|---|
| `app/trade.py:148-157` `_today_by_station` iterates `SUPPORTED_STATIONS` with no station argument | Confirmed exactly, byte-for-byte. |
| `app/trade.py:210-212` — the call to `_today_by_station()` precedes `load_family_manifest(...)`, so reordering is required | Confirmed exactly: line 210 is `today_by_station = _today_by_station()`, line 212 is `manifest = load_family_manifest(...)`. |
| `composition.py:448` — `for station in SUPPORTED_STATIONS:` in `build_current_rung_hold_strategies` | Confirmed exactly at line 448. |
| `composition.py:553` — the equivalent loop in `build_continuous_rung_hold_strategies` | **Not confirmed at the cited line.** The loop `for station in SUPPORTED_STATIONS:` in `build_continuous_rung_hold_strategies` is at line **565** in the current tree, not 553. Same code, same shape — citation-line drift of 12 lines, not a false claim. |
| `family_manifest.py:289-297` validates `stations` as a non-empty list of strings | Confirmed exactly. |
| `family_manifest.py:151-166` validation-error classes (`UnregisteredFamilyManifestError`, `UnpinnedBoundaryArtefactError`, `UnpinnedDensityArtefactError`) | Confirmed, same shape and refusal semantics as described. |
| `config.py:245-252` / `UnsupportedStationError` allow-list shape reused by `_composable_stations` | Confirmed: `CurrentRungHoldConfig.__post_init__` (lines 239-270) raises `UnsupportedStationError` naming every unsupported station, the exact fail-closed pattern the plan proposes to mirror in `app/trade.py`. |

## Defects

**MATERIAL — the diagnosis undercounts `SUPPORTED_STATIONS` iteration sites in `composition.py`, which weakens C4 as a validation criterion.** Beyond the two loops the plan names (`:448` and `:553`/actually `:565`), `resolve_station_instrument_ids` (called by *both* builders, `composition.py:297-372`) itself:
- builds its working dict directly over all four stations: `buckets: dict[...] = {station: {} for station in SUPPORTED_STATIONS}` (line 319), and
- filters `if station not in SUPPORTED_STATIONS: continue` (line 328).

And `_zero_instruments_message` (`composition.py:375-384`) independently iterates `for station in SUPPORTED_STATIONS` (line 381) to build its diagnostic counts string.

None of these four extra sites are named in the plan's §6 diagnosis, which describes the fix as "composition.py:448 and :553: `for station in SUPPORTED_STATIONS` → `for station in stations`" (two edits). Functionally this is **not a correctness bug** for the manifest-narrowing goal itself: `resolved` is always keyed by the full station set, so `resolved[station]` lookups from the (now-narrower) builder loops stay safe, and instrument resolution simply does harmless extra work for non-composed stations. But it directly undermines **C4** as written — "`SUPPORTED_STATIONS` appears **zero** times in a station-iteration position in `composition.py`" — which is false on the file as a whole after only the two named edits land, and the plan gives no instruction on whether `resolve_station_instrument_ids`/`_zero_instruments_message` are in scope. Left as-is, C4 is either (a) unsatisfiable if graded against the whole file, or (b) satisfiable only by an implementer decision the plan doesn't make explicit, which is exactly the "material design decision left to the implementer" class the review brief asks to flag. There's also a minor secondary effect worth naming: a manifest that narrows to 2 stations will still see `_zero_instruments_message` (if triggered) print counts for all 4 `SUPPORTED_STATIONS`, including ones the manifest never declared — a confusing diagnostic, not a safety issue, but the kind of "why no trades" ambiguity memory `no-trade-day-diagnosis-gaps` already flags as costly.

Required change: either (a) explicitly scope §6/§8/C4 to name all four sites and decide per-site whether each is in-scope (e.g., `resolve_station_instrument_ids` legitimately stays over `SUPPORTED_STATIONS` since it's a catalog-wide resolve, but then C4's wording must be narrowed to "the two station-selection loops" rather than "composition.py" unqualified), or (b) thread `stations` through `resolve_station_instrument_ids`/`_zero_instruments_message` too and update C4's grep target accordingly.

**MINOR — citation drift, `composition.py:553` → actual `:565`.** Same code, same shape; correct before merge.

## Answering the specific reviewer challenges

**Does the mechanism provably never write under `deploy/families/` or touch the supervisor unit?** Yes, provably by construction as described: 10a's diff touches only `app/trade.py` and `composition.py` (composition-input plumbing, no filesystem writes); 10b's output path is explicitly `derived/promotion/proposals/<id>/`, with three hard-refusal RED tests (§6, §7 step 9) asserting the generator cannot write outside `derived/promotion/`, cannot emit `status="REGISTERED"`, and cannot target the currently-armed `sending_family_id`. I found no code path in the plan's own description that touches `deploy/families/` or any systemd unit file — arming stays entirely a human act (§5, §9). This holds.

**Does 10a's threading of `manifest.stations` keep an unsupported station fail-closed, given the frozen archive table covers four stations only (`config.py:74-76`)?** Yes — verified: `_composable_stations` is specified to raise `SettingsError` naming every station in `manifest.stations` not in `SUPPORTED_STATIONS` (§6), the same allow-list shape `CurrentRungHoldConfig.__post_init__` already enforces (confirmed above), and the plan explicitly tests this (`test_a_manifest_naming_an_unsupported_station_refuses_the_boot`, NYC case, §7 step 2 / C2). This is fail-closed by construction, not by convention.

**Is the AUD-08→09→10 chain connected end to end by named artefacts, or implied?** Connected. AUD-08b's output is `station_candidates.jsonl` (consumed nowhere in AUD-09 or AUD-10's own text — it is NOT actually an input to AUD-09's census or AUD-10's criteria table; AUD-09 works off the quote-tape catalog directly, and AUD-10b's inputs list is `replay_results.jsonl`, live-tally artefacts, and the current manifest — no read of `station_candidates.jsonl` anywhere in AUD-10's §6). So the "chain" the audit gap groups together (G-05→G-06→G-07) is **not** a data-flow chain at all: AUD-08 is a parallel, independent capability whose only stated relationship to AUD-09/AUD-10 is that a future expansion venue (Kalshi) would someday feed new stations into both — AUD-08's own §11 says exactly this ("the only seam by which an expansion venue's larger city set becomes a testable input"). This is not a defect in AUD-10 specifically (AUD-10 never claims to consume AUD-08's artefact), but the reviewer brief's premise of an AUD-08→09→10 pipeline is not borne out by any of the three plans' own artefact tables — worth surfacing to the coordinator as a finding about the backlog's own dependency framing, not a flaw to fix inside AUD-10.

## Per-criterion points

| Criterion | Max | Points | Basis |
|---|---|---|---|
| Fidelity to audit gap and completeness | 20 | 17 | Matches author's self-score. |
| Technical correctness and evidence grounding | 20 | 15 | Core diagnosis (trade.py reorder, family_manifest validation, allow-list shape) confirmed exactly; the undercounted iteration sites (MATERIAL above) and the `:553`/`:565` drift are real grounding gaps beyond what the author self-flagged. |
| Implementation specificity and feasibility | 15 | 12 | 10a fully specified apart from the missed sites; 10b's estimator plumbing leans on unread signatures as author notes. |
| Acceptance criteria and validation quality | 20 | 14 | C1-C3, C5-C9 solid; C4 is not currently satisfiable as literally worded once `resolve_station_instrument_ids`/`_zero_instruments_message` are considered — this is the direct cost of the MATERIAL defect above. |
| Autonomous operation, failure handling, recovery | 15 | 12 | Three hard refusals, contradiction ordering (`C-KILL` first), read-only posture toward the live node all verified sound. |
| Portfolio objective alignment, scope, dependencies | 10 | 9 | Honest zero-ROI framing; abandonment criterion stated; the AUD-08 chain-connectivity finding above is informational, not a scope defect in this plan. |
| **Total** | **100** | **79** | |

## Required changes to reach 100

1. Name all four `SUPPORTED_STATIONS`-iteration sites in `composition.py` (`:448`, `:565`, `:319`, `:328`, `:381`) and state explicitly, per site, whether it is in-scope for 10a; rewrite C4 to match whatever scope decision results, rather than leaving "composition.py" unqualified.
2. Correct `composition.py:553` → `:565` in §6/§9.
3. Optionally (not required for 100, but worth a one-line note to the coordinator): correct the backlog's framing of AUD-08→09→10 as a data-flow chain — the three plans' own artefact tables show AUD-08 is not consumed by AUD-09 or AUD-10 today.

## Blockers

The plan's own named blockers (whether R5-7/R5-8 transfer from the closed forecast family to `continuous_rung_hold`; whether `C-VALIDITY` may ever admit a non-`MECHANISM_ONLY` row; arming/live-trading enablement) are all correctly strategy-lead/operator scoped and correctly kept out of this item's code. I concur they block *statistical interpretation* of any future proposal, not the build itself.
