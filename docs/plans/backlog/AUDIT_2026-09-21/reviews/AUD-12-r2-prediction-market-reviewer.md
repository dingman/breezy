# AUD-12 — Round 2 — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-12-cost-model-slippage-and-fee-drift.md
SHA256: 54953aa7636d9679d8cb77081c5b355b22689fc6d877ee53b90f0fe651510f86
Round: 2
Reviewer: prediction-market-reviewer (independent, blind)
Lens: fee formula, slippage reference price for IOC takes, fail-closed
fee-drift handling without editing the pin, and whether alert delivery
actually reaches someone.

## §13 review-history reconciliation

- R1 prediction-market-reviewer MATERIAL #1 (WP-B0 framed as unresolved
  future dependency) — claimed corrected throughout §2/§4/§6 item 3/§10/§12.
  VERIFIED this round: `git show --stat f97c26f` confirms the commit landed
  2026-09-20T14:08:33Z with exactly the content the plan now describes
  (`resolve_alert_sink`, `WebhookAlertSink`, `TeeAlertSink`, loopback-TLS
  proof, boot-time `log_alert_egress_status`). The plan's framing is now
  accurate — CONFIRMED FIXED.
- R1 prediction-market-reviewer MATERIAL #2 (no acceptance criterion verifies
  live alert-sink configuration) — claimed resolved via new §7 step 5 / §8
  closing bullet. See below: the new criterion is added, but it is not fully
  self-consistent (new MINOR-leaning-MATERIAL finding, see Defects).
- R1 prediction-market-reviewer MINOR #1 (unauthenticated `gateway_base_url`
  path not named) — claimed corrected in §6 item 3/§7 step 3 (fourth
  fixture)/§8/§9. VERIFIED this round by direct read of
  `docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/client.py:79-133`:
  `get()` defaults `authenticated=False`; `_request` routes
  `authenticated=False` to `self.gateway_base_url` with no auth headers, and
  `authenticated=True` requires `key_id`/`secret_key` and routes to
  `self.api_base_url`. The plan's description matches exactly — CONFIRMED FIXED.
- R1 prediction-market-reviewer MINOR #2 (`level0_ask == vwap_ask_at_intended_size`
  equivalence left implicit) — now stated explicitly in §2/§6 item 1.
  VERIFIED present — CONFIRMED FIXED.

## Claims verified this round (fresh read of the whole revised plan)

- WP-B0 commit `f97c26f` — CONFIRMED via `git show --stat`, matches plan's
  §2 bullet exactly, including the commit message's own "3 days... 11
  hours... neither delivered" framing the plan quotes.
- `breezy-check-alerts` entrypoint — CONFIRMED to exist:
  `pyproject.toml:302` registers `breezy-check-alerts = "breezy.runtime.check_alerts_cli:main"`,
  and `src/breezy/runtime/check_alerts_cli.py` implements exactly the exit
  contract the plan describes (0=delivered, 2=not-configured, 3=configured-
  but-not-delivered) and is genuinely value-free: on failure it prints only
  the exception's *type name*, explicitly withholding the message "because it
  can embed the webhook URL" (lines 142-149), and on success it prints only
  event/severity/detail (static, non-secret fields) — never the URL or host.
  This matches the plan's "never prints the webhook URL" claim precisely.
- `DOCUMENTED_TAKER_FEE_COEFFICIENT` exact-equality refusal — CONFIRMED at
  `decision.py:331` (`if inputs.fee_coefficient != inputs.config.required_fee_coefficient: return Refuse("fee_schedule_mismatch")`),
  matching the plan's "mirroring `decision.py:331`'s existing check" claim.
- `feeCoefficient` sourced from the market payload (`parsing.py:639-645`,
  `market.get("feeCoefficient")`) — consistent with the plan's assumption
  (§12) that the venue exposes this on a plain, unauthenticated market-listing
  read; the plan correctly hedges this as an assumption/conditional blocker
  rather than asserting it as proven, which is the right posture given this
  session did not capture a live wire response for the specific fee-drift
  probe endpoint.

## Defects

**MATERIAL** — the new round-2 closing criterion (§7 step 5, §8 last
bullet) offers two alternative pieces of evidence as if interchangeable —
"`breezy-check-alerts` (the existing WP-B0 CLI) against the live node's
actual environment, **or** inspect the boot log for the
`log_alert_egress_status` line" — but they do not prove the same thing.
Read directly from `src/breezy/runtime/health.py:629-665`:
`log_alert_egress_status` calls only `alert_egress_configured(env)` (itself
just `bool(env.get(ALERT_WEBHOOK_URL_ENV_VAR))`) and logs one INFO or WARNING
line; it never constructs a sink and never calls `.emit()`. It can prove
**configuration** (the env var is non-empty at boot) — a fact the
coordinator has already independently established via a read-only
`grep -c` on the env file — but it structurally cannot prove **delivery**
(a real POST reaching the endpoint and receiving 2xx), and it has no exit
code to report at all. `breezy-check-alerts`, by contrast, genuinely sends
one alert and returns exit 0/2/3 based on the real outcome. §8's bullet asks
for "a resolved `TeeAlertSink` **and** exit code 0 (delivered)" from either
source — but the boot-log alternative cannot supply an exit code or prove
delivery, only configuration. As written, an implementer who takes the "or"
literally could close (b) on the boot-log line alone, which would prove only
what the coordinator's env-file grep already proved this session, and would
NOT exercise the one failure mode this item exists to catch — "configured
but not delivered" (`check_alerts_cli.py`'s own `EXIT_DELIVERY_FAILED = 3`
case, e.g. a wrong host, a firewalled egress path, or a receiver that 4xxs).
That is precisely the gap the plan's own §8 prose names as the point of this
criterion ("a passing unit-test suite against a stub sink cannot... prove the
live node's alert actually reaches anyone") — the same reasoning applies to
the boot-log alternative, which is even weaker evidence than a stub-sink unit
test (it doesn't even attempt a send). **Required change:** make
`breezy-check-alerts` returning exit 0, run against the live node's actual
resolved environment, the SOLE sufficient evidence for closing (b) as
"delivered." Demote the boot-log `log_alert_egress_status` line to
supporting evidence for "configured" only (already substantially established
by the coordinator's env-file fact in §12) — explicitly state it does not
and cannot prove delivery, since it never calls `sink.emit`.

**MINOR** — §2/§6 item 3 cite the vendored SDK snapshot as
`docs_snapshots/.../client.py:84-133`. The actual path is
`docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/client.py`
(confirmed via `find`); "docs_snapshots" does not exist as a directory name
anywhere in the repo. The line range itself is accurate (84 = `get()`'s
`authenticated` param, 133 = the `headers.update(auth_headers)` line inside
the `authenticated` branch), so this is a citation-path typo, not a
substantive error, but should be corrected so a future reader can actually
follow the citation.

## Per-criterion points (caps: 20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 18/20 — both G-09 sub-claims are
  addressed and the WP-B0 landing correction is accurate; the closing
  criterion for (b) still allows a weaker-than-intended path to "done."
- Technical correctness and evidence grounding: 17/20 — every mechanism
  claim checked this round (commit, CLI, fee-equality check, unauthenticated
  path) matched source exactly; the boot-log-proves-delivery framing does
  not, and is a technical misreading of `log_alert_egress_status`'s actual
  behaviour.
- Implementation specificity and feasibility: 13/15 — concrete throughout;
  the "or" ambiguity in the closing check is the only feasibility gap.
- Acceptance criteria and validation quality: 16/20 — this is where the
  defect bites hardest: the criterion meant to be this item's actual closing
  gate is satisfiable by evidence that does not establish what it claims to
  establish.
- Autonomous operation, failure handling, recovery: 13/15 — the three-valued
  AGREE/DISAGREE/UNKNOWN probe design and unauthenticated-path requirement
  remain strong; the delivery-verification ambiguity slightly undercuts the
  "alert actually reaches someone" guarantee this item exists to provide.
- Portfolio alignment, scope, dependencies: 10/10 — dependency framing is now
  accurate (verification-gated, not landing-blocked); no duplication of A0;
  no invented ROI number.

**Total: 87/100.**

## Required changes to reach 100

- Make `breezy-check-alerts` exit 0 (run against the live node's actual
  environment) the sole sufficient evidence for closing (b) as "delivered";
  restate the boot-log alternative as supporting evidence for "configured"
  only, explicitly noting it cannot prove delivery.
- Fix the citation path from `docs_snapshots/.../client.py` to
  `docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/client.py`.

## Blockers

None new. Whether the live node's process actually resolves `TeeAlertSink`
and delivers is still an open verification fact (as the plan's own §12
states), not resolvable by this reviewer (no secrets/process access) — this
is correctly named as the plan's own residual, conditional blocker, not one
this review is introducing.
