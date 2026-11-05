Commit: e4848c39a979bac5a91b8f6b3887f75c497c1be8

# Alert delivery — one CRITICAL reaches a human (2026-09-12) — Rev 1

**L-1 (three verdicts).**
1. **Alert DELIVERY: GENUINELY-ABSENT in Nautilus.** `grep -rl "AlertSink|alert_sink"` and `grep -rl "webhook"` under `.venv/lib/python3.13/site-packages/nautilus_trader/` → **0 files**. Positive control on the same tree: `grep -rln "ComponentStateChanged" …/nautilus_trader/common/` → 5 files (`messages.pxd/.pyx/.pyi`, `events.py`, `component.pyx`). The grep works; the sink is absent. Breezy's own `health.AlertSink`/`WebhookAlertSink` is the shipped answer — extend it, build no second one.
2. **Condition PUBLICATION: NATIVE-sufficient, already consumed.** `Component.degrade()` (`component.pyx:2098-2127`) → `_trigger_fsm` publishes `ComponentStateChanged` on `events.system.<id>` (`component.pyx:2210-2225`). Custom `QuoteTapeGap` records already reach the bus: `data.py:1749-1758` (`_publish_custom` → `CustomData`) → `engine.pyx:2845-2848` → topic from `data_topics.pyx:189-210` = `data.QuoteTapeGap.<venue>.<symbol>` (no metadata ⇒ instrument-scoped form). **The gap alert needs a subscriber, not a producer.** Nothing in `adapters/` may import `runtime` (layers contract, `pyproject.toml [tool.importlinter]`), and `breezy.runtime.health` is in `BANNED_EXEC_TRANSPORT_MODULES` (`tests/unit/test_execution_egress_firewall_guard.py:1749`) — the msgbus join is the only legal route and it leaves `data.py` byte-unchanged.
3. **Unit-failure delivery: NATIVE-sufficient (systemd `OnFailure=`) but CURRENTLY UNREACHABLE.** Measured 2026-09-12T15:16:32Z: `breezy-quote-tape-ingest` logged `instance edb87425…: ingested quote_tick=failed order_book_depths=failed custom_venue_settlement_snapshot=failed custom_depth_truncation=failed`, systemd logged `Finished`, and `systemctl --user show` reports `Result=success ExecMainStatus=0`. `OnFailure=` can never fire on a unit that exits 0. Cause is build-side and single-line: `ingest_instance` returns `outcome="converted"` unconditionally (`quote_tape_ingest_cli.py:803-805`) while its per-file sibling computes `any_failure` correctly (`:1101-1114`); `run()` gates `EXIT_CONVERSION_FAILED` on the instance outcome (`:1342-1344`).

**Constraints.** Nautilus Trader immutable — no patch/fork/bypass/reimplementation. `allow_short` stays `False`. Never weaken or delete a safety, settlement or contract test to go green. Never assign an operator-reserved value (max daily budget, max per position). Never touch live-trading enablement or the NO-SEND execution-egress firewall. PREREG v3 is BINDING — this plan changes no §3/§5/§9 meaning and is therefore not an amendment. Tests only via `scripts/ci/run_tests_no_egress.sh` (addopts already has `-q`); `lint-imports` + `mypy` after every slice.

**L-32 prior ruling.** `docs/evidence/GO_LIVE_BLOCKERS_2026-09-06.md:27` (GL-10) and `:84` — **"GL-10: deprioritised (operator). Alerts stay log-only for now."** This plan does not overturn that ruling; it re-presents it with evidence that did not exist on 09-06 (the 09-11 five-hour lockout, 2/9 unattended days, and the measured exit-0 ingest failure). **The destination decision remains the operator's (§8).**

## 1. Goal state (falsifiable)

Every CRITICAL the runtime already emits is delivered to a channel a human reads within 60 s, and the delivery is provable from the log alone.

**Falsifier:** with `BREEZY_ALERT_WEBHOOK_URL` set, `breezy-alert-test` exits 0 and the node log contains one `breezy alert delivered event=… sink=WebhookAlertSink` receipt; a forced `free_space_error`, a forced `QuoteTapeGap` OPEN, and a non-zero `breezy-quote-tape-ingest` exit each produce one delivered alert; and `grep -rE '<destination-host>' <every log and unit file>` returns nothing.

**Happy walk (hop = file:line).** `Component.degrade()` `component.pyx:2098-2127` → publish `component.pyx:2210-2225` → `_on_component_state` `component_health_watch.py:277-304` → `emit_alert` `health.py:514-535` → sink chosen at `resolve_alert_sink` `health.py:495-511` (gate `health.py:114`) → `WebhookAlertSink.emit` `health.py:475-477` → **NEW receipt line** in `emit_alert` → human.

**Failure walks.**

| # | Walk | Today (file:line) | After |
|---|---|---|---|
| F1 | Webhook unreachable / TLS / timeout | `emit_alert` `health.py:529-535` logs ERROR, swallows | unchanged (contract); **no** retry, **no** second sink |
| F2 | Env var unset | silent `LoggingAlertSink` `health.py:388-410` — this IS B4 | boot-time WARN naming the resolved sink class |
| F3 | Node/supervisor process dead | nothing emits | systemd `OnFailure=` template unit posts to the same destination |
| F4 | Quote-tape gap OPEN | `data.py:2044-2049` (shard) / `:2089-2093` (feed-wide) log ERROR only | msgbus subscriber → one alert per gap, rate-limited |
| F5 | Ingest conversion `=failed` | exits 0 (**measured**) → `OnFailure=` never fires | truthful exit 3 → `OnFailure=` fires |
| F6 | Intent OPEN >15 min in a quiet session | `install_stale_intent_alert` `component_health_watch.py:198-230` re-polls **only on an FSM transition** — `events.system.*` has no other publisher | loop-thread periodic poll |
| F7 | Disk free/tape-file thresholds | `quote_tape_disk_monitor.py:187-197` `logger.log` only | ERROR-class events reach the sink |

## 2. Spec / evidence vs code

| Piece | Code today (file:line) | Gap |
|---|---|---|
| Sink selection | `resolve_alert_sink` `health.py:495-511`; gate `health.py:114` | Var absent everywhere; `WebhookAlertSink` never constructed (audit §4) |
| Destination config | `deploy/systemd/breezy-trade-supervisor.service:84,89,100` (`EnvironmentFile=-`) ; `~/.config/breezy/breezy-trade.env` keys = `POLYMARKET_US_ACCOUNT_NUMBER`, `POLYMARKET_US_EXEC_STATE_DB`, `BREEZY_TRADE_TRADER_ID`, `BREEZY_TRADE_CATALOG_ROOT`, `BREEZY_USER_AGENT` | No alert key; recorder unit has only `polymarket.env` (`breezy-quote-tape.service:81`) |
| Env forwarding to the node | `spawn_node` forwards `env` AS-IS `trade_supervisor.py:567-587` | Works once the key is in the supervisor env — no code change |
| Delivery proof | none — `emit_alert` logs only on FAILURE `health.py:530` | No receipt ⇒ "delivered" is unobservable |
| Sink multiplicity | 5 constructing sites in the node process: `trade_cli.py:405,410`; `app/trade.py:322`; `current_rung_hold/composition.py:518`; `nws_actor.py:2086`. 2 in the supervisor: `trade_supervisor.py:733,1144` | `composition.py:246-252` documents this exact anti-pattern ("five `httpx.Client`s"); `_close_alert_sink` `composition.py:254-267` exists and would be bypassed |
| Rate limit / dedupe | `AlertState` `health.py:584-663`, `DEFAULT_RENOTIFY_AFTER_NS` `health.py:94` (24 h) | Already built. **Reuse; build no new limiter.** |
| Gap → sink | `_open_shard_gap` `data.py:2040-2061`, `_open_tape_gap` `data.py:2084-2094` | Log only; records already on the bus (L-1 #2) |
| Disk monitor → sink | `_log_event` `quote_tape_disk_monitor.py:187-197` (already transition-deduped at `:196`) | Log only |
| Ingest failure → exit code | `ingest_instance` `:803-805` vs `:1101-1114`; `run()` `:1342-1344`; `EXIT_CONVERSION_FAILED=3` `:245` | Measured exit 0 on a failing run |
| Stale-intent cadence | `component_health_watch.py:198-230` on `COMPONENT_STATE_TOPIC` `:95` | Only publisher of that topic is `Component._trigger_fsm` — **not a heartbeat** |
| Redaction test shape | `test_app_trade_main_permit_logging.py:59` `_SENSITIVE_VALUES`, `:115` bare `value not in caplog.text` | `"100"` matches inside an epoch-ns timestamp — the 09-12 gate's one failure |

## 3. Design

**Where.** All new code under `src/breezy/runtime/` (may import `health`; is not under `exec/`, so E0-TRANSPORT does not apply — that rule is scoped to `EXEC_PACKAGE_PATH_PREFIX = "src/breezy/adapters/polymarket_us/exec/"`, `test_execution_egress_firewall_guard.py:236`). One new module `quote_tape_gap_watch.py` mirroring `component_health_watch.py` exactly; one new CLI `alert_test_cli.py`; one new templated systemd unit.

**Inputs.** `BREEZY_ALERT_WEBHOOK_URL` (name only) from a NEW operator-owned `~/.config/breezy/alerts.env`, mode 0600, referenced with `EnvironmentFile=-` by `breezy-trade-supervisor.service`, `breezy-quote-tape.service`, `breezy-quote-tape-ingest.service` and the `OnFailure=` template. A separate single-purpose file (not `breezy-trade.env`) because three units with different credential postures need exactly this one value and nothing else.

**Outputs.** One receipt log line per delivered alert; one `ALERT_DELIVERY_TEST` payload from the CLI; `docs/evidence/alert_delivery_<date>.md` holding the captured receipt.

**NOT changed (byte-unchanged pins).** `src/breezy/adapters/polymarket_us/data.py` — prove with `git diff --stat` showing zero lines; loader contract stays green (`tests/unit/test_quote_tape_gap_loader.py`). `AlertPayload`'s four-field shape and `MAX_ALERT_DETAIL_CHARS=200` (`health.py:109,341-373`). `emit_alert`'s `except BaseException` contract (`health.py:529`). The 15 existing sink tests in `tests/unit/test_runtime_health.py:338,348,365,371,377,383,388,393,404,419,429,438,447,681,694` stay green unmodified. No persisted alert-dedupe state — forbidden by `health.py`'s module docstring (cold-start rule).

**Thread-affinity constraint (do not get this wrong).** `tests/contract/test_live_timer_thread_affinity.py` (measured against 1.231.0) pins that a `LiveClock` timer callback runs on a **Rust/tokio thread seen as `_DummyThread`**, with no running loop. `AlertState`'s docstring (`health.py:596-608`) binds the caller to the owning loop's thread. Therefore F6's periodic poll MUST hop back with `asyncio.run_coroutine_threadsafe(coro, loop)` — the primitive that contract file exists to pin — with the loop captured on the loop thread. A timer callback that mutates `alerted_intent_ids` directly is a data race and must be rejected in review.

## 4. Increments (RED first)

| id | size | RED test(s) — file :: name | Minimal change | Observable |
|---|---|---|---|---|
| **A1** | S | `tests/unit/test_runtime_health.py::test_resolve_alert_sink_logs_the_selected_sink_class`; `::test_resolve_alert_sink_never_logs_the_webhook_url` | `resolve_alert_sink` `health.py:495-511` logs one INFO with the class name only | boot log says which sink is live; F2 closed |
| **A2** | S | `tests/unit/test_runtime_health.py::test_emit_alert_logs_a_delivery_receipt_naming_the_sink_class`; `::test_emit_alert_logs_no_receipt_when_the_sink_raises`; `::test_emit_alert_receipt_never_contains_the_webhook_url` | `emit_alert` `health.py:527-535`: one `logger.info("breezy alert delivered event=%s site=%s severity=%s sink=%s", …, type(sink).__name__)` after a successful `emit` | the receipt line — the artefact B4's unlock observable needs |
| **A3** | S | `tests/unit/test_runtime_redaction_matcher.py::test_matcher_flags_a_planted_secret`; `::test_matcher_does_not_flag_a_value_inside_an_epoch_ns_timestamp`; then re-point `test_app_trade_main_permit_logging.py:115` at it | New `tests/unit/redaction.py::assert_value_absent(text, value)` using `rf"(?<![0-9A-Za-z_.\-]){re.escape(value)}(?![0-9A-Za-z_.\-])"`; URLs/tokens ALSO get a plain-substring assertion (maximally sensitive, cannot collide with a timestamp) | the 09-12 gate's one failure goes away; no URL or cap value can pass unnoticed |
| **A4** | S | `tests/unit/test_alert_test_cli.py::test_emits_one_info_alert_through_the_resolved_sink`; `::test_exit_2_when_require_webhook_and_sink_is_logging`; `::test_never_prints_the_url` | New `src/breezy/runtime/alert_test_cli.py` (injected client, never posts under test); `[project.scripts] breezy-alert-test` | one end-to-end delivered alert, on demand |
| **A5** | M | `tests/unit/test_runtime_alert_sink_single_instance.py::test_trade_cli_resolves_exactly_one_sink_for_both_watches`; `::test_the_resolved_sink_is_closed_on_teardown` | `trade_cli.py:405,410` resolve ONE sink, inject into both installs; pass it to `app/trade.py:322`'s refusal path; close via `composition._close_alert_sink` `:254` | 5 `httpx.Client`s → 1; the documented anti-pattern (`composition.py:246-252`) stops being live |
| **A6** | M | `tests/unit/test_quote_tape_gap_watch.py::test_one_gap_open_fanned_out_across_instruments_emits_exactly_one_alert`; `::test_a_second_gap_seq_within_the_floor_is_suppressed_and_counted`; `::test_a_resolved_record_never_alerts_critical`; `::test_a_failing_sink_never_unwinds_into_the_publisher` | New `src/breezy/runtime/quote_tape_gap_watch.py`: `msgbus.subscribe(topic="data.QuoteTapeGap.*", …)`; dedupe key `AlertConditionKey("quote_tape_gap", "global", f"{recorder_instance_id}:{gap_seq}")` through `AlertState`; plus a floor of one alert per 300 s across seqs carrying `suppressed=<n>`; wired in `quote_tape_cli.run` and `trade_cli` after `node.build()` | F4 closed; `data.py` byte-unchanged |
| **A7** | S | `tests/unit/test_quote_tape_disk_monitor.py::test_error_class_event_reaches_the_injected_sink`; `::test_warning_class_event_stays_log_only`; `::test_recovery_never_alerts` | `QuoteTapeDiskMonitor.__init__` takes `alert_sink: AlertSink | None = None`; `_log_event` `:187-197` calls `emit_alert` for the three ERROR events only, reusing the `:196` transition dedupe; wire at `quote_tape_cli.py:274-276` | F7 closed; every existing monitor test stays green (default `None` = today) |
| **A8** | M | `tests/unit/test_quote_tape_ingest_cli.py::test_instance_with_a_failed_type_reports_outcome_failed`; `::test_run_returns_exit_conversion_failed_when_any_type_failed` | `ingest_instance` `:803-805` derives its outcome via the existing `_outcome_has_failure` `:826-833` over `type_results`, matching `:1101-1114` | `systemctl --user show … -p ExecMainStatus` becomes 3 on a failing pass — the precondition for F5 |
| **A9** | M | `tests/unit/test_alert_on_failure_deploy.py::test_template_unit_contains_no_literal_url`; `::test_template_unit_never_passes_the_url_as_a_bare_argv_token`; `::test_named_units_declare_onfailure` (precedent: `test_score_live_trials_deploy.py`) | New `deploy/systemd/breezy-alert@.service` (oneshot, `EnvironmentFile=-%h/.config/breezy/alerts.env`, `curl -sS --config -` reading `url="…"` on stdin so the URL never enters any argv); `OnFailure=breezy-alert@%n.service` on the supervisor, recorder and ingest units | F3 + F5 closed with **zero Breezy code** — native systemd is sufficient here |
| **A10** | M | `tests/unit/test_component_health_watch_stale_intent_alert.py::test_a_quiet_session_with_no_component_transition_still_polls`; `::test_the_poll_body_never_runs_off_the_owning_loop_thread` | `install_stale_intent_alert` gains `clock` + `loop` + `interval_ns=60s`; the timer callback does nothing but `asyncio.run_coroutine_threadsafe` the existing `_on_component_state` body onto the captured loop; msgbus subscription retained | F6 closed; the 09-11 five-hour blind spot cannot recur |

**Verification after EVERY increment:** `scripts/ci/run_tests_no_egress.sh tests/unit/test_runtime_health.py tests/unit/test_component_health_watch_stale_intent_alert.py tests/unit/test_quote_tape_disk_monitor.py tests/unit/test_quote_tape_ingest_cli.py` → then full `scripts/ci/run_tests_no_egress.sh`; then `lint-imports` and `mypy src/breezy`. Deploy-file increments additionally: `systemd-analyze verify deploy/systemd/breezy-alert@.service` (read-only; **no** `daemon-reload`, **no** unit start, **no** signal to any running process).

## 5. Acceptance — evidence the executing session must show

1. RED→GREEN transcript for each of A1–A10 (the RED output, not a claim of it).
2. `git diff --stat src/breezy/adapters/polymarket_us/data.py` → empty.
3. Full gate output; `lint-imports` and `mypy` clean.
4. **One delivered test alert**: `breezy-alert-test --require-webhook` exit 0 **and** the captured receipt line `breezy alert delivered event=ALERT_DELIVERY_TEST site=global severity=INFO sink=WebhookAlertSink`, pasted into `docs/evidence/alert_delivery_<date>.md`, with the destination host redacted.
5. **One delivered real alert**: a forced `free_space_error` (inject a `disk_usage_probe` returning `free=0`) produces a receipt.
6. Grep proof of no leak: the destination host string appears in **zero** files under `docs/`, `deploy/`, `src/`, `tests/` and in zero captured log lines.
7. `systemctl --user show breezy-quote-tape-ingest.service -p ExecMainStatus` reports 3 on the next failing pass (read-only observation; do not trigger a run by hand).

## 6. Non-goals (scope guard)

Paging/escalation policy, on-call rotation, acknowledgement flows. Changing any existing alert's severity, event name or site. Touching permit, intent, latch, ledger, or submit-chain logic. Adding new alert CONDITIONS beyond the three named paths (gap OPEN, disk ERROR, ingest failure). Email/SMTP (no MTA on the host — `sendmail`, `msmtp`, `mail`, `ssmtp`, `postfix` all absent; measured). A self-hosted destination. A dead-man / heartbeat monitor for the sink itself (F1's residual — named, deliberately deferred). Persisting alert dedupe state. Fixing the ingest non-disjoint-interval backlog itself (A8 makes it VISIBLE; repairing the catalog is a separate item). Re-litigating GL-10's operator call.

## 7. Risks, blast radius, rollback

**Blast radius (codegraph, HEAD).** `emit_alert` 18 callers (`runtime/__init__.py`, `health.py`, `ingest/nws_actor.py`, `strategy/weather_common/refusals.py`, +3); `resolve_alert_sink` 19; `WebhookAlertSink` 13; `LoggingAlertSink` 5; `AlertSink` 6 — **and `AlertSink` has no covering test**, so A5's injection work must add one.

| Risk | Mitigation |
|---|---|
| A2's receipt doubles `LoggingAlertSink` output (log line + receipt) | Accepted and stated; the receipt is the B4 unlock observable. Cap: receipt is ONE line, four static fields, no `detail` |
| Enabling the webhook opens 5 `httpx.Client`s in the node (`composition.py:246-252`) | A5 lands **before** the operator sets the var; sequence A1→A5 first |
| A8 makes the ingest unit RED 4×/day until the catalog backlog is repaired | Ingest alerts are **WARN**, never CRITICAL, so they cannot bury a trading CRITICAL. The noise is the true state of a pipeline that has failed every run for days |
| A6 alert storm on a reconnect flap | Two-layer: `AlertState` dedupe by `(recorder_instance_id, gap_seq)` **plus** a 300 s floor across seqs with `suppressed=<n>` |
| A10 data race on `alerted_intent_ids` | Hard design pin (§3) + `::test_the_poll_body_never_runs_off_the_owning_loop_thread`; reject any timer callback that mutates directly |
| URL leaking into a unit cmdline via `ps`/`systemctl status` | `curl --config -` (A9) + two deploy tests asserting no literal URL and no bare argv token |
| Webhook adds outbound egress from the node | Pre-existing, designed-for: `health.py` is already in `BANNED_EXEC_TRANSPORT_MODULES` precisely because it owns `httpx`. The NO-SEND firewall governs the EXECUTION path and is untouched |

**Rollback.** Remove the one line from `~/.config/breezy/alerts.env`. Every path returns to `LoggingAlertSink` — behaviour identical to today except two extra log lines. No schema, no store, no PREREG surface is touched, so rollback needs no data migration.

## 8. Rulings / operator items

**OP-1 (the only operator item): choose the destination.** Build side wires whatever is chosen; the operator writes one line into `~/.config/breezy/alerts.env`. **Until this is chosen, B4 stays OPEN and unattended operation is not responsible** — A1–A10 all land and every CRITICAL still resolves to `LoggingAlertSink`, i.e. still reaches nobody. GL-10 was deprioritised on 09-06 (`GO_LIVE_BLOCKERS_2026-09-06.md:84`); the new evidence is the 09-11 five-hour lockout and 2/9 unattended days.

| Destination | New account | Build change | Latency | Secret handling |
|---|---|---|---|---|
| **ntfy.sh topic URL** (recommended) | No | **None** — `WebhookAlertSink` posts bare JSON with no auth header, which ntfy renders as the message body | seconds (phone/desktop push) | The topic URL **is** the capability (read AND publish): high-entropy topic, 0600 env file, treated as a secret throughout |
| ntfy.sh with an access token | No | Yes — `WebhookAlertSink` sends no custom headers today | seconds | Token + header support = a new increment |
| Slack / Discord incoming webhook | Only if the operator has no workspace/server | Yes — both require a specific body shape (`{"text":…}` / `{"content":…}`), so a body adapter is needed | seconds | URL is a bearer secret (UNVERIFIED against a live endpoint) |
| Email relay | Yes (no MTA on host — measured) | Yes — new transport + credential | minutes | **Refused by this plan** (§6) |
| systemd `OnFailure=` → local journal only | No | No | n/a | Reaches no human off-host; insufficient alone |
| `notify-send` (`/usr/bin/notify-send` present) | No | Small | instant | Only reaches a human physically at the host — useless unattended |

**Build-side calls made here, stated not asked (Pre-Auth §8):** a NEW single-purpose `~/.config/breezy/alerts.env` rather than overloading `breezy-trade.env`; ingest failures at **WARN**, trading conditions at **CRITICAL**; A8's exit-code fix lands **before** the backlog repair; no dead-man monitor in this plan. **Not a PREREG amendment** — no §3/§5/§9 meaning changes.

## 9. Citations — verified against the working tree today (2026-09-12, HEAD e4848c3)

VERIFIED by direct read: `health.py:94,109,114,341-373,376-410,413-511,514-535,584-663`; `component_health_watch.py:95-140,142-230,233-307`; `quote_tape_disk_monitor.py:51-201`; `data.py:2040-2061,2084-2094,2113-2156,1749-1758`; `quote_tape_ingest_cli.py:239-245,728-762,766-805,1101-1114,1305-1350`; `quote_tape_cli.py:216-290`; `trade_cli.py:398-420`; `app/trade.py:64-76,322-327`; `trade_supervisor.py:44,567-587,598-622,721-737,1041-1067,1144`; `composition.py:240-300`; `current_rung_hold/composition.py:518`; `nws_actor.py:2086`; `test_execution_egress_firewall_guard.py:133,232-236,1735-1751,2019-2034`; `test_app_trade_main_permit_logging.py:59,115`; `test_runtime_health.py` (15 sink test names); `test_live_timer_thread_affinity.py` docstring; `pyproject.toml [tool.importlinter]` + `[project.scripts]`; `deploy/systemd/breezy-trade-supervisor.service:84,89,100,107-112,120-129`, `breezy-quote-tape.service:81,86,92`, `breezy-quote-tape-ingest.service` (whole file), `breezy-quote-tape-ingest.timer`.
INSTALLED Nautilus: `component.pyx:419-428,839,2098-2130,2200-2225`; `data/engine.pyx:2541,2571,2845-2848`; `common/data_topics.pyx:189-210`.
MEASURED today (read-only): `journalctl --user -u breezy-quote-tape-ingest` 15:15:30Z–15:16:32Z; `systemctl --user show breezy-quote-tape-ingest.service` → `Result=success ExecMainStatus=0 InactiveEnterTimestamp=15:16:32Z`; `~/.config/breezy/` listing + key NAMES only (no values read, printed or stored); absence of `sendmail|msmtp|mail|mutt|ssmtp|postfix`, presence of `/usr/bin/curl` and `/usr/bin/notify-send`.

**UNVERIFIED — the executing session must close these.**
1. The exact mechanism by which the 15:16Z run's per-type `failed` reached `summary_line`'s `"ingested"` prefix (`:759-763`) — `ingest_instance:803-805` is the identified cause, but a second path through `:1101-1114` was not excluded by execution. A8's first RED test must reproduce exit 0 from a per-type failure before fixing it.
2. `data.QuoteTapeGap.<venue>.<symbol>` was derived from `data_topics.pyx:189-210` (no-metadata branch), not observed on a live bus. A6 must assert the topic against a real `CustomData(DataType(QuoteTapeGap), …)` round-trip rather than hardcoding the string from this plan.
3. That `events.system.*` has **no** publisher other than `Component._trigger_fsm` — established from installed source, not from a quiet-session journal. A10's value does not depend on it (a 60 s poll is correct either way), but the claim should not be repeated as measured.
4. Slack/Discord body-shape requirements (§8 row 3) are external knowledge, not probed — the NO-SEND posture forbids probing them from here.
5. Whether all five node-process `resolve_alert_sink()` sites execute in a single v3 boot (grep-verified as call sites; not traced through one live boot).
