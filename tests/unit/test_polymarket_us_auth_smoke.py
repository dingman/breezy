"""Offline contract for the venue connectivity smoke script (plan Step 15).

Authority: ``docs/plans/archive/POLYMARKET_US_READONLY_AUTH_PLAN.md`` (revision 2)
section 10 (smoke procedure and evidence, ``:1306-1352``), control S15 (core
dumps, ``:1374``) and SEC-4 (``TRADING_ENABLEMENT_REVIEW.md:115-116``).

The live path itself is ``venue_live``-marked and lives in the script; it is
never exercised here. What IS exercised offline is everything that decides
whether a secret escapes:

* the refusal to run without an explicit unlock;
* ``RLIMIT_CORE`` being zeroed BEFORE any credential is read -- a crash during
  signing would otherwise write the Ed25519 key into a core file, and
  ``SecureString`` cannot prevent that (plan ``:1374``: ``clear()`` rebinds an
  immutable ``str`` and cannot scrub the original object's memory);
* the evidence artefact redacting ``X-PM-Signature`` **and** ``X-PM-Access-Key``,
  and carrying no secret and no four-character fragment of one.

That last one is the highest-blast-radius leak path in the slice: the evidence
file is the one artefact designed to be committed to the repository. Every
assertion about it is therefore paired with a proof-by-construction that the
detector actually fires (``*_detects_*``), so no barrier here can pass
vacuously.
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import importlib.util
import os
import resource
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from nacl.signing import SigningKey
from nautilus_trader.core.uuid import UUID4

from breezy.adapters.polymarket_us.credentials import (
    PolymarketUSCredentials,
    PolymarketUSSecretsRefConfig,
)
from breezy.adapters.polymarket_us.errors import VenueTransportError
from breezy.adapters.polymarket_us.factories import (
    API_BASE_ENV_VAR,
    DISCOVERY_RELOAD_INTERVAL_ENV_VAR,
    GATEWAY_BASE_ENV_VAR,
    MARKET_SLUGS_ENV_VAR,
    USER_AGENT_ENV_VAR,
    WS_URL_ENV_VAR,
)
from breezy.adapters.polymarket_us.redaction import REDACTED
from breezy.adapters.polymarket_us.secure import RedactedSecureString

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "venue" / "polymarket_us_auth_smoke.py"
SCRIPT_REL = "scripts/venue/polymarket_us_auth_smoke.py"

SLUG = "tc-temp-nychigh-2026-08-25-lt79f"
USER_AGENT = "breezy-smoke/1.0 (+mailto:ops@example.com)"
LEAK_SAFE_SECRET = base64.b64encode(bytes(range(32))).decode("ascii")
LEAK_SAFE_KEY_ID = "f13c9a7b-2d6e-4a80-b935-c8e20d41ab67"


def _load_smoke_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("breezy_polymarket_us_auth_smoke", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke_module()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_secret() -> str:
    """A freshly generated base64 Ed25519 secret. Never a real credential."""
    return base64.b64encode(bytes(SigningKey.generate())).decode("ascii")


def make_leak_safe_secret_pair() -> tuple[str, str]:
    """Deterministic fake credentials whose fragments do not occur in evidence text."""
    return LEAK_SAFE_SECRET, LEAK_SAFE_KEY_ID


@contextmanager
def permissive_umask() -> Iterator[None]:
    previous = os.umask(0)
    try:
        yield
    finally:
        os.umask(previous)


def make_credentials(secret: str, key_id: str) -> PolymarketUSCredentials:
    return PolymarketUSCredentials(
        key_id=RedactedSecureString(key_id, name="polymarket_us_key_id"),
        secret_key=RedactedSecureString(secret, name="polymarket_us_secret_key"),
    )


def make_env(**overrides: str) -> dict[str, str]:
    env = {
        smoke.VENUE_LIVE_ENV_VAR: "1",
        API_BASE_ENV_VAR: "https://api.polymarket.us",
        GATEWAY_BASE_ENV_VAR: "https://gateway.polymarket.us",
        WS_URL_ENV_VAR: "wss://api.polymarket.us",
        MARKET_SLUGS_ENV_VAR: SLUG,
        DISCOVERY_RELOAD_INTERVAL_ENV_VAR: "5",
        USER_AGENT_ENV_VAR: USER_AGENT,
    }
    env.update(overrides)
    return env


def make_report(*, key_id: str, signature: str) -> Any:
    """A report carrying REAL header values, so redaction is load-bearing."""
    sent_headers: Mapping[str, str] = {
        "X-PM-Access-Key": key_id,
        "X-PM-Timestamp": "1787000000000",
        "X-PM-Signature": signature,
        "User-Agent": USER_AGENT,
    }
    record = smoke.RequestRecord(
        step="B",
        label="authenticated portfolio read",
        path="/v1/portfolio/positions",
        query_string="",
        status=200,
        latency_ms=42.5,
        sent_headers=sent_headers,
        observed_headers={"date": "Tue, 25 Aug 2026 12:00:00 GMT"},
        note="accepted",
    )
    return smoke.SmokeReport(
        started_at="2026-08-25T12:00:00Z",
        finished_at="2026-08-25T12:03:00Z",
        core_limit=(0, 0),
        key_file_device=2049,
        key_file_filesystem="ext4",
        host_clock_offset_ms=12,
        user_agent=USER_AGENT,
        api_base_url="https://api.polymarket.us",
        gateway_base_url="https://gateway.polymarket.us",
        ws_url="wss://api.polymarket.us",
        market_slugs=(SLUG,),
        requests=(record,),
        findings=(
            smoke.Finding(key="E1", question="q", answer="a"),
            smoke.Finding(key="C", question="q", answer="a"),
            smoke.Finding(key="G", question="q", answer="a"),
            smoke.Finding(key="SLUG", question="q", answer="a"),
            smoke.Finding(key="G15", question="q", answer="a"),
        ),
        frame_schemas=(
            smoke.FrameSchema(
                frame_class="market_data",
                keys=("marketSlug", "bids"),
                structure_paths=("marketSlug", "bids"),
                value_types={"marketSlug": "str", "bids": "list"},
                safe_values={"marketSlug": SLUG},
                slug_bearing_keys=("marketSlug",),
            ),
        ),
        frame_class_counts={"market_data": 1},
        instrument_ids=(f"{SLUG}.POLYMARKET_US",),
        frames_received=17,
        quotes_delivered=12,
        quotes_per_slug={SLUG: 12},
        log_excerpt=("12:00:01Z connected", "12:00:02Z subscribed"),
        write_requests_issued=0,
        verdict=True,
        verdict_reason="authenticated GET accepted and quotes reached the DataEngine",
    )


# ---------------------------------------------------------------------------
# The run guard
# ---------------------------------------------------------------------------


def test_smoke_refuses_to_run_without_the_venue_live_unlock() -> None:
    env = make_env()
    del env[smoke.VENUE_LIVE_ENV_VAR]

    with pytest.raises(smoke.SmokeRefusal, match=smoke.VENUE_LIVE_ENV_VAR):
        smoke.assert_smoke_enabled(env)


def test_smoke_refusal_reports_when_the_venue_live_unlock_is_absent() -> None:
    env = make_env()
    del env[smoke.VENUE_LIVE_ENV_VAR]

    with pytest.raises(smoke.SmokeRefusal) as caught:
        smoke.assert_smoke_enabled(env)

    message = str(caught.value)
    assert f"Observed {smoke.VENUE_LIVE_ENV_VAR}: absent" in message
    assert f"pid={os.getpid()}" in message
    assert f"executable={sys.executable!r}" in message


def test_smoke_refusal_reports_the_observed_venue_live_value_with_repr() -> None:
    with pytest.raises(smoke.SmokeRefusal) as caught:
        smoke.assert_smoke_enabled(make_env(**{smoke.VENUE_LIVE_ENV_VAR: "1\n"}))

    message = str(caught.value)
    assert f"Observed {smoke.VENUE_LIVE_ENV_VAR}: '1\\n'" in message
    assert "POLYMARKET_US_" not in message


@pytest.mark.parametrize("value", ["0", "true", "yes", "on", "", " 1"])
def test_smoke_refuses_any_value_but_the_exact_string_one(value: str) -> None:
    with pytest.raises(smoke.SmokeRefusal):
        smoke.assert_smoke_enabled(make_env(**{smoke.VENUE_LIVE_ENV_VAR: value}))


def test_smoke_accepts_the_explicit_unlock() -> None:
    smoke.assert_smoke_enabled(make_env())


@pytest.mark.parametrize("level", ["DEBUG", "TRACE", "debug"])
def test_smoke_refuses_under_header_logging_log_levels(level: str) -> None:
    """S5: a DEBUG/TRACE run can print request headers, signature included."""
    with pytest.raises(smoke.SmokeRefusal, match="BREEZY_LOG_LEVEL"):
        smoke.assert_smoke_enabled(make_env(BREEZY_LOG_LEVEL=level))


# ---------------------------------------------------------------------------
# S15 -- core dumps off before any credential is read
# ---------------------------------------------------------------------------


def test_disable_core_dumps_requests_a_zero_rlimit_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[int, tuple[int, int]]] = []

    def fake_setrlimit(which: int, limits: tuple[int, int]) -> None:
        seen.append((which, limits))

    monkeypatch.setattr(smoke.resource, "setrlimit", fake_setrlimit)
    monkeypatch.setattr(smoke.resource, "getrlimit", lambda which: (0, 0))

    result = smoke.disable_core_dumps()

    assert seen == [(resource.RLIMIT_CORE, (0, 0))]
    assert result == (0, 0)


@pytest.mark.parametrize("in_force", [(-1, -1), (0, -1), (1024, 1024), (0, 8)])
def test_disable_core_dumps_refuses_when_the_limit_is_not_actually_zero(
    monkeypatch: pytest.MonkeyPatch,
    in_force: tuple[int, int],
) -> None:
    """setrlimit can be a silent no-op; only the in-force value is evidence."""
    monkeypatch.setattr(smoke.resource, "setrlimit", lambda which, limits: None)
    monkeypatch.setattr(smoke.resource, "getrlimit", lambda which: in_force)

    with pytest.raises(smoke.SmokeRefusal, match="RLIMIT_CORE"):
        smoke.disable_core_dumps()


@pytest.mark.parametrize(
    "exc",
    [OSError(1, "Operation not permitted"), ValueError("bad limits")],
)
def test_disable_core_dumps_refuses_when_setrlimit_raises(
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
) -> None:
    def boom(which: int, limits: tuple[int, int]) -> None:
        raise exc

    monkeypatch.setattr(smoke.resource, "setrlimit", boom)

    with pytest.raises(smoke.SmokeRefusal) as caught:
        smoke.disable_core_dumps()

    # Scrubbed: type and errno only, never the raw payload of the exception.
    assert type(exc).__name__ in str(caught.value)
    assert "bad limits" not in str(caught.value)


def test_disable_core_dumps_refuses_when_getrlimit_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(smoke.resource, "setrlimit", lambda which, limits: None)

    def boom(which: int) -> tuple[int, int]:
        raise OSError(22, "Invalid argument")

    monkeypatch.setattr(smoke.resource, "getrlimit", boom)

    with pytest.raises(smoke.SmokeRefusal, match="OSError"):
        smoke.disable_core_dumps()


def test_disable_core_dumps_refuses_when_the_platform_lacks_rlimit_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A platform with no RLIMIT_CORE cannot prove the key stays out of a dump."""
    monkeypatch.delattr(smoke.resource, "RLIMIT_CORE", raising=True)

    with pytest.raises(smoke.SmokeRefusal, match="RLIMIT_CORE"):
        smoke.disable_core_dumps()


def test_prepare_refuses_before_any_credential_read_when_core_limit_is_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal must land before the enablement check AND the secret read."""
    order: list[str] = []

    monkeypatch.setattr(smoke.resource, "setrlimit", lambda which, limits: None)
    monkeypatch.setattr(smoke.resource, "getrlimit", lambda which: (1024, 1024))

    def fake_loader(*args: Any, **kwargs: Any) -> PolymarketUSCredentials:
        order.append("credentials-loaded")  # pragma: no cover
        raise AssertionError("credentials must not be read once dumps may be written")

    monkeypatch.setattr(smoke, "load_polymarket_us_credentials", fake_loader)

    with pytest.raises(smoke.SmokeRefusal, match="RLIMIT_CORE"):
        smoke.prepare(make_env())

    assert order == []


def test_main_reports_a_core_dump_refusal_as_a_clean_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A raising setrlimit must exit 2 with REFUSED, never a traceback."""

    def boom(which: int, limits: tuple[int, int]) -> None:
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(smoke.resource, "setrlimit", boom)

    exit_code = smoke.main([])

    assert exit_code == 2
    assert "REFUSED" in capsys.readouterr().err


def test_core_dumps_are_disabled_before_credentials_are_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ordering IS the control; a later call would leave a crash window."""
    order: list[str] = []
    credentials = make_credentials(make_secret(), str(UUID4()))

    def fake_disable() -> tuple[int, int]:
        order.append("core-dumps-disabled")
        return (0, 0)

    def fake_loader(
        secrets_ref: PolymarketUSSecretsRefConfig, **kwargs: Any
    ) -> PolymarketUSCredentials:
        order.append("credentials-loaded")
        return credentials

    monkeypatch.setattr(smoke, "disable_core_dumps", fake_disable)
    monkeypatch.setattr(smoke, "load_polymarket_us_credentials", fake_loader)

    prepared = smoke.prepare(make_env())

    assert order == ["core-dumps-disabled", "credentials-loaded"]
    assert prepared.core_limit == (0, 0)


def test_prepare_refuses_before_touching_credentials_when_not_unlocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []

    def fake_disable_core_dumps() -> tuple[int, int]:
        order.append("core")
        return (0, 0)

    monkeypatch.setattr(smoke, "disable_core_dumps", fake_disable_core_dumps)

    def fake_loader(*args: Any, **kwargs: Any) -> PolymarketUSCredentials:
        order.append("credentials-loaded")  # pragma: no cover
        raise AssertionError("credentials must not be read by a refused run")

    monkeypatch.setattr(smoke, "load_polymarket_us_credentials", fake_loader)
    env = make_env()
    del env[smoke.VENUE_LIVE_ENV_VAR]

    with pytest.raises(smoke.SmokeRefusal):
        smoke.prepare(env)

    assert "credentials-loaded" not in order


# ---------------------------------------------------------------------------
# Fragment detection -- proven non-vacuous
# ---------------------------------------------------------------------------


def test_secret_fragments_enumerates_every_four_character_window() -> None:
    assert smoke.secret_fragments("abcdef") == frozenset({"abcd", "bcde", "cdef"})


def test_secret_fragments_of_a_short_secret_is_the_secret_itself() -> None:
    assert smoke.secret_fragments("ab") == frozenset({"ab"})


def test_find_secret_leak_offsets_detects_a_whole_secret() -> None:
    secret = make_secret()

    assert smoke.find_secret_leak_offsets(f"header={secret}", [secret]) != ()


def test_find_secret_leak_offsets_detects_a_four_character_fragment() -> None:
    secret = make_secret()
    fragment = secret[7:11]

    assert smoke.find_secret_leak_offsets(f"stray {fragment} text", [secret]) != ()


def test_find_secret_leak_offsets_is_clean_on_unrelated_text() -> None:
    secret = "A" * 44

    assert smoke.find_secret_leak_offsets("nothing to see here", [secret]) == ()


def test_find_secret_leak_offsets_ignores_empty_secrets() -> None:
    assert smoke.find_secret_leak_offsets("anything at all", ["", None or ""]) == ()


# ---------------------------------------------------------------------------
# SEC-4 -- the evidence artefact
# ---------------------------------------------------------------------------


def test_evidence_redacts_the_signature_header() -> None:
    secret, key_id = make_leak_safe_secret_pair()
    signature = base64.b64encode(b"a-signature-value-here").decode("ascii")
    text = smoke.render_evidence(
        make_report(key_id=key_id, signature=signature), secrets=[secret, key_id, signature]
    )

    assert "X-PM-Signature" in text
    assert signature not in text


def test_evidence_redacts_the_access_key_header() -> None:
    """SEC-4: the access key is redacted too, not only the signature."""
    secret, key_id = make_leak_safe_secret_pair()
    signature = base64.b64encode(b"a-signature-value-here").decode("ascii")
    text = smoke.render_evidence(
        make_report(key_id=key_id, signature=signature), secrets=[secret, key_id, signature]
    )

    assert "X-PM-Access-Key" in text
    assert key_id not in text


def test_evidence_redacts_sensitive_headers_even_with_no_secret_list() -> None:
    """Each redaction layer must hold ALONE, not only in combination.

    Added after a mutation proof: deleting ``x-pm-access-key`` from
    ``SENSITIVE_HEADERS`` did NOT fail the tests above, because
    ``redact_text`` masked the same value a moment later. The two layers were
    genuinely redundant, so neither was actually pinned. Passing an EMPTY
    secret list removes the second layer and leaves only the header-name
    layer under test -- which is also the realistic failure mode, since a
    caller that forgets to collect a secret into the list gets exactly this.
    """
    key_id = LEAK_SAFE_KEY_ID
    signature = base64.b64encode(b"a-signature-value-here").decode("ascii")
    text = smoke.render_evidence(make_report(key_id=key_id, signature=signature), secrets=[])

    assert key_id not in text
    assert signature not in text
    assert "X-PM-Access-Key" in text
    assert "X-PM-Signature" in text


def test_evidence_marks_every_sensitive_header_as_redacted() -> None:
    secret, key_id = make_leak_safe_secret_pair()
    signature = base64.b64encode(b"a-signature-value-here").decode("ascii")
    text = smoke.render_evidence(
        make_report(key_id=key_id, signature=signature), secrets=[secret, key_id, signature]
    )

    for header in ("X-PM-Access-Key", "X-PM-Timestamp", "X-PM-Signature"):
        line = next(line for line in text.splitlines() if line.startswith(f"| `{header}`"))
        assert REDACTED in line


def test_evidence_contains_no_secret_and_no_four_character_fragment() -> None:
    """The single highest-blast-radius assertion in this suite."""
    secret, key_id = make_leak_safe_secret_pair()
    signature = base64.b64encode(b"a-signature-value-here").decode("ascii")
    secrets = [secret, key_id, signature]
    text = smoke.render_evidence(make_report(key_id=key_id, signature=signature), secrets=secrets)

    assert secret not in text
    assert smoke.find_secret_leak_offsets(text, secrets) == ()


def test_evidence_reports_the_operator_facing_facts() -> None:
    secret, key_id = make_leak_safe_secret_pair()
    signature = base64.b64encode(b"sig").decode("ascii")
    text = smoke.render_evidence(
        make_report(key_id=key_id, signature=signature), secrets=[secret, key_id, signature]
    )

    assert f"{SLUG}.POLYMARKET_US" in text
    assert "12" in text  # quote count
    assert "connected" in text  # log excerpt
    assert "PASS" in text


def test_evidence_states_every_open_live_question() -> None:
    secret, key_id = make_leak_safe_secret_pair()
    text = smoke.render_evidence(
        make_report(key_id=key_id, signature="sig"), secrets=[secret, key_id]
    )

    for key in ("E1", "C", "G", "SLUG", "G15"):
        assert f"| {key} " in text


def test_evidence_records_the_websocket_frame_schema_keys() -> None:
    """The ``marketSlug`` field name is a GUESS; the raw keys settle it."""
    secret, key_id = make_leak_safe_secret_pair()
    text = smoke.render_evidence(
        make_report(key_id=key_id, signature="sig"), secrets=[secret, key_id]
    )

    assert "marketSlug" in text
    assert "bids" in text


def test_evidence_records_frame_classes_counts_and_safe_values() -> None:
    secret, key_id = make_leak_safe_secret_pair()
    text = smoke.render_evidence(
        make_report(key_id=key_id, signature="sig"), secrets=[secret, key_id]
    )

    assert "market_data" in text
    assert "| `marketSlug` |" in text
    assert SLUG in text


@pytest.mark.asyncio
async def test_recording_transport_records_transport_failure_as_its_own_event() -> None:
    """A failed request must not inherit the previous successful request record."""

    class FlakyReadTransport:
        calls = 0

        async def get(self, url: str, *, headers: Mapping[str, str], quota_key: str) -> Any:
            del quota_key
            self.calls += 1
            if self.calls == 1:
                return smoke.VenueResponse(
                    status=200,
                    headers={"date": "Tue, 25 Aug 2026 12:00:00 GMT"},
                    body=b"ok",
                )
            raise VenueTransportError(f"GET failed for {url}")

    transport = smoke.RecordingTransport(inner=FlakyReadTransport())

    await transport.get("https://api.polymarket.us/ok", headers={"X-Probe": "first"}, quota_key="q")
    with pytest.raises(VenueTransportError):
        await transport.get(
            "https://api.polymarket.us/fail",
            headers={"X-Probe": "second"},
            quota_key="q",
        )

    record = smoke._record_from(
        transport,
        step="B",
        label="authenticated portfolio read",
        path="/v1/portfolio/positions",
    )

    assert record.status is None
    assert record.sent_headers == {"X-Probe": "second"}
    assert record.observed_headers == {}
    assert "VenueTransportError" in record.note


# ---------------------------------------------------------------------------
# The writer refuses rather than committing a leak
# ---------------------------------------------------------------------------


def test_write_evidence_writes_the_artefact_and_a_digest_sidecar(tmp_path: Path) -> None:
    secret, key_id = make_leak_safe_secret_pair()
    report = make_report(key_id=key_id, signature="sig")

    path = smoke.write_evidence(report, secrets=[secret, key_id], directory=tmp_path)

    assert path.exists()
    sidecar = path.with_suffix(path.suffix + ".sha256")
    assert sidecar.exists()
    assert path.name in sidecar.read_text(encoding="utf-8")


def test_write_evidence_refuses_and_writes_nothing_when_a_fragment_survives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proof the writer's own gate is not vacuous."""
    secret, key_id = make_leak_safe_secret_pair()
    report = make_report(key_id=key_id, signature="sig")
    fragment = secret[3:7]

    monkeypatch.setattr(
        smoke,
        "render_evidence",
        lambda report, *, secrets: f"# leaked\n\nstray {fragment} text\n",
    )

    with pytest.raises(smoke.EvidenceLeakError):
        smoke.write_evidence(report, secrets=[secret, key_id], directory=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_evidence_leak_error_never_echoes_the_fragment_it_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret, key_id = make_leak_safe_secret_pair()
    report = make_report(key_id=key_id, signature="sig")
    fragment = secret[3:7]
    monkeypatch.setattr(
        smoke,
        "render_evidence",
        lambda report, *, secrets: f"stray {fragment} text",
    )

    with pytest.raises(smoke.EvidenceLeakError) as excinfo:
        smoke.write_evidence(report, secrets=[secret, key_id], directory=tmp_path)

    message = str(excinfo.value)
    assert fragment not in message
    assert secret not in message


def test_evidence_filename_is_timestamped_and_lands_under_the_venue_evidence_dir() -> None:
    assert smoke.EVIDENCE_DIRECTORY == Path("docs/evidence/venue/polymarket_us")
    name = smoke.evidence_filename("2026-08-25T120000Z")
    assert name.startswith("READONLY_AUTH_SMOKE_")
    assert name.endswith(".md")
    assert "2026-08-25T120000Z" in name


# ---------------------------------------------------------------------------
# Structural read-only guarantees
# ---------------------------------------------------------------------------


def test_smoke_script_is_classified_as_venue_touching_and_has_no_write_egress() -> None:
    import ast

    from tests.unit.test_polymarket_us_readonly_guard import (
        find_write_egress_violations,
        is_venue_touching,
    )

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert is_venue_touching(SCRIPT_REL, ast.parse(source)) is True
    assert find_write_egress_violations(SCRIPT_REL, source) == []


def test_smoke_script_imports_no_venue_sdk_module() -> None:
    from tests.unit.test_polymarket_us_readonly_guard import find_sdk_import_violations

    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert find_sdk_import_violations(SCRIPT_REL, source) == []


def test_smoke_script_never_disables_tls_verification() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    for banned in ("verify=False", "_create_unverified_context", "CERT_NONE"):
        assert banned not in source


def test_smoke_script_declares_only_the_get_method() -> None:
    source = SCRIPT_PATH.read_text(encoding="utf-8")

    assert smoke.HTTP_METHOD == "GET"
    assert "/v1/orders" not in source


def test_prepare_uses_the_process_environment_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller cannot accidentally hand in a permissive environment mapping."""
    monkeypatch.setattr(smoke, "disable_core_dumps", lambda: (0, 0))
    monkeypatch.delenv(smoke.VENUE_LIVE_ENV_VAR, raising=False)
    assert os.environ.get(smoke.VENUE_LIVE_ENV_VAR) is None

    with pytest.raises(smoke.SmokeRefusal):
        smoke.prepare()


# ---------------------------------------------------------------------------
# main() top-level exception containment (SEC finding 2, 2026-08-25)
# ---------------------------------------------------------------------------
#
# `prepare()` was wrapped in try/except but `asyncio.run(run_smoke(...))` and
# `write_evidence(...)` were not. Anything unanticipated inside the live run --
# `node.build()`, `trader.add_actor()`, or the background `node.run_async()`
# task -- therefore propagated out of `main()` to Python's default excepthook,
# which prints an UNREDACTED traceback. That traceback renders every frame,
# and `main()`'s own frame holds `secrets`, a list containing the plaintext
# Ed25519 secret and key id. The operator's first run against production keys
# is exactly the scenario most likely to reach an unanticipated error.


class _CanaryBoom(RuntimeError):
    """An 'unanticipated' failure whose message carries the secret."""


def _prepared_with(secret: str, key_id: str) -> Any:
    return smoke.Prepared(
        core_limit=(0, 0),
        config=None,
        credentials=make_credentials(secret, key_id),
    )


def test_unexpected_failure_in_run_smoke_is_contained_and_scrubbed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An arbitrary exception from the live run must not reach the excepthook."""
    secret, key_id = make_leak_safe_secret_pair()
    monkeypatch.setattr(smoke, "prepare", lambda *a, **k: _prepared_with(secret, key_id))

    async def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise _CanaryBoom(f"node.build() failed while signing with {secret} / {key_id}")

    monkeypatch.setattr(smoke, "run_smoke", _boom)

    exit_code = smoke.main([])

    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert exit_code != 0, "an unexpected failure must never report success"
    assert "Traceback (most recent call last)" not in combined
    assert secret not in combined
    assert key_id not in combined
    # Fail-closed against fragments too, using the script's own detector.
    assert smoke.find_secret_leak_offsets(combined, [secret, key_id]) == ()
    # The operator still learns WHAT failed.
    assert "_CanaryBoom" in combined


def test_unexpected_failure_in_evidence_write_is_contained(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`write_evidence` sits outside the old guard too, and holds the secrets."""
    secret, key_id = make_leak_safe_secret_pair()
    monkeypatch.setattr(smoke, "prepare", lambda *a, **k: _prepared_with(secret, key_id))

    async def _ok(*_args: Any, **_kwargs: Any) -> Any:
        return make_report(key_id=key_id, signature="c2ln" + "A" * 60)

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError(f"read-only filesystem while holding {secret}")

    monkeypatch.setattr(smoke, "run_smoke", _ok)
    monkeypatch.setattr(smoke, "write_evidence", _boom)

    exit_code = smoke.main([])

    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert exit_code != 0
    assert "Traceback (most recent call last)" not in combined
    assert smoke.find_secret_leak_offsets(combined, [secret, key_id]) == ()
    assert "OSError" in combined


def test_main_writes_latest_checkpoint_when_asyncio_run_fails_after_probes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A known Nautilus teardown loop-stop must not erase a proven PASS."""
    secret, key_id = make_leak_safe_secret_pair()
    monkeypatch.setattr(smoke, "prepare", lambda *a, **k: _prepared_with(secret, key_id))

    async def _checkpoint_then_boom(*_args: Any, **kwargs: Any) -> Any:
        checkpoint = kwargs["checkpoint"]
        checkpoint.write(make_report(key_id=key_id, signature="c2ln" + "A" * 60))
        raise RuntimeError("Event loop stopped before Future completed.")

    monkeypatch.setattr(smoke, "run_smoke", _checkpoint_then_boom)

    exit_code = smoke.main(["--evidence-dir", str(tmp_path)])

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    files = list(tmp_path.glob("READONLY_AUTH_SMOKE_*.md"))
    assert exit_code == 4
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "Connectivity verdict: PASS" in text
    assert "Teardown health: KNOWN_BENIGN_NAUTILUS_LOOP_STOP" in text
    assert "RuntimeError" in text
    assert "Event loop stopped before Future completed" in text
    assert "KNOWN_BENIGN_NAUTILUS_LOOP_STOP" in combined
    assert "Traceback (most recent call last)" not in combined
    assert smoke.find_secret_leak_offsets(text + combined, [secret, key_id]) == ()


def test_asyncio_loop_exception_handler_records_scrubbed_context_without_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The asyncio callback exception path bypasses sys.excepthook."""
    secret = LEAK_SAFE_SECRET
    counter = smoke._QuoteCounter([SLUG])
    loop = asyncio.new_event_loop()
    try:
        handler = smoke.build_safe_loop_exception_handler(counter, [secret])
        handler(
            loop,
            {
                "message": f"callback failed while holding {secret}",
                "exception": _CanaryBoom(f"signed header contained {secret}"),
            },
        )
    finally:
        loop.close()

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert combined == ""
    assert any("asyncio loop exception" in line for line in counter.log)
    assert any("_CanaryBoom" in line for line in counter.log)
    assert smoke.find_secret_leak_offsets("\n".join(counter.log), [secret]) == ()


def test_keyboard_interrupt_is_not_swallowed_as_a_crash(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Operator Ctrl-C must stay distinguishable from a defect, and stay quiet."""
    secret, key_id = make_leak_safe_secret_pair()
    monkeypatch.setattr(smoke, "prepare", lambda *a, **k: _prepared_with(secret, key_id))

    async def _interrupt(*_args: Any, **_kwargs: Any) -> Any:
        raise KeyboardInterrupt

    monkeypatch.setattr(smoke, "run_smoke", _interrupt)

    exit_code = smoke.main([])

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert exit_code != 0
    assert "Traceback (most recent call last)" not in combined


def test_process_excepthook_is_replaced_and_prints_no_message_or_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Belt-and-braces: nothing escaping main() may reach the default hook.

    Once a credential read has begun the replacement hook prints the exception
    TYPE only -- it cannot know which secrets to scrub, and a hook whose safety
    depends on a list it may not have is not a guard. This assertion is
    unchanged from before the guard existed; it is merely stated in the state
    where the claim is actually true. The pre-credential state is covered
    separately below.
    """
    guard = smoke.CredentialGuard()
    guard.mark_credential_read_begun()
    hook = smoke.build_safe_excepthook(guard)

    hook(_CanaryBoom, _CanaryBoom("secret-material-DO-NOT-PRINT"), None)

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "_CanaryBoom" in combined
    assert "secret-material-DO-NOT-PRINT" not in combined
    assert "Traceback" not in combined


def test_main_installs_the_safe_excepthook_before_reading_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Ordering matters: the hook must be live before `prepare()` is called."""
    observed: list[Any] = []

    def _record_then_refuse(*_args: Any, **_kwargs: Any) -> Any:
        observed.append(sys.excepthook)
        raise smoke.SmokeRefusal("not enabled")

    monkeypatch.setattr(smoke, "prepare", _record_then_refuse)
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)

    smoke.main([])
    capsys.readouterr()

    assert observed, "prepare() was never called"
    assert observed[0] is not sys.__excepthook__, (
        "the default excepthook was still installed when credentials were read"
    )


# ---------------------------------------------------------------------------
# Evidence file permissions (SEC finding 4, 2026-08-25)
# ---------------------------------------------------------------------------
#
# The artefact is redacted, but "redacted" is a property of the CURRENT
# renderer. It is written on an operator workstation whose umask is unknown,
# and a world-readable 0644 artefact on a shared or backed-up host widens the
# blast radius of any future rendering defect for free. 0600 costs nothing.


def _write_evidence_to(tmp_path: Path, key_id: str, secret: str) -> Path:
    report = make_report(key_id=key_id, signature="c2ln" + "A" * 60)
    # `smoke` is loaded via importlib, so mypy sees its members as Any.
    written: Any = smoke.write_evidence(
        report,
        secrets=[secret, key_id],
        directory=tmp_path / "nested" / "evidence",
    )
    assert isinstance(written, Path)
    return written


def test_evidence_file_and_sidecar_are_owner_read_write_only(tmp_path: Path) -> None:
    secret, key_id = make_leak_safe_secret_pair()

    with permissive_umask():
        path = _write_evidence_to(tmp_path, key_id, secret)
    sidecar = path.with_suffix(path.suffix + ".sha256")

    assert path.stat().st_mode & 0o777 == 0o600, "evidence artefact must be 0600"
    assert sidecar.stat().st_mode & 0o777 == 0o600, "digest sidecar must be 0600"


def test_evidence_directory_is_created_owner_only(tmp_path: Path) -> None:
    """A permissive parent directory undoes a restrictive file."""
    secret, key_id = make_leak_safe_secret_pair()

    path = _write_evidence_to(tmp_path, key_id, secret)

    assert path.parent.stat().st_mode & 0o777 == 0o700, "evidence directory must be 0700"


def test_a_permissive_preexisting_directory_is_tightened(tmp_path: Path) -> None:
    """`mkdir(exist_ok=True)` silently accepts whatever mode is already there."""
    directory = tmp_path / "nested" / "evidence"
    directory.mkdir(parents=True)
    directory.chmod(0o777)
    secret, key_id = make_leak_safe_secret_pair()

    _write_evidence_to(tmp_path, key_id, secret)

    assert directory.stat().st_mode & 0o777 == 0o700


# ---------------------------------------------------------------------------
# Node-task failures must be observed, not suppressed (SEC finding 2b)
# ---------------------------------------------------------------------------
#
# `node.run_async()` was fire-and-forget, and shutdown ran three back-to-back
# `contextlib.suppress(Exception)` blocks. A genuine startup or auth failure on
# the operator's FIRST live run therefore produced no diagnostic at all: the
# operator saw `quotes_delivered == 0` and a generic FAIL, which is also
# exactly what "the market is quiet" looks like. Those three outcomes -- auth
# failed / node never started / no quotes arrived -- must be distinguishable.


def test_describe_exception_gives_the_type_and_a_scrubbed_message() -> None:
    secret, key_id = make_leak_safe_secret_pair()

    described = smoke.describe_exception(
        RuntimeError(f"handshake rejected for {key_id} signed with {secret}"),
        [secret, key_id],
    )

    assert described.startswith("RuntimeError: ")
    assert smoke.find_secret_leak_offsets(described, [secret, key_id]) == ()
    assert "handshake rejected" in described, "the diagnostic must survive scrubbing"


def test_describe_exception_withholds_a_message_it_cannot_scrub() -> None:
    """Fail closed, but never lose the type -- that is the load-bearing part."""
    secret = LEAK_SAFE_SECRET

    described = smoke.describe_exception(_CanaryBoom(secret[:8]), [secret])

    assert described.startswith("_CanaryBoom")
    assert smoke.find_secret_leak_offsets(described, [secret]) == ()


@pytest.mark.asyncio
async def test_a_failed_node_task_is_captured_and_reported() -> None:
    secret = LEAK_SAFE_SECRET
    counter = smoke._QuoteCounter(["slug-a"])

    async def _explode() -> None:
        raise _CanaryBoom(f"node.build() blew up holding {secret}")

    task = asyncio.ensure_future(_explode())

    failure = await smoke.drain_node_task(task, counter, [secret])

    assert failure is not None
    assert "_CanaryBoom" in failure
    assert smoke.find_secret_leak_offsets(failure, [secret]) == ()
    assert any("_CanaryBoom" in line for line in counter.log), (
        "the failure must reach the evidence log excerpt, not just the return value"
    )


@pytest.mark.asyncio
async def test_a_healthy_node_task_reports_no_failure() -> None:
    counter = smoke._QuoteCounter(["slug-a"])

    async def _sleep_forever() -> None:
        await asyncio.sleep(3600)

    task = asyncio.ensure_future(_sleep_forever())
    await asyncio.sleep(0)

    assert await smoke.drain_node_task(task, counter, []) is None


@pytest.mark.asyncio
async def test_cancelling_a_healthy_node_task_is_not_reported_as_a_failure() -> None:
    """Cancellation is how the window ends normally; it is not a defect."""
    counter = smoke._QuoteCounter(["slug-a"])

    async def _sleep_forever() -> None:
        await asyncio.sleep(3600)

    task = asyncio.ensure_future(_sleep_forever())
    await asyncio.sleep(0)
    task.cancel()

    assert await smoke.drain_node_task(task, counter, []) is None


def test_the_verdict_distinguishes_a_dead_node_from_a_quiet_market() -> None:
    """The three first-run outcomes must not collapse into one FAIL string."""
    dead = smoke.verdict_reason_for(
        authenticated_ok=True, quotes_delivered=0, node_failure="_CanaryBoom: build failed"
    )
    quiet = smoke.verdict_reason_for(authenticated_ok=True, quotes_delivered=0, node_failure=None)
    unauthenticated = smoke.verdict_reason_for(
        authenticated_ok=False, quotes_delivered=0, node_failure=None
    )

    assert "_CanaryBoom" in dead
    assert dead != quiet != unauthenticated
    assert len({dead, quiet, unauthenticated}) == 3


def test_clock_skew_guard_accepts_a_safe_fraction_of_the_documented_window() -> None:
    records = (
        smoke.RequestRecord(
            step="A",
            label="public market read",
            path="/v1/market/slug/example",
            query_string="",
            status=200,
            latency_ms=1.0,
            sent_headers={},
            observed_headers={"date": "Tue, 25 Aug 2026 12:00:00 GMT"},
            note="accepted",
        ),
    )

    smoke.assert_host_clock_safe_for_signing(
        records,
        now_ms=int(dt.datetime(2026, 8, 25, 12, 0, 14, 999000, tzinfo=dt.UTC).timestamp() * 1000),
    )


def test_clock_skew_guard_refuses_before_signing_when_offset_is_too_large() -> None:
    records = (
        smoke.RequestRecord(
            step="A",
            label="public market read",
            path="/v1/market/slug/example",
            query_string="",
            status=200,
            latency_ms=1.0,
            sent_headers={},
            observed_headers={"date": "Tue, 25 Aug 2026 12:00:00 GMT"},
            note="accepted",
        ),
    )

    with pytest.raises(smoke.SignatureClockSkewError) as excinfo:
        smoke.assert_host_clock_safe_for_signing(
            records,
            now_ms=int(
                dt.datetime(2026, 8, 25, 12, 0, 15, 1_000, tzinfo=dt.UTC).timestamp() * 1000
            ),
        )

    message = str(excinfo.value)
    assert "15001" in message
    assert "15000" in message
    assert "30000" in message
    assert "Date header" in message


def test_clock_skew_guard_refuses_when_no_venue_date_header_was_measured() -> None:
    records = (
        smoke.RequestRecord(
            step="A",
            label="public market read",
            path="/v1/market/slug/example",
            query_string="",
            status=200,
            latency_ms=1.0,
            sent_headers={},
            observed_headers={},
            note="accepted",
        ),
    )

    with pytest.raises(smoke.SignatureClockSkewError, match="Date header"):
        smoke.assert_host_clock_safe_for_signing(records, now_ms=0)


# ---------------------------------------------------------------------------
# The excepthook's suppression must be state-aware, and its stated reason true
# ---------------------------------------------------------------------------
#
# Observed 2026-08-25 with only `BREEZY_VENUE_LIVE=1` set:
#
#     FATAL (uncaught): SettingsError. Message and traceback are suppressed
#     because this process holds an Ed25519 secret in memory.
#
# That reason was FALSE at that moment. `prepare()` runs `disable_core_dumps`
# -> `assert_smoke_enabled` -> `config_from_env` -> `load_polymarket_us_
# credentials`; the `SettingsError` came from `config_from_env`, i.e. strictly
# BEFORE any credential was read. The suppressed detail -- WHICH environment
# variable is unset -- contains no secret whatsoever and is precisely what the
# operator needs on a first run. Blanket suppression that misstates its own
# reason is worse than either alternative: it withholds safe information AND
# misinforms.
#
# The original design instinct is still sound and is preserved: the hook is
# installed before `prepare()` because at install time there is no secret list
# to scrub against. The fix is that the process can KNOW whether a credential
# read has begun, so the hook stops guessing.


def _capture_hook(guard: Any, exc: BaseException, capsys: pytest.CaptureFixture[str]) -> str:
    hook = smoke.build_safe_excepthook(guard)
    hook(type(exc), exc, None)
    captured = capsys.readouterr()
    return captured.out + captured.err


def test_a_fresh_credential_guard_reports_no_credential_read() -> None:
    assert smoke.CredentialGuard().credential_read_begun is False


def test_marking_the_guard_is_one_way() -> None:
    guard = smoke.CredentialGuard()
    guard.mark_credential_read_begun()
    guard.mark_credential_read_begun()
    assert guard.credential_read_begun is True


def test_excepthook_reports_the_message_before_any_credential_is_read(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The whole point: a config-stage failure must name the missing variable."""
    from breezy.runtime.settings import SettingsError

    exc = SettingsError(
        "Polymarket.us venue configuration is incomplete; every variable is "
        "required with no default. Unset or empty: POLYMARKET_US_API_BASE"
    )

    combined = _capture_hook(smoke.CredentialGuard(), exc, capsys)

    assert "SettingsError" in combined
    assert "POLYMARKET_US_API_BASE" in combined, (
        "the operator cannot diagnose a first run without the variable name"
    )
    assert "Traceback" not in combined


def test_excepthook_never_claims_a_secret_is_held_before_one_is_read(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Requirement 3: the stated reason must be true in BOTH states."""
    from breezy.runtime.settings import SettingsError

    combined = _capture_hook(
        smoke.CredentialGuard(), SettingsError("POLYMARKET_US_WS_URL is required"), capsys
    )

    assert "holds an Ed25519 secret in memory" not in combined
    assert "before any credential" in combined.lower()


def test_the_pre_credential_message_routes_through_the_redaction_seam(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Defence in depth: no secret should exist yet, but the seam is the seam.

    `describe_exception` is the single scrubbing seam (`redact_text` then a
    fragment re-check). If a future configuration value ever carries sensitive
    material, it must be scrubbed by construction rather than by argument.
    """
    calls: list[tuple[str, tuple[str, ...]]] = []
    original: Any = smoke.describe_exception

    def _spy(exc: BaseException, secrets: Any) -> str:
        calls.append((str(exc), tuple(secrets)))
        result: str = original(exc, secrets)
        return result

    monkeypatch.setattr(smoke, "describe_exception", _spy)

    _capture_hook(smoke.CredentialGuard(), RuntimeError("configuration is bad"), capsys)

    assert calls, "the pre-credential branch bypassed the redaction seam"
    assert calls[0][0] == "configuration is bad"


def test_excepthook_withholds_the_message_once_a_credential_read_has_begun(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Requirement 5: the post-credential behaviour must NOT be weakened."""
    guard = smoke.CredentialGuard()
    guard.mark_credential_read_begun()

    combined = _capture_hook(guard, _CanaryBoom("secret-material-DO-NOT-PRINT"), capsys)

    assert "_CanaryBoom" in combined
    assert "secret-material-DO-NOT-PRINT" not in combined
    assert "Traceback" not in combined


def test_excepthook_falls_back_to_the_type_when_the_message_cannot_render(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Fail closed: an exception whose `__str__` raises must not crash the hook."""

    class _Unrenderable(Exception):
        def __str__(self) -> str:
            raise ValueError("cannot render")

    combined = _capture_hook(smoke.CredentialGuard(), _Unrenderable(), capsys)

    assert "_Unrenderable" in combined
    assert "Traceback" not in combined


def test_prepare_arms_the_credential_guard_before_reading_the_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Armed BEFORE the read, never after: the read itself may raise."""
    guard = smoke.CredentialGuard()
    observed: list[bool] = []
    credentials = make_credentials(make_secret(), str(UUID4()))

    def fake_loader(
        secrets_ref: PolymarketUSSecretsRefConfig, **kwargs: Any
    ) -> PolymarketUSCredentials:
        observed.append(guard.credential_read_begun)
        return credentials

    monkeypatch.setattr(smoke, "load_polymarket_us_credentials", fake_loader)
    monkeypatch.setattr(smoke.resource, "setrlimit", lambda which, limits: None)
    monkeypatch.setattr(smoke.resource, "getrlimit", lambda which: (0, 0))

    smoke.prepare(make_env(), guard=guard)

    assert observed == [True], "the guard must be armed before the credential read"


def test_prepare_leaves_the_guard_disarmed_when_config_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reproduced defect, at the ordering level."""
    from breezy.runtime.settings import SettingsError

    guard = smoke.CredentialGuard()
    monkeypatch.setattr(smoke.resource, "setrlimit", lambda which, limits: None)
    monkeypatch.setattr(smoke.resource, "getrlimit", lambda which: (0, 0))

    env = make_env()
    # The endpoint triple became an OPTIONAL override in G-19 B1, so removing
    # it no longer fails config. `POLYMARKET_US_USER_AGENT` -- a contact
    # string, and the one remaining required input -- is what this ordering
    # test now removes to provoke the config failure.
    del env[USER_AGENT_ENV_VAR]

    with pytest.raises(SettingsError):
        smoke.prepare(env, guard=guard)

    assert guard.credential_read_begun is False


def test_main_arms_the_guard_the_hook_was_built_with(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One guard, not two: the hook must observe the guard `prepare` arms."""
    built: list[Any] = []
    original_build = smoke.build_safe_excepthook

    def _spy(guard: Any) -> Any:
        built.append(guard)
        return original_build(guard)

    monkeypatch.setattr(smoke, "build_safe_excepthook", _spy)
    monkeypatch.setattr(sys, "excepthook", sys.__excepthook__)

    def _record(env: Any = None, *, guard: Any = None) -> Any:
        assert guard is not None
        guard.mark_credential_read_begun()
        raise smoke.SmokeRefusal("not enabled")

    monkeypatch.setattr(smoke, "prepare", _record)

    smoke.main([])
    capsys.readouterr()

    assert built, "main() never built the safe excepthook"
    assert built[0].credential_read_begun is True, (
        "main() passed prepare() a different guard than the hook observes"
    )


# ---------------------------------------------------------------------------
# R-5R-3 -- the canonical-string probe takes its path from the caller
#
# OQ-M ("is the query string part of the signed canonical string?") is a hard
# precondition of R-4P-2: pagination is the first thing in Breezy that puts a
# query on a signed request, and choosing the wrong variant 401s every page
# after the first. The probe used to be pinned to the portfolio path, which the
# 2026-09-02 capture measured at 503 -- so the discriminator could not run at
# all while that one endpoint was unavailable. The path is a caller argument
# now, so the probe can be pointed at whichever private path is answering.
# ---------------------------------------------------------------------------


class _CannedInner:
    """A GET-only transport double answering from a per-URL script."""

    def __init__(self, statuses: Mapping[str, int], default: int = 200) -> None:
        self.statuses = statuses
        self.default = default
        self.urls: list[str] = []

    async def get(self, url: str, *, headers: Mapping[str, str], quota_key: str) -> Any:
        from breezy.adapters.polymarket_us.transport import VenueResponse

        self.urls.append(url)
        status = next(
            (code for fragment, code in self.statuses.items() if fragment in url),
            self.default,
        )
        return VenueResponse(status=status, headers={}, body=b"{}")


class _QuietLog:
    def debug(self, message: str) -> None: ...

    def info(self, message: str) -> None: ...

    def warning(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...


def _canonical_probe_client_factory(transport: Any) -> Any:
    from nautilus_trader.common.component import LiveClock

    from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
    from breezy.adapters.polymarket_us.signing import Ed25519RequestSigner

    credentials = make_credentials(make_secret(), LEAK_SAFE_KEY_ID)

    def build_client(variant: Any) -> Any:
        return PolymarketUSHttpClient(
            transport=transport,
            signer=Ed25519RequestSigner.for_variant(
                credentials, clock=LiveClock(), variant=variant
            ),
            api_base_url="https://api.example.invalid",
            gateway_base_url="https://gateway.example.invalid",
            logger=_QuietLog(),
        )

    return build_client


@pytest.mark.asyncio
async def test_the_canonical_string_probe_takes_its_path_as_a_caller_argument() -> None:
    """Both variant reads hit the path the CALLER named, not a module literal."""
    inner = _CannedInner({})
    transport = smoke.RecordingTransport(inner=inner)
    caller_path = "/v1/portfolio/activities"

    records, _finding = await smoke._probe_canonical_string(
        None, transport, _canonical_probe_client_factory(transport), path=caller_path
    )

    assert len(inner.urls) == 2
    assert all(url.startswith(f"https://api.example.invalid{caller_path}?") for url in inner.urls)
    assert [record.path for record in records] == [caller_path, caller_path]


@pytest.mark.asyncio
async def test_the_canonical_string_probe_still_defaults_to_the_portfolio_path() -> None:
    """The default is unchanged, so an existing invocation is not re-pointed."""
    inner = _CannedInner({})
    transport = smoke.RecordingTransport(inner=inner)

    records, _finding = await smoke._probe_canonical_string(
        None, transport, _canonical_probe_client_factory(transport)
    )

    assert [record.path for record in records] == [smoke.PORTFOLIO_PATH] * 2


@pytest.mark.parametrize(
    ("path_only", "path_with_query", "expected_fragment"),
    [
        (200, 401, "Path ONLY is signed"),
        (401, 200, "query string IS part of the canonical string"),
        (200, 200, "BOTH forms were accepted"),
        (503, 503, "Inconclusive"),
        (None, None, "Inconclusive"),
    ],
)
def test_the_canonical_string_outcome_has_exactly_four_coded_shapes(
    path_only: int | None, path_with_query: int | None, expected_fragment: str
) -> None:
    """The classifier is total: every status pair lands in one named shape."""
    answer = smoke.classify_canonical_string_outcome(
        path_only=path_only, path_with_query=path_with_query
    )
    assert expected_fragment in answer


def test_the_canonical_probe_path_is_a_cli_argument_defaulting_to_the_configured_path() -> None:
    """The re-point is an operator argument, never an edit to a source literal."""
    assert smoke._parse_args([]).canonical_probe_path == smoke.PORTFOLIO_PATH
    assert (
        smoke._parse_args(
            ["--canonical-probe-path", "/v1/portfolio/activities"]
        ).canonical_probe_path
        == "/v1/portfolio/activities"
    )
