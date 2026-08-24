# LESSONS

Binding rules earned from real defects in this repository. If a proposed
approach violates an active lesson, halt and report rather than proceeding.

Each entry records what happened, why it mattered, and the rule it produces.

---

## L1 — A test double must be able to exhibit the failure its subject handles

**What happened.** `FileStateStore.get()` raises `StateStoreCorruptError` on a
per-key CRC32 mismatch. Six handlers — three in `nws_actor.py`, three in
`gate.py` — caught only `(ValueError, TypeError, KeyError, UnicodeDecodeError)`.
`StateStoreCorruptError` descends from `RuntimeError`, so none of them caught it.

Every test covering those handlers used an in-memory store double with no
checksum, which **structurally cannot raise that exception**. The suite was
green, and had been green the whole time the defect existed.

**Why it mattered.** `gate.py`'s own comment states corrupt bytes "must never
propagate as a bare decode exception out of `status()`/`require_open()`".
Against the production store they did exactly that — on the UA-trap global
latch, the most safety-critical path in the system. Three carefully designed
fail-directions in the Actor were correct in design and wrong in deployment.

**Rule.** When a test double stands in for a component with integrity checking,
durability, or locking, the double must be able to produce that component's
failure modes — or the test must use the real component. A fail-direction test
backed only by a double proves the design, not the deployment. At least one
test per fail-direction must exercise the real implementation with the real
failure deliberately induced.

---

## L2 — Read a citation before relying on it

**What happened.** A supersession guard was widened to test the incoming side on
`header.is_correction_bbb OR incoming.correction_flag`, justified by an argument
that both sides should use "the same alphabet", citing `classify.py:60-70`.

Those lines say the opposite. `:68-70`: "Use
`cli_parse.CliStructuralHeader.is_correction_bbb` -- the positional,
structurally-validated verdict -- for supersession decisions, and this one for
the audit trail." `:62-63`: "That divergence in COVERAGE is reviewed and
deliberate; the divergence in ALPHABET was not." `:64`: "This flag is ADVISORY".

The cited passage anticipated the argument and rejected it. The citation was
relayed onward without being read, and the widening reopened the exact hole the
guard existed to close: an `RRA` retransmission of stale values whose body
contains incidental "CORRECTED" wording bypassed the guard entirely.

**Why it mattered.** `correction_flag` scans the whole product body for
`\bCC[A-Z]\b|\bCORRECTED\b|\bCORRECTIONS?\b`. Any unrelated remark carrying that
word makes a non-correction look like a correction, silently reverting a
corrected temperature with no alarm — a wrong settlement, unrecoverable once a
market trades against it.

**Rule.** A file:line citation used to justify a design decision must be read at
that line before the decision rests on it, and before the justification is
passed to anyone else. This applies with full force to citations arriving from
another agent: a plausible-sounding justification is not evidence. A wrong
justification left in a comment is worse than no comment, because it will be
re-derived by the next reader.

**Corollary.** Where a broad and a narrow signal both exist, decide the
direction per call site by consequence, not by symmetry. Here: a broad signal on
the STORED side makes the guard engage more often (safe); on the INCOMING side
it makes the guard engage less often (unsafe). Symmetry was the wrong instinct.
