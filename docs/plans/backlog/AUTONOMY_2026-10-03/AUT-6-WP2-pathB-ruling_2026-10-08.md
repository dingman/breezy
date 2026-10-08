# AUT-6 WP2 verify-first STOP: Path B ruling (2026-10-08, coordinator; r2 after security and architect review: READY)

**Binding inputs:**
- plan r15 §AUT-6.WP2 (l.1162), §3.7.1 (l.917) and R-9 (l.1557);
- ARCH §4.6 (`reviews/snapshots/ARCH_rev9_2.md:990-993`).

## Finding (verify-first)

- **The receiver.** It is the public ntfy.sh service. `~/.config/breezy/alerts.env` holds one key, `BREEZY_ALERT_WEBHOOK_URL`, which is a topic URL on the host `ntfy.sh`. This is observed config. Only the variable name and the host were read, never the topic.
- **Absence rules are supported, but only when the sender arms them.** The evidence class is vendor documentation: docs.ntfy.sh/publish, "Scheduled delivery" and "Updating scheduled notifications".
  - A publish to `/<topic>/<sequence-id>` carrying an `At:` or `In:` header (10 s to 3 days) is held, then delivered at that time.
  - Re-publishing with the same sequence id replaces the pending message.
  - Nothing can be configured on the receiver side.
- **Consequence: Path B.** Under plan §3.7.1, Path A is a receiver-side rule, and that does not exist here.

## Rulings

1. **No new key and no new host.**
   - The heartbeat URL is derived in code as `BREEZY_ALERT_WEBHOOK_URL + "/" + HEARTBEAT_SEQUENCE_ID`.
   - `HEARTBEAT_SEQUENCE_ID` is a module constant (`aut6_canary_deadman`), pinned in `persistence/autonomy/pins.py`.
   - `alerts.env` stays single-key, so the AUD15 contract and `migrate-alerts-env.sh` are unchanged.
   - `test_autonomy_alert_egress_not_widened` is re-pinned in the same commit, by one reviewed row: same host, plus the derived sequence path, and only the canary CLI reads it.
2. **Re-arm target.**
   - Every *delivered* canary re-publishes the dead-man message with `At:` set to the next 16:15Z that is at least 60 min ahead. In practice the 15:45Z canary on day D moves the alarm to D+1 16:15Z, and later slots leave it there.
   - The message text names the alarm: "AUT-6 canary absent: no delivered canary since <ts>".
   - The suppression drill (plan §3.7, on its pre-registered dates only) skips the re-arm, so the 16:15Z alarm fires. That page timestamp is the live proof.
3. **Topic secrecy, accepted risk.** Anyone who knows the topic can already read alerts, and could also DELETE or replace the pending alarm. The topic is already treated as a secret: env file only, never logged, and the test-suite secret scans. No new exposure is created. This is recorded here as an accepted risk.
4. **Failure handling.**
   - If the re-arm publish fails, that is a canary failure under the existing rules: queue a CRITICAL and exit 0.
   - The detector `alerts_undeliverable` does not count heartbeat publishes. It counts canary and CRITICAL delivery records only, as in the plan.
5. **Unit hygiene.** The canary unit contains no mount-namespace directive. The bwrap row is the only control (redeliver defect, fixed by a65ee68f/03789239).

## Build

WP2 is built per plan r15 l.1162-1169 with the stale anchors corrected:
- `deliver_with_proof` lives in `alert_proof.py:216`;
- the unit tests go in `tests/contract/test_autonomy_units_canary.py`;
- the writer is `canary`.

Path B adds two RED tests:
- `test_canary_heartbeat_rearms_on_delivered_canary_only`;
- `test_suppress_drill_skips_heartbeat`.

---
## r2 amendments (BINDING; they supersede rulings 1 and 4 where they conflict)

Sources: security-reviewer (CHANGES, 6 items) and architect (CHANGES, 11 items), both 2026-10-08.

**Plan erratum E-WP2-1.** Plan l.917 and R-9 (l.1557) call for a new key, `BREEZY_ALERT_HEARTBEAT_URL`. That is superseded: the heartbeat URL is derived and no new key exists. A builder must not add the key.

### A1. Where the heartbeat send lives
- A single new method on the existing sink: `WebhookAlertSink.schedule_deadman(*, sequence_id: str, at_utc: datetime, title: str, message: str) -> bool` in `src/breezy/runtime/health.py`.
- It is outside the autonomy tree. The canary therefore never names `BREEZY_ALERT_WEBHOOK_URL`, never touches `_url`, and never holds an `https://` literal.
- `test_autonomy_alert_egress_not_widened` stays unchanged, and `ALERT_EGRESS_ALLOWED_IMPORTS` stays `frozenset()`.
- A new test pins three things:
  - the method's name;
  - its only headers: `At`, `Priority: high`, `Title`;
  - the derived host, which must equal the base URL's host.

### A2. Deriving the URL
- Build it with `urllib.parse.urlsplit`.
- Refuse, failing closed, if the base URL has a query or a fragment.
- Strip one trailing slash, then append `/<sequence_id>` to the path.
- Re-run `_validate_webhook_url` on the result.
- The sequence id must match `^[-_A-Za-z0-9]{1,64}$` and must not be `json`, `sse`, `raw` or `ws`.
- RED tests cover: a trailing slash, a query (refused), a fragment (refused), and host equality.

### A3. Send semantics
- One POST with `follow_redirects=False`. Only a 2xx counts as success; a 3xx is failure.
- On error, log only `type(exc).__name__`.
- The method writes **no** delivery record. A test proves this.
- The canary CLI entry point pins the `httpx` and `httpcore` loggers to WARNING, and a test proves it. No code interpolates the URL into a string that is logged.

### A4. Recording and order
1. The canary runs `deliver_with_proof` first. That writes its normal `attempt_kind=canary` record.
2. Only if that delivery succeeded, the canary calls `schedule_deadman` for both alarms (A6).
3. It writes `evidence/alerts/<date>/heartbeat_<slot>.json` containing `{rearmed: bool, targets: [...], error_type}`. This is a new single-writer file with a row in the one-writer test.
4. A failed re-arm queues a CRITICAL `canary_heartbeat_rearm_failed` through the outbox, and the canary exits 0.

`alerts_undeliverable` (#5) ignores heartbeat files, enforced by `test_alerts_undeliverable_ignores_heartbeat_records`. A failed re-arm is fail-safe: the old alarm fires as a false page, which is acceptable.

### A5. Target time
- The alarm targets the next 16:15Z that is at least 60 min after now.
- RED test `test_heartbeat_target_is_next_1615z_at_least_60min_ahead` covers 14:45, 15:14:59, 15:15, 15:45, 16:30, 16:45, 17:10 and 23:45.

### A6. Repeated paging during a long outage
- Two sequence ids: `aut6_canary_deadman_d1` at the target time and `aut6_canary_deadman_d2` at target + 24 h.
- Every delivered canary replaces both.
- A host that dies is therefore paged on two consecutive days. Beyond that, the single-page limit is an accepted risk.

### A7. Accepted risks (they replace ruling 3's wording)
- **Silent cancellation.** Anyone who holds the topic can silently cancel the dead-man with a DELETE or a replacing publish. This defeats the control invisibly, which is worse than a forged alert.
- **Shared receiver.** An ntfy.sh outage defeats both the heartbeat and the page.
- **Mitigation.** The topic is held only in `alerts.env` (0600). It is never logged, enforced by the secret scan in `tests/unit/test_autonomy_envelope.py::_scan_alert_egress` and by the `_secret_findings` unit scans.

### A8. Verify-first (the builder, before any production code)
**V-a, live replace check:**
- Use a freshly generated random scratch topic (`claude-aut6-<uuid4 hex>`), never the production topic.
- Publish twice with the same sequence id and `At: +60s`, then poll the topic JSON feed after 90 s.
- Exactly one message must be delivered, and it must have the second message's text.
- Also check that a DELETE of a scheduled message cancels it.
- Any mismatch is a STOP, and the design goes back to review.

**V-b, ntfy.sh limits:** document the anonymous limits on the public server (daily message cap, scheduled-message cap, retention) in `docs/evidence/aut6/WP2_verify_first_2026-10-08.md`. Our load is about 30 publishes a day.

### A9. Network
The canary bwrap row is `network="egress"` with `resolves_dns=True`. It is never `--unshare-net`. Its binds are `evidence/alerts` only, and its closure contains no venue, adapter or execution module.

### A10. Activation criteria
These come in addition to the plan's criteria:
- The first full day after the timer is enabled shows a `delivered=1` canary at 15:45Z, `heartbeat_1545.json` with `rearmed=true`, and **no** 16:15Z page.
- The suppression drill, on its pre-registered date, shows the 16:15Z page.
- The coordinator reads the page timestamp in a one-off poll of the topic's JSON feed. The URL is never printed. The timestamp is recorded as a text attestation, and its hash goes into C4 `HEALTH`. No bot read path is added.

**Status:** READY. Both reviewers' items are addressed above.
