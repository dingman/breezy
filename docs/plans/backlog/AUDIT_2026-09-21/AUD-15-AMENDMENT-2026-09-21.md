# AUD-15 amendment — CONVERGED decision record (binding for implementation)

Base design: the appendix below (option B: dedicated `~/.config/breezy/alerts.env`,
0600, holding ONLY `BREEZY_ALERT_WEBHOOK_URL`; loaded by `breezy-study-failed@.service`,
`breezy-asos-refresh.service` and `breezy-trade-supervisor.service`).
Peer review: silent-failure-hunter ENDORSE-WITH-CHANGES, security-reviewer ENDORSE-WITH-CHANGES.
Where this record differs from AMENDMENT.md, THIS RECORD WINS.

## Commit 1 (prerequisite, separate commit) — fix(health): emit_alert must not log the webhook URL
- `src/breezy/runtime/health.py` `emit_alert` catch-all currently does `logger.exception(...)`; an
  `httpx.HTTPStatusError` message embeds the full request URL (ntfy topic URL = bearer capability).
  Log the exception TYPE only (mirror `TeeAlertSink.close()` and `check_alerts_cli.py`'s withheld-message
  discipline). No traceback, no `str(exc)`, no `repr(exc)`. Contract "emit_alert never raises" unchanged.
- RED first: a test whose sink raises an exception whose message contains a sentinel URL; assert the
  sentinel appears in NO captured log record (message, args, exc_text). Put it beside the existing
  emit_alert tests. Touch-set: health.py + that one test module. Nothing else.

## Commit 2 — AUD-15 as amended
A. Env delivery (AMENDMENT.md §4a-c) as designed, plus:
  1. Supervisor unit keeps the DASH form (`EnvironmentFile=-...alerts.env`) — it must never fail to
     start over an alerts file. Notifier + refresh units also use the dash form, because:
  2. RUNTIME visibility is mandatory: `notify_study_failed` and `asos_cache_freshness_check.main` call
     the existing `log_alert_egress_status(env, component=...)` (health.py) BEFORE resolving the sink,
     so a missing/empty alerts.env yields a distinct journal line every run. RED tests for both.
  3. The `tmp_path`-based sink test is kept but must be NAMED and DOCUMENTED as a unit test of
     `resolve_alert_sink` under the declared key name — it does not close the runtime gap; (2) and the
     deploy check do. Do not describe it otherwise.
  4. Allowlist test: each of the two units declares EXACTLY ONE EnvironmentFile and it is
     `-%h/.config/breezy/alerts.env`; forbidden substrings `breezy-trade.env`, `polymarket.env`,
     `operator.env`; the supervisor unit is asserted to load alerts.env too (single source).
     This replaces `test_the_study_failure_notifier_carries_no_environmentfile_and_no_credential`
     — re-scoped stricter, not weakened; say so in the test docstring.
  5. Least privilege: in `asos-refresh-run.sh` the fetch runs as
     `env -u BREEZY_ALERT_WEBHOOK_URL "$PY" .../asos_recent_refresh.py --since ...`; only the freshness
     check sees the variable. Pin with a test on the wrapper text.
B. Migration = ONE idempotent script `deploy/systemd/migrate-alerts-env.sh` (no secrets in it; never
   echoes values; `set -euo pipefail`; umask 077), asserting preconditions and aborting loudly:
   (1) exactly one `^BREEZY_ALERT_WEBHOOK_URL=` line exists in breezy-trade.env OR alerts.env already
   holds it; (2) create alerts.env 0600 by copying that one line (grep > file; never print it);
   (3) assert mode 600 on both files and dir 700; (4) STOP THERE by default. Deleting the key from
   breezy-trade.env is a separate `--finalize` mode that REFUSES unless
   `systemctl --user cat breezy-trade-supervisor.service` already shows the alerts.env line (i.e. the
   commit landed and daemon-reload ran) AND the delivery check has passed; after `sed -i` re-assert
   mode 600. Duplication during the transition is deliberate and harmless (same value; last-wins);
   state that in the README. The script NEVER restarts/stops/starts any unit. Tests: run the script
   against a tmp HOME fixture (fake files, fake `systemctl` on PATH) for: fresh migrate, idempotent
   re-run, zero-key abort, two-key abort, finalize-refused-before-reload, finalize-ok.
C. Deploy-time delivery check: `%h` is NOT expanded by `systemd-run -p`. Use
   `systemd-run --user --wait --pipe -p EnvironmentFile=-$HOME/.config/breezy/alerts.env \
    /home/jon/breezy/.venv/bin/breezy-check-alerts --severity INFO` ; require exit 0 (2 = not
   configured, 3 = not delivered). README must state why `%h` is unusable there. (Verify the
   `--severity` flag exists in check_alerts_cli; if not, use the CLI's real interface and say so.)
D. Folded review fixes (AMENDMENT.md §5 i–vi) as designed: README "Retiring a unit" section; reboot
   catch-up note names `breezy-asos-refresh.timer`; `SinkFactory` typed as
   `Callable[[Mapping[str, str]], AlertSink]`, `# type: ignore` dropped; EMPTY site list => the same
   `asos_cache_stale` WARN (never a vacuous pass); wrapper routes the two Python steps' stdout to
   `$LOG` instead of /dev/null; the contention test asserts on an injected/recording delivery
   signal, not on stderr text leaking from the logging sink.
E. Unchanged from the plan: retirement of both units+timers+wrappers and the re-home land in this
   SAME commit; no MemoryMax/Slice/TimeoutStartSec change on surviving units; zero diff on the three
   study modules; anchor not forked.

## Out of scope / not done by the implementer
No systemctl mutations, no running the migration script against the real ~/.config, no `uv sync`,
no commits. The coordinator commits (two commits, explicit paths) and owns deployment.


---

# Appendix — base design (trading-bot-architect), as reviewed

# AMENDMENT to AUD-15 — deliver both alert paths without a study unit gaining a venue credential

## 1. Contradiction

Plan §6 15a mandates "No `EnvironmentFile=`, no credential" on `breezy-study-failed@.service` and
`breezy-asos-refresh.service`. §12/§7-step-1 assumes `BREEZY_ALERT_WEBHOOK_URL` "is configured" for
them. On this host it lives ONLY in `~/.config/breezy/breezy-trade.env`, loaded only by
`EnvironmentFile=-%h/.config/breezy/breezy-trade.env` on `breezy-trade-supervisor.service`
(`:84`), absent from `systemctl --user show-environment`. Both new units, run under their declared
(empty) environment, resolve `resolve_alert_sink()` → `LoggingAlertSink` — detection without
delivery, the exact defect `f97c26f` was raised to close, reproduced by AUD-15 itself.

## 2. Investigation

- `breezy-trade.env` keys (names only): `POLYMARKET_US_ACCOUNT_NUMBER`,
  `POLYMARKET_US_EXEC_STATE_DB`, `BREEZY_TRADE_TRADER_ID`, `BREEZY_TRADE_CATALOG_ROOT`,
  `BREEZY_USER_AGENT`, `BREEZY_ALERT_WEBHOOK_URL`. Two are venue-account-identifying — pointing a
  study unit at this file hands it the venue account number and exec-state DB path the moment
  anyone edits it, protected only by a test that might not be re-run. **Rejected on the invariant
  itself, not on test discipline.**
- `f97c26f` (`git show --stat`) shipped `resolve_alert_sink`/`emit_alert`/`WebhookAlertSink`
  (`health.py`), the `BREEZY_ALERT_WEBHOOK_URL` env-var name, and `breezy-check-alerts`
  (exit 0 delivered / 2 not-configured / 3 configured-not-delivered). It never touched any unit's
  `EnvironmentFile=`.
- README convention (grepped across `deploy/systemd/`): every non-supervisor unit states "No
  EnvironmentFile" explicitly; exactly three load one (`breezy-quote-tape.service` →
  `polymarket.env`; `breezy-trade-supervisor.service` → all three env files). No existing
  convention for a shared, non-venue file — this amendment introduces the first one and documents
  it the same way.
- `check_alerts_cli.SinkFactory = Callable[[Mapping[str,str]], AlertSink]` (`:80`) is correct;
  `study_failure_notifier.SinkFactory = Mapping[str, str]` (`:89`) is unused and wrong-shaped.
- Wrapper-contention test asserts `"asos_cache_stale" in (stdout + log)`, where the string only
  appears because `LoggingAlertSink.emit` → `logger.warning` hits Python's `lastResort` handler on
  stderr (no logging config in a bare subprocess) and the wrapper redirects stderr into the log.
  **Green today because delivery is logging** — the false-positive shape this amendment closes.

## 3. Options evaluated

| Option | Verdict |
|---|---|
| (A) `EnvironmentFile=-%h/.config/breezy/breezy-trade.env` on both new units | **Rejected** — carries `POLYMARKET_US_ACCOUNT_NUMBER`/`POLYMARKET_US_EXEC_STATE_DB` into a study unit; a live invariant violation the moment the file gains a key. |
| (B) Dedicated `~/.config/breezy/alerts.env`, ONLY the webhook key, loaded by the two new units AND the supervisor (single source), one-time migration | **CHOSEN** — smallest correct extension; see §4. |
| (C) `systemctl --user set-environment` / environment.d | **Rejected** — transient (lost on user-manager restart), no existing `environment.d/`, invisible to unit-text pinning tests. |
| (D) `Environment=` inline in the unit file | **Rejected** — a bearer-capability URL in a file mirrored from tracked `deploy/systemd/`; explicitly excluded by the brief. |

(B) eliminates the two-sources-of-truth risk (supervisor reads the same file rather than keeping
its own copy) and matches the file's actual secrecy class: mode 0600, never in the repo, never in
a unit file.

## 4. Specification

**4a. New file.** `~/.config/breezy/alerts.env`, mode `0600`, exactly one line:
`BREEZY_ALERT_WEBHOOK_URL=<value>`.

**4b. Unit lines.** On `breezy-study-failed@.service` and `breezy-asos-refresh.service`, replace
the "No EnvironmentFile" comment with:
```
EnvironmentFile=-%h/.config/breezy/alerts.env
```
On `breezy-trade-supervisor.service`, ADD the same line before its existing `breezy-trade.env`
line (`:84`) — `breezy-trade.env` keeps its other four keys, loses the webhook line (§4e).

**4c. Test changes — re-scoping, not weakening.**
Replace the notifier's "no EnvironmentFile" test (and add the mirror for the refresh unit) with an
allowlist:
```python
_PERMITTED_ENV_FILES: Final[frozenset[str]] = frozenset({"%h/.config/breezy/alerts.env"})
_FORBIDDEN_SUBSTRINGS: Final[tuple[str, ...]] = ("breezy-trade.env", "polymarket.env", "operator.env")

def test_the_study_failure_notifier_declares_only_the_allowlisted_alert_env_file() -> None:
    lines = _directive_lines((_DEPLOY_DIR / _NOTIFIER_TEMPLATE_UNIT).read_text())
    env_files = [l.removeprefix("EnvironmentFile=").lstrip("-") for l in lines
                 if l.startswith("EnvironmentFile=")]
    assert set(env_files) == _PERMITTED_ENV_FILES
    assert not any(f in ef for ef in env_files for f in _FORBIDDEN_SUBSTRINGS)
```
Still asserts zero venue/operator env files (the invariant §6 protects) and additionally pins the
*allowed* file's identity, so a future widen (e.g. appending `polymarket.env`) fails the suite.
Add a companion asserting a fixture `alerts.env` contains exactly one key.

**New hermetic regression test** (no egress; a `tmp_path` fixture stands in for `alerts.env`):
```python
def test_the_alert_path_never_resolves_a_log_only_sink_under_the_units_declared_environment(
    tmp_path: Path,
) -> None:
    fixture_env = tmp_path / "alerts.env"
    fixture_env.write_text("BREEZY_ALERT_WEBHOOK_URL=https://ntfy.sh/fake-topic-token\n")
    env = _parse_environment_file(fixture_env)  # local KEY=VALUE helper, '#'-comments skipped
    sink = resolve_alert_sink(env)
    assert isinstance(sink, WebhookAlertSink)
```
Run for both units. Fails today (neither declares `EnvironmentFile=`) and would fail again if a
future edit dropped the line while the "webhook configured" prose stayed.

**4d. Deploy-time delivery verification.** After §4a/§4b land:
```
systemd-run --user --wait --pipe -p EnvironmentFile=-%h/.config/breezy/alerts.env \
  /home/jon/breezy/.venv/bin/breezy-check-alerts --severity INFO
```
Expected: exit `0`, `delivered -- event=BREEZY_ALERT_EGRESS_CHECK severity=INFO
detail=operator_channel_test`. One run covers both units (identical `EnvironmentFile=`). Exit `2`
→ `alerts.env` missing/empty, stop. Exit `3` → endpoint unreachable, report and stop.

**4e. Host migration (ordered, idempotent, never restarts the supervisor):**
1. `grep -c '^BREEZY_ALERT_WEBHOOK_URL=' ~/.config/breezy/breezy-trade.env` — must be `1`.
2. `[ -f ~/.config/breezy/alerts.env ] || install -m 0600 /dev/null ~/.config/breezy/alerts.env`.
3. `grep -q '^BREEZY_ALERT_WEBHOOK_URL=' ~/.config/breezy/alerts.env || grep '^BREEZY_ALERT_WEBHOOK_URL=' ~/.config/breezy/breezy-trade.env >> ~/.config/breezy/alerts.env`.
4. `diff <(grep '^BREEZY_ALERT_WEBHOOK_URL=' ~/.config/breezy/breezy-trade.env) <(grep '^BREEZY_ALERT_WEBHOOK_URL=' ~/.config/breezy/alerts.env)` — must be empty.
5. Land §4b/§4c; `systemctl --user daemon-reload`.
6. Run §4d; must exit 0 before proceeding.
7. Only after step 6 passes: `sed -i '/^BREEZY_ALERT_WEBHOOK_URL=/d' ~/.config/breezy/breezy-trade.env` (idempotent).
8. **Do not restart `breezy-trade-supervisor.service`.** Its added `EnvironmentFile=` and step 7's
   removal both take effect only at its next natural restart — never forced here (hard invariant:
   never touch the trade node/supervisor). The running process keeps its already-loaded URL until then.
9. `systemctl --user list-timers --all breezy-asos-refresh.timer` — confirm unaffected.

**4f. Rollback.** Re-add the line to `breezy-trade.env` from `alerts.env` (diff-verify per step 4),
`git revert` the unit/test commit, `daemon-reload`. Leave `alerts.env` in place (harmless) or
`rm -f` it. No supervisor restart at rollback either.

## 5. Folded-in review findings

**(i) README "Retiring a unit" section.** Add near "Rollback": `disable --now <unit>.timer`, then
`reset-failed <unit>.service` if ever `failed`, remove both symlinks under
`~/.config/systemd/user/`, `daemon-reload`. Cite `breezy-pm-crh-{cont,v2}-tally` (G-04) as the
named anti-pattern (orphans left `not-found`/`failed`). Apply to the AUD-15b/c retirement in tree.

**(ii) Reboot-catch-up naming.** `README.md:1069-1071` — name `breezy-asos-refresh.timer`
explicitly as the `Persistent=true` unit the residual applies to. If the working-tree timer file
does not yet set `Persistent=true`, flag that back as a separate gap — not silently fixed here.

**(iii) `SinkFactory` type fix** in `study_failure_notifier.py`:
```python
from collections.abc import Callable, Mapping
SinkFactory = Callable[[Mapping[str, str]], AlertSink]
```
Change `sink_factory: object | None = None` → `sink_factory: SinkFactory | None = None`; drop
`# type: ignore[operator]` on the `build(source)` call — unnecessary once typed correctly.

**(iv) Empty site list must alert, never pass vacuously.** In `check_and_alert`, before resolving
paths:
```python
if not sites:
    emit_alert(sink, AlertPayload(severity=ASOS_CACHE_STALE_ALERT_SEVERITY,
        event=ASOS_CACHE_STALE_ALERT_EVENT, site=ASOS_CACHE_STALE_ALERT_SITE,
        detail=AsosCacheStaleDetail.CONSUMER_CACHE_KEY_MISSING_OR_STALE_TODAY.value))
    return True
```
New RED test: `test_an_empty_site_list_is_treated_as_stale_not_a_vacuous_pass`.

**(v) Wrapper stdout must reach the journal.** In `asos-refresh-run.sh`, change both `>/dev/null
2>>"$LOG"` (lines 62, 76) to `>>"$LOG" 2>>"$LOG"` — the refresh's per-site outcome and the
`stale=` verdict must be visible; the unit already ships `StandardOutput=journal`.

**(vi) Contention test must assert real delivery.** Rewrite
`test_the_staleness_check_still_runs_when_the_studies_flock_is_held` to point
`BREEZY_ALERT_WEBHOOK_URL` at the loopback HTTPS fixture `tests/support/loopback_https.py`
(already shipped by `f97c26f`) and assert the receiver's captured body contains
`"event":"asos_cache_stale"`, replacing the `combined`-text grep. Depends on (v) only for
visibility of the non-alert log lines (`SKIPPED-LOCK` etc.), not for this assertion.

## 6. Final touch-set

`deploy/systemd/breezy-study-failed@.service`, `breezy-asos-refresh.service`,
`breezy-trade-supervisor.service` (EnvironmentFile= lines); `deploy/systemd/asos-refresh-run.sh`
(stdout routing); `deploy/systemd/README.md` (env-file note, retiring section, reboot-catch-up
naming); `src/breezy/runtime/study_failure_notifier.py` (SinkFactory);
`scripts/analysis/asos_cache_freshness_check.py` (empty-site alert); `tests/unit/test_study_failure_alert.py`,
a mirror test file for the refresh unit, `tests/unit/test_asos_refresh_wrapper_contention.py`,
`tests/unit/test_asos_cache_freshness_check.py`. **Host-only, never committed:**
`~/.config/breezy/alerts.env` (new), `~/.config/breezy/breezy-trade.env` (one line removed).

## 7. Acceptance criteria

1. `systemd-analyze --user verify` empty on both edited units.
2. Allowlist + forbidden-substring tests green on both units.
3. New hermetic "never resolves log-only sink" test green for both units.
4. §4d command exits `0` with the "delivered" line.
5. `grep -c '^BREEZY_ALERT_WEBHOOK_URL=' breezy-trade.env` == 0 post-migration; same on
   `alerts.env` == 1; `stat -c %a alerts.env` == `600`.
6. `breezy-trade-supervisor.service`'s `ActiveEnterTimestamp` unchanged before/after (no restart).
7. Empty-site-list test green.
8. Rewritten contention test asserts a captured HTTPS body, not log text; green under held lock.
9. `git diff` shows zero changes to `cli_basis_offer_gate_scan.py`, `ma_prelock_winner_ask_study.py`,
   `mb_current_rung_edge_study.py`.
10. `lint-imports` clean; `mypy` clean on touched `src/`.
