# AUD-02b Halt Deployment and Verification (2026-09-25)

**Timestamp (UTC):** 2026-09-25T03:15:30Z

---

## 1. Halt Status (Read from Store)

Store path: `/home/jon/.local/share/breezy/state/exec_polymarket_us.sqlite`

Store-path check: **MATCH**
Halted state: **True**

```
breezy-set-family-halt: store_path=MATCH halted=True
```

(Note: Live node holds the latch; --status reached the store in read-only mode.)

---

## 2. Decoded FAMILY_HALT_KEY Payload

**Location:** `continuous_rung_hold/halt` in exec state store

**Decoded content:**
```json
{
  "detail": "Ruling A1 2026-09-21: pm_us_crh_v4 may not SEND orders; node, capture and KILL clock keep running",
  "evidenceSha256": "754e5cbef13e2896854dc99391e6c64923fe7813ccd03909b7a8fef898b87353",
  "reason": "policy_halt",
  "tsNs": 1790268150964821245,
  "v": 1
}
```

**Decoded timestamp:** 2026-09-24T16:42:30.964821Z

**Evidence SHA256 verification:**

- Expected (from halt payload): `754e5cbef13e2896854dc99391e6c64923fe7813ccd03909b7a8fef898b87353`
- Actual (computed `sha256sum docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`): `754e5cbef13e2896854dc99391e6c64923fe7813ccd03909b7a8fef898b87353`
- **Match result: YES**

---

## 3. Set Record (2026-09-24 ~16:42Z)

**Status:** NOT RECOVERABLE

The supervisor log shows:
- 2026-09-24T16:40:01Z: `stop_prior_sigterm pid=1816897` (node stopped)
- 2026-09-24T16:50:11Z: `launch_refused_intent_open` (launch blocked by intent lock)
- 2026-09-24T17:05:12Z: `self_check result=FAIL_CHILD_EXITED continuous_family_not_halted=False`

The node was offline from 16:40 to 20:15Z. The halt was set at 16:42:30Z while the node was down (no lock held). The CLI output from the set command was not preserved in journalctl or logs; only the resulting store state is recoverable, which shows payload timestamp 16:42:30Z and policy_halt reason matching the A1 ruling.

---

## 4. Forced-Submit Refusal (Tests 1 and 10)

**Test suite:** `tests/unit/test_set_family_halt_cli.py`

**All 34 tests passing:**
```
tests/unit/test_set_family_halt_cli.py ................................. [100%]
============================== 34 passed in 1.54s ==============================
```

Tests (1) and (10) specifically verify:
- (1) Setting the family halt returns the correct verdict
- (10) A forced-submit operation is refused with `family_halt` veto

Both pass as part of the full suite.

---

## 5. Node Log Excerpt

**Node boot (09-24 20:15Z):** `breezy-trade-20260924T201520Z.log`

**Halt detected at startup:**
```
[1m2026-09-24T20:15:51.836707373Z[0m [1;31m[ERROR] BREEZY-L001.ContinuousRungHoldStrategy: continuous_rung_hold: family halt is set; never arming[0m
[1m2026-09-24T20:15:51.836766672Z[0m [1;33m[WARN] BREEZY-L001.breezy: breezy alert event=FAMILY_HALT_AT_START_POSITION site=ContinuousRungHoldStrategy-LAX severity=WARN detail=1 event(s) observed as family_halt_at_start (log-only, never an order)[0m
[1m2026-09-24T20:15:51.992081379Z[0m [1;31m[ERROR] BREEZY-L001.ContinuousRungHoldStrategy: continuous_rung_hold: family halt is set; never arming[0m
[1m2026-09-24T20:15:51.992129565Z[0m [1;33m[WARN] BREEZY-L001.breezy: breezy alert event=FAMILY_HALT_AT_START_POSITION site=ContinuousRungHoldStrategy-MDW severity=WARN detail=1 event(s) observed as family_halt_at_start (log-only, never an order)[0m
```

**Tally advancing (example from 2026-09-25T03:09:53.776Z):**
```
[1m2026-09-25T03:09:53.776278210Z[0m [INFO] BREEZY-L001.DataClient-POLYMARKET_US: 10000 quote(s) refused so far because a book side was empty, across 34 instrument(s); 319990 quote(s) published. Running total only -- the condition is expected on thin weather markets and depth capture is unaffected.
```

**Continuous capture:** Quote tally count advancing from 1000 (20:34Z) through 10000 (03:09Z) confirms continuous data capture and processing.

**Self-check status:** No `self_check_fail_continuous_family_halted` line present in log since 09-24 20:15Z boot. The halt prevents order submission and the node runs in shadow mode only.

---

## Summary

✓ **Halt deployed:** YES — policy_halt set in store  
✓ **Evidence SHA256 MATCH:** YES — A1 ruling verified  
✓ **Payload consistent:** YES — reason="policy_halt"; detail names A1  
✓ **Set record recoverable:** NO — CLI output not preserved (node was offline during set; only store timestamp 16:42:30Z available)  
✓ **Tests pass:** YES — all 34 AUD-02b tests pass  
✓ **Capture advancing:** YES — quote tally growing continuously  
✓ **Halt enforced:** YES — node detects halt at every boot and refuses order submission  

---

**Ready for Amendment C commit** with this file path cited per plan §1.
