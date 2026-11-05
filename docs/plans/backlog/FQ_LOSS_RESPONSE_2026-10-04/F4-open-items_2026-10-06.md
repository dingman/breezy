# F4 (AUT-2a-FQ labels): open items after the build-now scope (2026-10-06)

Merged: WP0–WP3, WP5, WP8, WP6 build-now, OFFLINE_PLUGINS registration (FQ-R41) and its test hardening. Every merge passed the full gate.

## WP6-promote (blocked on AUT-6)

Promotion is one change. It must not be split.

1. **Label units.** Move `breezy-label-outcomes.{service,timer}` from `tests/fixtures/aut2_units/` into `deploy/systemd/`.
2. **Score-live-trials units.** Copy the staged pair from `tests/fixtures/aut2_units/promote/` over the deployed pair. This brings the 13:55Z timer and the `ExecCondition` slot guard. It must land in the SAME change that installs the label timer, because the deployed units are symlinked (reviewed 10-06).
3. **Alerting.**
   - Bind `deliver_with_proof` (AUT-6) to the injected delivery seam.
   - Land the `breezy-autonomy-failed@` notifier (AUT-6).
4. **Production `UnitWiring`.**
   - The planner: C1 attribution plus the legacy CRH join to frozen scored trials.
   - The NWS catalog settlement source.
   - The real `aut6.memory_budget`.
   - The studies flock and the proof-window hook.
5. **WP7.** Flip `WP7_ACTIVE` when the WP7 C1 switch-over activates.
6. **Install.** Before `daemon-reload`, preflight `NeedDaemonReload`.

Until all of this lands, `portfolio_roi` publishes no ROI. The reason is GATED_IDENTITY / GATED_UNLABELLED_FQ, report schema v4.

## WP6-size (coordinator)

- **Plan defects to peer-review first:**
  - The transient unit name must fit the bwrap table grammar.
  - The peak must be read from outside the cgroup namespace.
- **Run.** `label_run --measure-peak` in a quiet window, under the 16 GiB MemAvailable floor, one heavy job at a time.
- **Commit.** One reviewed commit containing the `aut2_memory_peak/v1` artefact, the `MemoryHigh`/`MemoryMax` lines, and `test_label_unit_memory_max_from_measured_label_peak`.

## L-1

At the first live read, run two positive controls:

- the archived 2026-09-16 negative `netPosition` mapped to its ledger NO fill;
- the activity-feed YES/NO netting event.

## F7b

When `FqEvaluator` replaces the FQ row in `OFFLINE_PLUGINS`, F7b deliberately changes `EXPECTED_OFFLINE_TYPES` and the override test's allowed subclass names. `label()` stays routed to the FQ scorer, with `has_scorer`.

## Known gaps

- **Daily reconciliation legs.** The position, settlement and cash legs are INCONCLUSIVE until WP9 snapshot journals exist.
- **Proof-window lag clock.** It uses fill time until a settlement-deadline source is wired.
- **Reader views.** They do not expose `pass_flag` or `realised_pnl_c2_total`.
