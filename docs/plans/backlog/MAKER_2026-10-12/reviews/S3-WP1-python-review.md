# S3 WP1 python review (a119fd97 vs 63e1cdbb) - verdict APPROVE

Evidence: 41 focused tests pass (run_tests_no_egress.sh, both phases rc=0); ruff clean on the changed files; mypy clean on scripts/analysis/fq_loss_floor_mc_*.py; test file has 3 mypy `object` errors (floor_spec.py:446,451,453). Diff stat lists no spec_pins file, no np_bound, no fq_loss_floor_mc.py.

Scores: plan compliance 9, tests 8, conventions 9, security 10 (no I/O added), performance 8, scope 9.

## Findings
- [LOW] report.py `_day_z` re-runs `prepare_day(day)` per day per call. `_median_z` runs per alpha x epoch x mix (plus once more for `z_all_lose`). The xs is not cached. Plan wants no per-day re-derivation. Cost is small on maker cells (no `shrunk_joint` when sum(q)<=1) but it is wasted work. Fix: compute z once per (mix, path) or memoise; z does not depend on alpha.
- [LOW] `_day_z` swallows `FqLossStopRefusal` from the whole `worst_feasible_z` call. The sim only drops days on `clock_block`, which covers `prepare_day` refusals and zero_variance_realised. Both sets coincide: zero-sigma days return None in the report and never tick in the sim. A refusal raised by `step_clock` in the report would be swallowed, while the sim would raise. That is pathological and fails safe. No G1 bias found. No test pins the parity (refusing day skipped; zero-variance-realised day). Add one.
- [LOW] floor_spec.py:446-453 mypy `object` indexing on `engine.run_floor` result. Annotate `document: dict[str, Any]`.
- [LOW] `FloorSpec.__post_init__` does not reject duplicate persist modes, and `persist_for` silently takes the first. Also a persist mode that no cal row uses is accepted only if the mode is in cal (checked). Add a distinct-modes check.
- [LOW] floor_spec.py last assertion `sensitivity[0]["c"] == approx(max, abs=1.0)` is loose. The label spy assertions carry the real regression catch for site 3.

## Checks against the brief
1. Validation: mixes non-empty, canonical order, contains M-pool (`("M-pool","M-pool")` rejected since != canonical). binding not in cal rejected. Duplicate binding labels rejected. persist mode not in cal rejected, plus L>=1 and rho_p in [0,1]. Frozen + slots dataclass. Constants are immutable tuples, no mutation.
2. FQ byte-identical: all new params default to FQ values. Document hash equals the WP0 PASS_DOC_SHA256 with and without `spec=FQ_SPEC`. `floor_spec`, `g1_all_lose_z`, `z_g1`, `z_all_lose` are gated on `spec != FQ_SPEC` (equality) and `g1_path != "all_lose"`. `g1_all_lose_z` is stamped only when a context exists.
3. Three binding sites spec-driven: `outer.binding_c` (spec.mixes, spec.binding), `report.append_rows`/`evaluate_alpha` role + binding max, `finish_e2(binding=spec.binding)`. The test exercises all three (binding_c max over S8, binding-role rows, `sens|S8|persist3` labels, no `sens|S4`).
4. Persist: station factor held in a dict cleared when `day_index % L == 0`, per replicate. It is refused with rho and for L<1 or bad rho_p. The factor comes from `default_rng([seed, 0x9E15])`, created only when persist is set, so the main stream is never consumed by it. `persist=None` takes the old branch, and the golden digests (taken on 63e1cdbb) pin H0 and S5 omitted vs explicit. Persist draw is O(1) per kept station-day. No O(n^2).
5. worst_feasible_z = min(xs) over len(legs)+1 categorical outcomes, normalised via step_clock like all_lose_z. xs is passed in, so there is no circular import. `rows.py` stays free of draw imports.
6. np_bound untouched. `MIXES`, `PATH_FAMILIES`, `_CAL`, `_BINDING`, `_MIX_ORDER` are kept as FQ aliases, and np_bound's MIXES drift check still passes (np_bound tests green).
7. Test quality: CHANGE tests assert behaviour (persist block sharing, the redraw flip-rate window 0.35-0.65, a power check on the rho_p=0 comparison, and worst > all_lose equal to the one-leg-lost z). The characterisation tests would catch a regression: a stream-consuming change alters the digest; a document-key leak fails the key tests. I did not rerun the mutation evidence.

No CRITICAL or HIGH issues.
