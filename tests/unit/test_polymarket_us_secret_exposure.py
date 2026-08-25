"""No PARTIAL secret form may escape Breezy (cross-seam reconciliation item 2).

Why this suite exists
---------------------
``nautilus_trader.common.secure.SecureString`` is safe-by-name, not safe in
fact. Its ``get_redacted()`` (``common/secure.py:100-102``) returns::

    value[:visible_chars] + "..." + value[-visible_chars:]

and both ``__str__`` (``:133``) and ``__repr__`` (``:139``) route through it.
So ``str(secret_key)`` publishes the first FOUR and last FOUR base64
characters of an Ed25519 private key. Eight known characters is not a
catastrophe on its own, but it is a real reduction of an attacker's search
space and it is exactly the kind of value that ends up pasted into an issue.

Nautilus Trader is IMMUTABLE (CLAUDE.md), so this is NOT fixed upstream and
not monkey-patched. Instead Breezy interposes full redaction at every point a
credential-bearing object can reach a log record, an exception message, or an
evidence artefact, and this suite proves the partial form does not escape.

The ``contract`` test below pins the upstream behaviour deliberately: if a
future Nautilus release changes ``get_redacted``, that test fails and this
defence gets re-reviewed rather than silently drifting.
"""

from __future__ import annotations

import ast
import base64
import logging
import os
import traceback
from collections.abc import Iterator
from pathlib import Path

import pytest
from nautilus_trader.common.secure import SecureString

from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
from breezy.adapters.polymarket_us.redaction import REDACTED, redact_secure
from breezy.adapters.polymarket_us.secure import RedactedSecureString

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Roots that must never call a partial-redaction helper.
PARTIAL_REDACTION_SCAN_ROOTS = ("src", "scripts")

#: Upstream helpers that return a PARTIAL value. Calling either from Breezy
#: code is the leak; both are banned outright rather than reviewed per site.
BANNED_PARTIAL_HELPERS = frozenset({"get_redacted", "mask_api_key"})

_VISIBLE_CHARS = 4


def _make_secret(size: int = 32) -> str:
    """A freshly generated base64 secret. Never a real credential."""
    return base64.b64encode(os.urandom(size)).decode("ascii")


def _fragments(value: str) -> list[str]:
    """The leading and trailing fragments ``get_redacted`` would publish."""
    return [value[:_VISIBLE_CHARS], value[-_VISIBLE_CHARS:]]


def _iter_python_sources(roots: tuple[str, ...]) -> Iterator[tuple[str, str]]:
    for root in roots:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            yield path.relative_to(REPO_ROOT).as_posix(), path.read_text(encoding="utf-8")


@pytest.fixture
def credentials() -> PolymarketUSCredentials:
    return PolymarketUSCredentials(
        key_id=RedactedSecureString(_make_secret(), name="polymarket_us_key_id"),
        secret_key=RedactedSecureString(_make_secret(), name="polymarket_us_secret_key"),
    )


# ---------------------------------------------------------------------------
# The upstream behaviour being defended against
# ---------------------------------------------------------------------------


@pytest.mark.contract
def test_nautilus_secure_string_really_does_publish_a_partial_value() -> None:
    """Pins the leak this suite defends against; not vacuous.

    If Nautilus ever stops leaking, this fails and the defence is re-reviewed.
    """
    secret = _make_secret()
    rendered = str(SecureString(secret, name="pinned"))

    assert rendered == f"{secret[:4]}...{secret[-4:]}"
    for fragment in _fragments(secret):
        assert fragment in rendered


# ---------------------------------------------------------------------------
# Breezy must never emit that partial form
# ---------------------------------------------------------------------------


def test_credentials_repr_publishes_no_partial_fragment(
    credentials: PolymarketUSCredentials,
) -> None:
    secret = credentials.secret_key.get_value()
    key_id = credentials.key_id.get_value()

    for rendered in (repr(credentials), str(credentials), f"{credentials}", format(credentials)):
        leaked = [f for f in _fragments(secret) + _fragments(key_id) if f in rendered]
        assert leaked == [], f"partial credential fragment escaped into {rendered!r}"
        assert secret not in rendered
        assert key_id not in rendered
        assert REDACTED in rendered


def test_credentials_define_their_own_repr_rather_than_the_dataclass_default() -> None:
    """Structural guard: the generated dataclass repr calls repr() per field.

    Without an explicit override, ``repr(credentials)`` renders each
    ``SecureString`` through the leaking upstream ``__repr__``.
    """
    assert "__repr__" in PolymarketUSCredentials.__dict__


def test_credentials_inside_a_container_repr_publish_no_partial_fragment(
    credentials: PolymarketUSCredentials,
) -> None:
    """Containers call ``repr()`` on their members; the override must cover it."""
    secret = credentials.secret_key.get_value()
    rendered = repr({"creds": [credentials]})

    assert [f for f in _fragments(secret) if f in rendered] == []


def test_credentials_logged_as_a_log_record_publish_no_partial_fragment(
    credentials: PolymarketUSCredentials,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = credentials.secret_key.get_value()
    logger = logging.getLogger("breezy.test.secret_exposure")

    with caplog.at_level(logging.INFO, logger=logger.name):
        logger.info("loaded %s / %r", credentials, credentials)

    text = caplog.text
    assert [f for f in _fragments(secret) if f in text] == []
    assert secret not in text


def test_credentials_in_an_exception_message_publish_no_partial_fragment(
    credentials: PolymarketUSCredentials,
) -> None:
    secret = credentials.secret_key.get_value()
    try:
        raise RuntimeError(f"venue call failed for {credentials!r}")
    except RuntimeError as exc:
        rendered = str(exc) + repr(exc) + traceback.format_exc()

    assert [f for f in _fragments(secret) if f in rendered] == []


def test_redact_secure_returns_the_marker_and_never_the_value() -> None:
    secret = _make_secret()
    secure = SecureString(secret, name="polymarket_us_secret_key")

    assert redact_secure(secure) == REDACTED
    assert redact_secure(secret) == REDACTED
    assert redact_secure(None) == REDACTED


# ---------------------------------------------------------------------------
# Repo-wide ban on the partial-redaction helpers
# ---------------------------------------------------------------------------


def _find_partial_helper_calls(path: str, source: str) -> list[str]:
    tree = ast.parse(source, filename=path)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in BANNED_PARTIAL_HELPERS:
                found.append(f"{path}:{node.lineno}: {name}()")
    return found


def test_no_breezy_module_calls_a_partial_redaction_helper() -> None:
    violations = [
        v
        for path, source in _iter_python_sources(PARTIAL_REDACTION_SCAN_ROOTS)
        for v in _find_partial_helper_calls(path, source)
    ]
    assert violations == [], (
        "These call sites publish the first and last 4 characters of a "
        "credential (nautilus_trader/common/secure.py:100-102). Use "
        "breezy.adapters.polymarket_us.redaction.redact_secure instead:\n" + "\n".join(violations)
    )


def test_the_partial_helper_ban_is_not_vacuous() -> None:
    source = "def log(creds):\n    print(creds.secret_key.get_redacted())\n"
    assert _find_partial_helper_calls("src/breezy/x.py", source) != []
    source = "from nautilus_trader.common.secure import mask_api_key\n\n\ndef f(k):\n    return mask_api_key(k)\n"  # noqa: E501
    assert _find_partial_helper_calls("src/breezy/y.py", source) != []


def test_the_partial_helper_ban_scans_both_src_and_scripts() -> None:
    scanned = {path for path, _ in _iter_python_sources(PARTIAL_REDACTION_SCAN_ROOTS)}
    assert any(p.startswith("src/") for p in scanned)
    assert any(p.startswith("scripts/") for p in scanned)
