# R-8 OPERATOR RUNBOOK — from build-side "done" to the first live-small order (2026-09-04)

Scope: every OPERATOR-ONLY step, in order, between the build side declaring R-7 complete and the
first real order. Sources: `docs/plans/EXEC_SPINE_NEXT_2026-09-04.md` §A rows OP-1..OP-4 and §D;
`docs/plans/EXEC_SPINE_R65_R7_2026-09-02.md` §1 D1/D2 and §5; `scripts/venue/polymarket_us_write_signing_probe.py`;
`src/breezy/adapters/polymarket_us/safety.py:133`; `src/breezy/adapters/polymarket_us/operator_controls.py`;
`docs/core/PROGRESS.md` "Operator control contract"; `docs/plans/CURRENT_RUNG_HOLD_BLUEPRINT_2026-09-04.md` §7 + CONVERGED.

Naming rule, binding on this file: the live-trading enablement variable, the maximum daily budget and
the maximum per position are referred to BY ROLE only. Their environment-variable names are never
written here and their values are never written anywhere in this repository
(`operator_controls.py:22-40`, scanned by `tests/unit/test_operator_control_assignment_scan.py`).

## 0. Preconditions the build side must have met

| # | Precondition | Proof | State (2026-09-04) |
|---|---|---|---|
| 0.1 | R-6.5a — status+body carried across the read seam | commit `4f76137` | LANDED |
| 0.2 | R-6.5P — write-signing probe shipped, B4-exempted, value-free artefact | commit `38f2426`; `scripts/venue/polymarket_us_write_signing_probe.py` | LANDED |
| 0.3 | R-8-PRE-1 — fee floor expressible; OQ-8 measured (no venue minimum fee) | commit `3b669d5`; `docs/evidence/OQ8_MINIMUM_FEE_2026-09-04.md` | LANDED |
| 0.4 | R-9-PRE — settlement/exit guards | commit `b418424` | LANDED |
| 0.5 | R-7-PRE-2 — `DailySpendLedger` release + true-up | commit `e329667` (`operator_controls.py:408-474`) | LANDED, zero call sites |
| 0.6 | R-7 latch library — durable submit-intent latch, L-22 locked constructor | commit `5d41eaa` (`src/breezy/runtime/submit_intent.py`) | LANDED, zero call sites |
| 0.7 | **R-6.5b** — `write_transport.py`, `PERMITTED_WRITE_METHODS={"POST"}`, `post_cancel_all`, B4 narrowing | TODO — the module does not exist in `src/breezy/adapters/polymarket_us/` | **TODO** |
| 0.8 | **R-7** — `_submit_order` gets a body; startup calls `reconcile_at_startup` before the first `arm`; standing refusal removed | TODO — `exec/client.py` still ends at `_STANDING_ORDER_REFUSAL` | **TODO** |
| 0.9 | **R-7-STATUS** — by-id order read on the READ seam (blocks R-8) | TODO | **TODO** |
| 0.10 | **Seam B** — NWS observation publisher (A12); `0.75 h` staleness is miscalibrated without it | TODO | **TODO** |
| 0.11 | **current_rung_hold steps 4–7** — `config.py`, `decision.py`, `strategy.py`, PREREG artefact (plus 6b/6c/6d) | TODO — `src/breezy/strategy/current_rung_hold/` does not exist | **TODO** |
| 0.12 | Gate green: `scripts/ci/run_tests_no_egress.sh`, passed count never dropped | TODO at each increment | **TODO** |

Nothing below is started until 0.7–0.12 are closed, EXCEPT OP-1..OP-4, which are R-6.5b's own
precondition (OQ-D) and are run first.

## 1. OP-1 — rest a BUY of 1 contract at $0.01, by hand

Purpose: create the positive control that makes OP-2's refusal meaningful. A flat-account pre-flight
cannot distinguish "the account is flat" from "the venue hid our order" (Rev 7 §1 D1).

Steps, as far as the documents describe them: in the Polymarket.us UI, on any weather market whose
best ask is far above $0.01, place a **limit BUY, quantity 1, price $0.01**. BUY, never SELL — a SELL
on this account is a naked short. $0.01 far below best ask cannot execute unless someone sells into
it, so the loss bound is **$0.01 plus fee**. The empty bid side is irrelevant to a resting BUY.

What the operator must see: the order listed as **resting/open** in the venue's own UI.
Wrong observation: it filled immediately, or it does not appear. Filled → the account is not flat and
OP-2/OP-4 are both invalid; stop and reassess. Not visible → do not proceed; an unconfirmed order
makes `PREFLIGHT_NOT_EMPTY` unattributable.

Note: the exact UI click path is not described in any repo document. Only the order parameters above
are specified.

## 2. OP-2 — run the probe with the positive control

```
.venv/bin/python scripts/venue/polymarket_us_write_signing_probe.py --positive-control
```
(optional: `--stamp <suffix>`, `--evidence-dir <path>`; default is the private-shape evidence dir.)

Expected: refusal at the pre-flight with reason **`PREFLIGHT_NOT_EMPTY`**, exit code 2, **no artefact
written**, and no POST issued (`:522-527`, `:171`). That, and only that, answers OQ-B YES.

Other observations and what they mean:
- **`PREFLIGHT_NOT_200`** (`:512`, carries the HTTP status): transport fault, not evidence. **Re-run.**
  Never treat it as the control succeeding.
- **`OQB_NO`** (`:177`, `:528-535`): the unfiltered open-orders read reported an EMPTY list while the
  control order was resting — the venue does not enumerate the whole account. **STOP.** OQ-B is
  answered NO, whole-account flatness is unprovable, and the probe is dead as designed. Do not
  proceed to OP-3/OP-4; escalate to the build side.
- A run that *proceeds* past the pre-flight under `--positive-control` is the same failure as `OQB_NO`.

Stop rule: only `PREFLIGHT_NOT_EMPTY` licenses OP-3. A bare "refused" is not sufficient.

## 3. OP-3 — cancel the resting BUY by hand, verify flat

Cancel the OP-1 order in the venue UI. Then confirm in the UI that the unfiltered open-orders view is
**empty**.

**A failed cancel is a stop, not a retry** (Rev 7 §6). Cancellation runs over the same private
surface; if it does not take, the account is left un-flat, OP-4 is blocked by its own control, and the
correct action is to halt and report — not to re-issue cancels or to run OP-4 anyway.

## 4. OP-4 — the real probe run on the proven-flat account

```
.venv/bin/python scripts/venue/polymarket_us_write_signing_probe.py
```
(no `--positive-control`). Run it immediately after OP-3, with the operator present.

Expected: the pre-flight passes (200 + empty), one signed POST to the single pinned cancel-all path is
issued, and a `PRIVATE_`-prefixed artefact is written with the closed 7-field schema — including
`write_status` and `write_response_type`. stdout prints pre-flight status/reason, write status,
write response type, post-flight status/reason, and the artefact path (`:719-727`).

Reading the result (§D amendment 10, C-6):
- OQ-D is **CLOSED-YES** iff `write_status` is **200**, or a non-401/403 status carrying a
  `CancelAllOrdersResponse`-shaped body.
- **401 or 403 → CLOSED-NO.** The signer's canonical string is not accepted on a write verb;
  `WRITE_CANONICAL_STRING_VERIFIED` stays `False` and R-7 must refuse to wire a call site.
- `POSTFLIGHT_NOT_200` / `POSTFLIGHT_NOT_EMPTY` / `INTERRUPTED` describe the post-flight read or an
  interruption; they do not by themselves answer OQ-D, and an `INTERRUPTED` artefact is a partial,
  honest record — report it, do not re-run blindly.

The operator does not edit code. The **build side** flips `WRITE_CANONICAL_STRING_VERIFIED`, citing
the artefact path in the commit message. The `AUTH_OK` token from older plan revisions does not exist
in the shipped probe.

## 5. PREREG committed — BEFORE the first order

`docs/evidence/PREREG_current_rung_hold_<D0>.md` must be **committed before the first order**
(blueprint §3, §6 step 7). Fields (§7): D0 · stations LAX, MDW, MIA, SFO (NYC excluded, L-13) ·
window [12:00,17:00) LST · `L_extra=0` with archive arms 30 and 45 agreeing · `stale_observation_hours=0.75` ·
feed: NWS `api.weather.gov` (A12) · ask band (0.05,0.95), depth ≥1.0, size 1, IOC, hold to settlement ·
interval precision rule · unit = one filled taken trial per station-day · `held=1` iff CLI FINAL
`tmax_f` ∈ the rung bought · `PnL = 1{held} − fill_px − fee` · `BE(ā)=ā+0.06·ā·(1−ā)` ·
Wilson z=1.959963984540054 · KILL n≥60 · SURVIVE n≥150 · UNDERPOWERED n<60 · structural-dead rule ·
frozen archive-table sha · expected clock D0+22 / D0+55 (optimistic) · standing refusal: no floor
lowered, no post-hoc screen.

Ordering rule: PREREG committed, then enablement, then the node. A PREREG written after a fill is not
a pre-registration.

## 6. Enablement — the operator's shell only

In the shell that will launch the node, and nowhere else, export three values:
1. the **live-trading enablement variable** (`safety.py:133`; it must be exactly `"1"` — no default,
   no coercion, no inference);
2. the **maximum daily budget** — a rolling UTC-calendar-day USD notional ceiling;
3. the **maximum per position** — a USD *cost* ceiling (price × quantity, rounded up to the cent),
   not a contract count, and **pre-fee**.

Never place any of the three in a file: not a `.env`, not a systemd unit, not a shell rc file, not a
commit. `src/` and `scripts/` are structurally incapable of writing them, and the repo assigns no
value to any of them anywhere.

Absence fails closed: both caps are re-read on **every** authorization
(`operator_controls.py:147-166`, `:333-337`) and raise on absence, blankness, malformation or
non-positivity — with a message naming the control and never its value. There is no cached grant to go
stale, so an unset control refuses every order forever.

What the caps mean for this strategy: it buys **one contract**, IOC, at a displayed ask strictly
inside (0.05, 0.95) — so at most **$0.95 at risk per trial** (plus fee, which the per-position cap does
not model), and at most **one trial per station-day across four stations** = ≤4 orders/day.
**This runbook proposes no values.** They are the operator's alone (PROGRESS "Operator control
contract"); the build side neither suggests nor defaults them.

## 7. First run

Start the node from that same shell:
```
.venv/bin/breezy-trade
```
(`[project.scripts] breezy-trade = "breezy.runtime.trade_cli:main"`, `pyproject.toml:240`). It takes no
arguments; all configuration is read from the environment by `config_from_env` / `exec_config_from_env`.
There is **no systemd unit for the trade node**, and there must not be one: a unit file would put the
enablement value in a file. `deploy/systemd/` carries the tape, ingest, and study units only.

A healthy first afternoon, per station:
- entry evaluations only inside [12:00,17:00) LST; nothing outside the window;
- **at most one IOC per station-day** — the trial-day latch consumes the day at the first executable
  candidate, whether or not the taken test passes;
- most station-days end in a `not_taken` tally or `observation_unavailable` / `observation_ambiguous`
  refusals — these are counted refusal reasons, not faults;
- an IOC miss is logged once (`ioc_miss`) and never retried; no remainder is ever re-sent;
- zero SELLs, zero flattens, zero modifies on any path.

Where to look: order-guard refusals print one line to stderr at the instant they fire
(`trade_cli.py:221`) and are also latched; exec-client refusal reasons come from the
`trading_refusals` reader (`trade_cli.py:247-271`). Fills and the latch state live in the runtime
state store — the shared `SqliteStateStore` under the runtime state dir, holding
`exec/polymarket_us/intent/current` (plus `.../intent/history/<id>`) beside the trial-day keys
`current_rung_hold/trial/{station}/{climate_day}`.

Wrong observations: more than one order per station-day → stop the node, the latch is not doing its
job. Any SELL, any modify, any second contract → stop the node immediately. A refusal naming a
missing operator control → the export did not reach the process.

## 8. Crash and recovery

`retire()` writes the history key **before** the singleton, so a crash leaves the singleton **OPEN**
and every subsequent submit is refused **account-wide** (`submit_intent.py:1-19`, `:365-421`). That is
fail-closed and correct at n=1.

On restart, `reconcile_at_startup` repairs only two cases: a matching history record (copied back
verbatim), or `has_durable_fill_record(fingerprint) is True`. **Nothing supplies that fill probe
today**, so in practice a crash mid-POST leaves the latch OPEN.

The only remaining exit is an operator clear tool. **MISSING — build item.** There is no
`breezy-clear-submit-intent` console script (`pyproject.toml` ships exactly four: `breezy-quote-tape`,
`breezy-quote-tape-preflight`, `breezy-trade`, `breezy-quote-tape-ingest`), no clear/reset/reconcile
CLI under `scripts/`, and no clear entry point in `submit_intent.py` or `trade_cli.py`. The
`OPERATOR_CLEARED` retirement reason exists (`submit_intent.py:78`) with no tool to emit it. Per
Rev 7 §5, that tool must refuse without an operator acknowledgement, must require a positions +
fill-record artefact, must never accept open-orders emptiness as proof, and must take the same
exclusive flock — the node and the clear tool can never both act.

Until it exists: **never re-arm before reconciliation.** Do not delete the state store, do not edit the
singleton by hand, do not restart with a fresh store path. Stop, obtain the positions/fill evidence
from the venue, and hand the case to the build side.

## 9. Kill / survive

The nightly live-family verdict is a **build item (6d)**: a systemd timer beside `breezy-mb-daily`
that tallies the live family (n, k, Wilson interval vs BE → KILL / SURVIVE / UNDERPOWERED). It does
not exist yet. When it lands, its live section is read at
`~/.local/share/breezy/derived/mb_current_rung_edge_<date>.md`. Today that path is written by
`scripts/analysis/mb_current_rung_edge_study.py` via `deploy/systemd/mb-daily-run.sh:62-63` and
carries the ARCHIVE study only — no live section.

- **KILL** (n≥60 with the Wilson upper bound below pooled BE, or any dead n≥60 stratum): stop the node.
  The strategy is **dead by pre-registration**. No re-tuning, no floor lowered, no post-hoc screen.
- **SURVIVE** (n≥150, Wilson lower bound above BE, no dead stratum, ΣPnL > 0): licenses **nothing
  beyond continuing exactly as pre-registered**. Any sizing change, station change, or band change is a
  NEW pre-registration with its own clock.
- **UNDERPOWERED** (n<60): keep running; it is not a result.

The stop gate itself is unchanged: positive ROI from **real, very small, marketable orders**, with the
confidence-interval lower bound above break-even. A backtest number cannot satisfy it.
