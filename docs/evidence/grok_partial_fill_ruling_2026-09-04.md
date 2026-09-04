# Grok (strategy lead) ruling — partial fills, win labelling, provenance, clock (2026-09-04)

**Provenance.** `grok --prompt-file` (grok-4.6, read-only plan mode, no subagents, no terminal), brief at the coordinator scratchpad `grok_partial_fill_brief.md` (questions Q1–Q5 reproduced in the ruling). Exit 0; raw output below, narration preamble removed.

---

v1 is **silent** on `q ≠ 1` (only UNVERIFIED, §9.4:174). The registered unit is a **1-contract IOC buy** (§1:24–25; §3:58; `order_quantity=1` §3:63; `Take.quantity = config.order_quantity` at `decision.py:302–303`). Scoring is `pnl_i = 1\{held_i\} − fill\_px_i − fee_i` per contract, implicit `q=1` (§4:84). Conservative reading that never inflates `n` or `k`: a fill with `q ≠ 1` is **not** the unit. Exclude it (`excluded_reason=partial_fill` or fail-closed admission); **not in** Wilson `n`/`k`, **not in** stop-rule `ΣPnL`; report in a coverage table. (a) is rejected: `n += 1` on a fractional lot inflates `n` (and `k` if held) toward 60/150. Constraint: v1 tally code (`live_family_tally.py`) unmodified; enforcement is fail-closed **before** `score_trial` (do not rewrite frozen §4).
**Zero-fill:** **not a trial.** Latch is terminal (`strategy.py:455–468` consume `reason="taken"` before `_maybe_submit`; `RetirementReason.ACCEPTED_ZERO_FILL_TERMINAL`; blueprint:28 IOC miss, no retry) — same shape as a failed take consuming the day without entering `n` (§2:43–44). Wilson `n` = scored filled Takes only (§4; tally priced rows). Skip-days are not Wilson zeros (§2:45–47); an IOC miss is not either. Structural-dead “filled Takes ≈ 0” (§5:105–106) is **not** defeated by a miss.

**Q2. ACCEPT-WITH-CONSTRAINTS — (c) refuse the row; reject (a) and (b).**
v2 inherits the 1-contract filled-Take unit (v2 §3:45–48; v1 §3:58). Statistic (C) is unweighted Bernoulli on that unit:
\[
S_k=\frac{\sum_{i\in\mathcal{A}}(held_i-BE_i)}{\sqrt{\sum_{i\in\mathcal{A}}BE_i(1-BE_i)}},\quad I_k=\sum_{i\in\mathcal{A}}BE_i(1-BE_i),\quad t_k=\min(1,I_k/40)
\]
with \(\mathcal{A}=\{i: q_i=1\}\) and looks on \(n_k=|\mathcal{A}|\) at 10, 20, …, 160. A `q<1` row: \(\Delta n=\Delta k=\Delta I=\Delta S=0\); coverage table only. **Information:** each admitted row has \(\mathrm{Var}(held_i)=BE_i(1-BE_i)\le 1/4\), so \(I_{\max}=n_{\max}/4=40\) (v2 §3:55–60) stays the exact Bernoulli bound, not a loose envelope. (a) rejected: a fractional lot would count as one look and accrue full \(I_i\), inflating \(n_k\) and \(t_k\). (b) rejected: \(held_i\mid ask_i\sim\mathrm{Bern}(BE_i)\) is qty-invariant; \(q\)-weights would amend (C) and make \(I_{\max}=40\) a bound rather than the pin. Register `q_i=1` as a v2 admission predicate before D0; never touch v1.

**Q3. ACCEPT (v2-only, fail-closed, no relabel).**
v2 may refuse any candidate row with \(held_i \neq 1\{pnl_i>0\}\), \(pnl_i=1\{held_i\}-fill\_px_i-fee_i\) (v1 §4:84). Do **not** rewrite `held_i`. \(S_k\) stays (C) on surviving rows. For admitted `q=1` and `0.05<ask<0.95`, disagreement is malformed or `fill_px+fee\ge 1` (held but not a win). Dropping those rows cannot inflate `k`. Not a v1 change (`live_family_tally.py` / `trial_scorer.py` v1 path untouched).

**Q4. ACCEPT-WITH-CONSTRAINTS.**
v2 tally may require `provenance=="live"` **in addition to** `trial_id` prefix `current_rung_hold/trial/…` **and** `climate_day ≥ d0_climate_day` (v2 §8:176–197). Refuse rows missing the column or not `"live"`. Constraints: v2 store/tally path only — do **not** add a field to v1 `ScoredTrial` / 17-column schema (`trial_scorer.py:119–138`; `scored_trial_store.py:53–72`); prefix check is AND, never replaced; values are `{live, paper_replay}` only; **venue column stays forbidden** (ruling E; v2 §6:139–148).

**Q5. Plan stands; no change to kill/survive floors, \(n_{\max}\), \(\alpha\), or \(I_{\max}\).**
Polymarket.us lists only daily-HIGH ladders on NYC/SFO/MIA/MDW/LAX (enumeration 20260904T222013Z); NYC is already excluded (v1 §2:32–34), so this venue has **no station lever**. The PM family clock remains the four dense stations at the already-registered rates (optimistic ~2.73 taken/day → D0+22/D0+55; pessimistic ~1/listed-day → D0+165; v1 §6:121–131). M_B `n_taken=2`, `k=0` at the live 30/45 min arms is UNDERPOWERED, not a kill, and is the UNVERIFIED selector-survival risk already registered (v1 §9.4:172–174) — it does not rewrite floors or the D0+165 truncation. Kalshi remains the only clock lever (new stations, own PREREG, never pooled; v2 §8:199–204). Register v2 before the first PM fill (live `n=0`); do not start a new PM family from these facts.

RULING: Q1 (b) exclude `q≠1` + zero-fill not a trial; Q2 (c) refuse `q<1`, \(I_{\max}=40\) holds; Q3 ACCEPT fail-closed `held==(pnl>0)`; Q4 ACCEPT-WITH-CONSTRAINTS `provenance=="live"` AND prefix, v2-only; Q5 plan stands.
