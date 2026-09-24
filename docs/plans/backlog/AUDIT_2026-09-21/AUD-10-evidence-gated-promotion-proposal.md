# AUD-10 — Make a manifest's stations real, and generate evidence-gated promotion PROPOSALS

## 1. ID and actionable title

**AUD-10** — (a) fix **REG-1** so a family manifest's `stations` actually drives composition —
including the zero-instrument guard, which today would let a narrowed manifest boot with zero
strategies — and (b) add an unattended **promotion-proposal generator**: machine-checked criteria
over AUD-09's replay results and the live tally produce a *proposed* new family revision plus an
evidence bundle. **Arming stays a human/ruling gate and is untouched by this item.**

Split:

- **AUD-10a** — REG-1: `manifest.stations` consumed by composition, end to end.
- **AUD-10b** — the proposal generator + evidence bundle. Depends on 10a and on AUD-09.

## 2. Source finding and class

- **Gap:** G-07 "Promotion is a human commit and cannot change stations." Verdict **FALSE**.
- **Evidence:** unit-file commits `7938032` (09-12), `23fe848` (09-19), `bcb82d6` (09-20) are the
  promotion mechanism (V). **REG-1** (PROGRESS.md:49): `manifest.stations` / `trial_id_prefix` are
  validated but NOT consumed by composition (V). Written promotion criteria
  (`docs/evidence/FORECAST_EDGE_PEER_REVIEW_2026-09-18.md:121-152`) are not enforced by code (A).
- **Class:** **integration failure** (10a — a validated field is dead-ended one call away from its
  consumer) plus **missing capability** (10b — no code applies the written criteria).

**Existing PROGRESS item — UPDATE, do not duplicate.** **REG-1** (HIGH, plan pointer
"WP-11b merge `fbc5eea`") is exactly AUD-10a. Its PROGRESS row is re-pointed at this plan; no
second row is opened.

## 3. Current behaviour, required behaviour, concrete gap

**Current — verified against source; all line citations re-read in round 1 and spot-re-read in
round 3.**

1. `app/trade.py:192-212` loads exactly one manifest: `settings.sending_family_id` +
   `deploy/families/{id}.json` → `load_family_manifest`. The docstring at `:174-177` claims
   *"promoting a revision is a manifest + env act, never a source edit."*
2. `load_family_manifest` (`persistence/family_manifest.py:211-354`) strictly validates `stations`
   as a non-empty list of strings (`:289-297`) and carries it onto `FamilyManifest.stations`
   (`:183`, constructed at `:345`).
3. **That field is never read on the composition path.** `_today_by_station()`
   (`app/trade.py:148-157`) builds its mapping by iterating the module constant
   `SUPPORTED_STATIONS`, and the two builders iterate the same constant directly:
   `composition.py:448` (`build_current_rung_hold_strategies`) and **`composition.py:565`**
   (`build_continuous_rung_hold_strategies`, which starts at `:488` — the baseline cited `:553`/
   `:486`; corrected in round 1). Everything else *is* threaded from the manifest —
   `required_fee_coefficient=manifest.taker_fee_coefficient` (`trade.py:239,285`),
   `exit_manifest=manifest` (`:269,282`), dispatch by `manifest.composition_kind`
   (`:225,242,288`). Stations are the one hole.
4. **The hole is wider than two loops (round-1 MATERIAL, both reviewers, independently
   re-verified by both round-2 reviewers from a fresh grep).**
   `/usr/bin/grep -n "SUPPORTED_STATIONS" composition.py` returns exactly six
   sites: the import at `:45`, `buckets = {station: {} for station in SUPPORTED_STATIONS}` at
   `:319`, the filter `if station not in SUPPORTED_STATIONS: continue` at `:328`,
   `_zero_instruments_message`'s count string at `:381`, and the two builder loops at `:448`/`:565`.
   Every one is enumerated with a disposition in §6.
5. **A new silent-halt class the baseline would have introduced (round-1 P2, verified twice).** The
   guard is `if all(len(ids) == 0 for ids in resolved.values()):` at `composition.py:444` and
   `:544`, evaluated over `buckets` keyed by **all four** `SUPPORTED_STATIONS` (`:319`). Under a
   narrowed manifest, a day on which *both declared* stations resolve zero but an *undeclared*
   station resolved some does **not** raise: the guard passes, the narrowed loop skips both declared
   stations with a WARN, and the builder returns an empty tuple — **the node boots with zero
   strategies and no refusal.** In a repo whose audit is about silent halts, that is not acceptable
   collateral; §6 fixes it and §7 RED-tests exactly that shape.
6. There is no code that evaluates promotion criteria. They exist as prose:
   `FORECAST_EDGE_PEER_REVIEW_2026-09-18.md` R5-7 (paired estimator `edge_hat = Σx/Σqty`,
   `SE = √I/Σqty`, CI-lower vs CI-lower, station-day block bootstrap) and R5-8 (any artefact change
   MINTS A NEW REVISION; promotion REFUSED while any §9 KILL/LOSS_STOP is tripped **or pending at
   the next scheduled look**; a promotion never resets a tripped clock; promotion requires a real
   `boundary_inputs_sha256`).

**Required.**

- `manifest.stations` is the **only** station source on the composition path, intersected with the
  closed `SUPPORTED_STATIONS` allow-list at the composition root, fail-closed — and the
  zero-instrument guard is evaluated over **that** set, not over the constant.
- A scheduled generator that reads evidence, applies the written criteria mechanically, and emits
  either `NO_PROPOSAL(reason)` or a **proposal**: a candidate manifest JSON (status
  `DRAFT_NOT_REGISTERED`, unpinned artefact shas left unpinned) + an evidence bundle + a
  human-readable rationale.
- **Every predicate must name the artefact its inputs come from**, and any predicate with no
  producer must be declared inert rather than left to evaluate false-for-lack-of-data (round-2
  10-3). §6b.3.
- **The final arming step stays human/ruling-gated and is explicitly out of scope.**

**Concrete gap.** (a) an integration hole between a validated field and its consumers, spanning five
sites and one guard; (b) no machine-checked criteria and no proposal artefact.

## 4. Priority, rationale, dependencies, execution order

**Priority: P1** for AUD-10a, **P2** for AUD-10b.

- 10a is P1 and small: an already-triaged HIGH (REG-1), the precondition for *any* promotion that
  varies stations, and a validated-but-unconsumed field is a false-safety shape. Round 1 raised its
  stakes rather than lowering them: the naive two-loop fix would have **added** a zero-strategy boot
  path (§3.5), so the guard narrowing is part of 10a, not a follow-up.
- 10b is P2 because it consumes AUD-09's output, which does not exist yet, and because there is
  currently **nothing to promote**: no family has a proven edge, admissible n = 0 (PROGRESS.md:32),
  and the forecast-taker programme is CLOSED as terminal
  (`RULING_forecast_edge_programme_closes_2026-09-20.md`). A generator built today will correctly
  and repeatedly emit `NO_PROPOSAL`. That is the honest expected output and is worth having — it
  converts "promotion is a human commit" into "promotion is a human *decision on a machine-checked
  proposal*".

**Dependencies.** 10a: none. 10b: **AUD-10a** and **AUD-09** (hand-off H3, §6b.2). Validity of any
criterion computed over replay results inherits **AUD-11** and **AUD-12** — by id only; until both
land, a proposal may **never** cite a replay-derived edge statistic, only mechanism counts.
**AUD-08 is NOT a dependency** — hand-off H2 is declined without residue; see §6b.2.
**`C-PAIRED` has a named blocking dependency, and it is now OWNED:** a `--family-manifest` flag on
`current_rung_hold_paper_replay.py` (AUD-09 §5/§6b.2, §12) — **owned by AUD-19** (cited by id only),
itself gated on the replay-`trial_id` provenance fix landing first. Until it lands, `C-PAIRED` is
INERT (§6b.3).

**Execution order:** AUD-10a → (AUD-09) → AUD-10b.

## 5. Scope and explicit exclusions

**In scope.** Threading the composable station set through `_today_by_station`,
`resolve_station_instrument_ids`, `_zero_instruments_message` and both builders; narrowing the
zero-instrument guard; a manifest **serialiser** colocated with the loader; a proposal generator
script + evidence bundle; a scheduled emission; tests.

**Explicitly excluded — each for a stated reason.**

- **Arming.** No code writes `sending_family_id`, edits supervisor env, sets a `status` to
  `REGISTERED`, or clears `family_halted`. The live family halt (`continuous_family_check` →
  `family_not_halted` → `FAIL_CONTINUOUS_FAMILY_HALTED` + `CONTINUOUS_FAMILY_HALT_CLEARED_MARKER`,
  `POST_FORECAST_PHASE_2026-09-20.md` B-8) stays human-operated.
- **Writing into `deploy/families/`.** Proposals land under
  `~/.local/share/breezy/derived/promotion/proposals/<content-hash>/`, never the deploy tree.
- **Widening `SUPPORTED_STATIONS`** or the `UnsupportedStationError` allow-list
  (`config.py:76,239-252`; the raise is at `:245-252`). NYC stays excluded (A14, hourly-only feed,
  50 min staleness bound miscalibrated, `config.py:74-75,88-95`). **Extending or recalibrating the
  frozen archive table** (`archive_table.CORPUS_SHA256`, enforced by `ArchiveTablePinMismatchError`
  at `config.py:261-265`) for a fifth station is likewise outside this backlog — see §6c step 4.
- **Any change to `current_rung_hold_paper_replay.py`**, including the `--family-manifest` flag
  `C-PAIRED` would need. Named as a dependency (§4, §6b.3, §12) and **owned by AUD-19** (by id only),
  not taken here.
- **Standing up a champion-scoped KILL clock.** No change to
  `deploy/systemd/score-live-trials-run.sh` or its hard-coded `FAMILY_MANIFEST` (`:47`), and no
  second counter invocation — the dependency `C-KILL` would need. Named as a dependency (§6b.3,
  §11, §12) and **owned by AUD-05** (by id only), not taken here.
- **Changing PREREG v3 §3/§5/§9 semantics**, `taker_fee_coefficient` pins, or
  `DOCUMENTED_TAKER_FEE_COEFFICIENT`.
- **Relaxing any manifest validation.** `load_family_manifest`'s refusals —
  `UnregisteredFamilyManifestError` (`:151`, raised `:255-258`), `UnpinnedBoundaryArtefactError`
  (`:155`, raised `:265-269`), `UnpinnedDensityArtefactError` (`:159`, raised `:283-287`) — stay
  exactly as strict. A proposal is *expected* to be refused by `load_family_manifest` without
  `allow_draft=True`; that is the safety property, not a bug to route around.
- **The exactly-one-sending-family invariant.** `phase1_family_permits` (`composition.py:247-281`)
  and `tests/contract/test_rung_hold_families_mutual_exclusion_contract.py` untouched and green.

## 6. Proposed changes (grounded)

**Nautilus null hypothesis (L-1).** Strategy composition per instrument/venue subset: Nautilus
provides `Trader.add_strategy` with uniqueness on `f"{strategy_id}-{order_id_tag}"`
(`.venv/lib/python3.13/site-packages/nautilus_trader/trading/strategy.pyx:148-149`, uniqueness
checks at `trading/trader.py:400,416`) — which Breezy already uses, one strategy per station with
`order_id_tag=station` (`composition.py:_station_config`, `:387-421`). Nautilus has **no** notion of
a promotable family revision, no manifest, and no promotion gate. **Verdict: the family/promotion
layer is GENUINELY ABSENT and is already Breezy-owned** (`persistence/family_manifest.py`). 10a
reuses the native per-station-strategy mechanism unchanged and only changes *which* stations are
composed; 10b adds no runtime component at all.

### AUD-10a — REG-1, all six sites

- `app/trade.py:148` → `def _today_by_station(stations: Sequence[str]) -> dict[str, dt.date]`,
  iterating the passed sequence in order. The existing call at `:210` becomes
  `_today_by_station(_composable_stations(manifest))`, which requires moving the call to **after**
  `load_family_manifest` (currently `:210` precedes `:212`). That reordering is the whole of the
  control-flow change and must be explicit in the diff.
- New `_composable_stations(manifest) -> tuple[str, ...]` in `app/trade.py`:
  - de-duplicates preserving `SUPPORTED_STATIONS` order (strategy construction order is observable
    in logs and in `Trader` registration, so determinism matters);
  - raises `SettingsError` naming every station in `manifest.stations` **not** in
    `SUPPORTED_STATIONS` — fail-closed, mirroring `CurrentRungHoldConfig.__post_init__`'s
    `UnsupportedStationError` (`config.py:245-252`, re-read in round 3: the raise message quotes
    `SUPPORTED_STATIONS` and the offending list). A manifest naming NYC refuses the boot; it never
    silently drops it;
  - raises `SettingsError` on an empty intersection.

**Per-site disposition of every `SUPPORTED_STATIONS` occurrence in `composition.py`** (round-1
MATERIAL from both reviewers; the six sites are the complete `grep -n` output, re-derived by both
round-2 reviewers independently):

| Site | Code today | Disposition | Reason |
|---|---|---|---|
| `:45` | `from …config import SUPPORTED_STATIONS, CurrentRungHoldConfig` | **REMOVE the `SUPPORTED_STATIONS` name** from this import | After the five changes below there is no remaining use in this module. The allow-list is not weakened: it is enforced *above* by `_composable_stations` (boot refusal) and *below* by `CurrentRungHoldConfig.__post_init__`, which `_station_config` (`:387-421`) calls for **both** builders and which raises `UnsupportedStationError` for any station outside the tuple (`config.py:245-252`, verified). Defence in depth is preserved at two layers; only the middle layer's *iteration* moves to the manifest. |
| `:319` | `buckets = {station: {} for station in SUPPORTED_STATIONS}` | **NARROW** to `{station: {} for station in today_by_station}` | This is the site that makes the zero-guard wrong (§3.5). `resolved` must be keyed by the composable set and nothing else. |
| `:328` | `if station not in SUPPORTED_STATIONS: continue` | **NARROW** to `if station not in today_by_station: continue` | An instrument for an undeclared station must not be bucketed. `today_by_station` ⊆ `SUPPORTED_STATIONS` by construction, so this is strictly tighter than today. **Effect on non-`app` callers — round-2 c1, enumerated below this table.** |
| `:381` | `counts = " ".join(f"{station}={len(resolved[station])}" for station in SUPPORTED_STATIONS)` | **NARROW** to iterate `resolved` in its (composable-ordered) key order | Otherwise the refusal message reports counts for stations the manifest deliberately excluded — a "why no trades" ambiguity memory `no-trade-day-diagnosis-gaps` already prices. Also a `KeyError` risk once `:319` narrows. |
| `:448` | `for station in SUPPORTED_STATIONS:` (`build_current_rung_hold_strategies`) | **NARROW** to `for station in today_by_station:` | The builder loop REG-1 names. |
| `:565` | `for station in SUPPORTED_STATIONS:` (`build_continuous_rung_hold_strategies`, starts `:488`) | **NARROW** to `for station in today_by_station:` | Same. |

**Non-`app` callers affected by the `:328` narrowing (round-2 c1 accepted).** Enumerated from a
round-3 search for `resolve_station_instrument_ids` / `build_current_rung_hold_strategies` /
`build_continuous_rung_hold_strategies` across `src/`, `scripts/` and `tests/`:

- **`src/breezy/app/trade.py:48-49,228,271`** — the production caller, and the one this item
  rewires. No other production module calls any of the three.
- **`tests/unit/test_no_leg_composition_2026_09_14.py:47-49,123-128,145,174`** — calls
  `resolve_station_instrument_ids(tmp_path, {"LAX": _DAY})` and both builders with single-station
  mappings. Effect: **none** — its mapping is already a subset of the allow-list.
- **`tests/unit/test_current_rung_hold_composition.py:45-49,160,183,211,226,251,291,529,534,592,
  621,654,682,712,741,850`** — the main composition suite. Effect: **none** for the same reason;
  its `_TODAY` mapping is allow-list-shaped. The one behaviour change to expect is that a test
  deliberately passing a mapping containing an *unsupported* station would, after this change, fail
  later and louder — `UnsupportedStationError` from `CurrentRungHoldConfig.__post_init__` inside
  `_station_config` (`:387-421`) instead of being silently filtered at `:328`. **That is the correct
  direction and is named here rather than discovered during the port**; if such a test exists it is
  updated to assert the raise, never weakened to restore the silent filter.
- No caller in `scripts/`. `scripts/analysis/whole_tape_paper_replay.py` imports
  `SUPPORTED_STATIONS` directly from `config.py` — not from `composition.py` — and is untouched.

- **The zero-instrument guard (round-1 P2).** `composition.py:444` and `:544` keep the literal
  `if all(len(ids) == 0 for ids in resolved.values()): raise NoTradableInstrumentsError(...)`, but
  because `resolved` is now keyed by the composable set alone, the guard **fires** for the narrowed
  manifest whose declared stations all resolve zero — regardless of what an undeclared station
  resolved. No new guard is invented; the existing one is made correct by narrowing its domain.
  RED-tested at §7 step 3 for exactly the two-declared-zero / one-undeclared-non-zero shape.
- **L-2 unit line.** Before: composed set = `SUPPORTED_STATIONS` ∩ {stations with resolved
  instruments}. After: = `manifest.stations` ∩ `SUPPORTED_STATIONS` ∩ {stations with resolved
  instruments}. For `pm_us_crh_v4.json` (`stations = ["LAX","MDW","MIA","SFO"]` = the constant,
  re-read in round 3) the two are **EQUAL** — the live composition is byte-identical. For any other
  manifest they differ by design. A deliberate, declared narrowing, never a refactor.

### The layer decision (coordinator requirement 1 — identical text in AUD-09 §6)

Verified: `src/breezy/analysis/` **does not exist**, the `[tool.importlinter]` layers contract
(pyproject.toml:71-101) is `exhaustive = true` (:92), so a new `breezy.analysis` package fails
`lint-imports` — the gate this plan runs at §7 step 7.

**Decision: create `analysis` as a real layer, positioned immediately BELOW `app` and ABOVE
`strategy`.** The offline analysis cores must reach *down* into `persistence` (`family_manifest`,
`feather_preflight`, `station_candidates`), `settlement` (`roi_bound`, `current_rung_hold_v2`) and
`strategy` (`SUPPORTED_STATIONS`), and **nothing in the trading path may reach up into them**. The
one hole a layers contract leaves is `app` (above, therefore permitted), closed by an explicit
`forbidden` contract — the property that matters is that the live node process never loads offline
analysis code. The literal `pyproject.toml` change, one inserted layer plus two new contracts:

```toml
layers = [
    "app",
    # Offline analysis cores (census, promotion criteria). Reach DOWN into
    # strategy/persistence/settlement for constants and loaders; nothing below
    # may reach up into them, and `app` is barred by the forbidden contract
    # below so the live node process never loads offline analysis code.
    "analysis",
    "strategy",
    "runtime",
    "adapters",
    "ingest",
    "persistence | registry | normalize",
    "features | settlement",
    "domain",
]
```

```toml
[[tool.importlinter.contracts]]
name = "The live trading path never imports the offline analysis layer"
type = "forbidden"
source_modules = [
    "breezy.app", "breezy.strategy", "breezy.runtime", "breezy.adapters",
    "breezy.ingest", "breezy.persistence", "breezy.registry", "breezy.normalize",
    "breezy.features", "breezy.settlement", "breezy.domain",
]
forbidden_modules = ["breezy.analysis"]

[[tool.importlinter.contracts]]
name = "The offline analysis layer never DIRECTLY imports Nautilus"
type = "forbidden"
source_modules = ["breezy.analysis"]
forbidden_modules = ["nautilus_trader"]
# The property wanted is NO DIRECT ADOPTION: an analysis module must never
# write `import nautilus_trader`. Indirect chains are unavoidable and are NOT
# adoption -- `analysis` is permitted to import `breezy.strategy`, and
# `breezy.strategy.current_rung_hold.config` imports
# `nautilus_trader.model.identifiers` / `nautilus_trader.trading.config` at
# config.py:59-60, which is also where SUPPORTED_STATIONS (:76) lives. Same
# reasoning, and the same flag, as the `.com` adapter contract above.
allow_indirect_imports = true
```

***Round-2 change (10-1, identical to AUD-09's 09-1) — the `allow_indirect_imports = true` line and
its comment are new; revision 2's contract could not pass.*** Verified at source:
`ForbiddenContract.allow_indirect_imports = fields.BooleanField(required=False, default=False)`
(`.venv/lib/python3.13/site-packages/importlinter/contracts/forbidden.py:72`); at `:131-143` a false
value takes `graph.find_shortest_chains(...)`, so indirect chains are violations unless the flag is
true. With `nautilus_trader` in `root_packages` (`:68`), the chain
`breezy.analysis.promotion_criteria → breezy.strategy…config → nautilus_trader` is found on the
first run. **The option NOT taken, and why:** re-sourcing `SUPPORTED_STATIONS` into a Nautilus-free
module would mean editing `src/breezy/strategy/current_rung_hold/config.py` — a live strategy module
with 8 in-repo callers of that symbol — purely to satisfy a lint property, inverting the principle
the repo's own `.com` contract comment states (`pyproject.toml:116-121`), and it would collide
directly with 10a above, which *removes* the `composition.py` import of that very symbol. The flag
is the smaller change and the property it enforces (no direct adoption) is the one actually wanted.
Residual, named: an analysis module could still reach Nautilus indirectly and pass.

`analysis` may import `strategy`, `runtime`, `adapters`, `ingest`, `persistence | registry |
normalize`, `features | settlement`, `domain`; **not** `app`, **not** `nautilus_trader` directly. No
`ignore_imports` entry is added. **`"src/breezy/analysis"` is also added to `[tool.mypy] files`
(pyproject.toml:159-189) so `strict = true` (`:158`) covers it.** Whichever of AUD-09/AUD-10 lands
first makes this change; the second asserts it. **C10 and AUD-09's B10 are the same criterion.**

### AUD-10b — proposal generator

#### 6b.1 Modules and the serialiser

- New `scripts/analysis/promotion_proposal.py` + a pure core
  `src/breezy/analysis/promotion_criteria.py` (no direct `nautilus_trader` import, pinned by the
  second contract above).
- **Manifest serialiser (round-1 p2 accepted).** `family_manifest.py` today exposes only
  `load_family_manifest` (`:211-354`) and the key sets `_REQUIRED_KEYS` (`:96-111`) /
  `_OPTIONAL_KEYS` (`:125`). A generator that hand-rolls the candidate JSON would drift from those
  key sets — the parallel-architecture risk this item otherwise avoids. **Colocate**
  `dump_family_manifest(manifest: FamilyManifest) -> dict[str, object]` and
  `write_family_manifest(path, manifest)` in `persistence/family_manifest.py`, built from
  `_REQUIRED_KEYS | _OPTIONAL_KEYS` so a future key addition breaks the serialiser loudly.
  **Round-trip test:** `load_family_manifest(write_family_manifest(tmp, m), allow_draft=True) == m`.

#### 6b.2 Hand-offs

**Hand-off H3 — AUD-09b → AUD-10b (REAL; identical table in AUD-09 §6b.4).**

| Field | Value |
|---|---|
| Artefact | `~/.local/share/breezy/derived/replay/replay_results.jsonl` |
| `schema_version` | `1` (`REPLAY_RESULTS_SCHEMA_VERSION`, `src/breezy/analysis/replay_results.py`) |
| Writer | `breezy.analysis.replay_results.append_replay_result` (AUD-09b) |
| Reader | `breezy.analysis.replay_results.read_replay_results`, called by `scripts/analysis/promotion_proposal.py` |
| Join key | `(station, climate_day, strategy, lag_minutes)`. *Round-2 change:* `family_id` left the key — it is **provenance on the row**, because AUD-09b replays the armed family only (AUD-09 §6b.2) |
| Unknown version | `UnknownReplayResultSchemaError` — the generator refuses, naming path and version seen |
| Idempotency key | the join key; a duplicate key in the file is a hard error, not last-wins |

**Hand-off H2 — AUD-08b → AUD-10: DECLINED, without residue (round-2 10-2 accepted; stated
identically in AUD-08 §6c and AUD-09 §6a).**
AUD-10 does **not** read `station_candidates.jsonl` — **and no longer reads any part of it.** A
candidate cannot legitimately enter a promotion proposal: `SUPPORTED_STATIONS` is closed, the frozen
archive table covers those four stations only (`config.py:74-76`, `ArchiveTablePinMismatchError` at
`:261-265`), and widening the allow-list is a class-C act requiring a ruling artefact **and** the
`src/breezy/registry/sites.toml` re-verification gate. Justification against **G-05/G-07**: promotion stays a
human decision on a machine-checked proposal; station *expansion* is a different and higher gate, and
laundering it through the promotion path would let a proposal imply an authority it does not have.
*Round-2 correction, and it was a real contradiction:* revision 2 said "does not read" in one
sentence and "the register's candidate count is recorded in `criteria.json`" in the next — a count
cannot be recorded without a read, and that read had no reader, no `schema_version` check and no
missing-file rule, so §9's own refuse-on-missing-input rule would have made a **missing register
refuse a promotion proposal**. The count clause is **deleted here and in AUD-08 §6b**; `C-STATIONS`
becomes a pure subset predicate over the proposal's own stations (§6b.3). The visibility the count
was reaching for is delivered by AUD-08b's one-shot `BREEZY_STATION_CANDIDATE_NEW` alert — a push to
a human, which is what the situation actually needs.

#### 6b.3 Criteria — each predicate bound to its input artefact (round-2 10-3 accepted)

Round 2 found the inputs listed collectively and never bound per predicate, and `C-PAIRED` with no
possible producer. Both are fixed. Every predicate below names **the artefact each input comes
from**; the fourth column states what the predicate does when that input is absent.

| id | predicate | **input artefact(s)** | absent-input behaviour | source |
|---|---|---|---|---|
| `C-KILL` | no §9 KILL/LOSS_STOP of the champion tripped, **or pending at the next scheduled look**. Evaluated first; disqualifying alone | **two literal artefacts, enumerated in *The `C-KILL` binding* below** — the counter JSON `$OUT/covered_listed_station_days_<UTC-day>.json` (keys `count`, `fetch_start`, `stations`, `manifest_sha256`, `depth_root_present`) and the read-only exec-state DB `$POLYMARKET_US_EXEC_STATE_DB` | **refuse the whole run**, on any of: file absent, older than `KILL_CLOCK_MAX_AGE_SECONDS`, provenance mismatch, `depth_root_present == false`, or `evaluable is False` (a promotion with an unknown clock is the one case where silence must not be permissive). **Separately, when the counter file exists but was produced under a manifest that is NOT the champion's, the predicate is `INERT`, never true** — see *Whose KILL clock is it?* below | R5-8 **adapted, PROVISIONAL** |
| `C-PAIRED` | challenger vs champion compared **paired on the same post-`d0_climate_day` station-days** (the ruled adaptation of R5-7's `fit_date`, which does not exist for this family), CI-lower vs CI-lower (never challenger CI vs champion point) | challenger rows from `replay_results.jsonl` (H3) + champion rows from the live tally | **INERT — see below** | R5-7 **adapted, PROVISIONAL** |
| `C-ESTIMATOR` | `edge_hat = Σx/Σqty`, `SE = √I/Σqty` over `CombinedDraw`s, `CI = edge_hat ± z·SE`, plus the station-day **block bootstrap as already pinned in code** — `n_resamples=B_RESAMPLES` (`10_000`, `roi_bound.py:93`), `random_state=np.random.default_rng(SEED)` (`SEED = 20260904`, `:97`), `method="BCa"`, call at `:214-224`; no locally-defined resample count or seed (**C20**) | **the live-tally scored-trial store directory** `${BREEZY_SCORED_TRIALS_DIR:-~/.local/share/breezy/derived/scored_trials}/<champion family_id>/` (`deploy/systemd/score-live-trials-run.sh:54`; one subdirectory per family, L-38) — its `scored_trials_*.parquet` run files plus the `fill_order.jsonl` sidecar. Reader: **`breezy.persistence.realized_draws.load_realized_draws(store_dir)`** (`:249`), *not* the producing script | `NO_PROPOSAL` citing `C-N` | R5-7 **adapted, PROVISIONAL** |
| `C-N` | admissible n meets the family's registered minimum; `MIN_NON_EXCLUDED_N = 30` (**`src/breezy/settlement/roi_bound.py:100`** — corrected in round 1) is the floor below which the result is UNDERPOWERED by design, never a verdict | **the same store directory as `C-ESTIMATOR`**, plus the sidecars *inside it*: `provenance.json` (`_PROVENANCE_SIDECAR_NAME`, `family_tally_v2.py:160`, which must declare `provenance == "live"`, `:380`), `fill_order.jsonl` (`_FILL_ORDER_FILENAME`, `realized_draws.py:83`), `excluded_fills.jsonl` (`read_excluded_fills`, `family_tally_v2.py:838`) and `unresolved_takes.jsonl`. Files, not producers | `NO_PROPOSAL` citing `C-N` with n = 0 | V3 plan §2 |
| `C-REVISION` | the proposal is a NEW revision: new `trial_id_prefix`, new `d0_climate_day` = next climate day, n reset to 0, LD-OBF α spent from zero | the current `deploy/families/<sending>.json` via `load_family_manifest` | refuse the run (no champion manifest = nothing to revise) | R5-8 **adapted, PROVISIONAL** + L-34 class C |
| `C-PIN` | the proposal names a real `boundary_inputs_sha256` / `density_artefact_sha256` or is emitted as `PROPOSAL_INCOMPLETE` listing the artefacts a human must mint | the same manifest + the artefact files it points at | `PROPOSAL_INCOMPLETE` | R5-8 **adapted, PROVISIONAL**; `family_manifest.py:155-166` |
| `C-VALIDITY` | every replay-derived input row carries `validity != REPLAY_VALIDITY` (`"MECHANISM_ONLY"`) **and `params_match == true`**, else no edge statistic may be cited | `replay_results.jsonl` (H3) | vacuously true over zero rows, but `C-N` then fails — no edge statistic can be cited either way | AUD-11 / AUD-12; AUD-09 §6b.2 |
| `C-STATIONS` | **pure subset predicate:** the proposal's `stations` are a subset of `SUPPORTED_STATIONS`. No other artefact is read. Reason `EXPANSION_REQUIRES_RULING` is recorded when it fails | the proposal's own draft manifest only | n/a — the input is always present, it is the thing being proposed | this plan, §6b.2 H2 |

**R5-7 / R5-8 as adapted for `continuous_rung_hold` — RULED, pinned here (round 8).**
Rounds 1-6 tagged these criteria `SOURCE=FORECAST_FAMILY_R5` and stated they were *transcribed, not
adapted*, because the transfer was an open strategy-lead blocker. That blocker is **RULED and
peer-ENDORSED**: `docs/evidence/RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md`
(Revision 2, Q3; review trail `docs/evidence/reviews/RULING_citability_review_2026-09-21.md`). The
verdict is **transfer WITH NAMED ADAPTATIONS, tagged PROVISIONAL** — not as-is, and not replaced. The
adapted text, pinned as the ruling gives it:

> **R5-7 (adapted for `continuous_rung_hold`) — PROVISIONAL.** Realized-edge comparison: PAIRED on
> the same post-`d0_climate_day` station-days for champion and challenger (`d0_climate_day` replaces
> R5-7's original `fit_date`, a forecast-family-only field — `continuous_rung_hold` manifests carry
> no `fit_date`/density-calibration boundary, `deploy/families/pm_us_crh_v4.json:9`'s
> `density_artefact_path` is explicitly `not_applicable_density.json` — and `d0_climate_day`
> (`pm_us_crh_v4.json:5` = `"2026-09-20"`) is the field these families actually register as their
> admission/reset boundary), CI-lower vs CI-lower (never challenger CI vs champion point).
> Estimator: UNCHANGED, family-agnostic, already shared code — `edge_hat = Σx/Σqty`, `SE = √I/Σqty`
> over `CombinedDraw`s (`src/breezy/settlement/current_rung_hold_v2.py::combine_station_day`,
> `:298`), `CI = edge_hat ± z·SE`, plus the station-day block bootstrap ALREADY PINNED IN CODE —
> `scipy.stats.bootstrap((pnl_arr, cost_arr), _ratio_of_sums, paired=True, vectorized=True,
> n_resamples=B_RESAMPLES, random_state=np.random.default_rng(SEED),
> confidence_level=_CONFIDENCE_LEVEL, alternative="greater", method="BCa")`, with
> `B_RESAMPLES = 10_000` and `SEED = 20260904`. No forecast-specific parameter (density table,
> forecast bucket, R5-5) is part of this rule and none transfers.

> **R5-8 (adapted for `continuous_rung_hold`) — PROVISIONAL.** UNCHANGED IN SUBSTANCE. Any artefact
> change — including drift rollback to last-good — MINTS A NEW REVISION; an in-place action under a
> running `S_k` is `permit=None` halt only (L-34 class C). Promotion is REFUSED while any PREREG v3
> §9 KILL/LOSS_STOP **of the champion** is tripped or pending at the next scheduled look; a
> promotion never resets a tripped clock (§9's own count stays live-venue-scoped only, permanently —
> Q2). Promotion requires a real `boundary_inputs_sha256` (`load_family_manifest` raises
> `UnpinnedBoundaryArtefactError` otherwise) — a blocking step, not a by-product. **"The champion"
> means the manifest at `sending_family_id`** (today `pm_us_crh_v4`). R5-8's one operative gap for
> `continuous_rung_hold`, not closed by this adaptation: it presupposes a KILL clock actually scoped
> to the champion, and none is deployed (Q4). **C14** is the correct conservative
> operationalization of that gap and needs no further change.

**Line-citation note — the one place this plan departs from the ruling's own text, and it is a line
range only.** The ruling cites the bootstrap call as `roi_bound.py:213-222`. Re-read at source this
round: `result = bootstrap(` is at **`src/breezy/settlement/roi_bound.py:214`**,
`n_resamples=B_RESAMPLES` at `:219`, `random_state=np.random.default_rng(SEED)` at `:220`,
`method="BCa"` at `:223` — i.e. **`:214-224`**. Constants: `B_RESAMPLES: Final[int] = 10_000`
(`:93`), `SEED: Final[int] = 20260904` (`:97`), `MIN_NON_EXCLUDED_N: Final[int] = 30` (`:100`, the
floor `C-N` already cites). The ruling's substance is unchanged; only its ±1 range is corrected.
**This also closes the residual carried since revision 4** — that `C-ESTIMATOR`'s resample count was
unstated. It is now pinned to the shipped call and RED-tested (**C20**, §7 step 10): the generator
calls `roi_bound`'s bootstrap, it never re-parameterises it and never defines its own `B`/seed.

**Tagging and the lifting condition (both mandatory).** Every predicate whose source column names an
adapted R5 rule carries, in its `criteria.json` row, the literal tag `STATUS=PROVISIONAL,
SOURCE=FORECAST_FAMILY_R5,
ADAPTED_BY=RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21`, and `RATIONALE.md`
states the PROVISIONAL status on **both** `PROPOSAL` and `NO_PROPOSAL` verdicts, so a human reading a
proposal knows the criteria behind it have not been exercised end to end. **The generator never lifts the
tag itself.** The ruling's lifting condition
(`RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md:405-412`) — the first run
completing with **every predicate evaluable, no `INERT` anywhere in the run**, regardless of that
run's verdict — is **necessary, but it is not self-certifying**: a run cannot declare its own criteria
end-to-end exercised on the strength of its own outcome. **Recorded departure:** the ruling's word is
*automatically* (`:405-406`); this plan is deliberately **stricter**, because a run may not
self-certify. The stricter rule only ever keeps the tag on longer and never drops it earlier, so it
cannot conflict with the ruling's binding requirement that every un-lifted verdict carry the tag
(`:410-412`). So **every artefact emitted while the
criteria are PROVISIONAL — `criteria.json`, `RATIONALE.md`, and any `PROPOSAL` — carries
`criteria_status: "PROVISIONAL"` prominently, including the very run that is the first to have no
`INERT` predicate.** That triggering run's own artefact stays tagged; only runs *after* the lift may
read as unqualified. A run blocked by `C-PAIRED`/`C-KILL` `INERT` does **not** even meet the
condition: the adapted rules were cited there, not exercised. **The tag is lifted only by a separate
ruling artefact under `docs/evidence/`** recording that such a run occurred; the generator reads that
artefact **by pinned path + sha256** and lifts only on an exact match — artefact absent, unreadable,
or sha256-mismatched ⇒ `criteria_status: "PROVISIONAL"`, never a silent lift (and never a crash). A
PROVISIONAL `PROPOSAL` is therefore **advisory input to a human promotion commit, never an
auto-promotion** — promotion stays the human unit-file commit this plan already requires (§11), and
`C14` is unchanged. This is the identical gate §11's abandonment criterion already uses, and it is
unreachable until AUD-05's and AUD-19's artefacts exist.

**Champion/challenger at admissible n = 0 (ruled, Q3).** "Champion" = the armed `REGISTERED` manifest
at `sending_family_id`; "challenger" = the not-yet-armed candidate a proposal names. At champion
n = 0, R5-7's pairing **cannot execute** — and that is `C-N`/`C-PAIRED`'s job to say first, which
they already do. R5-7 never runs on an empty champion sample, and `C14` is unchanged.

**`MECHANISM_ONLY` (ruled, Q2 — confirms `C-VALIDITY`'s default, unmodified).** A `MECHANISM_ONLY`
replay result may never feed any promotion criterion requiring an edge statistic; `C-VALIDITY` as
written **stands**. The ruling additionally bars any replay-derived artefact, at **any** validity tag,
from ever being read into, substituted for, or used to corroborate PREREG v3 §9's
`covered_listed_station_days` — permanently, reversible only by a separate ruling. Nothing here does:
`C-KILL`'s two inputs are both live-venue artefacts, which is now a ruled requirement rather than a
local choice.

**The `C-KILL` binding — artefact, keys, reader, staleness (round-3 10-4 accepted in full).**
Revision 3 named `C-KILL`'s input only by its producing *script* while making its absence refuse the
entire nightly run — so the generator's steady-state outcome was undetermined, and the dangerous
failure was unnamed: a **stale** KILL-clock file parses fine and reads "not tripped", i.e. silently
permissive, which is exactly what this row's own parenthetical forbids. Read at source this round,
here is what deployment actually writes, and the binding that follows:

| Field | Value |
|---|---|
| **Artefact 1 (covered-listed count)** | `${BREEZY_LIVE_TALLY_OUTPUT_DIR:-~/.local/share/breezy/derived}/covered_listed_station_days_<UTC YYYY-MM-DD>.json` |
| Producing unit | `breezy-score-live-trials.service`, `OnCalendar=*-*-* 14:15:00 UTC`, `Persistent=true` (`deploy/systemd/breezy-score-live-trials.timer`), whose wrapper `deploy/systemd/score-live-trials-run.sh:115-129` (*round-4 c1: revision 4 wrote `:118-127`*) assigns `CJSON` (`:115`), `rm -f`s it (`:122`) and then runs `scripts/analysis/structural_dead_stop.py --catalog-root … --family-manifest … --output "$CJSON"` (`:123-126`), **exiting 1 if the counter fails** (`:127-129`) — so *absent* unambiguously means "the counter did not succeed today" |
| Write discipline | atomic `tempfile.mkstemp` + `os.replace` (`structural_dead_stop._write_output_json`, `:297-330`); a partial write is never visible |
| Keys present | exactly six, pinned by that script's own `--output` contract (`:189`, `:289`): `count`, `depth_root_present`, `fetch_end`, `fetch_start`, `manifest_sha256`, `stations` |
| **Keys `C-KILL` reads** | `count` → `covered_listed_station_days`; `fetch_start`, `stations`, `manifest_sha256` → provenance checks; `depth_root_present` → refuse the run when `false` (the count would be a measurement artefact, not a fact) |
| **Artefact 2 (fill-time count)** | the exec-state store at `$POLYMARKET_US_EXEC_STATE_DB`, opened **read-only** |
| **Reader** | `scripts/analysis/fill_time_count.count_filled_takes(source_path, *, family_prefix, since_climate_day) -> int \| None` (`fill_time_count.py:101-118`), called with `family_prefix=manifest.trial_id_prefix` and `since_climate_day=manifest.d0_climate_day` — **the identical call, with the identical arguments, that `family_tally_v2.py:1290-1297` makes under `family-tally-v2-run.sh:215-219`**. No second counter is written |
| **Verdict** | `structural_dead(covered_listed_station_days=count, filled_takes=…)` → `StructuralDeadVerdict` (`structural_dead_stop.py:111-132` — *round-4 c1: revision 4 wrote `:110-130`*). The shipped function, never re-implemented. **Reached only after the champion-scope rule below returns "this is the champion's clock"** |
| **MAX-AGE rule** | `KILL_CLOCK_MAX_AGE_SECONDS: Final[int] = 26 * 3600`. The generator resolves **today's** UTC-stamped file; it refuses if the file is absent, **or** if its `st_mtime` is older than that bound. 26 h, not 24: it must tolerate the 14:15Z cadence plus `Persistent=true` catch-up after a host outage, and nothing longer. **Stale ⇒ refuse, byte-for-byte the same refusal as absent** (`NO_PROPOSAL` is *not* used here; the whole run refuses), with `refusal_reason ∈ {KILL_CLOCK_ABSENT, KILL_CLOCK_STALE, KILL_CLOCK_PROVENANCE_MISMATCH, KILL_CLOCK_NOT_EVALUABLE}` |
| **Champion-scope rule (evaluated FIRST, round-4 10-5)** | `C-KILL` compares the file's `manifest_sha256` against the champion manifest's own `manifest_sha256` (`persistence/family_manifest.py:185`, computed over the manifest file's raw bytes at `:220`; written into the counter JSON from `manifest.manifest_sha256` at `structural_dead_stop.py:349`). **Unequal ⇒ `C-KILL` is `INERT`** with `inert_reason="NO_CHAMPION_SCOPED_KILL_CLOCK"` — never `true`, never `false`, and never a verdict. Evaluated **before** staleness, `depth_root_present` and the provenance rule, because a wrong-family file's age and coverage say nothing about the champion. See *Whose KILL clock is it?* below for why this is the deployed steady state and why it is not permissive |
| **Provenance rule (applies only once the champion-scope rule matched)** | refuse unless `fetch_start == manifest.d0_climate_day` and `set(stations) ⊆ set(manifest.stations)`. Once `manifest_sha256` matches, these two are guaranteed by the counter itself (`structural_dead_stop.py:347-349` takes both fields from that manifest), so the check is a cheap integrity cross-check on a hand-edited or truncated JSON, not a family test. *Round-4 c1 correction:* revision 4 called this a mirror of `score-live-trials-run.sh:152-160` — it is **not**. That wrapper extracts `fetch_start` (`:152`) and compares it to the **hard-coded `V1_D0_LITERAL="2026-09-05"`** (`:62`, the PREREG v1 D0 literal) at `:157`, not to any manifest's `d0_climate_day`. The claim is withdrawn; the rule stands on its own reasoning |
| **The permissive trap, closed** | `count_filled_takes` returns `None` — *fail closed, never zero* — for an absent or unreadable source (its own docstring, `:111-115`), and `structural_dead` then sets `evaluable=False` and `structural_dead=False` (`:118-125`). That `False` means **"unknown"**, not "clear". `C-KILL` therefore refuses the run on `evaluable is False` and **never** reads `verdict.structural_dead` without first asserting `verdict.evaluable`. This is the single most important line in the binding, and it is the one an implementer would otherwise get wrong |
| Test | **C17** |

**Whose KILL clock is it? — the deployed counter is v2-scoped, so `C-KILL` is INERT today
(round-4 10-5 accepted in full).**
Revision 4's provenance rule compared the counter JSON to the **champion** manifest read by
`C-REVISION`. Read at source this round, that is unsatisfiable against the deployed artefact and the
comparison it implies is the very error this item exists to prevent:

1. **The deployed counter is bound to a hard-coded v2 manifest.**
   `deploy/systemd/score-live-trials-run.sh:47` sets
   `FAMILY_MANIFEST="$REPO/deploy/families/pm_us_crh_v2.json"` and passes it at `:125`; the counter
   then takes `fetch_start = manifest.d0_climate_day`, `cities = manifest.stations` and
   `manifest_sha256 = manifest.manifest_sha256` from **that** manifest
   (`structural_dead_stop.py:347-349`). `pm_us_crh_v2.json:5` is `"d0_climate_day": "2026-09-05"`;
   the armed family this plan names, `pm_us_crh_v4.json:5`, is `"2026-09-20"`. So a
   champion-scoped `fetch_start` check can **never** pass, and revision 4's generator would have
   refused with `KILL_CLOCK_PROVENANCE_MISMATCH` every night forever — contradicting **C8**'s stated
   expected outcome and making C17(a)'s happy path unconstructable from deployment. The wrapper's own
   comment at `:40-46` is explicit that "the structural-dead-stop pin stays v2-scoped only, tracked
   separately (R-4, SP-1 I5)".
2. **The re-derivation would have crossed families.** `count` would be a **v2-scoped** covered-days
   count (v2 stations since 2026-09-05) while `count_filled_takes` is called with
   `family_prefix=manifest.trial_id_prefix` / `since_climate_day=manifest.d0_climate_day` — i.e.
   **v4-scoped** (`"continuous_rung_hold/trial/"`, since 2026-09-20). Two families' scopes in one
   verdict is exactly the "statistic attached to the wrong family" error memory
   `bss-headline-is-the-wrong-family` records and §11 names as this item's whole justification.

**Resolution taken — option (c): a named, non-permissive INERT state, mirroring `C-PAIRED`.**
When the counter JSON's `manifest_sha256` is not the champion's, `C-KILL` evaluates to the literal
verdict **`INERT`** with `inert_reason="NO_CHAMPION_SCOPED_KILL_CLOCK"`, the generator continues and
emits every other verdict, and — by the rule **C14** already states — **a run containing any `INERT`
predicate can never emit `PROPOSAL`**. A missing champion-scoped KILL clock is therefore *never*
permission; it is a standing bar on promotion that says truthfully *why*. On today's tree this is
the steady state, which is what makes **C8** and **C17** mutually reachable against the deployed
artefacts.

**The two alternatives, and why each is rejected on evidence rather than preference:**
- **(a) Bind provenance to the manifest that actually produced the file** (require
  `manifest_sha256 == pm_us_crh_v2.json`'s) **and read the verdict as v2-scoped.** Rejected: the
  predicate's own statement is *"no §9 KILL/LOSS_STOP **of the champion**"*. A v2-scoped verdict is
  not the champion's, so admitting it as a `true` would be a promotion permitted by another family's
  clock — the identical wrong-family error named above, and a *permission* rather than a bar. The
  v2-scoped file is still **read**, but only far enough to establish that it is not the champion's.
- **(b) Have the generator compute a champion-scoped counter itself**, via
  `structural_dead_stop.py --family-manifest deploy/families/<champion>.json --output <own path>`.
  Rejected on cost, containment and ownership, all three named: it is a quote-tape catalog scan over
  `count_covered_listed_station_days_from_catalog` whose window is `[d0_climate_day, ASOS_FETCH_END)`
  and therefore **grows without bound** as d0 recedes; it would run inside **AUD-09b's wrapper**,
  under the host-wide `breezy-studies.lock` and inside `breezy-replay-daily.service`'s
  `MemoryHigh=3G`/`MemoryMax=4G` cgroup — a cgroup deliberately sized for a single-day replay
  (AUD-09 §6b.3), so a catalog scan there would be OOM-killed and the failure attributed to the
  replay; and it would stand up a **second KILL clock** beside the deployed one, which is precisely
  what the round-3 binding refused to do, making a promotion generator the owner of a number the
  live-tally units own.

**The owned dependency this INERT names.** `C-KILL` becomes evaluable the moment **a deployed
wrapper counts the armed family** — i.e. invokes `structural_dead_stop.py --family-manifest` with
the champion's manifest and writes its own `--output`. That is not this item's change to make: the
repo already tracks the question as **PROGRESS R-4** (`docs/core/PROGRESS.md:73` — the tally "MUST
receive a v3-scoped count (own `--family-manifest`…, never v2's JSON)"; "today no unit runs the v3
tally at all"). **R-4's literal `pm_us_crh_cont.json` naming is SUPERSEDED** (RULING Q4 item 3,
`:483-491`; `pm_us_crh_cont` is retired, `terminal_climate_day: "2026-09-19"`): the count must follow
`sending_family_id` **dynamically**, never a manifest filename baked into spec text. **AUD-05** is the backlog item for the live-family tally unit — **cited by id
only; this plan asserts nothing about AUD-05's content and takes no dependency on its schedule**.
**Owner: AUD-05 exclusively** (RULING Q4 — a named increment implementing SP-1 I5; cited **by id
only**, this plan asserting nothing about its content and taking no dependency on its schedule).
When that clock exists, `C-KILL` stops being `INERT` with **no change to this plan** — the champion-scope rule simply matches and the
full binding above applies. Recorded in §12.

**Honest residual, named rather than papered over (the reviewer's explicit instruction).** No
deployed unit writes a machine-readable KILL *verdict*: `family_tally_v2.py` computes
`StructuralDeadVerdict` at `:673-680` but renders it only into the markdown report
`$OUT/family_tally_v2_<family>_<STAMP>.md` (`render_markdown_v2:1025`, written at `:1327-1329`), and
`--output` takes no JSON form. This plan therefore **re-derives** the verdict from the two
machine-readable inputs above using the shipped `structural_dead()`, rather than scraping markdown
or inventing a second clock. Two consequences are recorded, not hidden: (i) the derivation must stay
byte-equal to the tally's — pinned by **C17**, which asserts the generator's verdict equals
`structural_dead()` over the same two inputs the deployed wrapper supplies; (ii) if a future item
(AUD-05, by id only — this plan asserts nothing about its content) publishes a machine-readable
tally verdict, `C-KILL` should read **that** instead and drop the re-derivation. Recorded as a
dependency in §12.

*Round-2 change to `C-VALIDITY`:* the `params_match` clause is new. AUD-09 §6b.2 establishes that
the replay driver builds `CurrentRungHoldConfig(instrument_ids=..., stations=(station,))` at
`current_rung_hold_paper_replay.py:932` with `required_fee_coefficient` defaulting to
`Decimal("0.06")` (`config.py:226`), while the armed `deploy/families/pm_us_crh_v4.json` registers
`"taker_fee_coefficient": "0.0695"`. A row produced under parameters the named family does not
register is exactly the "statistic attached to the wrong family" error memory
`bss-headline-is-the-wrong-family` records, and `C-VALIDITY` is the barrier that keeps it out of a
proposal. On today's tree every replay row will carry `params_match = false`.

**`C-PAIRED` is INERT, and is declared so rather than left to fail quietly (round-2 10-3).**
Its challenger rows cannot exist: AUD-09b replays the **armed family only** (AUD-09 §6b.2), because
`current_rung_hold_paper_replay.py`'s parser (`:1075-1113`) accepts no family, manifest or
fee-coefficient argument. The champion's admissible live n is 0 (§4, PROGRESS.md:32). So the
predicate has no producer on either side. It is therefore:
- **emitted in `criteria.json` with the literal verdict `INERT`, not `false`** — a false would read
  as "the challenger lost", which is a different and wrong claim;
- accompanied by `inert_reason: "NO_CHALLENGER_REPLAY_PATH"` and the named blocking change:
  a `--family-manifest` flag on the driver threading `required_fee_coefficient` into the config
  built at `:932`;
- **unit-tested with a synthetic fixture** (C7), which round 2 correctly observed is the only kind
  of fixture available — the test asserts the *arithmetic* of a paired comparison, and the plan
  states plainly that it asserts nothing about production;
- **never** counted toward a `PROPOSAL` verdict: a run in which `C-PAIRED` is `INERT` can emit
  `NO_PROPOSAL` or `PROPOSAL_INCOMPLETE`, never `PROPOSAL`. Criterion **C14**.

**`C-ESTIMATOR`'s input type, read and quoted (round-2 c2 accepted).** The predicate does not
re-implement the statistic; it calls the shipped one.
`combine_station_day(rows: Sequence[StratumRow] | tuple[StratumRow, ...]) -> CombinedDraw`
(`src/breezy/settlement/current_rung_hold_v2.py:298`) folds one station-day's constituent rung fills
into `CombinedDraw` (`:195-222`), a frozen `slots=True, kw_only=True` dataclass whose **only** fields
are `x: float`, `variance: float`, `n_constituents: int`; `score_combined(draws)` (`:348`) pools
them into a `ScoreState`. Three consequences the plan must respect, all read this round:
- `CombinedDraw` carries **no station and no climate day**. Pairing is therefore done by the caller,
  which must keep the `(station, climate_day)` key *alongside* each draw — `C-PAIRED`'s "paired on
  the same post-`d0_climate_day` station-days" is a property of the caller's bookkeeping, not of the
  draw.
- `combine_station_day` **raises rather than returns** on **seven** reachable inadmissible shapes,
  not the four its docstring lists (*round-3 c1 accepted — the count "four" was the docstring's
  list, not the code's*). Re-read at source this round:
  1. `ValueError("combine_station_day() is undefined for an empty station-day")` (`:318-319`);
  2. `_MixedDayMissingRungKeyRefusal` — a NO row present while some row lacks a `rung` (`:320-325`);
  3. `_SameRungOppositeSidesRefusal` — same rung carrying both a YES and a NO fill, raised inside
     `_fold_same_rung_rows` (`:269-273`);
  4. `StationDayAdmissionRefusal` — same-rung same-side fills at **differing `entry_ask`**
     (`_fold_same_rung_rows`, `:275-280`);
  5. …at **differing `fee`** (`:281-286`);
  6. …**disagreeing on `held`** (`:287-292`);
  7. `StationDayAdmissionRefusal` when `Σq > 1` (`:331-336`).
  **The contract is a base-class catch, and that is stated rather than left implicit:**
  `StationDayAdmissionRefusal(ValueError)` (`:184`) is the parent of both private refusals
  (`_MixedDayMissingRungKeyRefusal`, `:230`; `_SameRungOppositeSidesRefusal`, `:237`), so
  `except (StationDayAdmissionRefusal, ValueError)` at the call site covers all seven — shapes 1–7
  inclusive, and any eighth a future change adds. The generator catches at that base, emits
  `NO_PROPOSAL` naming the refusal's **type and message**, and never lets one abort the nightly run.
  A per-shape enumeration would have left shapes 4–6 untested. **C15** is restated over all seven.
- `settlement` sits below `analysis` in the amended layers list, so `promotion_criteria.py` may
  import it directly. No new statistic is written in this item.

Each predicate is independently tested; the generator emits **all** verdicts, not just the first
failure, so a `NO_PROPOSAL` says *which* criteria failed, by how much, and from which artefact.

#### 6b.4 Output, emission, refusals

- **Output** under `derived/promotion/proposals/<content-hash>/` — *round-1 p3 accepted*: the
  directory name is the **sha256 of the canonicalised input set** (each input file's own sha256,
  plus the criteria-module version), **not** a UTC stamp. A stamp never collides, so the baseline's
  "idempotent by directory collision" claim was false; a content hash makes it true and testable.
  A second run on unchanged inputs finds the directory present, verifies its `criteria.json` is
  byte-identical, and exits 0 without rewriting; a byte difference under an identical hash is a hard
  error. Contents: `proposal.json` (a candidate manifest written by `write_family_manifest`,
  `status="DRAFT_NOT_REGISTERED"`, unpinned shas left as the all-zero placeholder so
  `load_family_manifest` refuses it without `allow_draft=True`), `criteria.json` (every predicate +
  verdict + value + threshold + **input artefact** + source citation), `evidence/` (copies of the
  exact input rows and their sha256s), `RATIONALE.md`, and `INPUTS.json` (the hash pre-image).
- **Emission:** appended to the AUD-09b wrapper (`deploy/systemd/replay-daily-run.sh`), inside the
  same host-wide `breezy-studies.lock`, after the replay. Disk-only, seconds. No new timer.
  **The coupling to AUD-09's wrapper contract, stated (round-4 10-6 = AUD-09 09-5; round-5 c1:
  the bolded property sentence below is identical word for word in AUD-09 §6b.3 (compare after whitespace normalisation: the two copies differ only in indentation and line-wrap, normalised sha256 ce5b6d1d…a26263) — the lead-in and
  closing around it are not, and are not claimed to be).** AUD-09 revision 4 asserted that wrapper carries "exactly
  two `"$PY"` invocations" and pinned it in **B18**; this line is a third, so a count is the wrong
  invariant — it would fail CI the moment AUD-10b lands, and whichever way an implementer resolved
  that, it would be a cross-item design decision neither plan had taken. **Decided once, for both
  plans:** the wrapper's invocation contract is a **property over a named script set**: **every
  `"$PY"` invocation in `deploy/systemd/replay-daily-run.sh` is one of the named scripts —
  `scripts/analysis/replay_sufficiency_census.py`, `scripts/analysis/replay_daily_runner.py`, and,
  once AUD-10b lands, `scripts/analysis/promotion_proposal.py` — and the wrapper contains no JSONL
  parsing and no `record_blocked`.** **`scripts/analysis/promotion_proposal.py` is the sanctioned
  third invocation**, named in AUD-09 **B18** and in AUD-09 §5; an unnamed fourth still fails. This
  item carries **C19** so the coupling is tested from this side too, not only from AUD-09's.
- **Three hard refusals, each RED-tested:** refuse to write outside `derived/promotion/`; refuse to
  emit `status="REGISTERED"`; refuse to emit a proposal whose `family_id` equals the currently-armed
  `sending_family_id` (an in-place change under a running `S_k` is `permit=None` halt only — L-34
  class C, R5-8).

### 6c. The eligibility sequence for a new station (identical in AUD-08 §6c and AUD-09 §6c)

Stated here because `C-STATIONS` refusing an out-of-allow-list station is only honest if the path
that *would* widen the allow-list is named. Steps marked **OUTSIDE** are not in this backlog:

| # | Step | Owner | In this backlog? |
|---|---|---|---|
| 1 | Venue lists an unregistered city → sighting → candidate record | automated (AUD-08) | **AUD-08** |
| 2 | One alert on first appearance, naming the ruling to open and its owner | automated (AUD-08b) | **AUD-08** |
| 3 | Ruling artefact under `docs/evidence/` + the `src/breezy/registry/sites.toml` re-verification gate | strategy lead + operator | **OUTSIDE** |
| 4 | Archive-table extension/calibration and widening `SUPPORTED_STATIONS` (the frozen corpus pin at `config.py:261-265` means a fifth station has no measured table) | strategy lead + implementer | **OUTSIDE** |
| 5 | Capture: a WS subscription within the shared MARKET_DATA+TRADE cap | implementer, with cap evidence | **OUTSIDE** |
| 6 | The station's days become SUFFICIENT in the census and are replayed | automated (AUD-09) | **AUD-09**, only after 4 and 5 |
| 7 | A promotion proposal may name the station, because step 4 widened the allow-list and `C-STATIONS` is a subset predicate | automated (**this item**) | **AUD-10**, only after 4 |
| 8 | Arming: four separate human acts — commit the manifest, pin the shas, change `sending_family_id`, file the class-C ruling | operator + strategy lead | **OUTSIDE** |

AUD-10 owns step 7, and owns it passively: `C-STATIONS` never *widens* anything, it only stops a
proposal from implying an authority it does not have.

## 7. Ordered implementation steps (RED first)

1. **RED** `tests/unit/test_current_rung_hold_composition.py::
   test_composition_uses_only_the_stations_the_manifest_declares` — a two-station mapping composes
   two strategies, not four. Fails today (loops read the module constant).
2. **RED** `tests/unit/test_trade_cli_current_rung_hold.py::
   test_a_manifest_naming_an_unsupported_station_refuses_the_boot` (NYC ⇒ `SettingsError`, exit
   `EXIT_CONFIG_ERROR`) and `…::test_an_empty_intersection_refuses_the_boot`.
3. **RED (the P2 test)** `tests/unit/test_current_rung_hold_composition.py::
   test_a_narrowed_manifest_whose_declared_stations_all_resolve_zero_refuses_the_boot` — a
   two-station mapping where **both** declared stations resolve zero instruments and a **third,
   undeclared** station resolves several must raise `NoTradableInstrumentsError`, not return an
   empty strategy tuple. Written once per builder. Fails today.
4. **RED (golden)** `…::test_the_live_v4_manifest_composes_the_same_four_stations_as_before` — the
   L-2 equality pin. Expected GREEN throughout; it is the regression barrier. **Extended in round 3
   (c2):** the same test asserts the boot-log line names the composed station set **and** the
   manifest's `family_id` (C18) — the §10 observable was otherwise the only unpinned one in the
   plan.
5. **GREEN** `_composable_stations`, the `_today_by_station` signature, the call reorder, and the
   six `composition.py` site changes in §6 (including the `:45` import removal). Re-run the two
   non-`app` test modules named in §6 and update any test that was relying on the silent `:328`
   filter to assert `UnsupportedStationError` instead.
6. **L-33 mutation evidence:** perturb `:319` back to `SUPPORTED_STATIONS` — step 3's test must
   fail; perturb `:448` back — step 1's test must fail. Record both outputs.
7. Gate: `scripts/ci/run_tests_no_egress.sh tests/unit/test_current_rung_hold_composition.py
   tests/unit/test_no_leg_composition_2026_09_14.py
   tests/unit/test_trade_cli_current_rung_hold.py tests/contract/
   test_rung_hold_families_mutual_exclusion_contract.py tests/unit/test_family_manifest.py`;
   `lint-imports`; `mypy src/breezy`.
8. **RED** `tests/unit/test_family_manifest.py::test_a_manifest_round_trips_through_the_serialiser`
   — `load_family_manifest(write_family_manifest(tmp, m), allow_draft=True) == m`, plus a test that
   a key present in `_REQUIRED_KEYS` but absent from the serialiser fails loudly.
9. **GREEN** `dump_family_manifest` / `write_family_manifest` in `persistence/family_manifest.py`.
10. **RED** `tests/unit/test_promotion_criteria.py`: one test per predicate in §6b.3's table, each
    with a passing and a failing fixture **and an absent-input fixture asserting the fourth column's
    behaviour**; `C-PAIRED` returns `INERT` (never `false`) with `inert_reason=
    "NO_CHALLENGER_REPLAY_PATH"`, and its synthetic paired-arithmetic fixture asserts CI-lower vs
    CI-lower and refuses a challenger-CI-vs-champion-point comparison; `C-STATIONS` refuses a
    proposal naming a station outside `SUPPORTED_STATIONS` **and reads no other file**;
    `C-VALIDITY` refuses a row with `params_match=false`; **each of `combine_station_day`'s seven
    reachable refusal shapes** (§6b.3) yields `NO_PROPOSAL` naming the refusal's type and message
    rather than an unhandled exception, caught at the `ValueError`/`StationDayAdmissionRefusal`
    base, with `StationDayAdmissionRefusal.__bases__` pinned (C15); **and the adapted-R5 pins
    (C20)** — `C-PAIRED` pairs on post-`d0_climate_day` station-days and refuses to look for a
    `fit_date`; `C-ESTIMATOR` calls `roi_bound`'s shipped bootstrap with `B_RESAMPLES = 10_000`
    (`roi_bound.py:93`) and `random_state=np.random.default_rng(SEED)`, `SEED = 20260904` (`:97`;
    call at `:214-224`), defining no local resample count or seed; and every adapted-R5 predicate's
    `criteria.json` row carries the `STATUS=PROVISIONAL, SOURCE=FORECAST_FAMILY_R5, ADAPTED_BY=…`
    tag.
11. **GREEN** `src/breezy/analysis/promotion_criteria.py` **plus the `pyproject.toml` layers
    amendment, both forbidden contracts (including `allow_indirect_imports = true`), and the
    `[tool.mypy] files` entry** (§6), if AUD-09 has not already landed them. `lint-imports` and
    `mypy src/breezy` green at this step.
12. **RED** `tests/unit/test_promotion_proposal.py`: the three hard refusals; a proposal is refused
    by `load_family_manifest` without `allow_draft=True`; `NO_PROPOSAL` names every failed criterion
    **and its input artefact**; a `MECHANISM_ONLY` or `params_match=false` input yields no edge
    statistic anywhere in the output; a run with `C-PAIRED = INERT` can never emit `PROPOSAL`;
    **idempotency** — two runs on unchanged inputs produce one directory and exit 0, and a tampered
    `criteria.json` under an unchanged hash is a hard error; an unknown `replay_results.jsonl`
    `schema_version` refuses; and **C17's seven `C-KILL` arms** — absent, stale (mtime beyond
    `KILL_CLOCK_MAX_AGE_SECONDS`), provenance mismatch, `depth_root_present == false`,
    `evaluable is False`, the champion-scoped happy path whose verdict equals an
    independently-computed `structural_dead(...)`, and **a counter JSON carrying a non-champion
    `manifest_sha256`, which yields `INERT`/`NO_CHAMPION_SCOPED_KILL_CLOCK` ahead of every other
    arm** (round-4 10-5) — each refusing the run or barring `PROPOSAL`, never degrading to a
    permissive read. Two of the fixtures are generated by invoking
    `structural_dead_stop.py --family-manifest` against the v4 and v2 manifests, so the arms are
    pinned to what deployment actually writes rather than to a hand-built JSON.
13. **RED then GREEN** the script + the wrapper line. The RED is **C19**: an assertion over
    `deploy/systemd/replay-daily-run.sh` that every `"$PY"` invocation is one of the three named
    scripts, that the proposal invocation is inside the host-wide `breezy-studies.lock` and follows
    the replay, and that the wrapper still contains no JSONL parsing and no `record_blocked` —
    i.e. AUD-09 **B18**'s property, asserted from this side (round-4 10-6). GREEN is the wrapper
    line plus `scripts/analysis/promotion_proposal.py`.
14. **One real run** against today's actual evidence, with its verdict asserted by a test (see C8).

## 8. Measurable acceptance criteria and required evidence

| # | Criterion | Evidence |
|---|---|---|
| C1 | A manifest declaring 2 stations composes exactly 2 strategies | step 1 RED→GREEN |
| C2 | A manifest naming an unsupported station (NYC) refuses the boot with a message naming it | step 2 |
| C3 | The live `pm_us_crh_v4` composition is byte-identical (same 4 strategies, same ids, same tags) | step 4 golden + step 6 mutation evidence |
| C4 | **`/usr/bin/grep -c "SUPPORTED_STATIONS" src/breezy/strategy/current_rung_hold/composition.py` returns `0`** — all five sites plus the import are dispositioned per §6, and the allow-list is enforced at `app/trade.py::_composable_stations` and `CurrentRungHoldConfig.__post_init__` instead | grep output + the §6 disposition table |
| C5 | A narrowed manifest whose declared stations all resolve zero raises `NoTradableInstrumentsError`, for **both** builders, even when an undeclared station resolved instruments | step 3 RED→GREEN |
| C6 | The zero-instrument refusal message names only the composable stations | assertion on the message in step 3 |
| C7 | Every promotion predicate has a passing, a failing **and an absent-input** test; `C-PAIRED`'s is explicitly labelled synthetic | step 10 output |
| C8 | **The first real run's verdict is asserted, both ways**: the generator's output is parsed by a test that requires either `NO_PROPOSAL` with a non-empty failed-criteria list, **or** a `PROPOSAL` whose `criteria.json` shows every predicate true and whose `proposal.json` is refused by `load_family_manifest` without `allow_draft=True`. Any third shape fails acceptance. **Expected today, restated against the deployed artefacts (round-4 10-5):** `NO_PROPOSAL` citing `C-N` (admissible n = 0) and `C-VALIDITY`, with **both** `C-PAIRED` (`NO_CHALLENGER_REPLAY_PATH`) **and `C-KILL`** (`NO_CHAMPION_SCOPED_KILL_CLOCK` — the 14:15Z counter JSON is produced under `pm_us_crh_v2.json`, `score-live-trials-run.sh:47`, not the champion) recorded `INERT`. This is a **reachable** steady state on today's tree, which is what revision 4's champion-scoped provenance rule made it not: that rule would have refused the run with `KILL_CLOCK_PROVENANCE_MISMATCH` every night, and this criterion could never have been met. | step 14 + the test |
| C9 | The generator cannot write outside `derived/promotion/`, cannot emit `REGISTERED`, cannot target the armed family | step 12, three refusal tests |
| C10 | **`lint-imports` green with `breezy.analysis` present**, under the amended layers list and both new forbidden contracts | command output; identical criterion to AUD-09 B10 |
| C11 | A manifest round-trips through the colocated serialiser and a missing required key fails loudly | step 8 |
| C12 | Proposal directories are content-hashed: two runs on unchanged inputs yield one directory and exit 0; a byte difference under an identical hash is a hard error | step 12 |
| C13 | Contract test `test_rung_hold_families_mutual_exclusion_contract.py` unmodified and green | gate output |
| C14 | **`C-PAIRED` is emitted as `INERT` with `inert_reason="NO_CHALLENGER_REPLAY_PATH"`, never as `false`, and a run containing an `INERT` predicate can never emit `PROPOSAL`** | step 10 + step 12 RED→GREEN |
| C15 | **Every predicate's row in `criteria.json` names its input artefact** (a path or a directory, never a producing script — round-3 10-4), and **each of `combine_station_day`'s SEVEN reachable refusal shapes** (§6b.3 items 1–7: empty rows; missing rung key on a mixed day; same-rung opposite sides; differing `entry_ask`; differing `fee`; disagreeing `held`; `Σq > 1`) produces `NO_PROPOSAL` naming the refusal's type and message rather than an unhandled exception, **via the base-class catch** `except (StationDayAdmissionRefusal, ValueError)` — asserted by a test that also pins `StationDayAdmissionRefusal.__bases__` to include `ValueError` (`current_rung_hold_v2.py:184`), so the catch cannot silently stop covering a subclass | step 10 (seven fixtures) + a schema assertion over `criteria.json` |
| C16 | **`C-VALIDITY` refuses a replay row with `params_match=false`**, and no edge statistic appears anywhere in the output of such a run | step 10 + step 12 |
| C17 | **`C-KILL` is bound, champion-scoped, fail-closed and staleness-aware.** **Seven** arms, each its own fixture, and none of them permissive: **(a)** a well-formed, same-day counter JSON **written by `structural_dead_stop.py --family-manifest <the champion manifest> --output <fixture path>`, so its `manifest_sha256` IS the champion's**, plus a readable exec-state DB, yields a verdict **equal to** `structural_dead(covered_listed_station_days=<count>, filled_takes=count_filled_takes(...))` computed independently in the test. *Round-4 10-5: the fixture is generated from the champion manifest precisely because the **deployed** file is not — see arm (g); this arm proves the binding is correct for the day the deployed clock becomes champion-scoped, and is constructible today only as a fixture.* **(b)** an **absent** counter JSON refuses the run with `KILL_CLOCK_ABSENT`. **(c)** a champion-scoped JSON whose `st_mtime` is set `KILL_CLOCK_MAX_AGE_SECONDS + 1` in the past and whose `count` would read "not tripped" refuses with `KILL_CLOCK_STALE` — **a stale "not tripped" must never be permissive**. **(d)** a champion-scoped JSON whose `fetch_start` ≠ the manifest's `d0_climate_day`, or whose `stations` ⊄ the manifest's, refuses with `KILL_CLOCK_PROVENANCE_MISMATCH`. **(e)** `depth_root_present == false` refuses. **(f)** an absent/unreadable exec-state DB makes `count_filled_takes` return `None`, so `evaluable is False`, and the run refuses with `KILL_CLOCK_NOT_EVALUABLE` — **never** proceeds on `structural_dead == False`. **(g) NEW (round-4 10-5) — the counter's manifest identity is asserted:** a counter JSON whose `manifest_sha256` is **not** the champion manifest's — the fixture is generated from `deploy/families/pm_us_crh_v2.json`, i.e. byte-for-byte what `score-live-trials-run.sh:47` produces today — yields `C-KILL = INERT` with `inert_reason="NO_CHAMPION_SCOPED_KILL_CLOCK"`, **never** `true`, **never** `false`, **never** a `structural_dead` read, and **never** `KILL_CLOCK_PROVENANCE_MISMATCH`; the run continues and emits the other verdicts but **cannot emit `PROPOSAL`** (C14). The arm additionally asserts the evaluation **order**: a v2-scoped file that is *also* stale, or whose `depth_root_present` is `false`, still reports `INERT`, not `KILL_CLOCK_STALE` — a wrong-family file's age says nothing about the champion. **No arm may emit `PROPOSAL`** | step 12 RED→GREEN, seven fixtures, two of them generated by invoking `structural_dead_stop.py --family-manifest` against the v4 and v2 manifests respectively |
| C18 | **The §10 boot-log line is pinned** (round-3 c2): the composition boot log states the composed station set **and** the `family_id` of the manifest it came from, asserted in the C3 golden composition test against the captured log text — not merely described in §10 | step 4 golden test, extended |

| C19 | **The wrapper coupling is tested from this side (round-4 10-6).** After 10b lands, **every `"$PY"` invocation in `deploy/systemd/replay-daily-run.sh` is one of the named scripts** — `scripts/analysis/replay_sufficiency_census.py`, `scripts/analysis/replay_daily_runner.py`, `scripts/analysis/promotion_proposal.py` — **and the wrapper still contains no JSONL parsing and no `record_blocked`**; the proposal invocation is inside the host-wide `breezy-studies.lock` and after the replay invocation. This is the identical property AUD-09 **B18** asserts, deliberately duplicated so neither item can land a wrapper edit that silently breaks the other's criterion | step 13 RED→GREEN; a grep-shaped assertion collecting the wrapper's invoked script paths and its lock/ordering, in the `tests/unit/test_analysis_units_memory_capped.py` shape AUD-09 §7 step 10 uses |

| # | Criterion | Evidence |
|---|---|---|
| C20 | **The adapted R5 criteria are pinned, tagged, and parameter-exact (round 8, RULING Q3).** `C-PAIRED` pairs on post-`d0_climate_day` station-days — never `fit_date`, which provably does not exist for this family; `C-ESTIMATOR` uses the shipped bootstrap parameters unchanged (`B_RESAMPLES = 10_000`, `roi_bound.py:93`; `SEED = 20260904`, `:97`; call at `:214-224`) and defines no local resample count or seed; every predicate sourced from an adapted R5 rule carries `STATUS=PROVISIONAL, SOURCE=FORECAST_FAMILY_R5, ADAPTED_BY=RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21` in its `criteria.json` row, and `RATIONALE.md` states the PROVISIONAL status on **both** verdicts; and a test asserts the tag is **not** dropped while any predicate in the run is `INERT` (the lifting condition is *no `INERT` anywhere*, §6b.3). **Round 9 adds three REDs on the lifting boundary:** (a) a fixture in which **every** predicate is evaluable on the very **first** exercised run still emits `criteria_status: "PROVISIONAL"` in that same run's `criteria.json`, `RATIONALE.md` **and** its `PROPOSAL` — the generator never lifts its own tag; (b) the tag reads as lifted **only** when the pinned lifting-ruling artefact under `docs/evidence/` is present **and** its sha256 matches the pinned value; (c) a missing, unreadable, or tampered (sha256-mismatched) ruling artefact falls back to `PROVISIONAL` rather than lifting or raising | step 10 + step 12 |

**Evidence artefact:** `docs/evidence/PROMOTION_PROPOSAL_MECHANISM_<date>.md` carrying C1–C20 and
stating in its first paragraph that **nothing in this mechanism arms anything**.

## 9. Validation: failure cases, integration, autonomous operation

- **Manifest/allow-list disagreement** → boot refusal with both sets printed. Never a silent drop.
- **All declared stations resolve zero** → `NoTradableInstrumentsError`, because `resolved` is now
  keyed by the composable set (§6). *Round-1 correction: the baseline asserted this held "as today";
  it did not.* C5 is the test.
- **Some declared stations resolve zero** → existing WARN + skip (`composition.py:451-456,
  556-561`) unchanged, now emitted only for declared stations.
- **A non-`app` caller passing an unsupported station** → now raises `UnsupportedStationError` from
  `CurrentRungHoldConfig.__post_init__` inside `_station_config` instead of being silently filtered
  at `:328`. *Round-2 c1:* this is a deliberate behaviour change in the correct direction, enumerated
  in §6 against the two test modules that call these functions, and it is never reverted by
  restoring the filter.
- **Generator input missing or schema-unknown** → the per-predicate rule in §6b.3's fourth column
  applies; there is no blanket refuse-everything rule any more, because a blanket rule is what made
  a missing register look like grounds to refuse a proposal (round-2 10-2). `C-KILL` and
  `C-REVISION` refuse the run; the rest degrade to a named `NO_PROPOSAL`. H3's `schema_version` is
  checked, not guessed.
- **Contradictory evidence** (replay says promote, live tally says KILL pending) → `C-KILL` is
  evaluated first and is disqualifying on its own; R5-8 is explicit that a promotion never resets a
  tripped clock. This holds **only when a champion-scoped clock exists**; when none does, `C-KILL`
  is `INERT` and bars `PROPOSAL` outright (next bullet), which is strictly stronger than
  disqualifying-on-its-own.
- **No champion-scoped KILL clock (round-4 10-5, the deployed steady state today).** The 14:15Z
  counter JSON is produced under the hard-coded `pm_us_crh_v2.json`
  (`score-live-trials-run.sh:47`), whose `d0_climate_day` is `2026-09-05` against the armed family's
  `2026-09-20`. The champion-scope rule (§6b.3) detects this from `manifest_sha256` **before** any
  staleness, coverage or provenance check, and `C-KILL` reports `INERT` with
  `inert_reason="NO_CHAMPION_SCOPED_KILL_CLOCK"`. The run proceeds and emits every other verdict —
  so the nightly line stays informative rather than saturating on one refusal — but **no run
  containing an `INERT` predicate can emit `PROPOSAL`** (C14). A missing champion-scoped clock is
  therefore never permission, and it is never silently re-read as another family's verdict. The
  owned dependency is named in §12. **C17(g).**
- **A halted / may-not-send champion (ruled:
  `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`).** The champion `pm_us_crh_v4`
  remains the deployed `sending_family_id` and is **RULED** not to send orders — but that halt is
  **not yet enforced**: the ruling's own status line says **"UNENFORCED until AUD-02b lands and the
  halt is set"** (`:3`), and its §4 states in the present tense that *"nothing in the repo prevents
  `pm_us_crh_v4` from placing an order the moment pricing legalizes... Writing this ruling does not,
  by itself, stop the family"* (`:273-278`). Any re-arm is a **new registration** (new `family_id`, n reset to 0 — L-34 class C). **The generator's output is
  unchanged: still `NO_PROPOSAL`** — and for reasons that do not depend on the halt, which is why
  this is stated rather than assumed. (i) `C-N` fails at n = 0 on today's tally for a reason
  that does not depend on enforcement at all: zero decisions reach pricing, the accidental by-product
  of the two unrelated data-quality gates (whole-degree NWS cadence; the SFO-only `illegal_cell`
  gate) rather than a designed control (`RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md:276-277`,
  `:337-343`), so no new admissible fills accrue whether or not the halt is ever set. (ii) `C-VALIDITY` bars any replay-derived edge statistic
  regardless. (iii) `C-KILL` and `C-PAIRED` stay `INERT`, and each bars `PROPOSAL` on its own under
  **C14** — and (i), (ii) and (iii) are each **independently sufficient** for `NO_PROPOSAL`, so the
  conclusion stands with or without enforcement. The halt is therefore never read as a reason to promote *around* the champion: a proposal
  naming a successor is still refused until both owned dependencies land, and the four human arming
  acts (last bullet of this section) are untouched. What the live tally may legitimately count for
  this family is ruled separately in
  `docs/evidence/RULING_live_family_tally_scope_2026-09-21.md`; this item reads that store through
  `load_realized_draws` only and asserts nothing further about it.
- **An inadmissible station-day** → all **seven** of `combine_station_day`'s reachable refusals are
  caught at the `StationDayAdmissionRefusal`/`ValueError` base and reported, never allowed to abort
  the nightly run (§6b.3, C15).
- **A stale KILL clock** (one that *is* the champion's) → refused identically to an absent one
  (`KILL_CLOCK_STALE`), because a counter JSON written days ago parses cleanly and reads
  "not tripped". So is a clock that cannot be
  evaluated at all (`count_filled_takes` → `None` ⇒ `evaluable is False`): the generator refuses
  rather than reading `structural_dead == False` as permission. §6b.3's binding, C17.
- **Integration with the live node: read-only.** The generator runs in the studies slice, touches no
  venue, mints no permit, and writes only under `derived/promotion/`. 10a changes composition input
  only; the permit path (`order_enablement.py:207`), the exec-client caps
  (`exec/client.py:3489-3531`) and the NO-SEND firewall are untouched.
- **Autonomous operation.** The proposal step inherits AUD-09b's timer, lock, and failure
  observability. Idempotency is by content hash (§6b.4), a real and tested property.
- **The human gate is load-bearing and must stay visible.** A proposal is inert: to act on it a
  human commits the manifest into `deploy/families/`, pins the artefact shas, changes
  `sending_family_id`, and — for a class-C revision — files a ruling under `docs/evidence/`. Four
  separate acts, each reviewable, none automatable by this item. Station *expansion* adds more
  (§6c steps 3–5) and is why H2 is declined.

## 10. Deployment, observability, rollback

- **Deploy:** 10a ships with the next node boot (composition input only; no unit change). 10b is one
  extra line in the AUD-09b wrapper (`deploy/systemd/replay-daily-run.sh`) — the **sanctioned third
  `"$PY"` invocation** under AUD-09 **B18**'s named script set (§6b.4, round-4 10-6), inside the
  same host-wide `breezy-studies.lock`. No new unit and no new timer; adding the line must keep
  B18 green, which **C19** asserts from this side.
- **Observability:** the boot log must state the composed station set **and the `family_id` of the
  manifest it came from** — today the family id is never logged at runtime (G-15(b)), so this
  line is also the cheapest partial repair of that gap. **Pinned by C18** (round-3 c2: every other
  observable in this plan carried a criterion; this one did not). The generator's daily line states `PROPOSAL(<hash>)` or
  `NO_PROPOSAL(<criteria>)`, and names any `INERT` predicate.
- **Rollback:** 10a reverts to the constant-iterating loops (behaviour returns to REG-1, including
  the pre-existing full-set guard). 10b: remove the wrapper line; `derived/promotion/` is read by
  nothing that trades. The `pyproject.toml` amendment reverts only together with removing
  `src/breezy/analysis/` and its `[tool.mypy] files` entry.

## 11. Relationship to portfolio-level ROI

**Demonstrated: none.** 10a enables a promotion to *act*; it promotes nothing. 10b's honest expected
output for the foreseeable future is `NO_PROPOSAL` — no proven edge, admissible n = 0, forecast
programme closed, **`C-PAIRED` `INERT`** (round 3; `inert_reason="NO_CHALLENGER_REPLAY_PATH"`) for
want of a challenger-replay path, and **`C-KILL` `INERT`** (round-4 10-5;
`inert_reason="NO_CHAMPION_SCOPED_KILL_CLOCK"`) because the 14:15Z counter JSON is produced under
the hard-coded `pm_us_crh_v2.json` (`score-live-trials-run.sh:47`), not the champion's manifest.
Both `INERT`s are the expected steady state recorded in **C8**, tested by **C14** (`C-PAIRED`) and
**C17(g)** (`C-KILL`), excluded from this item's scope by the two §5 dependency bullets, and named with
owners in §12; neither is ever `true`, ever `false`, or ever read as permission.

**Plausible, stated as plausible:** the programme's repeated, documented failure mode is a statistic
applied to the wrong family — the 09-20 BSS correction (memory `bss-headline-is-the-wrong-family`)
and `POST_FORECAST_PHASE_2026-09-20.md` B-1, *"this is the identical error I committed a correction
for earlier today"*. A generator that reads the family id from the manifest, refuses a row whose
engine parameters do not match that family's registered ones (`C-VALIDITY`'s `params_match` clause),
declares an unproducible comparison `INERT` instead of `false`, and prints its own criteria with
their input artefacts and citations is a direct control on the most expensive recurring error in
this repo's history. That is a *correctness* benefit, not a return benefit, and is not counted as
ROI. 10a additionally removes a latent zero-strategy boot path, which is a silent-halt class this
audit exists to close.

**The COMPOUND limit, stated here in one place (round-5 10-7).** Each `INERT` predicate bars
`PROPOSAL` on its own (**C14**), and the two are independent, so **no run can emit `PROPOSAL` until
BOTH externally-owned dependencies land**: **(1)** a **champion-scoped KILL clock** — a deployed
wrapper invoking `structural_dead_stop.py --family-manifest <champion manifest> --output <its own
path>`; **owned by AUD-05** (RULING Q4 — a named increment implementing SP-1 I5), cited **by id
only**, this plan asserting nothing about its content and taking no dependency on its schedule; and
**(2)** **`--family-manifest` on the replay driver** (`current_rung_hold_paper_replay.py`, threading
`required_fee_coefficient` into the `CurrentRungHoldConfig` built at `:932`), **owned by AUD-19**
(RULING Q4, cited by id only), itself gated on the replay-`trial_id` provenance fix. Both are out of
this
item's scope (§5) and **both become evaluable with no change to this plan** (§6b.3, §12).
**Until both land, this item's deliverable is a machine-checked REFUSAL WITH REASONS, not a working
promotion path:** the generator runs nightly, emits every other verdict, names each `INERT`
predicate and its `inert_reason` (§9, §10), and refuses to promote. That is a standing,
self-describing bar — worth having, and honestly less than a promotion path.

**How it will be evaluated:** by C1–C20, and thereafter by one question at each promotion decision —
*did the proposal's machine-checked verdict agree with the human ruling?* A disagreement is a finding
about the criteria and is recorded either way. **Abandonment criterion (re-gated, round-5 10-7):**
it counts **only promotion decisions on which EVERY predicate was evaluable — no `INERT` anywhere in
the run**. If after two such decisions the proposal is ignored or overridden both times, the criteria
are wrong or the artefact is unusable; retire it rather than maintain a decorative gate. Decisions
taken while `C-PAIRED` or `C-KILL` is `INERT` do **not** count: while `PROPOSAL` is unreachable the
generator can only ever say "do not promote", so any human promotion is an override **by
construction**, and counting those would retire a correct gate for an upstream cause. 10a is **not**
subject to this: it is a defect fix.

## 12. Assumptions, unresolved questions, blockers

- **Assumption (verified):** `manifest.stations` is validated non-empty at load
  (`family_manifest.py:289-297`), so `_composable_stations` never receives an empty list from a
  well-formed manifest; the empty-intersection guard covers the allow-list case only.
- **Assumption RETIRED, now verified (round 1, extended round 3):** all six `SUPPORTED_STATIONS`
  sites in `composition.py` are enumerated with dispositions in §6, and — new this round — the
  **non-`app` callers** of the narrowed functions are enumerated there too, with their expected
  effect. Callers of the constant outside this module (`config.py` itself, `app/trade.py`,
  `scripts/analysis/whole_tape_paper_replay.py`) are named and unchanged.
- **DEPENDENCY — externally owned, owner RULED in round 8 (was: BLOCKER, round-2 10-3):**
  `C-PAIRED` cannot evaluate until `current_rung_hold_paper_replay.py` gains a `--family-manifest`
  flag threading at least `required_fee_coefficient` into the `CurrentRungHoldConfig` built at
  `:932`. Excluded from both AUD-09's and AUD-10's scope; recorded identically in AUD-09 §12.
  **Owner: AUD-19** (a new sibling backlog item, `RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md`
  Q4 — cited **by id only**; this plan asserts nothing about its content and takes no dependency on
  its schedule), itself gated on the replay-`trial_id` provenance fix landing first. **Until it
  lands `C-PAIRED` stays `INERT` and no run can emit `PROPOSAL` (C14)** — round 8 named the owner,
  it did not produce the artefact.
- **DEPENDENCY — no deployed unit writes a machine-readable KILL verdict (round-3 10-4, named
  rather than papered over).** Verified this round: `family_tally_v2.py` computes
  `StructuralDeadVerdict` at `:673-680` but renders it **only** into the markdown report
  `$OUT/family_tally_v2_<family>_<STAMP>.md` (`render_markdown_v2:1025`, written `:1327-1329`); its
  `--output` has no JSON form. What *is* written machine-readably is the **counter** JSON
  (`covered_listed_station_days_<UTC-day>.json`, six keys, written 14:15Z by
  `score-live-trials-run.sh:115-129` — *round-4 c1* — under the **v2** manifest pinned at `:47`,
  which is the separate defect the entry below records) — one of the verdict's two inputs. This item therefore
  **re-derives** the verdict with the shipped `structural_dead()` from that JSON plus a read-only
  `count_filled_takes` over `$POLYMARKET_US_EXEC_STATE_DB`, rather than scraping markdown or
  standing up a second clock; **C17** pins the derivation equal to the tally's. Two consequences
  are accepted rather than hidden: the derivation is a second call site that must not drift (C17 is
  the guard), and if a later item — AUD-05, cited **by id only**; this plan asserts nothing about
  its content — publishes a machine-readable tally verdict, `C-KILL` should read that artefact and
  the re-derivation should be deleted. **Owner: AUD-05** (RULING Q4, by id only). This does not
  block the build: both inputs exist today and are read-only.
- **DEPENDENCY — the deployed KILL clock is v2-scoped, so `C-KILL` is `INERT` until a wrapper counts
  the armed family (round-4 10-5).** Verified: `deploy/systemd/score-live-trials-run.sh:47` hard-codes
  `FAMILY_MANIFEST="$REPO/deploy/families/pm_us_crh_v2.json"` and passes it at `:125`; the counter
  takes `fetch_start`, `cities` and `manifest_sha256` from that manifest
  (`structural_dead_stop.py:347-349`); `pm_us_crh_v2.json:5` is `"2026-09-05"` against
  `pm_us_crh_v4.json:5`'s `"2026-09-20"`; and the wrapper's own comment at `:40-46` says the
  structural-dead-stop pin "stays v2-scoped only, tracked separately (R-4, SP-1 I5)". `C-KILL`
  therefore evaluates to `INERT` / `NO_CHAMPION_SCOPED_KILL_CLOCK` (§6b.3, §9, C17(g)) and **bars
  `PROPOSAL`** (C14) — never permission, never another family's verdict read as the champion's.
  It becomes evaluable with **no change to this plan** the moment a deployed wrapper invokes
  `structural_dead_stop.py --family-manifest <champion manifest> --output <its own path>`. The repo
  already tracks that question as **PROGRESS R-4** (`docs/core/PROGRESS.md:73`) — whose literal
  `pm_us_crh_cont.json` naming is **SUPERSEDED** (RULING Q4 item 3, `:483-491`): the count must
  follow `sending_family_id` **dynamically**, never a manifest filename baked into the spec text.
  **Owner: AUD-05
  exclusively** (`RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md` Q4 — a
  named increment implementing SP-1 I5) — **cited by id only; this plan asserts nothing about
  AUD-05's content and takes no dependency on its schedule.** **Until it lands `C-KILL` stays
  `INERT`.** This does not block the build: the generator runs, emits all other verdicts, and
  refuses to promote.
- **RULED — strategy lead (was: BLOCKER, score-capping for 10b, rounds 1-6).** Whether R5-7/R5-8
  transfer from the closed forecast family (`FORECAST_EDGE_PEER_REVIEW_2026-09-18.md:121-152`,
  `pm_us_crh_fc_v1`, PREREG v6, CLOSED by `RULING_forecast_edge_programme_closes_2026-09-20.md`) to
  a `continuous_rung_hold` family, and what champion/challenger means at admissible n = 0, is
  **RULED and peer-ENDORSED**:
  `docs/evidence/RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md` Q3
  (Revision 2; trail `docs/evidence/reviews/RULING_citability_review_2026-09-21.md`). They
  **transfer with named adaptations, tagged PROVISIONAL** — `fit_date` → `d0_climate_day`; estimator
  and bootstrap are the existing shared code, unmodified. §6b.3 now pins the adapted text, the
  `STATUS=PROVISIONAL, SOURCE=FORECAST_FAMILY_R5, ADAPTED_BY=…` tag and the lifting condition, so
  10b no longer "transcribes without adapting". **What remains is not authorial:** the criteria stay
  PROVISIONAL until a run with every predicate evaluable exists, and that run needs AUD-05's and
  AUD-19's artefacts.
- **RULED — strategy lead (was: BLOCKER).** Whether a `MECHANISM_ONLY` replay result may contribute
  to any promotion criterion: **no.** The default this plan took is **confirmed unmodified** by
  `RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md` Q2, which additionally
  bars any replay-derived artefact, at **any** validity tag, from ever feeding PREREG v3 §9 —
  permanently, and reversible only by a separate ruling. `C-VALIDITY` stands as written; §6b.3
  records the extension.
- **BLOCKER — operator (named, not designed):** arming, live-trading enablement, and the two
  reserved caps. Nothing in this item reads, writes, or proposes a value for them.
- **Open question (not decided here):** whether a proposal should ever pin `boundary_inputs_sha256`
  itself by minting the artefact. Left to a human deliberately — R5-8 calls the pin *"a blocking
  step, not a by-product"*, and `load_family_manifest` enforces it (`UnpinnedBoundaryArtefactError`,
  `family_manifest.py:155-158,265-269`).

## 13. Review history

**Baseline self-score (2026-09-21, author):** 84/100.

### Round 1

- **trading-bot-architect (promotion-gate/risk-architecture lens): 79/100 · NOT READY**
- **code-architect (module boundaries, data contracts, layering): 69/100 · NOT READY**

| Defect | Reviewer | Disposition |
|---|---|---|
| **MATERIAL P1 / tba MATERIAL** — the two-loop change list does not close REG-1; `:319`, `:328`, `:381` also gate on the constant, and C4 is unattainable | both | **ACCEPTED.** Six occurrences re-derived by grep with a per-site disposition table (§6), including removing the name from the `:45` import; C4 restated as an attainable literal `grep -c … == 0`. Resolved toward the stricter remedy. |
| **MATERIAL P2** — a narrowed manifest can boot with zero strategies | ca | **ACCEPTED, the most important finding of round 1.** Fixed by narrowing the guard's domain via `:319`; **C5/C6** and §7 step 3. Both round-2 reviewers independently re-verified the fix and the hazard at `:444`/`:544`. |
| **MATERIAL P3** — `breezy.analysis` breaks `lint-imports` | ca | **ACCEPTED.** Single decision quoted in §6, identical in AUD-09. (Round 2 found the second contract still unable to pass — see 10-1.) |
| **MINOR p1** — `MIN_NON_EXCLUDED_N` path | ca | **ACCEPTED.** `settlement/roi_bound.py:100`. |
| **MINOR p2** — no manifest writer | ca | **ACCEPTED.** `dump_/write_family_manifest` colocated; **C11**. |
| **MINOR p3** — false directory-collision idempotency | ca | **ACCEPTED.** Content hash + `INPUTS.json`; **C12**. |
| **MINOR p4** — C8 is an expectation, not a test | ca | **ACCEPTED.** Two-way pass condition. |
| **MINOR p5 / tba minor** — line drift | both | **ACCEPTED.** Corrected. |
| **tba informational** — the AUD-08→09→10 "chain" is not a data flow | tba | **ACCEPTED.** H3 real; H2 declined. (Round 2 found the decline still carried a residual read — see 10-2.) |

**Rejections (round 1):** one reviewer *option* — "leave `resolve_station_instrument_ids` wide and
narrow only the two builder loops" — rejected on evidence. Round 2's trading-bot-architect
re-derived that analysis independently from source and confirmed the rejection was correct: leaving
`:319` wide does not merely permit the hazard, it **defeats** the guard, because the guard's domain
is `:319`'s bucket keys. No change.

### Round 2

- **trading-bot-architect (promotion-gate/risk-architecture lens): 91/100 · NOT READY**
- **architect (code-architect lens): 82/100 · NOT READY**

Both reviewers verified every round-1 disposition against the body from fresh greps and found each
fix real and each cited line exact (the six sites, `:444`/`:544`, `:297-300`/`:375-378`,
`settlement/roi_bound.py:100`, the manifest key sets, the `allow_draft=False` refusal). The
trading-bot-architect found **no new MATERIAL defect** and recorded one carried minor (the AUD-09
dependency). Round 3 therefore changes only what the architect's findings require, plus the two
2-point residuals both reviewers named.

| Defect | Reviewer | Disposition |
|---|---|---|
| **MATERIAL 10-1 (= AUD-09 09-1)** — the quoted Nautilus forbidden contract cannot pass; `allow_indirect_imports` defaults to `False` | architect | **ACCEPTED.** Verified at `importlinter/contracts/forbidden.py:72` and `:131-143`, and at `config.py:59-60,76`. **Decided once, identically in both plans: `allow_indirect_imports = true` with the rationale the `.com` contract already carries (pyproject.toml:116-121).** The re-sourcing alternative is **rejected with evidence** (§6): it edits a live strategy module with 8 callers of `SUPPORTED_STATIONS` to satisfy a lint property, inverts the principle the repo's own contract comment states, and collides with 10a, which removes that import from `composition.py` in this same backlog. The residual — an indirect reach still passes — is named, not glossed. `"src/breezy/analysis"` is added to `[tool.mypy] files` in the same change. |
| **MATERIAL 10-2 (= AUD-08 a2)** — H2 is "DECLINED" in three files while `C-STATIONS` records the register's candidate count, which requires reading it; the read has no reader, no version rule and no missing-file rule, and §9's refuse-on-missing-input would make a missing register refuse a proposal | architect | **ACCEPTED, and the reviewer's "absurd, surely unintended" reading is correct.** **Decided once for all three plans: `C-STATIONS` becomes a pure subset predicate with no register read, and the candidate-count clause is DELETED from AUD-10 §6b and AUD-08 §6b.** The bounded-read alternative was considered and rejected: it buys a number in `criteria.json` at the cost of a new cross-item coupling on the *promotion* path, and the thing actually wanted — that a human learns a candidate exists — is better served by a push. AUD-08b now emits a one-shot `BREEZY_STATION_CANDIDATE_NEW` alert instead. H2 is declined **without residue** in all three files. §9's blanket refuse rule is also replaced by the per-predicate absent-input column of §6b.3, since the blanket rule is what made this absurd. |
| **MATERIAL 10-3** — no input artefact is identified per predicate, and `C-PAIRED` has no producer | architect | **ACCEPTED IN FULL.** §6b.3's table gains an **input artefact** column and an **absent-input behaviour** column for every predicate, and **C15** asserts `criteria.json` carries the artefact per row. `C-PAIRED` is resolved the way the reviewer's second option allows and the coordinator required: **declared `INERT`, never `false`** (a `false` reads as "the challenger lost", a different and wrong claim), with `inert_reason="NO_CHALLENGER_REPLAY_PATH"`, the named blocking change (`--family-manifest` on the driver, threading `required_fee_coefficient` into the config at `:932`), an owner, a §12 blocker entry mirrored in AUD-09 §12, and **C14**: a run containing an `INERT` predicate can never emit `PROPOSAL`. Its unit fixture is explicitly labelled synthetic. Additionally, and beyond what was asked: `C-VALIDITY` now refuses any replay row with `params_match=false` (**C16**), closing the *other* half of the same hazard — a row stamped with the armed family's id but produced under `Decimal("0.06")` (`config.py:226`) when that family registers `"0.0695"` (`deploy/families/pm_us_crh_v4.json`). |
| **MINOR c1** — the narrowing's effect on non-`app` callers is not stated | architect | **ACCEPTED.** §6 now enumerates them from a round-3 search: `app/trade.py:48-49,228,271` (the only production caller) and two test modules, `test_no_leg_composition_2026_09_14.py` and `test_current_rung_hold_composition.py`, with line references and the expected effect — none today, because both pass allow-list-shaped mappings; and for any caller that does not, the failure moves from a silent `:328` filter to a loud `UnsupportedStationError`. Added as a §9 failure case and as a step-5 instruction never to restore the filter. |
| **MINOR c2** — `C-ESTIMATOR` leans on `CombinedDraw`/`combine_station_day` signatures the author had not read | architect | **ACCEPTED, and the reading changed the design.** Read and quoted this round: `combine_station_day(rows: Sequence[StratumRow] \| tuple[StratumRow, ...]) -> CombinedDraw` (`settlement/current_rung_hold_v2.py:298`); `CombinedDraw` (`:195-222`) is frozen with exactly `x`, `variance`, `n_constituents`; `score_combined` at `:348`. Two consequences the plan did not previously account for are now stated: **(i)** a `CombinedDraw` carries no station and no climate day, so `C-PAIRED`'s pairing is the caller's bookkeeping, not a property of the draw; **(ii)** `combine_station_day` **raises** on four inadmissible shapes (`:318-319`, `:320-325`, `:269-273`, `:331-336`), each of which the generator must catch and report as `NO_PROPOSAL` rather than let abort the nightly run — **C15**. |
| **MINOR (both reviewers, 2-point residual)** — no alerting independent of the host unit's failed state | both | **NOT TAKEN, with a reason.** 10b emits from inside AUD-09b's wrapper, and AUD-09 §9 records that it inherits G-14's alerting weakness explicitly. Adding a second, item-local alert path here would duplicate the mechanism AUD-08b and AUD-14 already own, for a generator whose expected daily output is `NO_PROPOSAL`. Recorded as a knowingly-accepted residual in the self-score rather than closed. |
| **MINOR (tba)** — 10b's input depends on AUD-09b, which cannot currently execute a real replay | tba | **ACCEPTED as visible sequencing, no change required here** — the reviewer's own assessment. C8 passes on an empty `replay_results.jsonl` by design. AUD-09 §6b.1 now builds the missing `--asos-cache-csv` producer, so the dependency is being closed at its own end. |

**Rejections:** two, both evidenced — the re-sourcing remedy for 10-1 (§6), and the bounded-read
remedy for 10-2 (above). Both were reviewer-offered alternatives, not defects; the defects
themselves are accepted in full. One residual (independent alerting) is knowingly not taken.

**Revision 3 self-score (2026-09-21, author, conservative):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 17 | 10a closes REG-1 across all six sites and closes the hole it would have opened. 10b's criteria set no longer contains a predicate that can only fail for lack of data — but declaring `C-PAIRED` inert is an honest accounting of a gap, not its closure, and G-07's "promotion is a unit-file commit" half is still only partially addressed. |
| Technical correctness and evidence grounding | 20 | 17 | Both round-2 verified errors are corrected against re-read source, and `CombinedDraw`/`combine_station_day` are now read rather than assumed — which changed the design. Residual: the criteria are still transcribed from a peer-review doc whose family is closed (a blocker, not a defect I can fix), and several `composition.py` line numbers are carried from earlier rounds rather than re-read this round. |
| Implementation specificity and feasibility | 15 | 12 | Per-site dispositions, non-`app` caller effects, the serialiser, the layer position, the content-hash scheme, the per-predicate input bindings and `C-ESTIMATOR`'s real input type are all decided. Residual: the block bootstrap's resampling unit and B-count are named by reference to R5-7 rather than pinned here, and the KILL-clock state's on-disk shape is named by producer rather than by path and schema. |
| Acceptance criteria and validation quality | 20 | 17 | C1–C16 objective; C4 attainable; C5/C6 cover the silent-halt class; C8 is two-way; C14/C15/C16 close the round-2 gaps. Residual: no criterion exercises a real multi-day promotion decision, which only time can supply, and `C-PAIRED`'s only test is synthetic by construction and says so. |
| Autonomous operation, failure handling, recovery | 15 | 12 | Three hard refusals, per-predicate absent-input behaviour replacing a blanket rule that produced an absurd outcome, the four `combine_station_day` refusals handled, contradiction ordering, content-hash idempotency, read-only posture. Residual: no alerting independent of the host unit's failed state — knowingly not taken (above). |
| Portfolio objective alignment, scope and dependencies | 10 | 9 | Zero-ROI honesty, correctness benefit named as such, both strategy-lead blockers kept verbatim, the new build blocker named with an owner and mirrored in AUD-09, H2 declined without residue, arming/caps/NO-SEND untouched. |
| **Total** | **100** | **84** | |

### Round 3

- **trading-bot-architect (autonomous-loop/pipeline lens): 100/100 · READY**
- **architect (code-architect lens): 87/100 · NOT READY**

**Readiness is the LOWER of the two: 87.** The 100 is recorded but not relied on: it found none of
the three defects below — including one (a stale KILL clock reading as permissive) that is a safety
property, not a documentation nicety. A perfect score that misses a silently-permissive gate is not
evidence of readiness.

Both reviewers confirmed every round-2 fix is real (the `allow_indirect_imports = true` contract
character-equal to AUD-09's, H2 declined without residue across all three plans, the per-predicate
input/absent-input columns, `C-PAIRED` as literal `INERT` with `inert_reason` and C14, the
`C-VALIDITY` `params_match` clause, the non-`app` caller enumeration, and the `CombinedDraw` /
`combine_station_day` / `score_combined` signatures that changed the design). 10a's six-site
enumeration was re-verified once more and found exact and complete. Revision 4 therefore changes
only the passages below.

| Defect | Reviewer | Disposition |
|---|---|---|
| **MATERIAL 10-4** — `C-KILL`'s input is named only by its producing script: no path, no key set, no reader, no staleness rule — while its absence refuses the whole run, so the generator's steady-state outcome was undetermined and a **stale** clock would read "not tripped", silently permissive. The same under-binding applies at lower stakes to `C-ESTIMATOR`/`C-N` | architect | **ACCEPTED IN FULL, and the artefact was found rather than assumed.** §6b.3 gains a full **`C-KILL` binding table**. The deployed writer is `deploy/systemd/score-live-trials-run.sh:118-127` under `breezy-score-live-trials.service` (`OnCalendar=*-*-* 14:15:00 UTC`, `Persistent=true`), which `rm -f`s and then rewrites `${BREEZY_LIVE_TALLY_OUTPUT_DIR:-~/.local/share/breezy/derived}/covered_listed_station_days_<UTC-day>.json` via `structural_dead_stop.py --output`, **exiting 1 if the counter fails** — so absent unambiguously means "the counter did not succeed today". Six keys, atomic `mkstemp`+`os.replace` (`_write_output_json:297-326`), contract pinned at `:189,289`. The predicate reads `count`, `fetch_start`, `stations`, `manifest_sha256`, `depth_root_present`. The **second** input, `filled_takes`, is read by `count_filled_takes` (`fill_time_count.py:101-118`) from `$POLYMARKET_US_EXEC_STATE_DB` **read-only**, with `family_prefix=manifest.trial_id_prefix` and `since_climate_day=manifest.d0_climate_day` — the identical call `family_tally_v2.py:1290-1297` makes under `family-tally-v2-run.sh:215-219`. The verdict is the shipped `structural_dead()` (`structural_dead_stop.py:110-130`), never re-implemented. **MAX-AGE: `KILL_CLOCK_MAX_AGE_SECONDS = 26*3600`** (24 h cadence plus `Persistent=true` catch-up, and nothing longer); **stale ⇒ refuse the run, identically to absent**, with an enumerated `refusal_reason`. A provenance rule (`fetch_start == d0_climate_day`, `stations ⊆ manifest.stations`) mirrors the drift guards the deployed wrappers already apply to this same file (`score-live-trials-run.sh:152-160`, `family-tally-v2-run.sh:203-205`). **And the permissive trap is closed explicitly:** `count_filled_takes` returns `None` — fail closed, never zero — so `structural_dead` sets `evaluable=False` **and `structural_dead=False`**; that `False` means *unknown*, not *clear*, so `C-KILL` refuses on `evaluable is False` and never reads `structural_dead` without first asserting `evaluable`. New criterion **C17** with six fixtures, one per arm. **Honest residual, stated rather than papered over as the reviewer instructed:** *no deployed unit writes a machine-readable KILL verdict* — `family_tally_v2` computes `StructuralDeadVerdict` at `:673-680` but renders it only into markdown (`render_markdown_v2:1025`, written `:1327-1329`), and `--output` has no JSON form. This plan therefore **re-derives** the verdict from the two machine-readable inputs, pins the equality in C17, and records the dependency in §12 (if a later item publishes a machine-readable tally verdict, `C-KILL` reads that and the re-derivation is dropped). `C-ESTIMATOR`/`C-N` now name **artefacts, not producers**: the store directory `${BREEZY_SCORED_TRIALS_DIR:-~/.local/share/breezy/derived/scored_trials}/<family_id>/` (`score-live-trials-run.sh:54`, one subdir per family under L-38), its `scored_trials_*.parquet` run files, and the sidecars inside it (`provenance.json`, `fill_order.jsonl`, `excluded_fills.jsonl`, `unresolved_takes.jsonl`), read through `load_realized_draws(store_dir)` (`realized_draws.py:249`). |
| **MINOR c1** — "four documented refusals" under-counts the reachable refusals by three | architect | **ACCEPTED, and the reviewer's count is exactly right.** Re-read `current_rung_hold_v2.py`: `_fold_same_rung_rows` raises `StationDayAdmissionRefusal` at three further distinct shapes — same-rung same-side fills at differing `entry_ask` (`:275-280`), at differing `fee` (`:281-286`), and disagreeing on `held` (`:287-292`) — beyond the four the docstring lists. §6b.3 now enumerates all **seven** and, following the reviewer's second option, **states the base-class catch as the contract**: `StationDayAdmissionRefusal(ValueError)` at `:184` is the parent of `_MixedDayMissingRungKeyRefusal` (`:230`) and `_SameRungOppositeSidesRefusal` (`:237`), so `except (StationDayAdmissionRefusal, ValueError)` covers all seven and any eighth a future change adds. **C15 is restated over all seven shapes** and additionally pins `StationDayAdmissionRefusal.__bases__`, so the catch cannot silently stop covering a subclass; §7 step 10 requires seven fixtures; §9's refusal line is corrected from four to seven. |
| **MINOR c2** — the §10 boot-log line has no acceptance criterion while every other observable in the plan does | architect | **ACCEPTED.** New criterion **C18**: the composition boot log states the composed station set **and** the manifest's `family_id`, asserted against captured log text in the **C3 golden composition test** rather than as a standalone test — the cheapest true home for it, since that test already composes the live `pm_us_crh_v4` manifest. §7 step 4 and §10 both updated to point at C18. |

**Rejections:** none in round 3. The two round-2 rejections (the re-sourcing remedy for 10-1, the
bounded-read remedy for 10-2) stand, both evidenced, and both were reviewer-offered alternatives
rather than defects. One residual — alerting independent of the host unit — is still knowingly not
taken and is recorded as such.

**Revision 4 self-score (2026-09-21, author, conservative):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 17 | 10a closes REG-1 across all six sites and closes the zero-strategy boot path it would have opened. 10b now binds **all eight** predicates to real artefacts, which was the round-3 deduction. Not higher: G-07's "promotion is a unit-file commit" half remains only partially addressed — the proposal is inert by design and four human acts still stand between it and an armed family. |
| Technical correctness and evidence grounding | 20 | 18 | The KILL artefact was located in deployment and read (`score-live-trials-run.sh:54,118-127,152-160`; `breezy-score-live-trials.timer`; `structural_dead_stop.py:110-130,189,289,297-326`; `fill_time_count.py:101-118`; `family_tally_v2.py:160,380,673-680,838,1025,1290-1297,1327-1329`; `family-tally-v2-run.sh:203-205,215-219`; `realized_draws.py:83,249`; `scored_trial_store.py:89-104,118`), and the refusal set was re-read and corrected from four to seven (`current_rung_hold_v2.py:184,230,237,269-292,318-336`). Not 20: the markdown-only KILL verdict means the plan re-derives rather than reads the authoritative number, which C17 pins but does not eliminate. |
| Implementation specificity and feasibility | 15 | 13 | The input that decides whether the generator runs at all is now specified to the path, the key set, the reader, the constant and the refusal-reason alphabet. Not 15: `KILL_CLOCK_MAX_AGE_SECONDS`'s home module is named by behaviour rather than by file, and the block-bootstrap resample count inside `C-ESTIMATOR` is still unstated. |
| Acceptance criteria and validation quality | 20 | 18 | C17's six arms make the stale-and-permissive case a test rather than a hope; C15 covers all seven refusal shapes plus the class hierarchy that makes the base catch valid; C18 pins the last unpinned observable. Not 20: C8's "one real run" is still expected to return `NO_PROPOSAL`, so most of the generator's `PROPOSAL` path is exercised only by fixtures. |
| Autonomous operation, failure handling, recovery | 15 | 13 | A stale or unevaluable clock now refuses instead of reading as permission — the round-3 deduction closed. Not 15: there is still no alerting independent of the host unit, so a nightly refusal is visible only in the unit's state and the log (knowingly not taken, §12). |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | The round-3 reviewer found no defect here. Zero-ROI honesty; the correctness benefit named as correctness, not return; both strategy-lead blockers retained verbatim; abandonment criterion scoped to 10b; arming, the two operator-reserved caps and the NO-SEND path untouched — and the new KILL binding is **read-only** on both artefacts (`count_filled_takes` opens the exec-state DB read-only). |
| **Total** | **100** | **89** | |

### Round 4

- **trading-bot-architect (promotion-gate/risk-architecture lens): 100/100 · READY**
- **architect (code-architect lens): 90/100 · NOT READY**

**Readiness is the LOWER of the two: 90.** For the **second consecutive round** the
trading-bot-architect returned a perfect score while finding none of the architect's defects — and
for the second consecutive round the missed defect is a *gate* defect, the lens's own subject
matter (round 3: a stale clock reading as permissive; round 4: a KILL clock scoped to the wrong
family, which would have refused every night AND mixed two families' scopes in one verdict). Its
round-4 record explicitly praises the very `C-KILL` binding that 10-5 shows is unsatisfiable against
deployment. The 100 is recorded, not relied on; both findings were re-verified at source by me
before acceptance.

Both reviewers confirmed every round-3 fix is real and exact: the `C-KILL` artefact with its six
keys and atomic write, `count_filled_takes`'s `None`-fail-closed docstring, `structural_dead`'s
`evaluable` semantics, the store **directory** replacing a producing script for
`C-ESTIMATOR`/`C-N`, the seven refusal shapes with the base-class catch and the `__bases__` pin, and
C18's boot-log pin. 10a was re-verified once more across all six sites and found exact. Revision 5
therefore changes **only** the passages named below.

| Defect | Reviewer | Disposition |
|---|---|---|
| **MATERIAL 10-5** — `C-KILL`'s provenance rule binds the clock to the **champion** manifest, but the deployed counter JSON is produced under a hard-coded, different family. As written the generator refuses every run forever (contradicting C8 and making C17(a) unconstructable), and the re-derived verdict mixes a v2-scoped covered-days count with a v4-scoped fill count — the "statistic attached to the wrong family" error this item exists to prevent. The cited `:152-160` "mirror" compares to a hard-coded v1 literal, not a manifest | architect | **ACCEPTED IN FULL, and independently re-verified at every cited line.** `score-live-trials-run.sh:47` hard-codes `FAMILY_MANIFEST=…/pm_us_crh_v2.json` (passed at `:125`); `structural_dead_stop.py:347-349` takes `fetch_start`, `cities` **and** `manifest_sha256` from that manifest; `pm_us_crh_v2.json:5` = `2026-09-05` vs `pm_us_crh_v4.json:5` = `2026-09-20`; and the wrapper's own comment at `:40-46` states the pin "stays v2-scoped only, tracked separately (R-4, SP-1 I5)". The `:152-160` claim is **withdrawn**: `:152` extracts `FETCH_START` and `:157` compares it to `V1_D0_LITERAL="2026-09-05"` (`:62`) — the PREREG v1 D0 literal, not any manifest's `d0_climate_day`. **Resolution: option (c).** A new **champion-scope rule**, evaluated FIRST, compares the file's `manifest_sha256` against the champion manifest's (`family_manifest.py:185,220`; written at `structural_dead_stop.py:349`); unequal ⇒ `C-KILL` = literal **`INERT`** with `inert_reason="NO_CHAMPION_SCOPED_KILL_CLOCK"`, mirroring the `C-PAIRED` treatment this plan already carries, and — by **C14**, which already generalises — **no run containing an `INERT` predicate can emit `PROPOSAL`**. A missing champion-scoped clock is therefore never permissive; it is a standing bar that states why. Options **(a)** and **(b)** are rejected **on evidence, in the plan body**: (a) admitting a v2-scoped verdict as the champion's is the wrong-family error itself, and as a *permission* rather than a bar; (b) computing a champion-scoped counter inside AUD-09b's wrapper is an unbounded-window catalog scan in a cgroup sized `MemoryHigh=3G`/`MemoryMax=4G` for a single-day replay, and stands up a second KILL clock the round-3 binding expressly refused. **C8 and C17(a) are now mutually reachable against the deployed artefacts:** C8's expected steady state records `C-KILL` `INERT` alongside `C-PAIRED`, and C17(a)'s happy path is explicitly a fixture generated by `structural_dead_stop.py --family-manifest <champion>`. **C17 gains a seventh arm (g)** asserting the counter's manifest identity *and the evaluation order* (a v2-scoped file that is also stale still reports `INERT`, not `KILL_CLOCK_STALE`). The owned dependency — a deployed wrapper counting the armed family — is named in §6b.3 and §12 with an owner, citing **PROGRESS R-4** (`docs/core/PROGRESS.md:73`) and **AUD-05 by id only**. §9 gains the case. |
| **MATERIAL 10-6 (= AUD-09 09-5)** — the emission site contradicts AUD-09's revision-4 wrapper contract: §6b.4/§10/§7 step 13 append a third `"$PY"` invocation to a wrapper AUD-09 **B18** pins at exactly two | architect (both plans) | **ACCEPTED IN FULL; the count is the wrong invariant and both plans now say so in character-identical words.** §6b.4 states the coupling explicitly, cites AUD-09 **B18**, and names `scripts/analysis/promotion_proposal.py` as the **sanctioned third invocation**; §10's deploy line says the same. AUD-09 restates B18 as a **property over a named script set** (census, runner module, and — once AUD-10b lands — `promotion_proposal.py`; no JSONL parsing, no `record_blocked`), names this line in its §5 as an expected, owned later addition, and updates its §7 step 10 wording. From **this** side, new criterion **C19** asserts the identical property plus the lock and the ordering, and §7 step 13 becomes RED-then-GREEN with C19 as the RED — deliberately duplicated so neither item can land a wrapper edit that silently breaks the other's criterion. |
| **MINOR c1** — two line ranges drift | architect | **ACCEPTED, both re-read this round.** `score-live-trials-run.sh:118-127` → **`:115-129`**, and the range is now broken out by role (`CJSON` at `:115`, `rm -f` at `:122`, the invocation at `:123-126`, the `exit 1` at `:127-129`). `structural_dead_stop.py:110-130` → **`:111-132`**. `_write_output_json`'s range is also corrected from `:297-326` to `:297-330`. The round-3 disposition row below is left **verbatim as the historical record it is**; the corrections are made in the live §6b.3 and §12 text, which is what an implementer reads. |

**Rejections:** none in round 4. The two round-2 rejections stand. Two reviewer-offered
*alternatives* for 10-5 — (a) v2-scoped provenance, (b) self-computed counter — are rejected with
the reasons recorded in §6b.3, which is the reviewer's own "choose ONE and specify it fully".
One residual (alerting independent of the host unit) is still knowingly not taken, §12.

**Revision 5 self-score (2026-09-21, author, conservative):**

| Criterion | Max | Score | Remaining weakness |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 18 | 10a closes REG-1 across all six sites and closes the zero-strategy boot path it would have opened; 10b's generator now has a **reachable** steady state on today's tree (`NO_PROPOSAL` with two `INERT` predicates), which was the round-4 deduction. Not higher: G-07's "promotion is a unit-file commit" half is a human gate by design, and 10b's central predicate is inert for want of an artefact another owner must produce — honest accounting of a gap, not its closure. |
| Technical correctness and evidence grounding | 20 | 19 | The family-scope defect was re-verified line by line (`score-live-trials-run.sh:40-46,47,62,115-129,125,152,157`; `structural_dead_stop.py:111-132,297-330,347-349`; `pm_us_crh_v2.json:5`; `pm_us_crh_v4.json:5`; `family_manifest.py:185,220`), the false `:152-160` "mirror" is withdrawn rather than reworded, and both c1 ranges are corrected. Not 20: the markdown-only KILL verdict means the plan still re-derives rather than reads the authoritative number, which C17 pins but does not eliminate. |
| Implementation specificity and feasibility | 15 | 14 | The implementer now has the evaluation **order**, the identity key, the `INERT` verdict and its `inert_reason`, the rejected alternatives with their reasons, and a fixture recipe (`--family-manifest` against v4 and v2) for both the happy and the inert arm. Not 15: `KILL_CLOCK_MAX_AGE_SECONDS`'s home module is still named by behaviour rather than by file, and the block-bootstrap resample count inside `C-ESTIMATOR` is still unstated. |
| Acceptance criteria and validation quality | 20 | 19 | C17's seventh arm pins the manifest identity *and* the ordering; C8 is reachable against deployment for the first time; C19 tests the cross-item wrapper coupling from this side. Not 20: C8's "one real run" is still expected to return `NO_PROPOSAL`, so most of the `PROPOSAL` path is exercised only by fixtures — and with `C-KILL` inert, the happy path of the plan's most safety-critical predicate is fixture-only too. |
| Autonomous operation, failure handling, recovery | 15 | 14 | The nightly steady state is no longer a refusal indistinguishable from a real provenance drift: the generator runs, emits every verdict, and bars promotion through a *named* inert state — so the one signal that matters is no longer saturated (the round-4 deduction). Not 15: there is still no alerting independent of the host unit, so a genuine `KILL_CLOCK_STALE` refusal is visible only in the unit's state and the log (knowingly not taken, §12). |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | No reviewer has found a defect here since round 2. Zero-ROI honesty; the correctness benefit named as correctness; both strategy-lead blockers retained verbatim; the new KILL-scope dependency named with an owner and citing PROGRESS R-4 / AUD-05 **by id only**; the wrapper coupling owned jointly and tested from both sides; arming, the two reserved caps and the NO-SEND path untouched, and the KILL binding read-only on both artefacts. |
| **Total** | **100** | **94** | |

### Round 5

- **trading-bot-architect (promotion-gate/risk-architecture lens): 100/100 · READY**
- **architect (code-architect lens): 96/100 · NOT READY**

**Readiness is the LOWER of the two: 96.** For the **third consecutive round** the
trading-bot-architect returned a perfect score while finding none of the architect's defects. Both
reviewers verified every round-4 disposition at source: the champion-scope rule evaluated **first**
on `manifest_sha256` (`family_manifest.py:185,220`; `structural_dead_stop.py:347-349`), the literal
`INERT` / `NO_CHAMPION_SCOPED_KILL_CLOCK` outcome that C14 turns into a standing bar, the withdrawn
`:152-160` "mirror" claim, C17's seventh arm with its ordering assertion and its deployment-generated
fixtures, C8 reachable on today's tree, C19, and all three corrected line ranges. The architect's
round-5 verdict on the coordinator's question was that the `INERT` steady state is stated honestly in
§4, §6b.3, C8, C14, C17(g), §9 and §12 — **but not in §11**. Revision 6 changes **only** §11 and one
line of §6b.4.

| Defect | Reviewer | Disposition |
|---|---|---|
| **MATERIAL 10-7** — §11 was never revised alongside the `INERT` decision, so the one section that states this item's value and its retirement rule misdescribes its reachable outcomes: (1) the `NO_PROPOSAL` reason list omits `C-KILL` `INERT` and "evaluated by C1–C16" is stale against C17–C19; (2) the **conjunction** of the two dependencies — "until then this is a refusal engine, not a promotion path" — is never stated in one place; (3) the abandonment criterion would fire for an upstream cause, because while `PROPOSAL` is unreachable every human promotion is an override **by construction**, so the rule mechanically retires a **correct** gate after two decisions | architect | **ACCEPTED IN FULL, all three parts; no design change, §11 catching up with §4/§6b.3/C8/C14/C17(g)/§9/§12 in their own terms.** (1) The opening paragraph now records **both** `INERT`s with their literal `inert_reason`s and the deployed cause (`score-live-trials-run.sh:47`), pointing at C8, C17(g) and §12; "C1–C16" → **C1–C19**, matching the evidence-artefact line. (2) A new paragraph states the **compound limit** once: `PROPOSAL` is unreachable until **both** externally-owned dependencies land — the champion-scoped KILL clock (owner: the live-tally / `score-live-trials` owner; **PROGRESS R-4**, `docs/core/PROGRESS.md:73`; **AUD-05 by id only**) and `--family-manifest` on the replay driver (owner as already named in §12) — both out of scope, both evaluable with no change to this plan, and **until then the deliverable is a machine-checked REFUSAL WITH REASONS, not a working promotion path**. (3) The abandonment criterion is **re-gated**: it counts only promotion decisions on which **every predicate was evaluable (no `INERT` in the run)**, with the override-by-construction reasoning stated so the gate is never retired for a missing upstream unit. |
| **MINOR c1 (= AUD-09 b1)** — the "character-identical in AUD-09 §6b.3" claim does not hold for the paragraph, only for the bolded property sentence; a self-identity claim that fails a literal diff devalues the plans' own drift-detection mechanism | architect (both plans) | **ACCEPTED, taking the reviewer's first option.** §6b.4's heading is **scoped to the property sentence**: *the bolded property sentence below is character-identical in AUD-09 §6b.3 — the lead-in and closing around it are not, and are not claimed to be*. **The property sentence itself is unchanged**, and was re-compared literally against AUD-09 §6b.3 before and after this edit; AUD-09 carries the mirrored edit. Making the paragraphs wholly identical was declined: the sentence is the binding, and each plan's lead-in correctly addresses its own side of the coupling. |

**Rejections:** none in round 5. The two round-2 rejections stand. One reviewer-offered *alternative*
for c1 (make the paragraphs identical) is declined in favour of the reviewer's own first option. The
residual — alerting independent of the host unit — is still knowingly not taken, §12.

**Revision 6 self-score (2026-09-21, author, conservative):** **94/100**, deliberately unchanged from
revision 5 (18 / 19 / 14 / 19 / 14 / 10). 10-7 and c1 were accuracy defects in the plan's own prose,
and closing them removes the reviewer's three deductions — but not one of the residuals behind my own
lower marks: G-07's "promotion is a unit-file commit" half is still a human gate by design; the
markdown-only KILL verdict means C-KILL still **re-derives** rather than reads the authoritative
number; `KILL_CLOCK_MAX_AGE_SECONDS`'s home module and `C-ESTIMATOR`'s block-bootstrap resample count
are still unpinned; C8's real run still returns `NO_PROPOSAL`, so the `PROPOSAL` path and `C-KILL`'s
happy path are fixture-only; and there is still no alerting independent of the host unit. §11 is now
honest about the compound limit — which is a correction, not an improvement in what the item can do.

### Round 8 — ruling intake (no peer review this round; nothing implemented)

| Change | Authority | Disposition |
|---|---|---|
| **Both strategy-lead blockers RULED and peer-ENDORSED** | `docs/evidence/RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md` (Revision 2; trail `docs/evidence/reviews/RULING_citability_review_2026-09-21.md`) | **APPLIED in §6b.3 and §12.** **Q3:** R5-7/R5-8 **transfer with named adaptations, tagged PROVISIONAL** — the `SOURCE=FORECAST_FAMILY_R5` *"transcribed, not adapted"* framing is replaced by the adapted text pinned as the ruling gives it (`fit_date` → `d0_climate_day`; estimator/bootstrap = the existing shared code), plus the lifting condition (first run with **no `INERT` anywhere**) and the mandatory `criteria.json` / `RATIONALE.md` tag. Champion/challenger at n = 0 is ruled; `C14` unchanged. **Q2:** `MECHANISM_ONLY` never feeds a criterion — confirms `C-VALIDITY`'s default **unmodified**, and extends the bar to PREREG v3 §9 permanently. |
| **The `C-ESTIMATOR` resample-count residual** (carried and accepted since revision 4) | same ruling, Q3 | **CLOSED.** Pinned to the shipped call — `B_RESAMPLES = 10_000` (`roi_bound.py:93`), `SEED = 20260904` (`:97`), `random_state=np.random.default_rng(SEED)`, call at `:214-224` — and RED-tested by new criterion **C20** (§7 step 10). The ruling's own `:213-222` range is corrected ±1 against source in §6b.3; its substance is unchanged. |
| **The two externally-owned dependencies gain single named owners** | same ruling, Q4 | **APPLIED, by id only, in §4, §5, §6b.3, §11 and §12.** Champion-scoped KILL clock → **AUD-05** (a named increment implementing SP-1 I5). `--family-manifest` on the replay driver → **AUD-19**, gated on the replay-`trial_id` provenance fix. **`C-KILL` and `C-PAIRED` remain `INERT` and `C14` still bars `PROPOSAL`** — round 8 named the owners, it did not produce the artefacts. |
| **A halted / may-not-send champion** | `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`; tally scope in `docs/evidence/RULING_live_family_tally_scope_2026-09-21.md` | **RECORDED in §9.** Output is unchanged — **still `NO_PROPOSAL`** — for reasons independent of the halt: a halted champion accrues no new live fills so `C-N` fails at n = 0, `C-VALIDITY` bars any replay-derived edge statistic, and both `INERT`s bar `PROPOSAL` under `C14`. A re-arm is a **new registration**, so the halt is never a reason to promote around the champion. |

**Round-8 effect on the score: none claimed.** Two blockers moving from *open* to *ruled* removes a
score **cap**, not a defect, and the resample pin closes exactly one named residual. Every other
revision-6 residual stands and still holds the marks down: G-07's "promotion is a unit-file commit"
half is a human gate by design; `C-KILL` still **re-derives** rather than reads an authoritative
verdict; `KILL_CLOCK_MAX_AGE_SECONDS`'s home module is still unpinned; C8's real run still returns
`NO_PROPOSAL`, so the `PROPOSAL` path and `C-KILL`'s happy path remain fixture-only; and there is
still no alerting independent of the host unit.

### Round 9 — peer-review intake (two delta reviews; nothing implemented)

| Change | Authority | Disposition |
|---|---|---|
| **MATERIAL — the PROVISIONAL lifting condition did not say whether the triggering (first no-`INERT`) run's OWN artefact stays tagged, so a first-ever `PROPOSAL` could read as settled authority** | `reviews/AUD-10-r8-trading-bot-architect.md` (defect 1), against `RULING_replay_evidence_citability_and_promotion_criteria_2026-09-21.md:405-412` | **ACCEPTED, resolved conservatively in §6b.3.** The generator **never** lifts its own tag: the ruling's no-`INERT` condition is necessary but not self-certifying, so **every** artefact emitted while the criteria are PROVISIONAL — `criteria.json`, `RATIONALE.md`, any `PROPOSAL` — carries `criteria_status: "PROVISIONAL"`, **including the run that first has no `INERT` predicate**. Lifting happens only through a separate ruling artefact under `docs/evidence/`, read **by pinned path + sha256**; absent/unreadable/mismatched ⇒ PROVISIONAL. A PROVISIONAL `PROPOSAL` is advisory input to the human unit-file promotion commit (§11), never an auto-promotion; `C14` unchanged. **C20** gains three REDs (first-no-`INERT` run still tagged; lift only with the pinned ruling; tampered/missing ⇒ PROVISIONAL) — extended in place, no renumbering. |
| **MINOR — §9's halted-champion reason (i) overclaimed the halt's enforcement** | same review (defect 2), against `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md:3`, `:273-278` | **ACCEPTED, text-only.** §9 now states the champion is **RULED** not to send but the halt is **UNENFORCED until AUD-02b lands**, quoting the ruling's own present-tense disclaimer; reason (i) is re-grounded on the enforcement-independent fact (zero decisions reach pricing — the accidental Gate 1/Gate 2 by-product, `:276-277`, `:337-343`), and the bullet now states that (i) `C-N` at n = 0, (ii) `C-VALIDITY` and (iii) both `INERT`s under `C14` are **each independently sufficient** for `NO_PROPOSAL`. No test, criterion, or design change. |
| **MINOR 10-9 — R-4 cited bare, carrying a superseded literal** | `reviews/AUD-10-r8-architect.md` (defect 10-9), against `RULING_…citability…:483-491` and `docs/core/PROGRESS.md:73` | **ACCEPTED in both places (§6b.3's R-4 quotation and §12's KILL-clock bullet).** R-4's literal `--family-manifest pm_us_crh_cont.json` naming is recorded as **SUPERSEDED** (`pm_us_crh_cont` retired, `terminal_climate_day: "2026-09-19"`): the count must follow `sending_family_id` dynamically, never a manifest filename baked into spec text. Ownership text (AUD-05 exclusively, by id only) unchanged. |

**Round-9 effect on the score: none claimed** — two text-accuracy defects and one specification gap
closed; no new capability, and nothing implemented. §6b.4's property sentence (mirrored in AUD-09) and
**C19**'s three-script set are byte-unchanged.

**Latest score:** 94 (revision 6 self-score, deliberately unchanged by the round-8 ruling intake;
round-5 peer scores 100 / 96; round-4 100 / 90; round-3 100 / 87; round-2 91 / 82; round-1 79 / 69).

**Readiness: NOT READY.** What remains open is no longer authorial — both strategy-lead blockers are
ruled and closed — but it is real: `C-KILL` is `INERT` until **AUD-05**'s champion-scoped clock
lands and `C-PAIRED` is `INERT` until **AUD-19**'s driver flag does, so **no run can emit
`PROPOSAL`**, and the adapted R5 criteria stay **PROVISIONAL** until a run with no `INERT` anywhere
exists. **AUD-10a (REG-1) is buildable now and depends on none of that.** Round-8 delta review
pending; nothing in this plan has been implemented.


<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-22) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `400aea7a33a1116849222aab4d38c18ad722a89814a674a06972982b9b1aa6fa`
- **Baseline self-score:** 84/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `architect` round 10: 100/100 — `reviews/AUD-10-r10-architect.md`
  - `trading-bot-architect` round 10: 100/100 — `reviews/AUD-10-r10-trading-bot-architect.md`
- **Readiness:** **READY**
- **Unresolved blockers / notes:**
  - None on buildability. 10a (REG-1) and the 10b generator are buildable now.
  - Stated limit, not a blocker: until AUD-05's champion-scoped KILL clock and AUD-19's driver flag land, `C-KILL` and `C-PAIRED` are INERT and the only possible output is a machine-checked `NO_PROPOSAL`. Adapted criteria stay PROVISIONAL until a separate lifting ruling exists.
- **Full review history:** 20 records, `reviews/AUD-10-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
