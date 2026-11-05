# GAP-4 REGISTERED-FAMILY: plan r1
Status: r1 — for re-review by architect, prediction-market-reviewer. Nothing is built or run until both return READY.

## Finding → resolution
| # | Sev | Resolution (section) |
|---|---|---|
| A-1 | HIGH | Accepted. GAP-3's m is a *selection* floor on realised mean excess. It is never used as the live take threshold. The live filter is the cell's forecast-edge bin in evaluate's own `net` units (`decision.py:337-355`: `ev_net(p_lower, fee+slippage_floor_prob)`), with the same `slippage_floor_prob` value in GAP-3 binning and live. S0 must prove that unit identity, or the cell is void (§2, §3 C1/C2). |
| P-1 | HIGH | Accepted. The statistic becomes the PREREG v2 per-fill centred score S_k = Σ(win_i − BE_i)/√ΣBE_i(1−BE_i), BE_i = ask_i + fee(ask_i). This is the formula in `scripts/analysis/crh_group_sequential_boundaries.py:11-14`, per `docs/evidence/grok_v2_score_statistic_ruling_2026-09-04.md`. The Wilson-vs-mean-BE wording is removed (§5). |
| P-2 | HIGH | Accepted. Both reviewers converge on this together with A-5. n_max and the boundaries come from the existing generator `crh_group_sequential_boundaries.py` (`--alpha --n-max --look-step --pi --delta --sim-reps --seed --out`), whose output is the manifest's required `boundary_artefact_path`/`boundary_inputs_sha256`. `fq_mc_eprocess.n_for_power` is rejected because it is an e-process, a different design (P-2's own point). A reachability check is added (§4 S0, §5). |
| P-3 | HIGH | Accepted. The S0 feasibility gate: if n_max ÷ (cell fills/day from the GAP-3 file) > D_c, the gap closes as **UNDERPOWERED-NOT-REGISTERED** and nothing is registered (§4, §5). |
| A-2 | MED | Accepted. C1 is now a manifest → `LadderEvConfig(margin_m0=margin_m24=edge_lo)` override at the composition root (`composition.py:188`, `ladder_cfg` is today always the default because no caller passes it). `evaluate`'s signature is untouched. `__post_init__` allows m0 == m24 (`config.py:197`). This closes r0 §9 item 5. |
| A-3 | MED | Accepted in part. `nbp_shadow_parity_pure._forecast_margin(h, cfg)` (`:612,:752`) already takes cfg, so C1 threads the same override helper into it when a family manifest carries one. `fq_mc_livedata.py:370` and `fq_resume_n_mc.py` are declared ramp-only, and their docstrings say so. Guard code in analysis-only Monte-Carlo scripts is declined as widening scope. S0 checks whether the live `parity_veto` in `FqComposedVeto` consumes the pure-parity output (see §7 risk). |
| A-4 | MED | Accepted. New keys go in `_OPTIONAL_KEYS` only (`family_manifest.py:162-164`), never `_REQUIRED_KEYS` (actual lines `:133-148`, not `:150-160`). `_field_getters` gains mappings, and None is omitted on dump (`:523`). A RED test proves existing manifests round-trip byte-identically. |
| A-5 | MED | Accepted (see P-2). S3 also mints the boundary artefact (schema `gs_boundary_artefact.py:110-123`: alpha, i_max, look_step, n_max, reference_table b_eff/b_fut) and `trial_id_prefix`. |
| P-4 | MED | Accepted. HARM is the generator's binding futility boundary b_fut, at the same one-sided α = 0.025 via the symmetric Lan-DeMets OBF spend (`:30-37`). No separate β. OBF early boundaries are very wide, so a crossing before about 30 fills is rare. If one happens, it is reported as low-information but still halts. Enactment goes through the existing `set_family_halt_cli` → `FqComposedVeto` halt branch (`loss_stop_probe.py:732-763`). No second stop semantic is added. |
| P-5 | MED | Accepted (§5 reporting). |
| P-6 | MED | Accepted. ZERO_FILL is neither a trial nor a look. AMBIGUOUS-latched rung-days are censored and counted in the PREREG. No retry is possible: `evaluate` latches on Take before submit (`decision.py:357`). |
| P-7 | MED | Accepted. GAP-3 bins must be on live `p_lower` from the same sha-pinned calibration artefact, or the cell is void. Overconfidence is caught by the cell's realised-excess criterion, plus a descriptive reliability table at S0 (§2). |
| A-6 | LOW | Accepted. Insertions go after (8)/(8a) (`decision.py:256-264`), with new tests and no edits to the pin `test_evaluate_check_order_pins_opposite_side_between_own_side_and_later_refusals`. The decision_log_fields claim is dropped: reason is a free string and the funnel vocabulary is open (`decision_funnel.py:17-23`). |
| A-7 | LOW | Accepted. Cited in §7: `strategy.py:299-331`, `:680-687`. |
| A-8 | LOW | Accepted. Test names fixed in §6. |
| A-9 | LOW | Accepted. The manifest+PREREG commit is separate from the C1/C2 code commits (§4 S5). |
| P-8 | LOW | Line numbers verified by me (see §9). |

## 1 Objective
Register one family that trades only the cell GAP-3 selects: (source, horizon, side, ask band [a_lo, a_hi], forecast-edge bin [edge_lo, edge_hi) in `net` units). It runs live-small at qty 1 under a frozen PREREG v2 group-sequential test, and answers "does the realised win rate exceed ask + fee?" on forward tape. It stops at **ready to arm**. Arming is operator-only.

## 2 Preconditions and dependencies
- **GAP-3 (hard):** a cell passing `p_one_sided × K_cum ≤ 0.05` and bootstrap LB(mean excess) > m, as an immutable `--out` file under `~/.local/share/breezy/derived/strategy_iteration/`. If none passes, the gap closes NOT-STARTED.
- **Unit parity (hard, void if broken):** the GAP-3 bin variable is `net = p_lower − ask − fee(ask) − slippage_floor_prob` (YES, `ev_net`). `p_lower` comes from `ArtefactBoundsProvider` over the *same* sha-pinned calibration artefact's `resolve(...).draws` (`decision.py:306-331`), and `slippage_floor_prob` is the same value live uses. Neither `p_hat` nor the point estimate may be used. GAP-3 binning must use strict `net > edge_lo`, the same as live (`:354`).
- **Calibration (hard):** the D+1 `p_lower` is the current artefact, not the retired 10-04 FQ draw. S0 emits a descriptive reliability table of the cell's fills. This is cl.3-disclosed and is not a look.
- **GAP-5 (hard):** a live IOC create resolves to FILLED or ZERO_FILL without latching AMBIGUOUS.
- **GAP-1/GAP-2 (conditional):** only if the cell's source is not NBP-calibrated NBM (C3).

## 3 Scope
A new `deploy/families/pm_us_fq_cell_v1.json` (pattern `pm_us_crh_fq_v1.json`, `composition_kind: forecast_quantile_ladder`). A JSON-only manifest suffices only if source = NBP, horizon = D+1, side = YES, edge_lo = 0.06 (the D+1 ramp value), edge_hi open, and there is no ask band. Otherwise:
- **C1 constant margin (edge_lo):** optional manifest key `take_margin` (decimal string). When present, the composition root builds `LadderEvConfig(margin_m0=margin_m24=take_margin)` and passes it as `ladder_cfg`. The same helper feeds `nbp_shadow_parity_pure`'s cfg. When absent, behaviour is byte-identical.
- **C2 band:** optional keys `ask_band: [lo, hi]` and `edge_hi` (decimal string). Non-latching refusals `ask_out_of_band` (inserted after (8a)) and `above_edge_band` (net ≥ edge_hi, checked after `below_margin`). Only a Take latches (`:357`).
- **C3 non-NBP source:** out of scope. It routes to GAP-1/GAP-2, a separate plan and the operator exception.
- **NO side or D0:** unsupported (§7). They are reported, not built.

Not in scope: Nautilus, `allow_short`, the exec adapter, the NO-SEND firewall, the permit, caps, the `live_orders_ruling` value, size q, and new evaluator logic.

## 4 Steps
| # | Action | Output | Runs | Est |
|---|---|---|---|---|
| S0 | Read the GAP-3 cell. Verify unit parity, calibration sha and strictness. Compute fills/day. Run the generator dry (`--pi` = cell mean BE, `--delta` = cell LB edge, `--look-step 10`, `--alpha 0.025`, fixed seed) to find the smallest n_max with power ≥ 0.8. Apply the feasibility gate. Check whether `parity_veto` reads pure-parity output. Choose JSON-only or C1/C2 | `docs/plans/backlog/GAPS_2026-11-01/gap4_registered_family/route.md` | sub-agent, read-only | 2 h |
| S1 | C1 RED→GREEN | diff + RED/GREEN log | tdd-guide via route (grok/codex) | 3 h |
| S2 | C2 RED→GREEN | same | same | 3 h |
| S3 | Mint the density artefact copy and the boundary artefact (generator `--out`), both sha-pinned, under `deploy/families/artefacts/`. Draft manifest `DRAFT_NOT_REGISTERED` with `trial_id_prefix` | manifest + 2 artefacts | sub-agent | 1 h |
| S4 | Write the PREREG (§5). Run `prereg_precommit_check.py` clean | `docs/evidence/PREREG_gap4_<family>_2026-11-xx.md` | sub-agent; Claude reruns | 2 h |
| S5 | Set REGISTERED, `d0_climate_day` > commit date, `terminal_climate_day` = d0 + D_c. Make one commit containing only the manifest, artefacts and PREREG, separate from S1/S2. Record shas in the sidecar before the first forward day | commit sha | main | 0.5 h |
| S6 | Shadow boot for one day: decisions and band/margin refusals visible, zero submits. A dry run, never a look | evidence log | bot | 1 d |
| S7 | READY TO ARM report: shas, GAP-5 evidence, shadow evidence, feasibility numbers | PROGRESS entry | main | — |

## 5 Pre-registered PASS/KILL (frozen at S4)
- **Frozen inputs:** cell id + GAP-3 `--out` sha; stations; side; ask band; [edge_lo, edge_hi); `slippage_floor_prob`; θ = 0.0695; density, calibration and boundary artefact shas; manifest sha; qty 1; generator argv + seed.
- **Unit:** one filled IOC take, scored on NWS CLI settlement. ZERO_FILL is not a trial. AMBIGUOUS-latched rung-days are censored and counted, and the censored count is reported at every look.
- **Statistic:** S_k = Σ(win_i − BE_i)/√ΣBE_i(1−BE_i), with I_max pinned at n_max/4. Under H0, each fill wins with probability equal to its own BE_i.
- **Boundaries:** Lan-DeMets OBF, one-sided α = 0.025 each side, binding futility, evaluated at the realised t_k via the generator's `boundary_for`. A look every 10 fills, with no other looks (L-34).
- **n_max:** the S0 value. Power is computed at the bootstrap-LB edge and is disclosed as optimistic under best-of-K selection.
- **Feasibility (registration gate):** n_max ÷ fills/day ≤ D_c, with D_c from the r1-delta table (5/10/15¢ → 221/55/25 d) keyed to the LB edge. If this fails: UNDERPOWERED-NOT-REGISTERED. If D_c exceeds the D = 28 iteration budget, that is stated, and D_c is never shortened.
- **PASS:** the b_eff crossing. **KILL:** n_max or D_c reached without a crossing. **HARM:** the b_fut crossing, which halts via `set_family_halt_cli` (FQ is in `HALTABLE_COMPOSITION_KINDS`, `family_id_arg.py:20-22`).
- **Reporting:** PASS means "wins above price + fee", not "≥ 70 % wins". The observed win rate against 70 % is reported with a Wilson interval, descriptively only. Widen, never relax (L-12). Shadow and dry runs never count.

## 6 Tests (RED first) and gate
- C1: `test_take_margin_absent_is_byte_identical_ladder_cfg`, `test_take_margin_present_sets_constant_forecast_margin`, `test_manifest_take_margin_must_be_decimal_string`, `test_parity_pure_uses_manifest_take_margin`. Update `test_equality_covers_new_manifest_fields` (`tests/unit/test_registry_resolver_child.py:153`).
- C2: `test_ask_out_of_band_refuses_without_latch`, `test_above_edge_band_refuses_without_latch`, `test_ask_band_check_follows_calibration_version_unavailable` (a new test; the existing pin is unedited), `test_manifest_ask_band_lo_lt_hi_in_0_1`.
- Manifest: `test_existing_manifests_round_trip_byte_identical_with_new_optional_keys`, `test_new_keys_are_optional_only`. The `test_load_manifests_*` tests (`tests/unit/test_te1_label_wiring.py:721-740`) accept the new family. The file `tests/strategy/forecast_quantile_ladder/test_forbidden_imports.py` stays green.
- Gate: `scripts/ci/run_tests_no_egress.sh` on the primary tree (binding), with basetemp inside the worktree and EXIT read before any push. Brief the whole-tree guards: autonomy_*, `lint-imports` (cd into the tree), asdict scan, fee pins, exec import pin, citation map.

## 7 Pins, isolation, risks
- **NO side is a BLOCKER.** FQ subscribes D+1 YES ids only (`strategy.py:299-331`) and submits `OrderSide.BUY` IOC (`:680-687`). The `ev_net_no` branch (`decision.py:349`) is never reached live. A NO cell needs a separate reviewed plan, with `allow_short` untouched.
- **Parity-veto risk:** if the live `parity_veto` compares against `nbp_shadow_parity_pure`, an un-threaded override would trip it on every take. C1 threads it, and S0 verifies the link.
- **Starvation:** AMBIGUOUS censoring shrinks n. GAP-5 is gating, and censoring counts are disclosed.
- **Pins:** byte-pinned exec files, the x1 egress set and NO-SEND are untouched. Any edit after S5 means a new family id.
- **Binding constraints:** Nautilus Trader immutable; `allow_short` False; no safety, settlement, contract, pin or NO-SEND test weakened; operator caps never assigned; enablement untouched; existing harness only (the boundary generator and halt CLI are existing tools); holdout cl.1–cl.4; L-75 sidecars only; `iem_cli_fetch.fetch` never called; credentials never printed; no order ids in the repo.

## 8 Operator decisions
Arming only: the permit, the `live_orders_ruling` id, max daily budget and max per position. None are set here. C3 or NO routing would be a separate operator-visible plan.

## 9 Citations
- **Verified r1:** `decision.py:244-264,306-357`; `margin.py:30-37`; `config.py:160-162,197`; `composition.py:188,250` (no caller passes `ladder_cfg`); `family_manifest.py:133-148,162-164,479-526`; `gs_boundary_artefact.py:110-123`; `crh_group_sequential_boundaries.py:1-72,338-349`; `nbp_shadow_parity_pure.py:612,752`; `fq_mc_livedata.py:370`; `strategy.py:299-331`; `loss_stop_probe.py:732-763`; `decision_funnel.py:17-23`.
- **Accepted from the architect, not re-opened:** `strategy.py:680-687`; `family_id_arg.py:20-22`; the test paths in §6.
- **Not verified:** see below.

Still unverified (5):
- Whether `crh_group_sequential_boundaries.py` output is directly loadable as an FQ `boundary_artefact_path`, or whether the existing `pm_us_crh_fq_v1.json` boundary came from it. S0 checks this.
- Whether the live `parity_veto` in `FqComposedVeto` reads `nbp_shadow_parity_pure` output.
- The `prereg_precommit_check.py` CLI flags (only part of its key list was seen: `theta`, `rounding`, `per_epoch_budgets`).
- The statistic `loss_stop_probe`'s loss-stop branch computes, beyond `FqComposedVeto` ordering.
- That `app/trade.py` never passes `ladder_cfg` was inferred from a whole-`src` search for `ladder_cfg\s*=`, not from reading trade.py.
