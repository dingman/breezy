"""Serialisation must not re-open a containment hole (review items 1 and 2).

Why this suite exists
---------------------
:mod:`tests.unit.test_polymarket_us_secret_exposure` proves that no *partial*
secret form escapes through ``repr``/``str``/logging. It does not cover
serialisation, and two serialisation routes bypass the hand-written
``PolymarketUSCredentials.__repr__`` entirely:

* **pickle (item 1, FULL cleartext).** ``SecureString`` keeps the plaintext in
  ``_value`` and a second copy in the ``_bytes`` bytearray, and defines no
  ``__reduce__``/``__getstate__``. ``PolymarketUSCredentials`` is
  ``slots=True``, so it pickles via ``__reduce_ex__`` protocol 2+ and drags the
  whole ``SecureString`` graph along. Empirically, ``pickle.dumps(creds)``
  contained the entire 32-byte Ed25519 secret in cleartext and round-tripped to
  an equal value. That is strictly worse than the 8-character leak the sibling
  suite defends against.

* **dataclasses.asdict (item 2, PARTIAL leak -- NOW CLOSED).** ``asdict``
  deep-copies field values and never consults the container's ``__repr__``. The
  resulting dict holds the field objects themselves, so ``repr()`` of it routes
  through whatever ``__repr__`` those field objects define. While the fields
  were bare ``SecureString`` that meant ``get_redacted()``
  (``nautilus_trader/common/secure.py:100-102``) and the exact first-4/last-4
  fragments. ``asdict`` is an established idiom in this repo
  (``src/breezy/ingest/gate.py:388,400``), so a future call site is plausible.

Nautilus Trader is IMMUTABLE (CLAUDE.md), so ``SecureString`` is not patched or
monkey-patched. Breezy interposes on its own types instead: the container for
serialisation, and a *subclass* -- ``RedactedSecureString`` -- for rendering.
Subclassing is a native extension point, not a modification.

Design choice, item 1: pickling a live credential is never legitimate here --
credentials are loaded from the environment at process start, not shipped
between processes -- so the guard *raises* rather than emitting a REDACTED
placeholder. A placeholder would round-trip into a silently broken credential
whose failure surfaces far from the cause. ``__reduce__``, ``__getstate__``,
``__copy__`` and ``__deepcopy__`` all refuse.

Design choice, item 2: ``asdict`` cannot be defeated from the *container* --
it recurses into field values via ``getattr`` and never consults a container
hook -- so the fix is applied one level down, at the FIELD TYPE.
``PolymarketUSCredentials`` now requires
:class:`~breezy.adapters.polymarket_us.secure.RedactedSecureString` for both
fields (``__post_init__`` rejects a bare ``SecureString``), and that subclass
renders no fragment under ``__str__``, ``__repr__``, ``__format__`` or
``get_redacted``. The gap is therefore CLOSED structurally, and
:func:`test_asdict_no_longer_leaks_a_partial_secret` asserts so.

The AST barrier :func:`find_asdict_on_credentials` is RETAINED as defence in
depth and is not now redundant: ``asdict`` still yields live, picklable
credential objects that bypass the container's ``__reduce__`` refusal, so the
idiom stays banned in ``src/`` and ``scripts/`` even though it no longer
renders a fragment.
"""

from __future__ import annotations

import ast
import base64
import copy
import dataclasses
import os
import pickle
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from nautilus_trader.common.secure import SecureString

from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
from breezy.adapters.polymarket_us.errors import CredentialSerializationError
from breezy.adapters.polymarket_us.redaction import REDACTED
from breezy.adapters.polymarket_us.secure import RedactedSecureString

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Roots scanned for the ``asdict``-on-a-credential ban.
ASDICT_SCAN_ROOTS = ("src", "scripts")

#: Current shipped coverage is 83 files (75 under ``src/breezy`` and 8 under
#: ``scripts``). Keep this as an at-least guard so new files do not require a
#: test edit, while any collapsed or misrouted scan fails loudly.
MIN_ASDICT_SCAN_SOURCE_COUNT = 83

_VISIBLE_CHARS = 4


def _make_secret(size: int = 32) -> str:
    """A freshly generated base64 secret. Never a real credential."""
    return base64.b64encode(os.urandom(size)).decode("ascii")


def _fragments(value: str) -> list[str]:
    """The leading/trailing fragments ``get_redacted`` would publish."""
    return [value[:_VISIBLE_CHARS], value[-_VISIBLE_CHARS:]]


@pytest.fixture
def secret() -> str:
    return _make_secret()


@pytest.fixture
def key_id() -> str:
    return _make_secret(16)


@pytest.fixture
def credentials(key_id: str, secret: str) -> PolymarketUSCredentials:
    return PolymarketUSCredentials(
        key_id=RedactedSecureString(key_id, name="key_id"),
        secret_key=RedactedSecureString(secret, name="secret_key"),
    )


# --------------------------------------------------------------------------
# Item 1 -- pickling leaks the FULL secret
# --------------------------------------------------------------------------


def test_pickling_credentials_raises_instead_of_serialising(
    credentials: PolymarketUSCredentials,
) -> None:
    """``pickle.dumps`` must refuse, not emit a secret-bearing byte stream."""
    with pytest.raises(CredentialSerializationError):
        pickle.dumps(credentials)


@pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
def test_no_pickle_protocol_can_serialise_credentials(
    credentials: PolymarketUSCredentials,
    protocol: int,
) -> None:
    """Every protocol is refused; protocol 0/1 take a different code path."""
    with pytest.raises(CredentialSerializationError):
        pickle.dumps(credentials, protocol=protocol)


def test_pickling_credentials_emits_no_byte_stream_carrying_the_secret(
    credentials: PolymarketUSCredentials,
    secret: str,
    key_id: str,
) -> None:
    """Belt-and-braces: if a stream is ever produced, it must be clean.

    Asserts on the FULL value and on the 4-character fragments, so a future
    change that downgrades the guard to a partial placeholder still fails.
    """
    try:
        blob = pickle.dumps(credentials)
    except CredentialSerializationError:
        return  # Refused outright -- the stronger outcome.

    pytest.fail(  # pragma: no cover - only reachable if the guard regresses
        "pickle.dumps produced a byte stream for a credential; "
        f"carries_full_secret={secret.encode() in blob} "
        f"carries_full_key_id={key_id.encode() in blob} "
        "fragments="
        f"{[f for f in _fragments(secret) + _fragments(key_id) if f.encode() in blob]}"
    )


def test_deepcopy_of_credentials_is_also_refused(
    credentials: PolymarketUSCredentials,
) -> None:
    """``copy.deepcopy`` uses the same reduction protocol as pickle.

    Pinned deliberately: this is the mechanism by which ``dataclasses.asdict``
    duplicates the secret, so its behaviour must be a conscious decision rather
    than an accident of which dunder was overridden.
    """
    with pytest.raises(CredentialSerializationError):
        copy.deepcopy(credentials)


def test_the_upstream_securestring_still_stores_cleartext(secret: str) -> None:
    """Contract test against Nautilus 1.231.0 -- the reason the guard exists.

    If a future Nautilus release stops storing plaintext or adds its own
    pickle guard, this fails and the Breezy-side defence gets re-reviewed
    instead of silently becoming redundant.
    """
    secure = SecureString(secret, name="secret_key")

    # Compare into a local BEFORE asserting. pytest rewrites assertions and
    # prints every operand on failure, so `assert x.get_value() == secret`
    # would dump cleartext into CI logs -- banned by the S16 barrier in
    # tests/unit/test_polymarket_us_readonly_guard.py.
    stores_cleartext = secure.get_value() == secret
    assert stores_cleartext

    assert not hasattr(SecureString, "__reduce__") or (SecureString.__reduce__ is object.__reduce__)
    assert not hasattr(SecureString, "__getstate__") or (
        SecureString.__getstate__ is object.__getstate__
    )

    # The bare SecureString remains picklable upstream; Breezy does not and
    # cannot change that, which is exactly why the container guards instead.
    round_tripped = pickle.loads(pickle.dumps(secure))
    survives_pickle = round_tripped.get_value() == secret
    assert survives_pickle


# --------------------------------------------------------------------------
# Item 2 -- dataclasses.asdict re-opens the PARTIAL leak
# --------------------------------------------------------------------------


def test_asdict_no_longer_leaks_a_partial_secret(
    credentials: PolymarketUSCredentials,
    secret: str,
    key_id: str,
) -> None:
    """The former residual gap, now CLOSED -- read the history before editing.

    ``dataclasses.asdict`` cannot be blocked from the container: it detects
    ``__dataclass_fields__`` and recurses straight into field values via
    ``getattr(obj, f.name)``, never consulting the container's ``__reduce__``,
    ``__getstate__``, ``__copy__`` or ``__deepcopy__``. While the fields were
    bare ``SecureString``, ``repr(dataclasses.asdict(creds))`` rendered
    ``SecureString(name='secret_key', value=NgZ4...GSM=)`` and republished the
    first and last four characters.

    An earlier revision of this test PINNED that leak as open, on the reasoning
    that a subclass would only bind at construction sites that opt in. That
    objection was answered by making the opt-in mandatory:
    ``PolymarketUSCredentials.__post_init__`` refuses a bare ``SecureString``,
    so every instance that exists at all carries redacting fields. Nautilus is
    untouched -- subclassing is a native extension point.

    This test now asserts the gap is CLOSED, and remains non-vacuous via
    :func:`test_a_bare_securestring_field_would_still_leak`, which pins the
    upstream behaviour the subclass exists to override.
    """
    rendered = repr(dataclasses.asdict(credentials))

    leaked = [f for f in _fragments(secret) + _fragments(key_id) if f in rendered]
    assert leaked == [], f"partial credential fragment escaped asdict: {rendered!r}"
    assert secret not in rendered
    assert key_id not in rendered
    assert rendered.count(REDACTED) == 2, rendered


def test_credentials_refuse_a_bare_leaking_securestring(secret: str, key_id: str) -> None:
    """The subclass requirement is enforced, not merely conventional."""
    with pytest.raises(TypeError, match="RedactedSecureString"):
        PolymarketUSCredentials(
            key_id=SecureString(key_id, name="key_id"),  # type: ignore[arg-type]
            secret_key=RedactedSecureString(secret, name="secret_key"),
        )
    with pytest.raises(TypeError, match="RedactedSecureString"):
        PolymarketUSCredentials(
            key_id=RedactedSecureString(key_id, name="key_id"),
            secret_key=SecureString(secret, name="secret_key"),  # type: ignore[arg-type]
        )


@pytest.mark.contract
def test_a_bare_securestring_field_would_still_leak(secret: str) -> None:
    """Non-vacuity guard for the test above, pinned against Nautilus 1.231.0.

    If upstream ever stops publishing fragments, this fails and
    ``RedactedSecureString`` gets re-reviewed instead of silently becoming
    dead weight.
    """
    rendered = repr({"secret_key": SecureString(secret, name="secret_key")})

    assert [f for f in _fragments(secret) if f in rendered] == _fragments(secret)


def test_redacted_secure_string_renders_no_fragment_on_any_surface(secret: str) -> None:
    """Every rendering surface of the subclass, including format specs."""
    secure = RedactedSecureString(secret, name="secret_key")

    surfaces = [
        str(secure),
        repr(secure),
        f"{secure}",
        f"{secure:>40}",
        format(secure),
        secure.get_redacted(),
        secure.get_redacted(visible_chars=16),
    ]
    for rendered in surfaces:
        assert [f for f in _fragments(secret) if f in rendered] == [], rendered
        assert secret not in rendered

    # Behaviour is otherwise unchanged: the value is still retrievable.
    round_trips = secure.get_value() == secret
    assert round_trips
    assert len(secure) == len(secret)
    assert bool(secure) is True


def test_asdict_bypasses_the_container_serialisation_hooks(
    credentials: PolymarketUSCredentials,
) -> None:
    """Pin the exact mechanism, so the reason for the barrier stays legible."""
    # Every container-level hook refuses...
    for operation in (
        lambda: pickle.dumps(credentials),
        lambda: copy.copy(credentials),
        lambda: copy.deepcopy(credentials),
    ):
        with pytest.raises(CredentialSerializationError):
            operation()

    # ...yet asdict still succeeds, because it never reaches them. That is why
    # the redaction had to move to the field type, and why the AST barrier
    # below is retained: the dict holds live, picklable credential objects.
    assert dataclasses.asdict(credentials) is not None


def _iter_python_sources(roots: tuple[str, ...]) -> Iterator[tuple[str, str]]:
    for root in roots:
        root_path = REPO_ROOT / root
        if not root_path.is_dir():
            continue
        for path in sorted(root_path.rglob("*.py")):
            yield (
                path.relative_to(REPO_ROOT).as_posix(),
                path.read_text(encoding="utf-8"),
            )


#: Names that identify a credential-bearing argument at an ``asdict`` call.
_CREDENTIAL_ARG_HINTS = frozenset({"credentials", "creds", "credential", "secrets"})


def find_asdict_on_credentials(path: str, source: str) -> list[str]:
    """Flag ``asdict(...)`` calls whose argument looks credential-bearing.

    Deliberately name-based and deliberately narrow: a repo-wide ban on
    ``asdict`` would be false-positive noise against the legitimate uses in
    ``src/breezy/ingest/gate.py``. The container guard is the real defence;
    this barrier stops the idiom being *written* against a credential.
    """
    tree = ast.parse(source, filename=path)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name != "asdict" or not node.args:
            continue
        arg = node.args[0]
        target = arg.attr if isinstance(arg, ast.Attribute) else getattr(arg, "id", "")
        if target.lower() in _CREDENTIAL_ARG_HINTS:
            found.append(f"{path}:{node.lineno}: asdict({target})")
    return found


def test_no_breezy_module_calls_asdict_on_a_credential() -> None:
    scanned_sources = list(_iter_python_sources(ASDICT_SCAN_ROOTS))
    if os.environ.get("BREEZY_ASDICT_GUARD_TRACE") == "1":
        print(f"ASDICT_GUARD_SCANNED_COUNT={len(scanned_sources)}")
        print("ASDICT_GUARD_SCANNED_NAMES=" + ",".join(path for path, _source in scanned_sources))
    assert len(scanned_sources) >= MIN_ASDICT_SCAN_SOURCE_COUNT, (
        "asdict credential guard scanned "
        f"{len(scanned_sources)} Python source files under roots {ASDICT_SCAN_ROOTS!r}; "
        f"expected at least {MIN_ASDICT_SCAN_SOURCE_COUNT}. Scanned: "
        + ", ".join(path for path, _source in scanned_sources)
    )
    violations = [
        v
        for path, source in scanned_sources
        for v in find_asdict_on_credentials(path, source)
    ]
    assert violations == [], (
        "dataclasses.asdict deep-copies SecureString fields and bypasses the "
        "hand-written __repr__, republishing the first/last 4 characters of "
        "the secret. Render credentials with "
        "breezy.adapters.polymarket_us.redaction.redact_secure instead:\n" + "\n".join(violations)
    )


def test_the_asdict_ban_fails_loudly_when_scan_coverage_collapses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys.modules[__name__], "ASDICT_SCAN_ROOTS", ("missing-root",))

    with pytest.raises(AssertionError, match="asdict credential guard scanned"):
        test_no_breezy_module_calls_asdict_on_a_credential()


def test_the_asdict_ban_is_not_vacuous() -> None:
    source = (
        "from dataclasses import asdict\n\n\n"
        "def log(credentials):\n    return asdict(credentials)\n"
    )
    assert find_asdict_on_credentials("src/breezy/x.py", source) != []
    source = "import dataclasses\n\n\ndef log(creds):\n    return dataclasses.asdict(creds)\n"
    assert find_asdict_on_credentials("src/breezy/y.py", source) != []


def test_the_asdict_ban_does_not_flag_legitimate_uses() -> None:
    source = "import dataclasses\n\n\ndef f(record):\n    return dataclasses.asdict(record)\n"
    assert find_asdict_on_credentials("src/breezy/ingest/gate.py", source) == []
