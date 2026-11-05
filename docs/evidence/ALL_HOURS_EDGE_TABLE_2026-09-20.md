# All 24 hours can be powered — but `p_hold` is not edge

**Date:** 2026-09-20. Addresses HUNT-1 / the operator requirement that the
strategy hunt continuously rather than inside `[12:00, 17:00)` LST.
**Artefact:** `~/.local/share/breezy/derived/archive_table_all_hours_2026_09_20.py`
sha256 `ec231e0120fca513bed666b9a2d4af7405eb5f65f0f75f8a7177cd58526f49f7`
(corpus sha256 identical to the shipped artefact's). NOT promoted.

## 1. The restriction was SCOPE, not correctness — proven

The study docstring already said so (*"a caller may widen it for a
general-purpose climatology, but SS1 only needs `{12..16}`"*), and
`build_archive_table` / `build_hold_cases` already took `hours` as a parameter —
only the generator hard-wired `ARCHIVE_HOURS`. The restriction came from Part B
(the tape join), which reads only `[12:00, 17:00)` instants. Part A reads the
ASOS running-max series and the CLI final, both defined at all 24 hours
(`is_complete_day` requires 24/24 covered hours).

**Decisive check, re-verified by the coordinator:**

```
shipped cells: 240      new cells: 1152
hours covered: 0..23    total None: 0
shipped keys absent from new: 0
DISAGREEMENTS on shipped cells: 0
```

The widened run reproduces every shipped cell exactly. No leakage change; the
as-of boundary is unchanged.

## 2. Coverage

**1152 cells, 1152 defined, 0 `None`** — 48 per hour × 24 hours
(4 stations × 4 seasons × 3 widths). `N_MIN` untouched at 90. Nothing imputed,
borrowed or smoothed; both bounds still come from one `wilson_interval` call.

The venue quotes all 24 hours: measured over the whole archived Depth10 tape
(3,638 files, 634 instruments), the thinnest hour (02 LST) still carries
~298k instants with a live ask across 15+ distinct days per station.

## 3. THE CRITICAL CAVEAT — `p_hold` is not edge

Median `p_hold_lower`, interior m=0: **0.626 at hour 12 → 0.766 at hour 23.**

It is tempting to read that gradient as "the evening is a better hunting
ground". **It is not, and acting on it would repeat this programme's most
expensive mistake.** The take rule is

    p_bound > price + fee

and this study measures only the left-hand side. `p_hold` rises through the day
for a trivial reason: by late afternoon the daily maximum is effectively
settled, so the rung containing `R(t)` almost always holds. **The market knows
this too and prices those rungs toward 1 in step.** A rising `p_hold` with a
rising price is not edge; it is the same "the information is already in the
price" failure that closed the forecast programme today
(`RULING_forecast_edge_programme_closes_2026-09-20.md`), wearing a different
hat.

**No hour may be admitted to the decision window on `p_hold` alone.** Each
candidate hour must be scored against the CONTEMPORANEOUS ASK at that hour,
net of `θ·p·(1−p)` and the half-spread, on post-freeze data.

## 4. Two further artefacts, both disqualifying on their face

1. **`open_upper` reads ~0.98 at 00–07 LST.** This is the `R(t)` anchor: after
   midnight `R(t)` sits at the ladder's bottom, so `[R, +∞)` nearly always
   holds. Live, `classify_width` would label that rung **`open_lower`**
   (dead-by-construction). It is not an overnight edge; it is an artefact of
   the anchor and must be validated on the real ladder.
2. **24 cells are a measured `0.0000`** (hours 00–06), not `None`. A defined
   zero means "measured, no edge" and the take rule correctly never clears it.
   Do not read a defined zero as a missing cell, or a missing cell as a zero.

## 5. What this does and does not authorise

**Does:** establishes that the five-hour window is not a data limit. All 24
hours are powered at the existing `N_MIN`, so continuous hunting is achievable
in principle.

**Does NOT:** authorise widening `_WINDOW_START/END_HOUR_LST`. That requires,
in order:
1. an ask-relative edge measurement per candidate hour (§3) — the gate, and the
   piece that does not yet exist;
2. `classify_width` validation on the real ladder for any overnight hour (§4.1);
3. regeneration and sha-pinning of the shipped artefact;
4. a PREREG amendment — widening the window changes the registered selector's
   estimand, so per L-34 it is class-C: a NEW family with `n` reset and fresh
   α, exactly as the θ drift was handled today (`pm_us_crh_v4`, `e3e8ac6`);
5. a decision on the 10 h permit TTL, which is sized to the union of the
   current windows and is an operator-facing safety bound — not to be widened
   quietly, and explicitly not via a second daily process.

## 6. Guard added

`generate_current_rung_hold_archive_table.py` **refuses** to overwrite the
shipped `src/.../archive_table.py` when `--hours` is non-default. Argument-free
regeneration stays byte-identical. A widened table cannot reach the live
selector by accident.
