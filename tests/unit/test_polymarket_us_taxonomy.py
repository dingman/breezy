"""One error taxonomy, one redaction marker, one always-runnable signing gate.

Cross-seam reconciliation items 1, 3 and 6. Each of these was a defect created
by three seams landing in parallel with disjoint write scopes:

* **Item 1** -- ``env.py`` defined its OWN ``CredentialSourceError`` because
  ``errors.py`` did not exist yet. ``signing.py`` raises the ``errors.py``
  one. Two same-named classes in one package means ``except
  CredentialSourceError`` catches whichever the caller happened to import and
  silently misses the other.
* **Item 3** -- the GET-only signing barrier (B2) lives in a module that
  imports ``nacl`` at module scope. With PyNaCl reachable only through an
  optional extra, the default suite SKIPPED the barrier's tests. A guard that
  never executes is indistinguishable from a guard that passes.
* **Item 6** -- ``redact_url`` rendered ``REDACTED`` while the header and
  free-text helpers rendered ``<redacted>``, so one redaction surface spoke
  two languages.
"""

from __future__ import annotations

import importlib
import tomllib
from pathlib import Path

import pytest

from breezy.adapters.polymarket_us import credentials as credentials_module
from breezy.adapters.polymarket_us import env as env_module
from breezy.adapters.polymarket_us import errors as errors_module
from breezy.adapters.polymarket_us import redaction as redaction_module

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Item 1 -- a single credential-error hierarchy
# ---------------------------------------------------------------------------


def test_env_and_errors_expose_the_same_credential_source_error_object() -> None:
    assert env_module.CredentialSourceError is errors_module.CredentialSourceError


def test_credential_source_error_is_inside_the_polymarket_us_taxonomy() -> None:
    assert issubclass(errors_module.CredentialSourceError, errors_module.PolymarketUSError)


def test_credential_config_error_is_inside_the_polymarket_us_taxonomy() -> None:
    """The config error must not be a second, parallel root."""
    assert issubclass(credentials_module.CredentialConfigError, errors_module.PolymarketUSError)


def test_credential_source_error_keeps_its_existing_ancestry() -> None:
    """Behaviour preservation: re-parenting must not drop what callers rely on."""
    assert issubclass(errors_module.CredentialSourceError, credentials_module.CredentialConfigError)
    assert issubclass(errors_module.CredentialSourceError, ValueError)


def test_a_loader_failure_is_catchable_as_the_adapter_base_error() -> None:
    ref = credentials_module.PolymarketUSSecretsRefConfig()
    with pytest.raises(errors_module.PolymarketUSError):
        env_module.load_polymarket_us_credentials(ref, env={})


def test_a_signing_failure_and_a_loader_failure_share_one_catch_clause() -> None:
    """The concrete bug: one ``except`` clause must catch both seams."""
    signing = importlib.import_module("breezy.adapters.polymarket_us.signing")
    assert signing.CredentialSourceError is env_module.CredentialSourceError


# ---------------------------------------------------------------------------
# Item 6 -- one redaction marker across the whole surface
# ---------------------------------------------------------------------------


def test_url_header_and_text_redaction_all_use_the_same_marker() -> None:
    marker = redaction_module.REDACTED

    url = redaction_module.redact_url("https://api.polymarket.us/v1/markets?apiKey=abc123")
    headers = redaction_module.redact_headers({"X-PM-Signature": "sig"})
    text = redaction_module.redact_text("token abc123 here", ["abc123"])

    assert "abc123" not in url
    assert marker in url
    assert headers["X-PM-Signature"] == marker
    assert marker in text


def test_the_marker_survives_url_query_encoding_intact() -> None:
    """A marker containing URL-unsafe characters would be percent-encoded.

    ``urlencode`` turns ``<redacted>`` into ``%3Credacted%3E``, which is why
    the bare uppercase token is the one marker that works in all three
    contexts rather than only in two of them.
    """
    url = redaction_module.redact_url("https://api.polymarket.us/v1/m?a=1&b=2")

    assert "%3C" not in url
    assert url.count(redaction_module.REDACTED) == 2


def test_the_ingest_layer_owns_the_single_marker_definition() -> None:
    """No second literal to drift: the adapter re-exports, never redefines."""
    from breezy.ingest.http import REDACTION_MARKER

    assert redaction_module.REDACTED == REDACTION_MARKER


# ---------------------------------------------------------------------------
# Item 3 -- the GET-only barrier must be executable in a default checkout
# ---------------------------------------------------------------------------


def _pyproject() -> dict[str, object]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_pynacl_is_a_core_dependency_not_an_optional_extra() -> None:
    """Barrier B2 lives behind ``import nacl``; a default checkout must have it."""
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    core = [str(spec) for spec in project["dependencies"]]

    assert any(spec.lower().startswith("pynacl") for spec in core), (
        "PyNaCl must be a core dependency: signing.py imports nacl at module "
        "scope and holds the GET-only order-submission barrier. Behind an "
        "optional extra, the barrier's tests SKIP in a default checkout."
    )


def test_the_signing_module_imports_without_any_optional_extra() -> None:
    signing = importlib.import_module("breezy.adapters.polymarket_us.signing")

    assert signing.PERMITTED_METHODS == frozenset({"GET"})


def test_the_get_only_barrier_actually_executes_here() -> None:
    """Not a skip: the barrier is exercised in the default suite."""
    signing = importlib.import_module("breezy.adapters.polymarket_us.signing")

    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert method not in signing.PERMITTED_METHODS


def test_the_signing_gate_suite_has_no_module_level_import_skip() -> None:
    """The barrier suite must fail loudly, never skip, on a default checkout."""
    source = (REPO_ROOT / "tests/unit/test_polymarket_us_signing.py").read_text(encoding="utf-8")
    head = source.split("# ---", 1)[0]

    assert 'importorskip(\n    "nacl"' not in head
    assert 'importorskip("nacl"' not in head


def test_mypy_typechecks_the_adapter_package_without_an_explicit_path() -> None:
    """Item 4: registered in ``[tool.mypy].files`` or it is never checked."""
    tool = _pyproject()["tool"]
    assert isinstance(tool, dict)
    mypy_config = tool["mypy"]
    assert isinstance(mypy_config, dict)
    files = [str(entry) for entry in mypy_config["files"]]

    assert "src/breezy/adapters" in files


def test_mypy_typechecks_the_script_the_operator_runs_against_production() -> None:
    """The smoke script was outside `[tool.mypy].files` and had a live error.

    It is the ONE file executed against production credentials, and it had
    never been typechecked -- the same failure mode as a green gate that is not
    looking at the code in question. Pinned so the scope cannot silently
    narrow again.
    """
    tool = _pyproject()["tool"]
    assert isinstance(tool, dict)
    mypy_config = tool["mypy"]
    assert isinstance(mypy_config, dict)
    files = [str(entry) for entry in mypy_config["files"]]

    assert "scripts/venue" in files


def test_the_polymarket_test_doubles_are_typechecked_against_the_real_classes() -> None:
    """Untypechecked doubles drift, and a drifted double validates a fiction.

    `test_polymarket_us_factories` was asserting `requires_auth` / `_signer`
    through the `MarketsFeed` Protocol, which declares neither.
    """
    tool = _pyproject()["tool"]
    assert isinstance(tool, dict)
    mypy_config = tool["mypy"]
    assert isinstance(mypy_config, dict)
    files = {str(entry) for entry in mypy_config["files"]}

    on_disk = {
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "tests" / "unit").glob("test_polymarket_us_*.py")
    }

    assert on_disk, "no polymarket_us test modules found"
    assert on_disk <= files, (
        f"these polymarket_us test modules are not typechecked: {sorted(on_disk - files)}"
    )


def test_the_package_ships_a_py_typed_marker() -> None:
    """Without it, mypy treats `breezy` as an untyped installed package.

    That silently downgraded every `from breezy...` import in the smoke script
    to `Any`, which is what hid the `no-any-return` at line 511.
    """
    assert (REPO_ROOT / "src" / "breezy" / "py.typed").is_file()
