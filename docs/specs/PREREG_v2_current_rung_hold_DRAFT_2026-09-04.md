# PREREG v2 — current_rung_hold (Polymarket.us) — group-sequential amendment (DRAFT, ratified-with-amendments 2026-09-04)

Status: DRAFT, ratified-with-amendments by the strategy lead
(`docs/evidence/grok_prereg_v2_ratification_2026-09-04.md`, §Final ruling (1)(a)-(f) and (3)).
Not yet registered — registration per §8 below. Supersedes the prior DRAFT
(`docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md`) wherever this document conflicts
with it.

## 1. Purpose

Unchanged from the prior draft: replace v1's fixed 60/150 Wilson interim-monitoring rule
(`mb_current_rung_edge_study.py:717,719,723-724`) with a valid alpha-spent sequential design,
without loosening v1's Type I error, its terminal decision quantities, or any of its frozen
parameters.

## 2. Binding inheritance from v1

- v1's Wilson `z = 1.959963984540054` (`archive_correction_probe.py:66,352-363`) is the fixed
  60/150 rule's own critical value; v1 kill/survive is the **inversion of a Wilson score test at
  that fixed z** (ratification (a), citing `mb_current_rung_edge_study.py:717-724`). v2's two
  one-sided tests, each α = 0.025, match this exactly — not a Wald approximation (see §3).
- Frozen and untouched: the strata definition, take rule, and per-row BE
  (`decision.py:249-256,298-300` — already correct, per-row, and not part of this amendment), the
  scoring rule, `z`, the BCa statistic/`B`/seed/ceiling (`roi_bound.py:93,97,100,104`), and the
  station set.
- **v1 stays byte-identical.** No clause below is applied to v1's live tally. The ratification is
  explicit that v1 registers no "computational-defect" or "bugfix" carve-out
  (v1 §7:137-150; ratification "Whether v1 permits computational-defect tally fixes while live" —
  Not granted).

## 3. The sequential rule (AMENDED — Wilson score, not Wald)

**Statistic — relabeled per ratification (a).** The draft's earlier §3 formula was mislabeled
"Wald"; it is the **Wilson score** form, the same inversion v1's fixed z already performs:

```
Z_k = (p̂_k − π_k) / sqrt(π_k(1 − π_k) / n_k)
p̂_k = k / n_k               (k = held count, n_k = filled Takes only)
π_k = mean_i(BE_i)           (v2-only; see §5 for BE_i)
```

`p̂_k` is on filled Takes only, matching v1 §5:105 and the live/paper/archive barrier
(`live_family_tally.py:139-171`). The Wald form would place `p̂` in the variance term instead of
`π`; using `π_k(1-π_k)/n_k` in the denominator is what makes this the Wilson-score statistic, the
same family v1's fixed-z Wilson interval already inverts (ratification (a): "Wilson interval …
is the inversion of this score"). **Wilson endpoints (the interval itself) are never
sequentialized — only `Z_k` is monitored against the boundary.**

**Boundary form.** Lan-DeMets alpha-spending, O'Brien-Fleming-type spending function. **Two
one-sided tests, each α = 0.025** (matching v1's two-sided-95%/one-sided-97.5% Wilson used
one-sided each direction):

| Direction | H1 | Stop when |
|---|---|---|
| Efficacy / SURVIVE | p > π | Z_k ≥ b_k^eff |
| Binding futility / KILL | p < π | Z_k ≤ b_k^fut |

Terminal `b_16^eff = z` (= 1.959963984540054), so the final look reduces to exactly v1's fixed
critical value. Both frozen v1 clauses still gate SURVIVE in addition to crossing `b_k^eff`:
ΣPnL > 0 and no stratum `cell_dead` (§4 below; unchanged from the prior draft's §5).

**Look schedule.** Every 10 filled Takes: `n_k = 10, 20, …, 160` (16 looks).

**Boundaries table.** Placeholder — generated and pinned per §7, unchanged in mechanism from the
prior draft.

| look k | n_k | efficacy boundary b_k^eff | futility boundary b_k^fut | cumulative α spent |
|---|---|---|---|---|
| 1 | 10 | *pending* | *pending* | *pending* |
| … | … | … | … | … |
| 15 | 150 | *pending* | *pending* | *pending* |
| 16 | 160 | z = 1.959963984540054 | *pending* | 0.025 |

## 4. Truncation

Unchanged from the prior draft: v1's time stop (D0+165, v1 §6:121-123) and loss stop
(ΣPnL ≤ −60 contract-units, v1 §6:124-128) still truncate the schedule.

**Information fraction — CONFIRMED `t_k = n_k / 160`** (ratification (c)). The prior draft's open
question proposing a *calendar-time* information fraction (`t/165`) is **rejected** — `t_k` is
always the filled-Takes fraction of `n_max = 160`, never a function of elapsed calendar days.

**Spending-to-horizon at truncation.** If D0+165 or ΣPnL ≤ −60 fires before `n_max = 160` is
reached, the design spends the remaining α at `t_trunc = n_trunc / 160` (the actual observed
information fraction at truncation, per the Lan-DeMets spending function), and only then computes
the terminal BCa bound (ratification (c): "truncation … spends remaining α at n_trunc/160, then
BCa").

## 5. BE definition (AMENDED — v2 only; concave-fee defect)

**Defect identified by the strategy lead:** v1's tally computes the analysis break-even as
`break_even(mean_ask)` — a single BE evaluated at the pooled mean ask
(`mb_current_rung_edge_study.py:736,743`; `live_family_tally.py:184,197,248` via
`build_realized_stratum`) — not the mean of each row's own BE. The fee is **concave** in ask
(`fees.py:86-88`: "The function is concave with a maximum at p = 0.50"), so by Jensen's
inequality `fee(E[ask]) ≥ E[fee(ask)]`, meaning `break_even(mean_ask)` systematically **raises**
the hurdle above `mean(BE_i)`. Worked example, two rows `{0.10, 0.90}`, θ=0.06
(`test_polymarket_us_fee_model.py:164-179`): `break_even(mean_ask=0.50) = 0.5154` vs
`mean(BE_i) = (0.1054+0.9054)/2 = 0.5054` — a 100-bp-scale inflation of the hurdle.

**v2-only correction.** v2 registers the analysis break-even as `π_k = mean_i(BE_i)`, with
`BE_i = entry_ask_i + fee_i` computed **per row** (fee already present on `ScoredTrial`, per
ratification (a)). This applies to:
- the pooled statistic `Z_k` in §3 (`π_k`), and
- the fixed-rule station/ask-band strata in §6 below — those strata switch to `mean(BE_i)` too
  (ratification (d): "v2 uses mean(BE_i) in those strata too").

**v1 is untouched by this correction.** v1's registered analysis BE is `BE(mean entry_ask)`
(v1 §1:26-27, §5:101-104), frozen by §7:142 ("the BE formula and rounding mode") and §7:147-150
("any change to a parameter, the table, or a **threshold** requires a NEW pre-registration …
Amending v1 in place is prohibited"). The ratification states explicitly: no computational-defect
carve-out exists for v1. Per-row take-time BE (`decision.py:249-256,298-300`) was never wrong and
is unaffected either way — the defect is confined to the *analysis*-time pooled/stratum BE, not
the take decision.

## 6. Unchanged / fixed-rule clauses

- **Sequential monitoring applies to the POOLED statistic only** (ratification (d)). Station and
  ask-band strata remain v1's fixed-rule `cell_dead` check at `n ≥ 60`
  (`mb_current_rung_edge_study.py:717-719`; `live_family_tally.py:251-253,265-277`) — not
  sequentialized — but now evaluated against `mean(BE_i)` per §5, not `break_even(mean_ask)`.
- **Both lag arms (30, 45 min) must agree** (v1 §3:71-74) — unchanged.
- **ΣPnL > 0 required for SURVIVE**, in addition to the boundary crossing
  (`live_family_tally.py:257-262`) — unchanged.
- **BCa ROI lower bound remains TERMINAL**, computed only at the final decision or at truncation
  (§4), never at an interim look (`roi_bound.py:173-236`) — unchanged. Do not sequentialize the
  BCa ratio-of-sums statistic (no known independent-increments structure across looks).
- **n counts filled Takes only** — no shadow, paper, archive, or Kalshi rows enter `n` or `Z_k`
  (`assert_live_only`/`assert_paper_only`, `live_family_tally.py:139-171`) — unchanged.

## 7. Boundary generation & pinning (script contract)

Unchanged in mechanism from the prior draft. `scripts/analysis/crh_group_sequential_boundaries.py`
must compute (not author) the §3 table:

- **Inputs:** two one-sided tests at α = 0.025 each; Lan-DeMets O'Brien-Fleming-type spending
  function; look schedule `n_k = 10..160` step 10; `n_max = 160`; per-look `π_k = mean(BE_i)`
  over accumulated filled Takes (§5), not `break_even(mean ask)`.
- **Outputs:** the full boundary table (`b_k^eff`, `b_k^fut`, cumulative α spent per direction per
  look), pinned verbatim into this spec once generated, plus a sha256 of the exact input parameter
  set, following v1's archive-table provenance-pin pattern (v1 §0, `archive_table.py:32-33`).
- **Also required:** simulated ASN under a real-edge scenario and a leak/no-edge scenario,
  reported as measured output, not asserted — the ratification does not restate the earlier
  draft's ASN figures as binding, and none should be presented as measured until this script runs.

## 8. Registration & D0

Unchanged rule, restated: v2 is a **new family** (v1 §7:147-150) — `n` resets to 0, no v1-scored
row is ever pooled into a v2 stratum or boundary evaluation.

**D0 rule (confirmed, ratification "Draft §8 D0 rule stands").** D0 = the first UTC day after (a)
this amended spec is committed, **and** (b) a v2-only live tally is running the §3/§7 boundary
table (not merely present in the repo). Any fill before both (a) and (b) is v1-only and reported
under v1's tally, never merged into v2's `n`.

## 9. Structural-dead test (AMENDED — full pin, implementable on v1 now)

Replaces the prior draft's §9 in full, per ratification (f). This is a **numeric pin of already-
registered machinery**, not a new screen — it is implementable on v1 immediately (unlike §§3-7,
which are v2-only) because v1 §5:105-106 already cites it via spec rev2 §6:139, and the ratification
confirms no carve-out is needed to *implement* a clause v1 already registered.

| Piece | Definition | Cite |
|---|---|---|
| Window | `[12:00, 17:00)` LST | v1 §2:35-36 |
| Afternoon-covered | span of distinct captured Depth10/quote instants in that window ≥ 30 min; 0–1 instant ⇒ 0 | `ma_prelock_winner_ask_study.py:160,323-332,360-361` (`MIN_AFTERNOON_COVERAGE_MINUTES = 30.0`, `afternoon_coverage_minutes`) |
| Listed | venue listed that station-day; skip-days excluded from the denominator | v1 §2:45-47 |
| Denominator | covered **listed** station-days of the family set (LAX, MDW, MIA, SFO) | v1 §2:32 |
| Fire at | count ≥ 15 | `MIN_AFTERNOON_STATION_DAYS = 15`, `ma_prelock_winner_ask_study.py:163`; v1 §5:105 |
| "≈0" | **filled Takes = 0** on those days — one fill kills this stop (L-9 "no seller"); this is not a Wilson take-rate test | analogous to `mb_current_rung_edge_study.py:54-58`'s M_B structural check |

Distinct from, and never a substitute for, the already-registered D0+165-without-n=150 clock stop
(v1 §6:121-123). Do not add an ε>0 tolerance or a Wilson test on the take rate — that would be a
new post-hoc screen, prohibited by the blueprint's standing refusal
(`docs/plans/CURRENT_RUNG_HOLD_BLUEPRINT_2026-09-04.md:48`).

`all_visited_cells_dead_by_construction` (`mb_current_rung_edge_study.py:683-697`) is confirmed
**archive-only** — it operates on `MbStationDaySummary`, the offline study's data shape, and is not
this test.

## 10. Rejected alternatives

- **SPRT at α=0.05/β=0.20** — rejected: loosens v1's registered one-sided 0.025, no
  corpus-grounded δ, open-ended `n_max`.
- **Sequential rule on the BCa ratio-of-sums** — rejected: no known independent-increments
  structure across bootstrap resamples; the BCa bound stays terminal-only.
- **Unspent Wilson peeks** — rejected: inflates realized Type I error above the registered 0.025
  with no accounting; the alpha-spending function in §3 exists precisely to prevent this.
- **Calendar-time information fraction (`t/165`)** — rejected by the strategy lead (ratification
  (c)); `t_k` is filled-Takes-based (`n_k/160`) only.

## 11. Implementation gap list

| Item | Module | Missing test |
|---|---|---|
| Group-sequential boundary generation | new file `scripts/analysis/crh_group_sequential_boundaries.py` (§7) | none exists yet — write RED-first alongside the script |
| Per-look boundary evaluation (`Z_k` vs `b_k^eff`/`b_k^fut`) wired into a v2-only live tally | new module or new mode on `live_family_tally.py` (current `build_live_family_tally`, lines 229-301, evaluates only v1's fixed rule) — must not mutate v1's existing code path | no test file found |
| `mean(BE_i)` computation for pooled and strata (v2 only) | new helper alongside `build_realized_stratum` (`mb_current_rung_edge_study.py:727-746`), must not alter that function's v1 behavior | no test found |
| Structural-dead check (§9), implementable on v1 now | `live_family_tally.py` — no afternoon-covered-station-day counter or filled-Takes-count check anywhere in this file (confirmed `:229-301`) | no `test_live_family_tally_structural_dead*` found |
| Spending-to-horizon truncation logic | not present anywhere | none |

## 12. Not touched on live v1

Copied verbatim from the ratification's table (3):

| If applied to v1 | Why post-hoc |
|---|---|
| Sequential Z_k, n_max=160, spending-to-horizon, boundary script in `live_family_tally.py` | Replaces frozen 60/150 Wilson (v1 §5:101-104, §7:142) |
| mean(BE_i) in the v1 tally / expansion-plan S2 | Changes registered `BE(mean entry_ask)` (v1 §5:101, §7:142,147-150) |
| Adding stations, Kalshi rows, shared pooled flag | Frozen station set (v1 §2:32, §7:143); sibling never pooled |
| Lowering floors, peeking Wilson, sequential BCa, Wald interval | v1 §5:112, §6:130-131, §7:143-144 |
| Extra structural-dead ε / Wilson-on-take-rate | New screen (blueprint:48) |

**Allowed on v1:** implement the already-registered structural-dead pin (§9 above); ALERT-only
corpus hash check (v1 §7:144-145). The §8 D0 rule stands unchanged: any fill before both the v2
spec and a v2-only tally exist is v1-only.
