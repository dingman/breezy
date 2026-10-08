# AUT-6 WP2 verify-first STOP: Path B ruling (2026-10-08, coordinator; IN PEER REVIEW)

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
