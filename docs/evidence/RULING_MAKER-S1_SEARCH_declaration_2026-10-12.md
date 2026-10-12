# RULING_MAKER-S1_SEARCH_declaration_2026-10-12

Status: FINAL. Immutable once committed; any change is a new dated declaration with a new sha256.
Date: 2026-10-12
Type: dated SEARCH declaration under RA-13 B-3 (WP0 of S1, `docs/plans/backlog/MAKER_2026-10-12/S1_preconditions_plan_r3.md`).
Reviews incorporated: `docs/plans/backlog/MAKER_2026-10-12/reviews/S1-WP0-prediction-market-reviewer.md`, `.../S1-WP0-architect.md`.
Hash: `SEARCH_DECLARATION_SHA256` = `sha256sum docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md` over the
committed file bytes (not the git blob id). WP1 reads exactly that repo-relative path.

## 1. Basis

- RA-13 B-3: the firewall binds the corpus, not the statistic. Any post-2026-09-25 count, outcome-blind or not, spends those
  station-days' H-ARCHIVE-RECAL-2026-09 CONFIRM status (`docs/evidence/RULING_RA-13_programme_kill_2026-09-27.md:89-92`).
- EDGE-4 carry-forward rule: no exploratory statistic may read post-freeze station-days unless the corpus is declared SEARCH
  for H-ARCHIVE-RECAL-2026-09 with the cost recorded in both plans
  (`docs/plans/backlog/EDGE_2026-09-27/EDGE-4_DISPOSITION_2026-09-27.md:19`). Template:
  `docs/evidence/RA-13-FW_firewall_audit_2026-09-27.md:21-29` ("declared SEARCH, meaning forfeited for CONFIRM").
- A census does not lift B-3; this declaration does (spec v0.3 section 6.0). Freeze = 2026-09-25 (`freeze_commit` 49261a5c,
  `docs/evidence/RULING_H-ARCHIVE-RECAL-2026-09_horizon_2026-09-25.md` section 0); confirmatory days are strictly after it.
- Pass B (post-freeze) is required: trade capture starts 2026-09-17 09:00Z, so the pre-freeze maker sample is climate days
  09-18..09-25 only. Pass A alone gives `n_eff_ub <= 12.8 < 30` (plan S-4).

## 2. Declaration

| Field | Value |
|---|---|
| Stations | LAX, MDW, MIA, SFO. NYC excluded and untouched |
| Climate days | 2026-09-26 .. 2026-10-13 inclusive (18 days) |
| Covers | S1 (maker-window print census, `TRADE_QUANTITY_UNIT` fill cross-check) and S2 Stage 0 reads only |
| Never covers | S5 shadow run or any later read; each needs its own declaration. S5 holdout days remain disjoint from this scope by construction (S5 window starts after its PREREG freeze) |
| Reads licensed | trade prints, `BinaryOption`/`QuoteTapeGap`/`VenueClockOffset` markers, own create-path fills; Stage 0 replay |
| Not licensed | any day > 2026-10-13, any other station, any use toward a CONFIRM leg or a GO, any forecast-store read |

A "read" is: any row attributed to an in-scope station-day passes `admit_print` or enters any computation. Bytes discarded
before `admit_print` (NYC, days outside 09-26..10-13) are not reads. All 72 in-scope station-days are forfeited at the first
WP1 run, whether or not each yields a row.

NBP holdout: `docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md:5-8` freezes [2026-07-01, 2026-10-02), so
climate days 2026-09-26..10-01 of this scope lie inside it; days from 10-02 are forward data (:9-11). This declaration permits
no forecast-store read. Within the holdout days, tape/print reads are descriptive evidence only, never a confirmatory input
(clause 3, :12-13). Design parameters for S5 may be informed by S1/S2 Stage 0 results on these SEARCH days; S5 days
(climate day >= 2026-10-14) are never read before their own declaration.

Enforcement (plan WP1): `require_firewall_clearance` refuses outside this station/day set or on a sha256 mismatch;
`admit_print` discards NYC and out-of-range prints before any count.

## 3. SEARCH cost

| Item | Station-days |
|---|---|
| Gross scope: 4 stations x 18 days (09-26..10-13) | 72 |
| Possibly already SEARCH (exit-window study; Depth10 read NOT shown, see below) | 0-14 |
| Net new forfeiture (declared) | 72 (58 only if a later audit proves the 14 were read) |

The 14 listed station-days: LAX 10-02..10-06 (5); MDW 10-02, 10-04, 10-05, 10-06 (4); MIA 10-03, 10-05 (2); SFO 10-03, 10-04,
10-06 (3). Source: `~/.local/share/breezy/derived/exit_window_study/2026-10-*_nightly/exit_window_study.json`, re-derived
2026-10-12. They appear only as `excluded fill (no_taken_latch ...)` entries in `missing_inputs`; no post-09-25 climate day
appears in `rows` (latest 2026-09-22). RA-13-FW item 3 makes a day SEARCH only if the study read its Depth10 rows, which is
not evidenced, so none is credited and the declared cost is 72.

Date effect: at a nominal 5 station-days/day accrual ([INFERRED] estimate, `docs/evidence/RULING_RA-13_programme_kill_2026-09-27.md:14`,
no measurement), 72 net moves the EDGE-4 revival trigger (>= 50% of 600 confirmatory station-days) by ~14 days, from
~2026-11-24 to ~2026-12-08 (~2026-12-06 if the 14 are later proven read). Both are inside the 2027-01-25 governance
backstop, which is not an accrual measure and is not extended (RA-13 B-5, :94-97). NYC is untouched.

## 4. Forfeiture statement

Every station-day in section 2 is, from the first WP1 run, SEARCH corpus for H-ARCHIVE-RECAL-2026-09 and permanently removed
from its CONFIRM count (as the H-ARCHIVE-RECAL ruling section 0 did for 09-21..09-25). The cost is the 72 of section 3.

## 5. Outcome statement

S1 outcomes are census counts, a `TRADE_QUANTITY_UNIT` verdict and, at most, an S-5 NO-GO pre-screen. They are never GO and
never NOT-KILLED. Stage 0 is EXPLORATORY only (spec v0.3 section 6.0). Nothing read under this declaration may be cited
toward any registered hypothesis's CONFIRM leg or toward the FQ-v2 NO-TRADE re-open triggers.

## 6. Per-fill list WP2 reads

Pinned; WP2 asserts set equality against this list (per plan r3; derived 2026-10-12 read-only from
`~/.local/share/breezy/state/exec_polymarket_us.sqlite`, keys `exec/polymarket_us/fill/<venueOrderId>`, 34 rows; derived
28 kept / 6 excluded, equal to plan r3). Keep rule: `tsEvent >= TRADE_CAPTURE_START_NS` (2026-09-17T09:00Z =
1789635600000000000), venue `tradeId` (not `GET-`, not null), `feeReconciled` True, station in LAX/MDW/MIA/SFO. All 28
legs are BUY; leg = YES, or NO where the instrument ends `^no`. Price = `cumulativeCost`. The 3 fills on 09-21/09-22 are
pre-freeze; the 25 on 10-02..10-06 sit inside this declaration. No NYC.

Kept (28):

| tradeId | station | climate day | leg | price | tsEvent (ns) |
|---|---|---|---|---|---|
| CMRYWHC1AW1E | MIA | 2026-09-21 | NO | 0.1200 | 1790018316346871145 |
| CMSVQ19VGW1E | SFO | 2026-09-21 | YES | 0.3500 | 1790022095806710834 |
| CNCE55N1WW1E | MDW | 2026-09-22 | NO | 0.1200 | 1790100001798169367 |
| CV44TMZW4YHR | LAX | 2026-10-02 | YES | 0.2300 | 1790870525229407434 |
| CV44TXW6JYHR | LAX | 2026-10-02 | YES | 0.0800 | 1790870526406875753 |
| CV44V8DE2YHR | MDW | 2026-10-02 | YES | 0.0300 | 1790870527281219595 |
| CV44VJNC8YHR | MDW | 2026-10-02 | YES | 0.0700 | 1790870528372964428 |
| CV56FW6R4YHR | MDW | 2026-10-02 | YES | 0.2300 | 1790874933767757723 |
| CVSE930Y2YHR | MIA | 2026-10-03 | YES | 0.4100 | 1790959847140488105 |
| CVSE937HRYHR | LAX | 2026-10-03 | YES | 0.0500 | 1790959847665493058 |
| CVWEANWH8YHR | LAX | 2026-10-03 | YES | 0.1500 | 1790972433034078620 |
| CVX115N56YHR | SFO | 2026-10-03 | YES | 0.0500 | 1790974876930646540 |
| CW0GJ0J0YYHR | SFO | 2026-10-03 | YES | 0.1500 | 1790989492897233183 |
| CW1EK169WYHR | MIA | 2026-10-03 | YES | 0.1100 | 1790993431294382247 |
| CWE1N7CA2YHR | LAX | 2026-10-04 | YES | 0.1500 | 1791046252389200264 |
| CWE25PN3EYHR | MDW | 2026-10-04 | YES | 0.2000 | 1791046320962004929 |
| CWE3HZTJ2YHR | SFO | 2026-10-04 | YES | 0.0900 | 1791046500941688491 |
| CWF9AGYQCYHR | LAX | 2026-10-04 | YES | 0.1500 | 1791051452689954358 |
| CX2MG6YM2YHR | MIA | 2026-10-05 | YES | 0.4800 | 1791132619971026350 |
| CX2MJZBNPYHR | MDW | 2026-10-05 | YES | 0.0700 | 1791132630656991412 |
| CX2MKE7R4YHR | MDW | 2026-10-05 | YES | 0.0300 | 1791132633338640824 |
| CX2MTHFKGYHR | LAX | 2026-10-05 | YES | 0.6400 | 1791132663671418230 |
| CX5MPF3JEYHR | MIA | 2026-10-05 | YES | 0.1100 | 1791145223404130652 |
| CXQ7T822YYHR | SFO | 2026-10-06 | YES | 0.1000 | 1791219050956080829 |
| CXQ7WGS7GYHR | MDW | 2026-10-06 | YES | 0.0300 | 1791219060514168712 |
| CXQ7ZD7NYYHR | MDW | 2026-10-06 | YES | 0.0700 | 1791219075677236821 |
| CXQ801VGYYHR | LAX | 2026-10-06 | YES | 0.1400 | 1791219079336343055 |
| CXSH6TQ0AYHR | SFO | 2026-10-06 | YES | 0.1500 | 1791228663091156742 |

Excluded (6):

| tradeId | station | climate day | leg | price | tsEvent (ns) | reason |
|---|---|---|---|---|---|---|
| null | SFO | 2026-09-11 | YES | 0.22 | 1789179830315479064 | tsEvent before capture start; null tradeId |
| GET-CFJ485874TMM | MIA | 2026-09-13 | YES | 0.70 | 1789319029809353347 | tsEvent before capture start; GET- resolver tradeId |
| CGW7YF5SEVAY | MDW | 2026-09-15 | YES | 0.1100 | 1789495204346084927 | tsEvent before capture start |
| CGWDJA68EVAY | MIA | 2026-09-15 | NO | 0.0900 | 1789495939244552293 | tsEvent before capture start |
| CGWJPXEMPVAY | MDW | 2026-09-15 | YES | 0.2400 | 1789496613740243932 | tsEvent before capture start |
| CGY4D3D4JVAY | SFO | 2026-09-15 | YES | 0.4400 | 1789503126244713950 | tsEvent before capture start |

## 7. Ledger entries (appended in the same commit as this file)

- `docs/evidence/RULING_H-ARCHIVE-RECAL-2026-09_horizon_2026-09-25.md`: new final section `## SEARCH declaration MAKER-S1 (2026-10-12)`;
  sections 0 and 1 unchanged.
- `docs/evidence/RA-13-FW_firewall_audit_2026-09-27.md`: one line after "Forfeiture to date: 0" superseding it (post-freeze forfeiture now 72).

## 8. Invariants

Docs only; plan r3 section 4 invariants apply.

## Citations

- `docs/plans/backlog/MAKER_2026-10-12/S1_preconditions_plan_r3.md` (section 3.2, WP0, S-4, section 7)
- `docs/plans/backlog/MAKER_2026-10-12/reviews/S1-r2-final.md`
- `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` (section 6.0 :195-203; section 9 :361, :398)
- `docs/evidence/RULING_RA-13_programme_kill_2026-09-27.md` (:14, B-3 :89-92, B-5 :94-97)
- `docs/plans/backlog/EDGE_2026-09-27/EDGE-4_DISPOSITION_2026-09-27.md` (:19, :22). The plan cites it under `docs/evidence/`; the real path is as given.
- `docs/evidence/RULING_H-ARCHIVE-RECAL-2026-09_horizon_2026-09-25.md` (section 0); `docs/plans/backlog/AUDIT_2026-09-21/AUD-18a_register_archive_recal_plan_r1_2026-09-26.md`
- `docs/evidence/RA-13-FW_firewall_audit_2026-09-27.md` (:21-29, :28)
- `docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md` (:5-13)
- `~/.local/share/breezy/derived/exit_window_study/2026-10-*_nightly/exit_window_study.json`
- House style: `docs/evidence/RULING_FQ-v2-NO-TRADE_2026-10-08.md`
