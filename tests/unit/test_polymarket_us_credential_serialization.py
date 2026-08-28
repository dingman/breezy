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


# --------------------------------------------------------------------------
# Q-1 fix -- invert the default from an open blocklist to a closed allowlist.
#
# The scanner above (`find_asdict_on_credentials`) is retained verbatim, but
# only as a LEGACY heuristic exercised by
# `test_the_old_name_heuristic_misses_an_unremarkable_variable_name`, which
# pins its known gap: it is name-based and an `asdict(x)` call escapes it the
# instant `x` is not spelled like `credentials`/`creds`/`credential`/
# `secrets`. That is unbounded and always losable (docs/core/PROGRESS.md
# Q-1).
#
# `find_unallowlisted_asdict_calls` below is the guard actually enforced by
# `test_no_breezy_module_calls_asdict_on_a_credential`. It inverts the
# default: every `asdict(...)` call site under `src/` and `scripts/` is a
# FAILURE unless it is named, by exact file + line + argument, in the closed
# `_ALLOWED_ASDICT_CALL_SITES` set below. A closed set defined by positive
# membership cannot be escaped by inventing a new variable name -- there is
# no name an evader could choose that is already a member of an empty-by-
# default set. This mirrors how other guards in this repo work (e.g. the
# venue market-data type allowlist): enumerate what is PERMITTED, not what is
# forbidden.
# --------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class _AllowedAsdictCallSite:
    """One positive-membership entry in the closed ``asdict`` allowlist.

    Keyed by exact file + line + argument name, not just file: a file that
    legitimately calls ``asdict`` once does not thereby license a second,
    different, unreviewed call added later in the same file.
    """

    path: str
    lineno: int
    arg_name: str
    justification: str


#: Closed set. Add an entry ONLY when the argument at that exact call site is
#: provably not credential-bearing, and say why. Anything else under `src/`
#: or `scripts/` that calls `asdict` is a hard failure -- see
#: `test_no_breezy_module_calls_asdict_on_a_credential`.
_ALLOWED_ASDICT_CALL_SITES: tuple[_AllowedAsdictCallSite, ...] = (
    _AllowedAsdictCallSite(
        path="src/breezy/ingest/gate.py",
        lineno=388,
        arg_name="entry",
        justification=(
            "`entry` is a `_SiteEntry` -- a frozen dataclass of gate-state "
            "booleans, timestamps and a `GateReason` enum used to persist "
            "the settlement gate's state machine. It carries no "
            "credential-bearing field; nothing here is loaded from, or "
            "authenticates to, a venue."
        ),
    ),
    _AllowedAsdictCallSite(
        path="src/breezy/ingest/gate.py",
        lineno=400,
        arg_name="entry",
        justification=(
            "`entry` is a `_GlobalEntry` -- the cross-site UA-trap latch, "
            "same shape as `_SiteEntry` above (booleans, a timestamp, a "
            "`GateReason` enum). No credential-bearing field exists on the "
            "type."
        ),
    ),
)

_ALLOWED_ASDICT_CALL_KEYS = frozenset(
    (site.path, site.lineno, site.arg_name) for site in _ALLOWED_ASDICT_CALL_SITES
)


def find_unallowlisted_asdict_calls(path: str, source: str) -> list[str]:
    """Flag every ``asdict(...)`` call site not in the closed allowlist.

    Unlike ``find_asdict_on_credentials`` above, this does not look at what
    the argument is NAMED at all -- it looks at whether the exact
    ``(path, lineno, arg_name)`` triple is a member of
    ``_ALLOWED_ASDICT_CALL_SITES``. A new call site under an unremarkable
    name (``payload``, ``data``, ...) is caught precisely because it was
    never granted membership, not because its name was recognised as
    suspicious.
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
        target = arg.attr if isinstance(arg, ast.Attribute) else getattr(arg, "id", "<expr>")
        if (path, node.lineno, target) in _ALLOWED_ASDICT_CALL_KEYS:
            continue
        found.append(
            f"{path}:{node.lineno}: asdict({target}) is not in the closed "
            "_ALLOWED_ASDICT_CALL_SITES allowlist"
        )
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
        for v in find_unallowlisted_asdict_calls(path, source)
    ]
    assert violations == [], (
        "an asdict(...) call site exists under src/ or scripts/ that is not in "
        "the closed _ALLOWED_ASDICT_CALL_SITES allowlist above. asdict deep-"
        "copies field values and bypasses hand-written __repr__/__reduce__ "
        "hooks entirely, so an unreviewed call site can leak or re-pickle "
        "credential material regardless of what its argument is named. Either "
        "remove the call, or -- only if the argument is provably non-"
        "credential-bearing -- add it to _ALLOWED_ASDICT_CALL_SITES with a "
        "justification:\n" + "\n".join(violations)
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


# --------------------------------------------------------------------------
# Q-1 -- semantic-reach hardening (docs/core/PROGRESS.md): the name-based
# heuristic above is an open blocklist and is always losable by inventing an
# unremarkable variable name. These tests are written FIRST, against
# `find_unallowlisted_asdict_calls` and `_ALLOWED_ASDICT_CALL_SITES`, which do
# not exist yet -- this block is expected to fail (RED) until both are added.
# --------------------------------------------------------------------------

#: A call site that would defeat the OLD name-based heuristic: `data` is not
#: in `_CREDENTIAL_ARG_HINTS`. Passed as literal (path, source) text -- not a
#: real file on disk -- mirroring how `test_the_asdict_ban_is_not_vacuous`
#: and `test_the_asdict_ban_does_not_flag_legitimate_uses` already exercise
#: these scanner functions above: both take `(path, source)` and never touch
#: the filesystem, so a synthetic path string plus literal source is exactly
#: as valid as writing a throwaway module and is fully hermetic.
_UNLISTED_ASDICT_FIXTURE_SOURCE = (
    "import dataclasses\n\n\n"
    "def leak_credentials(data):\n"
    "    # `data` stands in for a credential-bearing dataclass at an\n"
    "    # unremarkable call site -- the exact evasion Q-1 names.\n"
    "    return dataclasses.asdict(data)\n"
)


def test_the_old_name_heuristic_misses_an_unremarkable_variable_name() -> None:
    """BEFORE: the retained legacy heuristic passes this call site silently.

    ``data`` is not in ``_CREDENTIAL_ARG_HINTS`` -- an open blocklist of
    credential-sounding names is always losable this way. This is Q-1.
    """
    violations = find_asdict_on_credentials(
        "src/breezy/_fixture_unlisted_asdict.py", _UNLISTED_ASDICT_FIXTURE_SOURCE
    )
    assert violations == []  # the gap Q-1 names -- proven still open here


def test_the_new_allowlist_guard_catches_the_same_call_site() -> None:
    """AFTER: the closed-membership allowlist flags the identical call site.

    No name-based escape hatch exists here: the call site is simply absent
    from ``_ALLOWED_ASDICT_CALL_SITES``, so it fails regardless of what the
    argument is named.
    """
    violations = find_unallowlisted_asdict_calls(
        "src/breezy/_fixture_unlisted_asdict.py", _UNLISTED_ASDICT_FIXTURE_SOURCE
    )
    assert violations != []
    assert "asdict(data)" in violations[0]


def test_every_allowlisted_call_site_carries_a_justification() -> None:
    """Positive-membership entries must be justified, not just declared."""
    assert _ALLOWED_ASDICT_CALL_SITES, "allowlist should not be silently empty"
    for site in _ALLOWED_ASDICT_CALL_SITES:
        assert site.justification.strip(), f"{site.path}:{site.lineno} has no justification"


def test_every_allowlisted_call_site_still_exists_in_the_real_source() -> None:
    """Guards against allowlist rot: a stale entry is an unused permission."""
    sources = dict(_iter_python_sources(ASDICT_SCAN_ROOTS))
    for site in _ALLOWED_ASDICT_CALL_SITES:
        source = sources.get(site.path)
        assert source is not None, f"{site.path} no longer exists under scan roots"
        tree = ast.parse(source, filename=site.path)
        calls_at_line = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Attribute) and node.func.attr == "asdict")
                or (isinstance(node.func, ast.Name) and node.func.id == "asdict")
            )
            and node.lineno == site.lineno
        ]
        assert calls_at_line, f"{site.path}:{site.lineno} no longer calls asdict"


def test_no_unallowlisted_asdict_call_exists_under_the_scan_roots() -> None:
    """The NEW guard, run for real: every asdict call site under src/ and
    scripts/ must be exactly the closed allowlist -- nothing more."""
    scanned_sources = list(_iter_python_sources(ASDICT_SCAN_ROOTS))
    violations = [
        v
        for path, source in scanned_sources
        for v in find_unallowlisted_asdict_calls(path, source)
    ]
    assert violations == [], (
        "an asdict(...) call site exists under src/ or scripts/ that is not in "
        "the closed _ALLOWED_ASDICT_CALL_SITES allowlist. Either the call must "
        "be removed, or -- only if the argument is provably non-credential-"
        "bearing -- added to the allowlist with a justification comment:\n"
        + "\n".join(violations)
    )
