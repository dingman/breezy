# G-03 — Asymmetric settlement-gate pre-registration + adversarial review

**Phase:** B (free falsification). **Blocks:** G-08, and informs G-17.
**Can end the programme:** yes.

## Problem

The pre-registered 2 °F bucket-alignment gate **FAILED all five cities**. A
post-hoc boundary guard-band sweep did not rescue it: agreement DEGRADES as the
guard tightens (0.764 -> 0.688) while retention collapses to 12.97%.

The residual is not boundary noise. It is a one-directional bias: misses go
from 68.5% to 99.3% "METAR below CLI" as the guard tightens, and NYC is ~99.6%
one-directional at every band. KNYC (Central Park) reports ~29 observations/day
against ~306 at the airport ASOS sites — sparse sampling systematically misses
the true daily maximum.

**Systematic bias is correctable; boundary noise is not.** That is the whole
question, and it is currently untested. From `docs/core/PROGRESS.md`, verbatim:

> Open question, NOT yet tested: the bucket gate is SYMMETRIC, but the Tier-1
> rule is ASYMMETRIC — it only buys once the observed running max has already
> cleared the strike, and refuses the P~0 side. A negative bias is the
> conservative direction for that rule. Testing the asymmetric form needs its
> own pre-registration and an adversarial domain review; it must not be
> adopted as a rescue without one.

## The methodological hazard this item exists to prevent

Reformulating a failed gate into a shape that passes is, by default, p-hacking.
The asymmetric formulation may well be the *correct* one — the Tier-1 rule
genuinely is one-sided, so a symmetric test genuinely was the wrong instrument —
but that argument must be made and reviewed **on its merits, in advance of
seeing the asymmetric result**. If the pre-registration is written after the
number is known, it is worthless regardless of how sound the reasoning reads.

Ordering is therefore a hard requirement, not a preference:

1. Write the pre-registration.
2. Obtain adversarial domain review of the pre-registration.
3. Only then compute the statistic.

## Approach

### Step 1 — Pre-registration document

`docs/evidence/asymmetric_gate_prereg_2026-08-26.md` must state, before any
asymmetric statistic is computed:

- **The rule being tested, exactly.** Tier-1 buys only once the observed
  running max has already cleared the strike, and refuses the P~0 side. Write
  the decision rule as an unambiguous predicate.
- **Why the symmetric gate was the wrong instrument** — the argument that a
  one-sided rule needs a one-sided test — made independently of the observed
  failure. If this argument does not stand on its own without reference to the
  failed result, that is itself the answer.
- **The statistic:** the one-sided hit rate — P(CLI tmax >= strike | observed
  METAR running max has cleared strike), with a Wilson lower bound, per city
  and per degree-of-clearance stratum.
- **The direction that must hold:** the bias must be *conservative* for this
  rule. State precisely what "conservative" means as an inequality, and state
  what observation would falsify it.
- **Sample floor**, per city and per stratum, with power justification. Note
  DOM-8: >=200 settlements is under-powered above ~0.985 entries, which is
  exactly where the depth is, so the floor must be a function of realized entry
  price.
- **The PASS threshold**, justified against a volume-weighted break-even, NOT
  against the market-implied baseline. DOM-7: "beats the market-implied
  baseline" is a tautology for a deterministic tier, because the market-implied
  probability IS the price paid.
- **Pre-declared exclusions**, especially the KNYC sparse-sampling problem —
  decide in advance whether NYC is in or out, and on what stated ground.
- **What a FAIL means for the programme.** Say it plainly.

### Step 2 — Adversarial domain review

Dispatch an independent domain reviewer against the pre-registration with a
charter to attack it, not approve it. Specific questions the review must answer:

- Is the asymmetric reformulation a legitimate correction of instrument choice,
  or a post-hoc rescue of a failed gate? Argue the strongest case for "rescue".
- Does the one-sided statistic still permit the six unenumerated METAR->CLI
  divergence modes of DOM-4 to hide inside it? Those are: C->F rounding at 1 °F
  granularity (31.1 C = 87.98 F, and the trigger lives exactly where the
  conversion decides); intraday METAR CORs revising a temperature downward
  after Breezy has traded; LST-vs-clock window; METAR group choice vs the CLI's
  ASOS 5-minute derivation; station identity vs the venue's named station; and
  the venue's CLI-vs-METAR tiebreak.
- Does the KNYC sampling deficit invalidate NYC entirely rather than merely
  biasing it?
- Is there adverse selection (DOM-10)? A 0.97 offer may exist precisely because
  the seller knows the trigger is wrong — meaning the strategy would
  preferentially trade exactly the markets where its own trigger is defective.
  Does the proposed statistic detect that, or is it blind to it?

### Step 3 — Only after review sign-off

Compute the statistic. Not before. If the review returns BLOCK, amend and
re-review; do not proceed on an unreviewed pre-registration.

## Deliverable

- `docs/evidence/asymmetric_gate_prereg_2026-08-26.md` (pre-registration).
- The adversarial review verdict, recorded verbatim with its findings.
- A statement of whether Step 3 is authorised, and if not, what must change.

## GREEN criterion

Pre-registration written and adversarially reviewed, with the verdict recorded.
**Computing the statistic is explicitly NOT part of this item** — it belongs to
G-17, and doing it here would defeat the item's purpose.

## Risks

- **The review approves too easily.** Mitigation: the reviewer is briefed to
  build the strongest case *against*, and a bare APPROVE with no findings
  should be treated as a failed review, not a passed one.
- **Scope creep into computing the number.** Mitigation: the GREEN criterion
  above forbids it.
