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
| 0.7 | **R-6.5b** — `write_transport.py`, `PERMITTED_WRITE_METHODS={"POST"}`, `post_cancel_all`, `post_order`, B4 narrowing; `WRITE_CANONICAL_STRING_VERIFIED` (line 48) **= True since 2026-09-04 17:08 UTC** — OP-SEQ live verdict `CLOSED_YES_BOTH_VERBS`, artefact `PRIVATE_write_sequence_probe_20260904T170856Z.json` sha256 `46b3a75e…d617` | commit `092695c`; C5 flip on this branch | **VERIFIED** |
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

## 6. Enablement — the two operator caps (amended 2026-09-10)

Operator ruling 2026-09-10: the only operator-controlled variables are the two durable caps.
Every other value the live path currently demands is BUILD-SIDE and is supplied by the
trade-supervisor unit (or derived in code at permit mint) on every launch, including after a reboot.

**Durable role caps** — re-read on every authorization, never cached; the operator MAY keep them in
the gitignored `/operator.env` at the repo root (never committed, never written by the build side,
never read by repo Python):
1. the **maximum daily budget** — a UTC-calendar-day USD notional ceiling, enforced by the
   in-process `DailySpendLedger` (it is process-local: one process per trading day; the ledger
   re-keys at 00:00 UTC mid-session, and the durable trial-day latch — ≤1 order per station-day,
   ≤4 orders ≈ $3.80 pre-fee — is the binding cross-restart limit);
2. the **maximum per position** — a USD *cost* ceiling (price × quantity, rounded up to the cent),
   not a contract count, and **pre-fee**. With quantity 1 and asks strictly below 0.95, a
   whole-dollar cap admits the entire band; a cap below $0.95 refuses its top.

Unknown keys in `operator.env` are still rejected. Absence of either cap still fails closed at
permit issue and at every authorization.

**Build-side session values** — not operator knobs. The trade-supervisor unit assigns the
enablement flags and operator identity (`Environment=` lines; `%u` expands to the unit user).
The three numeric session ceilings (per-order notional, session notional, session order count)
are derived at `issue_live_trading_permit` from the two caps when those env vars are absent:
per-order := position cost; session notional := daily budget; session order count :=
floor(daily / position), minimum 1. An explicit session env var still wins if present.
Enablement still requires exactly `"1"`. `src/` and `scripts/` remain structurally incapable of
writing any of these (AST barrier).

The permit lives **10 hours** (`PERMIT_TTL_NS`, retargeted 2026-09-04 from 15 minutes: the union of
the four decision windows is 17:00 UTC → 01:00 UTC next day, plus 1 h slack each side). Launch the
node once per trading day **before 17:00 UTC**; it is never re-minted in-process.

Operator flow (from the repo root):

1. `cp operator.env.example operator.env` and fill in the two values; `chmod 600 operator.env`
2. `.venv/bin/python scripts/operator/print_operator_controls.py --check-file operator.env`
3. Restart the supervisor as §10(a) says. The unit references `operator.env`; the build-side
   constants travel with the unit; the three numeric ceilings derive at permit mint.

Accepted residual: the two caps at rest in `/operator.env` are readable by any same-UID process,
survive the shell, and enter backups. The build-side `Environment=` values are world-readable via
`systemctl cat` and `/proc/<pid>/environ` (same class as any other non-secret unit env).

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

**Superseded 2026-09-10.** The 2026-09-04 rule that the launch shell exports seven values (enablement,
the two caps, the three numeric session ceilings, and the operator identity), and that enablement
must never appear in a file, is revoked. Reason: the operator ruled that the only operator-controlled
variables are the two durable caps; every other live-path value is build-side and must be supplied
by the build on every launch, including after a reboot. GO_LIVE_PLAN §5's "No agent, and no
automation in this repo, may set D4" and safety.py's former "No default, never inferred" for the
three numerics encoded that old policy.

What remains binding: the two caps are never written by the build; unknown keys in `operator.env`
are still rejected; the permit still fails closed when the caps are absent; the boot-time permit
line stays the only proof of order capability. Enablement still requires exactly `"1"`.

The live-trading permit's TTL is 10 hours (`safety.py:157`, the union of the four decision windows plus
slack), and `OrderSubmissionPermit.issue` (`runtime/order_enablement.py`) checks it once at startup,
beside the live-trading permit, and never re-mints. **One process per trading day**, started
**before 17:00 UTC** (the latest decision window's close) so the permit is valid for the whole
session; the durable trial-day latch is the real cross-restart bound regardless (at most one order per
station-day, converged review item 3) — an unplanned restart makes that day's selector
uptime-conditional, disclosed rather than hidden, and the daily budget re-keys at 00:00 UTC mid-session.

The production launcher is the user unit in §10. A hand launch (`.venv/bin/breezy-trade`) still
reads the same environment; it takes no arguments; all configuration is read from the environment by
`config_from_env` / `exec_config_from_env`. A refusal from
`OrderSubmissionPermit.issue` (any of its five preconditions unmet, when the order path was requested)
is fatal at startup, logged with the refusal class name only, exit code 1 — restart with the missing
precondition corrected.
There is **no systemd unit for the trade node itself** — only for the supervisor that spawns it.
`deploy/systemd/` carries the tape, ingest, study, and supervisor units.

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
job. Any SELL, any modify, any second contract → stop the node immediately. **Exit seam status (2026-09-16):** the exit authorization path EXISTS but is UNARMED — live family `pm_us_crh_cont` has no `exit_rule`, and the v4 successor family `pm_us_crh_exit_v4` is `DRAFT_NOT_REGISTERED` pending §4 step 3 positive control; thus any live SELL is STILL a defect. The seam enters logs when `exit_decider` refuses (plan POSITION_EXIT_EXECUTION_2026-09-16 INC-E3), with reason codes: `family_not_exit_registered`, `missing_stop_no_order`, `no_exit_condition`, `book_not_executable`, `book_stale`, `expected_settlement_undefined`, `exit_rate_limited`, `station_day_exit_cap`, `r_threat_insufficient_proceeds`, `r_dead_nonpositive_proceeds`. An AMBIGUOUS or rejected exit halts the family; the durable halt is cleared only by `clear_family_halt_cli.py` (requires approval and evidence). Arming checklist (PREREG v4 §11): steps 0/0b/1 RETIRED (2026-09-16); steps 2–4 open. Nightly exit-window study (15:20Z, path `~/.local/share/breezy/derived/exit_window_study/<stamp>/exit_window_study.md`). **Exits never debit the daily budget and never replenish entry headroom** — the two-caps rule unchanged. A refusal naming a
missing operator control → the two caps in `operator.env` did not reach the process.

## 8. Crash and recovery

**Any restart inside the window makes that day's selector uptime-conditional** (the "first executable snapshot" the archive table was measured on may fall in the gap). The per-process daily ledger is NOT zeroed by a restart: `_seed_spend_from_durable_fills` (`exec/client.py:1292-1360`) re-seeds it from durable fills at every boot, including a relaunch, keyed by UTC calendar day -- summing only fills whose `ts_event` falls in the current UTC day and re-arming the permit budget from that sum, consistent with what the same running node would do on its own next order attempt. The durable trial-day latch still bounds the day regardless. Disclosed here so a crash day is never mistaken for a PREREG-comparable day without saying so.

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

PREREG v2 (registered 2026-09-05, `docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md`)
runs a SEPARATE sibling tally, `scripts/analysis/family_tally_v2.py`, driven by
`deploy/systemd/breezy-pm-crh-v2-tally.timer` (15:30 UTC, one hour after the v1 tally, PREPARED —
`family-tally-v2-run.sh pm_us_crh_v2`). It applies the group-sequential LD-OBF boundary to family
`pm_us_crh_v2` over the same 6c scored-trial store, and is never a substitute for the v1 KILL/
SURVIVE/UNDERPOWERED gate above.

- **KILL** (n≥60 with the Wilson upper bound below pooled BE, or any dead n≥60 stratum): stop the node.
  The strategy is **dead by pre-registration**. No re-tuning, no floor lowered, no post-hoc screen.
- **SURVIVE** (n≥150, Wilson lower bound above BE, no dead stratum, ΣPnL > 0): licenses **nothing
  beyond continuing exactly as pre-registered**. Any sizing change, station change, or band change is a
  NEW pre-registration with its own clock.
- **UNDERPOWERED** (n<60): keep running; it is not a result.

The stop gate itself is unchanged: positive ROI from **real, very small, marketable orders**, with the
confidence-interval lower bound above break-even. A backtest number cannot satisfy it.

## 10. Trade-supervisor relaunch — the systemd user unit (added 2026-09-08)

### Why this section exists

The daily supervisor (`breezy-trade-supervisor`, §7's launcher for the node) ran inside a tmux scope
with **no unit, no timer, no cron entry**. The `2026-09-08T01:07:50Z` host reboot killed it silently:
no `breezy-trade-2026-09-08*.log` was ever created, and nothing would have launched at that day's
16:50Z window. Supervision that does not survive a reboot is not supervision.

`deploy/systemd/breezy-trade-supervisor.service` fixes exactly that, and **only** that.

### This does not reopen a unit for the trade node itself

§7 still bans a unit for **the trade node**. This unit is for the **supervisor**. Operator ruling
2026-09-10: a reboot of this unit RESUMES supervision **and** order capability.

- The **two durable caps** reach it only by *reference* to your gitignored `/operator.env`, which §6
  already permits to hold exactly those two values at rest. The unit never reads or echoes them,
  and the build never writes them.
- The **build-side session constants** (enablement flags and operator identity) are `Environment=`
  lines in the unit. The three numeric session ceilings are derived at permit mint from the two
  caps when absent. There is no `import-environment` step.

### Standing note: no memory cap, deliberately

Unlike `breezy-quote-tape.service`, this unit sets **no `MemoryHigh=` / `MemoryMax=`**. A cgroup ceiling
here would also cover the spawned `breezy-trade` node, and a cgroup OOM kill is **SIGKILL** — it would
tear down a node possibly holding a live position, with no clean shutdown. The recorder can afford that
trade; a node with money at risk cannot. The cost of the choice: this unit is left to the host-wide OOM
killer. Watch it with `systemd-cgtop --user` and the `Memory:` line of `systemctl --user status`.

`KillMode=process` is set for the same reason: systemd's default `control-group` would SIGTERM/SIGKILL
**every** process in the cgroup on restart, including the node (its `start_new_session=True` detaches it
from the terminal, not from the cgroup). A node that outlives its supervisor is an anticipated state —
[B2] supervisor-death adoption re-adopts the PID-verified flock holder at the next 16:40Z cycle.

### (a) Install and enable

Linger — required for a user unit to run without an active login and to come back after reboot.
**Verify first; on this host it is already `yes`:**

```
loginctl show-user "$USER" --property=Linger
# expect: Linger=yes ; if it prints Linger=no, run:
loginctl enable-linger "$USER"
```

Link the unit (the repo file stays the source of truth, matching every other Breezy unit) and verify:

```
ln -s /home/jon/breezy/deploy/systemd/breezy-trade-supervisor.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemd-analyze --user verify ~/.config/systemd/user/breezy-trade-supervisor.service
```

`verify` prints **nothing** when the unit is clean — treat any output as a failure (it exits 0 either
way, so read the output, not the status). `daemon-reload` starts nothing.

Ensure `operator.env` holds the two caps, then:

```
systemctl --user restart breezy-trade-supervisor.service
```

That is the whole operator procedure. The unit already carries the build-side constants; the three
numeric ceilings derive at permit mint. First install (before 17:00Z on a day you intend to trade —
the permit TTL is 10 h and the launch window closes at `RELAUNCH_CUTOFF_UTC = 17:00Z`):

```
systemctl --user enable --now breezy-trade-supervisor.service
```

`enable` alone (without `--now`) arms it for the next boot without starting it today — use that if you
are installing outside a trading window.

**After every reboot** the unit comes back on its own (Linger=yes) and resumes order capability.
Restart it only if you changed `operator.env` or the unit file.

**To stop:** `systemctl --user stop breezy-trade-supervisor.service` (SIGTERM to the supervisor only —
`KillMode=process` leaves a running node alone). SIGTERM the node separately if you want it down too.
**Never SIGKILL either process.**

### (b) Verify it actually worked

1. **The unit is up and armed for the next boot.**

```
systemctl --user is-enabled breezy-trade-supervisor.service   # expect: enabled
systemctl --user status  breezy-trade-supervisor.service --no-pager
pgrep -af 'breezy-trade-supervisor-daily$'                    # expect: exactly one match
```

2. **The supervisor made its launch decision.** Its own log — not the journal — is the record:

```
journalctl --user -u breezy-trade-supervisor.service --since today --no-pager
tail -n 50 ~/.local/share/breezy/logs/breezy-trade-supervisor.log
```

Look for `supervisor_started` at start-up, and after 16:50Z a launch decision line.

3. **The node actually booted with ORDER CAPABILITY — the only proof that counts.**

Only the **boot-time permit line in the node's own log** proves order capability. Its absence from an
*incremental* log delta is a known false negative (the 2026-09-06 17:05Z `NO_PERMIT` alert was wrong for
exactly this reason: the line had already drained out of the delta window). **So read the node log file
itself, from the top — never a tail, never a delta, never the journal:**

```
# NOTE the [0-9] guard: a bare breezy-trade-*.log glob also matches the
# SUPERVISOR's own breezy-trade-supervisor.log, which never carries a permit line.
NODE_LOG=$(ls -1t ~/.local/share/breezy/logs/breezy-trade-[0-9]*T*Z.log | head -n1)
echo "checking: $NODE_LOG"
grep -c 'live-trading permit issued issued_at_ns=' "$NODE_LOG"
```

- count **≥1** → the node booted **with** order capability. This is the success line.
- count **0** → check for the refusal, which is equally explicit:

```
grep -n 'order submission permit not issued' "$NODE_LOG"
grep -n 'trading node failed'                "$NODE_LOG"
```

A `permit not issued` line means a §6 precondition was missing — most often one of the two caps is
absent from `operator.env`. Correct the file and restart the unit; the node exits 1 on that refusal
and is **never** relaunched automatically ([E4]: the supervisor's env is fixed for its lifetime, so a
relaunch could not change the outcome).

4. **The node is alive and separately sessioned:**

```
pgrep -af 'breezy-trade$'
ps -o sid,pgid,pid,cmd -p "$(pgrep -f 'breezy-trade-supervisor-daily$')" "$(pgrep -f 'breezy-trade$')"
```

Each should show its own SID/PGID.

### Reboot drill (do this once, outside a trading window)

`systemctl --user is-enabled` returning `enabled` plus `Linger=yes` is the paper proof. The real proof is
a reboot: after the host comes back, `systemctl --user status breezy-trade-supervisor.service` should show
the unit **active (running)** with **no login session**, and
`~/.local/share/breezy/logs/breezy-trade-supervisor.log` should carry a fresh `supervisor_started` line.
Order capability resumes with the unit — confirm it with the boot-time permit line in §10(b).

### (c) Phase 1 cut to pm_us_crh_cont — COMPLETED (2026-09-12)

Phase 1 is now deployed (commit 7938032). The tracked unit carries the continuous profile with
`BREEZY_CONTINUOUS_RUNG_HOLD=1`, `BREEZY_ORDERS_ENABLED=1`, and `BREEZY_CRH_CONT_PHASE0_SHADOW=0`.

#### (i) Preconditions

- **Registration landed:** `deploy/families/pm_us_crh_cont.json` has `status: "REGISTERED"`.
- **Gate green:** `scripts/ci/run_tests_no_egress.sh` passes.
- **D0 pinned:** `d0_climate_day` is locked.
- **Unit verified:** `breezy-trade-supervisor.service` carries Phase 1; `systemd-analyze verify` clean.

#### (ii) Deployment status

The tracked file now carries Phase 1. To activate, reload and restart (at 16:40Z if possible):

```
systemctl --user daemon-reload
systemctl --user restart breezy-trade-supervisor.service
```

The unit carries `BREEZY_CONTINUOUS_RUNG_HOLD=1`, `BREEZY_ORDERS_ENABLED=1`, and
`BREEZY_CRH_CONT_PHASE0_SHADOW=0` (no `BREEZY_CURRENT_RUNG_HOLD`). `KillMode=process` means
SIGTERM goes only to the supervisor; the node stops via STOP_PRIOR.

#### (iii) Verification — order capability enabled

1. **Supervisor is running with the Phase 1 unit:**

```
systemctl --user status breezy-trade-supervisor.service --no-pager
# expect: active (running), with PID listed
```

2. **The running node's environment includes the Phase 1 flags:**

```
NODE_PID=$(pgrep -f 'breezy-trade$')
cat /proc/$NODE_PID/environ | tr '\0' '\n' | grep BREEZY_
# expect: BREEZY_CONTINUOUS_RUNG_HOLD=1, BREEZY_ORDERS_ENABLED=1, BREEZY_LIVE_OBSERVATIONS=1
# absent: BREEZY_CURRENT_RUNG_HOLD (Phase 0b flag)
```

3. **Boot-time permit line proves order capability:**

```
NODE_LOG=$(ls -1t ~/.local/share/breezy/logs/breezy-trade-[0-9]*T*Z.log | head -n1)
grep 'live-trading permit issued issued_at_ns=' "$NODE_LOG"
# expect: exactly one line, proof that Phase 1 order capability was granted at startup
```

4. **Startup evidence was written (Phase 1 re-arm gate):**

```
# The node writes startup evidence to the execution state store for re-arm validation.
# This is internal; the presence of the log line above is the operator's proof.
grep 'startup_evidence written' ~/.local/share/breezy/logs/breezy-trade-[0-9]*T*Z.log
```

5. **No Phase1PermitForbiddenError (would appear if continuous_rung_hold is not armed):**

```
grep 'Phase1PermitForbiddenError\|phase1.*forbidden\|continuous.*permit.*denied' \
  ~/.local/share/breezy/logs/breezy-trade-[0-9]*T*Z.log
# expect: empty (no matches); presence means a precondition failed
```

#### (iv) Rollback — return to Phase 0b

If verification fails, restore from before the cut (commit 314a3ba):

```
git checkout 314a3ba -- deploy/systemd/breezy-trade-supervisor.service
systemctl --user daemon-reload
systemctl --user restart breezy-trade-supervisor.service
```

Verify Phase 0b is running: grep for `BREEZY_CURRENT_RUNG_HOLD=1` in `/proc/<pid>/environ`.

#### (v) AMBIGUOUS handling under Phase 1

Phase 1 adds automated resolution for with-id AMBIGUOUS orders (`_resolve_ambiguous_intents`,
`src/breezy/adapters/polymarket_us/exec/client.py:1068-1267`). The resolver runs as a bounded, firewall-scanned
coroutine and uses GET `/v1/order/{id}` to confirm filled or terminal status.

- **With-id AMBIGUOUS (automatic):** The resolver polls in the background and retires the intent when
  confirmed. Failure cases (GET 5xx, malformed body, timeout) leave the intent AMBIGUOUS and retry
  next poll cycle. This is never a manual step — the operator does not intervene.
- **No-id AMBIGUOUS:** If an order submit returns AMBIGUOUS without a venue_order_id, run
  `.venv/bin/breezy-clear-submit-intent --yes --resolution no-order-exists --evidence <positions file>`
  to retire the singleton and unblock arming. This is the sole manual step for no-id cases.

- **Duplicate fill (family halt):** If a single fill is recorded twice, the `continuous_rung_hold/halt`
  key stops arming. Clear with strategy-lead approval: `.venv/bin/breezy-clear-family-halt --reason "<msg>" --evidence-path <file>`.
- **Kill switch:** If the node must be stopped immediately, SIGTERM it:

```
pkill -f 'breezy-trade$'
# or, by PID
kill $(pgrep -f 'breezy-trade$')
```

The supervisor does not automatically relaunch a killed node (only crashes trigger bounded relaunch).
A manual restart is needed: `systemctl --user restart breezy-trade-supervisor.service` at the next
desired window, or before 17:00Z if you want to keep the day's permit active.

**AUD-13d note:** this manual kill switch bypasses the stop-intent marker the supervisor's own
`stop_prior` phase writes before its SIGTERM (`breezy.runtime.stop_intent_marker`) — if it lands on a
node that has not yet reached RUNNING, the CRITICAL `BOOT_HALT` alert **will** fire. Expected, not a bug:
treat it the same as any other unattributed halt.

#### (v-bis) First-boot verification (v3)

Run these checks against the newest `~/.local/share/breezy/logs/breezy-trade-[0-9]*T*Z.log` and the node's `/proc/<pid>/environ`:

1. **Environment flags:** `BREEZY_CONTINUOUS_RUNG_HOLD=1`, `BREEZY_ORDERS_ENABLED=1`, `BREEZY_LIVE_OBSERVATIONS=1`;
   absent: `BREEZY_CURRENT_RUNG_HOLD`. Verify: `cat /proc/<pid>/environ | tr '\0' '\n' | grep BREEZY_`.
2. **Boot-time permit line:** `grep 'live-trading permit issued issued_at_ns=' <NODE_LOG>` — exactly ≥1 line.
3. **Strategy armed per station:** `grep 'ContinuousRungHoldStrategy.*READY\|RUNNING' <NODE_LOG>` — one per active station.
4. **No Phase0PermitForbiddenError:** `grep 'Phase0PermitForbiddenError\|phase0.*forbidden' <NODE_LOG>` — expect empty.
5. **No trading refusals (critical):** `grep 'Trading refused' <NODE_LOG>` — expect empty. A `trading_refusals` entry
   (order_submission_permit=none) blocks every submit for the session.
6. **Exactly 4 BREEZY-NWS ERRORs (cosmetic):** `grep 'BREEZY-NWS.*ERROR' <NODE_LOG> | wc -l` — expect 4.
7. **Startup evidence present:** Query `~/.local/share/breezy/state/exec_polymarket_us.sqlite` with
   `sqlite3 -mode=ro <DB> "SELECT value FROM state WHERE key='exec/polymarket_us/startup_evidence';"` —
   expect `eof_complete=true` and `position_read_refused=false` (read-only query only).
8. **No family halt key (or cleared sentinel):** `sqlite3 -mode=ro <DB> "SELECT value FROM state WHERE key LIKE 'continuous_rung_hold/halt%';"` —
   expect empty or exactly `halt_cleared` entries. No active halt without evidence and approval.

The 17:05Z supervisor self-check (commit a858b93) automatically verifies items 1, 2, 3 and logs the results.

#### (vi) OPEN intent at launch

If an intent is still in OPEN state at the 16:50Z launch window, the supervisor **refuses** launch with
`REFUSE_INTENT_OPEN`. A CRITICAL `open_intent_stale` alert fires when an intent is unresolved for >15 minutes.
The resolver backs off 5→300 s polling; failure cases (GET 5xx, timeout, malformed response) keep it AMBIGUOUS.

**Recovery:**
- **Node not live:** Use `breezy-clear-submit-intent --yes --resolution <order-id=ID or no-order-exists> --evidence <positions-file>`.
  Requires venue evidence (positions + fill-record artefact from open-orders read).
- **Node can relaunch:** Relaunch the node so the resolver retires the AMBIGUOUS intent at startup via `reconcile_at_startup`.

#### (vii) Venue shape drift

When the venue changes its response structure, order-rejection lines log: `did not map` WARN or
`Trading refused ... could not be mapped`. These lines now carry a names-only `full body key tree` (no values).

**Fix:** Declare the new fields per surface in `src/breezy/adapters/polymarket_us/exec/reports.py` via
`_*_DRIFT_ALLOWED_KEYS` constants (reference the log timestamp as evidence). Never relax the mapping guard
(LESSONS L-37); new fields must be explicitly declared in code before orders resume.

#### (viii) Hand relaunch recipe

When a node must be restarted outside the 16:50Z window or after an unclean shutdown:

1. **Copy environment verbatim:** `env=$(cat /proc/<OLD_PID>/environ); echo "$env" | tr '\0' '\n'` (verify, never print).
2. **Stop the old process:** `kill -TERM <OLD_PID>` and wait for `TradingNode: DISPOSED` in the log (~11 s).
   **AUD-13d note:** this hand SIGTERM also bypasses the stop-intent marker (only `trade_supervisor`'s
   own `stop_prior` phase writes it) — a still-booting `<OLD_PID>` will page CRITICAL `BOOT_HALT` exactly
   as an unattributed crash would.
3. **Spawn the new node:** Mirror `trade_supervisor.spawn_node()`:
   ```
   subprocess.Popen(
     [".venv/bin/breezy-trade"],
     env=env,
     cwd=<repo>,
     stdin=subprocess.DEVNULL,
     stdout=<new-timestamped-logfile>,
     stderr=subprocess.STDOUT,
     start_new_session=True,
     preexec_fn=lambda: os.setrlimit(os.RLIMIT_CORE, (0, 0)) and os.close(os.fcopen(os.devnull, 'r')),
     close_fds=True
   )
   ```
   This detaches the node from the terminal and ensures clean shutdown on session end. The supervisor's
   16:40Z STOP_PRIOR finds running nodes by pgrep; a node that outlives its supervisor is an anticipated state.
   **A-1 note (docs/evidence/RULING_permit_daily_coverage_2026-09-25.md):** a hand-relaunched node mints a
   fresh, full-TTL permit with no daily coverage ceiling — this is outside A-1's automated-relaunch threat
   model since a human is deciding, but repeated hand relaunches in one trading day reproduce the same
   cumulative-coverage gap A-1 closes for `_do_midday_watch`, and are the operator's own call to make.

## Permit window posture (2026-09-25)

Ruled: `docs/evidence/RULING_B3_permit_window_posture_2026-09-25.md`
(trading-bot-architect + security-reviewer). Option (a) — accept the gap —
chosen over (a′) — move LAUNCH later.

**Nominal (single-mint):** permit runs 16:50Z→02:50Z (10h, `PERMIT_TTL_NS`).
Gap to the next STOP_PRIOR (16:40Z): ~13h50m.

**Worst case (multi-mint, WITHOUT the permit-cumulative-coverage cap):** a
mid-day relaunch as late as 00:59Z mints a fresh 10h permit expiring ~10:59Z.
Union of coverage: 16:50Z→~10:59Z (~18h09m). Gap to STOP_PRIOR: ~5h41m.

**With the cap** (`docs/evidence/RULING_permit_daily_coverage_2026-09-25.md`,
merged 13e4849): any mid-day-relaunch permit is capped at the day's
first-boot expiry, so worst-case coverage collapses back to the nominal case.

Both gaps fall entirely outside the union of the four station decision
windows (17:00Z→01:00Z, §6 above), so no live entry decision is denied by the
gap today.

**The gap is accepted and NOT alerted until B1 exists.** Moving LAUNCH is not
claimed to shift the capture or KILL-clock schedules — that Rev 1 claim was
unverified and has been dropped.
