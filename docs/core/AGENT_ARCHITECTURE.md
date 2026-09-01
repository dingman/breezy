# Breezy — Agent & Skill Architecture (FINAL)

Status: peer-reviewed (architect + security-reviewer, both APPROVE-WITH-CHANGES; all findings incorporated).
Evidence base: 4 parallel recon agents, source-verified. Scope: BUILD/INTEGRATE/TEST/MONITOR/MAINTAIN the bot.
Hard boundary: no component here trades, selects positions, sizes bets, computes edge, or makes execution decisions.

## Governing result

Null hypothesis held against ~15 candidates. **2 sub-agents + 3 skills survive.** Everything else is ordinary
code, a native Nautilus capability, or an existing roster component (73 agents / ~140 skills already available).

The two decisive evidence findings that shaped everything:
1. Nautilus's bundled `adapters/polymarket/` is hardcoded to the Polymarket.COM crypto CLOB (py_clob_client_v2,
   POLYGON, wallet private key, ERC-1155 token_id). It CANNOT serve Polymarket.us. New adapter required.
2. Nothing in the entire 73-agent/~140-skill roster mentions Nautilus Trader.

---

## SURVIVING COMPONENTS

### 1. `nautilus-adapter-builder` — sub-agent, project-scoped (`.claude/agents/`)

1. **Type**: sub-agent. Deliberately THIN — a router + tool-scope, not a claimed super-capability.
2. **Responsibility**: implement Breezy's Nautilus extensions — the Polymarket.us adapter (data/exec client,
   InstrumentProvider, factories, config, credentials module), weather `@customdataclass` types, catalog wiring,
   backtest config, reconnection/watchdog, and reconciliation report methods.
   **Boundaries**: never reviews its own work (tdd-guide/python-reviewer/security-reviewer/prediction-market-reviewer
   run as independent stages); never holds or reads real credentials (fixtures/mocks only); no live network access to
   api.polymarket.us or gateway.polymarket.us; never modifies/patches/forks Nautilus; no trading logic.
   **Dispatched via SEAM-SCOPED briefs, not one catch-all** (rev. H1): (a) transport+auth, (b) weather custom-data +
   catalog + backtest, (c) reconciliation reports, (d) NWS ingestion. Seams (b)+(d) are venue-independent and run first.
3. **Why not existing**: honest answer is ROUTING + TOOL-SCOPING, not capability (rev. M2 — the earlier
   "framework-constraint memory" claim was self-refuting; sub-agents are stateless per dispatch and constraints
   arrive via skill #3 regardless). `tdd-guide` drives RED→GREEN but carries no Nautilus constraint;
   `gan-generator` builds to spec but has no immutability guardrail; `ecc/python-patterns` is generic Python.
   The value is a definition that *always* loads skills #3/#4/#5 and is *denied* live-credential tools.
4. **Evidence**: bundled adapter unusable (§D) ⇒ genuinely new adapter work; Nautilus provides NO reconnection,
   NO re-subscription, NO heartbeat (§C) ⇒ real hand-authored surface; reconciliation orchestration IS free but
   requires generate_order_status_report(s)/generate_fill_reports/generate_position_status_reports (§C).
5. **In/out/tools**: In — skills #3/#4/#5, adapters/_template/, bundled adapter as structural reference.
   Out — Python under src/breezy/ + tests. Tools: Read/Write/Edit/Bash/Grep/Glob. Deps: nautilus_trader, pyiem,
   polymarket_us SDK.
6. **Failure modes/safeguards**: silent Nautilus behavior drift ⇒ **pin `~=1.231` + contract tests asserting each
   documented gotcha** (rev. H2 — cheapest durability control in the design); scope creep into trading ⇒
   prediction-market-reviewer gate; self-approval ⇒ prohibited, independent review mandatory.
7. **Verdict**: REQUIRED NOW (seams b/d are unblocked today).
8. **Absorbs**: reconnection/watchdog, reconciliation reports, provenance write-path, config/credentials module,
   custom-data types, catalog + backtest wiring — as CODE it authors, not as separate agents.

### 2. `polymarket-us-discovery` — sub-agent, project-scoped

1. **Type**: sub-agent. Isolated credential blast radius.
2. **Responsibility**: empirically resolve what the venue's docs cannot answer — per-market
   `orderPriceMinTickSize`/`minimumTradeQty`, weather slug grammar, WS subscribe/auth/heartbeat schemas, live rule
   text (`description`/`rulesDisclaimer`), error-code disambiguation.
   **Boundaries — ENFORCED, not prose** (rev. security C1/C2/H1, architect C2): read-only endpoint/method allowlist by
   default; NO order submission without a named per-dispatch operator exception with a capital ceiling; official SDK
   only, no raw curl/Bash HTTP; Write restricted to skill #4's append path; findings log carries extracted schema
   facts ONLY — never secret_key, signatures, raw headers, or full response bodies (`key_id` UUID is the sole
   credential-adjacent value permissible).
3. **Why not existing**: no roster agent probes a live credentialed venue; `docs-lookup` is Context7-only. Not
   ordinary code because the loop is genuinely iterative and judgment-laden — resolving *contradictions* between
   documented claims requires deciding what to probe next.
4. **Evidence**: docs self-contradict on decimal vs whole contracts; `intent × outcomeSide × action` have no
   documented precedence matrix; gateway.polymarket.us returns 403 to non-browser fetches; the Exchange Rulebook has
   no public URL; NO retail sandbox exists (preprod is institutional-only) (§E).
5. **In/out/tools**: In — credentials via env (never in files). Out — provisional findings appended to skill #4.
   Tools: polymarket_us SDK; Write scoped to skill #4.
6. **Failure modes/safeguards**: accidental real-money order ⇒ allowlist + minimum size + deliberately unmarketable
   prices + operator-set capital ceiling; single-market generalization ⇒ every finding is `provisional` until
   reproduced on ≥2 markets and signed off (rev. H4); credential leak into git ⇒ pre-commit guard for
   `X-PM-Signature`/`X-PM-Access-Key` patterns and base64-Ed25519-length blobs; runaway probing ⇒ backoff +
   circuit breaker (20 req/s, 429s, 5s stopgap).
7. **Verdict**: REQUIRED — but **PARALLEL TRACK, NOT CRITICAL PATH** (rev. C1). ~~Gated on KYC + operator budget.~~ **Venue access was RELEASED by the operator 2026-09-01 — no longer gated.**
8. **Absorbs**: API/schema discovery, auth verification, rule-text capture, venue error taxonomy.

### 3. `nautilus-trader-patterns` — skill, PROJECT-SCOPED (`.claude/skills/`)

1. **Type**: skill (reference knowledge; no execution).
2. **Responsibility**: the stable Nautilus extension-point map — adapter base classes and required vs optional
   coroutines, factory/TradingNode wiring, `@customdataclass`, ParquetDataCatalog, BacktestDataConfig, test_kit,
   env-var credential convention, and the reconnect/watchdog recipe (mirroring the bundled adapter's 60s MARKET /
   300s USER idle-timeout pattern). **Boundaries**: no venue facts, no weather domain.
   Carries a "verified against nautilus-trader 1.231.x" banner; version-volatile gotchas are backed by contract tests (rev. M3).
3. **Why not existing**: zero Nautilus coverage anywhere in the roster. Not code — it is knowledge that prevents
   reinvention of things Nautilus already provides, which is the project's stated prime directive.
4. **Evidence**: §C. Highest-leverage artifact in the design: it is what stops an implementer rebuilding the
   catalog, the serialization layer, or reconciliation orchestration.
5. **In/out**: In — installed source. Out — loaded into any Nautilus-building agent. PROJECT-SCOPED by operator
   decision: Breezy is the only Nautilus consumer, so this knowledge stays out of the global roster.
6. **Failure modes**: staleness on version bump ⇒ backed by the project's contract tests, so drift goes RED.
7. **Verdict**: REQUIRED NOW — build first, it is fully unblocked.
8. **Absorbs**: extension-point reference, persistence/backtest patterns, reliability recipe, config/secrets convention.

### 4. `polymarket-us-integration` — skill, project-scoped

1. **Type**: skill.
2. **Responsibility**: SOLE OWNER of venue-authored facts (rev. M1) — the two API stacks, Ed25519 canonical-string
   signing (`timestamp+METHOD+path`, 30s window) and Auth0 JWT (180s tokens), Series→Events→Markets + slug identity,
   order-field enums, per-market tick/min size, the fee formula, settlement timing (08:00 ET / 11:00 ET conflict
   branch / 7-day fallback), the 5-city station mapping, rate limits and error-code disambiguation, clock-skew
   monitoring. Carries the discovery log with provisional flags.
   **Boundaries**: no NWS mechanics (#5 owns those); no Nautilus mechanics (#3).
3. **Why not existing**: nothing covers this venue; too volatile and too Breezy-specific for the global roster.
4. **Evidence**: §E. Every fact is source-verified and every gap explicitly marked.
5. **Failure modes**: venue changes under us ⇒ >90-day staleness triggers a #2 re-dispatch with a named owner
   (rev. L2); provisional facts promoted too early ⇒ ≥2-market reproduction rule.
6. **Verdict**: REQUIRED — seeded now from verified docs, enriched by #2 later.
7. **Absorbs**: auth/signing reference, market structure, fees, settlement timing, station mapping, ops/error taxonomy.

### 5. `nws-cli-settlement` — skill, project-scoped

1. **Type**: skill.
2. **Responsibility**: the one genuinely novel domain trap — deciding which NWS record is **settlement-grade**.
   Covers: intraday-preliminary vs final CLI (key on the summary date parsed from the headline, NEVER `issuanceTime`);
   correction/revision detection (regex `CCA|CCB|CORRECTED|CORRECTION` over raw text, because api.weather.gov does NOT
   expose the WMO BBB field); dedupe on `(productCode, location, summary_date, hash)` since each re-issue gets a new
   UUID; monotonic `revision_seq` and supersession of already-settled data; **climate day = local STANDARD time**,
   never UTC, never DST-adjusted (rev. M4); mandatory non-generic `User-Agent` or 403 (rev. M4); the four identifier
   spaces (ICAO `KNYC` / CLI location `NYC` / WFO `KOKX` / lat-lon); pyIEM usage; **ACIS as a named independent
   reconciliation input** (rev. L3); required provenance fields.
   **Boundaries**: does NOT re-implement parsing (pyIEM owns that); does NOT own venue settlement timing (#4);
   never forward-infers resolution ahead of the venue.
3. **Why not existing**: pyIEM *parses* CLI text but does not decide what is settlement-grade — that judgment is
   entirely Breezy's and is where a silent, money-losing correctness bug lives.
4. **Evidence**: §F — two CLI issuances/day; corrections real but 0-in-200 sampled (invisible in testing, decisive
   in production); ACIS independently reproduced CLI values exactly.
5. **Failure modes**: settling on a preliminary report ⇒ contract tests over recorded real products, incl. a
   captured `CCA` correction; parser trusting malformed remote text ⇒ sanity-bounds validation before settlement use.
6. **Verdict**: REQUIRED NOW — fully unblocked, zero venue dependency.
7. **Absorbs**: provenance field set, station/identifier mapping, revision detection, reconciliation-source guidance.

---

## MINIMAL ARCHITECTURE & BUILD ORDER (re-sequenced per rev. C1)

**Stage 0 (unblocked, starts today)** — `nautilus-trader-patterns` (#3) → `nws-cli-settlement` (#5)
**Stage 1 (unblocked)** — #1 seams (b)+(d): weather custom-data types, catalog, backtest replay, NWS ingestion,
  provenance/revision write path, contract tests pinning Nautilus gotchas
**Stage 2 (PARALLEL; venue access released 2026-09-01, no longer gated)** — `polymarket-us-discovery` (#2) → enriches
  `polymarket-us-integration` (#4)
**Stage 3 (venue-dependent)** — #1 seams (a)+(c): adapter transport/auth, reconnection/watchdog, reconciliation reports
**Continuous** — tdd-guide (RED→GREEN), python-reviewer, security-reviewer, prediction-market-reviewer, doc-updater

Critical property: **if credentials slip for weeks, Stages 0–1 still deliver the majority of the system.**

## REJECTED CANDIDATES

| Candidate | Absorbed by / why rejected |
|---|---|
| NWS ingestion agent | Ordinary code + pyIEM; scheduled job. Judgment lives in skill #5. |
| CLI/F6 parser agent or skill | pyIEM solves it to production grade. Do not hand-roll. |
| Market→station mapping agent | Published 5-row table (NYC/KNYC/CLINYC … Chicago/**KMDW**/CLIMDW). Config + test. |
| Settlement-rule capture agent | Rules fully specified by venue; deterministic branch, not judgment. |
| Provenance/persistence agent | `@customdataclass` + ParquetDataCatalog native; revision/supersession path is a #1 code requirement. |
| Reconciliation agent | Nautilus orchestrates natively; adapter only implements 4 report methods. |
| Observability/monitoring agent | Agents are build-time. Runtime = code + runbook; operability criteria now live in #3/#4 + #1's acceptance criteria. |
| Data-normalization agent | `@customdataclass` + Pydantic-style validation. Code. |
| Config/env-schema agent | Nautilus config classes + `get_env_key()` convention. Code. |
| Security agent | `security-reviewer` exists and is well-covered. |
| Backtest/simulation agent | Native `BacktestDataConfig(data_cls=...)` replay confirmed. |
| Generic `python-specialist` doer | `tdd-guide` + `gan-generator` + `ecc/python-patterns` cover it; #1 is the narrow Nautilus-scoped router. |
| Kalshi adapter agent/skill | No Kalshi work now (YAGNI). Only forward-compat concession: a `sign(bytes)->bytes` seam with **venue-specific canonical-string builders kept separate** (Ed25519 vs RSA-PSS have different failure surfaces). |
| Orchestration agent | `execute-backlog`, `plan-execute`, `progress`, `loop-operator` already cover it. |

## MANDATORY CONTROLS (from security review, before implementation)

1. Enforced read-only endpoint/method allowlist for #2; no order submission without a named operator exception +
   capital ceiling. Findings log = extracted facts only, never secrets/signatures/raw bodies.
2. Signed-request unit-test suite (known-vector, clock-skew boundary, canonical-string construction) as a HARD GATE
   before any exec-client signing code is accepted.
3. Exact version pins (`pyiem`, `pynws`, `metar`, `polymarket_us`, `nautilus-trader~=1.231`) + sanity-bounds
   validation on parser output + pre-commit guard against credential-shaped strings in `.claude/`.
4. #1 never holds live credentials; TLS never disabled; sha256(raw_text) verified before settlement use.
