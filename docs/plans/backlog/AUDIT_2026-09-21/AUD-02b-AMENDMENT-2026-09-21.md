# AUD-02b amendment — CONVERGED decision record (binding for implementation)

Base design: the appendix below (code-architect).
Peer review: prediction-market-reviewer ENDORSE-WITH-CHANGES, silent-failure-hunter ENDORSE-WITH-CHANGES.
Where this record differs from AMENDMENT.md, THIS RECORD WINS.

## P1 — the durable-evidence FALLBACK IS REMOVED
The family halt can be set ONLY after a successful live venue positions GET proves flat-and-known.
Reasons (both verified from source by two independent reviewers):
 (i) plan §6.5 clause (b) `TrialDayRecord.exit_at_ns` is unreachable from a bare slug;
 (ii) the implemented fill cross-check was MIS-KEYED — `iter_fill_records([snapshot.slug ...])` passes
      bare venue slugs while the index is keyed by full instrument id (`<slug>.POLYMARKET_US`,
      `<slug>^no.POLYMARKET_US`), so it could never fire. The test hid it with an invented id.
Delete the dead branch, the mis-keyed call and its tests — leave NO unreachable code. Record in the
module docstring that `continuous_strategy._run_never_arm_walk` was checked and is correctly keyed
(full instrument ids) — the mis-keying was confined to the deleted code, not a wider live bug.
Live GET failure => `REFUSED reason=LIVE_GET_FAILED:<ExceptionClassName>` + a mandatory `NEXT:` line:
restore venue reachability and re-run; never hand-write the key; and, in one clause, the asymmetry —
a SET halt keeps the exit seam vetoed until a separate clear, whereas a stopped node resumes normal
exit evaluation on relaunch. Open/unknown position => refuse, absolute, no override flag.
Plan-test mapping (state it in the test module docstring): plan tests (13) stale-fallback and (14)
newer-fill are RETIRED with the fallback and RE-EXPRESSED as "live GET failure => REFUSED, never flat"
(one test per failure class: transport error, auth error, malformed JSON, schema drift); all other
plan-numbered tests keep their meaning. No re-GET after the write (reviewed: over-engineering vs the
plan's accepted TOCTOU residual).

## P2 — widen two exact-inventory pins, one row each, `==` preserved, SAME commit
- tests/unit/test_polymarket_us_readonly_guard.py c10: add
  "src/breezy/strategy/current_rung_hold/set_family_halt_cli.py" with the house-style
  WIDENED-not-relaxed comment (one SqliteStateStore, one open_submit_intent_latch, same flock as
  clear_family_halt_cli.py; never a second latch/store) and an old -> new note.
- tests/unit/test_execution_egress_firewall_guard.py X1: add "tests/unit/test_set_family_halt_cli.py"
  (no pytest marks, no SOCKET_RESTORING_MARKERS, positions_reader injected everywhere, no client
  instance constructed) with an old -> new note.
No other pin is tripped (B4/V1–V5, N2, E0-INERT, [project.scripts] verified). If the full gate later
shows another, STOP and report — do not widen anything not listed here.

## P3 — review fixes (AMENDMENT.md P3 i–viii) as designed, with these corrections
- (iii) `SubmitIntentLockHeld`, `SubmitIntentLockNotHeld`, `SubmitIntentLockError` are SIBLINGS under
  `SubmitIntentError` (submit_intent.py:143,150,157). Do NOT write any comment claiming inheritance
  between them; catch `SubmitIntentLockError` => clean REFUSED with its own reason.
- L-6: update the DOCSTRING ONLY of `TrialDayLatch.is_family_halted` to enumerate all three writers of
  FAMILY_HALT_KEY (`record_duplicate_fill`, `record_ambiguous_exit`, `record_policy_halt`). No code
  change on the read path — the diff there must be docstring lines only.
- `_default_live_positions_reader`: guard `config.venue is None` AND mirror the production factory's
  `isinstance(venue_config, PolymarketUSDataClientConfig)` check (factories.py ~:692-696) => REFUSED.
- Public delegations only: `factories.shared_polymarket_us_http_client` and
  `PolymarketUSExecutionClient.declared_positions`; the private lru_cached function and its four
  `cache_clear()` call sites stay untouched; existing Nautilus factory callers keep calling what they
  call today (zero behaviour change for the node).
- `EXIT_READBACK_FAILED = 4`; evidence hashed right after argparse, before store/flock/GET;
  unreadable evidence => clean REFUSED; GET exception logged via `logger` (type + traceback is fine
  here ONLY IF you verify the HTTP client's exceptions cannot embed credentials/signed headers/URL
  query secrets — otherwise log the type only); alert-sink failure on set => one distinct stderr line;
  CLI-level DISCOVERY_FAILED test; refusal messages all carry a NEXT: line.

## Out of scope
Steps 0c–0e (setting/verifying/rolling back the halt): NOT run. No CLI run against real state.
No commits, no `uv sync`, no systemctl. The coordinator commits and records the plan amendment.


---

# Appendix — base design (code-architect), as reviewed

# AUD-02b AMENDMENT — `breezy-set-family-halt` (P1/P2/P3)

Authority: `docs/plans/backlog/AUDIT_2026-09-21/AUD-02-edge-discovery-programme-status-and-fold-in.md`
§6.5, §7 steps 0a–0e, §8, §9. Scope: amends §6.5 fallback clause (b); adds the barrier rows and review
fixes the plan never named.

## P1 — DECISION: (a) REMOVE the fallback. The halt is settable ONLY on a successful live GET.

Two independent, verified facts, not one:

1. **Plan clause (b) is unreachable** (as the implementer reported). `TrialDayRecord` is readable only
   via `record(station, climate_day, key_instrument_id=...)` / `record_with_legacy_fallback(...)`
   (`trial_day_latch.py:684`, `:699`); both need `station` AND `climate_day` AND `key_instrument_id`.
   `StartupPositionSnapshot` carries `slug`/`net_position` only (`exec/client.py:976-979`, `:3079`).
2. **The clause (a) half that WAS implemented is mis-keyed and would silently pass.**
   `check_pre_set_position` calls `iter_fill_records([snapshot.slug ...])`, which reads
   `FILL_INDEX_KEY_PREFIX + <instrument_id>`; the writer keys it by `record.instrument_id` =
   `order.instrument_id.value` (`exec/client.py:2892`, `:3644`), i.e.
   `tc-temp-sfohigh-2026-09-21-gte70f.POLYMARKET_US` (`…^no.POLYMARKET_US` for the NO leg), whereas
   `_write_startup_position_evidence` records the BARE venue slug (`:3079`). Bare slug != instrument-id
   key, so the "newer fill" check can never fire in production. The shipped test hides this by seeding
   the fill index under the same invented string as the evidence slug (`slug = "KSFO-2026-09-21-HIGH-70"`).

Option (b) is REJECTED on its own stated test ("exact and reusable without new parsing logic"). A
slug→station/climate-day route does exist (`symbology.parse_weather_slug` → `parsed.city.upper()` +
`parsed.climate_date`; used at `continuous_strategy.py:1041-1047`, `composition.py:283-294`), but reusing
it here needs THREE new pieces: the station-scope gate (`self._config.stations`, which the CLI has no
config for), a slug→`key_instrument_id` construction including the YES/NO leg (undecidable from a bare
slug — the venue nets a NO holding as a negative YES on the BASE slug), and a second slug→instrument-id
conversion to repair fact 2. That is new machinery under an operator halt tool, specified nowhere.

**Operational consequence (stated, not hedged).** With the live GET down, the family halt CANNOT be set;
A1 enforcement is unavailable during a venue/credential outage. That is the correct direction under the
plan's own rule "UNKNOWN = open = refuse-to-set": the halt also vetoes `exit_wiring.submit_exit`, so a
false FLAT strands an open position with its only automated exit disabled. An unavailable halt is
recoverable by retry; a stranded position is not.

**Required CLI output on this path** (the automation/log reader is the only audience):

```
breezy-set-family-halt: refused, pre-set open-position check source=LIVE_GET verdict=UNKNOWN reason=LIVE_GET_FAILED:<ExceptionClassName>
breezy-set-family-halt: NEXT: the venue positions GET is the ONLY accepted evidence of flatness (AUD-02b P1: the durable-evidence fallback was removed). Restore venue reachability and re-run. Do NOT hand-set the halt. If the family must stop trading before the GET recovers, stop the trade node instead -- that is the operator path, and it does not veto the exit seam.
```
Exit code stays `EXIT_REFUSED` (2). Nothing is written; the store/flock is released.

**Code effect.** `check_pre_set_position(*, positions_reader) -> PositionCheckResult` — drop the `store`,
`now_ns` and `fallback_max_age_ns` parameters; exactly three outcomes: `(LIVE_GET, FLAT_AND_KNOWN,
"eof_page_all_zero")`, `(LIVE_GET, OPEN, "non_zero_net_position")`, `(LIVE_GET, UNKNOWN,
"LIVE_GET_FAILED:<Cls>" | "LIVE_PAGE_REJECTED:<detail>")`. Delete `SOURCE_FALLBACK`,
`FALLBACK_EVIDENCE_MAX_AGE_NS`, the `StartupPositionEvidence`/`STARTUP_EVIDENCE_KEY` imports and the
`iter_fill_records` call; `SqliteStateStore` stays (the latch still needs it). Docstrings state the
removal and why — no dead branch, and no "pending mechanism" comment that reads as a TODO someone later
"finishes" onto the mis-keyed index.

## P2 — the two exact-inventory pins: BOTH are SATISFIED. Add a row to each; change no production code.

### (i) `test_polymarket_us_readonly_guard.py::test_c10_submit_intent_and_operator_controls_reference_pins`

Property: every importer of `submit_intent` takes the SAME `open_submit_intent_latch` flock, opening no
second latch and no second store. VERDICT: **satisfied.** The CLI opens exactly one
`SqliteStateStore(store_path)` and one `open_submit_intent_latch(store, store_path)` — byte-for-byte the
shape of `clear_family_halt_cli.py:104-107`; `open_trial_day_latch` is threaded from that same
`intent_latch`; both lock exceptions refuse. Row to add to the `_modules_importing("submit_intent")` set:

```python
    # WIDENED (AUD-02b, 2026-09-21), not relaxed (L-6/L-12): the comparison
    # is still `==`; old -> new added exactly this one path.
    # `breezy-set-family-halt` is the SET sibling of `clear_family_halt_cli.py`
    # two rows above and the FOURTH tool on this flock. It takes the SAME
    # `open_submit_intent_latch`, opens no second latch and no second store,
    # and writes the SAME `FAMILY_HALT_KEY` payload shape via
    # `TrialDayLatch.record_policy_halt`. It lives in `strategy`, not
    # `runtime`, for the layers-contract reason its sibling states.
    "src/breezy/strategy/current_rung_hold/set_family_halt_cli.py",
```

### (ii) `test_execution_egress_firewall_guard.py::test_x1_the_live_scan_actually_reaches_a_test_that_imports_the_exec_package`

Property: a test module importing `…polymarket_us.exec*` carries NONE of `SOCKET_RESTORING_MARKERS`
(`allow_socket`, `live`, `venue_live`, `real_money`), stubs the transport, opens no socket. VERDICT:
**satisfied.** `tests/unit/test_set_family_halt_cli.py` applies no `pytest.mark.*` at all (`_marker_names`
returns the empty set), every test injects its own `positions_reader`, and
`test_the_live_page_parser_never_constructs_an_exec_client_instance` monkeypatches
`PolymarketUSExecutionClient.__init__` to raise — positive proof no client is built.
`_default_live_positions_reader`, the only socket-capable path, is never called by a test. Row to add to
the `exec_importing_test_modules()` set, in sorted position:

```python
        # Old -> new (this row, AUD-02b 2026-09-21): added
        # `tests/unit/test_set_family_halt_cli.py`, which imports `exec.client`
        # for `PolymarketUSExecutionClient.declared_positions` -- the node's
        # OWN positions parser, reused rather than copied. WIDENED, not
        # relaxed (L-6/L-12): the comparison is still `==`; the module carries
        # NO marker at all, injects `positions_reader` in every test, and pins
        # that no client instance is ever constructed.
        "tests/unit/test_set_family_halt_cli.py",
```

### Other pins checked — NONE tripped (verified against the live rules, not recalled)

* B4/V1-V5: the CLI IS venue-touching (C4 — it imports `breezy.adapters.polymarket_us.*`), so V1-V5
  apply. No write-method literal, no `/v<n>/orders?` literal, no `.post/.put/.patch/.delete/.request`
  attribute, no `getattr` bypass, no `http_post/http_patch/http_delete`. Clean, and must STAY clean:
  `PORTFOLIO_POSITIONS_PATH` stays an import, never a re-spelled literal.
* N2 exact-set: outside `_EGRESS_PATH_PREFIXES` (no E0), basename not in `_EGRESS_MODULE_BASENAMES`
  (no E1), `PositionCheckResult` matches neither `_EGRESS_CLASS_SUFFIXES` nor the base closure (no E2),
  no function in `_EGRESS_FUNCTION_NAMES` (no E3). No row.
* B3-M: the client is built inside a function, never at module scope. Clean.
* E0-INERT (`EXEC_PERMITTED_COROUTINE_NAMES`): scans `ast.AsyncFunctionDef` under `exec/` only; the P3(i) additions are SYNC. No row.
* `test_strategy_module_gate.py` is an exit-status gate, not an inventory; `test_operator_control_assignment_scan.py`
  is the known PRE-EXISTING AUD-17 failure — do not touch it. No test pins `[project.scripts]` as a set;
  the AUD-15 `breezy-study-failed` line is another agent's WIP.

## P3 — review findings, each with the exact change

**(i) HIGH — private factory + private parser.**
* Add to `factories.py`, immediately below `_shared_polymarket_us_http_client`, a public
  `shared_polymarket_us_http_client(config: PolymarketUSDataClientConfig, clock: LiveClock) ->
  PolymarketUSHttpClient` returning `_shared_polymarket_us_http_client(config, clock)`.
  Pure delegation: `@lru_cache(maxsize=1)` stays on the private function, so the two Nautilus callers
  (`:588`, `:721`) keep byte-identical behaviour and the four `._shared_polymarket_us_http_client.cache_clear()`
  call sites (`test_polymarket_us_factories.py:179,185`; `test_exec_client_wiring_contract.py:112,118`)
  are untouched. Trips no pin.
* `_default_live_positions_reader` calls the PUBLIC name, and fixes a latent defect:
  `PolymarketUSExecClientConfig.venue` is `… | None` (`config.py:622`), so `config.venue` needs an
  explicit `None` guard raising a clean refusal, not an implicit `Optional` pass.
* `_declared_positions`: EXPOSE, do not keep reaching through the private name. Add a public
  `@staticmethod declared_positions(payload)` on the same class delegating verbatim; the six in-class
  call sites and the existing private-name tests stay untouched. The CLI calls the public name only.

**(ii) evidence hashing order.** Move `hashlib.sha256(args.evidence_path.read_bytes()).hexdigest()` to
immediately after `parse_args` and BEFORE `resolve_store_path` / `SqliteStateStore` /
`open_submit_intent_latch` / any GET — mirroring `clear_family_halt_cli.py:94-104`. Wrap in
`except OSError as exc:` → stderr `--evidence-path unreadable ({type(exc).__name__}); refused. NEXT: ...`,
return `EXIT_REFUSED`. No traceback; no store is opened on this path.

**(iii) `SubmitIntentLockError`.** Add it as the LAST of the three flock handlers (AFTER
`SubmitIntentLockHeld`/`SubmitIntentLockNotHeld`, which are its subclasses — order matters): stderr
`lock infrastructure failure ({type(exc).__name__}); refused. NEXT: this is not "the node is running" --
check the store path and filesystem, then re-run.`, return `EXIT_REFUSED`. Never a traceback, never a proceed.

**(iv) read-back after write.** Immediately after `record_policy_halt(...)`, while still holding the SAME
`intent_latch`, call `trial_latch.is_family_halted()`. If not `True`, print to stderr `WROTE the halt but
the read-back through is_family_halted() says NOT halted -- the veto may not be armed. NEXT: run --status;
if it reports halted=False, treat the family as UNPROTECTED and stop the trade node.` and return the NEW
`EXIT_READBACK_FAILED: Final[int] = 4`. No alert on this path — the state is undefined and a WARN
"halt set" would be a false claim; the stderr line is the signal.

**(v) log the broad `except`.** Add a module `logger = logging.getLogger(__name__)` and
`logger.exception("live positions GET failed")` inside the handler (stderr via the default handler), so a
programming bug (`AttributeError`/`TypeError`) is distinguishable from `ConnectionError`/`TimeoutError`.
The printed token stays `LIVE_GET_FAILED:<ExceptionClassName>` — a class name, never a payload or URL.

**(vi) DISCOVERY_FAILED CLI test.** Drive the real `main` with a `proc_root` that makes
`node_store_path_check` return `DISCOVERY_FAILED` (an unreadable `/proc/<pid>` entry); assert
`EXIT_REFUSED`, `DISCOVERY_FAILED` on stderr, the store path NOT on stderr, `FAMILY_HALT_KEY is None`.
Today only `MISMATCH` is covered.

**(vii) refusal messages.** EVERY refusal print gains a second `NEXT:` sentence naming the action.
The `verdict=OPEN` refusal must print the documented sequence verbatim:
`NEXT: breezy-clear-family-halt (written reason + evidence) -> let the exit seam submit -> re-run breezy-set-family-halt.`

**(viii) alert-sink failure visibility.** Do NOT change `health.py`. Wrap the resolved sink in a local
`_ObservedSink` whose `emit` calls the real sink inside `try/except BaseException`, sets `self.failed =
True`, and RE-RAISES — so `emit_alert`'s `logger.exception` containment is preserved unchanged. After
`emit_alert` returns, if `sink.failed`, print to stderr: `halt IS set, but the alert sink FAILED --
nobody was told. NEXT: check the alert egress configuration; the halt itself needs no action.` Exit code
stays `EXIT_OK`: a dead sink must never undo or un-report a halt that really is set (the readiness-audit
"detector without delivery" shape, surfaced rather than swallowed).

## Final touch-set

| File | Change |
|---|---|
| `src/breezy/strategy/current_rung_hold/set_family_halt_cli.py` | P1 fallback removal; P3 i/ii/iii/iv/v/vii/viii; new `EXIT_READBACK_FAILED = 4` |
| `src/breezy/adapters/polymarket_us/factories.py` | P3(i): public `shared_polymarket_us_http_client` delegation |
| `src/breezy/adapters/polymarket_us/exec/client.py` | P3(i): public `declared_positions` staticmethod delegation |
| `tests/unit/test_set_family_halt_cli.py` | replace the 4 fallback tests; add P1/P3 RED tests below |
| `tests/unit/test_polymarket_us_readonly_guard.py` | P2(i) row + docstring old->new note |
| `tests/unit/test_execution_egress_firewall_guard.py` | P2(ii) row + old->new comment |
| `tests/unit/test_polymarket_us_factories.py` | RED: public wrapper returns the SAME cached object |
| `tests/unit/test_polymarket_us_exec_client.py` | RED: `declared_positions` == `_declared_positions` on the same payloads |
| plan `AUD-02-…md` §6.5 clause (b) | rewrite to state the fallback is REMOVED and why (coordinator's call to edit) |

UNCHANGED, asserted: `record_policy_halt` (already correct), `is_family_halted`,
`family_halt_submit_veto`, `exit_wiring.submit_exit`, `continuous_family_is_halted` — ZERO diff.
`pyproject.toml` gains nothing further; its `breezy-set-family-halt` line already landed.

## Acceptance criteria (mechanically checkable)

1. In `set_family_halt_cli.py`, `/usr/bin/grep -c` for each of `DURABLE_EVIDENCE_FALLBACK`, `FALLBACK_CHOSEN`, `StartupPositionEvidence`, `iter_fill_records`, `FALLBACK_EVIDENCE_MAX_AGE_NS`, `_shared_polymarket_us_http_client`, `._declared_positions` == 0.
2. `git diff --stat` shows ZERO changed lines in `composition.py`, `exit_wiring.py`, and in `trial_day_latch.py` outside the already-landed `record_policy_halt` block.
3. The c10 pin and the X1 pin both exit 0, and both assertions are still spelled `==`.
4. `pytest tests/unit/test_set_family_halt_cli.py tests/unit/test_clear_family_halt_cli.py tests/unit/test_polymarket_us_factories.py tests/unit/test_polymarket_us_exec_client.py` exits 0.
5. `lint-imports` exits 0 (adapters still never import `breezy.runtime`); `mypy src` exits 0 with no `Optional` error on `config.venue`.
6. Every non-zero-exit branch prints a `NEXT:` line — asserted over all ten: not-configured, MISMATCH, DISCOVERY_FAILED, unreadable evidence, lock-held, lock-not-held, lock-error, verdict=OPEN, verdict=UNKNOWN, read-back failure.
7. The exit-code set is exactly `{0, 2, 3, 4}`, pinned against the module's `EXIT_*` constants.
8. `tests/unit/test_set_family_halt_cli.py` carries no `pytest.mark` — asserted by the X1 row's own scan.

## RED tests to write FIRST (one per change; each must fail on today's tree)

* **P1a** `test_a_failed_live_get_always_refuses_and_names_the_exception_class` — reader raises
  `ConnectionError` WITH a fresh, eof-complete, all-zero `StartupPositionEvidence` seeded; assert
  `EXIT_REFUSED`, `LIVE_GET_FAILED:ConnectionError`, `NEXT:` on stderr, `FAMILY_HALT_KEY is None`.
  (Red today: reports `trial_exit_cross_check_unavailable`, no `NEXT:`.)
* **P1b** `test_check_pre_set_position_takes_no_store_and_has_only_three_outcomes` — `inspect.signature`
  plus the three `(source, verdict)` pairs.
* **P2** run the c10 pin and the X1 pin — each RED until its row lands.
* **P3(i)** `test_the_public_http_client_wrapper_returns_the_same_cached_instance` (factories suite);
  `test_declared_positions_public_alias_agrees_with_the_private_staticmethod` (exec-client suite,
  parametrised over the existing foreign/empty/non-eof payloads).
* **P3(ii)** `test_an_unreadable_evidence_file_refuses_before_the_store_is_opened` — evidence path is a directory; assert `EXIT_REFUSED`, no traceback, `store_path.exists() is False`.
* **P3(iii)** `test_a_lock_infrastructure_failure_refuses_with_a_distinct_reason` — patch `open_submit_intent_latch` to raise `SubmitIntentLockError`; assert `EXIT_REFUSED`, distinct token, no traceback.
* **P3(iv)** `test_a_failed_read_back_after_the_write_exits_distinctly` — patch `is_family_halted` to return `False` on the post-write call only; assert exit `4`, UNPROTECTED wording, no alert emitted.
* **P3(v)** `test_a_programming_bug_in_the_reader_is_logged_not_just_tokenised` — reader raises
  `AttributeError`; assert `caplog` has an ERROR with a traceback AND the token is exactly
  `LIVE_GET_FAILED:AttributeError`.
* **P3(vi)** `test_a_discovery_failed_store_path_check_refuses_and_writes_nothing`.
* **P3(vii)** `test_every_refusal_prints_a_next_step` (the ten branches in criterion 6).
* **P3(viii)** extend the existing raising-sink test: still `EXIT_OK`, still halted, PLUS the `nobody was told` stderr line.
