# M1v3-CONFIRM-readiness plan r4.3 — amendment to READY r4.2 (premise error: latch bound)

Every section below replaces its namesake in full, using the r4.1 numbering that r4.2 carries. Sections not listed are unchanged.

## 0. Verified facts — V8 amended; V23 and V24 added

**V8 (amended). The submit intent is a singleton.**
- `arm` refuses while any intent is OPEN (`/home/jon/breezy/src/breezy/runtime/submit_intent.py:386-422`).
- **An OPEN intent is retired only by the exec-client resolver.** The strategy has no retire path of its own and no GET schedule of its own.

**V23 (new). Resolver constants in `/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py`.** The client is byte-pinned (`_EXEC_CLIENT_SHA256`). These values are safety defence-in-depth, and **this plan never proposes changing them.**

| Constant | Value | Location | Meaning |
|---|---|---|---|
| `_RESOLVER_POLL_INTERVAL_SECS` | 5.0 s | `:587` | Base cadence of the resolver loop. |
| `_RESOLVER_BACKOFF_CAP_SECS` | 300 s | `:590-592` | Ceiling on the consecutive-failure backoff (5, 5, 10, 20 s, … per `:2604-2620`). |
| `_RESOLVER_ZERO_FILL_MIN_AGE_NS` | 120 s | `:1596`; age gate `:3088-3095` | Below this age a with-id zero-fill "stays AMBIGUOUS". Test-pinned equal to the strategy's `_REARM_MIN_DELAY_SECS`. |
| `_RESOLVER_NO_ID_MIN_AGE_NS` | 300 s | `:1604` | Earliest no-id venue read. |
| `_NO_ID_RECHECK_INTERVAL_NS` | 60 s | `:1626` | No-id re-read delay after a CONTRADICTION or INCOMPLETE result. |

What follows from these:
- A with-id zero-fill AMBIGUOUS intent cannot retire before **120 s** from creation, and in practice not before 120 s plus one pass (≥ 125 s).
- A no-id intent cannot retire before **300 s**.
- An ACCEPT_FILL retires on the first pass that sees fill evidence.
- **r4.2's latch ceiling (L = 60 s) and its strategy-side GET schedule {2, 7, 15, 30, 60} s were false premises. Both are removed.**

**V24 (new). WP-0(c0) evidence: node logs before 10-07, latency and class fields only.**

Source: `/tmp/claude-1000/-home-jon-breezy/40ab7227-004e-45e9-9c06-f7e3674039ac/scratchpad/c0/c0_orders.tsv`. To be copied into `/home/jon/breezy/docs/evidence/m1v3/` by the coordinator.

**Order counts**

| Measure | Value |
|---|---|
| Rows | 43 |
| Denied before POST | 4 |
| Posted (n) | **39** |
| Filled on POST | 32 |
| AMBIGUOUS (n_amb) | **7** |
| p_amb, point | 7/39 ≈ 0.18 |
| p_amb, Wilson upper 95% | ≈ 0.33 (z = 1.96: 0.327) |
| h_post | p50 0.169 s, p95 0.304 s |

**How the 7 AMBIGUOUS orders resolved**

| Outcome | Time | Note |
|---|---|---|
| ACCEPT_FILL | 3.2 s | — |
| ZERO_FILL | 125.4 s | — |
| ZERO_FILL | 126.1 s | — |
| ZERO_FILL | 143.5 s | — |
| ZERO_FILL | 96,823.9 s | 09-23 MIA, through GET 503s and a restart |
| Never resolved in logs | — | 2 orders |

- Resolved split: 1 accept, 4 zero.
- **Representativeness:** no order was NO at ask ≥ 0.90 (YES 36, NO 3, highest limit 0.70). Every AMBIGUOUS order was YES.

## A.2.7 Latch drop model, viability and K3 (replaces r4.2 A.2.7)

**Hold model: follows the code (R43-1).**

Each order holds the singleton latch until the exec-client resolver retires its intent.

- **Non-AMBIGUOUS order (a fill on POST):** hold = **h_post**, the measured p95, **0.304 s**.
- **AMBIGUOUS order:** two branches, with constants pinned because n_amb = 7 < 10.
  - **Accept-fill branch.** Probability **1/5**, from the observed resolved split. Hold = **5 s** (pinned; observed 3.2 s).
  - **Zero-fill branch.** Probability **4/5**. Hold = **max(150 s, code floor 120 s + one pass of 5 s) = 150 s**. This matches the empirical 125–144 s.
  - **No-id share.** Pinned at **0** in the primary model: every resolved zero-fill fits the with-id path. Informational sensitivity: the 2 never-resolved orders are treated as no-id, at 300 s + 5 s.
  - **Stuck-tail sensitivity (informational).** A 1/5 share of zero-fills holds until 13:00Z, modelled on the 96,823.9 s order. This sensitivity is never binding; K6 is the control for that case.
- **p_amb = 0.33**, measured as the Wilson upper bound from n = 39. **Caveat:** none of these orders was NO at ask ≥ 0.90, so p_amb, h_post and the branch split may not describe this family.

**Status: MEASURED.**
- n = 39 ≥ 30, so a viability STOP under this model is a **measured population finding**, carrying the representativeness caveat.
- It is not STOP-UNMEASURED. That label no longer applies under the current WP-0(c0) evidence.

**Replay.**
- Candidate arrival order comes from recorder `ts_event` on pre-window D_12Z first rows.
- For each pre-window day, run 1,000 seeded draws of the hold model. Day-level d̂ is the mean over those draws.
- Take p50 and p90 across days, plus the day-clustered SE.

**Viability STOP.**
- STOP iff **d̂_mix_p90 > 0.30**. p90 is used on purpose: it catches a bad-day population mismatch.
- **Prior:** a mean AMBIGUOUS hold of about 121 s (0.2·5 + 0.8·150) at p_amb up to 0.33 gives a mean per-order hold of about 40 s. On roughly 70% of days, one of the first three orders goes AMBIGUOUS and blocks the latch for 150 s while the 12:00Z burst arrives. So **d̂_p90 > 0.30 is expected**, and the viability check runs first (§C.7).

**τ_drop** (typical-day monitoring):
`τ_drop = min(0.40, d̂_mix_p50 + max(0.10, 2·SE_day))`

K3's drop test is cumulative since activation and is evaluated only once candidates ≥ 60.

All of these are frozen in §B: the constants, h_post, p_amb, the branch split, the procedure and the thresholds.

## A.3(l) (replaces r4.2 A.3(l))

**(l)** After the read, none of the following may change:
- any K1–K7 threshold or formula;
- any hold-model constant: h_post, p_amb, the branch split, the accept-fill and zero-fill holds, the no-id share;
- the drop procedure;
- any §B parameter.

**The exec-client resolver floors (V23) are never lowered**, whether to improve viability or for any other reason.

## A.5 (replaces r4.2 A.5)

Every outcome other than CONFIRM shelves the family. That covers:
- NO-EDGE, UNDERPOWERED or INVALID;
- PENDING_TRUTH past 12-21;
- a §B FAIL;
- a **Stage −1 viability STOP**, which is recorded as a **measured population finding** with the V24 representativeness caveat;
- an unratified WP-4;
- any WP-0 or M5 STOP;
- a peer rejection.

**Effects of shelving:**
- The manifest stays DRAFT, or is removed by a reviewed commit.
- No allowlist row is added.
- The code stays inert and unmerged.
- The drop-in stays.
- Nothing goes live.
- PROGRESS records it.
- Any re-test needs a new prereg and a new plan.

## A.6 Parity — two rows replaced

| Dimension | Screen | Live | Disclosure |
|---|---|---|---|
| Take-all vs serial latch | Every qualifying rung-day | Drop-not-queue. An AMBIGUOUS intent holds the singleton latch for **≥ 120 s** (zero-fill floor) or **≥ 300 s** (no-id), until the exec resolver retires it (V23). | d̂_mix p50/p90 and post-drop takes per day are entered at the §B freeze. The viability STOP at p90 > 0.30 is the measured outcome. |
| Latch-input representativeness | — | p_amb, h_post and the branch split come from 39 pre-10-07 orders. They were YES 36 / NO 3 with limits ≤ 0.70, and **none was NO at ask ≥ 0.90**. Every AMBIGUOUS order was YES. | The measured rates may not represent this family. Stated with every viability result. |

## B.1 Stage −1 and viability rows (replaces r4.2's Stage −1 and Viability rows)

| Element | Value |
|---|---|
| **Stage −1** | Uses pre-window data only, committed before the freeze. Reports:<br>• path ticks and S;<br>• the K4 inputs;<br>• the K5 reference;<br>• exclusion and feasibility counts;<br>• recorder-`ts_event` arrival order and gaps, with the share arriving 12:00:00–05Z;<br>• **the hold-model inputs from V24 and A.2.7**: h_post 0.304 s; p_amb 0.33; accept-fill 1/5 at 5 s; zero-fill 4/5 at 150 s; no-id 0. Each is labelled with its source (measured or pinned), n = 39 and n_amb = 7;<br>• the no-id and stuck-tail sensitivities;<br>• d̂_mix p50/p90 and SE_day;<br>• τ_drop;<br>• measured λ₄;<br>• post-drop takes per day, λ₄·(1 − d̂_mix_p50). |
| **Viability** | **STOP iff d̂_mix_p90 > 0.30.** This is a measured population finding, with the V24 caveat. It is **run first**, before any other early spend (§C.7). Condition 2 (post-drop takes against the takes-needed figure) stays informational. |

## B.3 `nolong_d12_stage_minus1.py` RED tests (replaces r4.2's list for that module)

Unchanged from r4.2:
- `test_nb_fit_moments`
- `test_nb_poisson_fallback_when_alpha_le_0`
- `test_rho_floored_at_zero`
- `test_alpha_prime_mapping`
- `test_nb_two_sided_tail_min_cdf_sf`
- `test_dmix_day_mean_over_1000_seeded_draws_p50_p90_across_days`
- `test_p_amb_wilson_upper`
- `test_tau_drop_formula_capped_at_040`
- `test_viability_stop_when_dmix_p90_gt_030`
- `test_viability_condition2_informational_when_no_takes_needed_field`
- `test_p_amb_by_ask_band_reported`
- `test_refuses_any_input_on_or_after_2026_10_07`
- `test_log_reads_pre_1007_field_allowlist_and_date_filter`

Removed (false premise):
- `test_ambiguous_hold_empirical_quantised_to_get_offsets_capped_60`
- `test_min_history_30_else_fallback_and_point_estimate_both_run`
- `test_stop_unmeasured_label_when_only_fallback_trips`

New (R43-1):
- `test_hold_model_two_branch_accept_1_5_at_5s_zero_4_5_at_150s`
- `test_zero_fill_hold_is_max_150_or_floor_plus_one_pass`
- `test_no_id_share_zero_primary_and_sensitivity_reported`
- `test_stuck_tail_sensitivity_informational_never_binding`
- `test_hold_model_constants_match_exec_client_source_ast`: parses `client.py` as text with `ast`, **without importing it** (avoids the exec import pin), and asserts 120 s, 300 s and 5.0 s.
- `test_viability_result_labelled_measured_with_representativeness_caveat`
- `test_no_hold_shorter_than_resolver_floor_for_zero_fill_branch`

## C.WP-0 (c) and latch policy (replaces r4.2 WP-0(c) and its "Latch ceiling" paragraph)

**(c) Latch mechanics.**
- **(c0) DONE.** The evidence is V24.
- The code reading is DONE. The facts are V23.
- **Nothing in this plan changes the resolver.**
- **Shadow measures no order latency.**

**Latch policy: follows the code.**
- There is no strategy-side ceiling and no strategy-side GET schedule.
- The OPEN intent is retired only by the exec-client resolver:
  - **with-id ZERO_FILL** at age ≥ 120 s;
  - **ACCEPT_FILL** as soon as fill evidence appears;
  - **no-id** at ≥ 300 s (rechecked after 60 s on CONTRADICTION or INCOMPLETE).
- Cadence is the 5.0 s base poll with consecutive-failure backoff capped at 300 s (V23).
- K6 bounds a stuck intent.

## C.WP-1 latch policy and tests (replaces r4.2's WP-1 latch paragraph and two test names)

**Latch policy.**
- Orders are serial: arm, then POST.
- Retirement is done **only** by the exec-client resolver (V23).
- A candidate that arrives while an intent is OPEN is dropped and counted, never queued.
- The strategy adds no GET calls and no retire path.
- The digest records, per AMBIGUOUS intent: `intent_age_at_retire` and `resolver_branch` (accept, zero with-id, or no-id).

**Test changes:**

| r4.2 test | r4.3 replacement |
|---|---|
| `test_ambiguous_get_retire_offsets_and_60s_bound` | `test_intent_retired_only_by_exec_resolver_no_strategy_get_schedule` |
| *(new)* | `test_strategy_never_retires_or_resolves_intent` |
| *(new)* | `test_strategy_does_not_reference_resolver_min_age_constants`: an AST scan of `strategy/no_longshot_d12/` |

All other WP-1 tests are unchanged.

## C.WP-5 K6 and threshold test (replaces r4.2 K6)

**K6 (R43-1). Halt iff either:**
- an intent is still **OPEN at 13:00Z**; or
- an intent's age exceeds its **resolver floor + 600 s**. With-id that is 120 + 600 = 720 s; no-id it is 300 + 600 = 900 s.

**Why K6 exists.** The 09-23 MIA order stayed AMBIGUOUS for **96,823.9 s**, through GET 503s and a restart (V24). An intent like that stops all entries on the node.

**What K6 does and does not do.**
- It halts the family's new entries only.
- It never retires the intent. Retirement remains the resolver's job, or a reviewed act backed by venue evidence (D.5).

**Threshold test changes:**

| r4.2 test | r4.3 replacement |
|---|---|
| `test_k6_unresolved_ambiguous_halts` | `test_k6_open_at_1300z_or_age_gt_floor_plus_600_halts` |
| *(new)* | `test_k6_never_retires_intent` |

## C.7 Effort and schedule: sequencing amendment (replaces r4.2's early-phase ordering)

**Viability first (R43-1).** Before any other early spend, build and run the **Stage −1 viability slice**, made up of:
- pre-window D_12Z first-row arrival extraction from recorder `ts_event`, with the date filter applied before any read;
- the V24/A.2.7 hold-model replay;
- d̂_mix p50/p90.

This is about 1.5 d build plus 0.5 d review, starting 11-09.

**If STOP:**
- Shelve under A.5 and record it as a measured population finding.
- **No other early work starts.** That covers the rest of WP-A, WP-4 on its branch, WP-1 `decision.py`, the WP-5 guard reshape, and every 11-20 branch build.
- Total sunk cost is about 2 agent-days.

**If PASS:** continue the r4.2 schedule unchanged. The viability slice counts toward WP-A's 6.5 d.

**Prior.** STOP is the expected outcome (A.2.7).

## C.9 Slip policy: addition

- **The viability slice gates all other early work.**
- If it slips past 11-12, the §B freeze date of 11-20 moves accordingly. The freeze must still come before the binding run and the read; if it cannot, the plan shelves.

## D.4 First-day check: one bullet replaced

| r4.2 bullet | r4.3 bullet |
|---|---|
| "every AMBIGUOUS resolved within 60 s, or K6" | **"Every AMBIGUOUS intent is retired by the exec-client resolver (with-id zero-fill at ≥ 120 s, accept-fill on evidence, no-id at ≥ 300 s), or K6 has fired. Each retirement's `intent_age_at_retire` and `resolver_branch` are logged in the digest."** |

## E. Risks: R5 and R14 replaced

| # | Risk | Sev. | Mitigation |
|---|---|---|---|
| R5 | Burst drops. The resolver floors (V23) hold the singleton latch for ≥ 120 s per AMBIGUOUS order. **The viability STOP is the expected outcome** (A.2.7 prior). | **High, likely terminal** | Viability runs first (§C.7), so a STOP costs about 2 agent-days. The floors are never lowered. τ_drop is capped at 0.40. |
| R14 | Latch-input representativeness. n = 39 is ≥ 30, so the result is MEASURED. But **no order was NO at ask ≥ 0.90**, and every AMBIGUOUS order was YES. n_amb = 7 forces pinned branch constants. The 150 s zero-fill hold understates stuck tails like the 96,823.9 s order, which K6 bounds. | High | The caveat travels with every viability result. No-id and stuck-tail sensitivities are reported. |

## F. Expected value: one caveat replaced

The r4.2 (R14) caveat is replaced as follows:
- **Under the measured hold model (V23, V24), the most likely outcome is a Stage −1 viability STOP**, at a sunk cost of about 2 agent-days, before any other early spend.
- The rest of the cost estimate (about 30 agent-days) applies only if viability PASSes.

## §R4.3 changelog

| ID | Section(s) changed |
|---|---|
| R43-1 (remove L = 60 s and the GET schedule; resolver-only retirement) | §0 V8; §C.WP-0(c) and latch policy; §C.WP-1 latch policy and test rename; §D.4 bullet |
| R43-1 (resolver cadence with file:line) | §0 V23 (`client.py:587`, `:590-592`, `:2604-2620`, `:1596`, `:3088-3095`, `:1604`, `:1626`) |
| R43-1 (two-branch hold model; pinned constants because n_amb < 10) | §A.2.7; §B.1 Stage −1 row; §B.3 new tests |
| R43-1 (p_amb measured, caveat kept) | §0 V24; §A.2.7; §A.6 row; §E R14 |
| R43-1 (K6 rewrite; the 96,823.9 s order) | §C.WP-5 K6 and tests |
| R43-1 (MEASURED, not STOP-UNMEASURED) | §A.2.7 status; §A.5; §B.1 viability row; §B.3 removed tests and `test_viability_result_labelled_measured_with_representativeness_caveat` |
| R43-1 (viability first; expected-STOP prior) | §A.2.7 prior; §C.7 sequencing; §C.9; §E R5; §F |
| R43-1 (never lower the floor) | §0 V23; §A.3(l); §C.WP-0(c); §E R5 |
| R43-2 (new V23; V8-type facts updated) | §0 V8, V23, V24 |
| R43-2 (every L = 60 s reference and test name fixed) | §A.2.7, §A.3(l), §C.WP-0, §C.WP-1 (`test_ambiguous_get_retire_offsets_and_60s_bound` replaced), §C.WP-5 (`test_k6_unresolved_ambiguous_halts` replaced), §B.3 (`test_ambiguous_hold_empirical_quantised_to_get_offsets_capped_60` removed), §D.4, §E R14 |

**Not satisfied, or choices made:**
1. **Section text.** I have not seen r4.2's committed text, so this delta replaces sections by their r4.1 numbering, which r4.2 is understood to carry. If r4.2 renumbered anything, the coordinator should remap the headings.
2. **No-id share pinned at 0 in the primary model.** The ruling left this open ("if any"). All four resolved zero-fills fit the with-id path. The 2 never-resolved orders are covered only by an informational sensitivity, so the primary model may understate holds if they were no-id.
3. **Stuck tails are a sensitivity only.** The 150 s zero-fill hold does not model stuck tails like the 96,823.9 s order; that case is informational and K6 is its control. A binding stuck-tail branch would only make the expected STOP more certain.
4. **Constant check by text, not import.** The model's constants are checked against the exec client by parsing its source with `ast`, not by importing it. Importing would trip the exec import pin. That means a renamed constant fails the test rather than being followed automatically.
