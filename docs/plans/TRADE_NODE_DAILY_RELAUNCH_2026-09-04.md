# Trade Node Daily Relaunch — 2026-09-04 (Rev 3)

GOAL STATE: for every trading day D (UTC), exactly one `breezy-trade` process holds `<store>.intent.lock` and a
permit covering [17:00 UTC D, 01:00 UTC D+1] runs continuously from ≤16:50 UTC D to ≥02:00 UTC D+1; no second
`breezy-trade` ever runs concurrently; none of the seven values is ever written to any file, unit, rc, or repo
path; no systemd unit targets `breezy-trade`; no OPEN submit-intent survives a crash undetected [B1]; supervisor
death never silently loses more than one day [B2]; every process runs with `RLIMIT_CORE=0` and never
`repr()`/`str()`s an environ on any exception path [R9]; readiness gating never depends on an unpinned Nautilus
log string [E1]. Falsifiable by: 0 or >1 concurrent flock holders; node not ready by 17:00 UTC; a value on disk;
a trade-node unit file; an OPEN intent with no alert; a core dump; an env dump in any log.

## 2. Options considered

(a) In-process restart — REJECTED: `DailySpendLedger` is process-local (`operator_controls.py:257-281`),
`_PERMIT_BUDGETS` is written under `_REGISTRY_LOCK` in-process (`safety.py:622-626`); the once-daily reset is
DESIGNED behaviour (CRH_STEP8_BRIEF:280-288). (b) Coordinator-session cron/loop — REJECTED: dies with the
session. (c) Native Nautilus scheduled-restart — NOT FOUND: `kernel.py` grepped for
`restart`/`reschedule`/`scheduled_restart` (no hits); tree searched for `*schedul*` (no hits) — only
SIGTERM/SIGINT/SIGABRT graceful-stop (`kernel.py:558-572`); `TradingNode.run()` returns `None`, no restart hook
(`live/node.py:283-302`). (d) Detached supervisor — RECOMMENDED, §3.
**[N11]** Banned by the runbook's stated REASON (disk persistence), not its label: `systemd-run --user
--on-calendar --setenv=…` (transient unit under `/run` carries values); `at`/`cron` (spools the invoking env to
disk). Neither substitutes for (d).

## 3. Recommended mechanism

**Build-order prerequisite [E2]:** this design REQUIRES `app/trade.py` to emit a Breezy-owned INFO line
`live-trading permit issued issued_at_ns=<int> expires_at_ns=<int>` on the success path — currently only REFUSAL
is logged, at `app/trade.py:167-171` (`trade_cli.logger.info("live-trading permit not issued: %s", exc)`). This
line is a hard PREREQUISITE of the supervisor, not a follow-on; the supervisor must not be built before it
ships. The refusal path is promoted at the same time from a bare INFO log to
`breezy_alert(AlertPayload(severity="WARN", event="LIVE_TRADING_PERMIT_REFUSED", site="trade_node",
detail="permit_refused"))` through the existing sink (`health.py:342` `AlertPayload`, `health.py:388` `LoggingAlertSink`,
`health.py:495` `resolve_alert_sink`, `health.py:514` `emit_alert`), so a refusal reaches the webhook when
`BREEZY_ALERT_WEBHOOK_URL` is set, not only the log.

**Tree & residency [R5]:** `supervisor` (own SID/PGID) → `breezy-trade` (own SID/PGID). Long-lived, unattended:
holds the seven values in memory/environ for the HOST'S UPTIME, every spawned child inherits them fresh — SAME
exposure class as R3 (`/proc/<pid>/environ`, same-UID readable) but materially LONGER residency; not parity.
Peer ruling: a supervisor holding values only in memory, forwarding via child `env=`, is the runbook's
"automation shell" (R8 runbook :158-165), not the banned launcher-script artefact whose stated reason is disk
persistence (:183-184). Source never committed, never under `deploy/`; lives outside the repo tree or as an
in-memory `bash -c`/`python -c` body with NO values in argv.

**Env vs argv:** values travel via `env=` only, matching `config_from_env`/`exec_config_from_env` (runbook:179).
Supervisor argv carries a distinct token, `breezy-trade-supervisor-daily`, never substring-shared with the
node's argv [R8].

**[B1] Pre-launch OPEN-intent probe:** open a fresh read-only `SqliteStateStore` connection to the store (SQLite
serves concurrent readers) and read the submit-intent singleton. `arm()` refuses forever while state is OPEN
(`submit_intent.py:334-341,347-365`) — a node relaunched after SIGKILL/reboot mid-POST passes every §6 liveness
check yet can never place an order. If OPEN: do NOT launch; alert `INTENT_OPEN_BLOCKS_ARM` [B4]; retirement
requires the operator running `runtime/clear_submit_intent_cli.py` with an evidence artefact and
`BREEZY_CLEAR_SUBMIT_INTENT_ACK=1` — never invoked by the supervisor. **Explicit rule: the supervisor never
sends SIGKILL to the node** — SIGTERM only. **[E5 scope]** this probe is PRE-LAUNCH ONLY, reading via a fresh
connection outside any mutex or flock — unlike the latch's own serialised read inside `arm()`'s `with
self._mutex:` span (`submit_intent.py:359-365`); it must never be invoked while a node may be running.

**[B2] Supervisor-death adoption:** if this supervisor did not spawn the node holding the flock (prior
supervisor died at 03:00 UTC; node, own SID, survived), do not blind-refuse. At 16:40 UTC, probe: `pgrep -f
'breezy-trade$'` for a live node AND whether `<store>.intent.lock` is held. **[E5]** ADOPT only if the flock
holder's PID EQUALS the pgrep'd PID, verified via `/proc/locks` (or `lslocks -p`) cross-referenced against the
lock file's inode — never assumed from pgrep alone, so an operator's manual `.venv/bin/breezy-trade` is never
SIGTERMed unless it is verified to be the store's actual flock holder. Refuse-and-alert if adoption fails or the
PIDs disagree.

**[R6] Split stop/launch, 16:40 / 16:50 UTC:** SIGTERM the (owned or adopted) prior node at 16:40; `waitpid()`
bounded; poll-acquire the flock to confirm release. Launch at 16:50 only if released; otherwise do NOT launch,
do NOT kill again, alert [B4].

**[B3/E1] Startup-only bounded relaunch, Breezy-owned readiness only:** readiness before 17:00 UTC is the
THREE-way conjunction (a) the node holds `<store>.intent.lock` (`app/trade.py:105`, acquired via
`open_submit_intent_latch` BEFORE `build_current_rung_hold_strategies`/node build) AND (b) the permit-issued
line (E2 prerequisite) AND (c) at least one `CurrentRungHoldStrategy subscribed` line (Breezy-owned,
`strategy/current_rung_hold/strategy.py`, emitted only after `on_start`, i.e. after node build, exec connect
and reconciliation). (a) and (b) alone are both true BEFORE the strategy exists, so a failure in the
build → connect → reconcile span — the one real failure observed on the first launch, exec client never
connected — must still count as pre-readiness and stay relaunch-eligible under E4. NEVER
`TradingNode: RUNNING`/`Execution state reconciled`, which are emitted by immutable Nautilus and pinned by no
Breezy test; this design consults neither in control flow, so no pinning test is required for them; the
three control-flow substrings above ARE pinned by Breezy tests (build obligation).

**[E4] Bounded relaunch:** at most 2 attempts, ≥3 min apart, never after 17:00 UTC. The two exit-1 causes are
distinguishable by LOG TEXT, not exit code: a permit/config refusal logs `order submission permit not issued`
(`app/trade.py:186-188`, returned before `trade_cli.run` is ever entered) and is DETERMINISTIC — the
supervisor's own env is fixed for its lifetime, so relaunching cannot change the outcome — NEVER relaunch on
this text. A generic build-time exception logs `trading node failed: ...` (`trade_cli.py:404-405`, `_run_node`'s
catch-all) and MAY be transient (e.g. venue connect) — only this category is eligible for bounded relaunch.

**[R7a] Supervisor mutual exclusion:** an exclusive `flock` on a supervisor-owned lock path, same pattern as
`submit_intent.py:493-513` / `persistence/catalog.py:829-856` — not a pgrep marker. A second supervisor refuses
and logs loudly.

**[R7b] Response keyed on flock state, not exit code:** `EXIT_CONFIG_ERROR` (2) covers both intent-lock refusal
AND `SettingsError`/`NodeConfigError`/`OSError` (`trade_cli.py:124-128`). Supervisor probes `flock -n` on
`<store>.intent.lock` directly: held → duplicate-node path, never retried; released → config error, retryable
ONCE before 17:00 UTC after the coordinator fixes it, never auto-looped.

**[B4/E1/E3] 17:05 UTC self-check + alert channel:** checks — intent-flock held by the tracked PID;
permit-issued line present with expiry beyond now (E2, runnable per §6); `CurrentRungHoldStrategy subscribed`
logged (Breezy-owned) — writes PASS/FAIL. **[E3]** node ready but NO live-trading permit (shadow mode) is a
distinct FAIL state, alerted, with NO relaunch (deterministic per E4): with `BREEZY_ORDERS_ENABLED=1` the absent
permit instead exits 1 PRE-readiness (`order_enablement.py:195-199`) before this state is reachable; without it,
the node runs all day trading nothing and the FAIL simply flags that condition. Alert channel:
`breezy.runtime.health` — `breezy alert event=... severity=... detail=...` (`health.py:388-408`,
`LoggingAlertSink`) logs via the `breezy` logger, forwarded into the Nautilus log stream; reaches beyond the log
ONLY when `BREEZY_ALERT_WEBHOOK_URL` is set (`health.py:114`, `composition.py:296-298`) — otherwise log-only.
Supervisor reuses this sink for PASS/FAIL and all refusal states.

**[N10] Clock:** permit `issued_at_ns`/`expires_at_ns` logged at startup (E2); 17:05 check compares wall clock.
An NTP step backward trips "permit used before it was issued; clock is untrusted" (`safety.py:718-719`) and
refuses every order — detectable (§4), not solved here.

**[R9] Hardening:** both processes call `resource.setrlimit(resource.RLIMIT_CORE, (0, 0))` at start. Neither
process ever `repr()`/`str()`s its own or a child's `env` on any exception path (caught, reported by
type/message only, matching `_report()` at `trade_cli.py:175-179`). Swap residency is ACCEPTED, not mitigated.

**Logs:** `breezy-trade-<YYYY-MM-DD>.log`; supervisor → `breezy-trade-supervisor.log`. **Operator stop:**
SIGTERM the supervisor (never SIGKILL), then SIGTERM the tracked node — no file, no unit.

## 4. Failure modes

| Mode | Response |
|---|---|
| OPEN intent after crash | [B1] pre-launch probe blocks launch, distinct alert, human retirement via clear-intent CLI. |
| Supervisor dies mid-day | [B2] next supervisor adopts the PID-verified flock holder at next 16:40 cycle; no day silently lost. |
| Startup exit 1, transient (build-time exception) | [E4] bounded relaunch, ≤2 attempts, ≥3 min apart, before 17:00 UTC. |
| Startup exit 1, permit/config refusal | [E4] NEVER relaunch — deterministic given a fixed supervisor env. |
| Ready but no live-trading permit (shadow mode) | [E3] 17:05 FAIL + alert, NO relaunch. |
| Exit 1 after readiness (all three signals observed) | Hard no-restart — one process/day. |
| Exit 2, flock held | Duplicate-node path, never retried [R7b]. |
| Exit 2, flock free (config error) | Retryable once before 17:00 UTC [R7b]. |
| Clock skew / NTP step backward | [N10] detectable via `clock is untrusted` refusals; not auto-corrected. |
| Two supervisors | [R7a] second refuses via exclusive flock, not pgrep. |
| Recorder unit restarting | Unrelated tree (`deploy/systemd/`); no interaction with trade-node flock/permit. |

## 5. Security

`/proc/<pid>/environ` exposure is the same CLASS as R3 but LONGER RESIDENCY — disclosed, not parity [R5]. No new
file holds values; supervisor source lives outside the repo tree or in-memory only. No new systemd unit.
`RLIMIT_CORE=0` on both processes; no env `repr()`/`str()` on any exception path [R9]. Swap residency accepted,
not mitigated. **[Security LOW]** the supervisor's own alert `detail` payload is always a fixed enum string
(e.g. `permit_refused`, `intent_open`, `lock_held`) — never exception text or any value-bearing string, matching
`AlertPayload`'s own ban on raw upstream bodies (`health.py:352-354`).

## 6. Verification checklist (no secrets required)

- `pgrep -f 'breezy-trade-supervisor-daily$'` — exactly one match, anchored [R8].
- `pgrep -f 'breezy-trade$'` — one match 16:50–02:00 UTC, zero outside, anchored so it never substring-matches
the supervisor's own argv [R8].
- `ps -o sid,pgid,pid,cmd -p <supervisor_pid> <node_pid>` — each its own SID/PGID.
- `flock -n <store>.intent.lock -c true` fails while the node runs; the holder PID (via `/proc/locks`) matches
the tracked node PID [E5].
- Node log shows the permit-issued line `issued_at_ns=... expires_at_ns=...` [E2] and `CurrentRungHoldStrategy
subscribed` [E1] — the two Breezy-owned readiness signals.
- `TradingNode: RUNNING` / `Execution state reconciled` may still be READ by a human as a manual sanity check
[E1] — never consulted by supervisor control flow, so no pinning test is required for this item.
- `cat /proc/<pid>/limits | grep 'Max core file size'` — `0` for both processes [R9].
- Supervisor log shows a 17:05 UTC PASS line for the day [B4].

## Open risks / not satisfied here

- Adoption's `/proc/locks`-to-PID cross-reference [E5] parsing/tooling is left to the build stage.
- Distinguishing transient vs deterministic exit-1 by log-text substring [E4] is not itself pinned by a Breezy
test; a pinning test for that substring is recommended at build time.

**Converged peer review (2026-09-04):** architecture BLOCK→REVISE→REVISE→one-edit (applied above: three-way readiness conjunct, `:33` citation); security REVISE→APPROVE (LOW: alert `detail` is a fixed enum). No further round warranted. Build-stage test obligations: pin the three control-flow substrings (permit-issued line, `order submission permit not issued`, `trading node failed`) and `CurrentRungHoldStrategy subscribed`; assert ≤2 attempts, ≥3 min apart, none at/after 17:00 UTC, zero after readiness; SIGTERM only when the `/proc/locks` holder PID equals the discovered PID, refuse-and-alert otherwise; `RLIMIT_CORE == (0, 0)` in both processes; no log record or alert `detail` ever carries an env value or exception text; never SIGKILL; the OPEN-intent probe refuses to run while a node PID is live.
