# Grok (strategy lead) acknowledgement — PREREG v2 registration choices C1–C4 (2026-09-05)

**Provenance.** `grok --prompt-file` (grok-4.6, read-only plan mode, no subagents, no terminal); memo at the coordinator scratchpad `grok_registration_memo.md` (disclosed: fill-time look ordering via `fill_order.jsonl`; store-level provenance sidecar + station census; q≠1 admission exclusion and the `held == (pnl > 0)` guard; the values-free daily supervisor). Exit 0; raw output below, narration removed.

---


\[
S_k=\frac{\sum_{i\in A_k}(held_i-BE_i)}{\sqrt{\sum_{i\in A_k}BE_i(1-BE_i)}},\quad I_k=\sum_{i\in A_k}BE_i(1-BE_i),\quad t_k=\min(1,I_k/40)
\]

with \(A_k=\) first \(n_k\in\{10,\ldots,160\}\) filled Takes, \(I_{\max}=40\), two one-sided \(\alpha=0.025\). \(S_k\) and \(I_k\) are commutative on a fixed set; `boundary_for(t_history)` is path-dependent, so order can move \(b_k\) — that is the realized information path, not a new score. §7 “every 10 filled Takes” is fill time; `(climate_day, trial_id)` was an unregistered 17-column proxy. Sidecar `{trial_id, score_seq, filled_at_ns}` + fail-closed missing entry leaves `ScoredTrial` untouched and cannot inflate \(n\). Concur: no statistic changed.  
**ACKNOWLEDGE**

**C2.** Q4 required `provenance=="live"` **and** prefix **and** `climate_day ≥ d0`, without a 17th-column field and without a `venue` column. Store-level `provenance.json={"provenance":"live"}` (live scorer only, even at 0 rows; paper never writes; mismatch refuses) is the schema-preserving form. Empty store + no sidecar → \(n=0\) cannot contaminate Type I; rows + missing/wrong sidecar still refuse. Station census (`LAX,MDW,MIA,SFO`, NYC out) is the existing `assert_family_only` identity check, not a new sequential axis.  
**ACKNOWLEDGE**

**C3.** Q1/Q2: \(\mathcal{A}=\{i:q_i=1\}\); \(0<q<1\) `partial_fill` and \(q>1\) `multi_fill` excluded **before** `score_trial`; \(q\le 0\) `malformed_input`; coverage table; \(\Delta n=\Delta k=\Delta I=\Delta S=0\); \(I_{\max}=40\) stays the Bernoulli pin. Q3: v2 refuses `held != (pnl > 0)` on the whole tally (stricter than row-drop; `held` not rewritten). `(trial_id, score_seq)` collision refuse is fail-closed integrity, not a weighting change. Tally `getattr(qty)` is a no-op on the frozen schema by design; admission is the binding gate.  
**ACKNOWLEDGE**

**C4.** `breezy-trade-supervisor`: `STOP_PRIOR_UTC=16:40`, `LAUNCH_UTC=16:50`, `SELF_CHECK_UTC=17:05`; SIGTERM only (`terminate` never SIGKILL); one process per UTC day; values-free (no `orders_enabled`, `allow_short`, budget, or per-position assignment). L-26 ops fix after the 21:42 UTC session SIGTERM. No change to (C), look schedule, floors, live enablement, or the NO-SEND firewall.  
**ACKNOWLEDGE**

RULING: C1–C4 ACKNOWLEDGE; statistic (C), \(I_{\max}=40\), two one-sided \(\alpha=0.025\), LD-OBF, v1 byte-identical, `allow_short=False`, and NO-SEND all stand.
