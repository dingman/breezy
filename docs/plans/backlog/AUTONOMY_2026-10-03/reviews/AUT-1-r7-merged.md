# AUT-1 r7: merged (coordinator)
TBA scored 94 and SFH scored 92 (one HIGH). The final score is 92, so the plan goes to r8.

## HIGH
- **X1 (SFH H-A, TBA M2): abandoned-alert delivery.**
  - Write the abandoned marker only after a `delivered=true` proof, or have the marker carry the delivery state.
  - Until it is proven, retry delivery hourly, keyed on the delivery record.
  - The matching key includes the heal sha, so it cannot match another heal's delivery.
  - Add tests.

## MEDIUM
- **X2 (TBA M1): `PayloadStore.put` collision.**
  - `put` raises a typed `PayloadCollision` and never touches `health` or emits from inside `put`.
  - The thread posts `PayloadPutFailed(error_type=collision)`, and the loop runs the failure path.
  - Extend `test_async_thread_failure_never_mutates_writer_state_off_loop` to cover this.
- **X3 (SFH M-A, TBA L1): abandonment scan.** Scan every date at or before `today−8`, bounded to 30 days. The marker keeps the scan idempotent.
- **X4 (SFH M-B): fact queue on stop.** In `on_stop`, after the thread joins, drain the fact queue once and run the failure path. Add a test.
- **X5 (SFH M-C): what `PENDING` keys on.**
  - Key `PENDING` on the async refusal path: an explicit reason allowlist, or the absence of a Take-linked decision id. Do not key it on `kind=Refuse`.
  - A Take-path `Refuse` that is missing its payload is an immediate gap.

## LOW
- **X6:** key the pending map by submit sequence, or use a per-sha count.
- **X7:** state why the stuck, dead and queue-full paths leave `health.ok` unchanged, and assert the DetectorEvent and CRITICAL in tests.
