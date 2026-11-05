# L80-GUARD r4 = r3 + this amendment (coordinator ruling after round-3 reviews)

Round-3 verdicts: architect APPROVE (all 6 r2 items resolved; recommends ~40% trim); python-reviewer 7/8/8/8/8/8 = 7.8 (one blocking B1); security REQUEST_CHANGES (one HIGH item 1, one cheap item 2; items 3-7 pin-and-defer).

## Ruling A — adopt the architect's trim (scope reduction; every HIGH stays closed)
Demote to strict xfail (each with a RESIDUAL GAPS docstring entry naming the fixture):
- `.format` and `%` folding (all forms) — the r1 "include" ruling is superseded by the r3 architect's proportionality ruling; security's r3 review lists no HIGH that depends on folding these.
- `Starred(x)` expansion; unbound `str.m(...)`; `"PO".__add__`/`str.__add__`.
- Subscript on literal Tuple/List/Dict.
- Values bound in CLASS, COMP and LAMBDA scopes → those scopes still exist for SHADOWING (parameters and comprehension targets stay scope-correct, no false positives) but hold no candidates (`Val({}, True)`). The class-body positive becomes a strict xfail.
- `for`/comprehension literal-iterable ELEMENTS, `with ... as`, and PARAM-default folding → plain OPAQUE/PARAM(None) bindings (the may-model keeps earlier candidates, so the decoy positives `A="PO"; for A in ()`, `del A`, `global` rebind still fire). `def f(a="PO")` and `for p in ("PO",)` positives become strict xfails.
KEEP: `+` chains, f-string identity parts, `str(x)`, `sep.join(List/Tuple)` incl. runtime-sep-as-"" , `.lower/.upper/.strip/.lstrip/.rstrip/.casefold`, `.replace/.removeprefix/.removesuffix` with static args, `IfExp`/`BoolOp` union (candidates-cap fixture depends on it), may-model, `prior`, fixed point, Limits, getattr consumption, all decoy positives, trailing-`/` ruling + fixtures, Phase 0.
Revised estimates: support module 200-240; guard +55-65; test file 300-340.
Docstring addition (architect): the may-analysis can OVER-approximate (flag safe code); the response is a rename or an R7 re-plan, never a loosened limit or a new exemption.

## Ruling B — security item 1 (HIGH): product over candidates for every multi-input fold
With Ruling A the affected surviving forms are the `.replace/.removeprefix/.removesuffix` RECEIVER and ARGS and the `sep.join` SEPARATOR. Rule: every operand position takes the full candidate set; result = capped cartesian product (`MAX_CANDS` pre-check already exists); "exactly one candidate" wording is deleted everywhere. Positives: `.replace` argument decoy `R="X"; R="Y"; "PXOST".replace(R,"")` (fires on the X candidate); separator decoy `SEP=""; SEP="-"; SEP.join(("DEL","ETE"))`. (The `.format` receiver and Starred decoys become moot under Ruling A and are covered by their strict xfails.)

## Ruling C — security item 2: fold `NamedExpr`
`fold(NamedExpr)` = fold(value) (the binding is already routed by Pass B). Positive fixture `(A:="PO")+"ST"`.

## Ruling D — python B1 (blocking): cross-scope and loop-carried `prior`
`prior(s, name, ordinal)` applies the ordinal restriction ONLY when the statement's own scope IS the target scope (`ctx.scope is s and ctx_origin_scope is s`). When the binding was routed from another scope (`global`/`nonlocal`), self-reference resolves to the JOIN of the target scope's NON-AUG bindings of that name (AUG→AUG would cycle and end in PASSES). Positive fixture: `def f(): global S; S += "ST"` at L2, `S = "PO"` at L10 → V6 (POST). Loop-carried `S="x"; for _ in r: S += "ST"; S = "PO"` → strict xfail + RESIDUAL entry (flow-insensitive). Fixture: two global AUG functions on one name give a defined result (PASSES or fold), never a crash.

## Ruling E — python non-blocking (all adopted)
- Ordinals: `ast.comprehension`, `ast.withitem`, `ast.arguments` have no `lineno`; take the ordinal from `target.lineno`/`context_expr.lineno`/the def node.
- `Scope`, `Binding`: `@dataclass(eq=False)` (identity hashing; they hold mutable sets).
- `Str = str | bytes`: narrow with `isinstance` before `+`; sort key `lambda f: (isinstance(f.text, bytes), f.text)`.
- Synthetic `BinOp(Name, Add, value)` has no lineno: always use `Site.lineno` from the real node.
- Pass-cap false positives on >16-deep forward-reference chains are fail-closed; Phase 0/R7 measure.
- Dead-reassignment over-approximation (`m="PO" … m="x" … m+"ST"` fires) is accepted under "tripwire"; one documented positive fixture.

## Ruling F — security items 3-7: pin and defer (strict xfail + RESIDUAL entry each)
- loop back-edge AUG (see D); empty runtime splice `"PO"+x[:0]+"ST"`, `"PO"+"".join(y)+"ST"`, `"PO"+os.environ.get("K","")+"ST"`; container/attribute-held values (`parts=["PO","ST"]; "".join(parts)`, `T=("PO","ST"); T[0]+T[1]`, `self.m`, `d["a"]`, `CFG["m"]`); `.format(**kw)`/`.format(*t)` (moot under A, still pinned), `operator.add`, `functools.reduce`, `__radd__`, `__mod__`, `c.__getattribute__(W)`, `operator.attrgetter`, `c.__dict__[W]`; decoy `str` rebinding (`str = builtins.str`) disables `str(...)` folding.
- Fixture (security): a candidate that trips V1 but whose atom passes V1 must fall through to rule 3 (V2), not skip to the next candidate; a candidate matching both V1 and V2 reports deterministically (V1 first per `_v6` order).

## Everything else in r3 stands.
Confidence after amendment: HIGH on the model (hand-walks a-f pass per python-reviewer; termination holds); MEDIUM on real-tree cleanliness under over-approximation (Phase 0 decides). Round count: 3 + coordinator amendment; a fourth independent review round was NOT run — the amendment is mechanical adoption of the three reviewers' own fixes, and the implementer brief will carry them verbatim with the code-review stage (Phase 9) as the independent check.
