# EDGE-3 (MED) — Per-family continuous-rung-hold halt — plan r2 (2026-09-27)

Status: PLAN r2. Nothing is implemented. Supersedes r1. It needs a round-2 peer review
(architect, security-reviewer, python-reviewer) before any build (§2 planning gate).

## r1→r2 changes

| # | Round-1 finding | r2 disposition |
|---|---|---|
| 1 | architect #1: the boot migration is unnecessary machinery | **ADOPTED: read-time attribution. Nothing is ever migrated.** Readers consult the legacy key and the per-family key forever. A legacy value whose bytes hash to the pinned sha256 halts `pm_us_crh_v4` only. Any other non-sentinel legacy value halts every family (fail closed). Removed: the boot writer, the MIGRATED sentinel, the `halt_migrated/` audit, the crash and read-back analysis, the `MigrationOutcome` kinds, the migration alerts, and their tests (r1 tests 6-12, 16, 17, 20, 28). The no-unset-window proof is now trivial (§4.4): EDGE-3 writes nothing at deploy. |
| 1a | the v4 clear must retire the legacy value | `clear_family_halt` on a v4-bound latch writes CLEARED to the per-family key and then to the legacy key. The legacy write comes last, so v4 reads halted at every crash point (§4.3). |
| 1b | sha constant | The FULL 64-hex sha is used everywhere. The strategy constant is duplicated in the runtime layer and pinned by a parity test. The digest re-uses the strategy decoder (see Disagreement D1). Re-verified 2026-09-27 read-only (`file:…?mode=ro`): **64 hex chars, 259 bytes**, `5a82b40140618de8d35338c0c9463afb256de37b73729ebbe32ffd8d75b19f28`. No `family_halt/*` or `halt_cleared/*` keys exist. |
| 1c | `--legacy` re-check (security) | Under read-time attribution, the A1 bytes stay in the legacy key. `--legacy` therefore REFUSES any value that matches the pin. Only the v4 per-family clear path can retire it (§4.3, test 13). |
| 2 | architect #2: rollback hazard | Added a pre-revert procedure (§8.4) and a test pinning that the pre-EDGE-3 one-arg decoder ignores per-family keys (test 14). |
| 3 | architect #3: `--status` must never write | `--status` never writes, never migrates, and **never takes the flock**. It is a lock-free `mode=ro` read, like the digest. It reports `legacy=halts_all|attributable_to_v4|cleared` (plus `absent` on a fresh store). The code-vs-evidence contradiction is resolved in §2: **the code is true, and AUD-02b:18 is false.** |
| 4 | security (blocking): path traversal | `--family-id` is validated against `^[A-Za-z0-9_-]{1,64}$` before any `Path` join. The path is then resolved and asserted to be contained under `deploy/families` before `load_family_manifest`. New test 21. Risk R6 covers family-id reuse. The digest wrapper re-uses the exact `replay-daily-run.sh:110-127` idiom. |
| 5 | python (blocking): boot tests | The real harness was opened (§6.2). New file `tests/unit/test_app_trade_family_halt_binding.py` re-uses `RecordingNode`, `_trade_env`, `_write_today_catalog` and `_operator_order_ceiling` from `test_trade_cli_current_rung_hold.py`, the same way `test_app_trade_fee_drift_probe_wiring.py:58-63` does. Halt state is asserted before strategy composition by spying on `breezy.app.trade.make_trial_day_latch_factory` / `open_trial_day_latch` (the `_spy` pattern at `test_trade_cli_current_rung_hold.py:381-386`), and inside the latch window from a `run()` override. |
| 6 | test list too long | Trimmed from 42 to **28** new tests. r1 tests 1+2 are merged into test 1; 7/16/37 are dropped (no migration, and no multi-key write ordering is left to race); 34+35 are merged into test 26. r1 3, 4, 24, 32, 38 and 40 are kept as tests 2, 3, 18, 12, 27 and 28. |
| 7 | the digest scope was under-sized | Re-sized in §5 item 11: about 150-200 LOC in the digest, about 30 in the wrapper, 8 existing `read_family_halt_status(` call sites and the `_store_with_halt_value` helper re-pointed, and the `format_digest_detail` token-tier logic touched. It is its own slice, S2c. |
| 8 | UNATTRIBUTABLE: boot or refuse? | **Kept: boot halted, never refuse to boot (L-48).** An unpinned legacy value halts every family. The boot logs it and emits a CRITICAL alert every boot, but writes nothing. |

Disagreements (with evidence):
- **D1, the sha "duplicated in the digest reader".** `scripts/analysis/decision_funnel_daily_digest.py:60`
  already imports `FAMILY_HALT_KEY, decode_family_halt` from the strategy layer. Scripts are
  outside the `lint-imports` runtime→strategy contract. A third literal in the digest would
  be dead code beside a strategy decoder that already carries the pin. It would also be one
  more place to drift. r2 therefore duplicates the constant in the runtime layer only, which
  `lint-imports` forces. The parity test pins runtime == strategy, and it pins that the digest's
  decoder `is` the strategy's function (an identity check). If the coordinator still wants a
  literal in the digest, it costs one constant plus one parity assertion. Nothing else changes.
- **D2, a fourth `legacy=` value.** A fresh store (every test, and any new venue store) has no
  legacy key. `--status` reports `legacy=absent` rather than folding it into `cleared`, so the
  printed state is never an inference. The live store is never `absent`.

---

## 1. Goal and acceptance criteria

Goal: a halt on family X blocks X only. The legacy un-keyed value blocks only
`pm_us_crh_v4`, and only while its bytes match the pin. Any other legacy value blocks every
family.

1. **AC-1 (per-family writes).** `record_duplicate_fill`, `record_ambiguous_exit` and
   `record_policy_halt` (the policy halt also covers the fee-drift DISAGREE path through
   `app/trade.py:365-373`) write only `continuous_rung_hold/family_halt/<family_id>`, where
   `<family_id>` is the latch's bound family. No code path writes `continuous_rung_hold/halt`
   except the two clear paths in AC-5 and AC-6.
2. **AC-2 (isolation).** Suppose family A's per-family key is halted, B has no per-family key,
   and the legacy key is absent, CLEARED or pinned. Then every reader (the latch, the
   supervisor self-check, the AUD-07 precondition, the digest and `--status`) reports A halted.
   It reports B not halted, unless B == `pm_us_crh_v4` and the legacy key is pinned.
3. **AC-3 (pinned legacy).** If the legacy bytes hash to
   `5a82b40140618de8d35338c0c9463afb256de37b73729ebbe32ffd8d75b19f28`, then every reader
   reports `pm_us_crh_v4` halted with source `legacy_attributed`. It reports every other family
   unaffected by the legacy key.
4. **AC-4 (unpinned legacy fails closed).** Any other legacy value that is not the CLEARED
   sentinel (a different payload, corrupt bytes, empty bytes, a non-bytes SQL value) makes
   every reader report every family halted, with source `legacy_halts_all`. The node still
   boots (L-48). It logs the state and emits CRITICAL `LEGACY_FAMILY_HALT_UNATTRIBUTABLE`.
5. **AC-5 (v4 clear retires the legacy value).** `breezy-clear-family-halt --family-id
   pm_us_crh_v4` writes an audit record, then CLEARED on the v4 per-family key (if it is
   halted), then CLEARED on the legacy key (if it is pinned). The legacy write is always last.
   v4 reads halted until that last write commits. A rerun after a crash converges.
6. **AC-6 (`--legacy`).** `breezy-clear-family-halt --legacy` refuses when the legacy key is
   absent, CLEARED, or **pinned**. It clears only an unpinned value, and writes its audit
   under the existing `continuous_rung_hold/halt_cleared/` prefix.
7. **AC-7 (CLI input safety).** `--family-id` must match `^[A-Za-z0-9_-]{1,64}$` before any
   filesystem call. The resolved manifest path must be contained under the resolved families
   dir. Only then is `load_family_manifest` called. The manifest must have
   `family_id == arg` and `composition_kind == "continuous_rung_hold"`. A value that fails any
   check is REFUSED with no filesystem access beyond the check that failed.
8. **AC-8 (`--status`).** `--status --family-id X` on either CLI is a lock-free `mode=ro`
   read. It succeeds while the node holds the flock and prints `family_id= halted= source=
   legacy=`. The store bytes are identical before and after it runs.
9. **AC-9 (no deploy-time write).** EDGE-3 writes nothing at merge, at supervisor restart or
   at node boot. The live store is byte-identical before and after the first new-code boot.
10. **AC-10 (observability).** A boot line `family_halt_state family_id= halted= source=
    legacy=` is logged before strategy composition. The never-arm line names the family id and
    source. `FAMILY_HALT_AT_START_POSITION`, `SelfCheckResult` and `AlertDetail` are
    unchanged. The self-check line gains `continuous_family_halt_source=`.
11. **AC-11 (gates).** `scripts/ci/run_tests_no_egress.sh` passes in full, and `lint-imports`
    passes. No safety, contract or egress test is deleted or weakened. Every pin that read
    the old key is re-pointed so that it cannot pass vacuously (R4).

## 2. Evidence and root cause (file:line, verified 2026-09-27)

- Key literal: `trial_day_latch.py:293` `FAMILY_HALT_KEY = "continuous_rung_hold/halt"`. The
  comment at :280-291 assumes a "GLOBAL-equivalent" halt under cardinality-1. Sentinel:
  `_HALT_CLEARED_MARKER` :303. One-arg decoder: `decode_family_halt` :306-319, which returns
  `raw is not None and raw != CLEARED`.
- Writers: `record_duplicate_fill` :923-933, `record_ambiguous_exit` :1007-1018,
  `record_policy_halt` :1042-1053. Reader: `is_family_halted` :1080. Clear:
  `clear_family_halt` :1096-1145. The latch has no family id (`__init__` :615-638,
  `open_trial_day_latch` :1426-1443).
- Runtime duplicate: `trade_supervisor_core.py:207` `CONTINUOUS_FAMILY_HALT_KEY`.
  `continuous_family_halt_key` :226-242 discards its argument. Decoder: `continuous_family_is_halted`
  :456. Supervisor reader: `trade_supervisor.py:437-457` (lock-free `SqliteStateStore`). AUD-07:
  `exit_control_precondition.py:72`.
- Digest: `decision_funnel_daily_digest.py:60` imports the strategy decoder. The
  `mode=ro` read is at :115-168. Signature: `read_family_halt_status(store_path)`. The
  wrapper `deploy/systemd/decision-funnel-digest-run.sh` passes `--store-path` only.
- Boot: `app/trade.py:470-471` opens the store and flock (held for the process lifetime).
  :504-520 build `cont_factory` and `family_halt_latch`, neither of them bound to a family.
  `_FAMILIES_DIR = Path("deploy/families")` is at :97.
- Never-arm: `continuous_strategy.py:879-886`. Its tests are in
  `tests/unit/test_continuous_rung_hold_fill_wiring.py`.
- **Live store, read-only (2026-09-27):** exactly one halt key, `continuous_rung_hold/halt`,
  259 bytes, sha256 `5a82b40140618de8d35338c0c9463afb256de37b73729ebbe32ffd8d75b19f28`. There
  are zero `halt_cleared/*` keys and zero `family_halt/*` keys. This is the only legacy halt ever
  written, and it is A1's halt on v4 (AUD-02b note §2, Ruling A1 §4).
- **Ruling-3 contradiction: the code is true.** `set_family_halt_cli.py:424-431` enters
  `open_submit_intent_latch` before it reads `args.status`. `SubmitIntentLockHeld` is caught at
  :484-490 and prints "the node holds the lock; refused". The lock is
  `<store>.intent.lock` (`submit_intent.py:558`), so a MATCHing store path means the same lock.
  The only CLI commit is `e837511` (09-21), so the code at 09-25T03:15Z was this code.
  `breezy-trade-20260924T201520Z.log` shows that node running until `DISPOSED` at
  2026-09-25T05:17:47Z. At 03:15:30Z it held the flock. `--status` could not have printed
  `store_path=MATCH halted=True` then. **`AUD-02b_halt_deployment_2026-09-25.md:18` ("Live
  node holds the latch; --status reached the store in read-only mode") is false.** The line
  it quotes was not produced by the CLI on that path. The halt itself stands: §2 of the same
  note decodes the stored payload, and 2026-09-27's read-only sha matches. r2 makes the note's
  claimed behaviour real (AC-8) and adds a one-line erratum to the AUD-02b note (§5 item 15).
- Manifest loader: `persistence/family_manifest.py:234` calls
  `assert_prereg_directory_eligible(path.parent)` and `path.read_bytes()` on whatever path it
  is given. That is why containment must precede it.

Root cause: the halt was scoped by composition kind on a cardinality-1 assumption. Ruling A1
halts one family and requires a re-arm through a fresh family (§7 item 4). Under today's key,
that fresh family inherits v4's halt.

## 3. Options and trade-offs

| Decision | Chosen | Rejected, and why |
|---|---|---|
| O1: moving the legacy halt | **Read-time attribution, no writes** | Boot migration (r1): the flock, crash-ordering, read-back and sentinel machinery bought nothing that a read does not. Lazy migration inside the veto: this would make the submit chokepoint a writer. |
| O2: attribution | **Pinned `(family_id="pm_us_crh_v4", sha256=<64 hex>)`** | Attributing to the booting family: a fresh family would inherit A1. Fanning out to all families: defeats EDGE-3. |
| O3: legacy end state after a v4 clear | **CLEARED (the existing sentinel)** | Leaving it pinned forever: v4 could never be cleared. |
| O4: key namespace | **`continuous_rung_hold/family_halt/<id>`** | `…/halt/<id>` nests under the legacy key and shares a prefix with `halt_cleared/`. |
| O5: unbound latch calls a halt method | **Raise `TrialDayLatchError`** | Reading "halt-all": this hides a wiring bug. |
| O6: `--status` | **Lock-free `mode=ro`** | Flock-guarded (today): useless while live, which is exactly when an operator asks. A lock-free reader is the proven digest/supervisor pattern. |
| O7: unpinned legacy at boot | **Boot halted, alert CRITICAL** (L-48) | Refusing to boot: the resolver and recorder would stop, which is the L-48 deadlock shape. |
| O8: constant rename | **`FAMILY_HALT_KEY` → `LEGACY_FAMILY_HALT_KEY`, no alias** | Keeping the name: about 20 tests assert `store.get(FAMILY_HALT_KEY) is None` after a refusal. Once writers move to per-family keys, those would pass vacuously. A loud import break forces each one to be re-pointed (R4). |

## 4. Architecture and data flow

### 4.1 Constants (strategy canonical; runtime duplicates, pinned by test 26)
```
trial_day_latch.py                                   trade_supervisor_core.py (runtime, no strategy import)
LEGACY_FAMILY_HALT_KEY  = "continuous_rung_hold/halt"          CONTINUOUS_LEGACY_FAMILY_HALT_KEY
FAMILY_HALT_KEY_PREFIX  = "continuous_rung_hold/family_halt/"  CONTINUOUS_FAMILY_HALT_KEY_PREFIX
FAMILY_HALT_CLEARED_KEY_PREFIX = "continuous_rung_hold/family_halt_cleared/"  (<id>/<ts_ns>)
_HALT_CLEARED_MARKER (unchanged)                               CONTINUOUS_FAMILY_HALT_CLEARED_MARKER
LEGACY_HALT_ATTRIBUTED_FAMILY_ID = "pm_us_crh_v4"              CONTINUOUS_LEGACY_HALT_ATTRIBUTED_FAMILY_ID
LEGACY_HALT_PINNED_SHA256 =                                    CONTINUOUS_LEGACY_HALT_PINNED_SHA256
  "5a82b40140618de8d35338c0c9463afb256de37b73729ebbe32ffd8d75b19f28"
FAMILY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")      CONTINUOUS_FAMILY_ID_PATTERN
family_halt_key(family_id) -> str   # fullmatch or raise ValueError
```

### 4.2 Pure decode (single source of truth; no I/O)
```
classify_legacy(raw) -> "absent" | "cleared" | "attributable_to_v4" | "halts_all"
  None -> absent; == CLEARED -> cleared; sha256(raw) == PIN -> attributable_to_v4; else -> halts_all
decode_family_halt_state(family_id, legacy_raw, family_raw) -> FamilyHaltReading(halted, source, legacy)
  legacy = classify_legacy(legacy_raw)
  if legacy == "halts_all":                                   source = "legacy_halts_all"
  elif family_raw is not None and family_raw != CLEARED:      source = "per_family"
  elif legacy == "attributable_to_v4" and family_id == V4:    source = "legacy_attributed"
  else:                                                       source = "none"
  halted = source != "none"
```
The runtime copy `continuous_family_halt_state(family_id, legacy_raw, family_raw)` has the
same table. Test 26 runs both over the full cross-product: {absent, CLEARED, pinned bytes,
pinned bytes ±1 byte, `{"v":1}`, `b""`, corrupt} × {absent, CLEARED, halted} × {v4, fresh}.
The one-arg `decode_family_halt` is removed. Its only non-latch caller is the digest.

Consistency: a reader does two point reads (or, in the digest and `--status`, one
`SELECT key, value FROM state WHERE key IN (?, ?)`). Races only matter against the clear
paths. §4.3 orders every clear so that each intermediate state still reads halted.

### 4.3 Writes (all under the flock, node down, operator-invoked)
| Path | Write order | Crash at any point |
|---|---|---|
| `record_*` on a family-bound latch | per-family key only (first-cause-wins on the per-family raw value; payload gains `"familyId"`) | single write |
| clear `--family-id X` (X ≠ v4) | refuse if `legacy == halts_all`; refuse if X is not halted. Then audit `family_halt_cleared/X/<ts>` → per-family CLEARED | X halted until the last write |
| clear `--family-id pm_us_crh_v4` | refuse if `legacy == halts_all`; refuse if not halted. Then audit (with `legacySha256` when legacy is pinned) → per-family CLEARED if halted → **legacy CLEARED if pinned (last)** | v4 is halted through the per-family key or the pinned legacy until the last write. A rerun sees `legacy_attributed` and finishes. |
| clear `--legacy` | refuse unless `legacy == halts_all`. Then audit `halt_cleared/<ts>` → legacy CLEARED | single effective write |

### 4.4 No-unset-window proof (re-derived)
EDGE-3 performs no deploy-time, boot-time or supervisor-time write (AC-9). At every point in
the rollout the live store holds exactly today's bytes: the pinned legacy value. Each reader
generation reads those bytes as follows:

- old node, old supervisor and old digest: the legacy key is present and not CLEARED, so
  every family is halted;
- new code: `attributable_to_v4`, so v4 is halted.

v4 is the only family the node can boot (`BREEZY_SENDING_FAMILY_ID`). So v4 reads halted
under every mix of old and new processes. The only writes that can un-halt v4 are the
operator's v4 clear (§4.3, last-write ordered) after a new A1-class ruling, and nothing else.
QED.

### 4.5 Readers
- Latch: `family_halt_state()` reads the legacy key, then `family_halt_key(self._family_id)`.
  `is_family_halted()` returns `.halted`. The submit veto (`composition.family_halt_submit_veto`)
  and the exit veto (`exit_wiring.py:270`) are unchanged, because both call `is_family_halted()`
  on the bound latch.
- Boot (`app/trade.py`, inside the continuous branch after `open_submit_intent_latch`, before
  `make_trial_day_latch_factory`): the latch is opened bound to `manifest.family_id`, and the
  boot asserts `manifest.family_id == settings.sending_family_id` (SettingsError →
  EXIT_CONFIG_ERROR). It logs `family_halt_state …`. If `legacy == halts_all`, it emits CRITICAL
  `LEGACY_FAMILY_HALT_UNATTRIBUTABLE` on every boot and continues. It writes nothing.
- Never-arm (`continuous_strategy.py:879`): `continuous_rung_hold: family halt is set
  (family_id=%s source=%s); never arming`.
- Supervisor `read_continuous_family_store_state(store_path, sending_family_id)`: legacy, then
  per-family, then the runtime decode. `ContinuousFamilyStoreState.family_halt_source` is
  added. The self-check result enum is unchanged.
- AUD-07: the verdict comes via the same runtime decode, with the per-family `halt_key`.
- Digest and `--status`: one shared strategy helper, `read_family_halt_rows_readonly(store_path,
  family_id, *, busy_timeout_s, connect) -> (legacy_raw, family_raw)`, opens
  `file:<path>?mode=ro` with one `IN (?, ?)` select. It raises `sqlite3.Error`/`OSError`
  and a typed `MalformedHaltValue` on non-bytes. The digest maps those to `unknown`, and the
  CLI maps them to REFUSED.

### 4.6 Clearing paths (L-48)
| Latch state | Who clears | Process | Test |
|---|---|---|---|
| per-family X (X ≠ v4) | operator | `breezy-clear-family-halt --family-id X`, node down | 11 |
| v4 (pinned legacy and/or per-family) | operator, **only after a new A1-class ruling** | `… --family-id pm_us_crh_v4`, node down | 9, 10 |
| legacy, unpinned (halts all) | operator, with evidence, or a new peer-reviewed pin | `… --legacy`, node down | 13 |

None of these depends on an armed strategy, so each can run while the latch is closed and
across a day boundary.

## 5. File-by-file plan

Strategy layer
1. `src/breezy/strategy/current_rung_hold/trial_day_latch.py` (~+180/−40):
   - The §4.1 constants plus `family_halt_key`, `classify_legacy`, `FamilyHaltReading` and
     `decode_family_halt_state`.
   - Remove `decode_family_halt`. Rename to `LEGACY_FAMILY_HALT_KEY` (no alias). Update `__all__`.
   - `TrialDayLatch.__init__` and `open_trial_day_latch` take the keyword
     `family_id: str | None = None`, validated through `family_halt_key`. When it is unbound,
     every halt method raises.
   - Writers write per-family and add `familyId`.
   - `family_halt_state()`, `clear_family_halt()` (§4.3 order) and
     `clear_legacy_family_halt(*, reason, evidence_sha256, ts_ns)` (refuses on a pin).
   - `read_family_halt_rows_readonly()` and `MalformedHaltValue`.
   - Rewrite the :276-291 comment.
2. `composition.py:198-214` `make_trial_day_latch_factory(…, family_id=None)`.
3. `continuous_strategy.py:879-886`: the never-arm line reads `family_halt_state()` once.
4. `set_family_halt_cli.py`: add `--family-id` (required, including with `--status`) and
   `--families-dir` (default `deploy/families`). Add `_resolve_family(arg, families_dir)`:
   regex → `(families_dir / f"{arg}.json").resolve()` →
   `is_relative_to(families_dir.resolve())` → `load_family_manifest` → id and kind checks.
   `--status` moves before `open_submit_intent_latch` and uses the read-only helper.
   "Already halted" now means `family_halt_state().halted`. The positions GET is unchanged.
   The alert detail gains `family_id=`.
5. `clear_family_halt_cli.py`: `--family-id` and `--legacy` in a required argparse
   mutually-exclusive group, the same `_resolve_family`, and a lock-free `--status`. The
   docstring is de-`pm_us_crh_cont`-ed. `_resolve_family` lives once, in a small shared
   module `current_rung_hold/family_id_arg.py`, so the two CLIs cannot drift.
6. `exit_wiring.py`: no change.

App layer
7. `src/breezy/app/trade.py` (continuous branch, ~+30): bind `family_id` on `cont_factory` and
   `family_halt_latch`, add the mismatch assert, the boot `family_halt_state` line, and the
   CRITICAL alert on `halts_all`. The v2 branch is unchanged (it never reads the halt).

Runtime layer (literals only)
8. `trade_supervisor_core.py`: the §4.1 duplicates. `continuous_family_halt_key(id)` returns
   prefix + validated id, and `continuous_family_halt_state(...)` is added.
   `continuous_family_is_halted` is removed. Enums are untouched.
9. `trade_supervisor.py:437-457`: two reads, the source field, and the self-check line token.
10. `exit_control_precondition.py:72`: per-family `halt_key` and the new decode.

Scripts and deploy (**slice S2c, sized honestly**)
11. `scripts/analysis/decision_funnel_daily_digest.py` (~150-200 LOC changed):
    - `read_family_halt_status(store_path, family_id, …)` gains a positional `family_id` and
      uses the shared read-only helper (the `mode=ro` connect, `busy_timeout` and
      malformed-value handling move into it).
    - `FamilyHaltStatus` gains `family_id` and `source`.
    - `--family-id` is added to `_parse_args`. `_resolve_halt_status` falls back to
      `BREEZY_SENDING_FAMILY_ID` and returns `unknown` ("no family id") if neither is set.
    - An invalid id is `unknown`, never `no`.
    - `_artefact` and `_missing_tape_artefact` gain `halt_family_id`, `halt_source` and
      `halt_legacy` (additive).
    - `format_digest_detail` (:389-480) gains an optional `halt_family=` token in the
      droppable tier, and `halt=` stays a fixed short token. The tier-length tests are updated.
    - The module docstring (:20-30) is rewritten.
    - Existing tests: the 8 `read_family_halt_status(` call sites and `_store_with_halt_value`
      (:458-466) in `test_decision_funnel_daily_digest.py` (51 tests, 78 halt lines) are
      re-pointed. A legacy-seeding case keeps its `yes` assertion, because pinned or corrupt
      legacy bytes still read halted for v4. `test_f2_writer_to_digest_integration_2026_09_25.py`
      is checked for halt assumptions.
12. `deploy/systemd/decision-funnel-digest-run.sh` (~+30): a
    `resolve_sending_family_id` function, copied verbatim from `replay-daily-run.sh:110-127`
    (`$SYSTEMCTL --user show breezy-trade-supervisor.service --property=Environment`, the
    sed/tr extraction, quote strip, and `case *[!A-Za-z0-9_-]*`). On success it passes
    `--family-id "$id"`. When the id is absent or invalid it omits the flag and logs, so the
    digest reports `unknown`. A systemctl failure → `SKIPPED-INFRA`, exit 75 (same as today's
    lock-infra failures). `BREEZY_SYSTEMCTL` is injectable for tests. Extend
    `tests/unit/test_analysis_units_serialized.py` only if it pins the wrapper's argv.
13. `scripts/analysis/current_rung_hold_paper_replay.py:781-792`: bind
    `family_id=manifest.family_id`, or `"paper_replay"` when there is no manifest. The store is
    private.

Fixtures and docs
14. `tests/fixtures/family_halt/legacy_v4_halt_2026-09-24.bin`: the verbatim 259 bytes,
    captured with a `mode=ro` open at build time (L-42; no secret: reason text plus an
    evidence hash). Re-verify the sha and the length before committing. On a mismatch, STOP.
15. `docs/evidence/AUD-02b_halt_deployment_2026-09-25.md`: an appended erratum paragraph
    (the :18 claim is false per §2; the halt state is independently confirmed). Also a
    `docs/core/PROGRESS.md` row, and the runbook CLI-args note if a family-halt runbook exists.

Existing pins re-pointed (never loosened; each assertion stays non-vacuous)
- `test_set_family_halt_cli.py` (about 16 `store.get(FAMILY_HALT_KEY) is None` sites, and the
  :894-930 AST reader-set scan): assert that BOTH the legacy key and `family_halt_key(<id>)`
  are unchanged. The AST scan tracks `LEGACY_FAMILY_HALT_KEY`, `FAMILY_HALT_KEY_PREFIX` and
  `family_halt_key`.
- `tests/contract/test_reconciliation_durable_reports_contract.py:1146,1182`: assert that no
  key under `continuous_rung_hold/family_halt/` and not the legacy key is written. This is a
  contract test, so the assertion widens to cover both keys and never narrows.
- `test_trade_supervisor_cont_self_check.py:245,326,346,508-545,645-647`,
  `test_aud07_exit_control_halt_precondition.py:107-139`, `test_clear_family_halt_cli.py:79-235`,
  `test_current_rung_hold_trial_day_latch.py:750,911,935`,
  `test_continuous_rung_hold_fill_wiring.py:48,176,238,1608`: re-seed through the real writers
  on a bound latch, or with the fixture bytes. Literal pins keep the identical literal.

## 6. Test strategy (RED first; 28 new tests; all through `scripts/ci/run_tests_no_egress.sh`)

### 6.1 `tests/unit/test_edge3_per_family_halt.py` (latch and decode; real writers or fixture bytes only, L-42)
1. `test_every_halt_writer_writes_only_its_per_family_key` (parametrised over the 3 writers; r1 1+2)
2. `test_halt_on_family_a_does_not_halt_family_b` (r1 3)
3. `test_unpinned_legacy_value_halts_every_family` (fixture ±1 byte, `{"v":1}`, `b""`, corrupt; r1 4)
4. `test_pinned_legacy_bytes_halt_v4_only`
5. `test_absent_or_cleared_legacy_halts_no_family`
6. `test_fixture_bytes_hash_to_the_full_64_hex_pin_and_are_259_bytes`
7. `test_family_halt_key_rejects_empty_dotdot_slash_tilde_caret_colon_nul_newline_and_65_char_ids`
8. `test_unbound_latch_raises_on_every_halt_method`
9. `test_clear_v4_writes_audit_then_per_family_then_legacy_last_and_leaves_other_families`
10. `test_clear_v4_interrupted_before_the_legacy_write_leaves_v4_halted_and_rerun_converges`
11. `test_clear_non_v4_family_never_touches_the_pinned_legacy_value`
12. `test_clear_family_refuses_while_legacy_halts_all_and_writes_nothing` (r1 32)
13. `test_clear_legacy_refuses_absent_cleared_and_pinned_and_clears_only_unpinned` (security's `--legacy` re-check)
14. `test_pre_edge3_one_arg_decoder_ignores_per_family_keys`: the removed rule `raw is not
    None and raw != CLEARED` is restated as a local function over `store.get(LEGACY)`. The test
    shows that a store with only a per-family halt reads "not halted" to old code. This pins
    the rollback hazard behind §8.4.

### 6.2 `tests/unit/test_app_trade_family_halt_binding.py` (boot harness)
It imports `RecordingNode`, `_operator_order_ceiling`, `_trade_env` and `_write_today_catalog`
from `tests.unit.test_trade_cli_current_rung_hold` (the pattern in
`test_app_trade_fee_drift_probe_wiring.py:58-63`), with `_v4_env`/`_continuous_env` builders as
at :93-120. The store is seeded before `run()` through `SqliteStateStore(env[
"POLYMARKET_US_EXEC_STATE_DB"])` with fixture bytes, or through a real writer on a bound latch.

**Before composition:** patch `breezy.app.trade.make_trial_day_latch_factory` and
`open_trial_day_latch` with spies that call through, record `family_id`, and read
`family_halt_state()` on the returned latch at call time. The spies run inside the held flock
(the `_spy` pattern at `test_trade_cli_current_rung_hold.py:381-386`) and before
`build_*_strategies`. The boot log line is captured with `caplog`, and its position is
asserted against the first `add_strategy` in `RecordingNode.calls`.

**In the latch window:** a `run()` override, as at :388-406 (the flock is released when
`run()` returns). Confirmed feasible: that test already reads `trial._store` and `trial._lock`
from `strategy._latch_factory()` inside `run()`, and fee-drift test :216 reads the veto there.

15. `test_boot_binds_cont_factory_and_veto_latch_to_the_manifest_family_id`
16. `test_boot_refuses_when_manifest_family_id_differs_from_sending_family_id`
17. `test_v4_boot_with_pinned_legacy_reads_halted_before_composition_and_writes_nothing` (full `state`-table snapshot is equal before and after; AC-9)
18. `test_fresh_family_boots_unhalted_while_the_pinned_legacy_stays_in_place` (r1 24; a third registered continuous manifest is written into a tmp families dir)
19. `test_boot_with_unpinned_legacy_boots_halted_alerts_critical_and_exits_ok` (L-48; ruling 8)
20. `test_never_arm_log_names_family_id_and_source` (in `test_continuous_rung_hold_fill_wiring.py`, beside the existing `family_halt_at_start` assertions)

### 6.3 CLIs (extend `test_set_family_halt_cli.py` and `test_clear_family_halt_cli.py`)
21. `test_set_refuses_family_id_containing_path_traversal_before_touching_the_filesystem`
    (parametrised `../x`, `a/b`, `/etc/passwd`, `..`, `x\x00`, 65 chars). It patches
    `load_family_manifest`, `Path.resolve` and `SqliteStateStore` to fail if called. It
    asserts REFUSED and that a sentinel file outside the families dir is never read.
22. `test_set_and_clear_refuse_unknown_non_continuous_mismatched_or_escaping_family_id`
    (includes a symlink inside `families/` that points outside → containment refusal; clear's
    `--family-id`/`--legacy` group is required and mutually exclusive)
23. `test_set_on_fresh_family_writes_only_its_key_while_v4_stays_halted`
24. `test_status_is_lock_free_read_only_while_the_flock_is_held_and_reports_legacy_state`
    (holds `open_submit_intent_latch` in the test; parametrised over the four legacy classes;
    the store is byte-identical afterwards)
25. The existing `test_refuses_while_the_node_holds_the_lock` tests (set and clear) stay, with
    argv `+ --family-id`, for the write paths. This is not counted as new.

### 6.4 Runtime, AUD-07, digest
26. `test_runtime_and_strategy_halt_constants_and_decoders_agree_on_the_full_cross_product`
    (r1 34+35: key, prefix, CLEARED, pinned sha, attributed family id and the regex are
    equal; the decode tables are equal; the digest's decoder `is` the strategy's)
27. `test_self_check_and_aud07_are_per_family_and_block_every_family_on_unpinned_legacy` (r1 36+38)
28. `test_digest_reports_family_source_legacy_and_unknown_without_or_with_invalid_family_id_never_no` (r1 39+40)

The count is 28 new tests (1-24 and 26-28 is 27, plus the wrapper test below).
- `test_digest_wrapper_passes_the_validated_supervisor_family_id_and_omits_an_invalid_one`
  (in a new `tests/unit/test_decision_funnel_digest_wrapper.py`, modelled on
  `test_replay_daily_wrapper.py`, with `BREEZY_SYSTEMCTL` stubbed).

Edge paths covered: corrupt, empty, non-bytes and near-miss-sha legacy values; a crash
between clear writes; a family id with a separator, traversal, NUL, symlink or overlong
value; an unbound latch; a manifest mismatch; a digest with no or an invalid id; an
unattributable boot; `--legacy` on pinned bytes; `--status` under a held flock; the old
decoder after a revert.

## 7. Execution order and parallelism

- **S1 (root, sequential):** trial_day_latch, composition, fixture, and tests 1-14.
  `lint-imports`.
- **S2 (parallel after S1; disjoint files):**
  - S2a: runtime core, supervisor, AUD-07, tests 26-27, and the re-pointed runtime pins.
    `lint-imports`.
  - S2b: both CLIs plus `family_id_arg.py`, tests 21-24, and the re-pointed CLI pins.
  - S2c: digest, wrapper, paper replay, test 28, the wrapper test, and the re-pointed digest
    tests (the largest slice after S1).
- **S3 (after S2):** `app/trade.py`, the `continuous_strategy` line, tests 15-20, and the
  contract-test re-point.
- **S4:** full gate after each merge (L-43). Worktree env: `PYTHONPATH=<wt>/src`,
  `BREEZY_PYTHON=/home/jon/breezy/.venv/bin/python`, basetemp `/home/jon/.cache/breezy-gate/`.
  Never `uv`/`pip`. Before merge, sweep with `/usr/bin/grep -rn 'continuous_rung_hold/halt"'`
  over src, scripts, deploy and docs/runbooks, with a positive control.
- Reviews: python-reviewer, security-reviewer and trading-bot-architect. No implementer
  reviews its own slice.

## 8. Deploy and verification

1. Pre-merge: a read-only `mode=ro` read confirms the legacy sha (64 hex) and 259 bytes, zero
   `halt_cleared/*` keys and zero `family_halt/*` keys. On a mismatch, STOP (§4.4 no longer
   holds as proven).
2. Merge (editable install): the CLIs and digest are live at once. The supervisor goes live
   at its next restart (01:00-16:40Z window, FU-17 procedure). The node goes live at its next
   respawn. Nothing is killed, and nothing is written (§4.4).
3. Proof it is live:
   - (a) the node log file (Popen stdout, not journald) on the first new-code boot has
     `family_halt_state family_id=pm_us_crh_v4 halted=True source=legacy_attributed
     legacy=attributable_to_v4`;
   - (b) the node log has `family halt is set (family_id=pm_us_crh_v4
     source=legacy_attributed); never arming` and `FAMILY_HALT_AT_START_POSITION` per station
     (09-24 baseline);
   - (c) no `LEGACY_FAMILY_HALT_UNATTRIBUTABLE` alert;
   - (d) the first self-check after the supervisor restart shows
     `continuous_family_halt_source=legacy_attributed`, and the result string equals the
     pre-deploy baseline;
   - (e) the next 09:20Z digest artefact has `halt_enforced: yes`, `halt_family_id:
     pm_us_crh_v4`, `halt_source: legacy_attributed`;
   - (f) `breezy-set-family-halt --family-id pm_us_crh_v4 --status` **while the node is live**
     prints `halted=True source=legacy_attributed legacy=attributable_to_v4`;
   - (g) a `mode=ro` re-read shows the legacy sha unchanged and zero `family_halt/*` keys;
   - (h) zero orders.
4. **Pre-revert procedure (rollback hazard).** Old code reads only the legacy key, so after a
   revert any per-family halt becomes invisible. Before reverting:
   - (i) `mode=ro`: list `continuous_rung_hold/family_halt/*` with their states, and
     classify the legacy key.
   - (ii) If the legacy key is `attributable_to_v4` or `halts_all`, old code over-halts all
     families. Revert freely.
   - (iii) Otherwise (legacy is CLEARED or absent) and **any** per-family key is halted
     (including v4 re-halted after a clear): revert with the node down. Re-set the global
     halt with the old CLI (`breezy-set-family-halt --reason … --evidence-path …`, node down,
     flock), and confirm with a `mode=ro` read that the legacy key is non-CLEARED BEFORE the
     node respawns.
   - (iv) If the old CLI refuses on its pre-set open-position check, do NOT relaunch on old
     code. Roll forward instead. Test 14 pins why this is needed.

## 9. Risk register

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R1 | v4 reads unhalted during a clear | L | CRIT | The legacy write is last. Tests 9 and 10. Clear is operator-only and gated by A1. |
| R2 | Wrong attribution | L | HIGH | Full 64-hex pin, test 6, pre-merge re-read. A near-miss value halts all (test 3). |
| R3 | Unbound continuous latch | M | HIGH | The latch raises (test 8). Boot wiring test 15. |
| R4 | Re-pointed pins pass vacuously | M | HIGH | The rename has no alias. Each "nothing written" pin asserts both keys (§5). Review checklist item. |
| R5 | Path traversal or symlink via `--family-id` | L | HIGH | Regex before join, resolve + containment before load (tests 21, 22). |
| R6 | **Family-id reuse inherits a retired id's halt** | L | MED | A retired id's per-family halt (or, for the literal `pm_us_crh_v4`, the pinned legacy halt) is inherited by any new manifest that reuses that id. The failure is fail-closed (over-halt). The registry convention is a fresh id per revision (A1 §7 item 4), and `--status` shows the inherited source. Reusing an id is a registry-review defect. |
| R7 | Rollback hides per-family halts | M | HIGH | §8.4 procedure, test 14. |
| R8 | Unpinned legacy value at boot | L | HIGH | Boots halted, CRITICAL every boot, never refuses (L-48). Test 19. |
| R9 | The digest regresses to `unknown` | L | LOW | The wrapper resolves the id. `unknown` is never `no`. |
| R10 | A lock-free `--status` sees a torn state mid-clear | L | LOW | A single `IN` select is one snapshot. Clear only runs with the node down. |
| R11 | Missed supervisor restart | M | LOW | The old supervisor over-reports halted. Deploy step 3(d). |

## 10. LESSONS and invariant compliance

- Nautilus is immutable: no Nautilus class is touched. The null hypothesis was checked:
  `RiskEngine.TradingState` is node-wide and in-memory, and `CacheConfig(database=None)` gives
  no durable per-strategy halt.
- `allow_short`, the caps and live-trading enablement are untouched. **The A1 halt stays SET.**
  EDGE-3 writes nothing to it. `--legacy` refuses its bytes. Only an operator v4 clear after a
  new A1-class ruling retires it.
- No safety, contract or egress test is deleted or weakened. The contract pin widens to
  assert both keys. The `SelfCheckResult`/`AlertDetail` exact sets are not widened. The one
  new alert event is free-form `emit_alert`.
- L-42: fixtures come from real writers or the verbatim fixture bytes. L-43: full gate after
  every merge. L-48: the clearing-path table is in §4.6, and the node boots halted, never
  refuses.
- Flock: writes happen only under the flock. New lock-free readers (`--status`) are
  `mode=ro`. Layers: runtime duplicates literals, and `lint-imports` runs after S1, S2a and S3.
- NO-SEND firewall: no new egress. `--status` makes no positions GET.
- Tilde memory: the id regex excludes `~ ^ : / .`.

## 11. Dependencies on other EDGE items
- None hard. Any EDGE item that boots a fresh continuous family, or sets or clears a family
  halt, lands after EDGE-3.
- Any fee-drift UNKNOWN→halt change writes per-family through `record_policy_halt` at no
  extra cost.
- EDGE-5's re-arm roadmap relies on AC-2 and AC-3 so that a fresh manifest is not blocked by
  v4's A1 halt.

## 12. Confidence and unknowns

Confidence: **0.9** (r1: 0.85). The migration surface, which was r1's largest risk, is gone.

- U1. The live legacy bytes stay unchanged until merge (pre-merge step 1).
- U2. Whether `test_analysis_units_serialized.py` pins the digest wrapper's argv. This is
  checked at S2c.
- U3. The `format_digest_detail` length tiers may need a second droppable token. This is
  bounded to S2c.
- U4. The coordinator's call on D1 (a third sha literal in the digest) and D2 (`legacy=absent`).

## r2 final amendment (coordinator, round-2 merge). BINDING: overrides anything above that conflicts with it

Round-2 verdicts: security APPROVE; architect APPROVE with one required amendment; python REQUEST_CHANGES (incomplete re-pointing audit). The amendments below close both findings. Status: **READY for implementation**.

- **AM-1 (architect: the rollback respawn window).** In §8.4 step (iii), and in the roll-forward branch (iv), **stop `breezy-trade-supervisor.service` first and keep it stopped** until a `mode=ro` read confirms the legacy key holds a non-CLEARED halt. FU-17 (53d403c) makes the supervisor respawn and retry the node, so an old-code node could otherwise boot during the window in which per-family halts are invisible to it. State plainly that (iv) roll-forward is the LIKELY branch, not an edge case: the old set CLI refuses on `VERDICT_OPEN` or any non-FLAT position (`set_family_halt_cli.py:448-463`), and per-family halts usually come from duplicate fills or ambiguous exits that leave positions open.
- **AM-2 (architect: re-point strength).** Every re-pointed "nothing written" pin uses the same **prefix scan** over `continuous_rung_hold/family_halt/*` as the contract pin (`test_reconciliation_durable_reports_contract.py:1182`). Checking only the legacy key plus `family_halt_key(<id>)` is not enough, because it would pass a write to the wrong family id. The positive pins at `test_current_rung_hold_trial_day_latch.py:750/911` must assert that the per-family key is PRESENT and that the legacy key is ABSENT.
- **AM-3 (python: the complete call-site audit).** An unbound latch raises on every halt method (O5). The audit, done read-only on 2026-09-27, found 13 src/scripts and 118 test construction sites. By class: **A 8, B 34, C 0, D 84.** Implementation slice S0 must handle all class-A and class-B sites before any other slice turns green:
  - **A: production, 8 sites, all must bind the family id.**
    - `composition.py:214` (`make_trial_day_latch_factory` body: add the parameter)
    - `app/trade.py:487` (v2), `:504` (continuous), `:518` (`family_halt_latch`), all bound from `manifest.family_id`
    - `set_family_halt_cli.py:426`, `clear_family_halt_cli.py:108` (bound from the validated `--family-id`)
    - `scripts/analysis/current_rung_hold_paper_replay.py:786` (`_latch_context`: `--family-manifest`, else a named replay test family, never v4 by default)
    - `trial_day_latch.py:1443` (the `open_trial_day_latch` kwarg itself)
  - **B: tests that reach halt methods, 34 sites, must bind v4 or a test family id.**
    - test_aud07_exit_control_halt_precondition.py (98, 116, 152, 167)
    - test_set_family_halt_cli.py (149, 956, 1008)
    - test_clear_family_halt_cli.py (50, 134, 157, 262, 284, 323, 357)
    - test_current_rung_hold_trial_day_latch.py (736, 757, 783, 904, 917, 950, 958)
    - test_current_rung_hold_composition.py (1143, 1175, 1176)
    - test_current_rung_hold_ambiguous_resolver.py (1835, 1890)
    - test_fee_drift_probe.py (440)
    - test_operator_caps_through_the_live_composition.py (341)
    - test_continuous_rung_hold_strategy.py:87 `_cont_latch_factory`, which is shared by 4 importers including the contract test at :1206/:1265, so one fix covers all
    - test_continuous_rung_hold_fill_wiring.py (1671)
    - test_continuous_rung_hold_no_only_hunt_2026_09_24.py (143)
    - test_continuous_rung_hold_diagnostics_hourly.py (66)
    - test_f2_writer_to_digest_integration_2026_09_25.py (72)
    - test_no_leg_composition_2026_09_14.py (120)
    - test_current_rung_hold_paper_replay.py 2389/2432, which are fixed through the A-row for the script
  - **C: 0 today, so the new raise has NO coverage.** Add at least 3 class-C tests: an unbound latch raises on `is_family_halted`, on `record_policy_halt` and on `record_duplicate_fill`, and a veto built from an unbound latch fails CLOSED. It must deny, never allow.
  - **D: 84 sites that never reach a halt method.** Leave them unchanged. The exceptions are `test_current_rung_hold_trial_day_latch.py:676/723`, and those two change only if the `TrialDayLatch(store, lock)` constructor signature changes.
  - The halt readers these sites reach: `continuous_strategy.py:879` (`_run_never_arm_walk`), `:1823` (`_hunt_tick`, unconditional), `:3207` (`record_duplicate_fill`), `exit_wiring.py:132,270`, and `composition.py:250` (the veto). The v2 `CurrentRungHoldStrategy` calls no halt method.
  - Test-count update: 28 new + 3 class-C, plus about 34 class-B bindings, which are edits, not new tests.
