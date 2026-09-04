# FAMILY_TALLY_V2_BLUEPRINT_2026-09-04 — Rev 2

Status: REVISED after two adversarial reviews and the strategy-lead score-statistic ruling; pending convergence check. Implements plan S2+S3 with v1 byte-unmodified.

## Blueprint — PREREG v2 / Kalshi sibling tally (plan S2+S3) — Rev 2

Supersedes Rev 1. Incorporates `docs/evidence/grok_v2_score_statistic_ruling_2026-09-04.md` (statistic C, truncation D, venue-stratum reject E, D0 discriminant F), read in full, plus both REVISE reviews.

### Design decisions (evidence-cited)
- **The interim statistic is a per-row centred score, not a plug-in z.** Rev 1's `z_score(k,n,π)` re-estimated `π_k=mean(BE_i)` at every look and used `n·π(1−π)` as variance — an independent-increments claim that is false (ruling: "`x(1−x)` concave ⇒ `nπ(1−π) ≥ Σ BE(1−BE)`"). Under H0 `held_i | ask_i ~ Bern(BE_i)` with `BE_i` **known** (`decision.py:298`; `fee` on `ScoredTrial`, `trial_scorer.py:138`), so the numerator `Σ(held_i−BE_i)` does have independent increments. Rev 2 uses `S = Σ(held_i−BE_i)/sqrt(I)`, `I = Σ BE_i(1−BE_i)`, `t = min(1, I/I_max)`, `I_max = 40 = 160×¼` (Bernoulli bound, pinned in the generator's input sha256 before the first fill — never a live/archive/look-1 estimate).
- **Boundaries are solved at realized `t`, not looked up at equal `n`.** Looks still fire every 10 filled Takes, but `t` is information-based and unequal, so the generator emits a *spending function of t* + solver inputs + a 16-row equal-t **reference fixture** (regression only, never the live path). Persistence loads/wraps it as `boundary_for(t_history) -> (b_eff, b_fut)`.
- **`mean(BE_i)` stays, but only where ruled:** stratum `π = mean(BE_i)` for the fixed-rule `cell_dead` at n≥60 on station/ask-band (ratification (1)(d)); the sequential score never uses it.
- **`venue:` stratum REMOVED** (ruling E). Strata = pooled | station | ask-band only. Families are single-venue and never pooled, so `venue:*` ≡ pooled — an unregistered axis buying nothing. Venue lives in the manifest + trial-id prefix (`Kalshi §0:17`); a `venue` column on `ScoredTrial` is forbidden (17-column schema, `scored_trial_store.py:53-72`).
- **v1 is untouched by construction.** No import of, edit to, or branch in `live_family_tally.py` / `mb_current_rung_edge_study.py`.
- **No `src/` → `scripts/` import.** `settlement/current_rung_hold_v2.py` inlines the ~3-line Wilson-score arithmetic for `cell_dead`, citing `scripts/analysis/archive_correction_probe.py:352-363` and `Z_95 = 1.959963984540054` as the reference. Importing a script from a package would invert the layer graph and is untested-for.
- **Split pure math from I/O.** `src/breezy/settlement/` is AST-pure (`test_settlement_purity_guard.py`: no `open`/`print`/`os`/`pathlib`), so score/strata/verdict math lands there beside `roi_bound.py`; the boundary-artefact loader and manifest loader (file read + sha256) land in `persistence/`, which the layer contract already places above `settlement` — the direction `scored_trial_store.py` already uses.
- **Script placement stays `scripts/analysis/`.** The timer never imports Python (`breezy-live-tally.service` → `live-tally-run.sh` → `.venv/bin/python scripts/analysis/live_family_tally.py`), and import-linter roots are `breezy`/`nautilus_trader` only. Nothing forces package placement.
- **Family provenance: trial-id prefix + declared manifest, no dataclass/schema change.** Prefix separates venues (a new Kalshi latch freely picks `kalshi/current_rung_hold/trial/`); it cannot separate PM-v1 from PM-v2, which share `current_rung_hold/trial/` on the same latch. The manifest's registered `d0_climate_day` is the second discriminant, committed before the first fill (cost-free at n=0), never retroactive. Rejected: a `ScoredTrialV2` wrapper (still needs an external truth source — relocates the problem); rejected: a new field (ruling (e)(i), and E forbids it explicitly).

### Files to create
| File | Purpose |
|---|---|
| `src/breezy/settlement/current_rung_hold_v2.py` | PURE: `BE_i`, `score()`, `StratumV2`/`cell_dead` (inlined Wilson), `look_verdict`, `terminal_look` |
| `src/breezy/persistence/gs_boundary_artefact.py` | Load + sha256-pin-check the generator artefact; expose `boundary_for` and `alpha_spent_at` |
| `src/breezy/persistence/family_manifest.py` | Load/validate the family manifest |
| `scripts/analysis/family_tally_v2.py` | CLI sibling of `live_family_tally.py`: barrier, strata, look/terminal verdict, terminal BCa, markdown |
| `deploy/families/{pm_us_crh_v2,kalshi_crh_v1}.json` | Per-family manifests (data, not code) |
| `deploy/systemd/family-tally-v2-run.sh` | Wrapper mirroring `live-tally-run.sh`; family id as `$1` |
| `deploy/systemd/breezy-pm-crh-v2-tally.{service,timer}` | Concrete pair, `OnCalendar=*-*-* 15:30:00 UTC` |
| `deploy/systemd/breezy-kalshi-crh-tally.{service,timer}` | Concrete pair, `OnCalendar=*-*-* 16:30:00 UTC` |
| `tests/fixtures/prereg_v2/boundary_reference_16.json` | Generator's equal-t reference fixture (regression only) |
| `tests/unit/test_prereg_v1_is_byte_unmodified.py` | Ruling (3) AST source-text pin |
| `tests/unit/test_current_rung_hold_v2_score.py`, `…_strata.py`, `test_gs_boundary_artefact.py`, `test_family_manifest.py`, `test_family_tally_v2.py`, `test_family_tally_v2_truncation.py` | RED-first suites |

**No templated systemd unit** (Rev 1 defect): the repo has no `@.service` precedent, and one template `.timer` cannot carry two different `OnCalendar` times. Two concrete pairs, per convention.

### Files to modify
| File | Change | Reason |
|---|---|---|
| `docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md` | rev b: statistic C, `I_max=40`, `t=min(1,I/I_max)`, remaining-α truncation, `d0_climate_day` rule, BE amendment (1)(e), structural-dead pin (1)(f) | spec precedes code (build order 1) |
| `docs/specs/PREREG_v1_kalshi_*.md` | Drop the copied `Z_k`/`π_k`/`t_k=n_k/n_max` (`:135-146`); inherit C verbatim; own `I_k`, own n, own D0, same `I_max` rule | ruling F |
| **NOT modified:** `live_family_tally.py`, `mb_current_rung_edge_study.py`, `trial_scorer.py`, `scored_trial_store.py`, `tests/unit/test_deploy_timer_hours.py` | — | ruling (3); the hour test **globs** `deploy/systemd/*.timer`, so new timers are admitted automatically — Rev 1's "modify it" was wrong |

### Interfaces
```python
# settlement/current_rung_hold_v2.py   (pure: no os/pathlib/open/print)
Z_95: Final[float] = 1.959963984540054      # value of archive_correction_probe.Z_95, restated not imported
def break_even_row(entry_ask: Decimal, fee: Decimal) -> Decimal          # BE_i = ask_i + fee_i
@dataclass(frozen=True, slots=True, kw_only=True)
class ScoreState: s: float; information: float; n: int                   # S, I, filled count
def score(rows: Sequence[StratumRow]) -> ScoreState
    # I = Σ BE_i(1-BE_i); S = Σ(held_i - BE_i)/sqrt(I); raises if I <= 0 (undefined, never 0.0)
def information_fraction(information: float, *, i_max: float) -> float   # min(1.0, I/I_max)
@dataclass(frozen=True, slots=True, kw_only=True)
class StratumV2: label: str; n: int; k: int; mean_ask: Decimal; pi: Decimal
    wilson_lower: float; wilson_upper: float                             # inlined per archive_correction_probe.py:352-363
    @property cell_dead: bool        # n >= 60 and wilson_upper < float(pi);  pi = mean(BE_i)
def build_stratum_v2(label: str, rows: Sequence[StratumRow]) -> StratumV2 | None      # None on empty
def look_verdict(state: ScoreState, *, b_eff: float, b_fut: float, total_pnl: Decimal,
                 cell_dead: Sequence[StratumV2], structural: StructuralDeadVerdict | None
                 ) -> Literal["SURVIVE", "KILL", "CONTINUE"]
    # SURVIVE  <=> S >= b_eff AND total_pnl > 0 AND not cell_dead AND not structural_fired
    # KILL     <=> S <= b_fut OR cell_dead OR structural_fired
    # else CONTINUE
class TruncationReason(StrEnum): D0_165 = "D0_165"; LOSS_STOP = "LOSS_STOP"; I_MAX = "I_MAX"
def terminal_look(state: ScoreState, *, reason: TruncationReason, b_eff: float, b_fut: float,
                  total_pnl: Decimal, cell_dead: Sequence[StratumV2]) -> Literal["SURVIVE", "KILL"]
    # CONTINUE is ILLEGAL here (ruling D). LOSS_STOP (ΣPnL <= -60) -> KILL unconditionally
    # (SURVIVE needs ΣPnL>0, impossible; efficacy alpha is vacuous).
    # b_fut < S < b_eff -> KILL, fail-closed: the family is stopping, not continuing.

# persistence/gs_boundary_artefact.py
I_MAX: Final[float] = 40.0                              # 160 x 1/4, pinned in the artefact input sha
@dataclass(frozen=True, slots=True, kw_only=True)
class BoundaryArtefact:
    inputs_sha256: str; i_max: float; alpha_one_sided: float; spending: SpendingSpec
    reference_rows: tuple[ReferenceRow, ...]            # 16 equal-t rows, REGRESSION ONLY
    def boundary_for(self, t_history: Sequence[float]) -> tuple[float, float]   # (b_eff, b_fut)
    def alpha_spent(self, t_history: Sequence[float]) -> float
    def remaining_alpha(self, t_history_completed: Sequence[float]) -> float    # 0.025 - spent(last completed look)
def load_boundary_artefact(path: Path, *, expected_sha256: str) -> BoundaryArtefact
    # raises BoundaryPinMismatch on sha drift; raises on i_max != 40, alpha != 0.025,
    # non-monotone t_history, t outside (0,1], or a reference fixture the solver cannot reproduce.

# persistence/family_manifest.py
@dataclass(frozen=True, slots=True, kw_only=True)
class FamilyManifest:
    family_id: str; venue: str; trial_id_prefix: str
    d0_climate_day: str                                  # LST station-day, ISO-8601; ruling F
    boundary_artefact_path: Path; boundary_inputs_sha256: str; stations: tuple[str, ...]
def load_family_manifest(path: Path) -> FamilyManifest

# scripts/analysis/family_tally_v2.py
def assert_family_only(rows: Sequence[ScoredTrial], manifest: FamilyManifest) -> None
def build_family_tally_v2(rows, *, manifest, artefact,
                          covered_listed_station_days: int | None = None,
                          truncation: TruncationReason | None = None) -> FamilyTallyV2
def main(argv=None) -> int      # --family REQUIRED, --store-dir, --output, --as-of, --truncate {D0_165,LOSS_STOP}
```

### Data flow
`scored_trials/*.parquet` → `read_scored_trials()` (unchanged) → `assert_family_only`: `trial_id.startswith(manifest.trial_id_prefix)` **and** `climate_day >= manifest.d0_climate_day`, else refuse the whole tally. `climate_day` is the latch key's own LST station-day (`trial_day_latch.py:113-114`, never DST, `climate_day.py:41-53`) and `ScoredTrial` carries **no** fill timestamp; the ruling shows the comparison is conservative — afternoon `[12:00,17:00)` LST at PM offsets −5/−6/−8 puts the fill UTC in `{D, D+1}`, never `D−1`, so a Pacific 16:00 LST fill on D0−1 lands 00:xx UTC on D0 and stays **v1**. Rev 1's "filled on D0−1 for a D0 climate day" risk **cannot occur** and is withdrawn.
→ drop `excluded_reason is not None` → per-row `BE_i = entry_ask + fee` → strata **pooled | station:* | ask:(lo,hi]**, each carrying `π = mean(BE_i)`; `cell_dead` fixed-rule at n≥60 on station/ask-band → pooled `score()` → `(S, I)`, `t = min(1, I/40)`, `t_history` = realized t at every completed look → `artefact.boundary_for(t_history)` → `look_verdict`. If `I ≥ 40` before n=160, or `n = 160`, or `--truncate` is given, or `ΣPnL ≤ −60` → `terminal_look` on **remaining** α (`0.025 − α_spent(last completed look)`; 0.025 if none) at `t_trunc`; at n=160 with `I<40` the remaining α makes terminal `b_eff = 1.959963984540054`. → **terminal only**: `compute_roi_bound(ROIInputRow(pnl, cost=fill_px + fee, excluded_reason))` + `format_roi_bound` (`settlement/roi_bound.py`, reused verbatim; `cost = fill_px + fee` confirmed unchanged) → markdown, header echoing `family_id`, `inputs_sha256`, `d0_climate_day`.

### Build order (commits, RED-first each)
1. `docs(specs)`: PREREG v2 **rev b** — statistic C, `I_max=40`, `t=min(1,I/I_max)`, remaining-α truncation, `d0_climate_day` rule; Kalshi sibling drops the copied `Z_k`. **Registered before any code that implements it** (v1 §7 restart discipline: a statistic in code but not in the spec is a post-hoc screen).
2. `feat(persistence)`: `gs_boundary_artefact` — loader, sha pin, `boundary_for`/`alpha_spent`/`remaining_alpha`, against the committed reference fixture (unblocks the parallel generator: the generator satisfies the fixture, not the reverse).
3. `test(prereg)`: the v1 non-modification pin — lands **before** any v2 wiring so every later commit is guarded.
4. `feat(settlement)`: `current_rung_hold_v2` — `score`, `StratumV2` (inlined Wilson), `look_verdict`.
5. `feat(settlement)`: `terminal_look` + `TruncationReason` (separate commit: it is the fail-closed path and gets its own RED).
6. `feat(persistence)`: `family_manifest` + the two manifest data files.
7. `feat(analysis)`: `family_tally_v2.py` — barrier, strata, look/terminal dispatch, BCa line, markdown.
8. `feat(deploy)`: wrapper + two concrete service/timer pairs (15:30 / 16:30 UTC).

### Tests (RED-first)
- **Score correctness** — `score()` on a hand-computed 3-row fixture matches `S`/`I` to 1e-12; `I` equals `Σ BE(1−BE)` and is **strictly less** than `n·π̄(1−π̄)` on a variance-bearing ask fixture (the concavity the ruling turned on); `I=0` raises rather than returning 0.0.
- **Non-vacuous BE golden** — asks 0.10/0.50/0.90 at θ=0.06: `mean(BE_i) < break_even(mean_ask)` strictly, gap pinned numerically (Jensen; addendum item 3).
- **Mixed-θ fixture** — rows with fees from θ=0.06 and θ=0.07 in one stratum: `π` is the arithmetic mean of per-row `BE_i`, not any single-θ `break_even`. (Proves the math; a real family is single-venue and never pooled.)
- **v1-rows-through-v2 refusal** — a `current_rung_hold/trial/…` row with `climate_day < d0_climate_day` raises; a Kalshi-prefixed row in the PM-v2 tally raises; symmetric case raises. Non-vacuity: the same rows minus the barrier build a stratum.
- **Non-modification pin** — AST source-text extraction (no import, so no side effects, though import is safe: `mb_current_rung_edge_study.py` is `__main__`-guarded, precedent `tests/unit/test_mb_current_rung_edge_study.py`) over `scripts/analysis/mb_current_rung_edge_study.py`: `FEE_THETA` (`:176`), `break_even` (`:179-181`), `RealizedStratum` (`:701-724`), `build_realized_stratum` (`:727-746`), each sha256-pinned. Plus the v1 call sites **re-derived after b08166c** (the structural-dead stop shifted them): `live_family_tally.py:192` (`station:` stratum), `:205` (`ask:` band), `:289` (`pooled`) — line-anchored source text, equality-pinned. Both directions, with two neighbour proofs each (one widened, one narrowed mutant asserted REFUSED by the same predicate), per `test_cage_rule_constants_are_pinned.py`.
- **Boundary artefact** — sha mismatch raises; `i_max != 40` raises; non-monotone `t_history` raises; the 16-row equal-t reference fixture is reproduced by the solver to 1e-9; `remaining_alpha` at look 0 is exactly 0.025.
- **Truncation** (own suite) — `CONTINUE` is unreachable: `terminal_look`'s return type admits only SURVIVE/KILL and a `b_fut < S < b_eff` fixture returns **KILL**; `LOSS_STOP` with `S ≥ b_eff` still returns KILL; `D0_165` admits both verdicts on the appropriate fixtures; `I_MAX` fires when `I ≥ 40` at n<160 and spends remaining α; at n=160 with `I<40` the terminal `b_eff` equals 1.959963984540054.
- **Strata/`cell_dead`** — false at n=59, true at n=60 with `wilson_upper < π`; the inlined Wilson matches `archive_correction_probe.wilson_interval` on 200 random `(k,n)` pairs (imported **in the test only**, never in `src/`).
- **BCa terminal-only** — a `CONTINUE` look invokes no `compute_roi_bound` (monkeypatched call counter); a terminal look invokes it exactly once.
- **No `venue:` stratum** — the rendered report's stratum labels are exactly `pooled`, `station:*`, `ask:*`; a regression assert that no label starts with `venue:`.
- **Deploy** — `test_deploy_timer_hours` (unmodified, globbing) stays green with the two new timers; `--family` is required (argparse exits 2); the wrapper passes `$1` through unmodified and fails loudly on an unknown family id.

### Risks
- **Boundary generator drift** (built in parallel, blind): mitigated by pinning the loader against a committed reference fixture in commit 2 and by `expected_sha256` in the manifest.
- **Solver-vs-generator disagreement.** `boundary_for(t_history)` is a *solver* over unequal, data-dependent `t` — it must be deterministic and path-dependent (the boundary at look k depends on the realized t's of looks 1..k). Any nondeterminism silently changes the registered α. Mitigate: the artefact records the spending spec and solver tolerance; the loader replays the reference fixture on every load and refuses on mismatch.
- **`I_max = 40` is a bound, not an expectation.** Real asks make `I ≪ 40`, so `t` grows slowly and early looks are very conservative; the family may reach n=160 at `t<1`. That is handled (remaining α at n=160), but the design's effective power is lower than the ratification's ASN sketch. Not a defect — a stated consequence to re-measure once the generator runs.
- **Manifest is a declaration, not a cryptographic fact.** A post-D0 edit would relabel rows. Mitigate: manifests committed pre-D0; their sha256 echoes into every report header, so a later edit shows in git and in the report diff.
- **Kalshi θ/rounding UNVERIFIED** (`KALSHI_INTEGRATION_PLAN_2026-09-03.md` §5.2/§5.4) and settlement-leg fee MISSING §5.5: per-row `fee` is only as good as the fee model that wrote it, and `assert_family_only` cannot detect a wrong fee. Kalshi stays shadow until pinned.
- **Structural-dead reuse.** `scripts/analysis/structural_dead_stop.py::structural_dead` is a script module the pure package must not import; `FamilyTallyV2` takes an already-built `StructuralDeadVerdict` from the script layer, mirroring how `live_family_tally.py` receives `covered_listed_station_days` from its caller.

### Null hypothesis — what already exists
- **BCa ROI bound: exists.** `src/breezy/settlement/roi_bound.py::compute_roi_bound/format_roi_bound/ROIInputRow` — reused verbatim, `cost = fill_px + fee` unchanged.
- **Wilson interval: exists** (`archive_correction_probe.py:352-363`, `Z_95`) — **restated, not imported**, to avoid a `src/` → `scripts/` edge; equivalence asserted in tests.
- **Structural-dead stop: exists** (`structural_dead_stop.py:95`, landed b08166c) — reused as a value object, not reimplemented.
- **scipy 1.18.1 installed** — `scipy.stats.norm.ppf/cdf` supplies the normal quantiles the *generator* needs. **statsmodels absent**, and neither scipy nor numpy ships Lan-DeMets alpha-spending or a sequential boundary solver, so the generator is a genuine gap (out of this blueprint's scope). `score()` itself is four arithmetic ops — no library.
- **Parquet store + `(trial_id, max score_seq)` dedupe: exists** (`scored_trial_store.py`), reused with **zero** schema change.
- **Nautilus: nothing to reuse and nothing touched.** It has no pre-registration, alpha-spending, or family-tally surface; this is post-settlement analysis, outside its extension points.
