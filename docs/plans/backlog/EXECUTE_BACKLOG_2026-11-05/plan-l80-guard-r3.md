# L80-GUARD r3: reject write-egress literals rebuilt at runtime (V6)

## Trade-offs
- Guard is B4 in `tests/unit/test_polymarket_us_readonly_guard.py` (2683 lines). `find_write_egress_violations` is at L410-464 and `scan_write_egress` at L467. V1 (L420), V2 (L422) and V4 (L447-455) match a single `ast.Constant[str]`, so the incident `POST = "pos" + "t"` gets past all three. V3/V5 match identifiers and are unaffected. PROGRESS row 60 asks for this test and none exists.
- A static-string folder goes in a new support module, and the guard calls it as rule V6. B4 gets wider and nothing is relaxed (L-12). `B4_EXEMPT_PATHS` (L292) and `V2_ORDER_READ_PATH_ALLOWLIST` (L225) stay byte-identical, and a fixture asserts that. Security approved this.
- **Binding model is a may-analysis.** A name's env is (known static candidates, runtime flag). An unknown binding sets the flag and never erases the candidates. V6 fires if any known candidate trips a rule. So V6 is a tripwire over reachable static spellings, not a proof of absence. The module docstring says so.
- Folded and pinned forms are listed in the table under Architecture. Everything pinned is `xfail(strict=True)`.
- Bytes: Phase 0 measures first. Either bytes get folded and the V1/V2 bytes checks widen, or bytes are pinned strict-xfail with counts.
- Test-only. No `src/` change. Nautilus is untouched.

## Acceptance Criteria
1. In a venue-touching module, each V6 site produces exactly one `Violation(path, site.lineno, "V6", msg)` when one of its candidates trips V1-eq, V2-eq or V4-eq and is not just a re-spelling of an atom. `msg` names the equivalent rule and the folded value. Every positive fixture asserts the rule named in `msg`, so an accidental "unfoldable" result cannot pass as a positive.
2. FAIL CLOSED. Any of these limits gives V6 `"unfoldable: <limit> exceeded"`: depth > 64, candidates > 64 (checked before a product is built), folded text > 4096 chars, or fixed-point passes > 16. The message names the limit that actually fired (`Limit` enum value).
3. A bare `Name` is never a V6 site, except as the second argument of `getattr`. That argument is consumed, so it gives one V6 at most.
4. The visitor reports only the outermost site. There is at most one V6 per site, and folded sub-parts are never visited again.
5. No V6 for: purely runtime expressions; genuine shadows (parameters without defaults, comprehension/lambda/class scoping); non-venue modules; re-spellings of a single literal that V1/V2 already report; ordinary self-extension such as `msg="a"; msg+="b"` or `+=` in a loop.
6. Real-tree barriers stay green: `scan_write_egress() == []`, the per-file `== []` asserts, and `test_polymarket_us_write_transport.py:558`, which still finds exactly 4. That test is named "three" but pins four; this is pre-existing and not renamed. If a barrier breaks, see R1/R2.
7. RED is non-vacuous. The incident control `POST = "pos" + "t"` in `scripts/venue/evil.py` gives no V1/V2/V4 on the current guard. This is recorded with the Phase 0 numbers.
8. All existing tests pass unchanged. `ruff check`, `ruff format --check` (touched files only), `lint-imports` and `mypy` on the strict files are clean.

## Edge Cases & NFRs
- `"PO" "ST"` is one Constant, so V1 only. `f"POST"` and `"POST"+""` are re-spellings, so V1 only. Non-string Constants are runtime leaves.
- str and bytes never join one run; the type change ends the run.
- Purity: no I/O, no `eval`, no `literal_eval`. Every walk uses an explicit stack. `ast.parse` itself can hit RecursionError on very deep left-associative chains, so tests cover 70 and 900 terms and nothing larger is claimed.
- `str(...)`, `str.m(...)` and `str.__add__` fold only when no scope in the resolution chain binds `str`.
- `.format` folds only these fields: auto, numbered, or keyword without `.`/`[`, conversion None or `s`, empty spec (this blocks `{:>999999999}`). The receiver must have exactly one candidate.
- `%` folds only `%s`/`%%`. The right side must be a str/bytes value or a Tuple, and the operand count must match.
- f-string identity part: conversion -1 or `s`, and the spec is absent or folds exactly to `{""}` or `{"s"}`.
- Python 3.14 `TemplateStr`/`Interpolation` nodes are runtime (the fold falls through to `None`).
- Cost: one extra pass to build scopes, the fixed point, and one visitor pass, all per venue-touching module.

## Architecture
`find_write_egress_violations` keeps its V1-V5 loop, refactored onto shared predicates. After that loop: `if venue: for site in iter_fold_sites(tree): found += _v6(path, site)`.

**Types** (`tests/support/static_str_fold.py`; `from __future__ import annotations`, `__all__`, no `Any`, mypy strict):
```
Str = str | bytes
class Limit(Enum): DEPTH="depth"; CANDS="candidates"; LENGTH="length"; PASSES="passes"
class FoldLimit(Exception): limit: Limit
@dataclass(frozen=True) Folded: text: Str; atoms: frozenset[Str]        # atoms = source literals concatenated
@dataclass(frozen=True) Val: cands: frozenset[Folded]; partial: bool     # partial = may also be runtime
Entry = Val | Limit                                     # env entry; a Limit entry is an overflowed name
fold -> Val | None                                      # None == RUNTIME: no static candidate
@dataclass(frozen=True) Ctx: scope: Scope; names: frozenset[str]; ordinal: tuple[int, int]
@dataclass(frozen=True) Site: node: ast.expr | ast.stmt; lineno: int; runs: tuple[frozenset[Folded], ...]
                              getattr_arg: bool; limit: Limit | None
MAX_DEPTH = MAX_CANDS = 64; MAX_TEXT = 4096; MAX_PASSES = 16
```

**Form decisions** (review item 4; every form listed is either folded or pinned):
| Form | Decision |
|---|---|
| str Constant, Name, `+` chain, f-string identity part, `str(x)` | fold |
| bytes Constant | Phase 0 (fold or pin) |
| `sep.join(List/Tuple)` with static sep; `Starred(x)` element where x has one candidate (expands to its characters) | fold |
| `x.join(List/Tuple)` with runtime `x` | fold at the site as if sep="" (item 5) |
| `.lower/.upper/.strip/.lstrip/.rstrip/.casefold`; `.replace/.removeprefix/.removesuffix` with static single-candidate args | fold |
| `.title/.capitalize/.swapcase/.ljust/.rjust/.center/.zfill` | pin (one parametrised xfail) |
| `"PO".__add__("ST")`, `str.__add__("PO","ST")`, unbound `str.m(r,*a)` incl. `str.join` | fold (same as `r.m(*a)`) |
| `IfExp` | fold as union of both branches (`partial` if one branch is None) |
| `BoolOp` | fold as union of operands |
| Subscript on literal Tuple/List with Constant int index; Dict with all-Constant keys and Constant key | fold |
| `%s`/`%%`; `.format` (restricted as above) | fold |
| `%c`, `%(a)s` | pin |
| Slices, `reversed(...)`, generator/comprehension/`map(str, ...)`/`list("...")` join elements | pin |
| Function return values `p()`, `mk("PO")`, lambda call | pin |
| Class body local `class K: A="PO"; B=A+"ST"` | fold (class scope) |
| Class attribute `K.M`, cross-module import value | pin (imports are opaque) |
| Loop accumulation `for c in "POST": s += c` | pin (flow-insensitive) |
| `chr`, `.decode`, `operator.methodcaller`, `globals()/vars()[...]` (one xfail), `importlib`, aliased `g=getattr` / `setattr`-installed (one xfail) | pin |
| C3/C5 classification folding | pin, with leaf precondition |
| t-strings (3.14) | runtime; negative fixture with skipif |

**build_scopes(tree) -> (scopes: dict[ast.AST, Scope], bindings: list[Binding])**. Scope has node, kind (MODULE, FUNCTION, CLASS, COMP, LAMBDA), parent, bound set, globals and nonlocals. Binding has scope, name, kind (VALUE, AUG, ELEMENTS, OPAQUE, PARAM), expr, eval_scope, ordinal = `(lineno, col_offset)` of the binding node, and `partial: bool`.

Pass A walks each scope's own region iteratively in source order. It records events but does not enter nested bodies. Decorators, defaults, annotations, bases and the first comprehension `iter` belong to the outer scope.

| Source | Event |
|---|---|
| `Assign` Name target | VALUE(value) |
| `Assign` Tuple/List target with Tuple/List value of the same length, no Starred | pairwise, recursive |
| `Assign` any other target | every Name in it is OPAQUE |
| `Assign` Attribute/Subscript target | none |
| `AnnAssign` with a value | VALUE (without a value: none) |
| `AugAssign(Add)` | AUG(value) |
| `AugAssign`, other operators | OPAQUE |
| `for` / `async for` / comprehension Name target | ELEMENTS if iter is a literal List/Tuple/Set or a str Constant; else OPAQUE. Non-Name targets: their Names are OPAQUE |
| `with ... as Name` | VALUE(context_expr) with partial=True |
| `NamedExpr` | VALUE (routed below) |
| except-as, import aliases, def/class names, `del`, match captures | OPAQUE |
| Parameters | PARAM(default or None); defaults aligned right for positional, `kw_defaults` for keyword-only |
| `*args` / `**kwargs` | OPAQUE |

Pass B routes each event to a target scope. A name in `scope.globals` goes to module scope. A name in `scope.nonlocals` goes to the nearest enclosing FUNCTION scope whose own events bind it (if none, it goes to module scope as OPAQUE). A walrus inside COMP goes to the nearest non-COMP scope, after applying that scope's global/nonlocal. Pass B then adds the name to `target.bound`.

**Context and prior.** One constructor, `ctx_for(stmt, scope)`, is used by both the solver and the visitor. It returns `Ctx(target_scope, all Name targets of stmt, ordinal)`.
```
prior(s, name, ordinal) = join(contrib[b] for b in by_name[(s,name)] if b.ordinal < ordinal)   # Limit -> raise FoldLimit
eval_binding(b): VALUE -> fold(expr, eval_scope, ctx_for(b), 0)
                 AUG   -> fold(BinOp(Name(name), Add, expr), eval_scope, ctx_for(b), 0)      # = prior + value
                 ELEMENTS -> union(fold(elt) for each elt)  (str Constant: its characters)
                 PARAM -> Val(fold(default).cands if default folds else {}, partial=True)
                 OPAQUE -> Val({}, True)
                 then partial |= b.partial
```

**Fixed point.** The solver is global over all bindings sorted by ordinal. Gauss-Seidel: each contribution is written and env is updated immediately.
```
contrib = {b: Val({}, False)}; env[s][n] = join(contribs of (s, n))
for _ in range(MAX_PASSES):
    changed: set[tuple[Scope, str]] = set()
    for b in bindings:
        old = contrib[b]
        if isinstance(old, Limit): continue
        try:    v = eval_binding(b)
        except FoldLimit as e: new = e.limit
        else:   new = Val(old.cands, True) if v is None else Val(old.cands | v.cands, old.partial or v.partial)
                if isinstance(new, Val) and len(new.cands) > MAX_CANDS: new = Limit.CANDS
        if new != old: contrib[b] = new; refresh env[b.scope][b.name]; changed.add((b.scope, b.name))
    if not changed: break
else:
    for (s, n) in changed: all contribs of (s, n) = Limit.PASSES; refresh env
taint: repeat until no new Limit: for b with Val contrib: try eval_binding(b) except FoldLimit e: contrib[b] = e.limit, refresh
finally: env entries Val({}, False) (forward ref / unbased cycle) -> Val({}, True)
```
- Contributions only grow, so the loop terminates.
- A move to Limit counts as a change, so dependent bindings are re-evaluated and raise in turn. After a pass-cap overflow, the taint loop does the same (it is bounded by `len(bindings)`).
- Self-reference uses `prior`, so `S+="ST"`, `S=S+"ST"` and loop `+=` all converge. Only cross-name cycles (`A=B+..; B=A+..`) can grow.

**resolve(name, scope, ctx) -> Val | None**:
```
s = route(scope, name); first = True
while s:
    if name in s.bound and (first or s.kind is not CLASS):
        e = prior(s, name, ctx.ordinal) if ctx and ctx.scope is s and name in ctx.names else env[s][name]
        if isinstance(e, Limit): raise FoldLimit(e)
        return e if e.cands else None
    s, first = s.parent, False
return None   # unbound or builtin
```

**fold(n, s, ctx, d) -> Val | None.** If `d > MAX_DEPTH`, raise `FoldLimit(DEPTH)`.
- Constant str (and bytes if admitted) → `Val({Folded(v, {v})}, False)`.
- Name → `resolve`.
- Add chain, JoinedStr, identity FV, `.join` → `concat` over `parts(n, at_site=False)`. Any RuntimeLeaf, or a leaf that folds to None, makes the result None.
- IfExp and BoolOp → `union`.
- Subscript, `%`, `.format`, method calls, `str()`, `__add__`, unbound `str.m` → evaluate the operands at `d+1`. Product over receiver × args, with a size check first. Apply the real str method inside `try/except (ValueError, IndexError, KeyError, TypeError)`, which yields None.
- Anything else → None.
- `union`: cands = union of non-None cands. partial = any None or any partial. Raise CANDS if over the cap. Return None if cands is empty.
- `concat`, `product(a, b)`: if `len(a)*len(b) > MAX_CANDS`, raise `FoldLimit(CANDS)` before building. `Folded(x.text+y.text, x.atoms|y.atoms)`. Any text longer than `MAX_TEXT` raises `FoldLimit(LENGTH)`. Mixing str and bytes returns None (in site runs it ends the run instead).

**parts(n, s, ctx, at_site) -> (leaves, visit)**, iterative:
```
stack = [n]
while stack: m = stack.pop()
  BinOp(Add): push right, left | JoinedStr: push reversed(values)
  FormattedValue identity: push value | FormattedValue: leaves += RuntimeLeaf(m.value)
  Call(.join, one List/Tuple arg, no kw): sep = m.func.value if fold(sep) else None
      if sep is None and not at_site: leaves += RuntimeLeaf(m); continue
      if sep is None: visit += m.func.value                      # runtime sep: as if ""
      push items reversed, interleaved with sep (if any); Starred(x) with one candidate -> character Constants
  else: leaves += m
```

**site_runs(n, s, ctx) -> (runs, visit)**:
```
leaves, visit = parts(n, s, ctx, True); runs = []; acc = None
for lf in leaves:
    v = None if RuntimeLeaf else fold(lf, s, ctx, 1)
    if v is None: flush acc; visit += (iter_child_nodes(n) if lf is n else [lf.node if RuntimeLeaf else lf])
    else: acc = v.cands if acc is None else product(acc, v.cands)   # type change: flush, acc = v.cands
flush acc; return runs, visit
```

**iter_fold_sites(tree).** Explicit stack of `(node, scope, ctx)`. `push_children(n, s, ctx)` gives the outer parts of a scope-opening node the outer scope, gives its body `scopes[n]`, and pushes Assign/AnnAssign/NamedExpr values with `ctx_for`.
```
pop (n, s, ctx)
if Call(Name getattr) and len(args) >= 2 and not str-Constant(args[1]):
    try: runs, rest = site_runs(args[1], s, ctx); if runs: yield Site(args[1], n.lineno, runs, True, None)
    except FoldLimit as e: yield Site(args[1], n.lineno, (), True, e.limit); rest = []
    push func, args[0], args[2:], keyword values, rest; continue          # args[1] consumed
if AugAssign(Add, Name t): node = n; expr = BinOp(Name(t.id), Add, n.value) at n; ctx = ctx_for(n, s)
elif site_kind(n): node = expr = n        # BinOp Add/Mod, JoinedStr, Call .join/.format/fold-method/__add__/str()/str.m
else: push_children(n, s, ctx); continue
try: runs, rest = site_runs(expr, s, ctx)
except FoldLimit as e: yield Site(node, node.lineno, (), False, e.limit); continue
if runs: yield Site(node, node.lineno, runs, False, None)
push each r in rest with (s, ctx)          # folded parts are never revisited
```

**Predicates** go in the guard and are shared by V1/V2/V4/V6:
- `_is_write_method(t)` = `t.strip().upper() in _WRITE_METHODS`
- `_is_order_path(p, t)` = `_ORDER_PATH_RE.search(t) and not _v2_read_path_allowed(p, t)`
- `_is_write_getattr_name(t)` = `t in _WRITE_ATTRS | _WRITE_FUNCTIONS`
- bytes go through `t.decode("latin-1")`
- `_v2_folded_allowed(p, t)` = `_v2_read_path_allowed(p, t) or _v2_read_path_allowed(p, t.removesuffix("/"))`

**Trailing-`/` ruling** (security ACCEPT; this is a precondition for step 4). One `removesuffix("/")`, never `rstrip`. It is applied only in `_v6`, and V2 is unchanged.

**`_v6(path, site)`**:
- If a limit is set, return V6 `unfoldable: <limit.value> exceeded`.
- Otherwise, for each run and each `f` in `sorted(run, key=text)`, check in this order:
  1. getattr_arg and `_is_write_getattr_name` → "V4".
  2. `_is_write_method(f.text)` and no atom passes it → "V1".
  3. `_ORDER_PATH_RE` matches, `_v2_folded_allowed` is false, and no atom passes `_is_order_path` → "V2".
- The first rule that trips returns one Violation, and nothing else is checked.

**Why the write_transport pin holds** (Phase 0 measures it):
- L205/L241 `f"{base.rstrip('/')}{CANCEL_ALL_PATH|ORDERS_PATH}"`: `base` is runtime. The path runs are atoms V2 already reports, or import-opaque names, so there are no candidates.
- L229/L248: `_WRITE_METHOD` (L58) is `next(iter(PERMITTED_WRITE_METHODS))`. That is a runtime value, so the name has no candidates. The remaining runs `" "` plus trailing text trip nothing.

## File-by-File Plan
| Path | new/mod | Changes | Est |
|---|---|---|---|
| tests/support/static_str_fold.py | new | All of the above. Docstring cites L-80, says "tripwire, not proof", and lists RESIDUAL GAPS with each one's xfail name. | 330-390 |
| tests/unit/test_polymarket_us_readonly_guard.py | mod | (a) import `iter_fold_sites`/`Site`/`Limit`; (b) the predicates, with V1/V2/V4 calling them (same behaviour); (c) `_v2_folded_allowed`, `_v6`; (d) V6 loop after L463; (e) V6 paragraph in the Step-2 docstring, anchored by grepping "V5". Nothing else changes. | +55-65 |
| tests/unit/test_readonly_guard_reconstructed_literals.py | new | All fixtures below, parametrised; incident control; invariance and real-tree asserts | 420-500 |
| docs/core/PROGRESS.md | at close | Row 60 → DONE; Phase 0 numbers; follow-ups (C3/C5 folding, residual xfails) | ~6 |

## Test Strategy
**Phase 0** (measure first in the scratchpad; nothing committed). Run `iter_fold_sites` + `_v6` over `iter_python_sources(EGRESS_SCAN_ROOTS)`. Report exempt and non-exempt paths separately:
- (i) V6 hits per path, with the rule;
- (ii) Limit hits per limit;
- (iii) bytes Constants that would trip V1/V2 or newly classify under C3/C5;
- (iv) count of partial names, for information.

Bytes decision: if (iii) is 0, widen the bytes checks and make `b"PO"+b"ST"` and `b"/v1/orders"` positives. Otherwise pin them strict-xfail and record the counts. STOP if (i) or (ii) is nonzero on a non-exempt path, or if anything changes the L558 count (R1/R2/R7).

**Conventions**
- Venue path is `scripts/venue/evil.py` (C2). `EP` is a copy of `_ENDPOINTS_PATH`. `ALLOWED` is a literal taken from the allowlist.
- `W` = `next(n for n in sorted(_WRITE_ATTRS|_WRITE_FUNCTIONS) if n.upper() not in _WRITE_METHODS)`. Preconditions: `len(W) >= 2`, and an AST walk of each fixture source shows no Name/Attribute spelled `W`. `W1`/`W2` are the halves split at the midpoint.
- Every positive asserts exactly one V6, its lineno, and the rule in `msg`.

**Incident control:** `POST = "pos" + "t"`. On the current guard it gives no V1/V2/V4. After wiring it gives exactly one V6, named V1.

**Positive fixtures**
- Chains and nesting: `"pos"+"t"`; `("P"+"O")+"ST"`; 70-term and 900-term chains; a multi-line parenthesised chain (lineno is the outermost line); `"po"+"st "`.
- f-strings: `f"{'po'}st"`; module `A="PO"` then `f"{A}ST"`; `f"{A!s}ST"`; `f"{f'PO'}ST"`; `f"{'PO'+'ST'}"`.
- Joins: `"".join(["P","O","S","T"])`; `"".join(("P","O","ST"))`; `"O".join(["P","ST"])`; `"".join([*A,"ST"])`; `SEP="";SEP.join(("DEL","ETE"))`; `str.join("",["PO","ST"])` (moved from the xfail list); runtime separator `x.join(["/v1/","orders"])`.
- Format and methods: `"{}ST".format("PO")`; `"%sST" % "PO"`; `str("PO")+"ST"`; `"PO".lower()+"st"`; `"PX".replace("X","O")+"ST"`; `"PO".__add__("ST")`; `str.__add__("PO","ST")`.
- Unions and subscripts: `("PO" if c else "x")+"ST"`; `(x or "PO")+"ST"`; `("PO","ST")[0]+"ST"`; `{"a":"PO"}["a"]+"ST"`.
- Order paths: `"/v1/"+"orders"`; `BASE+"/v1/"+"orders"` on EP (mixed run); `f"{base}/v1/{'orders'}"`; `"".join([base,"/v1/","orders"])`; `ALLOWED+"/cancel"` on EP; `ALLOWED+"//"` on EP.
- Bindings: function-local `a="PO"; return a+"ST"`; `S="PO"; S+="ST"` (V1, not unfoldable); `S="PO"; S=S+"ST"`; `S="x"; S="PO"; x=S+"ST"`; `B=A+"ST"` resolved by the fixed point; class-body `class K: A="PO"; B=A+"ST"`.
- Decoy bindings that may-analysis must survive: `A="PO"` + `for A in (): pass`; `A="PO"` + `del A`; `A="PO"` + `S=os.sep` style dead reassignment `A=h()`; `A="PO"` + `def f(): global A; A=h()` (flipped from negative); `for p in ("PO",): p+"ST"`; `def f(a="PO"): return a+"ST"`; `A,B="PO","ST"; A+B`; walrus in a comprehension `[(A:="PO") for _ in x]; A+"ST"`.
- getattr: `getattr(c, W1+W2)`; `getattr(c, W1.lower()+W2)`; `getattr(c, N)` with `N=W` (V4); `getattr(c, "po"+"st")` (exactly one V6).
- Fail-closed: nesting deeper than 64 → depth; 7-term product of `("a" if c else "b")` → candidates; three 2000-char Constants `+`-joined → length; cycle `A="P"; B=A+"O"; A=B+"S"; X=A+"T"` → V6 "passes" on lines 2, 3 and 4.

**Negative fixtures**
- Shadows: `def g(A): return f"{A}ST"` with module `A="PO"`.
- Runtime: `"po"+x`; `f"{', '.join(xs)}"`; `f"{'granted' if p else 'none'}"`.
- Allowed path: `ALLOWED+"/"+oid` on EP.
- Re-spellings: `"PO" "ST"`, `"POST"+""` and `f"POST"` give V1 only, exactly one violation each. `METHOD="POST"` then bare `METHOD` gives one V1 and no V6. `f"{CANCEL}{x}"` with CANCEL a V2 literal gives V2 only.
- Scope: non-venue module containing `"pos"+"t"`; `from m import A; A+"ST"`.
- Self-extension: `msg="a"; msg+="b"` in a venue module gives no V6; `for x in xs: msg += "b"` gives no V6 and no Limit.
- t-string `t"PO{'ST'}"` (skipif < 3.14): no V6, no crash.
- Invariance: `B4_EXEMPT_PATHS` and `V2_ORDER_READ_PATH_ALLOWLIST` equal frozen literal snapshots.

**Strict xfail fixtures**
- C3 `"api.poly"+"market.us"` with `M="POST"` under `src/breezy/runtime/x.py`, and C5 name split. Precondition for both: no leaf matches `_VENUE_HOST_RE`/`_VENUE_NAME_RE`.
- Class attribute `K.M+"ST"`.
- `"TSOP"[::-1]`; `chr(80)+"OST"`; `b"POST".decode()`.
- `operator.methodcaller(W1+W2)`; `globals()/vars()[W1+W2]` (one parametrised fixture); `importlib` attribute; aliased `g=getattr` and `setattr`-installed alias (one fixture).
- Casing/padding methods (parametrised).
- `%c` and `%(a)s`.
- `def p(): return "PO"; p()+"ST"`; `mk("PO")`; lambda call.
- Join of `reversed`, `[::-1]`, generator, `map(str,…)`, `list("POST")`.
- Loop accumulation `for c in "POST": s += c`.
- `/v1/orders/open/` sub-path on EP.
- `ALLOWED+"/"+oid+"/cancel"` (split run).
- Bytes forms, if Phase 0 says pin.

**RED → GREEN**
1. Write the support module and the test file without the V6 wiring. Run `scripts/ci/run_tests_no_egress.sh tests/unit/test_readonly_guard_reconstructed_literals.py`.
2. Expected RED: the incident control passes, which proves the gap. Every positive fails with "V6 not in rules". Negatives pass. Xfails xfail. Save the tail and read the exit code.
3. Wire V6 and get GREEN.

**Barriers and importers**
- Guard module, including real-tree `scan_write_egress() == []` at L868, 1050, 1074, 1389, 2683 and the exact rule-list asserts at L903, 1229, 1246, 1262, 2614.
- `test_polymarket_us_write_transport.py` L558-573 (`len(raw)==4`) and L575 (`== []`).
- `test_kalshi_s0.py:310`, `test_polymarket_us_auth_smoke.py:687`, `test_polymarket_us_factories.py:747`, `test_polymarket_us_transport.py:563`, `test_probe_containment.py:305`.
- `test_execution_egress_firewall_guard.py` (L125 import, L4157 b4), `test_polymarket_us_fee_guard.py`, `test_venue_positions_read.py`, `test_polymarket_us_capital_flow_pull.py`.
- Then the full gate, delegated, returning 15 lines at most.

## Execution Order
1. Phase 0 and the bytes decision.
2. Support module and test file; record RED.
3. Predicate extraction (behaviour-neutral; the existing suite must be green before V6 is wired).
4. Wire V6 and the docstring for GREEN. Preconditions: the trailing-`/` ruling is recorded, and Phase 0 showed no non-exempt hits.
5. Barrier list, full gate, lint, lint-imports, mypy.
6. python-reviewer in parallel with security-reviewer. Bypass hunting: plant a new evading form and add it as a fixture.
7. Commit by explicit path; update PROGRESS.md.

Steps 1-5 run in sequence. Step 6 is the only parallel seam.

## Risk Register
- **R1: a live offender on a non-exempt path.** The V6 wiring commit does not land until the offender's rename has merged as its own reviewed change (L-80). Until then steps 2-4 stay uncommitted, with a scratchpad snapshot of the untracked files. Never exempt.
- **R2: the L558 `len(raw)==4` pin or a per-file `== []` trips.** STOP and split the re-pin into its own reviewed item.
- **R3: a partial run hits a legitimate read path.** Only `_v2_folded_allowed` applies (exact path; literal or literal+one `/`). Known residuals are pinned.
- **R4: implementer drift** (allowlist edits, weakened comparisons, bare Names as sites, poisoning reintroduced). Guarded by the invariance fixtures, the decoy positives and the incident control. The diff is reviewed against this pseudo-code.
- **R5: residual evasions remain.** Each one is a strict xfail, so an XPASS forces promotion.
- **R6: C3/C5 folding is deferred.** `build_scopes`/`fold` are reusable for it.
- **R7: may-analysis over-approximation or limits fire on real code** (flow-insensitive unions, long help-text `+` chains). Phase 0 measures this. STOP and re-plan; never loosen a limit silently.
- **R8: the guard grows by about 60 lines** (2683 → ~2745).

## LESSONS
- L-80: this delivers the test; rename, never reconstruct.
- L-12: the rule only widens; the exempt list and allowlist are frozen and asserted.
- L-14: the incident control proves the gap on the current guard, and scope is measured on the real tree before wiring.
- Nautilus untouched; no `src/` change; no whole-directory `ruff format`.

## Confidence
- HIGH (~85%): the seam, the may-model, convergence of self-reference, and the barrier inventory.
- MEDIUM (~70%): that the real tree is V6-clean under the over-approximation, and the bytes widening. Phase 0 decides both.
- MEDIUM-HIGH: the line estimates (the module is bigger than in r2; this is the honest number).

## Changes from r2
| Review item | Resolution |
|---|---|
| B1 self-reference | `prior(s, name, ordinal)` over earlier bindings via a shared `ctx_for`. AUG = prior + value. Self-extension negatives added. OVERFLOW only for cross-name cycles; pass-cap fixture added. |
| B2 fixed point | Every transition, including to Limit, sets `changed` per name. Pass cap gives `Limit.PASSES` on the names that changed in the last pass, plus a taint loop. Resolving a Limit raises `FoldLimit` with that exact limit. |
| B3 poisoning | `Val(cands, partial)`. Unknown bindings set `partial` only. Decoy positives added (for/del/global/dead reassign/tuple/walrus). Literal for/comp iterables, with-as, parameter defaults and Tuple-to-Tuple assignment fold. Shadows stay scope-correct. Docstring says "tripwire". |
| B4 forms | Form-decision table: every listed form is folded or pinned. Class body is a positive. t-string is a negative with skipif. |
| B5 runtime sep | `parts(at_site=True)` treats a runtime separator as "" and visits the receiver; fixture added. |
| B6 getattr | `args[1]` is consumed and only its runtime leaves are pushed; `"po"+"st"` single-V6 fixture added. |
| Product check | `len(a)*len(b)` is checked before the product is built. |
| Length cap | `MAX_TEXT = 4096` gives `Limit.LENGTH`; fixture added. |
| Trailing `/` | Single `removesuffix`, only in `_v6`. `"//"` and `"/cancel"` positives, `"/"+oid` negative, two residual xfails. Ruling is a step-4 precondition. |
| R1 | Wiring does not land until the rename has merged; work stays uncommitted with a snapshot. |
| Phase 0 | Exempt and non-exempt reported separately; STOP on non-exempt hits or an L558 change. |
| mypy | `Limit` enum, `Val \| None` for fold, `Site.node: ast.expr \| ast.stmt`. |
| 10k claim | Tests use 70 and 900 terms; the claim is withdrawn. |
| W fixture | `len(W) >= 2` plus a no-Name/Attribute precondition. |
| Factual | L229/L248 `_WRITE_METHOD` is runtime (L58); L558 "three" pins four (pre-existing). |
| Estimate | Module 330-390, guard +55-65, test file 420-500. |