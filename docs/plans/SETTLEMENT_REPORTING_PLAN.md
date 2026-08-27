# Settlement Reporting Layer — Build Plan (G-20 remainder)

Status: plan artifact, **revision 3**, 2026-08-27. Implemented; see the commit that adds `src/breezy/settlement/reporting.py`.
Design plus its executed cross-check record; the build followed it.

Revision 2 answered two independent adversarial reviews, both **BLOCK**. Five
CRITICALs, all the same species: a discipline applied on one axis and abandoned
on another. Revision 3 resolved a self-contradiction found by the implementer:
§3.2 required `SignedErrorDirection.METAR_BELOW_CLI` while D4 forbade any
`below_cli` member unless city-keyed, which an enum member cannot be. D4 now
keys on POLARITY -- a type declaring both directions is measuring, a
single-polarity name is claiming.

CRITICAL and eight HIGH findings are accepted and folded in; two reviewer claims
are rejected with executed evidence and are answered in §12. Revision 1's core —
the Option A rejection (§1), the import-graph [R7] barrier (§4 D2), identity-not-
equality for MDW (§3.3 H2), the sole-constructor scan (§4 R1), the unconditional
NOT EVALUATED section (§3.4), enumerate-don't-count (§3.6), the availability sum
type (§3.2) — is retained unchanged except where a finding touches it.

Binding authority: `docs/evidence/asymmetric_gate_prereg_2026-08-26.md`.
Backlog item: `docs/plans/backlog/G-20-settlement-gate-remaining.md`.
Existing seam: `src/breezy/settlement/coverage.py`,
`src/breezy/settlement/programme.py`,
`tests/unit/test_settlement_coverage_rule.py`,
`tests/unit/test_settlement_programme_rollup.py`.

## Framing, corrected

Revision 1 opened by claiming the plan answers prereg line 845 ("Discipline that
changes no action is theatre") and then conceded at R-4 that it does not force a
report to exist at all. Both cannot be true. Scoped correctly:

> This plan makes the **reporting** half non-theatrical: given that a programme
> report is produced through the sanctioned path, it cannot omit MDW, cannot
> present NYC inside the primary verdict, cannot render a figure it does not
> have, and cannot leave a stratum or a city silently unevaluated. It does
> **not** force a report to be produced, and it does not reach the trading path.
> Residuals R-4 and R-7 (§9) state that limit; no docstring may claim more.

---

## 0. Scope boundaries

**In scope.** A pure reporting layer over `ProgrammeDetermination`; mechanical
[R7] purity and field-allowlist barriers over the settlement package; a
structural un-representability barrier for prereg rule 2's second clause; a
prose lint for its first clause; one impure evidence-writer script; six new test
modules registered in `[tool.mypy] files`.

**Explicitly NOT in scope.**

1. **No trading path, no strategy, no order submission, no egress call site.**
   Barrier N2 in `tests/unit/test_execution_egress_firewall_guard.py` fails the
   build the moment an execution-egress module appears without a proven OS
   firewall, and that is correct. Nothing here goes near it.
2. **No estimator.** This plan defines the *carrier* for the figures and the
   join that binds them to a determination. It does not compute them.
3. **No carrier for `H2(c,k,q)`**, the DOM-10 adverse-selection statistic
   (prereg 280-300). Named as residual **R-8** (§9), which revision 1 omitted
   entirely. Consequence, stated so it cannot be overstated elsewhere: this is
   the **`H(c,k)` report**, not "the pre-registered report". The prereg
   pre-registers two statistics and this covers one.
4. **No change to `coverage.py` or `programme.py` behaviour.**
5. **No revision of the pre-registration.** §11 states what a revision-15
   clarification must say and escalates it; this plan does not amend anything.
6. **These files are owned by a concurrent agent and must not be touched:**
   `tests/unit/test_polymarket_us_auth_smoke.py`,
   `tests/unit/test_polymarket_us_fee_model.py`,
   `tests/unit/test_polymarket_us_discovery.py`, `tests/conftest.py`.

---

## 1. Central design decision: where the numbers come from

Rule 4 (prereg 858-860) demands "MDW's **number**".
`ProgrammeDetermination` carries classifications, never figures.

### Option A — put figures on the determination. REJECTED

The motivating Wilson figures are hindsight-stratified by the day's FINAL METAR
max (`coverage.py:30-36`; prereg 442-446). [R7] forbids them as a gating input.
A numeric field on a determination sits one attribute access away from
`_programme_status` reading it, with nothing to notice. That converts a
structural guarantee into a code-review convention.

### Option B — reporter takes only an evidence structure. REJECTED

Nothing binds figures to verdict; a missing city reads as satisfaction.

### Option C — two inputs joined on exact sets. **ADOPTED**

```python
def build_programme_report(
    determination: ProgrammeDetermination,
    evidence: CityEvidenceTable,
    *,
    stamp: ReportStamp,
) -> ProgrammeReport: ...
```

Two exact-set joins, both in the idiom of `programme.py:309-323`
(`_assert_exact_city_set`, missing **and** unexpected both reported):

- **city axis** — the evidence table's city set must equal the determination's;
- **stratum axis** — per city, the figure set must equal the closed `Stratum`
  enum (§3.1). **New in revision 2; this was the C-1 defect.**

Numeric types live in `breezy.settlement.reporting`; `coverage.py` and
`programme.py` do not import it and, under D2, may not. The deciding functions
cannot reach a number because the number's *type* is downstream of them in the
import graph — checkable in one AST pass, unlike "nobody read the field".

---

## 2. Purity boundary

| Layer | Location | Purity |
|---|---|---|
| Gate | `coverage.py`, `programme.py` | Pure. Unchanged. |
| Report model + render | **`src/breezy/settlement/reporting.py`** (new) | **Pure.** No `open`, no clock, no env, no network. |
| Evidence I/O + write | **`scripts/analysis/settlement_programme_report.py`** (new) | Impure. Reads JSON, writes `docs/evidence/…md` + `.sha256` + `.meta.json`. |

Precedent: `scripts/analysis/settlement_bucket_guard_band.py` (`write_sidecars`
:609-632, `main` :649-709).

No clock in `src/`: the renderer takes `stamp: ReportStamp`, caller-supplied
strings, the injected-`Clock` discipline of `safety.py`. The report is therefore
byte-reproducible in a test without freezing time.

Import-linter (`pyproject.toml:55-79`) puts `features | settlement` below
`persistence | registry | normalize`, so `reporting.py` may import
`breezy.settlement.*` and stdlib only — **not** `breezy.registry`. City
identities are `Final` constants in the settlement package; a test pins them
against `sites.toml` from the *test* side, where the layering rule does not
apply.

---

## 3. `src/breezy/settlement/reporting.py` — the pure layer

### 3.1 Closed sets and identities

```python
MDW_MANDATORY_REVIEW_CITY: Final[str] = "MDW"                # prereg 835-839
PRE_DECLARED_PRIMARY_CITIES: Final[frozenset[str]] = frozenset({"LAX","MDW","MIA","SFO"})

@enum.unique
class Stratum(enum.Enum):                                    # prereg 276-278
    BOUNDARY_0_1 = "[0,1)"
    CLEAR_1_2    = "[1,2)"
    CLEAR_2_3    = "[2,3)"
    CLEAR_3_5    = "[3,5)"
    CLEAR_5_INF  = "[5,inf)"
```

`Stratum` is the C-1 fix. Prereg 276-278: "Clearance bands, at minimum: `[0,1)`,
`[1,2)`, `[2,3)`, `[3,5)`, `[5,∞)` °F. Reported separately. **A pooled figure
alone is not acceptable** — the whole question is how the rate behaves near the
boundary." Revision 1 made only the boundary figure mandatory and let
`wide_figures` be an arbitrary, possibly empty, string-keyed tuple. That
reproduced revision 1's own Option-B rejection one axis over: `[0,1)` and
`[5,∞)` reported, `[1,2)` never computed, and the ledger — which derived entries
only from figures that *existed* — printed `NONE`. A false statement emitted by
the machinery built to prevent false statements. Prereg 792-794 names `[0,1)`
and `[1,2)` as exactly where the DOM-4 divergence modes bite.

An enum member whose value is literally `"pooled"` is unrepresentable, which is
the prereg's "a pooled figure alone is not acceptable" made structural.
`Stratum.BOUNDARY_0_1.value` must equal `coverage.BOUNDARY_STRATUM`; a test
pins that equality so the two modules cannot drift.

**Identity constants are never parameters.** No function in this module takes an
argument naming the mandatory-review city, the secondary city, the primary
roster or the boundary stratum. This is the `boundary_stratum` lesson: a
caller-supplied "which city is MDW" would let a caller nominate a passing city
and satisfy rule 4 while omitting the city rule 4 names. Enforced by
`test_reporting_module_takes_no_identity_parameter` (§7.1).

**`PRE_DECLARED_PRIMARY_CITIES` invariant — subset, not equality.** The primary
set of any report must be a **subset** of the roster, and must **contain MDW**.
Equality is wrong: prereg 265-274 contemplates LAX and SFO going
OUT-OF-SCOPE-DOM-9 ("NYC, MIA and MDW are unaffected and may proceed"), after
which the legitimate primary set is `{MDW, MIA}`. An equality invariant would
make a pre-registered exclusion unreportable. Subset + mandatory MDW is positive
membership over a closed roster and survives DOM-9. Revision 1 exported the
constant with no invariant at all, which the review correctly called out as
decorative.

### 3.2 Figures — sum types, case counts that survive absence

```python
@enum.unique
class FigureAvailability(enum.Enum):
    REPORTED                  = "REPORTED"                  # anchor + bound derived
    UNDERPOWERED              = "UNDERPOWERED"              # N below the floor; counts EXIST
    STRUCTURALLY_UNREACHABLE  = "STRUCTURALLY_UNREACHABLE"  # prereg 781-786
    PROVISIONAL_UNDERPOWERED  = "PROVISIONAL_UNDERPOWERED"  # [R13]
    NOT_DERIVED               = "NOT_DERIVED"               # nothing was run
```

C-4 fix. Revision 1 had three members and forced every non-coverage-satisfying
boundary to `NOT_DERIVED`, which **discarded the case count** — the one number
distinguishing "below the floor" from "never run" — and rendered prereg 781-786
("the rule cannot clear its own break-even at that stratum on measured
historical data") as a shrug.

```python
@enum.unique
class FigureProvenance(enum.Enum):
    HINDSIGHT_STRATIFIED_BY_FINAL_METAR_MAX = "HINDSIGHT_STRATIFIED_BY_FINAL_METAR_MAX"
    DECISION_TIME_OBSERVABLE                = "DECISION_TIME_OBSERVABLE"

@enum.unique
class SignedErrorDirection(enum.Enum):          # H-2 fix; prereg 323-331
    METAR_ABOVE_CLI  = "METAR_ABOVE_CLI"        # the direction that costs money
    METAR_BELOW_CLI  = "METAR_BELOW_CLI"
    MIXED            = "MIXED"
    NOT_DERIVED      = "NOT_DERIVED"

@dataclass(frozen=True, slots=True, kw_only=True)
class PowerFloor:                               # H-2 fix; prereg 721-728
    floor_n: int | None
    anchor: str | None                          # p̂_anchor(c,k), decimal string
    met: PowerFloorStatus                       # MET | MET_ONLY_AT_OPTIMISTIC_THETA
                                                # | NOT_MET | NOT_DERIVED
@dataclass(frozen=True, slots=True, kw_only=True)
class StratumFigure:
    stratum: Stratum
    availability: FigureAvailability
    provenance: FigureProvenance = FigureProvenance.HINDSIGHT_STRATIFIED_BY_FINAL_METAR_MAX
    cases: int | None
    agreements: int | None
    wilson_lower: str | None                    # decimal string; no float in the model
    break_even: str | None
    signed_error_direction: SignedErrorDirection
    mean_signed_error: str | None
    power_floor: PowerFloor
    note: str
```

`__post_init__` invariants:

- `wilson_lower` / `break_even` non-`None` **iff** `availability is REPORTED`.
- `cases` / `agreements` non-`None` for `REPORTED`, `UNDERPOWERED` **and**
  `STRUCTURALLY_UNREACHABLE` — the counts are the evidence in those states —
  and `None` only for `NOT_DERIVED`.
- half-filled states raise `IncoherentFigureError`.

No `has_figure: bool` anywhere: a boolean defaults, survives
`dataclasses.replace`, and vanishes across JSON.

**Provenance defaults to hindsight (H-4 fix).** Revision 1 left it caller-
declared with no default and gated the caveat block on it, so one mislabel would
publish a hindsight-stratified bound affirmatively marked decision-time
observable, under a sha256 sidecar, in the official record. That is precisely how
the prereg's own DOM-2/[R7] defect entered ("Same word, different conditioning
variable", prereg 444-446). Both halves now fail closed: the default is the
hindsight member, and the caveat block is emitted **unconditionally** (§3.6).

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CityEvidence:
    city: str
    figures: Mapping[Stratum, StratumFigure]    # __post_init__: keys == set(Stratum)
    evaluation_index: int                       # H-3 fix; >= 1
    tape_window: str

@dataclass(frozen=True, slots=True, kw_only=True)
class CityEvidenceTable:
    entries: tuple[CityEvidence, ...]           # unique, sorted
    evaluation_index: int
```

`figures` keyed by the enum with an exact-key invariant is the C-1 join: a city
missing `[1,2)` cannot be constructed, so it cannot silently fail to be
reported.

**`evaluation_index` (H-3).** `apply_expiry(determination, *,
evaluations_elapsed)` already makes the evaluation index first-class: the same
`NO_GO` means categorically different things at index 1 and index 3. Prereg
784-786 requires the distinction be visible — "a NO-GO on evidence, stated
plainly and immediately, **never one arrived at by letting a clock run out**."
Without it, a rule-3 programme rejection triggering halt-and-unwind (a real-money
action) renders two identical `NO_GO` lines, half of them clock-driven, with no
reader able to tell. The index appears on both inputs and the join asserts them
equal (`EvaluationIndexMismatchError`); every NO-GO line renders its basis.

### 3.3 Headline

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class CityHeadlineLine:
    city: str
    scope: CityProgrammeScope
    determination: CityDeterminationStatus
    position_taking: PositionTakingDisposition
    verdict_status: VerdictStatus               # ISSUED | BLOCKED_PENDING_ADVERSARIAL_REVIEW
    no_go_basis: NoGoBasis                      # EVIDENCE | EXPIRY_CONVERSION | NOT_APPLICABLE
    figures: tuple[StratumFigure, ...]          # all five strata, Stratum order

@dataclass(frozen=True, slots=True, kw_only=True)
class ProgrammeHeadline:
    determination: ProgrammeDeterminationStatus
    primary_lines: tuple[CityHeadlineLine, ...]
    mdw_line: CityHeadlineLine
    mdw_annotation: MdwAnnotation
    unevaluated: UnevaluatedLedger
    reason: str
```

Invariants, checked in `__post_init__` **and** re-checked by
`_assert_headline_invariants` at render:

- **H1 — MDW present.** `mdw_line.city == MDW_MANDATORY_REVIEW_CITY`, else
  `MdwHeadlineOmissionError`.
- **H2 — MDW is the same object as in the body.** `any(line is headline.mdw_line
  for line in primary_lines)` — identity, not equality, the `is_blocked_sentinel`
  lesson from N1 (`test_execution_egress_firewall_guard.py:212-220`).
- **H3 — no NYC in the primary verdict.** Every primary line has
  `scope is CityProgrammeScope.PRIMARY` (positive membership over the enum, not
  a string check on `"NYC"`).
- **H4 — the ledger is a required field** of a non-optional type.
- **H5 — a `PRIMARY_GO` headline requires MDW's boundary figure to be
  `REPORTED`** (H-1 fix), else `MdwFigureUnavailableForPassError`. Revision 1
  delivered "MDW's line is present" while claiming "MDW's number": `PRIMARY_GO`
  with every figure `NOT_DERIVED` was constructible and renderable today, because
  status is computed from classifications alone. Consequence, accepted
  deliberately: until an estimator exists, **no report can be a `PRIMARY_GO`
  report.** That is the honest outcome and the fail-closed direction.
- **H6 — primary set discipline.** `{line.city for line in primary_lines}` is a
  subset of `PRE_DECLARED_PRIMARY_CITIES` and contains MDW (§3.1).

**`MdwAnnotation` — the C-5 fix, the most permissive gap in revision 1.**

```python
@enum.unique
class MdwAnnotation(enum.Enum):
    FAILED_AS_PRE_DECLARED                    = ...   # prereg 323-328
    PASSED_CONTRARY_TO_PRE_DECLARED_PREDICTION = ...  # prereg 329-331
    NOT_YET_RESOLVED                          = ...
    EXCLUDED_OUT_OF_SCOPE_DOM_9               = ...
```

Derived mechanically from `mdw_line.determination`, never caller-supplied.
Prereg 329-331, verbatim: if MDW passes, "that is evidence the one-sided
statistic is measuring something other than what §3 describes, and **demands
explanation before any GO**." Revision 1 read rule 4 as a presence obligation
only, so four primaries GO with MDW's boundary at 0.994 rendered a clean
`PRIMARY_GO` — formally rule-4 compliant while affirmatively presenting the
outcome the prereg says means the instrument is measuring the wrong thing. The
renderer emits the annotation adjacent to the MDW line and, for the
`PASSED_CONTRARY…` member, an explicit "explanation required before any GO"
block citing 329-331. Test-pinned in §7.1.

(The complementary obligation at prereg 326-328 — MDW's expected failure must
not be reported as an incidental per-site exception — was already satisfied in
revision 1 by the dedicated headline line plus H1/H2, and is unchanged.)

**MDW at `OUT_OF_SCOPE_DOM_9`** was an unnamed unconstructible state in revision
1: `MdwAbsentFromProgrammeError` does not fire (MDW is present) but H2 and H3
cannot both hold. Rule 4 says "whatever it is", so silence is the one wrong
answer — and it is a route *around* prereg 835-839, since classifying MDW's
cells DOM-9 makes the sanctioned path refuse and the report gets written by
hand. Resolved: `mdw_line` carries its actual scope, H3 constrains
`primary_lines` only, the annotation is `EXCLUDED_OUT_OF_SCOPE_DOM_9`, and the
renderer states the exclusion and its DOM-9 ground in the headline.

**Sole-constructor rule (R1, §4).** `build_programme_report` is the only
sanctioned construction site in `src/` and `scripts/`, and no class may
**subclass** `ProgrammeHeadline` (revision 1 was bypassable in one line by
`class _H(ProgrammeHeadline): def __post_init__(self): pass`).

**Considered and rejected: an HMAC issuer tag as in `safety.py`.** The permit is
a capability authorising real spend against a motivated in-process adversary; a
report is a document, and its threat model is a future reporting path that
forgets MDW. An HMAC here would raise the cost of every test double while
defending against no realistic actor.

**MDW absent from the in-scope set entirely** raises
`MdwAbsentFromProgrammeError` (prereg 835-839: "MDW stays in the primary verdict
precisely so that it can fail it"). A subset programme can still be *gated*;
it cannot be *reported* through this path. No `require_mdw` parameter, no
override.

### 3.4 The ledger

```python
@enum.unique
class UnevaluatedReason(enum.Enum):
    BOUNDARY_UNDERPOWERED                = ...   # [R2] + count exists
    BOUNDARY_PROVISIONAL_UNDERPOWERED    = ...   # [R13], prereg 588-596
    BOUNDARY_STRUCTURALLY_UNREACHABLE    = ...   # prereg 781-786: a FINDING
    BOUNDARY_NOT_YET_ANSWERABLE          = ...
    STRATUM_FIGURE_NOT_DERIVED           = ...
    STRATUM_FIGURE_UNDERPOWERED          = ...
    EXCLUDED_SECONDARY_NYC               = ...   # prereg 825-833
    EXCLUDED_OUT_OF_SCOPE_DOM_9          = ...   # [R10]
    VERDICT_BLOCKED_PENDING_REVIEW       = ...   # prereg 787-788
```

C-4 fix: one member per prereg-distinct state, replacing revision 1's single
`BOUNDARY_NOT_COVERAGE_SATISFYING`. `coverage.py` carries these as distinct
members precisely because prereg 715-717 says `STRUCTURALLY_UNREACHABLE` "is a
finding, not a timeout … explicitly distinct from `UNDERPOWERED`"; collapsing
them in the report discards that.

**H-5 fix — `VERDICT_BLOCKED_PENDING_REVIEW`.** Prereg 787-788: "Escalation
requires an adversarial re-review **before any verdict is issued** on the
affected cells" (and 593 for `PROVISIONAL-UNDERPOWERED`). Revision 1 rendered
such a city as a normal line — more permissive than a rule with an explicit
"before any verdict" clause. `CityHeadlineLine.verdict_status` now carries it,
the renderer prints `VERDICT BLOCKED PENDING ADVERSARIAL RE-REVIEW` in place of
the verdict, and the ledger records it. (Note: `determine_city` currently
*raises* `UnresolvedCellClassificationError` for these cells rather than
returning a determination, so this state reaches the report only via the
evidence side. The renderer must handle both; the barrier does not assume one.)

**The ledger is partitioned (H-8 fix):**

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class UnevaluatedLedger:
    structural_exclusions: tuple[UnevaluatedEntry, ...]   # NYC, DOM-9: always expected
    evaluation_gaps: tuple[UnevaluatedEntry, ...]         # missing/underpowered figures
```

Revision 1 lumped them, and since `EXCLUDED_SECONDARY_NYC` appears on every
normal run, "ledger non-empty" was the permanent state — which, combined with
revision 1's exit rule, guaranteed exit 2 forever (§6).

**Derivation is mechanical from the two inputs.** Every field except `detail` is
computed; `detail` is free text and is explicitly **not** load-bearing — no
distinction is carried only in `detail`. Revision 1's §3.4 claimed "never
asserted by a caller" while `detail` was caller-visible; that claim is now
scoped to the derived fields.

**Rendering rule.** Both partitions render unconditionally, immediately after
the headline and **before** the detail tables. An empty `evaluation_gaps` prints
`NONE — every in-scope city carries a reported figure at every one of the five
pre-registered strata.` An omitted section reads as satisfaction; an explicit
`NONE` does not.

### 3.5 `ProgrammeReport` — defined (C-3 fix)

Revision 1 named this type three times and never gave it a body, leaving an
implementer to invent the thing on which the central safety claim rests.

```python
@dataclass(frozen=True, slots=True, kw_only=True)
class ProgrammeReport:
    headline: ProgrammeHeadline
    determination: ProgrammeDetermination
    evidence: CityEvidenceTable
    secondary_lines: tuple[CityHeadlineLine, ...]      # NYC
    out_of_scope_lines: tuple[CityHeadlineLine, ...]   # DOM-9
    stamp: ReportStamp
```

Two report-level invariants close the C-3 gap that H2's identity check did not
reach — revision 1's H2 bound two attributes of the *same headline*, so a
headline built from a filtered subset while detail tables rendered from the full
determination passed H1-H5, passed R1, passed the render re-check, and produced
a headline and city tables that disagreed:

- **P-1** — every line in `headline.primary_lines` is the identical object
  appearing in `secondary_lines`/`out_of_scope_lines`' complement for this
  report; concretely, the union of the three line tuples is exactly one line per
  `determination.city_determinations` entry, matched by city, with no city
  appearing twice and none missing.
- **P-2** — `headline.determination is report.determination.determination`.

And the renderer renders the **primary section from
`headline.primary_lines`**, not from `determination.primary_city_determinations`.
That is what makes H2 load-bearing rather than intra-object: the tuple whose MDW
membership is identity-checked is the tuple the reader sees.

### 3.6 Rendering

`render_markdown(report: ProgrammeReport) -> str`. Fixed section order, pinned
by test:

1. header / provenance (`stamp`, evaluation index, tape window, input digests)
2. **headline verdict** — enumerating the primary city set, never counting it
3. **MDW line + `MdwAnnotation`** (+ the explanation-required block when
   `PASSED_CONTRARY_TO_PRE_DECLARED_PREDICTION`)
4. **NOT EVALUATED — structural exclusions**
5. **NOT EVALUATED — evaluation gaps** (or the literal `NONE …` line)
6. primary city detail, five strata per city, rendered from
   `headline.primary_lines`
7. **SECONDARY (NYC) — excluded from the primary verdict**
8. out of scope (DOM-9)
9. **the [R7] provenance block, emitted unconditionally** (H-4): it states which
   figures, if any, claim `DECISION_TIME_OBSERVABLE` and on what named
   derivation, and states that every figure is reported evidence and was an
   input to no determination.

The verdict line never renders "four-city pass" or any count; a count hides
which city is missing, which is what rule 4 is about.

### 3.7 Public surface

`__all__` exports the types above plus errors rooted at
`SettlementReportError(Exception)`, matching `SettlementCoverageError` /
`ProgrammeInputError`: `EvaluationIndexMismatchError`,
`EvidenceCityMismatchError`, `EvidenceStratumMismatchError`,
`IncoherentFigureError`, `MdwAbsentFromProgrammeError`,
`MdwFigureUnavailableForPassError`, `MdwHeadlineOmissionError`,
`PrimaryCityRosterError`, `UnrecognisedScopeError`.

---

## 4. Barriers over the settlement seam

`tests/unit/test_settlement_purity_guard.py` (**D1-D4**) and
`tests/unit/test_settlement_reporting_guard.py` (**R1-R2**). Every rule is paired
with a `*_detects_*` proof-by-construction test, the idiom of
`test_polymarket_us_readonly_guard.py` (B1-B6) and
`test_execution_egress_firewall_guard.py` (N1-N5). Both reuse `Violation` and
`iter_python_sources` from the read-only guard, as the egress guard already does
(`test_execution_egress_firewall_guard.py:114-118`).

**D1 — the settlement package is pure.** No module under
`src/breezy/settlement/` may import `os`, `pathlib`, `datetime`, `time`,
`random`, `secrets`, `socket`, `httpx`, `requests`, `json`, `subprocess`, nor
call `open`/`input`/`print`. Verified clean today: the only imports across both
modules are `enum`, `collections.abc`, `dataclasses`, `typing`, `__future__`,
`breezy.settlement.coverage`. [R7] purity is currently claimed only in a
docstring (`coverage.py:33-36`); D1 makes it mechanical. This is a ban list, not
an allowlist — residual R-5.

**D2 — the gate may not depend on the reporter.** No module in
`src/breezy/settlement/` other than `reporting.py` may import
`breezy.settlement.reporting`. **Claim narrowed (review finding):** revision 1
said this "keeps figures out of the decision path"; it constrains one package.
A future `src/breezy/strategy/` could import `reporting` freely. D2's honest
claim is: *the settlement gate's own modules cannot reach a figure type.* The
wider case is residual **R-9**.

**D3 — positive field allowlist (C-2 fix, replacing revision 1's type ban).**
For `CityDetermination`, `CityProgrammeDetermination` and
`ProgrammeDetermination`, the set of `AnnAssign` target names must **equal** a
pinned frozenset, extracted from the shipped tree:

```python
_PINNED_DETERMINATION_FIELDS = {
 "CityDetermination": frozenset({"city","determination","tradeable",
   "boundary_classification","blocking_cells","expiry_disposition",
   "escalation_required","reason"}),
 "CityProgrammeDetermination": frozenset({"city","city_determination","scope",
   "position_taking"}),
 "ProgrammeDetermination": frozenset({"determination","city_determinations",
   "primary_city_determinations","secondary_city_determinations",
   "out_of_scope_city_determinations","rejecting_primary_cities",
   "primary_no_go_count","reason"}),
}
```

Revision 1 banned `float`/`Decimal`/`complex` annotations — and the canonical
representation this very plan chose is `wilson_lower: str` and `cases: int`, so
the hindsight quantity D3 exists to exclude was **invisible to D3**, in the exact
case it was sold as backstopping. The type formulation is also unrepairable by
extending the list: `ProgrammeDetermination.primary_no_go_count: int` already
exists, so `int` cannot be banned. The allowlist is type-independent: any new
field of any type fails until someone edits the barrier deliberately. This is
`COVERAGE_SATISFYING` doctrine applied to the barrier itself, and it repairs the
"closed sets, never negation" violation revision 1 admitted for D1 but not D3.

**D4 — the obvious spellings of a programme-wide conservatism claim are
refused (rule 2, second clause).** Revision 2 titled this "the conservatism
property is un-representable" and specified a single pattern,
`(?i)conservatis?m|metar_below_cli|below_cli|one_sided_conservat`, firing unless
the identifier was city-keyed. **That specification was unbuildable and the
title overclaimed.** Both are corrected here.

*The collision.* §3.2 requires `SignedErrorDirection.METAR_BELOW_CLI`; an enum
member cannot carry a `city` field, so the required type made the required
barrier fire and the plan could not be built. Executed against all 111
identifiers §3 specifies, this was the **only** collision (§13).

*The distinction D4 actually needs.* Not "does this identifier name the
direction" but "does it **assert** the property, or **measure** it".
`SignedErrorDirection` is a measurement axis: its container `CityEvidence` is
city-keyed, and it is precisely the per-city re-derivation prereg 852-853
demands. The mechanical signal is polarity — **a type that admits both
directions is measuring; a constant or type naming only one direction is
claiming.** Two rules:

- **D4a — claim vocabulary.** Any class, enum member, dataclass field, function
  or module-level constant under `src/breezy/` whose name matches
  `(?i)conservatism|conservative_estimator|estimator_conservat|one_sided_conservat|metar_reads_below|reads_below_cli`
  fires, **unless** the declaring class carries a `city` field or the function
  takes a `city` parameter. Note `below_cli` and `metar_below_cli` are **removed**
  from the pattern; they name a direction, not a claim.
- **D4b — one-sided direction.** Any identifier matching
  `(?i)\b(metar|cli)_(above|below)_(cli|metar)\b` fires, **unless** it is an
  enum member whose enclosing enum also declares the opposite-polarity member.
  A module-level constant, a class attribute, a function name, or an enum
  offering only one polarity therefore fires; `SignedErrorDirection`, offering
  both, does not.

This remains the enforceable half of rule 2 ("Any component relying on that
property must re-derive it per city"), and barriers for zero callers are exactly
what N2 already does here
(`test_n2_the_shipped_tree_currently_has_no_execution_egress_module`).

**But it is a naming barrier, and the revision-2 title was the §10k defect this
plan exists to avoid.** Nothing prevents `X: Final[bool] = True` under a name
D4 does not match, and nothing prevents a `ProgrammeConservatismFinding` with a
`city: str` field set to `"ALL"`. D4 raises the cost of the obvious spellings;
it does not make the property un-representable. Residual **R-10**.

**R1 — sole constructor + no subclass.** In `src/` and `scripts/`, an
`ast.Call` to `ProgrammeHeadline` may appear only inside
`build_programme_report`, and no `ClassDef` may name `ProgrammeHeadline` as a
base. Tests are deliberately out of scope so the invariants can be proven.

**R2 — demoted to a lint, not a barrier (review finding accepted).** It asserts
`render_markdown`'s body contains a call to `_assert_headline_invariants`. It is
satisfiable by a dead call (`if False: …`), so it is not a guarantee. Kept
because it is free and makes silent deletion visible; the *behaviour* is covered
by `test_render_refuses_a_headline_built_via_object_new` (§7.1). No text in the
implementation may call R2 a barrier.

---

## 5. Rule 2, first clause — P1 as a prose lint

Prereg 850-853. **This is a lint, not enforcement.** It raises the cost of the
literal recurrence; it does not close the class. Revision 1 called it a barrier
and called §5 calibrated; both were wrong (§12).

**P2 is CUT.** Its escape hatch (a `%`, a digit range, or a table pipe) is
satisfied by almost any sentence, giving high nuisance and near-zero detection.
Rule 2's positive clause is now carried by **D4**, structurally.

### The specification, as executed

Scope: `docs/plans/**.md`, `docs/core/**.md`, **`docs/evidence/**.md`**,
`src/**.py`, `scripts/**.py`. **No path allowlist. No directory exclusion.**

1. **Wrap-normalise before splitting.** Join single newlines within a paragraph,
   split paragraphs on blank lines, then split sentences on `[.;]`. Revision 1
   split on `[.;\n]`, so hard-wrapped sentences never reached four tokens and its
   exemptions were never exercised.
2. **Strip Markdown code spans and fenced blocks** before scanning `.md`. A
   quotation is not an assertion. This is what removes the need for a path
   allowlist, including for this plan file and the barrier's own fixtures.
3. A violation is a sentence carrying **all four** of: a METAR token; a CLI
   token; a direction token (`below|under|lower than|colder than|conservative|
   conservatism|never exceeds?`); and a generality marker (`always|in general|
   generally|universally|invariably|every city|all cities|programme-wide|
   program-wide|as a (general )?property|systematically`).
4. **Exemptions are constructions anchored to the assertion verb**, not bare
   words: a negation operator (`no|not|never|neither|forbid*|prohibit*|may not|
   must not|cannot`) within 90 characters **before** an assertion verb
   (`assert*|claim*|report*|state*|treat*|rely/relies*|describ*`); or a
   refutation verb (`falsif*|refut*|withdraw*|disprov*|re-derive*|already
   observed`). Revision 1's bare word list was a one-word bypass — the review's
   example `METAR always reads below CLI, and this is not in dispute.` evaded it
   via `is not`. It does not evade the construction form.

### Executed results — real output, not reasoning

Run against the shipped tree with `.venv/bin/python`:

```
LIVE SCAN, NO ALLOWLIST, markdown code spans stripped: 0 hits
```

Planted positives, all firing:

```
fires=True | METAR always reads below CLI.
fires=True | Treat METAR-below-CLI as a general property of the estimator.
fires=True | METAR always reads below CLI, and this is not in dispute.
fires=True | The estimator systematically reads METAR below CLI in every city.
```

Calibration corpus — real shipped lines, all correctly non-firing:

```
fires=False | scripts/analysis/settlement_bucket_guard_band.py:84   data label
fires=False | docs/evidence/settlement_bucket_gate_2026-08-25.md:83 table header
fires=False | docs/plans/GO_LIVE_PLAN.md:90                         measurement
fires=False | docs/core/PROGRESS.md:766-768                         prohibition
fires=False | docs/plans/backlog/G-20-…:37-39                       prohibition
fires=False | docs/evidence/asymmetric_gate_prereg_…:851            prohibition
fires=False | docs/evidence/asymmetric_gate_prereg_…:333            blanket falsification
```

The calibration test must pin each line **as it is fragmented by the live
splitter**, not as a hand-copied literal — revision 1's would have passed for a
reason unrelated to the live scan.

### Mandatory tests

`test_p1_no_hits_on_the_shipped_tree`; `test_p1_scan_covers_plans_core_evidence_
src_and_scripts` (anti-vacuity: the prereg path must be **inside** the scanned
set — revision 1's equivalent test asserted the opposite);
`test_p1_detects_a_planted_general_claim`;
`test_p1_detects_the_property_phrasing`;
`test_p1_detects_the_is_not_in_dispute_evasion`;
`test_p1_calibration_corpus_does_not_fire` (the seven lines above);
`test_p1_wrap_normalisation_joins_a_hard_wrapped_sentence` (a sentence wrapped
across three lines must reach four tokens);
`test_p1_code_span_stripping_exempts_a_quoted_fixture`.

**Residual R-1:** paraphrase evades P1 entirely. "The venue's thermometer runs
cooler than the climate report everywhere" carries no METAR or CLI token and is
undetectable by any regex a maintainer would tolerate.

---

## 6. `scripts/analysis/settlement_programme_report.py`

Mirrors `settlement_bucket_guard_band.py`. Imports only `breezy.settlement.*`
and stdlib — no sibling analysis script (they import by bare module name, which
would drag `mypy_path` into the registration).

```python
def load_city_evidence(path: Path) -> CityEvidenceTable: ...
def load_city_cells(path: Path) -> dict[str, dict[str, CellClassification]]: ...
def parse_args(argv: Sequence[str]) -> argparse.Namespace: ...
def write_sidecars(*, output: Path, command: str, inputs: Mapping[str, str]) -> None: ...
def main(argv: Sequence[str] | None = None) -> int: ...
```

Loaders are strict: unknown keys raise, unknown enum values raise, a `figures`
map whose keys are not exactly `set(Stratum)` raises. No `--require-mdw`, no
`--primary-cities`, no `--city` filter (§3.1). No network; imports no venue
module, so the read-only guard is unaffected.

**Exit semantics (H-8 fix).**

| Code | Meaning |
|---|---|
| `0` | the report rendered and the ledger is fully **stated** — including when `evaluation_gaps` is non-empty |
| `2` | the builder **refused to render** (any `SettlementReportError`) |

Revision 1 exited 0 only when every primary city carried a `REPORTED` figure
and 2 when the ledger was non-empty. Since no estimator exists and
`EXCLUDED_SECONDARY_NYC` lands on every normal run, those overlapped and exit 2
was the permanent state — a script that always exits non-zero never enters
`validate.sh` or CI, so nothing would ever invoke the reporter, and R-4 would
stop being a residual and become guaranteed-permanent by design. By this plan's
own §5 argument, a signal that always fires gets relaxed. A stated gap is a
successful report; a refusal to render is the failure.

**Step 9 commits one generated report** plus `.sha256` and `.meta.json` from a
real run, so the mechanism has demonstrably executed once against real inputs
rather than only in tests.

---

## 7. Tests

Six new modules, all added to `[tool.mypy] files` beside the two existing
settlement entries (`pyproject.toml:198-201`). The script is registered as an
individual path, **not** by widening `scripts/analysis`, which carries five
pre-existing strict errors documented at `pyproject.toml:143-149`.

### 7.1 `tests/unit/test_settlement_reporting.py`

MDW / rule 4: `test_headline_cannot_be_built_without_mdw`;
`test_headline_rejects_a_fabricated_mdw_line_not_present_in_the_body` (equal but
not identical); `test_primary_go_requires_mdw_boundary_figure_reported` (H5);
`test_render_states_mdw_figure_values_for_every_programme_status` — parametrised
over all five statuses, asserting the rendered **value** (`wilson_lower`,
`cases`, `break_even`, signed-error direction, power floor), **not** a token;
`test_mdw_pass_renders_the_contrary_to_prediction_annotation_and_explanation_
block` (C-5); `test_mdw_out_of_scope_dom_9_renders_the_exclusion_not_an_error`.

Strata / C-1: `test_city_evidence_requires_every_pre_registered_stratum`;
`test_join_rejects_a_city_missing_the_1_2_stratum`;
`test_stratum_enum_boundary_value_matches_coverage_boundary_stratum`;
`test_ledger_reports_a_gap_for_a_stratum_that_was_never_derived`.

Report structure / C-3: `test_render_renders_the_primary_section_from_headline_
lines`; `test_report_rejects_a_headline_whose_lines_disagree_with_the_
determination` (P-1); `test_report_rejects_a_headline_status_differing_from_the_
determination` (P-2).

Ledger / C-4 / H-5: `test_underpowered_boundary_retains_its_case_count`;
`test_structurally_unreachable_renders_as_a_finding_not_a_gap`;
`test_verdict_blocked_pending_review_renders_in_place_of_a_verdict`.

NYC / rule 5 / [R7]: `test_render_marks_nyc_as_secondary`, asserting position by
index against the primary section boundary, not substring presence;
`test_programme_rejected_renders_halt_disposition_for_every_city_including_
live_ones` (rule 5 — the most action-bearing rule in prereg §7 and the only one
revision 1 left with no pinned rendering test);
`test_render_always_emits_the_provenance_block` (H-4, both provenance values);
`test_figure_provenance_defaults_to_hindsight`.

Expiry / H-3: `test_no_go_by_expiry_renders_a_different_basis_than_no_go_on_
evidence`; `test_join_rejects_mismatched_evaluation_index`.

General: `test_render_always_emits_both_ledger_partitions` (including the
literal `NONE` line); `test_figure_numerics_iff_availability`;
`test_render_refuses_a_headline_built_via_object_new` — asserting the **domain**
error, not merely "raises"; the implementation must catch the `AttributeError`
from unset slots and re-raise `MdwHeadlineOmissionError` (or a dedicated
`MalformedHeadlineError`), because a bare `AttributeError` would pass a lazy
`pytest.raises(Exception)`;
`test_report_is_byte_identical_for_identical_inputs`;
`test_reporting_module_takes_no_identity_parameter` — introspects
`inspect.signature` of every public function, asserting no parameter name
matches `(?i)mdw|primary_cit|secondary_cit|review_city|boundary_stratum`.

### 7.2 `tests/unit/test_settlement_reporting_guard.py` — R1, R2
Live scan; `test_r1_detects_a_planted_direct_construction`;
`test_r1_detects_a_planted_subclass`; `test_r1_allows_the_sanctioned_builder`;
`test_r2_detects_a_renderer_without_revalidation`.

### 7.3 `tests/unit/test_settlement_purity_guard.py` — D1-D4
Live scans; `test_d1_detects_a_planted_pathlib_import`;
`test_d1_detects_a_planted_open_call`;
`test_d2_detects_a_planted_reporting_import_in_the_gate`;
`test_d3_detects_a_planted_extra_field_of_any_type` (an added `str` field must
fail, which is the C-2 point); `test_d3_pinned_names_match_the_shipped_tree`;
`test_d4a_detects_a_programme_wide_conservatism_type`;
`test_d4a_allows_a_city_keyed_conservatism_finding`;
`test_d4a_detects_a_conservatism_function_without_a_city_parameter`;
`test_d4a_allows_a_per_city_re_derivation_function`;
`test_d4b_detects_a_module_level_one_sided_direction_constant`;
`test_d4b_detects_an_enum_offering_only_one_polarity`;
`test_d4b_allows_signed_error_direction_which_offers_both`;
`test_d4_does_not_fire_on_any_type_this_plan_requires` — the §13
cross-check, executed as a test over every public name in `reporting.py`;
`test_d1_scan_actually_covers_both_settlement_modules`.

### 7.4 `tests/unit/test_settlement_conservatism_prose_guard.py` — P1 (§5).

### 7.5 `tests/unit/test_settlement_programme_report_script.py`
`test_main_writes_report_and_both_sidecars` (sha256 of written bytes matches the
sidecar); `test_main_exits_zero_when_gaps_are_stated`;
`test_main_exits_two_when_the_builder_refuses`;
`test_loader_rejects_an_evidence_entry_missing_a_stratum`;
`test_loader_rejects_an_unknown_cell_classification`.

### 7.6 `tests/unit/test_settlement_report_prose_claims.py`
One anti-`§10k` test: every `SHOULD`/`MUST`/"cannot"/"unconstructible" claim in
`reporting.py`'s module docstring is listed in a pinned tuple, and each entry
names the test or barrier that enforces it. The prereg's §10k names
prose-claiming-more-than-the-code as the document's recurring defect, and this
plan's own revision 1 committed it four times.

---

## 8. Build order

1. **`test_settlement_purity_guard.py` D1 + D3 + D4** — all pass on the shipped
   tree today, so they land as guard suites (the `readonly_guard` idiom: "its job
   is to fail *later*"). Cheap and independent. (D2 is vacuous until
   `reporting.py` exists; revision 1's claim that this ordering was "the
   load-bearing part of the sequence" is withdrawn — it is merely sensible.)
2. **`reporting.py` types** — `Stratum`, availability/provenance/direction enums,
   `PowerFloor`, `StratumFigure`, `CityEvidence`, `CityEvidenceTable`,
   `ReportStamp`, errors — with the `__post_init__` tests RED first.
3. **`build_programme_report`** — both joins, the ledger, `ProgrammeHeadline`
   H1-H6, `MdwAnnotation`, `ProgrammeReport` P-1/P-2. RED first on
   `test_headline_cannot_be_built_without_mdw`.
4. **`render_markdown`** — section order, MDW annotation, both ledger
   partitions, unconditional provenance block, rule-5 rendering.
5. **D2** (now non-vacuous) + **R1/R2**.
6. **P1** (§5) — independent of 2-5; may run in parallel. Sequenced separately
   because it is the item most likely to need re-calibration, and blocking the
   reporting work on a lint would be wrong.
7. **`scripts/analysis/settlement_programme_report.py`** + §7.5.
8. **`pyproject.toml`** — six test modules + one script path. Then `mypy`,
   `ruff`, `lint-imports`, full `pytest`.
9. **Docs + one committed generated report.** Update
   `docs/plans/backlog/G-20-settlement-gate-remaining.md` (rule 4 and rule 2's
   second clause → Closed; rule 2's first clause → Closed-as-lint; "no consumer"
   → Closed **for the reporting path only**), append PROGRESS.md, and commit one
   real report plus sidecars (§6).

---

## 9. Residuals — claims this plan does NOT enforce

- **R-1.** P1 catches the literal formulation only; paraphrase evades it. §5.
- **R-2.** R1 covers `src/` and `scripts/`, not `tests/`, deliberately.
- **R-3 (reframed).** Revision 1 called input drift an accepted risk. That was
  overstated in one direction and understated in another. Overstated: §6 `main`
  computes the determination and renders in the same process, so the sanctioned
  path cannot pair a stale determination with fresh evidence; the real drift is
  between the cells file and the evidence file, which `ReportStamp`'s digests
  surface. Understated: the *evaluation index* was not a vintage nicety but a
  missing semantic field, now required (§3.2, H-3). What remains: digests are
  printed, not verified against a manifest.
- **R-4.** Nothing forces a report to be *produced*. Closing that needs the
  trading-path consumer, out of scope. This is the honest limit against prereg
  line 845.
- **R-5.** D1 is a ban list, not an allowlist. An allowlist of permitted imports
  was rejected because it fires on every legitimate `typing` addition and would
  be widened reflexively.
- **R-6 (downgraded).** Provenance is still caller-declared, but both fail-open
  halves are closed: hindsight is the default and the block is unconditional. A
  mislabel now produces a *contradicted* claim in a section that always prints,
  not a silently missing caveat.
- **R-7 (new).** "Unconstructible" holds only for headlines routed through
  `ProgrammeHeadline`. A future analysis script writing a determination in prose
  — the idiom `settlement_bucket_guard_band.py` already uses — touches no barrier
  and lands in `docs/evidence/`. **Rule 4 has no prose barrier at all.** This is
  the widest bypass in the plan and is deliberately not closed: a prose barrier
  over generated evidence documents would fire on every legitimate report,
  including the ones this plan generates.
- **R-8 (new).** No carrier for `H2(c,k,q)`, the DOM-10 adverse-selection
  statistic (prereg 280-300), which was CRITICAL in two prereg review rounds.
  `StratumFigure` has no price-decile axis. The axis is not added because a
  second table for a statistic with no estimator is speculative; the omission is
  named instead, and §0.3 forbids describing the output as "the pre-registered
  report".
- **R-9 (new).** D2 constrains the settlement package only. A future
  `src/breezy/strategy/` may import `reporting` and reach a figure freely.

---

## 10. Recorded: the five-vs-four wording

Prereg 854-857 (rule 3) says "two or more of **the five cities**"; rule 4 at
858-860 says "a **four-city** pass". The five-city set is LAX/MDW/MIA/SFO/NYC
(`src/breezy/registry/sites.toml:117-296`) and NYC is excluded from the primary
verdict at 825-833.

The reporting layer sidesteps the wording by enumerating the primary set rather
than counting it (§3.6). But that does **not** resolve the substantive
ambiguity, which is already shipped — see §11.

---

## 11. ESCALATION — for the coordinator, not for this plan to resolve

`programme.py:167-171` tallies rule-3 NO-GOs over the **primary** set only, so
NYC cannot contribute to a programme rejection. Note the direction: **including
NYC would make rejection easier, so the shipped reading is the more permissive
one on rule 3.** It is well-grounded in the NYC exclusion at 825-833, but it is
an implementer's judgement about a binding document's literal text ("the five
cities"), resolved toward more trading.

Prereg §8/§9 establish that this document's ambiguities are resolved in writing,
adversarially, **before computation**. G-17 is authorised and not yet computed.
This is that window.

**A revision-15 clarification must state, in the prereg's own voice:**

1. Whether rule 3's failure tally is taken over the four primary cities or over
   all five including NYC — and if NYC is included for the tally while excluded
   from the verdict, say so explicitly, because those are separable.
2. Whether a city at `OUT_OF_SCOPE_DOM_9` reduces the rule-3 denominator or
   merely is skipped — [R10] at 262-264 excludes such cities from the count, so
   two NO-GOs out of two remaining primaries would reject the programme; confirm
   that is intended.
3. Whether rule 4's "four-city pass" is a literal arity or shorthand for "a pass
   of the primary set", given (1) and (2).

**This plan does not amend the pre-registration.** It is binding and an
amendment needs its own adversarial review (prereg 822-823).

---

## 12. Reviewer claims rejected, with executed evidence

Both reviews were substantially right, and eleven of thirteen findings are
accepted above. Two claims are rejected.

**Rejected — H-7's verification.** The finding's *conclusion* (scan
`docs/evidence/**`) is accepted and implemented. Its stated verification is
false. H-7 asserts that "with wrap normalisation the entire evidence corpus
yields exactly ONE four-token fragment, the prereg's own prohibition, which
marker 5 exempts." Executed against the shipped tree with revision 1's exemption
list and a wrap-normalised splitter, the evidence corpus yields **two**
fragments, and marker 5 exempts **neither**:

```
docs/evidence/asymmetric_gate_prereg_2026-08-26.md
    **Blanket falsification:** any evidence that CLI systematically reads
    **below** METAR falsifies the conservatism claim outright, …
docs/evidence/asymmetric_gate_prereg_2026-08-26.md
    ** No downstream document, requirement, or strategy may assert "METAR reads
    below CLI" as a general property of the estimator
```

The first evades marker 5 on inflection (`falsifies` vs the listed `falsified`);
the second because the sentence reads "may **assert**", while marker 5 lists
"may **not**". Both are exempted only under revision 2's construction-anchored
form (§5.4). The reviewer reached the right answer by the same route it faulted
in revision 1 — reasoning where execution was required — and the correction
matters, because a plan that adopted H-7's scope change *with* revision 1's
exemption list would have landed a barrier firing twice on the prereg.

The stronger consequence: with code-span stripping (§5.2), **no path allowlist
is needed at all** — not for the prereg, not for `docs/evidence/**`, not for
this plan file, not for the barrier's own fixtures. Revision 1's
record-versus-assertion gloss is withdrawn; H-7 was right that it was the
author's distinction and not the prereg's.

**Partially rejected — "H-3 supersedes R-3".** The evaluation index is a
missing required field and is now mandatory. But R-3 is not thereby dissolved:
input digests are printed, not verified against a manifest, so a mismatched
cells/evidence pair still renders. R-3 survives in reduced form (§9).

**Not a rejection, a correction of my own revision 1:** revision 1's §5 said
"This was run against the real corpus, and the answers determine the design." It
was not run. Executed, revision 1's spec fires **four** times on the shipped tree
— once on `G-20-settlement-gate-remaining.md:38` and three times on the plan
file itself, including on the descriptions of its own detector tests — so §8
step 6 would have landed RED and could only have gone green by widening
exemptions before the barrier had ever fired in anger. In a repo whose recurring
defect is prose claiming more than the mechanism delivers, an uncalibrated
calibration section is the finding, not the individual lines. Revision 2's §5
numbers are pasted from a real run.


---

## 13. Cross-check record — executed, not reasoned

Revision 2 added D3, D4 and the §3 types in one pass and never ran them against
each other. That is how the D4/`SignedErrorDirection` collision shipped in a plan
whose own §12 faults a reviewer for reasoning where execution was required. Both
cross-checks below were executed against the committed tree with
`.venv/bin/python`.

**1. D4 against every type §3 requires.** All 111 identifiers §3 specifies —
every enum member, dataclass field, class name, function and constant — were
matched against D4's revision-2 pattern:

```
=== D4 (revision 2 pattern) vs every identifier plan §3 requires ===
  FIRES: enum SignedErrorDirection.METAR_BELOW_CLI   city-keyed-escape=False
         -> BLOCKS THE BUILD

  total identifiers checked: 111
```

Exactly one collision, and no others. Re-run against D4 revision 3 (§4):

```
=== D4 rev3 vs the types plan section 3 REQUIRES (must be empty) ===
  no hits — the plan is buildable

=== D4 rev3 vs planted cases ===
  FIRES  | programme-wide conservatism verdict (D4's reason for existing)
           ('D4a', 'ConservatismVerdict', 'claim vocabulary, not city-keyed')
  clean  | city-keyed conservatism finding (must NOT fire)
  FIRES  | module-level one-sided constant
           ('D4b', 'METAR_BELOW_CLI', 'module-level one-sided direction')
  FIRES  | one-sided direction enum (only one polarity)
           ('D4b', 'Direction.METAR_BELOW_CLI', 'one-sided direction')
  FIRES  | function returning conservatism without a city arg
           ('D4a', 'estimator_conservatism_holds()', 'claim vocabulary, no city parameter')
  clean  | function re-deriving per city (must NOT fire)
```

D4 still catches the thing it was added for, and no longer catches the thing the
plan requires.

**2. D3's pinned allowlist against the committed source.** Field names extracted
by AST from `src/breezy/settlement/coverage.py` and `programme.py` as committed,
compared to the frozensets in §4 D3:

```
  CityDetermination (coverage.py, 8 fields): MATCH
  CityProgrammeDetermination (programme.py, 4 fields): MATCH
  ProgrammeDetermination (programme.py, 8 fields): MATCH

  other annotated classes in the two modules: []

RESULT: allowlist is current, D3 lands green
```

No drift; D3 lands green on the current tree. Note the standing obligation this
creates: **D3 pins the shipped tree, so any future field added to those three
dataclasses fails D3 until the allowlist is edited deliberately.** That is the
intended behaviour, not a defect, and `test_d3_pinned_names_match_the_shipped_tree`
is what will report it.

**Standing rule for any future revision of this plan:** a barrier and a type
introduced in the same revision must be executed against each other before the
revision is issued, and the output pasted here. Reasoning about whether they
collide is not sufficient — twice now it has not been.
