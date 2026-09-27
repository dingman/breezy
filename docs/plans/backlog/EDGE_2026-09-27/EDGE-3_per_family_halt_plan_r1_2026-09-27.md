# EDGE-3 (MED) — Per-family continuous-rung-hold halt — plan r1 (2026-09-27)

Status: PLAN r1. Nothing is implemented. Needs peer review before any build (§2 planning gate).
Scope: key the continuous-rung-hold family halt by family id, migrate the existing
`pm_us_crh_v4` A1 halt without it ever reading as unset, and thread a family id through
the set/clear CLIs, the node boot, the strategy never-arm walk, the submit/exit vetoes,
the supervisor self-check, the AUD-07 exit-control precondition and the AUD-03 digest.

Out of scope: clearing the A1 halt. That stays the operator's act, taken only after a new
A1-class ruling. Also out of scope: lifting cardinality-1 (WP-11b), any change to the fee-drift
probe's UNKNOWN handling, and any change to `allow_short`, caps or live-trading enablement.

---

## 1. Goal and acceptance criteria

Goal: a halt on family X blocks X only. The one exception is the legacy un-keyed halt. While
it exists and is not yet migrated, it halts every family (fail closed).

1. **AC-1 (per-family key).** Every halt writer (`record_duplicate_fill`,
   `record_ambiguous_exit`, `record_policy_halt`, which also covers the fee-drift DISAGREE
   path) writes only `continuous_rung_hold/family_halt/<family_id>`, where `<family_id>` is the
   latch's bound family. None of them writes `continuous_rung_hold/halt` again.
2. **AC-2 (isolation).** If family A's per-family key is halted, the legacy key is absent,
   cleared or MIGRATED, and B has no per-family key, then `is_family_halted()` is True for A
   and False for B. The same holds for the supervisor reader, the AUD-07 precondition and the
   digest.
3. **AC-3 (legacy fails closed).** If the legacy key holds any value other than absent, the
   CLEARED sentinel, or the new MIGRATED sentinel (this includes corrupt bytes), then every
   reader reports halted for every family id.
4. **AC-4 (migration preserves the halt).** After migration, the per-family key for
   `pm_us_crh_v4` holds exactly the legacy bytes. Its sha256 is
   `5a82b40140618de8d35338c0c9463afb256de37b73729ebbe32ffd8d75b19f28` and it is 259 bytes, so
   `reason=policy_halt`, `tsNs=1790268150964821245` (2026-09-24T16:42:30.964821Z), `detail`
   and `evidenceSha256` carry through unchanged. A migration audit record exists. The legacy
   key holds the MIGRATED sentinel.
5. **AC-5 (the halt is never unset).** For every interleaving of the migration's writes with a
   concurrent, lock-free reader (supervisor, digest, AUD-07), and after a crash at any point
   in the migration, every reader reports `pm_us_crh_v4` halted. A reverted build (old
   readers, post-migration store) also reports it halted.
6. **AC-6 (idempotent).** Running the migration N≥2 times, or rerunning it after a crash
   between any two of its writes, converges on the AC-4 end state. It never overwrites an
   existing per-family halt and never writes a second MIGRATED audit once the sentinel is in
   place.
7. **AC-7 (attribution fails closed).** If the legacy bytes do not hash to the pinned sha256,
   the migration writes nothing, the legacy key keeps halting all families, and the boot emits
   a CRITICAL alert `LEGACY_FAMILY_HALT_UNATTRIBUTABLE`.
8. **AC-8 (CLIs).** `breezy-set-family-halt` and `breezy-clear-family-halt` require
   `--family-id <id>`. The id must name a manifest in the families registry with
   `composition_kind == "continuous_rung_hold"`, and its `family_id` must equal the filename
   stem. `breezy-clear-family-halt --legacy` (mutually exclusive with `--family-id`) clears
   only an UNATTRIBUTABLE legacy value. Both CLIs run the migration first, under their own
   flock. `--status` reports `family_id`, `halted`, `source`, and `legacy`.
9. **AC-9 (live, flock intact).** The migration runs inside the trade node's own boot, under
   the flock the node already holds, before any strategy, veto or probe is composed. No new
   process takes, waits on or bypasses the intent flock. The currently running node is not
   stopped. The migration goes live at the next scheduled node respawn.
10. **AC-10 (observability).** The never-arm log line names the family id and the halt source
    (`per_family` or `legacy_unmigrated`). The event name `FAMILY_HALT_AT_START_POSITION` is
    unchanged. The self-check log line gains `continuous_family_halt_source=`. The
    `SelfCheckResult`/`AlertDetail` enums are unchanged.
11. **AC-11 (gates).** `scripts/ci/run_tests_no_egress.sh` passes in full and `lint-imports`
    passes (runtime still never imports strategy). No safety, contract or egress test is
    deleted or weakened.

## 2. Evidence and root cause (file:line, verified 2026-09-27)

- The key is a module-level literal with no family component:
  `src/breezy/strategy/current_rung_hold/trial_day_latch.py:293`
  `FAMILY_HALT_KEY: Final[str] = "continuous_rung_hold/halt"`. The comment at :280-291 states
  the design assumption: cardinality-1 makes the halt "GLOBAL-equivalent", "no matter which
  literal family id currently occupies that slot".
- Writers: `record_duplicate_fill` :923-933, `record_ambiguous_exit` :1007-1018 and
  `record_policy_halt` :1042-1053 all write `FAMILY_HALT_KEY`. All three are first-cause-wins
  through `is_family_halted()`.
- Reader: `is_family_halted` :1080 → `decode_family_halt` :306-319 (present and not equal to
  `_HALT_CLEARED_MARKER` :303). Clear: `clear_family_halt` :1096-1145 writes the audit
  `HALT_CLEARED_KEY_PREFIX` :298 and then the sentinel.
- The latch has no family id: `TrialDayLatch.__init__` :615-638 and `open_trial_day_latch`
  :1426-1443 take only `key_prefix`.
- Runtime duplicate: `src/breezy/runtime/trade_supervisor_core.py:207`
  `CONTINUOUS_FAMILY_HALT_KEY`. `continuous_family_halt_key(sending_family_id)` :226-242
  discards its argument (`del sending_family_id`). The docstring says lifting this "would need
  to widen this function's body". `continuous_family_is_halted` :456-467. The sentinel
  duplicate is at :252.
- Self-check: `trade_supervisor_core.py:672-673` → `FAIL_CONTINUOUS_FAMILY_HALTED`. Its input
  is `read_continuous_family_store_state` (`src/breezy/runtime/trade_supervisor.py:437-457`),
  which uses a fresh lock-free `SqliteStateStore` connection while the node is live.
- AUD-07: `src/breezy/runtime/exit_control_precondition.py:72` uses
  `continuous_family_halt_key`.
- Digest: `scripts/analysis/decision_funnel_daily_digest.py:60,151,167` reads
  `FAMILY_HALT_KEY` through a read-only uri connection. Its wrapper is
  `deploy/systemd/decision-funnel-digest-run.sh`, which passes `--store-path` only.
- Boot: `src/breezy/app/trade.py:470-471` opens the store and intent latch (the flock is held
  for the process lifetime). :504-520 builds `cont_factory` and `family_halt_latch`, both with
  `key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX` and no family id. :365-377 `_set_family_halted`
  (fee-drift probe) → `family_halt_latch.record_policy_halt`.
- Never-arm: `continuous_strategy.py:879-887` logs "family halt is set; never arming" and
  records `_POSITION_FAMILY_HALT_AT_START` (:218). `RefusalAlerter` turns that into
  `FAMILY_HALT_AT_START_POSITION` (`weather_common/refusals.py:153`, `reason.upper()_suffix`).
  AUD-02b evidence lines 84-87 show this event on the 09-24 20:15Z boot.
- CLIs: `set_family_halt_cli.py:424-431` and `clear_family_halt_cli.py:106-112` open the flock
  through `open_submit_intent_latch` and return `SubmitIntentLockHeld` → REFUSED while the node
  is live. Neither takes a family id.
- Other latch constructors: `composition.py:198-214` (`make_trial_day_latch_factory`) and
  `scripts/analysis/current_rung_hold_paper_replay.py:781-792`.
- Store: `src/breezy/runtime/sqlite_store.py:117-176`. It uses WAL. `set` commits before
  returning. There is no delete and no multi-key transaction.
- **Live store state, read-only (`mode=ro`) at 2026-09-27:** exactly one halt-related key,
  `continuous_rung_hold/halt`, is present. It holds `{v:1, reason:policy_halt,
  tsNs:1790268150964821245, detail, evidenceSha256}`, 259 bytes, sha256 `5a82b401…5b19f28`.
  There are zero `continuous_rung_hold/halt_cleared/*` keys, so no halt was ever cleared.
  This value is therefore the only legacy halt ever written, and it is the A1 halt on
  `pm_us_crh_v4`. That attribution is confirmed by
  `docs/evidence/AUD-02b_halt_deployment_2026-09-25.md:37,56` and Ruling A1 §4.
- The registry holds two continuous families: `deploy/families/pm_us_crh_cont.json` and
  `pm_us_crh_v4.json`, both REGISTERED. Ruling A1 §7 item 4 requires a fresh manifest for any
  re-arm, which would be a third continuous family. Under today's key, that family would be
  blocked by v4's halt.

Root cause: the halt was scoped by composition kind (the fixed trial-key prefix) on a
cardinality-1 assumption, not by family. Ruling A1 halts one family on policy grounds and
sets a re-arm path that registers a different family, which breaks that assumption.

## 3. Options and trade-offs

### O1 — Where the migration runs (the flock constraint)
| Option | Verdict |
|---|---|
| (a) **Inside the trade node's boot**, in `app/trade.py::run` right after `open_submit_intent_latch`, under the flock the node already holds | **CHOSEN.** No second flock holder and no lock-free writer. It runs "while live" in the only sense the flock allows: no stop is needed, and it executes at the next scheduled 16:50Z respawn. Each respawn re-runs it idempotently. |
| (b) Standalone CLI that takes the flock | Refuses while the node is live (`SubmitIntentLockHeld`), so it cannot meet the "while live" requirement. Kept as a secondary path: the set/clear CLIs run the same migration first when the node is down. |
| (c) Standalone CLI that writes lock-free while the node is live | **REJECTED.** Breaks the flock discipline, and a lock-free writer could race the node's read-check-write in `record_*` (first-cause-wins). |
| (d) Lazy migration inside `is_family_halted()` | **REJECTED.** Turns the submit-veto chokepoint (`family_halt_submit_veto`, called synchronously before permit spend) into a writer. |

### O2 — Which family the legacy halt belongs to
| Option | Verdict |
|---|---|
| (a) **Pinned attribution** `(family_id="pm_us_crh_v4", legacy_sha256=5a82b401…)` as a committed constant, migrated only on a byte match | **CHOSEN.** Grounded in evidence (§2: the only legacy halt ever written). Any other bytes, such as a halt written later by old code, fail closed (AC-7). |
| (b) Attribute to the booting node's `sending_family_id` | **REJECTED.** If a fresh family were the first to boot on new code, it would inherit v4's A1 halt, and v4's own halt would silently move off v4. |
| (c) Fan out to every registered continuous family | Fails closed, but the fresh family inherits the A1 halt. That defeats EDGE-3, and clearing the copy would look like clearing A1. |
| (d) Never migrate, so the legacy key halts all families forever | Defeats EDGE-3. The only exit would be a clear, which would clear A1. |

### O3 — Legacy key end state
| Option | Verdict |
|---|---|
| (a) **New MIGRATED sentinel** `b'{"v":2,"state":"migrated"}'` | **CHOSEN.** Old-code readers (`decode_family_halt`, `continuous_family_is_halted`) treat any value other than the CLEARED sentinel as halted. A post-migration rollback therefore over-halts, which is safe. New readers recognise it as "no legacy halt". |
| (b) CLEARED sentinel | **REJECTED.** An old supervisor or digest, or a reverted build, would read v4 as not halted. That is the forbidden window, seen from the reader's side. |

### O4 — Per-family value
Verbatim legacy bytes (**CHOSEN**) against a re-serialised JSON with `familyId` added.
Verbatim bytes preserve reason, timestamp and detail by construction, and keep the sha
provable against the pinned constant. Migration provenance goes in a separate audit record.
New writes after EDGE-3 add a `familyId` field to the v1 payload. The field is additive, so
existing decoders ignore it.

### O5 — Key namespace
`continuous_rung_hold/family_halt/<id>` (**CHOSEN**) against `continuous_rung_hold/halt/<id>`.
The latter nests under the legacy key and shares a string prefix with
`continuous_rung_hold/halt_cleared/`, which invites prefix-scan and `LIKE` mistakes.

### O6 — Latch with no family id calling a halt method
It raises `TrialDayLatchError` (**CHOSEN**) rather than reading "halt-all". Every production
continuous latch is bound (§5, pinned by a wiring test). v2 `current_rung_hold` never calls
halt methods. An unbound call is a wiring bug and should surface loudly. If it happens inside
`_hunt_tick`, the raise halts the tick, which is fail closed.

### O7 — Reader consistency without a multi-key transaction
Store-API readers read the **legacy key first, then the per-family key**. The migration
writes the **per-family key first and the MIGRATED sentinel last**. If a reader sees MIGRATED,
the per-family write has already committed (WAL, commit-before-return), so its next read sees
the halt. The digest uses one `SELECT key, value FROM state WHERE key IN (?, ?)` statement,
which gives a single snapshot. This avoids adding a transaction API to `SqliteStateStore`.

## 4. Architecture and data flow

```
constants (trial_day_latch.py, strategy layer)           duplicated literals (trade_supervisor_core.py, runtime)
  LEGACY_FAMILY_HALT_KEY   = "continuous_rung_hold/halt"    CONTINUOUS_LEGACY_FAMILY_HALT_KEY   (pinned ==)
  FAMILY_HALT_KEY_PREFIX   = "continuous_rung_hold/family_halt/"  CONTINUOUS_FAMILY_HALT_KEY_PREFIX (pinned ==)
  _HALT_CLEARED_MARKER     (unchanged)                      CONTINUOUS_FAMILY_HALT_CLEARED_MARKER (pinned ==)
  _LEGACY_HALT_MIGRATED_MARKER = b'{"v":2,"state":"migrated"}'  CONTINUOUS_LEGACY_HALT_MIGRATED_MARKER (pinned ==)
  FAMILY_HALT_CLEARED_KEY_PREFIX = "continuous_rung_hold/family_halt_cleared/"   (<id>/<ts_ns>)
  HALT_MIGRATED_KEY_PREFIX       = "continuous_rung_hold/halt_migrated/"         (<ts_ns>)
  LEGACY_HALT_ATTRIBUTION = LegacyHaltAttribution(family_id="pm_us_crh_v4",
                                                   legacy_sha256="5a82b401...5b19f28")
  family_halt_key(family_id) -> str     # validates ^[A-Za-z0-9_-]{1,64}$ (no ~ ^ : / per L-tilde memory)
```

Pure decode (single source of truth, no I/O):
```
decode_family_halt_state(legacy_raw, family_raw) -> FamilyHaltReading(halted, source)
  legacy_halts_all = legacy_raw not in (None, _HALT_CLEARED_MARKER, _LEGACY_HALT_MIGRATED_MARKER)
  per_family       = family_raw is not None and family_raw != _HALT_CLEARED_MARKER
  source = "legacy_unmigrated" if legacy_halts_all else "per_family" if per_family else "none"
  halted = legacy_halts_all or per_family
```
The runtime duplicate `continuous_family_halt_state(legacy_raw, family_raw)` has the same
table. A parity test checks both against the full cross-product of fixtures.

Migration (method `TrialDayLatch.migrate_legacy_family_halt(*, attribution, now_ns) ->
MigrationOutcome`, requires the held flock and the constructing thread):
```
1. legacy = get(LEGACY)                        -> None/CLEARED/MIGRATED => NOOP_* (no write)
2. sha256(legacy) != attribution.legacy_sha256  => UNATTRIBUTABLE (no write; caller alerts CRITICAL)
3. target = family_halt_key(attribution.family_id); cur = get(target)
   cur is None or cur == CLEARED               => set(target, legacy)        # verbatim bytes; fail closed
   else                                        => leave cur (first cause wins)
4. set(HALT_MIGRATED_KEY_PREFIX+now_ns, {v:1, familyId, legacySha256, legacyRawHex, migratedAtNs})
5. read back: decode_family_halt_state(None, get(target)).halted must be True, else raise TrialDayLatchError
   (the sentinel is NOT written; legacy keeps halting all)
6. set(LEGACY, _LEGACY_HALT_MIGRATED_MARKER)                                  # last write
-> MIGRATED
```
Crash analysis: a crash before 3 leaves nothing changed. A crash between 3 and 6 leaves both
keys set: the legacy key halts all and the per-family key halts v4. A rerun then skips the
write at 3 (cur is a halt), writes a second audit at 4 (harmless: each audit is keyed by
ts_ns), and completes 6. After 6, reruns are NOOP_ALREADY_MIGRATED with no audit. v4 is
halted in every state.

Readers:
- `TrialDayLatch.is_family_halted()` → `self.family_halt_state().halted`.
  `family_halt_state()` reads the legacy key, then `family_halt_key(self._family_id)`.
- Submit veto (`composition.family_halt_submit_veto`) and exit veto
  (`exit_wiring.py:270`) need no code change. They call `is_family_halted()` on a
  family-bound latch.
- Never-arm (`continuous_strategy.py:879`) calls `family_halt_state()` once and logs
  `continuous_rung_hold: family halt is set (family_id=%s source=%s); never arming`. The
  `family_halt_at_start` record and event are unchanged.
- Supervisor `read_continuous_family_store_state(store_path, sending_family_id)` reads the
  legacy key, then the per-family key. `ContinuousFamilyStoreState` gains `family_halt_source`,
  which is logged on the self-check line. `family_halted` keeps its meaning.
- AUD-07 `read_exit_control_halt_precondition`: `halt_key` becomes the per-family key. The
  verdict is unchanged (via the reader above).
- Digest `read_family_halt_status(store_path, family_id)` issues one `IN (?, ?)` select. With
  no family id it returns `unknown`, reason `no family id` (never `no`).

Boot order (`app/trade.py::run`, inside the existing `ExitStack` after
`open_submit_intent_latch`, before `phase1_sending_permit` and any composition):
```
mig_latch = open_trial_day_latch(latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
                                 family_id=settings.sending_family_id)
outcome = mig_latch.migrate_legacy_family_halt(attribution=LEGACY_HALT_ATTRIBUTION, now_ns=time.time_ns())
_boot_logger.info("family_halt_migration outcome=%s family_id=%s", outcome.kind, outcome.family_id)
MIGRATED        -> emit_alert WARN  event=FAMILY_HALT_MIGRATED (once; later boots are NOOP)
UNATTRIBUTABLE  -> emit_alert CRITICAL event=LEGACY_FAMILY_HALT_UNATTRIBUTABLE (every boot); boot CONTINUES
                   (legacy halts all => never arms; the node stays up for resolver/recorder duties)
store error     -> propagates, same as any other boot-time store failure today
```
`cont_factory` and `family_halt_latch` are then built with `family_id=manifest.family_id`,
which is asserted equal to `settings.sending_family_id`.

Clearing paths (L-48 row):
| Latch state | Who clears | Process | Inputs | Test |
|---|---|---|---|---|
| per-family halt X | operator (for A1: only after a new A1-class ruling) | `breezy-clear-family-halt --family-id X`, node down (flock) | reason ≥20 chars, evidence file | `test_clear_per_family_halt_writes_family_scoped_audit_and_leaves_other_families` |
| legacy, attributable | automatic migration (it moves the halt, never clears it) | node boot, or either CLI | pinned attribution | `test_boot_migrates_legacy_v4_halt_before_composition` |
| legacy, UNATTRIBUTABLE | build side (new peer-reviewed attribution) **or** operator `breezy-clear-family-halt --legacy` with evidence | node down | reason, evidence | `test_clear_legacy_refuses_when_attributable_and_clears_when_unattributable` |
Every path can run while the latch is closed and across a day boundary, because none of
them depends on an armed strategy.

## 5. File-by-file plan

Strategy layer
1. `src/breezy/strategy/current_rung_hold/trial_day_latch.py`
   - Rename `FAMILY_HALT_KEY` to `LEGACY_FAMILY_HALT_KEY` (literal unchanged). No alias, so
     every old import fails loudly and is migrated consciously. Update `__all__`.
   - Add `FAMILY_HALT_KEY_PREFIX`, `FAMILY_HALT_CLEARED_KEY_PREFIX`,
     `HALT_MIGRATED_KEY_PREFIX`, `_LEGACY_HALT_MIGRATED_MARKER`, `family_halt_key()`,
     `FamilyHaltReading`, `decode_family_halt_state()`, `LegacyHaltAttribution`,
     `LEGACY_HALT_ATTRIBUTION`, `MigrationOutcome` (kind ∈ {NOOP_ABSENT, NOOP_CLEARED,
     NOOP_ALREADY_MIGRATED, MIGRATED, UNATTRIBUTABLE}; family_id).
   - Replace `decode_family_halt(raw)` with `decode_family_halt_state` (remove the one-arg
     function; the digest is its only other caller).
   - `TrialDayLatch.__init__` / `open_trial_day_latch` gain keyword `family_id: str | None =
     None`, validated through `family_halt_key` when set.
   - All three writers: the idempotency check reads the per-family raw value only, and the
     payload adds `"familyId"`. Writing while the legacy key halts all is allowed and harmless.
   - `is_family_halted`, new `family_halt_state`, `clear_family_halt` (per-family: audit
     under `FAMILY_HALT_CLEARED_KEY_PREFIX/<id>/<ts_ns>` with `familyId`, then the CLEARED
     sentinel on the per-family key; raises if the per-family key is not halted; never
     touches legacy).
   - New `clear_legacy_family_halt(*, reason, evidence_sha256, ts_ns, attribution)`: raises if
     legacy is absent/CLEARED/MIGRATED **or if it is attributable** (it must be migrated, never
     cleared). Otherwise it writes an audit under the existing `HALT_CLEARED_KEY_PREFIX` and
     then the CLEARED sentinel.
   - New `migrate_legacy_family_halt` (§4). Update the comment block at :276-291 to retire
     "GLOBAL-equivalent".
2. `src/breezy/strategy/current_rung_hold/composition.py`: `make_trial_day_latch_factory`
   gains `family_id`. `family_halt_submit_veto` needs no change.
3. `src/breezy/strategy/current_rung_hold/continuous_strategy.py:879-887`: never-arm log line
   with family id and source (AC-10). No change to event names.
4. `src/breezy/strategy/current_rung_hold/set_family_halt_cli.py`:
   - `--family-id` (required, including with `--status`) and `--families-dir` (default
     `deploy/families`, the same relative convention as `app/trade.py:97`).
   - Validation via `load_family_manifest`: the file exists, the `family_id` field equals the
     argument, and the kind is continuous. Otherwise REFUSED with NEXT.
   - The latch is opened with `family_id`. Migration runs first. UNATTRIBUTABLE prints a
     warning and continues: setting a per-family halt is still valid and additive.
   - "already halted" now means the per-family key is halted.
   - `--status` prints `family_id= halted= source= legacy=<absent|cleared|migrated|halts_all>`.
   - The alert detail adds `family_id=`. The pre-set positions GET is unchanged (account-wide,
     so it is conservative for a per-family set).
5. `src/breezy/strategy/current_rung_hold/clear_family_halt_cli.py`:
   - `--family-id` XOR `--legacy` (argparse mutually exclusive group, one required), plus
     `--families-dir` and the same validation.
   - Migration runs first. `--family-id` clears the per-family key. `--legacy` →
     `clear_legacy_family_halt`, printing "legacy halt is attributable; it was migrated, not
     cleared" when the latch raises for that reason.
   - Add a read-only `--status` mirroring the set CLI.
   - Module docstring: rename `pm_us_crh_cont` to "a continuous-rung-hold family".
6. `src/breezy/strategy/current_rung_hold/exit_wiring.py`: no code change. Confirm by test
   that the exit veto reads the bound family.

App layer
7. `src/breezy/app/trade.py`: boot migration block (§4), right after `open_submit_intent_latch`
   and before `phase1_sending_permit`. Pass `family_id=manifest.family_id` to `cont_factory`
   and `family_halt_latch`. Assert `manifest.family_id == settings.sending_family_id`
   (SettingsError → EXIT_CONFIG_ERROR). The v2 branch factory stays unbound; v2 never reads
   the halt.

Runtime layer (literals only; never imports strategy)
8. `src/breezy/runtime/trade_supervisor_core.py`:
   - Rename `CONTINUOUS_FAMILY_HALT_KEY` to `CONTINUOUS_LEGACY_FAMILY_HALT_KEY`. Add
     `CONTINUOUS_FAMILY_HALT_KEY_PREFIX` and `CONTINUOUS_LEGACY_HALT_MIGRATED_MARKER`.
   - `continuous_family_halt_key(id)` returns prefix + validated id (the body widening its own
     docstring anticipated).
   - `continuous_family_is_halted` becomes two-argument, and
     `continuous_family_halt_state(legacy_raw, family_raw) -> (halted, source)` is added.
   - `SelfCheckResult` and `AlertDetail` are untouched.
9. `src/breezy/runtime/trade_supervisor.py:437-457`: read legacy then per-family, populate
   `family_halt_source`, and add `continuous_family_halt_source=` to the self-check log line.
   `ContinuousFamilyStoreState` gains the field.
10. `src/breezy/runtime/exit_control_precondition.py`: no logic change beyond the per-family
    `halt_key`. The verdict comes from the updated reader.

Scripts and deploy
11. `scripts/analysis/decision_funnel_daily_digest.py`: add a `--family-id` argument. It falls
    back to `BREEZY_SENDING_FAMILY_ID` in the digest's env, and with neither it reports
    `unknown`. Single-statement `IN (?, ?)` select → `decode_family_halt_state`. The artefact
    gains the additive fields `halt_family_id` and `halt_source`.
12. `deploy/systemd/decision-funnel-digest-run.sh`: resolve `BREEZY_SENDING_FAMILY_ID` from
    `systemctl --user show breezy-trade-supervisor.service --property=Environment`, using the
    exact idiom and `[A-Za-z0-9_-]` check in `replay-daily-run.sh:110-127`, and pass
    `--family-id`. If the id is absent, the digest still runs and reports `unknown` (no
    silent `no`).
13. `scripts/analysis/current_rung_hold_paper_replay.py:781-792`: bind
    `family_id=manifest.family_id` when `--family-manifest` is given, else a module constant
    `REPLAY_FAMILY_ID = "paper_replay"`. The replay store is private, so no live halt is read.

Fixtures and docs
14. `tests/fixtures/family_halt/legacy_v4_halt_2026-09-24.bin`: the verbatim 259 legacy bytes,
    captured read-only (`file:…?mode=ro`) at build time. This is the real writer's output (L-42).
    It holds no secret: reason text plus an evidence hash. Before committing, re-verify the
    sha equals the pinned value. If it differs, STOP and re-plan: the store changed since
    2026-09-27.
15. `docs/core/PROGRESS.md` row, and a `docs/runbooks` note (if a family-halt runbook exists)
    on the new CLI args. No LESSONS change unless the build diverges.

## 6. Test strategy (RED first; all through `scripts/ci/run_tests_no_egress.sh`)

New file `tests/unit/test_edge3_per_family_halt.py` (the halt state is always seeded through
the real writers, `record_policy_halt`/`record_duplicate_fill`/`record_ambiguous_exit`, or,
for legacy, the verbatim fixture bytes of the real legacy writer; L-42):
1. `test_policy_halt_writes_only_the_per_family_key_and_never_the_legacy_key`
2. `test_duplicate_fill_and_ambiguous_exit_halts_are_per_family`
3. `test_halt_on_family_a_does_not_halt_family_b` (AC-2)
4. `test_any_non_sentinel_legacy_value_halts_every_family` (fixture bytes, `b"{\"v\":1}"`, corrupt bytes, empty bytes) (AC-3)
5. `test_cleared_or_migrated_legacy_sentinel_does_not_halt_an_unhalted_family`
6. `test_migration_copies_the_legacy_bytes_verbatim_to_the_attributed_family` (sha, reason, tsNs, detail, evidenceSha256) (AC-4)
7. `test_migration_writes_per_family_before_the_legacy_sentinel` (recording-store double asserting set order: target, audit, legacy) (AC-5)
8. `test_crash_after_each_migration_write_leaves_v4_halted_and_rerun_converges` (parametrised over 3 injected failure points) (AC-5, AC-6)
9. `test_migration_is_idempotent_and_writes_no_second_audit_once_migrated` (AC-6)
10. `test_migration_never_overwrites_an_existing_per_family_halt`
11. `test_unattributable_legacy_bytes_are_not_migrated_and_keep_halting_all` (AC-7)
12. `test_migration_readback_failure_raises_and_leaves_legacy_in_place`
13. `test_fixture_bytes_hash_to_the_pinned_attribution_sha` (pins the constant to reality)
14. `test_family_halt_key_rejects_empty_tilde_caret_colon_slash_and_overlong_ids`
15. `test_unbound_latch_raises_on_every_halt_method` (O6)
16. `test_reader_that_sees_migrated_sentinel_always_sees_the_per_family_halt` (interleaving: a lock-free reader store runs between each migration write, legacy-first order) (AC-5)
17. `test_old_decoder_reads_migrated_sentinel_as_halted` (rollback safety: the pre-EDGE-3 one-arg rule re-stated as a local lambda against the new sentinel) (AC-5)
18. `test_clear_per_family_halt_writes_family_scoped_audit_and_leaves_other_families`
19. `test_clear_legacy_refuses_when_attributable_and_clears_when_unattributable`

Boot wiring, in `tests/unit/test_app_trade_*` (the existing continuous-boot harness):
20. `test_boot_migrates_legacy_v4_halt_before_composition` (the migration log line precedes any strategy construction; the store ends in the AC-4 state)
21. `test_boot_with_unattributable_legacy_alerts_critical_and_never_arms`
22. `test_boot_binds_cont_factory_and_veto_latch_to_the_manifest_family_id`
23. `test_boot_refuses_when_manifest_family_id_differs_from_sending_family_id`
24. `test_fresh_family_boots_unhalted_after_v4_halt_is_migrated` (A1 §7 item 4 scenario; strategy does NOT log family_halt_at_start)
25. `test_never_arm_log_names_family_id_and_source` (both sources)

CLIs (extend `tests/unit/test_set_family_halt_cli.py`, `tests/unit/test_clear_family_halt_cli.py`):
26. `test_set_requires_family_id_even_for_status`
27. `test_set_refuses_unknown_or_non_continuous_or_mismatched_family_id`
28. `test_set_runs_migration_first_then_reports_already_halted_for_v4`
29. `test_set_on_fresh_family_writes_only_its_key_while_v4_stays_halted`
30. `test_status_reports_family_id_halted_source_and_legacy_state`
31. `test_clear_requires_exactly_one_of_family_id_or_legacy`
32. `test_clear_family_id_never_clears_a_legacy_halts_all_value` (after clearing X, X still reads halted while legacy is unmigrated)
33. The existing `test_refuses_while_the_node_holds_the_lock` tests stay green unchanged except
    for the argv addition (flock discipline, AC-9).

Supervisor, AUD-07 and digest:
34. `test_trade_supervisor_cont_self_check.py`: the byte-for-byte pins are re-pointed, not
    loosened: `CONTINUOUS_LEGACY_FAMILY_HALT_KEY == LEGACY_FAMILY_HALT_KEY`, prefix equals
    prefix, MIGRATED marker equals marker, CLEARED equals CLEARED.
35. `test_runtime_and_strategy_halt_decoders_agree_on_the_full_fixture_cross_product`
36. `test_self_check_fails_halted_for_v4_and_passes_the_halt_check_for_an_unhalted_family`
37. `test_supervisor_reader_reads_legacy_before_per_family` (get-order recorder)
38. `test_aud07_precondition_is_per_family_and_blocks_all_on_legacy`
39. `test_digest_single_statement_read_reports_per_family_and_legacy_sources`
40. `test_digest_without_family_id_reports_unknown_never_no`
41. Existing tests that seed `store.set(FAMILY_HALT_KEY, …)` (`test_aud07…:139`,
    `test_decision_funnel_daily_digest.py:463`, `test_clear_family_halt_cli.py:83`,
    `test_trade_supervisor_cont_self_check.py:326,346,532`) now seed the **legacy** key, and
    they keep passing with their halted assertions, because legacy halts all. Where a test
    meant per-family behaviour, it gains a sibling that seeds via the real writer. None is
    deleted.
42. `test_continuous_rung_hold_fill_wiring.py:1608` is re-pointed to
    `LEGACY_FAMILY_HALT_KEY == "continuous_rung_hold/halt"`, the same literal assertion.

Edge and failure paths covered: corrupt, empty and non-JSON legacy bytes; a crash at each
write; a read-back failure; a lock-free reader interleaving; a reverted build; a family id
with separator characters; an unbound latch; a manifest mismatch; a digest with no id; an
UNATTRIBUTABLE boot; clear on a family that is not halted; `--legacy` on an attributable
value.

## 7. Execution order and parallelism

One seam owner. The strategy constants and decode are the root of every other change, so the
slices are staged.
- **S1 (sequential root):** trial_day_latch constants, decode, family binding, writers,
  migrate, clear, clear_legacy, plus tests 1-19. Run `lint-imports`.
- **S2 (parallel after S1, disjoint files):**
  - S2a: runtime literals, supervisor reader, AUD-07, tests 34-38. Run `lint-imports`.
  - S2b: CLIs, tests 26-33.
  - S2c: digest, wrapper script, paper replay, tests 39-40.
- **S3 (after S2):** `app/trade.py` boot migration and binding, the `continuous_strategy`
  log line, `composition` factory, tests 20-25.
- **S4:** full gate after the S3 merge (L-43), and again after the final merge. Worktree
  env: `PYTHONPATH=<wt>/src`, `BREEZY_PYTHON=/home/jon/breezy/.venv/bin/python`, basetemp under
  `/home/jon/.cache/breezy-gate/`. Never `uv`/`pip`.
- Reviews: `python-reviewer` plus `security-reviewer` (halt is a safety control) plus
  `trading-bot-architect` on the migration and attribution. The implementer never reviews its
  own slice.

## 8. Deploy and verification

Pre-merge:
1. Re-read the legacy value read-only and confirm sha256 = `5a82b401…5b19f28` and that no
   `halt_cleared/*` keys exist. On a mismatch, STOP (AC-7 would fire; re-plan attribution).

Merge (editable install):
2. At merge the CLIs and the digest are live immediately, the supervisor goes live at its next
   restart (01:00–16:40Z window only), and the node goes live at its next respawn (daily 16:50Z
   spawn). Nothing is killed. Before the node respawns, the running old node keeps reading and
   writing only the legacy key. That key already holds a halt, and every legacy writer is
   first-cause-wins, so it cannot change. New readers see `legacy_unmigrated` → halted. There
   is no window.
3. Supervisor restart inside the window (FU-17 procedure). The first self-check after restart
   logs `continuous_family_halt_source=legacy_unmigrated`.

What proves it live (after the first new-code node boot):
4. The node log file (Popen stdout log, not journald) has
   `family_halt_migration outcome=MIGRATED family_id=pm_us_crh_v4` exactly once on that boot,
   and `NOOP_ALREADY_MIGRATED` on every later boot.
5. The node log has `family halt is set (family_id=pm_us_crh_v4 source=per_family); never
   arming` and `FAMILY_HALT_AT_START_POSITION` per station, the same as the 09-24 baseline.
6. Read-only store check (`mode=ro`): `continuous_rung_hold/family_halt/pm_us_crh_v4` has
   sha256 `5a82b401…`; `continuous_rung_hold/halt` equals the MIGRATED sentinel; one
   `halt_migrated/<ts>` audit exists.
7. The alert sink received `FAMILY_HALT_MIGRATED` (WARN) and did NOT receive
   `LEGACY_FAMILY_HALT_UNATTRIBUTABLE`.
8. The 17:05Z self-check line shows `continuous_family_halt_source=per_family`, and the
   result string equals the pre-deploy baseline for the same node condition.
9. The next 09:20Z digest artefact has `halt_enforced: yes`, `halt_family_id: pm_us_crh_v4`,
   `halt_source: per_family`.
10. `breezy-set-family-halt --family-id pm_us_crh_v4 --status` (run only while the node is
    down, otherwise it refuses on the flock by design) is optional. Items 4-9 are enough.
11. Zero orders after deploy (unchanged from 09-24).

Rollback: reverting the code is safe. Old readers see the MIGRATED sentinel as halted, so all
families stay halted (O3).

## 9. Risk register

| # | Risk | L | I | Mitigation |
|---|---|---|---|---|
| R1 | A reader sees the per-family key absent and the legacy key MIGRATED (the halt reads unset) | L | CRIT | Write order per-family → sentinel. Reader order legacy → per-family, or a single statement. Tests 7, 16, 37. |
| R2 | The legacy halt is attributed to the wrong family | L | HIGH | Pinned sha plus family. Fixture test 13. Pre-merge re-check. A mismatch fails closed (AC-7). |
| R3 | A continuous latch is not bound to a family id | M | HIGH | Unbound calls raise (O6). Boot wiring test 22. No alias for the renamed constant. |
| R4 | A stale script still reads `continuous_rung_hold/halt` | M | MED | Old-name imports fail at import time. Sweep with `/usr/bin/grep -rn "continuous_rung_hold/halt\b"` over src, scripts, deploy (a positive control per memory) before merge. The old one-arg decode rule reads MIGRATED as halted, so it over-halts. |
| R5 | Operator mistypes the family id and sets a halt on the wrong family | M | HIGH | Registry validation (continuous kind, id equals stem). `--status` echoes the id. |
| R6 | The migration raises at boot and the node refuses to start (L-48 deadlock shape) | L | HIGH | UNATTRIBUTABLE never raises. Only store I/O errors and a read-back failure raise, and they behave the same as today's boot-time store errors. A read-back failure leaves legacy halting all, so a retry is safe. |
| R7 | A fresh family inherits the A1 halt | L | MED | Chosen O2(a). Test 24. |
| R8 | The digest regresses to `unknown` because the supervisor env lacks the id | L | LOW | The wrapper resolves the id with the existing idiom and reports `unknown`, never `no`. |
| R9 | Supervisor restart missed, so the old supervisor reads legacy = MIGRATED | M | LOW | Old code reads it as halted. That is correct today and over-reports after a future clear. Deploy step 3. |
| R10 | Thread confinement: migration on the wrong thread | L | MED | Runs in `run()` on the store's constructing thread, before the node starts. Covered by the boot test. |

## 10. LESSONS and invariant compliance

- Nautilus immutable: no Nautilus class is touched. The halt remains Breezy state in the
  existing `SqliteStateStore`. Null hypothesis checked: Nautilus has no per-strategy durable
  halt store under this config (`CacheConfig(database=None)`, `sqlite_store.py` docstring), and
  `RiskEngine.TradingState` is node-wide and in-memory.
- `allow_short` untouched. Caps untouched. Live-trading enablement untouched. The A1 halt
  stays SET throughout. Nothing in this plan clears it, and `--legacy` refuses the
  attributable A1 bytes.
- Safety tests: none deleted or weakened. Pins are re-pointed with identical literal
  assertions (§6 items 34, 41, 42). No exact-set pin (SelfCheckResult/AlertDetail) is widened.
  The two new alert event strings are free-form `emit_alert` events.
- L-42: every halt fixture comes from a real writer or the verbatim bytes of the real legacy
  writer. Readers normalise keys through `family_halt_key` with a round-trip test (14).
- L-43: full gate after every merge (§7 S4).
- L-48: clearing-path table in §4. The migration is a move, never a clear, and it runs inside
  a closed-latch node boot.
- Flock: only the node, or a CLI when the node is down, ever writes. No new lock-free writer.
  Lock-free readers stay read-only (AC-9).
- Layers: runtime duplicates literals and never imports strategy. `lint-imports` runs after
  S1, S2a and S3.
- NO-SEND firewall: no new egress. `emit_alert` uses the existing alerts.env convention.
- Tilde memory: the family-id regex excludes `~ ^ : /`.
- Never `uv`/`pip`. Durable processes are unaffected. Node and supervisor code go live only
  via their normal respawn/restart.

## 11. Dependencies on other EDGE items

- EDGE-3 has no hard dependency on any other EDGE item.
- Any EDGE item that registers or boots a fresh continuous-rung-hold family, or that sets or
  clears a family halt, must land after EDGE-3. Otherwise it inherits the A1 halt, or writes
  the legacy key that EDGE-3 retires.
- An EDGE item that changes the fee-drift probe's UNKNOWN handling to set a halt would write a
  per-family key through `record_policy_halt` after EDGE-3 lands, with no extra work.

## 12. Confidence and unknowns

Confidence: **0.85** that this design meets AC-1..11 as written. 0.9 on the migration and
no-window argument alone.

Unknowns and assumptions:
- U1. The live legacy bytes stay unchanged until merge. Pre-merge step 1 checks this.
- U2. The exact existing test harness for `app/trade.py` continuous boot was not opened. Test
  placement for items 20-25 may move to whichever file already drives `run()`.
- U3. Whether any runbook or doc outside src/scripts/deploy hard-codes the legacy key string.
  Sweep at build time (R4).
- U4. Whether the supervisor's `BREEZY_SENDING_FAMILY_ID` is always present when the digest
  runs. If not, the digest reports `unknown` by design.
- U5. Setting a per-family halt still requires an account-wide flat positions GET. That is
  conservative. A future multi-family node might want a per-family flatness read, which is
  out of scope.
- Open question for peer review: should UNATTRIBUTABLE refuse boot instead of booting halted?
  This plan boots so the resolver and recorder keep running, per L-48. Reviewers should
  confirm.
