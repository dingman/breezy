# TE-2 r3 review merge — coordinator rulings (binding on r3.1)

| Reviewer | Score | Verdict |
|---|---|---|
| domain | 88 | READY |
| python | 90 | READY |
| architecture | 89 | NOT-READY (one BLOCKER, text-sized) |
| codex | 92 | READY-WITH-CHANGES |

All findings are accepted. r3.1 is a targeted revision. The architecture and domain reviewers then run a confirmation pass.

1. **Per-boot pin by reflog, not committer time** (arch C1 BLOCKER; python R3-3).
   - Each boot is pinned to the commit the deployed branch (`feat/data-capture-and-risk`; HEAD reflog fallback) pointed to at boot time.
   - The reflog table is captured and committed at `docs/evidence/te2/REFLOG_SNAPSHOT_2026-10-01_to_10-06.txt` (reflogs expire). The resolver reads that file, not the live reflog.
   - Committer time is never the selector. Rebased branches fast-forwarded later make it unsound. Example: `4ac87414` has committer time 16:28:33Z, but reached the branch via the 17:11:31Z fast-forward to `2be63d85`.
   - Correct P7: only the 10-05 boot carries `4ac87414`; the 10-04 boot does not.
   - Correct the `20aa5ea5` touched-file list (it also touched `current_rung_hold/composition.py`) (codex F1).
   - Test #44 gains a rebased-commit fixture whose committer time is earlier than its fast-forward time.
   - Blob-sha corroboration of the manifest and artefact is unchanged.
2. **Widen the pin path set** (python R3-1). Add `src/breezy/normalize/climate_day.py`, `src/breezy/strategy/ladder_ev/` (whole package, including `f2e91fe4`), `src/breezy/ingest/nbm_quantile_actor.py`, and `src/breezy/strategy/forecast_quantile_ladder/strategy.py`. Restate the P7 commit list over the widened set.
3. **Holm testability** (python R3-2, domain M3, arch C4).
   - A member is TESTABLE only if its minimum attainable p is ≤ its Holm step-1 threshold α/k. Otherwise it is TESTABLE-CONDITIONAL, or NOT-TESTABLE.
   - The VARIANCE "TESTABLE secondary" clause requires an unconditionally TESTABLE member.
   - NOT-TESTABLE members are dropped before Holm, so k shrinks. Apply the same rule in the 6-cluster sensitivity.
   - Pin this in test #32.
4. **Testability after ties** (domain M1). Remove "tie-free" from S0-I; S0-I uses the cluster count only. In Phase B, re-evaluate testability on n after ties are dropped, using a pre-declared rule. A test that drops to NOT-TESTABLE after ties is reported as such and cannot feed the VARIANCE clause. Add a test.
5. **T-LOC null** (domain M2). Use one null: the per-day pmf-based null P(tmax > median | not tied), from the model's own pmf, collapsed to clusters conservatively. State the collapse rule, and pin it in the predeclaration.
6. **Power** (domain M4).
   - Compute cluster power as the minimum over {max-P_c, independent-union P_c}.
   - Report T-SPREAD power.
   - If secondary power is unknown, the VARIANCE label carries "weak".
7. **T-SPREAD pmf per fill** (domain M5). Use the pmf of each fill's decision cycle. A day's q is the max over that day's fills. A_c = 1 if any fill in the cluster is a tail miss.
8. **§0 expectation** (domain M6).
   - Restate the expectation for w_obs = 2 of 7 clusters: INCONCLUSIVE from non-rejection is the likelier outcome.
   - The leave-one-out recomputes w_obs on the remaining clusters when it drops a win cluster.
   - The leave-one-out sits outside the α budget. It can only block VARIANCE or add the "single-cluster-driven" label.
9. **Naming and order** (domain M7). Rename class K9 to BODY_MISS. Pin SIBLING_WON-first ordering in test #13.
10. **Low items.**
    - Fix the cite: the `BridgeUnmatched("no_trade_id")` return is at `decision_link.py:216` (python R3-4).
    - The K1b consumer becomes "closed — no action, incident already fixed (`0fe98eb4` + orders-off drop-in; HALT_POINT_2026-10-06)" (arch C3).
