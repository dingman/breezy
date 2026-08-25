"""Step 3 (POLYMARKET_US_READONLY_AUTH_PLAN.md §9) — credential loading.

Every key used here is generated in-process. No test in this module reads,
writes, or depends on a real credential, and none touches ``os.environ``:
the loader takes an injected ``env`` mapping precisely so the repo-wide
credential tripwire (``tests/conftest.py``) stays meaningful.
"""

from __future__ import annotations

import base64
import os
import stat
import traceback
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from breezy.adapters.polymarket_us.credentials import (
    PolymarketUSCredentials,
    PolymarketUSSecretsRefConfig,
)
from breezy.adapters.polymarket_us.env import (
    CredentialSourceError,
    load_polymarket_us_credentials,
)
from breezy.adapters.polymarket_us.secure import RedactedSecureString

KEY_ID_VAR = "POLYMARKET_US_KEY_ID"
SECRET_VAR = "POLYMARKET_US_SECRET_KEY"
SECRET_FILE_VAR = "POLYMARKET_US_SECRET_KEY_FILE"

REF = PolymarketUSSecretsRefConfig()
FAKE_KEY_ID = "11111111-2222-3333-4444-555555555555"


def make_secret(size: int = 32) -> str:
    """Return a freshly generated base64 secret. Never a real credential."""
    return base64.b64encode(os.urandom(size)).decode("ascii")


def write_key_file(path: Path, secret: str, mode: int = 0o600) -> Path:
    path.write_text(secret, encoding="ascii")
    path.chmod(mode)
    return path


@pytest.fixture
def secret() -> str:
    return make_secret()


# ---------------------------------------------------------------------------
# Config surface
# ---------------------------------------------------------------------------


def test_secrets_ref_config_names_the_key_file_variable() -> None:
    assert REF.secret_key_file_env_var == SECRET_FILE_VAR


# ---------------------------------------------------------------------------
# key_id
# ---------------------------------------------------------------------------


def test_missing_key_id_raises_naming_only_the_variable(tmp_path: Path, secret: str) -> None:
    key_file = write_key_file(tmp_path / "key", secret)
    env: Mapping[str, str] = {SECRET_FILE_VAR: str(key_file)}

    with pytest.raises(CredentialSourceError) as excinfo:
        load_polymarket_us_credentials(REF, env=env)

    message = str(excinfo.value)
    assert KEY_ID_VAR in message
    assert secret not in message


def test_blank_key_id_is_rejected(tmp_path: Path, secret: str) -> None:
    key_file = write_key_file(tmp_path / "key", secret)
    env = {KEY_ID_VAR: "   ", SECRET_FILE_VAR: str(key_file)}

    with pytest.raises(CredentialSourceError, match=KEY_ID_VAR):
        load_polymarket_us_credentials(REF, env=env)


# ---------------------------------------------------------------------------
# Source selection
# ---------------------------------------------------------------------------


def test_both_secret_sources_set_is_rejected_as_ambiguous(tmp_path: Path, secret: str) -> None:
    key_file = write_key_file(tmp_path / "key", secret)
    env = {
        KEY_ID_VAR: FAKE_KEY_ID,
        SECRET_VAR: secret,
        SECRET_FILE_VAR: str(key_file),
    }

    with pytest.raises(CredentialSourceError) as excinfo:
        load_polymarket_us_credentials(REF, env=env)

    message = str(excinfo.value)
    assert SECRET_VAR in message
    assert SECRET_FILE_VAR in message
    assert secret not in message


def test_neither_secret_source_set_is_rejected() -> None:
    with pytest.raises(CredentialSourceError) as excinfo:
        load_polymarket_us_credentials(REF, env={KEY_ID_VAR: FAKE_KEY_ID})

    message = str(excinfo.value)
    assert SECRET_VAR in message
    assert SECRET_FILE_VAR in message


def test_env_var_secret_source_loads_but_warns(secret: str) -> None:
    env = {KEY_ID_VAR: FAKE_KEY_ID, SECRET_VAR: secret}

    with pytest.warns(UserWarning) as recorded:
        credentials = load_polymarket_us_credentials(REF, env=env)

    secret_round_trips = credentials.secret_key.get_value() == secret

    assert secret_round_trips, "secret_key does not round-trip (value withheld)"
    warning_text = "".join(str(record.message) for record in recorded)
    assert SECRET_FILE_VAR in warning_text
    assert secret not in warning_text


# ---------------------------------------------------------------------------
# Key file hardening (S4)
# ---------------------------------------------------------------------------


def test_key_file_with_0600_mode_loads_into_secure_string(tmp_path: Path, secret: str) -> None:
    key_file = write_key_file(tmp_path / "key", secret)
    env = {KEY_ID_VAR: FAKE_KEY_ID, SECRET_FILE_VAR: str(key_file)}

    credentials = load_polymarket_us_credentials(REF, env=env)

    assert isinstance(credentials, PolymarketUSCredentials)
    assert isinstance(credentials.secret_key, RedactedSecureString)
    assert isinstance(credentials.key_id, RedactedSecureString)
    secret_round_trips = credentials.secret_key.get_value() == secret
    key_id_round_trips = credentials.key_id.get_value() == FAKE_KEY_ID

    assert secret_round_trips, "secret_key does not round-trip (value withheld)"
    assert key_id_round_trips, "key_id does not round-trip (value withheld)"


def test_key_file_trailing_newline_is_stripped(tmp_path: Path, secret: str) -> None:
    key_file = tmp_path / "key"
    key_file.write_text(secret + "\n", encoding="ascii")
    key_file.chmod(0o600)
    env = {KEY_ID_VAR: FAKE_KEY_ID, SECRET_FILE_VAR: str(key_file)}

    credentials = load_polymarket_us_credentials(REF, env=env)
    secret_round_trips = credentials.secret_key.get_value() == secret

    assert secret_round_trips, "secret_key does not round-trip (value withheld)"


def test_key_file_with_group_readable_mode_is_rejected(tmp_path: Path, secret: str) -> None:
    key_file = write_key_file(tmp_path / "key", secret, mode=0o640)
    env = {KEY_ID_VAR: FAKE_KEY_ID, SECRET_FILE_VAR: str(key_file)}

    with pytest.raises(CredentialSourceError) as excinfo:
        load_polymarket_us_credentials(REF, env=env)

    message = str(excinfo.value)
    assert "0o640" in message
    assert "0o600" in message
    assert str(key_file) in message
    assert secret not in message


def test_symlinked_key_file_is_rejected_by_o_nofollow(tmp_path: Path, secret: str) -> None:
    target = write_key_file(tmp_path / "real-key", secret)
    link = tmp_path / "link-key"
    link.symlink_to(target)
    env = {KEY_ID_VAR: FAKE_KEY_ID, SECRET_FILE_VAR: str(link)}

    with pytest.raises(CredentialSourceError) as excinfo:
        load_polymarket_us_credentials(REF, env=env)

    message = str(excinfo.value)
    assert str(link) in message
    assert secret not in message


def test_symlink_swapped_between_stat_and_read_cannot_be_observed(
    tmp_path: Path,
    secret: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The path is resolved exactly once; all checks apply to the open FD."""
    key_file = write_key_file(tmp_path / "key", secret)
    env = {KEY_ID_VAR: FAKE_KEY_ID, SECRET_FILE_VAR: str(key_file)}

    opens: list[tuple[str, int]] = []
    path_stats: list[str] = []
    fd_stats: list[int] = []

    real_open = os.open
    real_fstat = os.fstat

    def counting_open(path: str | os.PathLike[str], flags: int, mode: int = 0o777) -> int:
        opens.append((os.fspath(path), flags))
        return real_open(path, flags, mode)

    def recording_fstat(fd: int) -> os.stat_result:
        fd_stats.append(fd)
        return real_fstat(fd)

    def forbidden_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        path_stats.append(str(path))
        raise AssertionError("loader must not resolve the path a second time")

    monkeypatch.setattr(os, "open", counting_open)
    monkeypatch.setattr(os, "fstat", recording_fstat)
    monkeypatch.setattr(os, "stat", forbidden_stat)
    monkeypatch.setattr(os, "lstat", forbidden_stat)
    monkeypatch.setattr(Path, "stat", forbidden_stat)
    monkeypatch.setattr(Path, "read_text", forbidden_stat)
    monkeypatch.setattr(Path, "read_bytes", forbidden_stat)

    credentials = load_polymarket_us_credentials(REF, env=env)

    secret_round_trips = credentials.secret_key.get_value() == secret

    assert secret_round_trips, "secret_key does not round-trip (value withheld)"
    assert path_stats == []
    assert len(opens) == 1, f"expected exactly one open(), saw {opens}"
    opened_path, flags = opens[0]
    assert opened_path == str(key_file)
    assert flags & os.O_NOFOLLOW, "key file must be opened with O_NOFOLLOW"
    assert len(fd_stats) == 1, "checks must be made against the opened descriptor"


def test_key_file_owned_by_another_uid_is_rejected(
    tmp_path: Path,
    secret: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_file = write_key_file(tmp_path / "key", secret)
    env = {KEY_ID_VAR: FAKE_KEY_ID, SECRET_FILE_VAR: str(key_file)}
    foreign_uid = os.getuid() + 1

    with pytest.raises(CredentialSourceError) as excinfo:
        load_polymarket_us_credentials(REF, env=env, require_owner_uid=foreign_uid)

    message = str(excinfo.value)
    assert str(foreign_uid) in message
    assert str(os.getuid()) in message
    assert secret not in message

    # And the same rejection when fstat reports a foreign owner for the FD.
    real_fstat = os.fstat

    def foreign_owner_fstat(fd: int) -> os.stat_result:
        result = real_fstat(fd)
        fields = list(result)
        fields[stat.ST_UID] = foreign_uid
        return os.stat_result(fields)

    monkeypatch.setattr(os, "fstat", foreign_owner_fstat)
    with pytest.raises(CredentialSourceError, match=str(foreign_uid)):
        load_polymarket_us_credentials(REF, env=env)


def test_directory_as_key_file_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "keydir"
    directory.mkdir(mode=0o700)
    env = {KEY_ID_VAR: FAKE_KEY_ID, SECRET_FILE_VAR: str(directory)}

    with pytest.raises(CredentialSourceError, match="regular file"):
        load_polymarket_us_credentials(REF, env=env)


def test_absent_key_file_names_the_path_not_the_variable_value(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    env = {KEY_ID_VAR: FAKE_KEY_ID, SECRET_FILE_VAR: str(missing)}

    with pytest.raises(CredentialSourceError) as excinfo:
        load_polymarket_us_credentials(REF, env=env)

    assert str(missing) in str(excinfo.value)


# ---------------------------------------------------------------------------
# Shape validation
# ---------------------------------------------------------------------------


def test_malformed_base64_secret_is_rejected_without_echoing_the_value() -> None:
    bad = "not base64 !!!! at all ????"
    env = {KEY_ID_VAR: FAKE_KEY_ID, SECRET_VAR: bad}

    with pytest.raises(CredentialSourceError) as excinfo:
        load_polymarket_us_credentials(REF, env=env)

    message = str(excinfo.value)
    assert bad not in message
    assert "base64" in message


def test_secret_of_wrong_decoded_length_reports_only_the_length() -> None:
    short = base64.b64encode(os.urandom(16)).decode("ascii")
    env = {KEY_ID_VAR: FAKE_KEY_ID, SECRET_VAR: short}

    with pytest.raises(CredentialSourceError) as excinfo:
        load_polymarket_us_credentials(REF, env=env)

    message = str(excinfo.value)
    assert "16" in message
    assert short not in message


def test_64_byte_secret_is_accepted() -> None:
    long_secret = make_secret(64)
    env = {KEY_ID_VAR: FAKE_KEY_ID, SECRET_VAR: long_secret}

    with pytest.warns(UserWarning):
        credentials = load_polymarket_us_credentials(REF, env=env)

    secret_round_trips = credentials.secret_key.get_value() == long_secret

    assert secret_round_trips, "secret_key does not round-trip (value withheld)"


# ---------------------------------------------------------------------------
# SEC-3: no secret in any message, repr, or traceback
# ---------------------------------------------------------------------------


def _failing_cases(tmp_path: Path, secret: str) -> Iterator[Mapping[str, str]]:
    group_readable = write_key_file(tmp_path / "mode-key", secret, mode=0o640)
    world_readable = write_key_file(tmp_path / "world-key", secret, mode=0o644)
    good = write_key_file(tmp_path / "good-key", secret)
    link = tmp_path / "link-key"
    link.symlink_to(good)

    yield {KEY_ID_VAR: FAKE_KEY_ID, SECRET_FILE_VAR: str(group_readable)}
    yield {KEY_ID_VAR: FAKE_KEY_ID, SECRET_FILE_VAR: str(world_readable)}
    yield {KEY_ID_VAR: FAKE_KEY_ID, SECRET_FILE_VAR: str(link)}
    yield {KEY_ID_VAR: FAKE_KEY_ID, SECRET_VAR: secret, SECRET_FILE_VAR: str(good)}
    yield {SECRET_VAR: secret}
    yield {KEY_ID_VAR: FAKE_KEY_ID, SECRET_VAR: secret + "%%%"}
    yield {KEY_ID_VAR: FAKE_KEY_ID, SECRET_VAR: base64.b64encode(b"x" * 7).decode("ascii")}


@pytest.mark.parametrize("size", [32, 64])
def test_secret_absent_from_str_and_from_formatted_traceback(tmp_path: Path, size: int) -> None:
    secret = make_secret(size)
    case_dir = tmp_path / f"case{size}"
    case_dir.mkdir()
    for index, env in enumerate(_failing_cases(case_dir, secret)):
        try:
            load_polymarket_us_credentials(REF, env=env)
        except CredentialSourceError as exc:
            formatted = traceback.format_exc()
            assert secret not in str(exc), f"secret leaked into str() for case {index}"
            assert secret not in repr(exc), f"secret leaked into repr() for case {index}"
            assert secret not in formatted, f"secret leaked into traceback for case {index}"
        else:  # pragma: no cover - defensive
            raise AssertionError(f"case {index} unexpectedly succeeded")


def test_secret_never_appears_in_repr_of_credentials_or_config(tmp_path: Path) -> None:
    secret = make_secret()
    key_file = write_key_file(tmp_path / "key", secret)
    env = {KEY_ID_VAR: FAKE_KEY_ID, SECRET_FILE_VAR: str(key_file)}

    credentials = load_polymarket_us_credentials(REF, env=env)

    for rendered in (repr(credentials), str(credentials), repr(REF), str(REF)):
        assert secret not in rendered
        assert FAKE_KEY_ID not in rendered


def test_loader_does_not_read_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """With an injected mapping the loader must ignore ``os.environ`` entirely."""

    def forbidden_environ_get(*args: object, **kwargs: object) -> str:
        raise AssertionError("loader read os.environ despite an injected mapping")

    monkeypatch.setattr(os.environ, "get", forbidden_environ_get)

    with pytest.raises(CredentialSourceError):
        load_polymarket_us_credentials(REF, env={})
