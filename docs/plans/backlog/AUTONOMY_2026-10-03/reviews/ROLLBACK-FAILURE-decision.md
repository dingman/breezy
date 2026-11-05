# Coordinator decision: rollback failure never freezes the venue (2026-10-03)

**Conflict.** ARCH Rev 6 C5 writes a failed-rollback HALT with cause `rollback_failed`, class INTEGRITY on a byte mismatch. Under
the exec-store mirror, INTEGRITY freezes the venue. That contradicts the coordinator ruling recorded in AUT-7-r1-merged.

**Decision (binding on ARCH Rev 7/8 and AUT-7):**
1. A failed rollback writes a HALT with `cause_code=rollback_failed`, in the **non-freezing** class `ROLLBACK_FAILED`. It halts only the
   family that failed to activate, retries daily, and sends a CRITICAL through `deliver_with_proof`.
2. A byte mismatch on a rollback **target** makes that target **ineligible** (`rollback_eligible=false`, `cause=target_integrity`)
   and sends a CRITICAL. The target was never loaded, so the venue is not frozen. Each load re-verifies the running champion's own
   bytes; a mismatch on the **champion's own** artefact at load is a genuine INTEGRITY event and keeps the existing freeze semantics.
3. AUT-7 uses the ARCH enum (`rollback_failed`, plus the trigger's own class) and introduces no new `cause_code` values.
