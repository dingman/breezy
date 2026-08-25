"""Repo-wide read-only barriers B1-B6 for the Polymarket.us slice.

Authority: ``docs/plans/POLYMARKET_US_READONLY_AUTH_PLAN.md`` (revision 2)
sections 2.1 (barriers B1-B6), 9 Step 13, and 11 controls S11/S16.

This is a **guard suite**, not a TDD step: there is no implementation that
makes it pass, because the current tree already satisfies it. Its job is to
fail *later*, when someone adds an order-submission path outside the plan.

Two concrete escapes a peer review proved against the previous barrier
design, and which this module closes:

* **Escape A (outside the adapter package).** A module under ``scripts/``
  does ``from polymarket_us.auth import create_auth_headers`` and POSTs
  ``/v1/orders`` itself. The shipped ban in
  ``test_polymarket_us_phase0_safety.py`` matches only the *name*
  ``PolymarketUS`` imported from the *exact* module string
  ``polymarket_us``; ``polymarket_us.auth`` is a different string and was
  not matched at all. Closed by :func:`find_sdk_import_violations`, which
  prefix-matches on the first dotted segment and scans ``src/``,
  ``scripts/`` **and** ``tests/``.
* **Escape B (inside the package).** ``nautilus_pyo3.HttpClient`` is
  POST-capable, so ``client._transport._client.post(...)`` reaches a write
  verb without the string literal ``"POST"`` appearing anywhere. Closed by
  the attribute rule in :func:`find_write_egress_violations`.

DETECTION ALGORITHM (stated in full so it is falsifiable, and exercised by
the ``*_detects_*`` proof-by-construction tests below -- no barrier here is
allowed to pass vacuously).

Step 1 -- classify each ``*.py`` file under ``src/`` and ``scripts/`` as
*venue-touching* or not. A file is venue-touching when ANY of:

  (C1) its path is under ``src/breezy/adapters/polymarket_us/``;
  (C2) its path is under ``scripts/venue/``;
  (C3) any ``ast.Constant`` string in it matches
       ``(?i)\\b(?:api|gateway)\\.polymarket\\.us\\b`` or
       ``(?i)\\bpolymarketexchange\\.com\\b``;
  (C4) it imports a module whose first dotted segment is ``polymarket_us``
       (absolute imports only), or imports ``breezy.adapters.polymarket_us``
       (or a submodule of it).

A file that is not venue-touching is exempt from the write-verb rules. That
exemption is deliberate and load-bearing: ``src/breezy/runtime/health.py``
legitimately does ``self._client.post(url, json=...)`` to an
operator-configured alert webhook, which is not a venue egress path. A
blanket repo-wide ban on the token ``POST`` would either fail on that, on
the constant ``POST_SETTLEMENT_REVISION``, or on prose in docstrings --
and a barrier that must be silenced is a barrier that will be silenced.

Step 2 -- inside a venue-touching file, report a violation for ANY of:

  (V1) an ``ast.Constant`` ``str`` whose stripped, upper-cased value is
       exactly one of ``POST``/``PUT``/``PATCH``/``DELETE``;
  (V2) an ``ast.Constant`` ``str`` matching ``(?i)/v\\d+/orders?\\b`` --
       the order-path shape;
  (V3) an ``ast.Attribute`` whose ``attr`` is one of ``post``/``put``/
       ``patch``/``delete``/``request``, on any receiver. Inside a
       venue-touching module there is no legitimate receiver for those
       names, so no receiver-type inference is needed -- which matters,
       because ``client._transport._client.post`` is exactly the case
       where receiver inference is statically undecidable;
  (V4) a ``getattr(x, "post")``-style call: ``ast.Call`` to the bare name
       ``getattr`` whose second positional argument is a constant string
       in the V3 name set. Without this, V3 is trivially bypassed.

RESIDUAL GAP, stated rather than papered over: a module that neither names
a venue host nor imports the venue SDK, and that builds its URL from an
environment variable at runtime, is not statically detectable by any rule
here. That path is covered by other layers, not this one -- B1/B2 (the
signer refuses to sign a non-GET, so such a request cannot be authenticated
by Breezy code), B6 (the shipped chokepoint), and the pytest socket
kill-switch plus the ``nautilus_pyo3`` constructor block in
``tests/conftest.py``.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Roots scanned for the write-verb barrier (B4).
EGRESS_SCAN_ROOTS = ("src", "scripts")

#: Roots scanned for the SDK import ban (B5) and the ``.get_value()`` ban (S16).
REPO_WIDE_SCAN_ROOTS = ("src", "scripts", "tests")

#: The single module barrier B5 permits to import the SDK signing package.
#: Plan Step 4 makes it the differential oracle against
#: ``polymarket_us.auth.create_auth_headers``; nothing else may reach it.
SDK_IMPORT_ORACLE = "tests/unit/test_polymarket_us_signing.py"

#: First dotted segment of the venue SDK distribution's import package.
SDK_ROOT_PACKAGE = "polymarket_us"

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_WRITE_ATTRS = frozenset({"post", "put", "patch", "delete", "request"})
_ORDER_PATH_RE = re.compile(r"/v\d+/orders?\b", re.IGNORECASE)
_VENUE_HOST_RE = re.compile(
    r"\b(?:api|gateway)\.polymarket\.us\b|\bpolymarketexchange\.com\b",
    re.IGNORECASE,
)
_ADAPTER_PACKAGE = "breezy.adapters.polymarket_us"


@dataclass(frozen=True, slots=True)
class Violation:
    """One barrier finding: where it is, and which rule fired."""

    path: str
    lineno: int
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.path}:{self.lineno}: [{self.rule}] {self.detail}"


# --------------------------------------------------------------------------
# Source enumeration
# --------------------------------------------------------------------------


def iter_python_sources(roots: tuple[str, ...]) -> Iterator[tuple[str, str]]:
    """Yield ``(repo_relative_path, source_text)`` for every scanned module."""
    for root in roots:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            yield (
                path.relative_to(REPO_ROOT).as_posix(),
                path.read_text(encoding="utf-8"),
            )


# --------------------------------------------------------------------------
# Step 1 -- venue-touching classification (C1-C4)
# --------------------------------------------------------------------------


def _imported_module_strings(tree: ast.AST) -> Iterator[str]:
    """Yield every absolutely-imported module string in ``tree``.

    Relative imports (``from .polymarket_us import x``, ``level > 0``) are
    deliberately skipped: their ``node.module`` is a bare package name that
    would otherwise collide with the SDK's top-level name.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module


def is_venue_touching(path: str, tree: ast.AST) -> bool:
    """Return True when ``path`` may sit on a Polymarket.us egress path."""
    if path.startswith("src/breezy/adapters/polymarket_us/"):
        return True  # C1
    if path.startswith("scripts/venue/"):
        return True  # C2
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _VENUE_HOST_RE.search(node.value)
        ):
            return True  # C3
    for module in _imported_module_strings(tree):
        segments = module.split(".")
        if segments[0] == SDK_ROOT_PACKAGE:
            return True  # C4
        if module == _ADAPTER_PACKAGE or module.startswith(_ADAPTER_PACKAGE + "."):
            return True  # C4
    return False


# --------------------------------------------------------------------------
# Step 2 -- B4 write-egress rules (V1-V4)
# --------------------------------------------------------------------------


def find_write_egress_violations(path: str, source: str) -> list[Violation]:
    """Apply rules V1-V4 to one module. Non-venue-touching modules pass."""
    tree = ast.parse(source, filename=path)
    if not is_venue_touching(path, tree):
        return []

    found: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
            if text.strip().upper() in _WRITE_METHODS:
                found.append(Violation(path, node.lineno, "V1", f"write-method literal {text!r}"))
            if _ORDER_PATH_RE.search(text):
                found.append(Violation(path, node.lineno, "V2", f"order-path literal {text!r}"))
        elif isinstance(node, ast.Attribute) and node.attr in _WRITE_ATTRS:
            found.append(
                Violation(path, node.lineno, "V3", f"write-capable attribute .{node.attr}")
            )
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
            and node.args[1].value in _WRITE_ATTRS
        ):
            found.append(
                Violation(
                    path,
                    node.lineno,
                    "V4",
                    f"getattr bypass to .{node.args[1].value}",
                )
            )
    return found


def scan_write_egress(roots: tuple[str, ...] = EGRESS_SCAN_ROOTS) -> list[Violation]:
    return [
        v
        for path, src in iter_python_sources(roots)
        for v in find_write_egress_violations(path, src)
    ]


# --------------------------------------------------------------------------
# B5 -- SDK signing-module import ban, prefix matched
# --------------------------------------------------------------------------


def find_sdk_import_violations(path: str, source: str) -> list[Violation]:
    """Flag any absolute import whose first dotted segment is the venue SDK.

    Prefix matching on ``module.split(".")[0]`` is the whole point: the
    shipped ban compared ``node.module == "polymarket_us"`` and therefore
    saw nothing at all in ``from polymarket_us.auth import
    create_auth_headers``.
    """
    if path == SDK_IMPORT_ORACLE:
        return []
    tree = ast.parse(source, filename=path)
    found: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == SDK_ROOT_PACKAGE:
                    found.append(Violation(path, node.lineno, "B5", f"import {alias.name}"))
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
            and node.module.split(".")[0] == SDK_ROOT_PACKAGE
        ):
            names = ", ".join(alias.name for alias in node.names)
            found.append(Violation(path, node.lineno, "B5", f"from {node.module} import {names}"))
    return found


def scan_sdk_imports(roots: tuple[str, ...] = REPO_WIDE_SCAN_ROOTS) -> list[Violation]:
    return [
        v for path, src in iter_python_sources(roots) for v in find_sdk_import_violations(path, src)
    ]


# --------------------------------------------------------------------------
# S16 -- ``.get_value()`` inside an ``assert``
# --------------------------------------------------------------------------


def find_get_value_in_assert(path: str, source: str) -> list[Violation]:
    """Flag ``SecureString.get_value()`` calls lexically inside an ``assert``.

    pytest rewrites assertions in test modules and conftest files to print
    every operand on failure, so ``assert creds.secret_key.get_value() ==
    expected`` dumps cleartext credential material into CI logs.

    Compare into a local first and assert on the resulting bool. Do NOT reach
    for ``SecureString.get_redacted()``: it returns ``value[:4] + "..." +
    value[-4:]`` (``nautilus_trader/common/secure.py:100-102``) and so
    publishes eight characters of the secret. That helper is separately banned
    by ``tests/unit/test_polymarket_us_secret_exposure.py``.
    """
    tree = ast.parse(source, filename=path)
    found: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "get_value"
            ):
                found.append(Violation(path, inner.lineno, "S16", ".get_value() inside an assert"))
    return found


def scan_get_value_in_assert(roots: tuple[str, ...] = REPO_WIDE_SCAN_ROOTS) -> list[Violation]:
    return [
        v for path, src in iter_python_sources(roots) for v in find_get_value_in_assert(path, src)
    ]


# ==========================================================================
# Barrier B4 -- repo-wide write-egress ban
# ==========================================================================


def test_no_write_method_literal_or_write_attribute_in_src_or_scripts() -> None:
    violations = scan_write_egress()
    assert violations == [], "B4 violations:\n" + "\n".join(str(v) for v in violations)


def test_b4_detects_a_write_method_literal_on_a_venue_touching_module() -> None:
    source = 'BASE = "https://api.polymarket.us"\nMETHOD = "POST"\n'
    rules = {v.rule for v in find_write_egress_violations("scripts/evil.py", source)}
    assert "V1" in rules


def test_b4_detects_an_order_path_literal() -> None:
    source = 'URL = "https://api.polymarket.us/v1/orders"\n'
    rules = {v.rule for v in find_write_egress_violations("scripts/evil.py", source)}
    assert "V2" in rules


def test_b4_detects_escape_b_chained_attribute_access_without_any_post_literal() -> None:
    """The exact escape: no ``"POST"`` string anywhere in the source."""
    source = "async def go(client):\n    return await client._transport._client.post(path, body)\n"
    path = "src/breezy/adapters/polymarket_us/http.py"
    violations = find_write_egress_violations(path, source)
    assert "POST" not in source
    assert {v.rule for v in violations} == {"V3"}


def test_b4_detects_the_getattr_bypass_of_the_attribute_rule() -> None:
    source = 'import polymarket_us\n\n\ndef go(c):\n    return getattr(c, "post")(1)\n'
    rules = {v.rule for v in find_write_egress_violations("scripts/evil.py", source)}
    assert "V4" in rules


def test_b4_classifies_a_scripts_module_importing_the_sdk_as_venue_touching() -> None:
    """Escape A's module becomes in-scope for B4 via classifier rule C4."""
    source = "from polymarket_us.auth import create_auth_headers\n\nM = 'DELETE'\n"
    violations = find_write_egress_violations("scripts/analysis/whatever.py", source)
    assert [v.rule for v in violations] == ["V1"]


def test_b4_does_not_fire_on_a_non_venue_module_that_posts_to_an_operator_webhook() -> None:
    """The exemption that keeps this barrier from being silenced wholesale."""
    source = "class Sink:\n    def emit(self, p):\n        self._client.post(self._url, json=p)\n"
    assert find_write_egress_violations("src/breezy/runtime/health.py", source) == []


def test_b4_actually_covers_the_shipped_health_module_as_a_non_venue_file() -> None:
    """Guards the exemption itself: health.py must still be non-venue-touching."""
    path = REPO_ROOT / "src" / "breezy" / "runtime" / "health.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assert is_venue_touching("src/breezy/runtime/health.py", tree) is False


def test_b4_scan_covers_both_src_and_scripts() -> None:
    scanned = {path for path, _ in iter_python_sources(EGRESS_SCAN_ROOTS)}
    assert any(p.startswith("src/") for p in scanned)
    assert any(p.startswith("scripts/") for p in scanned)


# ==========================================================================
# Barrier B5 -- SDK signing-module import ban
# ==========================================================================


def test_sdk_signing_module_is_imported_only_by_the_named_oracle_test() -> None:
    violations = scan_sdk_imports()
    assert violations == [], "B5 violations:\n" + "\n".join(str(v) for v in violations)


def test_b5_detects_escape_a_the_submodule_import_the_shipped_ban_misses() -> None:
    source = "from polymarket_us.auth import create_auth_headers\n"
    # The shipped ban's predicate, reproduced verbatim, sees nothing here.
    tree = ast.parse(source)
    shipped_ban_hits = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        and n.module == "polymarket_us"
        and "PolymarketUS" in {a.name for a in n.names}
    ]
    assert shipped_ban_hits == []
    assert [v.rule for v in find_sdk_import_violations("scripts/venue/smoke.py", source)] == ["B5"]


def test_b5_detects_a_plain_dotted_import_of_the_sdk() -> None:
    source = "import polymarket_us.auth as pmauth\n"
    assert find_sdk_import_violations("scripts/venue/smoke.py", source) != []


def test_b5_permits_the_named_oracle_test_only() -> None:
    source = "from polymarket_us.auth import create_auth_headers\n"
    assert find_sdk_import_violations(SDK_IMPORT_ORACLE, source) == []
    assert find_sdk_import_violations("tests/unit/test_something_else.py", source) != []


def test_b5_does_not_confuse_the_breezy_adapter_package_with_the_sdk() -> None:
    source = "from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials\n"
    assert find_sdk_import_violations("src/breezy/adapters/polymarket_us/http.py", source) == []


def test_b5_does_not_fire_on_a_relative_import_of_a_local_module_of_the_same_name() -> None:
    source = "from .polymarket_us import thing\n"
    assert find_sdk_import_violations("src/breezy/adapters/__init__.py", source) == []


def test_b5_scan_covers_tests_as_well_as_src_and_scripts() -> None:
    scanned = {path for path, _ in iter_python_sources(REPO_WIDE_SCAN_ROOTS)}
    assert any(p.startswith("tests/") for p in scanned)
    assert any(p.startswith("src/") for p in scanned)
    assert any(p.startswith("scripts/") for p in scanned)


# ==========================================================================
# Barrier B6 / non-goals -- no execution client, no chokepoint caller
# ==========================================================================


def test_adapter_package_defines_no_live_execution_client() -> None:
    banned = {"LiveExecutionClient", "LiveExecClientFactory", "LiveExecutionClientFactory"}
    offenders: list[Violation] = []
    for path, source in iter_python_sources(("src", "scripts")):
        tree = ast.parse(source, filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
                    if name in banned:
                        offenders.append(Violation(path, node.lineno, "NG", f"{node.name}({name})"))
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    if alias.name in banned:
                        offenders.append(
                            Violation(path, node.lineno, "NG", f"imports {alias.name}")
                        )
    assert offenders == [], "execution-client violations:\n" + "\n".join(str(o) for o in offenders)


def test_safety_chokepoint_has_no_caller_in_this_slice() -> None:
    """B6: the shipped chokepoint stays uncalled by src/ and scripts/.

    A caller would mean an order path exists. Its own definition site and
    its tests are naturally excluded because only ``src`` and ``scripts``
    are scanned, and the definition is a ``FunctionDef``, not a ``Call``.
    """
    callers: list[Violation] = []
    for path, source in iter_python_sources(("src", "scripts")):
        tree = ast.parse(source, filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name == "assert_live_order_submission_permitted":
                    callers.append(Violation(path, node.lineno, "B6", "chokepoint called"))
    assert callers == [], "B6 violations:\n" + "\n".join(str(c) for c in callers)


def test_b6_detects_a_call_to_the_chokepoint() -> None:
    """Proof the B6 scan is not vacuous, using the same predicate shape."""
    source = (
        "from breezy.adapters.polymarket_us.safety import (\n"
        "    assert_live_order_submission_permitted,\n"
        ")\n"
        "\n"
        "\n"
        "def submit():\n"
        "    assert_live_order_submission_permitted(credentials=c, permit=p)\n"
    )
    tree = ast.parse(source)
    hits = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", "") == "assert_live_order_submission_permitted"
    ]
    assert len(hits) == 1


# ==========================================================================
# S16 -- ``.get_value()`` inside an ``assert``
# ==========================================================================


def test_get_value_never_appears_inside_an_assert_statement() -> None:
    """No quarantine, no exemptions: S16 holds across src, scripts and tests.

    The temporary ``GET_VALUE_ASSERT_QUARANTINE`` that once held seven known
    violations is gone -- every one was rewritten to compare into a local and
    assert on the resulting bool, so a failing assertion prints ``False``
    rather than the cleartext secret.
    """
    violations = scan_get_value_in_assert()
    assert violations == [], (
        "S16 violations (pytest assertion rewriting would print the cleartext "
        "secret into CI logs; compare into a local and assert on the bool):\n"
        + "\n".join(str(v) for v in violations)
    )


def test_s16_detects_the_cleartext_comparison_it_targets() -> None:
    source = "def test_x(creds, expected):\n    assert creds.secret_key.get_value() == expected\n"
    assert [v.rule for v in find_get_value_in_assert("tests/unit/test_x.py", source)] == ["S16"]


def test_s16_permits_get_value_outside_an_assert() -> None:
    source = (
        "def check(creds):\n    if not creds.secret_key.get_value():\n        raise ValueError\n"
    )
    path = "src/breezy/adapters/polymarket_us/credentials.py"
    assert find_get_value_in_assert(path, source) == []
