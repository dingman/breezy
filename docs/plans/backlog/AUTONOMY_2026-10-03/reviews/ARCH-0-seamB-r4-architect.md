**Verdict: APPROVE.** Every item in the plan body is resolved, and the plan needs no further round. **E-7d: ADOPT. E-7e: ADOPT-WITH-AMENDMENT.** Two E-9 lines in E-7e(f) promise a "re-check" that will fail for certain. Both are wording fixes and are given exactly below. Apply them when filing; they do not need re-review.

## Per-N status (checked against the r4 text)

| N | Status |
|---|---|
| N1 | **Closed.** Covered by the AC-9.4 budget (process-group kill, `skipped`, file always written), the required `-` prefix on the pre line, the M35 lint `B+5 < TimeoutStartSec`, the AC-9.6 mapping, and V21 end to end. |
| N2 | **Closed.** AUT-2 l.408/953, AUT-3 l.267, AUT-6 l.1046 and AUT-5 l.277 are confirmed. I was wrong in r3 about AUT-2 l.423/463: the `slot_guard` `ExecCondition` sits on `breezy-score-live-trials.service` (AUT-2 l.813), so it is correctly "not owned". |
| N3 | **Closed.** (a) `RUN_TRANSIENT_SHOW_ARGV` uses `run-*.service`, which also correctly avoids matching mounts (M40). (b) Moot, because the drill now runs unwrapped (B4-R2). (c) The grammar is fixed. |
| N4 | **Closed.** The `touch` line keeps the inode (M33), and `%t` expands in unit files (M36). |
| N5, N7, N8, N9, N11 | **Closed.** |
| N6 | **Partial.** The per-unit table exists, but two of its rows contradict the bounds they cite (blockers B-1 and B-2 below). |
| N10 | **Closed.** The work is serialised, and the three-way split is stated as a deviation from B4-R8. One V-step is placed in the wrong WP (non-blocking item 1). |

**Spot-check of 14 cites, all correct:**
- AUT-2: l.408 (label unit `breezy-study-failed@`), l.953, l.423.
- AUT-3: l.267.
- AUT-6: l.247/250 (PROC rows), l.276, l.958–962, l.1027, l.1046, l.1071 (`IN_PROCESS_STUDIES_LOCK_UNITS`), l.1174 (V-6 expects in-row reads to equal outside).
- AUT-1: l.905 and l.881.
- AUT-5: l.277.
- AUT-4: l.637/848/1311 already name `breezy-autonomy-failed@`.
- AUT-7: 0 hits.

**Missed consumers (L-46):**
- **AUT-2 l.1199** says "The label unit keeps `OnFailure=breezy-study-failed@` (the §5.2 studies rule)". It cites frozen ARCH §5.2 l.1066 ("Studies … with `OnFailure=breezy-study-failed@`"). E-7e(f) reverses this rule, but nowhere says it supersedes the ARCH text. E-7a (errata l.142) implies the change but does not name the conflict, so the AUT-2 implementer has a citable reason to refuse.
- **AUT-1 hits not classified:** l.147, 167, 222, 602, 738, 1015, 1044, 1579 and 1598 are in neither list. I read l.857–858; they are descriptive and do no harm. Still, the claim "every hit classified" is a small L-47 overclaim.

## WP table

- **Sizes and order:** 7 WPs, sum ≈ 5,720 lines (the arithmetic checks out), largest about 1,000. The order B2a → B2b-1 → B2b-2 → B2b-3 → B2c → B3 is serial, and B1 runs in parallel.
- **Registry:** +1 file each at B2a, B2b-3, B2c and B3, giving 4. Correct.
- **Three-way B2b deviation:** stated, and justified by the ≤ ~1,000-line rule.
- **V-step placement:** V0 (B2a), V4/5/9 (B2b-2), V1–3/6–8/12/14–16/18–20 (B2b-3), V17/21 (B2c) and V10/13 (B3) each match what that WP ships. The one exception is V11 (non-blocking item 1).

## E-9 / M35 consistency

- **The M35 rule itself is right.** `TimeoutStartSec` re-arms per command, so the end bound is the sum of `T+K` over the pre lines, plus the main line, plus `TimeoutStopSec`. Every pre-line bound is below its unit's `TimeoutStartSec`:
  - failed@: 15 < 30
  - health: 20 < 115
  - daily: 20 < 1500
  - audit: 15 < 1500
- **The applied numbers are where it goes wrong:**

**B-1 (blocking for filing): E-7e(f), AUT-3 bullet.**
- **Problem:** reproduce-am's worst end is exactly 10:45:00Z (09:35:00 + 1 + 4139 + 60; AUT-3 l.271, AUT-4 l.642), so it has zero margin. The new `touch` line adds 5 s, giving 10:45:05. That fails `test_pre_offline_studies_units_end_by_1045z` once the test counts pre lines, which E-7e(f)'s "every plan" bullet requires. "Re-checks the 10:45Z bound" therefore promises a check that will fail.
- **Fix (replace the parenthetical):** "(+5 s; reproduce-am `TimeoutStartSec` 4139 → **4134**, so 09:35:00 + 1 + 5 + 4134 + 60 = 10:45:00Z, and the AM eligibility threshold becomes `runtime_s × 1.2 + 600 ≤ 4134`, i.e. `runtime_s ≤ 2945`; AUT-4's K8 test sums pre lines.)"

**B-2 (blocking for filing): E-7e(f), AUT-6 health E-9.**
- **Problem:**
  - Frozen ARCH §5.2 l.1089 bounds `aut6.health` at "≤ 120 s / start + 120 s". AUT-6 already sits exactly on that bound (start + 115 + 5).
  - The snapshot line adds 20 s.
  - The consumer table adds an `install -d` pre line for `cache/aut6_health_bus`, but its bound is missing from the sum. So "+20 s" is too small, and "re-check" fails.
- **Fix (replace the health clause):** "health ≤ start + `T+K`(install) + 20 + 115 + 5 s (≤ start + 145 s); **this erratum amends ARCH §5.2 l.1089 `aut6.health` to '≤ 145 s | start + 145 s'**. The 16:31/16:41/16:51/17:01 passes end ≤ +146 s from the slot, before the next slot, and the pass is read-only. `HEALTH_PASS_BUDGET_S=90` is unchanged."
- **Also add to E-7e(f) "Every plan":** "This supersedes ARCH §5.2 l.1066's `OnFailure=breezy-study-failed@` for autonomy-owned studies (E-7a rule 1); AUT-2 l.1199 is amended accordingly."

## Non-blocking

1. **V11 is in the wrong WP.** It is listed under B2b-2, but it needs `WRAPPER_CODE_FILES` from `write_sites.py`, which ships in B2b-3. Move V11 to B2b-3.
2. **Two WPs both claim the AC-5 snapshot pre-line form.** The test and the "accept without `-`" mutation are in B2b-2, while B2c's scope also says "AC-5 snapshot form". Name B2b-2 as the owner.
3. **AUT-1 audit E-9.** `13:50 + 60 + 15 + 1500 + 5 = 14:16:20` leaves out the `flock -w 600` wait. That is only correct because the flock runs inside ExecStart's `timeout` (AUT-1 l.876), whereas AUT-1 l.874 and l.881 add the flock wait separately (14:25 = 13:50 + 600 + 1500). State which basis is used: "flock inside ExecStart's `timeout` (≤ 1500), so it is not added; AUT-1 l.881 restated".
4. **Daily and failed@ sums leave out the `install -d` line.** The daily figure 05:56:30Z cannot be derived from the inputs (05:55:06 + 20 + 5 + install ≈ 05:55:36). It is conservative and harmless, but show the derivation. failed@ should read "≤ 20 s before its page".
5. **The health `show -- 'breezy-*'` read also returns timers and slices (M40).** AUT-6 should filter on `Id` ending in `.service`.

## E-7d
**ADOPT as written.** Rules 1–5 match the script and the plugin:
- the confirm-file omission rule;
- `env -u` covering `PYTEST_PLUGINS` and `PYTEST_ADDOPTS`;
- the condition-6 `-p` allowlist (the plugin, `no:randomly`, `no:cacheprovider`).

The residual is stated honestly, and the Supersedes clause is correct.

## Scores
| Axis | Score |
|---|---|
| Correctness | 8 |
| Fit | 9 |
| Test coverage | 8 |
| Risk mitigation | 8 |
| Scope minimality | 8 |
| Feasibility | 9 |

Files:
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamB_plan_r4.md` (l.402, 482–501, 717, 741)
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUTONOMY_ARCHITECTURE.md` (l.1066, 1089)
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-3-retraining_plan_r6.md` (l.271)
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r11.md` (l.642)
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-6-drift-health_plan_r15.md` (l.1027–1064)
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-2-outcome-labeling_plan_r7.md` (l.1199)
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-1-data-capture_plan_r12.md` (l.874–881)