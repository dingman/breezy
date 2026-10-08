# SUP-RESTART-ANYTIME r4.1: delta to r4 (HEAD bd32de69, 2026-10-08)

**Base.** r4 (`SUP-RESTART-ANYTIME_plan_r4.md`, APPROVED in `reviews/SUP-RESTART-ANYTIME-r4-final.md`). Only the sections below change; everything else is r4 text.

**Author.** Planner. The coordinator adopted it pending a single peer check of D2.3 and T16d.

## D1 Alert delivery
Replaces r4 :12 "No new delivery mechanism…", §1 rows :70/:71, §2.4 :249-254, R9 :441 and R10 :442.

### D1.1 §1 "Alert path" row (:70)
- In production, `resolve_alert_sink()` (`health.py:392-430`) returns `TeeAlertSink(LoggingAlertSink(), JournalingWebhookAlertSink(url, writer="legacy_runtime"))`.
- `JournalingWebhookAlertSink` (`alert_delivery.py:88-119`) sends through `deliver_with_proof` (`alert_proof.py:216-261`), which:
  - writes a `DeliveryRecordWriter` record for every send;
  - writes and fsyncs an `AlertOutbox` entry for proof-bearing payloads (every CRITICAL, `is_proof_bearing` at `:140-142`) and claims it before the POST;
  - raises `AlertNotDeliveredError` on any non-2xx response.
- The Tee contains that raise through `emit_alert` (`health.py:486-517`):
  - `_send_permit_alert` still returns True (SH1 holds).
  - The local line is `alert sink failed to emit event=… exception_type=AlertNotDeliveredError`.
  - An undelivered CRITICAL stays in `outbox/claimed/legacy_runtime/`.
- `breezy-autonomy-alert-redeliver.timer` (`*:03/5`) runs `drain_outbox` (`alert_drain.py:108`). It reclaims claims older than 60 s and re-POSTs them until delivered. After 24 h it names them abandoned.
- **Verdict: REUSE.** No supervisor code is needed. The step sends on `ports.alert_sink` and so inherits the outbox.

### D1.2 §1 "Delivery-proof helper" row (:71)
"Shipped by AUT-6 WP1 (bd32de69). It is reached through the production sink and never called directly. Nothing is built here."

### D1.3 §2.4 Delivery bullet (:249-254)
Retitled "logged locally; CRITICAL durably queued and redelivered; WARN best effort".
- **READY_ADOPTION CRITICAL:** a local line plus an outbox entry. If the POST fails, redelivery happens within about 5–6 min.
- **READY_ADOPTION WARN:** the event is not in `PROOF_BEARING_EVENTS` (`alert_proof.py:41-65`). It gets a delivery record but no outbox entry, so it is best effort.
- **The 60-poll CRITICAL re-fire is KEPT.** Its purpose changes from webhook retry to a reminder that the condition persists.
  - The bound stays ≤8 per child per night, which is immaterial against `ALERT_OUTBOX_MAX=128`.
  - If the outbox is full, the result is `outbox_overflow` and the local line is still written.
- Latch-on-True is unchanged.

### D1.4 Tests
- **T16c stays valid.** It injects its own `WebhookAlertSink` with a 503 MockTransport. Add a comment that it is not the production branch type.
- **New T16d:** `test_ready_adoption_critical_queued_in_outbox_through_production_sink`.
  - Setup: `alert_sink = TeeAlertSink(LoggingAlertSink(), JournalingWebhookAlertSink("https://alerts.invalid/hook", client=httpx.Client(transport=MockTransport(503))))`, with `default_alerts_root` monkeypatched to `tmp_path`, running the T16c scenario for 13 polls.
  - Assert:
    - (a) the poll-12 CRITICAL leaves exactly one `*_TRADE_SUPERVISOR_READY_ADOPTION_DEFERRED.json` under `outbox/claimed/legacy_runtime/`;
    - (b) the poll-5 WARN leaves no outbox entry;
    - (c) `exception_type=AlertNotDeliveredError` is logged;
    - (d) after the claim ages past 60 s, `drain_outbox(drainer="redeliver", …)` with a 200 MockTransport delivers and removes it;
    - (e) the URL appears in no log line.
  - No socket is opened, so NO-SEND is untouched.
- Add `tests/unit/test_alert_delivery.py` to the focused gate (:355).

### D1.5 R9 (:441)
"CRITICALs are durably queued and redelivered by the AUT-6 WP1 outbox. The redeliver timer must be enabled (D5 pre-check). WARNs are best effort. Residual risk: a CRITICAL undelivered for 24 h is abandoned and named by the drainer."

### D1.6 R10 (:442)
**CLOSED.** WP1's check-alerts fix routes the production path through `deliver_with_proof` (`check_alerts_cli.py:172-195`). Only the test `sink_factory` path calls `sink.emit` (`:144`).

### D1.7 §5 README row (:371)
"CRITICALs are queued in the alert outbox and redelivered by `breezy-autonomy-alert-redeliver.timer`; WARNs are best effort."

## D2 Orders OFF: activation versus acceptance
Replaces §6 :429, §7 :449-459, §0 :53, and README/memory rows :371/:373.

### D2.1 Premise
- `fq-v1-halt-orders-off.conf` sets `BREEZY_ORDERS_ENABLED=0`, and RULING_FQ-v2-NO-TRADE_2026-10-08 is in force.
- Every node therefore logs `order submission permit not minted: orders not requested` (`app/trade.py:1269`, `PERMIT_NOT_REQUESTED_MARKER` at core:155).
- Check 5 yields NOT_REQUIRED (C12, terminal) on every in-window poll, so the step never marks.
- **Parity:** a supervisor that never restarted also never sets `readiness_observed`, so MIDDAY_WATCH is not due either way. This plan changes nothing under orders-off.
- The plan never touches the drop-in, the permit or enablement.

### D2.2 §6 merge-blocking item 4 (:429)
- New item 4: "[ ] State whether the node at merge time is armed. If it is unarmed (expected), the activation proof is D2.4 and the MARK proof is DEFERRED per D2.5."
- Items 1–3 (SM3 re-measure) stay merge-blocking.
- If the 7-day span has no SHADOW_DECISION, item 2 is vacuous. Record that and keep the r4 basis (15.1 s over 2 FQ days).

### D2.3 Evidence line
Amends §2.2 :210 and §2.1 :186-193.
- Add a 5th per-child field, `ready_adoption_terminal_logged: bool = False`. `record_child_adopted` and `_for_day` clear it.
- On a terminal verdict of NO_CHILD, PERMIT_EXPIRED or NOT_REQUIRED, while the field is False: emit `log_decision("ready_adoption_terminal", verdict=<value>, pid=<tracked_pid>)` once, then latch the field.
- NOT_IN_WINDOW and ALREADY_READY stay silent (shell early returns).
- T5 gains the field. T10b asserts exactly one `ready_adoption_terminal verdict=not_required pid=<pid>` line across 200 polls. T1 is unchanged.

### D2.4 Activation proof
Replaces §7 :455-457. On the first in-window poll after the restart (≥17:10Z the same day, with no further restart), the supervisor journal shows:
- `permit_watch phase=permit_watch capability=not_required`, and `breezy alert event=TRADE_SUPERVISOR_PERMIT_NOT_REQUIRED … severity=WARN` (B1, unchanged);
- `ready_adoption_terminal verdict=not_required pid=<node pid>` (the new step, evaluated).

It must NOT show, all night:
- `restart_adopted_ready_node`, `ready_adoption_deferred` or `TRADE_SUPERVISOR_READY_ADOPTION_DEFERRED`;
- a MIDDAY_WATCH dispatch;
- any spawn or signal other than the scheduled 16:40/16:50 ones.

The adoption-path variant is proven by T10b and T17 only.

### D2.5 DEFERRED (machinery proven only, mirroring AUT-6 X-7)
- The live MARK proof is deferred to the first armed boot after a re-arm ruling that coincides with an in-window supervisor restart. It is the sequence `permit_watch_adopted_live_node` → `restart_adopted_ready_node pid=… liveness_age_s=…` within 2 polls → MIDDAY_WATCH dispatch.
- Record it in PROGRESS as an open acceptance item.
- Until then:
  - §0 :53 is amended: the 01:00–16:40Z restart restriction is NOT retired.
  - README :371 keeps the restriction and adds "ready-adoption shipped; restriction retires after the D2.5 proof".
  - Memory :373 is deferred.
  - "Activate at any UTC instant" is superseded by D5.

## D3 Coordination with AUT-6 WP6
Amends §2.1 :184 and §5 :365-366.

### D3.1 Compatible with WP6
- WP6 moves the regex so that a bwrap-wrapped unit can use it without importing `trade_supervisor`.
- `trade_supervisor_core.py` imports only the stdlib, so keeping the regex in core satisfies WP6's closure intent.

### D3.2 Naming
- Core defines a public `NODE_LOG_NAME_RE = re.compile(r"^breezy-trade-(\d{8}T\d{6}Z)\.log$")`.
- `trade_supervisor.py` binds `_NODE_LOG_NAME_RE = NODE_LOG_NAME_RE`, so `test_trade_supervisor.py:37` and `find_adopted_node_log` :834 need no edits.
- T6b asserts the identity.
- Known DRY debt, out of scope: `analysis/capture_node_log_spawns.py:78` holds an identical literal.

### D3.3 Order: SUP lands first
Hand-off note for the AUT-6 errata:
- "WP6 M2: `NODE_LOG_NAME_RE` already lives in `trade_supervisor_core` (SUP-RESTART-ANYTIME, with a capture group). WP6 does NOT move it."
- WP6 drops the regex row from the M2 table (:339) and from the `flock_holders.py` inventory (:191, :1385).
- Consumers import it from core.
- `test_trade_supervisor_lock_names_are_the_moved_objects` drops the regex pair.
- Re-run `lint-imports`.
- Fallback: `flock_holders.NODE_LOG_NAME_RE` becomes an alias of the core object.

## D4 Anchor re-verification at bd32de69
- **Exact anchors:** all `trade_supervisor.py`, `trade_supervisor_core.py` and `strategy.py` anchors cited by r4.
- **Drifted anchors:** update these citations. None changes the design.
  - `health.py`: `resolve_alert_sink` 392-430; `emit_alert` 486-517; failure log 511-517.
  - `check_alerts_cli.py`: production path at 172-195.
  - `app/trade.py`: duplicate-refusal at ~1115-1136.
  - `adapters/polymarket_us/data.py`: `should_warn_at_count` at 578; `_note_depth_truncation` at 2000-~2055.

## D5 Activation
Replaces §7 :449-453.
- Merge only after the full gate exits 0, and read the EXIT code first.
- Restart only inside [01:00Z, 16:40Z): `systemctl --user restart breezy-trade-supervisor` (no daemon-reload).

**Pre-checks**
- (a) `systemctl --user show breezy-trade-supervisor -p MainPID,ActiveState,DropInPaths,Environment`:
  - ActiveState is active;
  - DropInPaths lists `fq-v1-halt-orders-off.conf`;
  - Environment contains `BREEZY_ORDERS_ENABLED=0`.
- (b) Node pid:
  - take it from `systemd-cgls --user-unit breezy-trade-supervisor` (never pgrep);
  - run `ps -o pid,etimes,args -p <pid>`;
  - confirm the pid is the intent-flock holder in `/proc/locks`.
- (c) The newest `~/.local/share/breezy/logs/breezy-trade-*Z.log` contains `order submission permit not minted: orders not requested`. If it shows a permit line instead, STOP.
- (d) `systemctl --user is-active breezy-autonomy-alert-redeliver.timer` returns active.

**Post-checks**
- (a) The node pid is unchanged and its etimes keeps increasing.
- (b) The journal shows `supervisor_started … revision=<merge sha>`, with no `phase_exception_contained`, `permit_watch_exception_contained` or `TRADE_SUPERVISOR_*` CRITICAL.
- (c) No step lines appear before 16:40.
- (d) The 16:40/16:50 lines appear as usual.
- (e) D2.4 is observed at ≥17:10Z.

**Rollback:** revert the merge and restart within the same window.

## Verdict
READY: r4 plus this delta.

---
## Peer-review amendments: binding, architect review 2026-10-08, verdict SOUND-WITH-CHANGES

The architect verified D1, D2.3, D3 and D5 at bd32de69. These changes are binding on the build.

- **A1 (T16d setup).** Monkeypatch the closure target:

  `monkeypatch.setattr("breezy.runtime.alert_delivery.default_alerts_root", lambda: tmp_path)`

  The name resolves in `alert_delivery`'s globals. Patching `alert_outbox.default_alerts_root` has no effect; this is the same target `test_alert_delivery.py:67` uses.

- **A2 (T16d transports).** Use `httpx.MockTransport(lambda request: httpx.Response(503))`, and the same form with 200 for (d).

- **A3 (T16d, replaces item (d)).** `drain_outbox` does not drive the stale check; `reclaim_stale` reads wall-clock `time.time()` against file mtime. So:
  1. Backdate the claim: `os.utime(claimed, (time.time() - 61, time.time() - 61))`.
  2. Call `drain_outbox(drainer="redeliver", outbox=AlertOutbox(tmp_path), sink=TeeAlertSink(LoggingAlertSink(), WebhookAlertSink("https://alerts.invalid/hook", client=<200 client>)), records=DeliveryRecordWriter(tmp_path), min_age_s=REDELIVER_MIN_AGE_S)`.
  3. Assert `summary.reclaims == 1` and `summary.delivered == 1`.
  4. Assert there is no `*.json` under `outbox/claimed/legacy_runtime/` or `outbox/claimed/redeliver/`.

- **A4 (T16d, new item (f)).** Assert a delivery record exists with `writer` `legacy_runtime`, `status_class` `5xx`, and `outbox_entry` equal to the claimed filename.

- **A5 (D5 pre-check (a)).** The last `BREEZY_ORDERS_ENABLED=` token in `Environment` must be `=0`. The base unit sets `=1` at :121 and the drop-in sets `=0`, so `show` lists both.

- **A6 (D5, new pre-check (e)).** Check these without ever printing the value:
  - `~/.config/breezy/alerts.env` exists and is non-empty.
  - It defines `BREEZY_ALERT_WEBHOOK_URL` (`grep -c '^BREEZY_ALERT_WEBHOOK_URL='`).

  Without it, `resolve_alert_sink` returns a bare `LoggingAlertSink` and D1's outbox path does not apply.

- **A7 (D5 pre-check (c)).** Check the node log bound to the pid from (b), not the newest log: its mtime must be ≥ the `/proc/<pid>` ctime, which is how `find_adopted_node_log` selects it. A refused duplicate's newer log could otherwise give a false pass.

- **A8 (D2.4).**
  - Change "on the first in-window poll after the restart" to "on the first in-window poll after the restart on which B1 has latched `orders_not_requested_seen`".
  - Add: `ready_adoption_terminal verdict=not_required` must appear in the same poll as, or a later poll than, the B1 `capability=not_required` line. No `ready_adoption_deferred` line may precede it.

- **Note (non-blocking).** D2.3 latches the first terminal verdict per child, so a later and different terminal verdict for the same child is silent. That can only happen through child turnover, which clears the field. Say this in the docstring.

**Verdict after amendments: READY.**
