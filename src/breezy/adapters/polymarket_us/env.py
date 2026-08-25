"""Credential loading for the Polymarket.us adapter.

Resolves the environment variable *names* carried by
:class:`PolymarketUSSecretsRefConfig` into runtime
:class:`PolymarketUSCredentials`, whose fields are
:class:`~breezy.adapters.polymarket_us.secure.RedactedSecureString` -- the
Breezy subclass of Nautilus's ``SecureString`` that renders no fragment of the
protected value. The bare base class is NOT used for credential material: its
``__repr__`` publishes the first and last four characters, and
``dataclasses.asdict`` walks straight past the container's own ``__repr__`` to
reach it.

Null hypothesis (CLAUDE.md): Nautilus ships
``nautilus_trader.adapters.env.get_env_key``. It does not fit this seam, for
three reasons visible in its four-line body: it reads ``os.environ`` directly
with no injectable mapping (the repo's credential tripwire in
``tests/conftest.py`` aborts any pytest session with a Polymarket variable
set, so tests must inject), it accepts a blank value as present, and it raises
``RuntimeError`` rather than a typed, catchable credential error. The
file-based source it has no notion of at all. It is therefore mirrored, not
reused; nothing here modifies or reimplements Nautilus behaviour.

Security controls implemented here (POLYMARKET_US_READONLY_AUTH_PLAN.md §11):

* **S4** — the secret key file is opened with ``O_NOFOLLOW`` and every check
  is made against the resulting descriptor via ``os.fstat``. There is exactly
  one path resolution, so there is no stat-then-read window an attacker can
  swap a symlink into.
* **S6** — no exception message, argument, or frame carries secret material.
  Failures report the variable name, the path, the observed octal mode, the
  observed uid, or a decoded length; never a value.

Residual gap — S4 covers the FINAL path component only
------------------------------------------------------
``O_NOFOLLOW`` refuses a symlink at the last component of the path and every
subsequent check runs against that one descriptor via ``os.fstat``, so there is
no stat-then-read window on the file itself. It does NOT defend a symlinked
*ancestor* directory: given ``/etc/breezy/keys/pm.key``, an attacker who can
replace the ``keys`` (or ``breezy``, or ``etc``) directory with a symlink can
still redirect the open, because ``O_NOFOLLOW`` constrains only the final
component. Closing this would need ``O_PATH``/``openat2(RESOLVE_NO_SYMLINKS)``
directory-walk resolution, which is Linux-specific and not implemented here.

Mitigation is operational, not code: the key file must live in a directory
chain owned by the running user or root and not group/world-writable. Deploy
accordingly. Documented in the same spirit as the B4 residual gap.

Blocking I/O — must not run on the Nautilus event loop
------------------------------------------------------
``load_polymarket_us_credentials`` performs synchronous filesystem I/O
(``os.open``/``os.read``/``os.fstat``). When the async data client lands, calling
it from a coroutine would block the Nautilus event loop and stall every other
client on it. Load credentials ONCE at startup, before the loop runs (e.g. in
the adapter factory), or wrap the call in ``asyncio.to_thread``. See
``docs/plans/POLYMARKET_US_READONLY_AUTH_PLAN.md``.
"""

from __future__ import annotations

import base64
import binascii
import os
import stat
import warnings
from collections.abc import Mapping
from typing import Final

from breezy.adapters.polymarket_us.credentials import (
    PolymarketUSCredentials,
    PolymarketUSSecretsRefConfig,
)
from breezy.adapters.polymarket_us.errors import CredentialSourceError
from breezy.adapters.polymarket_us.secure import RedactedSecureString

__all__ = [
    "DEFAULT_KEY_FILE_MODE",
    "MAX_KEY_FILE_BYTES",
    "VALID_SECRET_KEY_LENGTHS",
    "CredentialSourceError",
    "load_polymarket_us_credentials",
]

# Re-exported, never redefined: the single definition lives in ``errors.py``
# so that one ``except CredentialSourceError`` catches the loader seam and the
# signing seam alike.

DEFAULT_KEY_FILE_MODE: Final[int] = 0o600
MAX_KEY_FILE_BYTES: Final[int] = 8192
VALID_SECRET_KEY_LENGTHS: Final[frozenset[int]] = frozenset({32, 64})

_READ_CHUNK: Final[int] = 4096


def load_polymarket_us_credentials(
    secrets_ref: PolymarketUSSecretsRefConfig,
    *,
    env: Mapping[str, str] | None = None,
    require_key_file_mode: int = DEFAULT_KEY_FILE_MODE,
    require_owner_uid: int | None = None,
) -> PolymarketUSCredentials:
    """Resolve Polymarket.us credentials from the environment.

    Parameters
    ----------
    secrets_ref : PolymarketUSSecretsRefConfig
        Carries the environment variable NAMES to read. Never a value.
    env : Mapping[str, str], optional
        Environment mapping to read. Defaults to ``os.environ``.
    require_key_file_mode : int, default ``0o600``
        Exact permission bits the secret key file must carry.
    require_owner_uid : int, optional
        Uid the secret key file must be owned by. Defaults to ``os.getuid()``.

    Raises
    ------
    CredentialSourceError
        If a source is missing, ambiguous, unsafe, or malformed.

    """
    source = os.environ if env is None else env
    owner_uid = os.getuid() if require_owner_uid is None else require_owner_uid

    key_id = _require_present(source, secrets_ref.key_id_env_var)
    secret_key = _resolve_secret_key(
        source,
        secrets_ref,
        require_key_file_mode=require_key_file_mode,
        require_owner_uid=owner_uid,
    )
    _validate_secret_shape(secret_key)

    return PolymarketUSCredentials(
        key_id=RedactedSecureString(key_id, name="polymarket_us_key_id"),
        secret_key=RedactedSecureString(secret_key, name="polymarket_us_secret_key"),
    )


def _resolve_secret_key(
    source: Mapping[str, str],
    secrets_ref: PolymarketUSSecretsRefConfig,
    *,
    require_key_file_mode: int,
    require_owner_uid: int,
) -> str:
    file_var = secrets_ref.secret_key_file_env_var
    inline_var = secrets_ref.secret_key_env_var
    file_path = _optional(source, file_var)
    inline = _optional(source, inline_var)

    if file_path is not None and inline is not None:
        raise CredentialSourceError(
            f"Ambiguous secret source: both {file_var} and {inline_var} are set; "
            f"unset one (the {file_var} source is preferred)"
        )
    if file_path is not None:
        return _read_secret_key_file(
            file_path,
            require_mode=require_key_file_mode,
            require_uid=require_owner_uid,
        )
    if inline is not None:
        warnings.warn(
            f"Reading the Polymarket.us secret key from {inline_var}; a "
            f"0600 key file referenced by {file_var} is the preferred source",
            UserWarning,
            stacklevel=3,
        )
        return inline

    raise CredentialSourceError(
        f"No secret key source: set exactly one of {file_var} (preferred) or {inline_var}"
    )


def _read_secret_key_file(path: str, *, require_mode: int, require_uid: int) -> str:
    """Open once with ``O_NOFOLLOW``, validate the descriptor, then read it.

    Residual gap: ``O_NOFOLLOW`` constrains the FINAL path component only. A
    symlinked ANCESTOR directory can still redirect this open; see the module
    docstring for the operational mitigation.
    """
    # BLOCKING I/O. This must never execute on the Nautilus event loop. When
    # the async data client lands, load credentials once at startup before the
    # loop runs, or call through asyncio.to_thread -- otherwise this stalls
    # every other client sharing the loop.
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        fd = os.open(path, flags)
    except FileNotFoundError as exc:
        raise CredentialSourceError(f"Secret key file {path} does not exist") from exc
    except OSError as exc:
        raise CredentialSourceError(
            f"Secret key file {path} could not be opened safely "
            f"(errno {exc.errno}); a symlink at the final path component is refused"
        ) from exc

    try:
        st = os.fstat(fd)
        _assert_descriptor_is_safe(
            st,
            path=path,
            require_mode=require_mode,
            require_uid=require_uid,
        )
        raw = _read_all(fd, path=path)
    finally:
        os.close(fd)

    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        # `from None`: UnicodeDecodeError.object carries the raw file bytes,
        # so the chained exception must never reach a formatted traceback.
        raise CredentialSourceError(f"Secret key file {path} is not ASCII text") from None
    del raw
    return text.strip()


def _assert_descriptor_is_safe(
    st: os.stat_result,
    *,
    path: str,
    require_mode: int,
    require_uid: int,
) -> None:
    if not stat.S_ISREG(st.st_mode):
        raise CredentialSourceError(f"Secret key file {path} is not a regular file")

    mode = stat.S_IMODE(st.st_mode)
    if mode != require_mode:
        raise CredentialSourceError(
            f"Secret key file {path} has mode 0o{mode:03o}; expected exactly 0o{require_mode:03o}"
        )

    if st.st_uid != require_uid:
        raise CredentialSourceError(
            f"Secret key file {path} is owned by uid {st.st_uid}; "
            f"expected uid {require_uid} (the running process uid)"
        )


def _read_all(fd: int, *, path: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(fd, _READ_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_KEY_FILE_BYTES:
            raise CredentialSourceError(
                f"Secret key file {path} exceeds {MAX_KEY_FILE_BYTES} bytes; "
                "it does not look like a key file"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_secret_shape(secret_key: str) -> None:
    """Check base64 shape and decoded length without echoing the value."""
    try:
        decoded = base64.b64decode(secret_key, validate=True)
    except (binascii.Error, ValueError):
        raise CredentialSourceError("Secret key is not valid base64 (value withheld)") from None

    decoded_len = len(decoded)
    del decoded
    if decoded_len not in VALID_SECRET_KEY_LENGTHS:
        expected = ", ".join(str(n) for n in sorted(VALID_SECRET_KEY_LENGTHS))
        raise CredentialSourceError(
            f"Secret key decodes to {decoded_len} bytes; expected {expected}"
        )


def _optional(source: Mapping[str, str], name: str) -> str | None:
    raw = source.get(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _require_present(source: Mapping[str, str], name: str) -> str:
    value = _optional(source, name)
    if value is None:
        raise CredentialSourceError(f"Environment variable {name} is not set (or is blank)")
    return value
