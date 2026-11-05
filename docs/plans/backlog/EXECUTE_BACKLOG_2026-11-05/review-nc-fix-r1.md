# NC-FIX — Round 1 review merge (python-reviewer 8/8/8/7/6/8 = 7.5 NOT HIGH; architect REQUEST_CHANGES; prediction-market-reviewer REQUEST_CHANGES)

Consensus: option E (penalty-off NC + PC, opt-in pin) is the RIGHT design. B rejected correctly (N3 +0.66). Numbers match LEAK_NULL sidecar. Statistics sound. Fixes are small but several.

## Rulings
- TERMINOLOGY: "DoF-matched" is a misnomer; design is penalty-neutralised. Rename token to `penalty_off` (not `penalty_off_dof`); record the ruling in the plan.
- SCOPE: re-tag as MEDIUM (≈11 touched units across 3 source files + ~20 tests + mutations). Keep the A/B/C seams but fix the file collision (below).
- Opt-in pin and PC are justified (frozen prereg encodes the gate rule; unconditional swap changes the meaning of frozen J3/GAP-1).

## Blocking
1. REFUSAL TYPING [HIGH] (python + architect). `leak_null.Refusal` is `msb.PreregIncompleteError`, NOT the skill's `scripts.analysis.multisource_blend_refusal.Refusal`. `null_label_rows` raises it on inconsistent labels / replay mismatch / `moved_fraction < 0.5`; `plant_leak` and `NullLabels.__post_init__` raise on empty rows or bad `noise_sd_f`. Nothing catches it → traceback on a small/tied-label block (breaks AC6 "never traceback" and P6 in `_check_values`). Fix: wrap AC3/AC4 construction; map `PreregIncompleteError` → `HELD_LEAK_AUDIT` reason (or skill `Refusal`, exit 2); add a test. Drop the redundant "asserted equal to `msb.shuffle_labels`" (null_label_rows already enforces).
2. AC1 vs AC7 CONTRADICTION [HIGH]. `report` gaining `negative_control_design` in legacy mode breaks byte-identity. Emit new keys in new mode ONLY; `test_legacy_mode_byte_identical` compares against a HEAD-captured dict.
3. KEY SEMANTICS [MED]. Don't change what `negative_control` means by mode. Keep `negative_control` = the λ-pinned figure in BOTH modes; add gating key `negative_control_penalty_off` (+ `positive_control`). Downstream readers stay safe.
4. PREREG DISCIPLINE [HIGH] (pm-reviewer finding 1; architect L-59). Gate was chosen after J3 was held and validated only on the LEAK-NULL block. Plan must state: next F13 prereg freezes `penalty_off` BEFORE any look; the one-look run must not be J3's block or any block already scored; the λ-pinned reference NEVER alters a verdict (explicit no-forking-path rule). Step 5 needs a pre-verdict dry run of penalty-off NC + PC false-positive rate on the frozen GAP-2 block; if shuffled-label compute conflicts with L-59's "no labels" clause, send to peer loop rather than assume.
5. PC SENSITIVITY [MED] (pm-reviewer finding 2). L_PC 1.798 is ~250× the λ=0 bias and ~12× the ACCEPT-relevant scale (adj_lb 0.127, floor 0.064); `mean ≥ 0.005` is below the benign bias magnitude so adds nothing over `lb > 0`. The PC proves liveness, not sensitivity at the size that matters. Fix (pick one, state it): add a second planted level near the floor (noise_sd_f giving mean ≈ 0.07–0.15) and require it to flag; OR rename PC a liveness check and drop the 0.005 pin. Planting LAMP-only exercises the LAMP channel only — state as a limitation in the result `limitations`.
6. UNVERIFIED CLAIM [HIGH, L-18]. "contamination/memorisation leaks strengthen at λ=0" was never run (only a planted feature leak at λ=0 measured). Mark UNVERIFIED or remove. Evidence for the mechanism is the λ intervention (N1→N2), not the variance story; word it that way.
7. SEAM FILE COLLISION [HIGH]. Seams A and B both create `tests/unit/test_multisource_blend_nc_fix.py`. Split: `test_multisource_blend_nc_fix_stats.py` (A) and `test_multisource_blend_nc_fix_skill.py` (B, C). Run A and B in separate worktrees with PYTHONPATH; B and C serial (both edit skill.py).
8. GAP-2 §8 [MED, L-32]. PROGRESS row claims "§8 precondition met" while Confidence admits §8 unread. Read §8 (docs/plans) and cite CONFIRMS or CONTRADICTS.
9. L-24 un-injected run [MED]. Add one run of the production default un-injected against a cheap real stand-in (e.g. one fold on the real block via a `run_probe`-style path). Also a boot-time/first-use check is not applicable; a single real-artefact fold is.

## Simplifications
- Drop `_score_with`; use `_score(dataclasses.replace(ctx, settings=s0), rows, …)` (python-reviewer notes `_score(ctx, rows, **kwargs)` forwards `ctx.settings` positionally so `settings=` kwarg would collide — replace() avoids a new function).
- Parse pin with `NegativeControlDesign(value)` catching ValueError; reject non-str explicitly.

## Verified facts (use them)
- `_check_values` does NOT reject unknown pins (validates named `_PIN_INTS`/`_PIN_NUMBERS` + collections; `load_pins` reads named keys only); `content_digest`/`check_frozen_blob` cover the whole design so new pins bind under the freeze. Name `_check_nc_design` as called from `_check_values`. `_is_number` accepts ints (noise_sd_f=1 passes — state if intended).
- Registry: `scripts/ci/gate_reviewed.json` (lists test_leak_null_study.py at L238); also `gate_shards.py`, `gate_durations.json`. Replace "path as fixed in 7f1cf104" with the concrete file; say whether a `gate_durations.json` entry is required.
- `AcceptanceInputs` is frozen+slots with trailing required `negative_control`; appending defaulted fields is legal.
- scripts → `breezy.analysis.leak_null` import fine (scripts/analysis outside layers; leak_null imports only the msb facade; no cycle). Signatures `null_label_rows`, `null_settings(settings, NullId)`, `plant_leak(labels, *, seed, noise_sd_f)` match.
- Single seed adequate for specificity (N2 mean −0.0073, sd 0.0028, ~2.7 sd below 0; 95% UB on FP rate ≈14% by rule of three; FP only holds the run). If seeds added, gate on mean-over-seeds lb, never "any seed fires". PIN the seed choice in the prereg and state whether F13 `bootstrap_seed` is one of the 20 LEAK-NULL seeds. State the FP bound and cost of a spurious HELD in the risk register.
- Audit sensitivity weakens by ≈0.007 CRPS (immaterial vs 0.064 floor). Calibration and settlement-time leakage were already invisible to shuffled-label NCs (AC14) — state plainly this NC does not cover them; untouched: label-carrying feature, +60 min lag twin, embargo checks, "too good" spread check.

## Missing tests
- `PreregIncompleteError` → hold/Refusal, never traceback. Mutation (m5): PC scored under λ-pinned settings instead of s0. Explicit no-LAMP-rows → held. bool/NaN/negative `positive_control_mean_min_crps_f` refused. Byte-identity test pins the existing `negative_control` dict with fixed `gate` string.
- Memory: state peak row-copy count under the 8 GiB cap (null_label_rows builds shuffled+expected copies; plant_leak another).
- Step 5 cites `THRESHOLDS["plant_noise_sd_f"]` as the source of 1.0.

Prohibited-command scan: clean. Path hygiene: clean apart from the registry path.
