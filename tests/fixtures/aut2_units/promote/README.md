# Staged unit changes (AUT-2 WP6), not installed

`deploy/systemd/` is installed into the user manager by symlink, so any edit there takes effect at
the next `daemon-reload`. The two files here are the WP6 versions of the tally unit pair. They are
staged, not deployed, until the label unit is promoted (WP6-promote, after AUT-6 lands the
`breezy-autonomy-failed@` notifier row and `deliver_with_proof`). Promotion copies them over the
deployed pair in the same change that installs the label timer.

## What changes

* `breezy-score-live-trials.timer`: `OnCalendar` moves 14:15 UTC to 13:55 UTC, so the tally's worst
  case (13:55 + 60 s accuracy + 1200 s start + the 90 s default stop = 14:17:30) releases before the
  label run's studies-flock wait (14:15 + 600 s) expires. `test_aut2_units_deploy.py` derives the
  arithmetic from these files.
* `breezy-score-live-trials.service`: one `ExecCondition=` line running `slot-guard-run.sh`.
  `Persistent=true` on the timer fires a missed run at any hour; the guard refuses a start whose
  worst-case span meets the launch window `[16:30Z, 17:10Z)` or that begins in the heavy night
  `[01:00Z, 04:30Z)`. A deliberate refusal exits 1 (a clean skip, never `failed`), any internal error
  exits 255 (a failure that fires `OnFailure=`).

## Why it is not live yet

Installed today, the guard would silently skip a catch-up run between 16:07:30Z and 17:10Z (exit 1
is "condition not met", with no `OnFailure=`). With no `score_live_trials_ok` marker the 17:20 tally
and the ROI report then refuse. Nothing gains from the change before the label unit exists.
`test_no_deployed_file_references_slot_guard_run_until_promotion` pins that no deployed file calls
the wrapper.
