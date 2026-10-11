VERDICT: NOT-READY
SCORE: 74/100

| ID | Sev | Finding | Evidence file:line | Required change |
|---|---|---|---|---|
| F1 | BLOCKER | Most likely way the plan fails to classify all 25 fills: the Take join premise is wrong or fragile. Take logs carry no `client_order_id`. `decision_link` joins fill to filled to init by client id, then joins to the Take by instrument and time window. The plan also lets up to 2 fills stay unjoined, which contradicts "all 25". | `decision.py:200-212`; `decision_link.py:220-235`; `TE-2_plan_r1.md:16-17,94-96` | Rewrite S0-C so it does not join Takes by `client_order_id`. Require 25 of 25 exact Take attribution, or define an explicit UNCLASSIFIED/STOP outcome. |
| F2 | MED | The "memory entry" part of P13 was not found in `MEMORY.md`. The named lessons do exist. | `TE-2_plan_r1.md:74`; `docs/core/LESSONS.md:8,67,871,1384,1610` | Cite a repo-local lesson or evidence file instead, or mark the memory entry as non-binding context. |

Data claims:
- **Take and fill counts (verified):** 32 Take lines and 25 OrderFilled, found in `/home/jon/.local/share/breezy/logs/...`.
- **Log path (refuted):** the plan's repo-root `logs/breezy-trade-202610*.log` glob does not exist.
- **Durable store:** it holds 34 fills, 25 of them October FQ.
- **`derived/nbp` (verified):** it has no October rows. `derived/nbp/2026` stops at 09 and `derived/nbp5/2026` stops at 06.
- **Truth coverage (verified):** it runs through 2026-10-10, per the CSV and `coverage.json`.

Premise checklist:
- P1 verified: `decision.py:216-218,277-281,331,349,353-355`.
- P2 verified: `decision.py:200-212`. The slippage claim is in the audit at `TRADE_EFFECTIVENESS_2026-10-11.md:26-27`.
- P3 partially refuted. The counts hold, but the repo-root log glob is absent and "join to Takes by client_order_id" is refuted by `decision.py:200-212` and `decision_link.py:220-235`.
- P4 verified: all 32 Take `now_ns` values had 2 SHADOW_DECISION rows. Plan premise at `TE-2_plan_r1.md:40-41`.
- P5 verified: `fill_source.py:58-82`; `client.py:988-1064`; `decision_link.py:1-17`; `fq_scorer.py:1-14`; `instrument_facts.py:72-115`.
- P6 verified: `pm_us_crh_fq_v1.json:5-18`; `NBP_S2_VALIDATE_RESULT_2026-09-30.md:7,14,17,22-29,72-80,128-132`.
- P7 verified: `nbp_calibration.py:273-278`.
- P8 verified: `nbp_shadow_parity_pure.py:97-132`.
- P9 verified: `nbm_quantile_actor.py:210-218,223-238`. TXN uncertainty is at `NBP_TXN_WINDOW_AND_BBB_NOTE_2026-09-29.md:42-53`.
- P10 verified for truth coverage. The M1-v3 window guard is at `M1v3-CONFIRM-readiness_plan_r4_2.md:23,251`.
- P11 verified. No `*/10*` directories exist under `derived/nbp` or `derived/nbp5`. The availability ledger is JSONL of seen/miss records.
- P12 verified: `RULING_FQ-v2-NO-TRADE_2026-10-08.md:48-50`; `PROGRESS.md:102-104`; `F13-source-breaks-proposal_2026-10-09.md:48-54`.
- P13 partially verified. The lessons are at the lines in F2. The memory-entry subclaim was not found in `MEMORY.md`.