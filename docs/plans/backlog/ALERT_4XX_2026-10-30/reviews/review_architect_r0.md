VERDICT REVISE (architect on plan_r0, ~15:35Z). Diagnosis right; (a) sound; (b) needs redesign; (d) + order need fixes.
HIGH-1 (b) can hold a CRITICAL 6 h past the 00:00Z quota reset: cap backoff 30-60 min; POST the newest entry as a probe each pass even in backoff; clear backoff on any 2xx.
HIGH-2 (b) wrong level: 429/401/403/404/rotated target hit every entry at once; only payload-rejection is per-entry. Use ONE global backoff file under alerts_root (no per-entry unlink/orphan problem; complete runs elsewhere alert_proof.py:259-260).
MED-3 backoff file follows the outbox file rules: no symlink following, mode 0o600, atomic like _publish (alert_outbox.py:76-99; C1 symlink test test_alert_outbox_hardening.py:235); not .json; read BEFORE claim.
MED-4 (c) has no ordering rule (_work_list oldest-first alert_drain.py:91-104): drop (c) or attempt CRITICAL + never-drained first; the 40 s budget already bounds the slow case.
MED-5 (d) as written drops the TeeAlertSink local "breezy alert event=..." line on repeats (the 09-20 line class): on repeats emit to LoggingAlertSink() alone so the local line is untouched; skip only the webhook POST.
MED-6 outage visibility: one WARNING per backoff episode from the drain with the exact status code (no URL); backlog item "no 2xx in N hours" health check; note outbox fills to 112 entries then refuses non-CRITICAL proof-bearing alerts without a POST (alert_outbox.py:123-128, alert_proof.py:243-244).
MED-7 shipping order: (a)+(d) first (no proof-bearing retry change, (d) no re-pin), revised (b) second.
LOW-8 exact-code rule: 429 -> back off; 401/403/404/410 -> dead/rotated target = operator config action; 400/413/422 -> payload. Retry-After optional.
LOW-9 two drainers theoretical: run_deadman_drain (alert_delivery.py:70) has no caller in src/; only redeliver runs.
LOW-10 separate backlog: _alert calls resolve_alert_sink() per denial (strategy.py:977): new httpx client each time, never closed, up to 5 s POST on the kernel thread.
Answers: (1) confirmed is_proof_bearing alert_proof.py:140-142, queue gate :242; (2) nothing deletes before 2xx; delay not loss; (3) no schema bump (precedent outbox_write_failed alert_outbox.py:269-270; readers capture_aut6_contract.py:129, unit_health_intraday.py:356, unit_health_store.py:469); (4) (d) not a weakening if done per MED-5.
Citations 19 ok; wrong: test name (real: test_deliver_with_proof_reports_non_2xx_through_tee).
