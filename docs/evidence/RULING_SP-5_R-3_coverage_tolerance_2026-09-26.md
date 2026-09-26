# RULING — SP-5/R-3: coverage KILL-clock tolerance (2026-09-26)

**Authority:** `docs/plans/COVERAGE_KILL_CLOCK_2026-09-12.md` §9 options i–iv, with PREREG v3 §9 as the binding frame.

**How it was ruled:** Two agents were briefed blind and each measured independently against the live catalog.
- `trading-bot-architect` (AUTHOR) recommended (iv-b) + (ii).
- `prediction-market-reviewer` (ADVERSARIAL) recommended indeterminate-exclusion.

The coordinator merged the two positions under the operator's standing grant. No operator-reserved value is involved.

## Measured facts (both agents, CONFIRMED)
- Window 09-12..09-25, DENSE_STATIONS, 56 listed station-days (0 never listed):
  - 13 are clean under any-overlap.
  - 35 have only sub-60 s *resolved* blips.
  - 8 are zombie-blocked: LAX, MDW, MIA and SFO on both 09-14 and 09-15.
- **How a zombie row arises:**
  1. A genuine ~3.5-min venue WS drop occurs (09-14 19:57Z, journal-verified).
  2. The recorder self-terminates by design.
  3. systemd restarts it with a new `recorder_instance_id`.
  4. The dead instance's gap rows never resolve, because `resolved_gaps_by_seq` deliberately never merges across instances (`tape_records.py:551-561`).
- Instrument ids are day-specific, so a zombie poisons only its own station-day.
- **Which counter matters:**
  - `covered_listed_station_days_2026-09-25.json` (count 17) is `pm_us_crh_v2`'s pin-gate artefact.
  - The live KILL input is `…_champion_2026-09-25.json` (count 10), a split made by AUD-05 fix-2 on purpose.
- **Nothing is at risk today:**
  - The champion `pm_us_crh_v4` has 3 filled Takes (`family_tally_v2_pm_us_crh_v4_2026-09-25.md:26`). structural_dead requires `filled_takes == 0`, so it can never fire for v4.
  - The zombie days belong to `pm_us_crh_cont`, which is TERMINAL since 09-19 and outside v4's accounting window.

## Contradiction and resolution
The AUTHOR's (ii), a 60 s duration tolerance, is rejected for three reasons:
- **It is a threshold change.** It adds a duration parameter to "resolved QuoteTapeGap". Under the v2 ratification clause (`grok_prereg_v2_ratification_2026-09-04.md:81`), "any change to a parameter … or a threshold" restarts n→0. The 09-12 note "costs nothing" is stale: v4 now carries 3 live fills.
- **It inflates the KILL clock.** It rescores 43/56 (77%) of days to covered in one step.
- **(iv-b) as proposed is unsound.** It takes the close time from the *process-scoped* next-instance reconnect, which reintroduces the cross-shard fan-out that d3f6c47 fixed.

**ADOPTED:**
1. **Indeterminate-exclusion.** A gap row whose `recorder_instance_id` is no longer running and never resolved is classed INDETERMINATE. Its station-day is excluded from both the numerator and the denominator of the covered-listed count, with the exclusion logged per station-day.
2. **Binding invariant: delay, never manufacture.** A coverage rule change may only ever delay a KILL, never create one. This matches the existing listed-vs-captured residual exclusion.
3. **No new numeric parameter.** Any-overlap and the [12:00,17:00) / 30-min / ≥15 wording stay unchanged.
4. **Prospective only.** The rule applies to families REGISTERED after this ruling, recorded in their registration or PREREG addendum. It never applies mid-stream to an accruing family, so the restart-clause ambiguity cannot arise.
5. **Any future dead-instance close-time inference must be instrument-scoped.** The close time is that same instrument's first observed data in the new instance, never process-level reconnect or subscribe-ack. It is logged per §9 (iv-b)'s caveat and requires its own ruling.

## Build item
**SP-5b** (LOW, prospective):
- Implement the INDETERMINATE classification and exclusion in the covered-listed counter, behind a per-family registration flag that defaults OFF for existing families.
- RED-first tests must cover:
  - a zombie day is excluded, never counted as covered;
  - it is never counted as not-covered either;
  - a family without the flag is byte-unchanged;
  - the exclusion is logged.

## Re-open triggers
- A new champion is registered: apply this rule in its registration.
- A structural_dead evaluation becomes live again (`filled_takes == 0`) for any accruing family.
- Zombie frequency rises (more than 2 incidents per 2 weeks).
