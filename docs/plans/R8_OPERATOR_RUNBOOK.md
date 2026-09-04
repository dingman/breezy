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
| 0.7 | **R-6.5b** — `write_transport.py`, `PERMITTED_WRITE_METHODS={"POST"}`, `post_cancel_all`, `post_order`, B4 narrowing; `WRITE_CANONICAL_STRING_VERIFIED: Final[bool] = False` (line 48) | commit `092695c`; `src/breezy/adapters/polymarket_us/write_transport.py:40-175` | LANDED, 092695c |
| 0.8 | **R-7** — `_submit_order` gets D1–D9 body; startup calls `reconcile_at_startup` before the first `arm`; `exec/submit_chain.py` classifies shape/response | commit `092695c`; `src/breezy/adapters/polymarket_us/exec/client.py:1484-1550`; `src/breezy/adapters/polymarket_us/exec/submit_chain.py` | LANDED, 092695c; refined 02bfd63 |
| 0.9 | **R-7-STATUS** — by-id order read on the READ seam (`exec/client.py::generate_order_status_report`, templated path, no new B4 row) | LANDED `092695c` | **LANDED** |
| 0.10 | **Seam B** — NWS observation publisher (A12); `50 min` staleness (rev 3 delta; was 0.75 h) | LANDED `e9492bc` (flag `BREEZY_LIVE_OBSERVATIONS=1`), staleness gating `86d6a63` | **LANDED** |
| 0.11 | **current_rung_hold steps 4–7** — `config.py`, `decision.py`, `strategy.py`, PREREG artefact (plus 6c/6d) | FLAG-OFF runtime wiring landed (commit `c86bd10`); `orders_enabled` stays False and unreachable from env (`src/breezy/runtime/settings.py`); per-tick refusal counts (commit `2aa3e3a`); config/decision/strategy landed (`15f04f4`, `348f9c8`, `74cfa7c`+fixes); 6c scorer `24950d1`/`43e38ff`, 6d tally `abcc1ad` (timer PREPARED, not enabled), 6e BCa `6ddca6e`; PREREG v1 BINDING (draft line removed 2026-09-04, operator delegation); `breezy-live-tally.timer` ENABLED 2026-09-04 | **LANDED** |
| 0.12 | Gate green: `scripts/ci/run_tests_no_egress.sh`, passed count never dropped | green at every landing 09-04 (5856 → 7452+) | **HELD** |

Nothing below is started until 0.7–0.12 are closed, EXCEPT OP-1..OP-4, which are R-6.5b's own
precondition (OQ-D) and are run first.

## Shadow mode

`current_rung_hold` can be registered on the trading node without submitting an order.
`orders_enabled` stays False and cannot be flipped from the environment.

Both flags must be exactly `1`. The catalog root is required only when the strategy flag is on.

| Role | Variable | Value |
|---|---|---|
| Live NWS observation publisher | `BREEZY_LIVE_OBSERVATIONS` | `1` |
| Shadow-mode `current_rung_hold` | `BREEZY_CURRENT_RUNG_HOLD` | `1` |
| Trade-role catalog root (pre-build discovery) | `BREEZY_TRADE_CATALOG_ROOT` | absolute path, no `..` |

`BREEZY_CURRENT_RUNG_HOLD=1` without `BREEZY_LIVE_OBSERVATIONS=1` is a configuration error (exit 2) and names both variables.

The composition root (`breezy.app.trade:main`, commit `092695c`; `pyproject.toml:251`) is the sole opener of the submit-intent latch. The exec client stores the injected latch and does not open a second one.

journalctl strings to grep:

- `CurrentRungHoldStrategy subscribed <instrument-id>` — the strategy armed a market
- `TAKE recorded, no submit (order_submission_permit=none):` — the shadow-mode signal; a trial was taken and no order was sent (`order_submission_permit=granted` with no submit line following means the permit was granted but `stale_observation_minutes` is not an `int`, which cannot happen in a real deployment)
- `OUTSIDE_DECISION_WINDOW_REFUSALS`
- `OBSERVATION_UNAVAILABLE_REFUSALS`
- `OBSERVATION_AMBIGUOUS_REFUSALS`
- `FEE_SCHEDULE_MISMATCH_REFUSALS`
- `TRIAL_DAY_CONSUMED_REFUSALS`

A station that resolves zero instruments for today's climate day is skipped and counted; the process refuses to start only when every station resolves zero.

## 1–4. OP-SEQ — the bot rests, proves, cancels and verifies its own positive control (rewritten 2026-09-04)

Operator ruling 2026-09-04: resting and cancelling the control is the bot's job, never a venue-UI
step. Plan: `docs/plans/OP_SEQ_BOT_POSITIVE_CONTROL_2026-09-04.md` (converged). One command:

```
.venv/bin/python scripts/venue/polymarket_us_write_signing_probe.py --sequence [--stamp <token>]
```

Precondition: no manual venue order may exist on the account for the run's duration (cancel-all
would take it). Steps and stop rules, every stop terminal and never retried:

| # | Step | Pass | Stop |
|---|---|---|---|
| S0 | artefact `O_EXCL` pre-check | absent | exit 2 before any request |
| S1 | signed unfiltered `GET /v1/orders/open` | 200 + empty | `PREFLIGHT_NOT_200` (transport; re-run once) · `PREFLIGHT_NOT_EMPTY` (not flat; no write) |
| S2 | public `GET /v1/markets`, deterministic pick: smallest eligible weather slug, best ask ≥ $0.20, tick 0.01, min qty ≤ 1, not resolved | one slug | `NO_ELIGIBLE_INSTRUMENT` (no write, no artefact) |
| S3 | signed `POST /v1/orders`: limit BUY YES, qty 1, $0.01, GTC, `participateDontInitiate` | 200 + id | 401/403 → **CLOSED-NO**, nothing resting · other → `REST_AMBIGUOUS`, cleanup S5, `INCONCLUSIVE` |
| S4 | signed open-orders read (one 250 ms re-read allowed) | our id, unfilled | `OQB_NO` / `CONTROL_FILLED` → cleanup S5, escalate |
| S5 | signed cancel-all | 200 / `CancelAllOrdersResponse` | `CANCEL_NOT_OK` → **STOP un-flat, never retry** |
| S6 | signed open-orders read | 200 + empty | `POSTFLIGHT_*` describes the read only |

Verdict `CLOSED_YES_BOTH_VERBS` iff S3 200+id, S4 enumerated-unfilled, S5 ok, S6 empty. Loss bound if
the control ever fills: $0.01 (fee rounds to $0.00). The artefact
`PRIVATE_write_sequence_probe[_<stamp>].json` (+ `.sha256`) is written iff a signed request was
issued; it carries statuses, reason codes, response type names and the verdict — never a slug, id,
count or body. An interruption after S3 writes a partial artefact with `verdict=INCONCLUSIVE`;
recovery is one legacy cancel-all-only run (`--positive-control` is legacy and no longer part of the
sequence). Only `CLOSED_YES_BOTH_VERBS` licenses C5: the build side flips
`WRITE_CANONICAL_STRING_VERIFIED`, pasting the rendered artefact JSON and its sha256 into the commit.

## 5. PREREG committed — BEFORE the first order

`docs/specs/PREREG_v1_current_rung_hold_2026-09-04.md` (v1 DRAFT exists; remove its draft line to make it binding) must be **committed as binding before the first order**
(blueprint §3, §6 step 7). Fields (§7): D0 · stations LAX, MDW, MIA, SFO (NYC excluded, L-13) ·
window [12:00,17:00) LST · `L_extra=0` with archive arms 30 and 45 agreeing · `stale_observation_minutes=50` (rev 3 delta) ·
feed: NWS `api.weather.gov` (A12) · ask band (0.05,0.95), depth ≥1.0, size 1, IOC, hold to settlement ·
interval precision rule · unit = one filled taken trial per station-day · `held=1` iff CLI FINAL
`tmax_f` ∈ the rung bought · `PnL = 1{held} − fill_px − fee` · `BE(ā)=ā+0.06·ā·(1−ā)` ·
Wilson z=1.959963984540054 · KILL n≥60 · SURVIVE n≥150 · UNDERPOWERED n<60 · structural-dead rule ·
frozen archive-table sha · expected clock D0+22 / D0+55 (optimistic) · standing refusal: no floor
lowered, no post-hoc screen.

Ordering rule: PREREG committed, then enablement, then the node. A PREREG written after a fill is not
a pre-registration.

## 6. Enablement — the operator's shell only (amended 2026-09-04, step-8 peer review)

In the shell that will launch the node, and nowhere else, export **seven** values, in two classes.

**Durable role caps** — re-read on every authorization, never cached:
1. the **maximum daily budget** — a UTC-calendar-day USD notional ceiling, enforced by the
   in-process `DailySpendLedger` (it is process-local: one process per trading day; the ledger
   re-keys at 00:00 UTC mid-session, and the durable trial-day latch — ≤1 order per station-day,
   ≤4 orders ≈ $3.80 pre-fee — is the binding cross-restart limit);
2. the **maximum per position** — a USD *cost* ceiling (price × quantity, rounded up to the cent),
   not a contract count, and **pre-fee**. With quantity 1 and asks strictly below 0.95, a
   whole-dollar cap admits the entire band; a cap below $0.95 refuses its top.

**Per-process session values** — read once at start by `issue_live_trading_permit`
(`safety.py:583-592`); they reset on every restart:
3. the **live-trading enablement variable** (`safety.py:133`; exactly `"1"` — no default, no coercion);
4. the **order-submission request flag** `BREEZY_ORDERS_ENABLED=1` (not a reserved control; refused
   unless `BREEZY_CURRENT_RUNG_HOLD=1` and `BREEZY_LIVE_OBSERVATIONS=1` are also set; it is a
   REQUEST that the permit constructor validates — a bool is never the gate);
5. the **per-order notional ceiling** — whole-USD granularity (`safety.py:560-566`); must be ≥ the
   per-position cap or every order is refused;
6. the **session notional** — floor: station count × $1;
7. the **session order count** — floor: the number of configured stations (four); anything lower
   silently truncates the day;
8. the **operator identity** string (logged never by value; permit `repr` is suppressed).

The permit lives **10 hours** (`PERMIT_TTL_NS`, retargeted 2026-09-04 from 15 minutes: the union of
the four decision windows is 17:00 UTC → 01:00 UTC next day, plus 1 h slack each side). Launch the
node once per trading day **before 17:00 UTC**; it is never re-minted in-process.

Never place any of the values in a file: not a `.env`, not a systemd unit, not a shell rc file, not
a commit, not a launcher script. `src/` and `scripts/` are structurally incapable of writing them, and
the repo assigns no value to any of them anywhere. Accepted residual exposure of shell exports (the
same class already accepted for the enablement variable): the values are readable from
`/proc/<pid>/environ` by same-UID processes and may persist in shell history outside the repo.

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

The launch shell exports **seven** values before the node starts (converged peer review item 5;
`safety.py:583-592` names five of the seven, `operator_controls.py` the other two): the live-trading
enablement variable, the maximum daily budget, the maximum per position, the per-order notional
ceiling, the session notional ceiling, the session order count, and the operator identity — plus, when
requesting the order path (step 8), the CRH enablement flag `BREEZY_ORDERS_ENABLED=1` (build-side, not
operator-reserved — see `settings.py`'s `ORDERS_ENABLED_VAR`), `BREEZY_CURRENT_RUNG_HOLD=1` and
`BREEZY_LIVE_OBSERVATIONS=1`. All of it goes only into the launching shell's own environment — never a
file (§6).

The live-trading permit's TTL is 10 hours (`safety.py:157`, the union of the four decision windows plus
slack), and `OrderSubmissionPermit.issue` (`runtime/order_enablement.py`) checks it once at startup,
beside the live-trading permit, and never re-mints. **One process per trading day**, started from that
shell **before 17:00 UTC** (the latest decision window's close) so the permit is valid for the whole
session; the durable trial-day latch is the real cross-restart bound regardless (at most one order per
station-day, converged review item 3) — an unplanned restart makes that day's selector
uptime-conditional, disclosed rather than hidden, and the daily budget re-keys at 00:00 UTC mid-session.

Start the node from that same shell:
```
.venv/bin/breezy-trade
```
(`pyproject.toml:251`: `breezy-trade = "breezy.app.trade:main"`). It takes no arguments; all configuration is read from the environment by `config_from_env` / `exec_config_from_env`. A refusal from
`OrderSubmissionPermit.issue` (any of its five preconditions unmet, when the order path was requested)
is fatal at startup, logged with the refusal class name only, exit code 1 — restart with the missing
precondition corrected.
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

**Any restart inside the window makes that day's selector uptime-conditional** (the "first executable snapshot" the archive table was measured on may fall in the gap) and resets the per-process daily ledger and session budgets; the durable trial-day latch still bounds the day. Disclosed here so a crash day is never mistaken for a PREREG-comparable day without saying so.

`retire()` writes the history key **before** the singleton, so a crash leaves the singleton **OPEN**
and every subsequent submit is refused **account-wide** (`submit_intent.py:1-19`, `:365-421`). That is
fail-closed and correct at n=1.

On restart, `reconcile_at_startup` repairs only two cases: a matching history record (copied back
verbatim), or `has_durable_fill_record(fingerprint) is True`. **Nothing supplies that fill probe
today**, so in practice a crash mid-POST leaves the latch OPEN.

The only remaining exit is an operator clear tool. **LANDED** — `breezy-clear-submit-intent` (commit `092695c`; `pyproject.toml:263`; `src/breezy/runtime/clear_submit_intent_cli.py:69-163`). Requires operator ack
(`BREEZY_CLEAR_SUBMIT_INTENT_ACK="1"`), `--yes`, `--resolution` (order-id=<id> or no-order-exists), and `--evidence` (positions + fill-record artefact). Exit codes: 0 (cleared), 2 (refused), 3 (nothing OPEN). The tool refuses without an operator acknowledgement, requires positions + fill-record evidence, never accepts open-orders emptiness as proof, and takes the same exclusive flock — the node and the clear tool can never both act.

## 9. Kill / survive

The nightly live-family verdict (6d, `abcc1ad`) is `scripts/analysis/live_family_tally.py` driven by
`deploy/systemd/breezy-live-tally.timer` (14:30 UTC, PREPARED — the operator enables it with
`systemctl --user enable --now breezy-live-tally.timer` after `systemd-analyze --user verify`). It tallies
the live family (n, k, Wilson vs BE → KILL / SURVIVE / UNDERPOWERED; SURVIVE also needs ΣPnL>0) and prints
the BCa lower bound on ROI — the stop-gate quantity. Its output path is set by the unit's `--output`. Today that path is written by
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
