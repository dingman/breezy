"""Repo-wide read-only barriers B1-B6 for the Polymarket.us slice.

Authority: ``docs/plans/archive/POLYMARKET_US_READONLY_AUTH_PLAN.md`` (revision 2)
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
  verb without the string literal ``"POST"`` appearing anywhere. A second
  escape through ``transport._get.__self__.post`` exists if the transport
  stores a bound pyo3 method. Closed by the runtime receiver-graph check in
  :func:`find_write_capable_receiver_exposures` plus the attribute rule in
  :func:`find_write_egress_violations`.

DETECTION ALGORITHM (stated in full so it is falsifiable, and exercised by
the ``*_detects_*`` proof-by-construction tests below -- no barrier here is
allowed to pass vacuously).

Step 1 -- classify each ``*.py`` file under ``src/`` and ``scripts/`` as
*venue-touching* or not. A file is venue-touching when ANY of:

  (C1) its path is under ``src/breezy/adapters/polymarket_us/``;
  (C2) its path is under ``scripts/venue/`` or ``scripts/probes/``;
       (``scripts/probes/`` is covered pre-emptively per
       ``DATA_CAPTURE_AND_RISK_PLAN.md`` R15: a probe placed there taking
       its base URL from config and importing only ``breezy.ingest.http``
       would otherwise match NONE of C1-C4, so the write-verb and
       order-path rules would silently not apply to it);
  (C3) any ``ast.Constant`` string in it matches
       ``(?i)\\b(?:api|gateway)\\.polymarket\\.us\\b`` or
       ``(?i)\\bpolymarketexchange\\.com\\b``;
  (C4) it imports a module whose first dotted segment is ``polymarket_us``
       (absolute imports only), or imports ``breezy.adapters.polymarket_us``
       (or a submodule of it);
  (C5) any ``ast.Constant`` string in it matches ``(?i)polymarket`` -- the
       venue's NAME rather than its host. C3 matches only the two origins;
       a module that names the venue any other way matched nothing. The
       concrete escape C5 closes is a module OUTSIDE the adapter package
       that takes its base URL from the environment::

           BASE = os.environ["POLYMARKET_US_API_BASE_URL"]

       -- one of the four override variables the shipped config already
       declares (``config.py:55-58``). It names no host (C3 miss), imports
       no venue module (C4 miss), and lives outside both path prefixes (C1
       and C2 miss), so before C5 every write-verb rule silently did not
       apply to it. Measured before landing: C5 newly classifies 15 shipped
       modules and adds ZERO V1-V4, F1 or E0-E3 findings.

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

RESIDUAL GAP, stated rather than papered over, and NARROWER since C5: a
module that names the venue NOWHERE -- not its host, not its name, not its
SDK, not its adapter package -- and that builds its URL from an environment
variable whose name also does not name the venue, is not statically
detectable by any rule here. C5 closed the case where the environment
variable itself names the venue, which is every variable the shipped config
declares; what is left is a module that is anonymous about its destination
end to end. That path is covered by other layers, not this one -- B1/B2 (the
signer refuses to sign a non-GET, so such a request cannot be authenticated
by Breezy code), B6 (the shipped chokepoint), B7 (nothing may mint a permit),
and the pytest socket kill-switch plus the ``nautilus_pyo3`` constructor
block in ``tests/conftest.py``.

BARRED CALLEES (B6, B7) -- two functions in ``safety.py`` that no module in
``src/`` or ``scripts/`` may CALL, at zero, with no allowlist:

  (B6) ``assert_live_order_submission_permitted`` -- the chokepoint. A caller
       means an order path exists;
  (B7) ``issue_live_trading_permit`` -- the ISSUER. It derives every field
       from the operator's environment and takes no ceiling parameter, so a
       caller anywhere in the tree mints authority for itself out of nothing
       but ``os.environ``. It shipped with no caller barrier at all and was
       re-exported from the package ``__init__``; both are closed here (the
       export by removal, the reachability by this rule).

There is deliberately NO allowlist for either. A one-entry allowlist that is
empty is a zero-entry allowlist, and shipping the structure unused is how it
later gets an entry without a paired assertion. The plan that first needs a
caller introduces the allowlist together with its ``== 1`` pin.
"""

from __future__ import annotations

import ast
import inspect
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

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
#: C5 -- the venue's NAME anywhere in a string constant. Deliberately broader
#: than ``_VENUE_HOST_RE``: it has to match an environment-variable NAME
#: (``POLYMARKET_US_API_BASE_URL``) and a venue-id string, not just an origin.
#: Broad classification is the safe direction -- it only ever puts MORE modules
#: under the write-verb rules.
_VENUE_NAME_RE = re.compile(r"polymarket", re.IGNORECASE)
_ADAPTER_PACKAGE = "breezy.adapters.polymarket_us"

#: C2 -- script directories whose contents are venue-touching BY PATH.
#:
#: ``scripts/venue/`` is where the venue smoke and the P2 probes live.
#: ``scripts/probes/`` carries no file today and is listed anyway, per
#: ``docs/plans/DATA_CAPTURE_AND_RISK_PLAN.md`` R15: the barrier has to be in
#: place BEFORE the directory exists, or the first probe written there is
#: exempt from every write-verb rule and nobody notices.
VENUE_TOUCHING_SCRIPT_PREFIXES: tuple[str, ...] = (
    "scripts/venue/",
    "scripts/probes/",
)


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
    if any(path.startswith(prefix) for prefix in VENUE_TOUCHING_SCRIPT_PREFIXES):
        return True  # C2
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if _VENUE_HOST_RE.search(node.value):
            return True  # C3
        if _VENUE_NAME_RE.search(node.value):
            return True  # C5
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
# B3 runtime receiver graph -- no pyo3 client exposed through attributes
# --------------------------------------------------------------------------


class _WriteCapableHttpClient:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        return

    async def get(self, *_args: Any, **_kwargs: Any) -> object:
        return object()

    def post(self, *_args: Any, **_kwargs: Any) -> object:
        return object()


def find_write_capable_receiver_exposures(obj: object) -> list[Violation]:
    """Find ordinary attribute paths exposing an object with a write verb.

    This intentionally checks two Python-level mistakes a source scan cannot
    prove away: storing the client directly, and storing a bound method whose
    ``__self__`` is the client.
    """
    found: list[Violation] = []
    for name in dir(obj):
        if name.startswith("__"):
            continue
        value = getattr(obj, name)
        if callable(getattr(value, "post", None)):
            found.append(
                Violation(
                    "<object>",
                    0,
                    "B3",
                    f"{name} exposes write-capable receiver directly",
                )
            )
        receiver = getattr(value, "__self__", None)
        if receiver is not None and callable(getattr(receiver, "post", None)):
            found.append(
                Violation(
                    "<object>",
                    0,
                    "B3",
                    f"{name}.__self__ exposes write-capable receiver",
                )
            )
    return found


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
# B6 / B7 -- functions no module in src/ or scripts/ may CALL
# --------------------------------------------------------------------------

#: Callee name -> barrier id. A DENY table, not an allowlist: there is no
#: exemption mechanism here and adding one is itself the change a reviewer
#: must see. Equality-pinned by
#: ``tests/unit/test_cage_rule_constants_are_pinned.py``, so an entry cannot
#: be dropped by a one-token diff.
BARRED_CALLEES: Mapping[str, str] = MappingProxyType(
    {
        "assert_live_order_submission_permitted": "B6",
        "issue_live_trading_permit": "B7",
    }
)


def find_barred_callers(path: str, source: str) -> list[Violation]:
    """Report every call in ``source`` to a barred ``safety.py`` function.

    The single implementation of B6 and B7: the live scans below and their
    proof-by-construction tests run this same function, so the proofs prove
    the enforced rule rather than a copy of it.

    A definition site is not a call site -- ``safety.py`` defines both names
    as ``FunctionDef`` nodes and is therefore never reported by its own rule.
    The signature takes ``(path, source)`` and nothing else, deliberately:
    an exemption parameter is the shape an allowlist arrives in, and
    ``test_b7_the_caller_barrier_has_no_exemption_mechanism`` pins its
    absence.
    """
    tree = ast.parse(source, filename=path)
    found: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        rule = BARRED_CALLEES.get(name)
        if rule is not None:
            found.append(Violation(path, node.lineno, rule, f"calls {name}()"))
    return found


def scan_barred_callers(roots: tuple[str, ...] = EGRESS_SCAN_ROOTS) -> list[Violation]:
    return [v for path, src in iter_python_sources(roots) for v in find_barred_callers(path, src)]


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


#: RED 5 / counter 2. A module OUTSIDE the adapter package that reaches the
#: venue with its base URL read from the environment. It names no host (C3
#: miss), imports no venue module and no SDK (C4 miss), and is under neither
#: path prefix (C1/C2 miss). The only thing that betrays it is the NAME of
#: the environment variable -- which is one of the four the shipped config
#: already declares (``config.py:55-58``).
_PLANTED_ENVIRONMENT_DRIVEN_EGRESS = (
    "import os\n"
    "\n"
    "import httpx\n"
    "\n"
    "BASE = os.environ['POLYMARKET_US_API_BASE_URL']\n"
    "\n"
    "\n"
    "def fetch(path):\n"
    "    return httpx.get(BASE + path)\n"
)


def test_c5_classifies_an_environment_driven_egress_module_outside_the_package() -> None:
    """Counter 2: a module that escapes the classifier escapes every rule.

    This is the negative case with content. Asserting ``is_venue_touching``
    is True for the paths section 5 of the plan already lists is vacuous --
    every one of them passes on the C1 string prefix alone, before any file
    exists.
    """
    path = "src/breezy/egress_outside_the_package.py"
    tree = ast.parse(_PLANTED_ENVIRONMENT_DRIVEN_EGRESS, filename=path)
    assert is_venue_touching(path, tree) is True


def test_c5_the_planted_module_matches_none_of_c1_to_c4() -> None:
    """Pins WHY the module was undetected, so C5 cannot be dropped as spare.

    Each of the four shipped rules is re-evaluated here against the planted
    source; if a later edit made one of them cover this case, this test fails
    and the redundancy is surfaced rather than assumed.
    """
    path = "src/breezy/egress_outside_the_package.py"
    tree = ast.parse(_PLANTED_ENVIRONMENT_DRIVEN_EGRESS, filename=path)

    assert not path.startswith("src/breezy/adapters/polymarket_us/")  # C1
    assert not any(path.startswith(prefix) for prefix in VENUE_TOUCHING_SCRIPT_PREFIXES)  # C2
    hosts = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and _VENUE_HOST_RE.search(n.value)
    ]
    assert hosts == []  # C3
    for module in _imported_module_strings(tree):
        assert module.split(".")[0] != SDK_ROOT_PACKAGE  # C4
        assert not module.startswith(_ADAPTER_PACKAGE)  # C4


def test_c5_makes_the_write_verb_rules_apply_to_the_planted_module() -> None:
    """Classification is only worth what it switches on. This is that."""
    path = "src/breezy/egress_outside_the_package.py"
    source = _PLANTED_ENVIRONMENT_DRIVEN_EGRESS + (
        "\n\ndef send(body):\n    return httpx.post(BASE, json=body)\n"
    )
    rules = {v.rule for v in find_write_egress_violations(path, source)}
    assert "V3" in rules


def test_c5_does_not_classify_a_module_that_names_no_venue_at_all() -> None:
    """Non-vacuity in the other direction: C5 is a token match, not a blanket."""
    source = "import os\n\nBASE = os.environ['SOME_OTHER_BASE_URL']\n"
    tree = ast.parse(source)
    assert is_venue_touching("src/breezy/runtime/whatever.py", tree) is False


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
# Barrier B3 -- no write-capable pyo3 client exposed through transport object
# ==========================================================================


def test_b3_constructed_transport_exposes_no_write_capable_receiver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nautilus_trader.core import nautilus_pyo3

    from breezy.adapters.polymarket_us.transport import NautilusHttpTransport

    monkeypatch.setattr(nautilus_pyo3, "HttpClient", _WriteCapableHttpClient)

    transport = NautilusHttpTransport(
        timeout_secs=5,
        default_quota=object(),
        keyed_quotas=[],
        default_headers={"User-Agent": "breezy-b3-test/1.0 (+mailto:ops@example.com)"},
    )

    violations = find_write_capable_receiver_exposures(transport)
    assert violations == [], "B3 receiver exposure(s):\n" + "\n".join(
        str(v) for v in violations
    )


def test_b3_detector_catches_the_bound_method_self_escape() -> None:
    class LeakyTransport:
        __slots__ = ("_get",)

        def __init__(self) -> None:
            client = _WriteCapableHttpClient()
            self._get = client.get

    violations = find_write_capable_receiver_exposures(LeakyTransport())

    assert [v.rule for v in violations] == ["B3"]
    assert "_get.__self__ exposes write-capable receiver" in violations[0].detail


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


#: The execution-client surface this slice is allowed to contain, as an exact
#: MAP from path to ``"ClassName(BaseName)"`` -- never a path allowlist.
#:
#: NARROWED BY EXEC_SPINE R-4, and NARROWED AGAIN BY W. R-4 IS the live
#: execution client, so a rule reading "no live execution client exists"
#: could not survive it and stating otherwise would be a lie about shipped
#: code. W registers that client with a REAL node -- the whole point of the
#: increment (``docs/plans/EXEC_SPINE_R5_R6_2026-09-02.md`` section 3) -- via
#: exactly one ``LiveExecClientFactory`` subclass, so the second row below is
#: a deliberate, reviewed widening, not the "factory anywhere" bypass
#: ``test_the_execution_client_rule_detects_a_factory_anywhere`` still proves
#: this rule catches. Each entry stays an equality on (path, class, base), so
#: a SECOND client or factory, or either at another path, still fails.
#:
#: Its inertness is not asserted here. It is enforced next door by E0-NOSEND
#: (``test_execution_egress_firewall_guard.py``), which refuses an ``await``
#: inside any of the six order coroutines under ``exec/`` -- the mechanical
#: form of "no order may become sendable" -- and by N2's own exact-set pin,
#: which the factory's ``LiveExecClientFactory`` base also trips (E2).
PERMITTED_EXECUTION_CLIENTS: Mapping[str, str] = MappingProxyType(
    {
        "src/breezy/adapters/polymarket_us/exec/client.py": (
            "PolymarketUSExecutionClient(LiveExecutionClient)"
        ),
        "src/breezy/adapters/polymarket_us/factories.py": (
            "PolymarketUSLiveExecClientFactory(LiveExecClientFactory)"
        ),
    },
)


def find_execution_client_definitions(path: str, source: str) -> list[Violation]:
    """Every live-execution-client definition or import in one module."""
    banned = {"LiveExecutionClient", "LiveExecClientFactory", "LiveExecutionClientFactory"}
    found: list[Violation] = []
    tree = ast.parse(source, filename=path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
                if name in banned:
                    found.append(Violation(path, node.lineno, "NG", f"{node.name}({name})"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name in banned:
                    found.append(Violation(path, node.lineno, "NG", f"imports {alias.name}"))
    return found


def test_the_slice_defines_exactly_the_permitted_execution_clients() -> None:
    """An EQUALITY on (path, class), not a count and not a path allowlist."""
    found: dict[str, list[str]] = {}
    for path, source in iter_python_sources(("src", "scripts")):
        for violation in find_execution_client_definitions(path, source):
            found.setdefault(path, []).append(violation.detail)

    assert set(found) == set(PERMITTED_EXECUTION_CLIENTS), (
        "execution-client surface changed:\n"
        + "\n".join(f"{p}: {d}" for p, d in sorted(found.items()))
    )
    for path, details in found.items():
        expected = PERMITTED_EXECUTION_CLIENTS[path]
        base_name = expected[expected.index("(") + 1 : -1]
        # Sorted, because `ast.walk` is breadth-first and the ORDER of the
        # import and the class definition is not the property under test.
        assert sorted(details) == sorted(
            [
                expected,
                f"imports {base_name}",
            ],
        ), details


def test_the_execution_client_rule_detects_a_second_client() -> None:
    """Non-vacuity: the shape a bypass would arrive in is a NEW module."""
    source = (
        "from nautilus_trader.live.execution_client import LiveExecutionClient\n"
        "\n"
        "\n"
        "class ShadowExecutionClient(LiveExecutionClient):\n"
        "    pass\n"
    )
    found = find_execution_client_definitions("src/breezy/runtime/shadow.py", source)
    assert [v.rule for v in found] == ["NG", "NG"]
    assert "src/breezy/runtime/shadow.py" not in PERMITTED_EXECUTION_CLIENTS


def test_the_execution_client_rule_detects_a_factory_anywhere() -> None:
    """Factories stay banned OUTSIDE the named allowlist entry (EXEC SPINE W).

    The detector itself does not consult `PERMITTED_EXECUTION_CLIENTS` --
    that mapping is applied only by the live-tree scan above -- so this proof
    is unaffected by W's widening: a factory planted at any OTHER path (as
    here) is still caught.
    """
    source = (
        "from nautilus_trader.live.factories import LiveExecClientFactory\n"
        "\n"
        "\n"
        "class PolymarketUSExecClientFactory(LiveExecClientFactory):\n"
        "    pass\n"
    )
    found = find_execution_client_definitions(
        "src/breezy/adapters/polymarket_us/exec/client.py",
        source,
    )
    assert [v.rule for v in found] == ["NG", "NG"]


#: The planted caller B6's non-vacuity proof uses. An order path, in source.
_PLANTED_CHOKEPOINT_CALLER = (
    "from breezy.adapters.polymarket_us.safety import (\n"
    "    assert_live_order_submission_permitted,\n"
    ")\n"
    "\n"
    "\n"
    "def submit(c, p):\n"
    "    assert_live_order_submission_permitted(credentials=c, permit=p)\n"
)

#: The planted caller B7's non-vacuity proof uses: a module outside the issuer
#: minting a permit for itself out of the operator's environment. Every field
#: of the permit is derived inside the issuer from ``os.environ``, so this call
#: -- with no argument but a clock -- is the whole self-issuance defect.
_PLANTED_PERMIT_MINTER = (
    "from breezy.adapters.polymarket_us.safety import issue_live_trading_permit\n"
    "\n"
    "\n"
    "def mint_from_the_operator_environment(clock):\n"
    "    return issue_live_trading_permit(clock=clock)\n"
)


def test_safety_chokepoint_has_no_caller_in_this_slice() -> None:
    """B6: the shipped chokepoint stays uncalled by src/ and scripts/.

    A caller would mean an order path exists. Its own definition site and
    its tests are naturally excluded because only ``src`` and ``scripts``
    are scanned, and the definition is a ``FunctionDef``, not a ``Call``.
    """
    callers = [v for v in scan_barred_callers() if v.rule == "B6"]
    assert callers == [], "B6 violations:\n" + "\n".join(str(c) for c in callers)


def test_b6_detects_a_call_to_the_chokepoint() -> None:
    """Proof the B6 scan is not vacuous -- run through the ENFORCED scanner."""
    violations = find_barred_callers("src/breezy/rogue.py", _PLANTED_CHOKEPOINT_CALLER)
    assert [v.rule for v in violations] == ["B6"]


def test_permit_issuer_has_no_caller_in_this_slice() -> None:
    """B7 (defect D-2): nothing in src/ or scripts/ may mint a permit.

    ``issue_live_trading_permit`` reads the operator gate, both ceilings and
    the operator identity from ``os.environ`` and takes no parameter but a
    clock, so any caller anywhere in the tree grants itself authority. The
    pin is ``== 0``, repo-wide across both scanned roots, with no allowlist.
    """
    callers = [v for v in scan_barred_callers() if v.rule == "B7"]
    assert callers == [], "B7 violations:\n" + "\n".join(str(c) for c in callers)


def test_b7_detects_a_module_minting_a_permit_from_the_operator_environment() -> None:
    """Proof by construction that B7 is not vacuous."""
    violations = find_barred_callers("src/breezy/rogue.py", _PLANTED_PERMIT_MINTER)
    assert [v.rule for v in violations] == ["B7"]


def test_b7_detects_the_call_through_an_attribute_receiver_too() -> None:
    """``safety.issue_live_trading_permit(...)`` is the same mint."""
    source = (
        "from breezy.adapters.polymarket_us import safety\n"
        "\n"
        "\n"
        "def mint(clock):\n"
        "    return safety.issue_live_trading_permit(clock=clock)\n"
    )
    assert [v.rule for v in find_barred_callers("scripts/analysis/rogue.py", source)] == ["B7"]


def test_b7_does_not_fire_on_the_issuer_s_own_definition_site() -> None:
    """The shipped ``safety.py`` defines both names and calls neither.

    Read off the real file, not a planted string: if the definition site ever
    started calling the issuer, this barrier has to see it.
    """
    path = REPO_ROOT / "src" / "breezy" / "adapters" / "polymarket_us" / "safety.py"
    source = path.read_text(encoding="utf-8")
    assert find_barred_callers("src/breezy/adapters/polymarket_us/safety.py", source) == []


def test_b7_the_caller_barrier_has_no_exemption_mechanism() -> None:
    """No allowlist, and no parameter through which one could arrive.

    The plan's own words: a one-entry allowlist that is empty is a zero-entry
    allowlist, and shipping the structure unused is how it later gets an entry
    without a paired assertion. This pins the ABSENCE of the structure.
    """
    assert list(inspect.signature(find_barred_callers).parameters) == ["path", "source"]
    assert list(inspect.signature(scan_barred_callers).parameters) == ["roots"]
    assert set(BARRED_CALLEES) == {
        "assert_live_order_submission_permitted",
        "issue_live_trading_permit",
    }


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
