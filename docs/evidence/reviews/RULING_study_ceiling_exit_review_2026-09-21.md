# Adversarial peer review — RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md

Status: PROPOSED — pending author response. Read-only session; verified citations against the
tree, no edits made outside this file.

## Ruling 1 (AUD-15b/c retire, re-home ASOS refresh) — ENDORSE-WITH-REQUIRED-CHANGES

- **CRITICAL — the binding condition names the wrong grain.** E13/E14 treat "re-home
  `asos_recent_refresh.py`" as one fact, but the two wrappers invoke it with materially DIFFERENT
  args producing DIFFERENT cache keys: `offer-gate-daily-run.sh:80` calls it with no `--since`
  (default `DEFAULT_LOOKBACK_DAYS=3`, `asos_recent_refresh.py:91`) — a rolling recent-days URL —
  while `mb-daily-run.sh:86-87` calls it `--since 2026-08-30` (`ASOS_FETCH_START_ANCHOR`), which is
  the ONLY invocation that fetches the fixed `[ASOS_FETCH_START, ASOS_FETCH_END]` window keyed at
  `cache_path_for_url` and read cache-only, raise-on-miss, by
  `current_rung_hold_monitor_hypothetical_hold.py:156-168` (docstring names the `--since` refresh
  explicitly) and by `current_rung_hold_exit_window_study.py:16-22`. Retiring `breezy-mb-daily`
  removes the ONLY producer of that fixed-window cache file; retiring `breezy-offer-gate-daily`
  removes an unrelated 3-day rolling cache the live-path consumer never reads.
  **Silent-failure risk:** because the fixed-window cache file already exists from prior runs, a
  re-homing that (by following the ruling's ungrafted wording) moves only the offer-gate's plain
  invocation would NOT raise on miss — it would leave the monitor/exit-window study silently
  consuming an increasingly stale cache with no error, exactly the failure class AUD-15 exists to
  close.
  **Required text change:** §1.4 item 4 must read "re-home the **`--since $ASOS_FETCH_START_ANCHOR`
  (mb-daily) invocation** of `asos_recent_refresh.py`" — not "the refresh" — and the RED pin
  `test_an_enabled_timer_still_invokes_the_asos_recent_refresh` must assert the surviving invocation
  carries `--since` with that anchor value, not merely that some invocation exists.
- E4 ("nothing reads `offer_gate_latest.md`") and E13 ("only two schedulers") verified exactly as
  cited by repo-wide grep. E5/E12 (module reuse, PREREG pin) verified.

## Ruling 2 (R-12 count ceiling KEPT, BLOCKER-D no-op) — ENDORSE-WITH-REQUIRED-CHANGES

- **Undisclosed asymmetry: the count ceiling resets on relaunch; the dollar ledger does not.**
  `DailySpendLedger.seed_spent` (`operator_controls.py:305-329`) durably re-seeds the dollar total
  from a prior-fill walk at reconnect. The order-count side has no equivalent: a fresh permit mint
  sets `remaining_order_count = budget_orders` at the FULL derived ceiling every time
  (`safety.py:737`), and `seed_permit_budget_from_prior_spend` explicitly states it is "never...
  touching the order-count budget, which counts orders this permit itself authorises, not
  prior-process spend" (`safety.py:786-792`). Given the documented 3x/day mid-day relaunch, the
  count ceiling is effectively "topped up" on every relaunch while the dollar ledger is not. The
  ruling's claim that the bound "can only ever stop the day EARLIER, never authorise more spend"
  stays true in dollar terms (ledger still binds), but its actual protective value — stopping a
  runaway ORDER COUNT — degrades across relaunches, and the ruling's evidence table never surfaces
  this even though the brief asked for it to be checked.
  **Required text change:** §2.2/§2.3 add this citation and a named residual: "the count ceiling's
  budget resets to the full derived value on every permit mint (each of the 3x/day relaunches),
  while the dollar ledger reseeds durably from fills; this is an accepted, documented asymmetry
  (`safety.py:786-792`), not a gap this ruling introduces — but it means the count ceiling cannot be
  relied on as a precise per-day order cap across a relaunch day."
- **BLOCKER-D "no-op" closure doesn't answer the brief's material-change concern.** Going from
  qty=1 (~cents) to a cap-sized order under AUD-06b is a real behavioural change even though the
  per-position cap VALUE is untouched. §2.3 point 4 asserts no operator input is needed (correct —
  it is not a new value), but stops there; it does not require the same discipline point 3 already
  mandates for the count-ceiling stop (a distinct, valueless, logged signal). A silent behaviour
  change from micro-orders to cap-sized orders, with no build-side acknowledgement, is exactly the
  "log-and-forget" pattern the count-ceiling requirement was written to avoid one paragraph earlier.
  **Required text change:** §2.3 point 4, add: "AUD-06b's implementation must emit a distinct,
  dimensionless, valueless log/alert event the first time a live order is sized to the per-position
  cap under the new sizing path (e.g. `ORDER_SIZED_TO_POSITION_CAP`), so the qty=1→cap-sized
  transition is legible in the operational record without asking the operator for or restating any
  value." This is symmetric with point 3's own reasoning and closes the gap without reopening
  BLOCKER-D as an operator question.
- `_derived_session_order_count` (`safety.py:591-606`), `_session_count` override path
  (`safety.py:621-625`, `SESSION_ORDER_COUNT_ENV_VAR` at `:155`), and `authorize_order_cost`'s
  dollar-first gating verified as cited.

## Ruling 3 (AUD-07 sequencing/DRAFT/positive control) — ENDORSE

- Citations verified: `OP_SEQ_BOT_POSITIVE_CONTROL_2026-09-04.md:7` ("operator residue is one
  command... No UI clicks...") and the Residue section text match; `POSITION_EXIT_EXECUTION_
  2026-09-16.md:8-12` ("Everything below the two budget caps is build-side and decided here") and
  `:322-328` (preview-capture retirement gate) match verbatim.
- Checked the brief's specific worry — is "live enablement already granted" being stretched to
  cover arming a NEW family? `pm_us_crh_exit_v4` is confirmed a distinct, separately-manifested
  family (`AUD-07-exit-seam-arming-verification-path.md:34-35`, `deploy/families/
  pm_us_crh_exit_v4.json` DRAFT_NOT_REGISTERED, `_EXIT_RULE_REGISTERED_FAMILIES` gates it
  separately from `TRADING_ENABLED`). The 09-16 operator ruling's authorization ("sell identified
  losers... everything below the two budget caps is build-side") is a class-level authorization,
  not scoped to `pm_us_crh_cont` alone, and AUD-07 itself states arming happens elsewhere and this
  plan "does not arm anything." On that basis the claim holds — not a stretch — but it is implicit.
  **Minor required change:** §3.2.2(b) should state explicitly that `pm_us_crh_exit_v4` is a new
  family and name the 09-16 ruling's authorization as class-scoped (selling identified losers),
  not family-scoped, so a future reader does not need to re-derive that chain.

## Verified but not disputed
E1–E3, E6–E12 (Ruling 1); the ledger/permit code structure (Ruling 2); AUD-07 §7 step-7 sha-pinning
claim (Ruling 3) — all match cited lines.

## Unverifiable in this session
`systemctl --user list-timers` shows no `breezy-family-tally@pm_us_crh_exit_v4` or `pm_us_crh_v4`
timer instance at present; whether that bears on AUD-07 sequencing is outside this ruling's scope
and not evaluated here.

## Delta review (Revision 2 addendum)

Verified against `docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md`
sha256 `de52c084fd96a3b7dc5fd059c04e513c0ba71fd297af4de83959b585b1212c4f`.

**A1 (ASOS re-home, --since form only) — ENDORSE, no required change.** Fixes my finding exactly:
names the mb-daily `--since $ASOS_FETCH_START_ANCHOR` invocation, excludes the rolling form,
requires a freshness (epoch-mtime) assertion, not existence. Challenged "rolling invocation not
kept — is there truly no consumer of the 3-day key?": the ONLY caller of
`load_recent_asos_rows` (the function that opportunistically reads whatever `.txt` files are on
disk, including rolling-refresh output) is `cli_basis_offer_gate_scan.py:893`, inside the scan's
own `main()` — the same module Ruling 1 retires (unscheduled) regardless. The two other importers
of the module (`cli_basis_setup_win_rate_study.py:72`, `whole_tape_paper_replay.py:30`) pull only
`CONTAMINATED_STATIONS`/`QUALIFYING_HEADROOM`, never `load_recent_asos_rows`, and neither is
scheduled by any systemd unit. Claim holds.

**A2 (R2-a per-process residual, BLOCKER-D conditional) — ENDORSE, no required change.** Citation
corrections verified exactly: `operator_controls.py:306` is `def seed_spent`, matching the cited
`:306-331` body; `safety.py:735-738` is the `_Budget(...)` mint block setting
`remaining_order_count=budget_orders` fresh; `safety.py:786-789` is the docstring clause "never
touching the order-count budget... not prior-process spend." This is exactly my flagged gap, now
disclosed as R2-a with a considered, explicitly-rejected alternative (making the count durable) —
correctly framed as new durable state on the highest-consequence seam, not casually deferred. The
BLOCKER-D conditional close (valueless `ORDER_SIZED_TO_POSITION_CAP`, deduped to first occurrence,
alert-delivered) satisfies my required change.

**A3 (new-family / class-scoped authorisation, enablement stays operator-only) — ENDORSE, no
required change.** Matches my citations; adds the explicit operator-only enablement sentence
against `PROGRESS.md:39-42`, closing the implicit-chain concern I raised.

**Regression check:** none of A1–A3 weakens or removes anything in the original ruling; all three
add disclosure/conditions strictly on top of the RETIRE/KEEP/CLOSED decisions already endorsed.
No new unverifiable citation found.

**Net:** ENDORSE the addendum in full. No further required changes from this reviewer.
