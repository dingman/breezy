Commit: e4848c39a979bac5a91b8f6b3887f75c497c1be8

# Free hygiene — flaky gate test, doc truth, stale docstrings, dead record (2026-09-12) — Rev 1

**L-1.** Nothing in this plan creates infrastructure, so the null hypothesis is tested only where a native could plausibly exist: the `PositionReportingLag` measurement. **Verdict: GENUINELY-ABSENT for the record, NATIVE-insufficient for the measurement.** Positive control: `grep -c 'class OrderStatusReport' .venv/lib/python3.13/site-packages/nautilus_trader/execution/reports.py` = 1, and `ts_last` is present at `reports.py:126,194,267` — the grep reaches installed source. Negative: `grep -rn 'reporting_lag\|ReportingLag' .venv/lib/python3.13/site-packages/nautilus_trader/` = 0 matches. The closest native is `position_check_interval_secs` (`live/config.py:150,195`), a periodic position-reconciliation poll that is deliberately `None` here (contract-pinned); it polls, it does not measure fill→confirm latency. All other increments (H-1 pytest assertion shape, H-2..H-7 prose, H-9/H-10 static gates) touch **no Nautilus surface at all** — no extension point, no subclass, no config.

**Constraints.** Nautilus Trader is immutable — never patch, fork, bypass, or reimplement it. `allow_short` stays `False`. Never weaken or delete a safety, settlement, or contract test to go green. Never assign an operator-reserved value (max daily budget, max per position). Never touch live-trading enablement or the NO-SEND execution-egress firewall. PREREG v3 is BINDING: §3/§5/§9 meaning changes are AMENDMENT/RULING items (see §8), never code patches. Tests run via `scripts/ci/run_tests_no_egress.sh [args]` — `addopts` already carries `-q`, never add another. `lint-imports` and `mypy` after every slice.

**Scope note.** This plan is *behaviour-preserving by construction*. Every increment changes a test assertion shape, a comment, a docstring, or whitespace. Zero increments change a runtime code path. That is the property the acceptance evidence must demonstrate.

---

## 1. Goal state (falsifiable)

The item is closed when **all five** hold:

| # | Goal | Falsifier |
|---|---|---|
| G1 | The no-egress gate is green at HEAD on **every** calendar instant — no assertion in `tests/` depends on the wall clock's digits | `tests/unit/test_app_trade_main_permit_logging.py` passes for a planted `issued_at_ns` containing every sensitive value's digit run |
| G2 | The five named state documents say what the code and the host actually do | each stale sentence carries a dated superseding note citing HEAD file:line |
| G3 | The three stale docstrings are true | each replacement's claim re-verified against HEAD source |
| G4 | `PositionReportingLag` is either produced or its non-production is truthfully explained and escalated | module docstring states the real blocker; ruling item filed (§8 R-1) |
| G5 | No behaviour change anywhere | `git diff` touches only test-assertion shape, docstrings, comments, Markdown, and whitespace — no runtime statement |

**Happy walk (the flake, hop by hop).** `trade_module.main()` mints the live-trading permit → `app/trade.py` logs `live-trading permit issued issued_at_ns=<ns> expires_at_ns=<ns> ttl_s=36000` → the test regex at `tests/unit/test_app_trade_main_permit_logging.py:104-107` matches → the leak scan at `:114-115` iterates `_SENSITIVE_VALUES` (`:57`) and does `value not in caplog.text`.

**Failure walk (measured, not hypothesised).** `_SENSITIVE_VALUES` contains `"100"` — the `order_count` default of `enable_operator_gate` (`tests/unit/test_polymarket_us_permit_issuance.py:118`). `issued_at_ns` is a ~19-digit nanosecond timestamp; `expires_at_ns = issued_at_ns + PERMIT_TTL_NS` (`safety.py:172,697`). Whenever the digit run `100` appears **anywhere** inside either number, the bare substring scan fires on a line that leaked nothing. **Measured today** (2 000 000 sampled timestamps over ±1 year, `PERMIT_TTL_NS = 10*60*60*1e9`): P(`issued_at_ns` contains `100`) = **1.53%**; P(the permit line as a whole contains `100`) = **1.98%**. The value the audit captured, `issued_at_ns=1789215710055411863`, contains `100` — and so does its `expires_at_ns=1789251710055411863`. `ttl_s=36000` never collides. The other three sensitive values (`operator@example.com`, `5.00`, `1000.00`) each contain a non-digit character and structurally cannot collide with a digit run.

**Second failure walk (the record with no producer).** PREREG v3 §11 assigns `PositionReportingLag` emission to the **resolver path**. At HEAD that path cannot supply the quantity the record defines: `_resolve_ambiguous_intents` reads positions at `exec/client.py:1430`, takes `now_ns` at `:1448`, and `_resolve_accept_fill` (`:1550`) stamps `ts_event=now_ns` (`:1616`, `:1658`). The GET report carries no venue fill instant — `parse_order_status_report` sets `ts_accepted` and `ts_last` **both** to `createTime` and explicitly refuses to promote `insertTime` (`exec/reports.py:911-916`). So a record built on that path would be `first_eof_read_ts_showing_long` (read at `:1430`) minus `fill_ts_event` (`now_ns`, taken **later** at `:1448`) — a **negative** delta, which `__post_init__` rejects (`position_reporting_lag.py:56-61`). Using a later pass's read instead yields the resolver's own poll cadence, not the venue's reporting lag. The only venue-sourced `fill.ts_event` is on the create path (`exec/client.py:2802,2852`, parsed at `:581` from `payload["tsEvent"]`) — the branch that has never fired on a real order.

---

## 2. Evidence vs code

| # | Piece | Code/host today (file:line) | Gap |
|---|---|---|---|
| 1 | Permit-log leak scan | `test_app_trade_main_permit_logging.py:57,114-115` | bare substring scan; 1.98%/run false failure (measured) |
| 2 | Same-pattern audit | `rg -n 'in caplog.text' tests` → 12 hits | 3 other leak scans use **non-numeric** sentinels (`test_trade_supervisor.py:733,753`; `test_exec_state_db_path.py:277`) — cannot collide. Remaining 8 are presence assertions. **H-1 is the only site.** |
| 3 | systemd README | `deploy/systemd/README.md:3-5` "PREPARED, NOT ACTIVATED. Nothing … is installed, enabled, or running" | **20 units installed**; 19 are symlinks into `/home/jon/breezy/deploy/systemd/`; 3 services `active running`, 9 timers `active waiting`, 8 oneshot services `inactive` by design. Brief cited `:5-6`; the claim actually spans `:3-5`. |
| 4 | systemd drift | `/home/jon/.config/systemd/user/breezy-nws-ingest.service` is a **regular file**, dated 2026-08-24 | No source in `deploy/systemd/` — the repo is not the complete source of truth for the installed set |
| 5 | PROGRAMME_PATH ROI | `docs/core/PROGRAMME_PATH.md:7-13` | An expectancy pipeline **does** exist: `src/breezy/settlement/trial_scorer.py`, `src/breezy/settlement/roi_bound.py:173 compute_roi_bound`. The binding limit is statistical power, not a missing pipeline. |
| 6 | PROGRAMME_PATH exec spine | `:22-24` "R-5R + R-6.5P VENUE-GATED …; R-4P-2 (cursor pagination) open" | Exec spine landed and live (audit READY row: `exec/client.py:2647-2716` chokepoint, permit mint, intent latch, resolver) |
| 7 | GO_LIVE_BLOCKERS | `docs/evidence/GO_LIVE_BLOCKERS_2026-09-06.md:18` (GL-1), `:21` (GL-4), `:26` (GL-9) shown open | GL-1/GL-4 **RULED HOLD** 09-10 (`gl1_gl4_order_state_ruling_2026-09-10.md:3`); GL-9's observable met only synthetically (`tests/contract/test_live_fill_scoring_chain_contract.py`, audit S7) |
| 8 | BLIND_RISK_VIEWS | `docs/core/findings/BLIND_RISK_VIEWS_2026-09-02.md:151` "all three live node configs pass `strategies=[]`"; `:155-157` "permit system is entirely unwired … zero callers in `src/`" | Both conclusions false at HEAD. Strategies are added **after** `node_config`, at `trade_cli.py:396-397` (`node.trader.add_strategy`). `assert_live_order_submission_permitted` is called at `exec/client.py:2693`. **Nuance:** the cited `node_config.py:231,544,819` literally still read `strategies=[]` — the citation is accurate, the conclusion is not. |
| 9 | native_reuse_audit §5 | `docs/evidence/native_reuse_audit_2026-09-01.md:111-118` "no `RiskEngineConfig` and no `max_notional_per_order` anywhere in `src/breezy` … **Being remediated**" | Done: `LiveRiskEngineConfig` at `node_config.py:67,567,615`, `max_notional_per_order` at `:619` |
| 10 | native_reuse_audit §6 | `:122-133` "`forbidden_modules` is `["nautilus_trader"]` … ~30-entry `ignore_imports` … **Being narrowed**" | Done: `pyproject.toml` now reads `forbidden_modules = ["nautilus_trader.adapters.polymarket"]` with an empty allow-list |
| 11 | Docstring A | `exec/client.py:1965-1972` "there are no fills, because there are no orders" | False: a fill exists (09-11 20:20Z). Consequence: native reconciliation re-infers it EXTERNAL each boot (audit S9 #1, log 2026-09-12T02:26:12.478Z "0 orders, 0 fills") |
| 12 | Docstring B | `runtime/position_reporting_lag.py:8-16` "neither exists in `src/` yet (grep confirms zero hits for both names)" | False: `_resolve_ambiguous_intents` at `exec/client.py:1182`, `read_startup_position_evidence` at `:2378`. The real blocker is §1's second failure walk. |
| 13 | Docstring C | `operator_controls.py:85-92` "ZERO PRODUCTION CALL SITES, DELIBERATELY … ships as a library with no caller" | False: `DailySpendLedger` constructed at `factories.py:777` (imported `:89`); further prod importers at `runtime/order_enablement.py:49`, `safety.py:558,567,581` |
| 14 | `PositionReportingLag` reach | codegraph impact: 8 symbols, all inside `position_reporting_lag.py` + `tests/unit/test_position_reporting_lag.py` | Zero production producers **and** zero production consumers |
| 15 | Static gates (measured today) | `ruff check` **24**; `ruff format --check` **268 files**; `mypy` **433 errors / 41 files** | See §2a — the audit's "all in tests/ and scripts/analysis" is **wrong for ruff** |

### 2a. Static-gate breakdown (measured, `ruff 0.16.4` / `mypy 2.3.1`)

| Gate | Total | Where | Correction to audit S7 |
|---|---|---|---|
| `ruff check` | 24 | 18 in `docs/evidence/venue/kalshi/raw/**` (throwaway probe scripts), 3 `scripts/analysis`, 2 `tests/unit`, **1 `src/breezy/persistence/family_manifest.py:42` (RUF022, autofixable)** | "all in tests/ and scripts/analysis" is false on both counts |
| `ruff format --check` | 268 files | 253 `.py` + **15 `.md`**; of the `.py`: 155 `tests/`, **64 `src/breezy/`** (strategy 21, adapters 13, runtime 12, …), 31 `scripts/`, 3 `docs/evidence` | A bulk `ruff format .` would rewrite 64 money-path modules **and** `docs/core/LESSONS.md` (binding) and `.claude/skills/nautilus-trader-patterns/SKILL.md` |
| `mypy` | 433 / 41 files | 399 `tests/unit`, 29 `scripts/analysis`, 4 `tests/contract`, 1 `tests/integration`; **0 under `src/`** | Correct as stated |

Worst two files: `tests/unit/test_trade_supervisor.py` **197**, `tests/unit/test_trade_supervisor_cont_self_check.py` **64** = 261/433 (60%). Dominant code across the pair: **`no-untyped-def` 203**, then `arg-type` 36, `union-attr` 8, `type-arg` 5, `assignment` 5, `attr-defined` 3, `func-returns-value` 1.

Neither `ruff` nor `mypy` nor `lint-imports` is invoked by `scripts/ci/run_tests_no_egress.sh`, and there is no `Makefile`; they are run by hand per the standing constraint. So these counts gate nothing automatically today — which is why H-9/H-10 are OPTIONAL and churn-bounded.

---

## 3. Design

**Where.** H-1 in one test module. H-2..H-6 in five Markdown files. H-7 in three docstrings. H-9/H-10 in three lint sites and two test modules.

**H-1 shape (the only non-prose change).** Split the constant by *collidability*, and check each half the way that half can actually leak:

- `_SENSITIVE_SUBSTRINGS` — values containing a non-digit character (`operator@example.com`, `5.00`, `1000.00`). Keep the existing bare `not in caplog.text` scan; these cannot appear inside a digit run.
- `_SENSITIVE_FIELD_VALUES` — values that are a bare digit run (`100`). Check by **whole-field equality**: parse `key=value` tokens out of each record's message and assert no token's *value* equals a sensitive one.

This is a **strengthening in one direction and a narrowing in exactly one**: a leak of `100` as a real field value (`session_order_count=100`) still fails; only `100` *embedded in a longer digit run* stops firing. `_SENSITIVE_VALUES` itself is retained as the union so no value can be dropped from coverage by editing one tuple.

**What is NOT changed (byte-unchanged pins).** No production module under `src/breezy/` changes behaviour in H-1..H-8. These must stay green untouched and are the guard that H-7's docstring edits changed nothing executable:
- `tests/unit/test_execution_egress_firewall_guard.py` — **the exec-package pin**. Its X3 scan reads *string constants* as well as source (`:1294-1298`), so any replacement docstring inside `exec/` must not contain `_SHORT` or `OUTCOME_SIDE_NO`, and must introduce no `1 - x` BinOp (`:1300`). Its `==` file-set assertion (`:1557`) stays byte-identical — no file is added to or removed from `exec/`.
- `tests/unit/test_position_reporting_lag.py` — all five tests unchanged; the record's behaviour is not touched.
- `tests/unit/test_order_submission_permit_issuance.py`, `tests/unit/test_polymarket_us_permit_issuance.py` — the R2 leak-scan precedent H-1 mirrors.
- `tests/contract/**` — untouched.

**Doc edits are insertions, never rewrites.** Every H-2..H-6 edit is a dated superseding note placed *beside* the original text. Historical evidence documents keep their original wording — the record of what was believed on the day is the artefact. The only replacement is H-2's status paragraph, because a `Status:` line is a live claim about the host, not a historical record.

---

## 4. Increments

| id | size | RED test(s) / mutation evidence | minimal change | observable |
|---|---|---|---|---|
| **H-1** | S | `tests/unit/test_app_trade_main_permit_logging.py`: `test_a_permitted_ns_timestamp_embedding_every_sensitive_digit_run_is_not_a_leak` (planted record, expects PASS — RED today) and `test_a_sensitive_value_logged_as_a_whole_field_value_is_still_a_leak` (plants `session_order_count=100` and `operator_id=operator@example.com`, expects the scan to FAIL — GREEN today, must stay GREEN) | `:57` split constant; `:114-115` → helper `_assert_no_sensitive_value_leaked(caplog)` in the same module | both new tests GREEN; the parametrised planted-timestamp case is deterministic, so the 1.98% flake is gone by construction, not by retry |
| **H-2** | S | L-33 characterisation: `systemctl --user list-unit-files 'breezy*'` = 20; `list-units` = 3 running + 9 waiting + 8 inactive; `ls -l /home/jon/.config/systemd/user/` = 19 symlinks + 1 regular file | replace `deploy/systemd/README.md:3-5`; insert one "Installed state (verified 2026-09-12)" line + runbook pointer | README's status matches `systemctl` output; the `breezy-nws-ingest.service` drift is named |
| **H-3** | S | L-33: `ls src/breezy/settlement/{trial_scorer,roi_bound}.py`; `roi_bound.py:173`; `node_config.py:615` | insert a dated note after `docs/core/PROGRAMME_PATH.md:13`; insert a second note after `:24` for the EXEC SPINE lines | both stale claims carry a superseding note; original 2026-09-01 text byte-unchanged |
| **H-4** | S | L-33: `gl1_gl4_order_state_ruling_2026-09-10.md:3` "Both HOLD"; audit S7 for GL-9 | insert a dated header note after `GO_LIVE_BLOCKERS_2026-09-06.md:12` | the ruling is reachable from the blocker list |
| **H-5** | S | L-33: `trade_cli.py:396-397`; `exec/client.py:2693` | insert a dated header note after `BLIND_RISK_VIEWS_2026-09-02.md:9` | the two false conclusions are marked, with the `node_config.py` citation nuance stated |
| **H-6** | S | L-33: `node_config.py:67,567,615,619`; `pyproject.toml` `forbidden_modules` | insert one line after `native_reuse_audit_2026-09-01.md:109` and one after `:122` | "Being remediated"/"Being narrowed" both resolved to DONE with the landing citation |
| **H-7** | S | L-33 mutation evidence = the three gaps in §2 rows 11–13 | replace three docstring bodies in place | each claim re-derivable from HEAD; `test_execution_egress_firewall_guard.py` still green (X3 token scan) |
| **H-8** | — | none — this is a ruling, not a build | no code change; §8 R-1 | recorded decision |
| **H-9** | S, OPTIONAL | none (formatting) | `ruff check --fix src/breezy/persistence/family_manifest.py` (RUF022); hand-fix `tests/unit/test_quote_tape_service_memory_ceiling.py:68` (E501) and `tests/unit/test_ma_prelock_winner_ask_study.py:404` (DTZ011); `ruff format` **only** on `.py` paths this commit already touches | `ruff check src/ tests/ scripts/` clean; `ruff format --check` count drops by exactly the touched-file count, never in bulk |
| **H-10** | M, OPTIONAL | none (typing) | add annotations to `tests/unit/test_trade_supervisor.py` and `tests/unit/test_trade_supervisor_cont_self_check.py`; 203 of the 261 are `no-untyped-def` (add `-> None` + param types), then `arg-type` (36) | `mypy` total falls 433 → ≤ 172 with **zero** assertion changes in either file |

**Verification commands** (run after every increment):

```
scripts/ci/run_tests_no_egress.sh tests/unit/test_app_trade_main_permit_logging.py
scripts/ci/run_tests_no_egress.sh tests/unit/test_execution_egress_firewall_guard.py tests/unit/test_position_reporting_lag.py
scripts/ci/run_tests_no_egress.sh
.venv/bin/lint-imports
.venv/bin/mypy
.venv/bin/ruff check .
git diff --stat
```

Read the **exit code**, not the summary line: `addopts` already carries `-q`, and a second `-q` collapses it to `-qq` and hides the summary.

---

## 5. Acceptance

The executing agent must show, as evidence:

1. **H-1 RED→GREEN transcript**: the planted-timestamp test failing against HEAD's `:114-115`, then passing after the split — plus the whole-field leak test green **both** before and after (proof the guard was narrowed only where it was wrong).
2. `git diff` on `src/breezy/**` limited to docstring/comment lines — verified by `git diff -U0 -- src/ | grep -E '^[+-]' | grep -vE '^[+-]{3}'` showing no non-comment, non-string statement.
3. `scripts/ci/run_tests_no_egress.sh` exit code 0, with `tests/unit/test_execution_egress_firewall_guard.py` and `tests/unit/test_position_reporting_lag.py` explicitly in the run.
4. `lint-imports` and `mypy` output, before and after, with the delta explained.
5. For each of H-2..H-6: the inserted note quoted verbatim, plus the command that re-verifies its claim (the `systemctl` invocation, the `grep`, the file:line).
6. §8 R-1 written up and filed — the plan is not closed by silently deleting or silently wiring `PositionReportingLag`.

---

## 6. Non-goals

- **Any behaviour change.** If an increment requires one, it leaves this plan.
- **Bulk `ruff format .`** — it would rewrite 64 `src/breezy/` modules and 15 `.md` files including `docs/core/LESSONS.md` (binding) and a `.claude/skills/**` file. Explicitly refused.
- **`docs/core/PROGRESS.md`** — including the CF-11/CF-12 counts and the "at 4 covered/day the 15th lands 09-11" line. Coordinator's to refresh; out of scope here.
- **`docs/specs/PREREG_v3_*`** — no edit. §11's resolver-emission assignment is a ruling (§8 R-1), not a patch.
- **The 18 `ruff check` errors under `docs/evidence/venue/kalshi/raw/**`** — throwaway capture-probe scripts; add to `extend-exclude` or leave, but do not hand-fix.
- **`docs/core/RUNBOOK_*:532` "CRITICAL alert fires" (log-only)** — listed in audit §5 but not assigned to this plan. Named here so it is not silently dropped; it belongs with the alert-sink work.
- **Deleting `PositionReportingLag`** — see §8 R-1; deletion would orphan PREREG v3 §5's re-arm-floor verification instrument.

---

## 7. Risks, blast radius, rollback

| Risk | Severity | Mitigation |
|---|---|---|
| H-1 narrows a security assertion too far | **HIGH** — it is an R2 secret-leak guard | The whole-field test is written FIRST and must be green before *and* after. `_SENSITIVE_VALUES` is kept as the union of the two halves so no value can be silently dropped. Never delete the scan. |
| H-7 edits a docstring inside `exec/` | MED | The X3 scan reads string constants (`test_execution_egress_firewall_guard.py:1294-1298`): new text must avoid `_SHORT` and `OUTCOME_SIDE_NO`, and add no `1 - x`. The `==` file-set pin (`:1557`) is untouched — no file moves into or out of `exec/`. |
| H-9 `ruff format` widens beyond touched files | MED | Formatter runs on an explicit path list only, never `.`; diff reviewed before commit. |
| H-10 annotation pass silently edits an assertion | MED | Constrain the diff to signatures and imports; `git diff` must show no change on any `assert` line. |
| A concurrent agent holds the same files | MED | Commit only files this plan touches, by explicit path — never `git add -A`/`-am`. |
| Doc rewrite destroys a historical record | LOW | Every H-3..H-6 edit is an *insertion*; the only replacement is H-2's live `Status:` claim. |

**Blast radius (codegraph impact).** `PositionReportingLag` → 8 symbols, all within `src/breezy/runtime/position_reporting_lag.py` and `tests/unit/test_position_reporting_lag.py`. No production consumer; the only other mention in `src/` is a comment at `strategy/current_rung_hold/continuous_strategy.py:120`. H-1's blast radius is one test module. H-2..H-6 are Markdown, radius zero.

**Rollback.** Every increment is an independent commit touching ≤3 files; `git revert` per increment. No migration, no state, no deploy step. No systemd unit is installed, enabled, started, stopped, or reloaded by this plan — H-2 only *describes* the installed set.

---

## 8. Rulings / operator items

**R-1 — `PositionReportingLag`: keep, wire, or delete? (strategy-lead ruling; NOT build-side)**

PREREG v3 §11 assigns emission to the "resolver path"; §5 makes the record the verification instrument for `_REARM_MIN_DELAY_SECS = 120` ("unverified until first `PositionReportingLag` record in live fills"). The code says the assignment cannot be honoured as written (§1, second failure walk).

| Option | What it costs | What it needs |
|---|---|---|
| **A — wire on the resolver path** (brief's first option) | **NOT RECOMMENDED.** `ts_event=now_ns` (`exec/client.py:1616`) is a clock read taken *after* the positions read (`:1430` vs `:1448`), so `__post_init__` raises; and the GET report has no venue fill instant (`exec/reports.py:911-916`). Any value produced measures Breezy's own poll cadence, then "verifies" the 120 s floor against a quantity §5 does not define. | A PREREG §5 redefinition of the measured quantity — i.e. an amendment, not a patch |
| **B — delete the module** (brief's second option) | Orphans §5's named verification instrument and §11's Phase 0b row; the 120 s floor loses its stated path to verification | A PREREG v3 §5 **and** §11 amendment, plus a note on why the floor stays permanently unverified |
| **C — keep the record, correct the docstring, wire later on the create path** | **RECOMMENDED.** The create path already carries a venue-sourced `fill.ts_event` (`exec/client.py:2802,2852`, parsed `:581`). It is the branch that has never fired on a real order — the same branch audit B2 is already working to exercise. Zero code change now; H-7 makes the module honest. | A §11 clarification that emission belongs on the **create-path accept-fill**, not the resolver path |

Evidence the decider needs: the §1 failure walk above; PREREG v3 §5 (`:80-106`) and §11 (`:172-188`); audit rows B2 and S9 #5. **L-32 prior:** `docs/evidence/gl1_gl4_order_state_ruling_2026-09-10.md` (fail-closed stands where live evidence is absent) and the memory rule that resolver fills are residual by PREREG (the 09-12 fee-reconcile patch was blocked on exactly this boundary) both argue against inventing a resolver-path number. **Boundary:** if a reconciliation plan owns the resolver/create-path fill work, R-1's *wiring* half is theirs; R-1's *ruling* half (what §11 should say) is the strategy lead's. This plan owns only the docstring.

**R-2 — `breezy-nws-ingest.service` has no source in `deploy/systemd/`** (build-side, but out of this plan's scope). An installed, enabled, running unit whose definition exists only under `~/.config`. Options: commit the unit file to `deploy/systemd/` and re-link, or document it as intentionally host-local. H-2 only *records* the drift. No unit is touched here.

**Operator items: none.** Nothing in this plan touches budgets, enablement, position caps, or the NO-SEND firewall.

---

## 9. Citations (verified against the working tree, 2026-09-12, HEAD `e4848c3`)

| Claim | Source |
|---|---|
| Leak scan + constant | `tests/unit/test_app_trade_main_permit_logging.py:57,104-107,114-115` |
| `order_count="100"` default | `tests/unit/test_polymarket_us_permit_issuance.py:118` |
| `PERMIT_TTL_NS = 10*60*60*1e9` | `src/breezy/adapters/polymarket_us/safety.py:172`, used `:697` |
| Flake rate 1.53% / 1.98% | measured today, 2 000 000 samples, `.venv/bin/python`, seed 20260912 |
| Same-pattern audit (12 hits, 3 other leak scans, all non-numeric) | `rg -n 'in caplog.text' tests` |
| 20 units / 3 running / 9 waiting / 8 inactive / 19 symlinks / 1 regular file | `systemctl --user list-unit-files 'breezy*'`, `list-units --all`, `ls -l ~/.config/systemd/user/` |
| Resolver ordering and `ts_event=now_ns` | `src/breezy/adapters/polymarket_us/exec/client.py:1182,1373,1430,1448,1468,1550,1616,1658` |
| GET report timestamps are `createTime` | `src/breezy/adapters/polymarket_us/exec/reports.py:911-916,924` |
| Create-path venue fill ts | `src/breezy/adapters/polymarket_us/exec/client.py:581,2802,2852` |
| Record + invariant | `src/breezy/runtime/position_reporting_lag.py:8-16,41,55-67` |
| Zero producers / 8-symbol radius | `grep -rn PositionReportingLag src/ scripts/ tests/`; codegraph impact |
| Permit chokepoint call site | `src/breezy/adapters/polymarket_us/exec/client.py:2693` |
| Strategies wired after config | `src/breezy/runtime/trade_cli.py:396-397`; literal `strategies=[]` at `node_config.py:231,544,819` |
| `DailySpendLedger` prod call sites | `src/breezy/adapters/polymarket_us/factories.py:89,777` |
| Native risk caps landed | `src/breezy/runtime/node_config.py:67,567,615,619` |
| `forbidden_modules` narrowed | `pyproject.toml` `[[tool.importlinter.contracts]]` "Breezy never imports the Nautilus Polymarket .com adapter" |
| Layers direction (adapters below runtime) | `pyproject.toml` `[tool.importlinter]` `layers` |
| Exec-package pins (X3 tokens, `==` file set) | `tests/unit/test_execution_egress_firewall_guard.py:236,252,1294-1300,1555-1566` |
| GL-1/GL-4 ruled HOLD | `docs/evidence/gl1_gl4_order_state_ruling_2026-09-10.md:3` |
| PREREG v3 §5 re-arm floor / §11 emission row | `docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:80-106,172-188` |
| Static-gate totals and breakdowns | `ruff 0.16.4`, `mypy 2.3.1`, commands in §4 |
| Expectancy pipeline exists | `src/breezy/settlement/trial_scorer.py`, `src/breezy/settlement/roi_bound.py:173` |

**UNVERIFIED / marked:**
- The exact replacement **text** for the three docstrings (H-7) and the six doc notes (H-2..H-6) is specified by *content requirement* in §2/§4, not drafted verbatim — the executing agent drafts it and must re-verify each claim against HEAD before writing. Every factual ingredient is cited above.
- H-9's "`ruff format` on files this commit already touches" cannot be enumerated here: this plan runs blind to the other 2026-09-12 plans. It is a **rule**, applied at execution time, not a file list.
- The audit's `deploy/systemd/README.md:5-6` line reference is off by two (the claim is at `:3-5`); `:5-6` is corrected above, not carried forward.
- The last real run date of the 4 `venue_live` tests (audit S7) is unknown and not established here.
