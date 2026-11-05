# GAP-4 REGISTERED-FAMILY: plan r0
Status: r0, peer review pending (architect, prediction-market-reviewer). Nothing is built or run until both return READY.

## 1 Objective
Register one family that trades only the cell GAP-3 selects: (source, horizon, side, ask band [a_lo, a_hi], margin m ∈ {0.02, 0.03, 0.05}). It runs live-small at qty 1 under a frozen PREREG v2 sequential test. This is the step that turns a backtested cell into fills that are scored: it answers "does realised win rate exceed ask + fee?" on forward tape. It stops at **ready to arm**. Arming is operator-only.

## 2 Preconditions and dependencies
- **GAP-3 (hard):** a cell that passed `p_one_sided × K_cum ≤ 0.05` and bootstrap LB(mean excess) > m, as an immutable `--out` file under `~/.local/share/breezy/derived/strategy_iteration/`. No passing cell means GAP-4 closes as NOT-STARTED. No family is registered on a failed or absent cell.
- **GAP-5 (hard):** FQ is an IOC taker (`strategy.py:680-687`, `OrderSide.BUY`, `TimeInForce.IOC`). The 11-01 create-path defect (empty-executions → AMBIGUOUS → latch denies) blocks the YES path. GAP-5 must show a live IOC create resolving to FILLED or ZERO_FILL without latching.
- **GAP-2 / GAP-1 (conditional):** only needed if the cell's source is not the NBM-quantile + NBP-calibration p that FQ already computes live. See C3.
- **Parity (hard):** the p that GAP-3 binned must be the same quantity the live `evaluate` gates on. That is `p_lower` from `bounds_provider` over `calibration.resolve(...).draws` (`decision.py:306-331`), not `p_hat` and not a point estimate. A different quantity is a unit change and voids the cell.

## 3 Scope: does a new family JSON suffice?
**Partly.** A new `deploy/families/pm_us_fq_cell_v1.json` (pattern: `pm_us_crh_fq_v1.json`, `composition_kind: forecast_quantile_ladder`, status REGISTERED, `taker_fee_coefficient` "0.0695", sha-pinned `density_artefact_path`, `stations`, `d0_climate_day`, `terminal_climate_day`) is enough **only when all of these hold**:
(a) source = NBP-calibrated NBM quantiles;
(b) horizon = D+1 (`_is_d_plus_1`, `decision.py:216-218,277-281`);
(c) side = YES;
(d) PREREG accepts the existing margin `forecast_margin(h)`, which ramps 0.02→0.06 and equals 0.06 on every D+1 tick (`test_every_d_plus_1_tick_has_forecast_margin_0_06`);
(e) there is no ask band.

The GAP-3 cell carries its own m and band, so (d) and (e) fail in general. The manifest refuses unknown keys (`family_manifest.py:324-326`), and `evaluate` has no band check. Expected code changes, each a separately reviewed TDD change:
- **C1 frozen margin:** optional manifest key `take_margin` (decimal string). When present, the composition root passes it in place of `forecast_margin(h, cfg)`. When absent, behaviour is byte-identical. Touches `family_manifest.py` `_OPTIONAL_KEYS` + `FamilyManifest`, FQ composition, `decision.evaluate` (a margin parameter). Running m = 0.06 when the cell was m = 0.03 would trade a different fill set than the one backtested, so C1 is required unless GAP-3 picks 0.06.
- **C2 ask band:** optional manifest key `ask_band: [lo, hi]`, plus a new refusal `ask_out_of_band` inserted **after (8a)** per the pinned check order (`decision.py:244-264`). It is a non-latching Refuse. Add it to `decision_log_fields` coverage.
- **C3 p source (only if the cell is not NBP):** there is no live emitter for LAMP, PFM or blend p. That needs a new BoundsProvider/actor and is out of GAP-4 scope. It routes to GAP-1/GAP-2 plus a separate plan and the operator's harness exception.
- **C4 NO side:** see §7. Treat it as a blocker, not a change inside this plan.
- Horizon D0: out of scope. `NotDPlus1` is a pinned non-trial gate, so a D0 cell is reported as unsupported, not built.

Not in scope: Nautilus, `allow_short`, the exec adapter, the NO-SEND firewall, the permit, caps, `live_orders_ruling` value, size q.

## 4 Steps
| # | Action | Output | Runs | Est |
|---|---|---|---|---|
| S0 | Read GAP-3 cell file; verify parity (§2) and (a)–(e); choose JSON-only or C1/C2 | `docs/plans/backlog/GAPS_2026-11-01/gap4_registered_family/route.md` | sub-agent, read-only | 1 h |
| S1 | C1 RED→GREEN (if needed) | diff + RED/GREEN log | tdd-guide (grok/codex per route) | 3 h |
| S2 | C2 RED→GREEN (if needed) | diff + RED/GREEN log | same | 3 h |
| S3 | Mint density artefact copy (sha-pinned) under `deploy/families/artefacts/`; draft manifest `DRAFT_NOT_REGISTERED` | manifest + artefact | sub-agent | 1 h |
| S4 | Write PREREG (§5); run `scripts/analysis/prereg_precommit_check.py` clean | `docs/evidence/PREREG_gap4_<family>_2026-11-xx.md` | sub-agent; Claude reruns check | 2 h |
| S5 | Flip status to REGISTERED; set `d0_climate_day` > commit date; commit manifest + PREREG; record both sha256 in PREREG sidecar **before the first forward day** | commit sha | main (commit only) | 0.5 h |
| S6 | Shadow boot (`shadow_only=True`) one day: decisions emitted, band/margin refusals visible, zero submits. A dry run, never a look | evidence log | bot | 1 d |
| S7 | Report READY TO ARM: manifest sha, PREREG sha, GAP-5 evidence, shadow evidence | PROGRESS entry | main | — |

## 5 Pre-registered PASS/KILL (frozen at S4, before any forward day)
- **Frozen inputs:** cell id + GAP-3 `--out` sha; stations; side; band [a_lo, a_hi]; m; θ = 0.0695; density artefact sha; manifest sha; qty 1; one take per (station, day, rung, side) via the existing latch.
- **Unit:** one filled IOC take, scored win/loss on the NWS CLI settlement. Break-even per fill = ask + fee(ask). H0: win rate ≤ mean break-even of the fills.
- **Design:** PREREG v2 sequential test. One-sided Wilson LB with Lan-DeMets O'Brien-Fleming spending, α = 0.025, a look every 10 fills, n_max = n_min.
- **n_min:** the smallest n at which the final LD-OBF boundary rejects H0 with power 0.8 at the GAP-3 bootstrap-LB edge. The computation is written into the PREREG and frozen.
- **D_c:** from the r1-delta table (one-sided, R = 3): 5/10/15¢ → 221/55/25 days, chosen by the cell's LB edge. `terminal_climate_day` = d0 + D_c.
- **PASS:** the upper boundary is crossed at any look.
- **KILL:** n_max is reached, or D_c days pass, without crossing.
- **HARM:** the LD-OBF lower boundary is crossed. The family is halted through the existing `set_family_halt_cli`; FQ is in `HALTABLE_COMPOSITION_KINDS`.
- **Rules:** one look per 10 fills, no others (L-34). Shadow and dry-run never count. Widen, never relax (L-12). The operator's ≥ 70% preference is reported descriptively and is not a gate.

## 6 Tests (RED first) and gate
- C1: `test_take_margin_absent_is_byte_identical_forecast_margin`, `test_take_margin_present_replaces_ramp`, `test_manifest_take_margin_must_be_decimal_string`, plus an update to `test_equality_covers_new_manifest_fields`.
- C2: `test_ask_out_of_band_refuses_without_latch`, `test_ask_band_check_follows_calibration_version_unavailable` (extends the check-order pin), `test_manifest_ask_band_lo_lt_hi_in_0_1`.
- Manifest: `test_load_manifests` accepts the new family; `test_forbidden_imports` stays green.
- Gate: `scripts/ci/run_tests_no_egress.sh` on the primary tree (binding). Basetemp goes inside the worktree. Read EXIT before any push. Name the whole-tree guards in the brief: autonomy, import-linter via `lint-imports`, asdict scan, fee pins, exec import pin.

## 7 Pins, isolation, risks
- **NO side is a BLOCKER for this family.** `decision.evaluate` does price NO from the native NO ask (`ev_net_no`). But the FQ live loop subscribes D+1 **YES** ids (`_d1_candidate_ids`, `strategy.py:299-317`) and always submits `OrderSide.BUY` on `take.instrument_id`. The merged S5 SELL/BUY_SHORT path lives in the continuous-rung-hold mixin (`continuous_no_side.py`), not in FQ. A NO cell therefore needs a separate reviewed plan to route FQ NO takes through the S5 path, with `allow_short` untouched. Until then a NO cell is reported unsupported.
- **Exposure risk:** IOC misses classify as AMBIGUOUS, so each miss latches. That consumes trial-days and starves n, so GAP-5 is gating.
- **D_c risk:** at roughly 5 stations × HIGH only, D_c can exceed the r1 D = 28 budget. State this in the PREREG; do not shorten it.
- Byte-pinned exec files, the x1 egress set and NO-SEND are not touched. The manifest sha and PREREG sha are committed together; any later edit means a new family id.
- **Binding constraints:** Nautilus Trader immutable; `allow_short` False; no safety, settlement, contract, pin or NO-SEND test weakened; operator caps never assigned; enablement untouched; existing harness only; holdout cl.1–cl.4; L-75 sidecars only; `iem_cli_fetch.fetch` never called; credentials never printed; no order ids in the repo.

## 8 Operator decisions
Arming only: the permit, `live_orders_ruling` id, max daily budget and max per position. The plan sets none of these. If the cell needs C3 or NO routing, that is a separate operator-visible plan.

## 9 Citations not verified
- The S5 adapter maps BUY on a NO sibling to SELL/BUY_SHORT for CRH only. FQ use was inferred from `strategy.py:680-687` plus YES-only subscription and needs an S0 check.
- No existing FQ code implements the LD-OBF HARM boundary was checked (`loss_stop_probe.py` was read only at `FqComposedVeto`).
- The `prereg_precommit_check.py` flags and output contract were not read.
- The name and location of an n_min/power helper in the existing harness were not found.
- That `LadderEvConfig` reaches FQ from the composition root and not from the manifest is inferred.
