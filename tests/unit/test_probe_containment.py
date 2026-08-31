"""Structural containment for the P2 read-only probes.

Authority: ``docs/plans/DATA_CAPTURE_AND_RISK_PLAN.md`` section 4.P2 and
finding R15.

Why this suite exists
---------------------
``docs/evidence/forecast_endpoint_probe_2026-08-29.md:27-39`` records a probe
that **over-spent its request budget** -- 23 requests against an approved ~20 --
because a hand-rolled ``curl`` silently followed redirects. The plan's verdict
(R15) is that a request counter bolted onto a raw HTTP client *reproduces the
defect class*: the counter counts what the caller meant to do, while the
redirect chain decides what actually went out.

So the containment here is **structural, and tested before anything runs**:

* the budget is consumed inside the transport, immediately before the single
  ``client.stream`` dispatch, so one authorised request is one socket exchange;
* redirects are not followed and cannot be, because the probe transport
  *inherits* :class:`breezy.ingest.http.HttpTransport` rather than
  reimplementing it, and overrides none of the four controls the plan cites by
  line (``http.py:622`` allowlist, ``:630`` ``follow_redirects=False``,
  ``:857`` 3xx-as-integrity-alarm, ``:930`` streaming body cap);
* no write verb is constructible, asserted by reusing the shipped read-only
  guard's own detectors rather than a second copy of them.

**Every test in this module runs against fixtures.** ``tests/conftest.py``
blocks real sockets for anything not marked ``live``/``allow_socket``, and
nothing here carries either marker, so a regression that tried to reach the
network would fail rather than spend a request.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import httpx
import pytest
import respx

from breezy.ingest.http import HttpTransport, RedirectError
from breezy.ingest.probe_transport import (
    PROBE_PAYLOAD_SUFFIX,
    SETTLEMENT_HOSTS,
    ProbeEvidenceWriter,
    ProbeTransport,
    RequestBudget,
    RequestBudgetExceededError,
    SettlementHostForbiddenError,
)
from tests.unit.test_polymarket_us_readonly_guard import (
    find_write_capable_receiver_exposures,
    find_write_egress_violations,
    is_venue_touching,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SRC_ROOT: Final[Path] = REPO_ROOT / "src" / "breezy"

PROBE_A_PATH: Final[Path] = REPO_ROOT / "scripts/venue/open_meteo_previous_runs_probe.py"
PROBE_B_PATH: Final[Path] = REPO_ROOT / "scripts/venue/iem_afos_forecast_pil_probe.py"
PROBE_PATHS: Final[tuple[Path, ...]] = (PROBE_A_PATH, PROBE_B_PATH)

PROBE_A_REL: Final[str] = "scripts/venue/open_meteo_previous_runs_probe.py"
PROBE_B_REL: Final[str] = "scripts/venue/iem_afos_forecast_pil_probe.py"

LIVE_TEST_PATHS: Final[tuple[Path, ...]] = (
    REPO_ROOT / "tests/live/test_open_meteo_previous_runs_probe_live.py",
    REPO_ROOT / "tests/live/test_iem_afos_forecast_pil_probe_live.py",
)

PROBE_UA: Final[str] = "breezy-probe (contact: ops@example.invalid)"


def _load_script(path: Path) -> ModuleType:
    """Import a ``scripts/`` module by path, as the auth-smoke suite does."""
    spec = importlib.util.spec_from_file_location(f"breezy_probe_{path.stem}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - import plumbing
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe_a = _load_script(PROBE_A_PATH)
probe_b = _load_script(PROBE_B_PATH)


def _clock() -> int:
    return 1_700_000_000_000_000_000


def _transport(
    *,
    budget: RequestBudget | None = None,
    base_url: str = "https://api.open-meteo.com",
    allowed_hosts: frozenset[str] = frozenset({"api.open-meteo.com"}),
    max_body_bytes: int = 4096,
) -> ProbeTransport:
    return ProbeTransport(
        base_url=base_url,
        allowed_hosts=allowed_hosts,
        budget=budget if budget is not None else RequestBudget(limit=8),
        max_body_bytes=max_body_bytes,
        user_agent=PROBE_UA,
        accept="application/json",
        clock=_clock,
    )


# ==========================================================================
# Requirement 1 -- a HARD request budget that raises on the (N+1)th request
# ==========================================================================


def test_request_budget_authorises_exactly_n_requests_then_raises() -> None:
    budget = RequestBudget(limit=3)
    assert [budget.consume() for _ in range(3)] == [1, 2, 3]
    assert budget.spent == 3
    assert budget.remaining == 0
    with pytest.raises(RequestBudgetExceededError):
        budget.consume()


def test_request_budget_stays_exhausted_after_the_first_refusal() -> None:
    """A refused request must not leave the counter recoverable or drifting."""
    budget = RequestBudget(limit=1)
    budget.consume()
    for _ in range(3):
        with pytest.raises(RequestBudgetExceededError):
            budget.consume()
    assert budget.spent == 1


def test_request_budget_rejects_a_non_positive_limit() -> None:
    with pytest.raises(ValueError):
        RequestBudget(limit=0)


@respx.mock
@pytest.mark.asyncio
async def test_transport_aborts_the_n_plus_first_request_before_the_socket_opens() -> None:
    """The (N+1)th ``probe_get`` raises and NO extra request reaches the wire."""
    route = respx.get(url__startswith="https://api.open-meteo.com/v1/probe").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    transport = _transport(budget=RequestBudget(limit=2))

    await transport.probe_get("/v1/probe", label="one")
    await transport.probe_get("/v1/probe", label="two")
    assert route.call_count == 2

    with pytest.raises(RequestBudgetExceededError):
        await transport.probe_get("/v1/probe", label="three")

    # The whole point: the refusal happened BEFORE dispatch.
    assert route.call_count == 2


@respx.mock
@pytest.mark.asyncio
async def test_budget_charges_a_failed_exchange_too() -> None:
    """A 404/5xx/redirect still SPENT a request; the counter must say so."""
    respx.get(url__startswith="https://api.open-meteo.com/v1/probe").mock(
        return_value=httpx.Response(404, text="nope")
    )
    budget = RequestBudget(limit=5)
    transport = _transport(budget=budget)

    await transport.probe_get("/v1/probe", label="miss")

    assert budget.spent == 1


# ==========================================================================
# Requirement 2 -- redirects are not followed; a 3xx is recorded as a finding
# ==========================================================================


@respx.mock
@pytest.mark.asyncio
async def test_a_3xx_is_not_chased_and_is_recorded_as_a_finding() -> None:
    respx.get("https://api.open-meteo.com/v1/moved").mock(
        return_value=httpx.Response(302, headers={"location": "https://api.open-meteo.com/v1/here"})
    )
    followed = respx.get("https://api.open-meteo.com/v1/here").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    transport = _transport()

    exchange = await transport.probe_get("/v1/moved", label="moved")

    assert followed.call_count == 0, "a redirect was chased -- the 2026-08-29 defect class"
    assert exchange.status_code == 302
    assert exchange.outcome == "redirect_not_followed"
    assert exchange.finding is not None
    assert "redirect" in exchange.finding.lower()
    assert exchange.text is None


@pytest.mark.asyncio
async def test_the_underlying_transport_still_raises_redirect_error() -> None:
    """``probe_get`` records the finding; the inherited control still fires."""
    transport = _transport()
    with respx.mock:
        respx.get("https://api.open-meteo.com/v1/moved").mock(
            return_value=httpx.Response(307, headers={"location": "/elsewhere"})
        )
        with pytest.raises(RedirectError):
            await transport.probe_get_strict("/v1/moved")


def test_probe_transport_overrides_none_of_the_four_cited_controls() -> None:
    """R15's four controls are INHERITED, never reimplemented or forked."""
    for control in ("_validate_url", "_build_client", "_raise_for_status", "_read_capped_body"):
        assert control not in vars(ProbeTransport), (
            f"ProbeTransport overrides {control!r}; the plan's cited control "
            "must be inherited from HttpTransport, not forked"
        )
        assert getattr(ProbeTransport, control) is getattr(HttpTransport, control)


def test_probe_transport_is_a_subclass_of_the_hardened_transport() -> None:
    assert issubclass(ProbeTransport, HttpTransport)


@respx.mock
@pytest.mark.asyncio
async def test_the_client_the_probe_builds_does_not_follow_redirects() -> None:
    transport = _transport()
    client = transport._build_client()  # asserting the shipped control directly
    try:
        assert client.follow_redirects is False
        assert client.trust_env is False
    finally:
        await client.aclose()


# ==========================================================================
# Requirement 3 -- both probes classify as venue-touching under the guard,
# and the classifier is extended to cover ``scripts/probes/`` as well
# ==========================================================================


@pytest.mark.parametrize("rel", [PROBE_A_REL, PROBE_B_REL])
def test_both_probes_classify_as_venue_touching(rel: str) -> None:
    source = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert is_venue_touching(rel, ast.parse(source, filename=rel)) is True


def test_a_module_under_scripts_probes_would_also_classify_as_venue_touching() -> None:
    """R15 future-proofing: the path is covered before anything is put there."""
    tree = ast.parse("x = 1\n")
    assert is_venue_touching("scripts/probes/anything.py", tree) is True


def test_the_classifier_still_exempts_the_operator_webhook_module() -> None:
    """Widening the classifier must not start firing on `runtime/health.py`."""
    source = (SRC_ROOT / "runtime" / "health.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="src/breezy/runtime/health.py")
    assert is_venue_touching("src/breezy/runtime/health.py", tree) is False


# ==========================================================================
# Requirement 4 -- zero write requests; no write verb constructible
# ==========================================================================


@pytest.mark.parametrize("rel", [PROBE_A_REL, PROBE_B_REL])
def test_probe_modules_contain_no_write_egress_violation(rel: str) -> None:
    source = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert find_write_egress_violations(rel, source) == []


def test_probe_transport_exposes_no_write_capable_receiver() -> None:
    """No attribute path off a constructed probe transport reaches a write verb."""
    assert find_write_capable_receiver_exposures(_transport()) == []


def test_probe_transport_public_surface_is_get_only() -> None:
    public = {
        name
        for name in dir(ProbeTransport)
        if not name.startswith("_") and callable(getattr(ProbeTransport, name, None))
    }
    assert public == {
        "probe_get",
        "probe_get_strict",
        # Inherited from the settlement transport and CLOSED -- see
        # `test_the_settlement_fetch_methods_are_unreachable_from_a_probe`.
        "fetch_discovery_list",
        "fetch_product",
    }


@respx.mock
@pytest.mark.asyncio
async def test_every_dispatched_request_is_a_get() -> None:
    route = respx.get("https://api.open-meteo.com/v1/x").mock(
        return_value=httpx.Response(200, json={})
    )
    await _transport().probe_get("/v1/x", label="x")
    assert route.calls[0].request.method == "GET"


@pytest.mark.asyncio
async def test_the_settlement_fetch_methods_are_unreachable_from_a_probe() -> None:
    """The inherited NWS endpoint methods are closed, not merely discouraged."""
    transport = _transport()
    with pytest.raises(NotImplementedError):
        await transport.fetch_discovery_list("NYC")
    with pytest.raises(NotImplementedError):
        await transport.fetch_product("00000000-0000-0000-0000-000000000000")


# ==========================================================================
# Requirement 5 -- AST: no HTTP client but ``breezy.ingest.http`` is imported
# ==========================================================================

#: Anything that can open an outbound connection on its own.
_HTTP_CAPABLE_MODULES: Final[frozenset[str]] = frozenset(
    {
        "httpx",
        "requests",
        "urllib",
        "urllib2",
        "urllib3",
        "http",
        "aiohttp",
        "pycurl",
        "socket",
        "ssl",
        "websockets",
        "nautilus_trader",
        "polymarket_us",
        "ftplib",
        "telnetlib",
        "smtplib",
    }
)


def _imported_roots(tree: ast.AST) -> Iterator[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module, node.lineno


def find_foreign_http_client_imports(path: str, source: str) -> list[str]:
    """Report any import in ``path`` that can transport HTTP on its own.

    ``breezy.ingest.http`` (and the probe subclass that inherits from it) are
    the ONLY permitted transports -- that is the whole of R15's transport
    clause, made falsifiable.
    """
    tree = ast.parse(source, filename=path)
    found: list[str] = []
    for module, lineno in _imported_roots(tree):
        root = module.split(".")[0]
        if root in _HTTP_CAPABLE_MODULES:
            found.append(f"{path}:{lineno}: imports HTTP-capable module {module!r}")
    return found


@pytest.mark.parametrize("rel", [PROBE_A_REL, PROBE_B_REL])
def test_probes_import_no_http_client_other_than_breezy_ingest_http(rel: str) -> None:
    source = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert find_foreign_http_client_imports(rel, source) == []


@pytest.mark.parametrize("rel", [PROBE_A_REL, PROBE_B_REL])
def test_probes_do_bind_to_the_hardened_transport(rel: str) -> None:
    """The negative above is worthless without this positive."""
    source = (REPO_ROOT / rel).read_text(encoding="utf-8")
    modules = {module for module, _ in _imported_roots(ast.parse(source, filename=rel))}
    assert "breezy.ingest.probe_transport" in modules


def test_the_foreign_import_detector_is_not_vacuous() -> None:
    """Proof by construction: it fires on the exact bypass it exists to catch."""
    source = "import requests\n\ndef go():\n    return requests.get('https://x')\n"
    assert find_foreign_http_client_imports("scripts/venue/bad.py", source) != []


def _breezy_import_closure(rel: str) -> set[str]:
    """Every ``breezy.*`` module reachable by import from ``rel``."""
    seen: set[str] = set()
    frontier = [
        module
        for module, _ in _imported_roots(ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8")))
        if module.startswith("breezy.")
    ]
    while frontier:
        module = frontier.pop()
        if module in seen:
            continue
        seen.add(module)
        source_path = SRC_ROOT.parent / Path(module.replace(".", "/") + ".py")
        if not source_path.is_file():
            continue
        frontier.extend(
            child
            for child, _ in _imported_roots(ast.parse(source_path.read_text(encoding="utf-8")))
            if child.startswith("breezy.")
        )
    return seen


@pytest.mark.parametrize("rel", [PROBE_A_REL, PROBE_B_REL])
def test_exactly_one_module_in_the_probe_import_closure_speaks_httpx(rel: str) -> None:
    """The probe cannot inherit a second, softer transport through a dependency.

    Scoped to the CLOSURE rather than all of ``src/``: ``runtime/health.py``
    legitimately holds an ``httpx.Client`` for the operator alert webhook, and
    banning it repo-wide would be a barrier that has to be silenced. What
    matters is that no such client is reachable from a probe.
    """
    speakers = sorted(
        module
        for module in _breezy_import_closure(rel)
        if (SRC_ROOT.parent / Path(module.replace(".", "/") + ".py")).is_file()
        and "httpx"
        in {
            m.split(".")[0]
            for m, _ in _imported_roots(
                ast.parse(
                    (SRC_ROOT.parent / Path(module.replace(".", "/") + ".py")).read_text(
                        encoding="utf-8"
                    )
                )
            )
        }
    )
    assert speakers == ["breezy.ingest.http"]


# ==========================================================================
# Requirement 6 -- repo-wide: no module under ``src/`` READS docs/evidence/
# ==========================================================================


def _docstring_constants(tree: ast.Module) -> set[int]:
    """Ids of every ``ast.Constant`` node that is a docstring."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def find_evidence_path_reads(path: str, source: str) -> list[str]:
    """Report any *executable* reference to ``docs/evidence`` in ``path``.

    ``docs/evidence/`` is the EVIDENCE ONLY -- NEVER INGEST boundary. Until
    now it was a comment in a Markdown header; this makes it a test.

    Docstrings and comments are exempt on purpose, and that exemption is
    load-bearing rather than a loophole: several shipped modules legitimately
    *cite* the evidence capture their parsing rules were derived from
    (``adapters/polymarket_us/series.py``, ``symbology.py``). Citing a
    provenance document is not ingesting it. What is banned is the path
    reaching runtime -- a string constant that can be opened, globbed or
    joined.
    """
    tree = ast.parse(source, filename=path)
    exempt = _docstring_constants(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "docs/evidence" in node.value
            and id(node) not in exempt
        ):
            found.append(f"{path}:{node.lineno}: runtime reference to {node.value!r}")
    return found


def test_no_module_under_src_reads_docs_evidence() -> None:
    offenders: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT).as_posix()
        offenders.extend(find_evidence_path_reads(rel, path.read_text(encoding="utf-8")))
    assert offenders == [], (
        "docs/evidence is EVIDENCE ONLY -- NEVER INGEST. A src/ module now "
        "carries the path as a runtime value:\n" + "\n".join(offenders)
    )


def test_the_evidence_boundary_detector_is_not_vacuous() -> None:
    source = (
        '"""A module that cites docs/evidence/x.md in prose -- allowed."""\n'
        "from pathlib import Path\n"
        "P = Path('docs/evidence/x.md')\n"
    )
    found = find_evidence_path_reads("src/breezy/bad.py", source)
    assert len(found) == 1
    assert "docs/evidence/x.md" in found[0]


def test_the_evidence_boundary_detector_permits_a_prose_citation() -> None:
    source = '"""Derived from docs/evidence/venue/x.md."""\nX = 1\n'
    assert find_evidence_path_reads("src/breezy/ok.py", source) == []


# ==========================================================================
# Requirement 7 -- both probes are ``live``/``venue_live`` marked and are
# DESELECTED by default
# ==========================================================================


def test_pyproject_addopts_deselect_the_probe_markers() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "-m 'not live and not venue_live and not real_money'" in pyproject


@pytest.mark.parametrize("path", LIVE_TEST_PATHS, ids=lambda p: p.name)
def test_each_probe_live_module_declares_the_markers(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    assert "pytestmark" in source
    assert "pytest.mark.live" in source
    assert "pytest.mark.venue_live" in source


def test_the_probe_live_modules_collect_to_zero_under_default_addopts() -> None:
    """Not "they carry a marker" -- that the DEFAULT run selects none of them."""
    result = subprocess.run(
        [
            str(REPO_ROOT / ".venv" / "bin" / "python"),
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            *[str(p) for p in LIVE_TEST_PATHS],
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    # 5 is pytest's EXIT_NOTESTSCOLLECTED. Asserting the exit CODE rather than
    # grepping the summary line means a future pytest rewording cannot silently
    # turn this barrier green while the probes become default-selected.
    assert result.returncode == 5, output
    assert "::test_" not in output, output


@pytest.mark.parametrize("path", PROBE_PATHS, ids=lambda p: p.name)
def test_the_probe_cli_refuses_to_run_without_its_explicit_live_unlock(
    path: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _load_script(path)
    monkeypatch.delenv("BREEZY_LIVE", raising=False)
    exit_code = module.main(["--output-directory", str(tmp_path)])
    assert exit_code != 0


# ==========================================================================
# Requirement 8 -- ``.probe.json`` payloads; a ``request_manifest.tsv``
# ==========================================================================


def test_the_payload_suffix_is_the_one_no_production_loader_reads() -> None:
    assert PROBE_PAYLOAD_SUFFIX == ".probe.json"


def test_no_module_under_src_reads_the_probe_payload_suffix() -> None:
    namers = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in sorted(SRC_ROOT.rglob("*.py"))
        if PROBE_PAYLOAD_SUFFIX in path.read_text(encoding="utf-8")
    ]
    assert namers == ["src/breezy/ingest/probe_transport.py"]


def test_the_probe_evidence_module_contains_no_read_call_at_all() -> None:
    """The writer can WRITE a payload and can never read one back."""
    source = (SRC_ROOT / "ingest" / "probe_transport.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    banned = {"read_text", "read_bytes", "glob", "rglob", "iterdir", "listdir", "load", "loads"}
    offenders = [
        f"{node.lineno}: .{node.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in banned
    ]
    offenders += [
        f"{node.lineno}: open()"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open"
    ]
    assert offenders == []


@respx.mock
@pytest.mark.asyncio
async def test_the_writer_records_one_manifest_row_per_request(tmp_path: Path) -> None:
    respx.get("https://api.open-meteo.com/v1/a").mock(
        return_value=httpx.Response(
            200, json={"a": 1}, headers={"content-type": "application/json"}
        )
    )
    respx.get("https://api.open-meteo.com/v1/b").mock(
        return_value=httpx.Response(404, text="gone", headers={"content-type": "text/plain"})
    )
    transport = _transport()
    writer = ProbeEvidenceWriter(tmp_path)

    writer.record("alpha", await transport.probe_get("/v1/a", label="alpha"))
    writer.record("beta", await transport.probe_get("/v1/b", label="beta"))

    rows = (tmp_path / "request_manifest.tsv").read_text(encoding="utf-8").splitlines()
    assert rows[0].split("\t") == [
        "ordinal",
        "requested_at_utc",
        "label",
        "url",
        "status",
        "bytes",
        "content_type",
        "outcome",
        "sha256",
    ]
    assert len(rows) == 3, "the manifest must record the failed exchange too"
    assert rows[1].split("\t")[3] == "https://api.open-meteo.com/v1/a"
    assert rows[1].split("\t")[4] == "200"
    assert rows[1].split("\t")[6] == "application/json"
    assert rows[2].split("\t")[4] == "404"


@respx.mock
@pytest.mark.asyncio
async def test_payloads_are_written_with_the_probe_json_suffix(tmp_path: Path) -> None:
    respx.get("https://api.open-meteo.com/v1/a").mock(
        return_value=httpx.Response(200, json={"a": 1})
    )
    writer = ProbeEvidenceWriter(tmp_path)
    writer.record("alpha", await _transport().probe_get("/v1/a", label="alpha"))

    payload_files = sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".json")
    assert payload_files == ["alpha.probe.json"], (
        "a captured payload must carry the suffix no production loader reads"
    )
    payload = json.loads((tmp_path / "alpha.probe.json").read_text(encoding="utf-8"))
    assert json.loads(payload["body"]) == {"a": 1}
    assert payload["status"] == 200
    assert payload["url"] == "https://api.open-meteo.com/v1/a"


def test_the_evidence_directory_carries_the_never_ingest_header(tmp_path: Path) -> None:
    ProbeEvidenceWriter(tmp_path)
    header = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "EVIDENCE ONLY" in header
    assert "NEVER INGEST" in header


# ==========================================================================
# Transport containment that is specific to this repo's blast radius
# ==========================================================================


def test_a_probe_transport_can_never_be_pointed_at_the_settlement_host() -> None:
    """Out of scope by construction: zero UA-trap exposure on api.weather.gov."""
    for host in sorted(SETTLEMENT_HOSTS):
        with pytest.raises(SettlementHostForbiddenError):
            ProbeTransport(
                base_url=f"https://{host}",
                allowed_hosts=frozenset({host}),
                budget=RequestBudget(limit=1),
                max_body_bytes=1024,
                user_agent=PROBE_UA,
                accept="application/json",
                clock=_clock,
            )


def test_the_probe_transport_requires_an_explicit_per_instance_body_cap() -> None:
    """Plan section 1.2 item 10: no global ``max_body_bytes`` lever, ever."""
    signature = ProbeTransport.__init__.__annotations__
    assert "max_body_bytes" in signature
    with pytest.raises(TypeError):
        ProbeTransport(  # type: ignore[call-arg]
            base_url="https://api.open-meteo.com",
            allowed_hosts=frozenset({"api.open-meteo.com"}),
            budget=RequestBudget(limit=1),
            user_agent=PROBE_UA,
            accept="application/json",
            clock=_clock,
        )


def test_the_shipped_settlement_allowlist_is_untouched() -> None:
    from breezy.ingest.shared_state import DEFAULT_ALLOWED_HOSTS

    assert DEFAULT_ALLOWED_HOSTS == frozenset({"api.weather.gov"})


def test_the_settlement_transport_default_accept_header_is_unchanged() -> None:
    """The probe's ``accept`` seam must not have moved the NWS default."""
    from breezy.ingest.http import DEFAULT_ACCEPT

    assert DEFAULT_ACCEPT == "application/ld+json"


@respx.mock
@pytest.mark.asyncio
async def test_the_body_cap_is_enforced_per_instance_during_streaming() -> None:
    from breezy.ingest.http import OversizeBodyError

    respx.get("https://api.open-meteo.com/v1/big").mock(
        return_value=httpx.Response(200, text="x" * 5000)
    )
    transport = _transport(max_body_bytes=1024)
    with pytest.raises(OversizeBodyError):
        await transport.probe_get_strict("/v1/big")


@pytest.mark.parametrize(
    "path",
    [
        "https://evil.example/x",
        "//evil.example/x",
        "/v1/../../etc/passwd",
        "v1/no-leading-slash",
        "/v1/with\nnewline",
    ],
)
@pytest.mark.asyncio
async def test_a_probe_path_that_could_retarget_the_request_is_refused(path: str) -> None:
    with pytest.raises(ValueError):
        await _transport().probe_get(path, label="bad")


@pytest.mark.asyncio
async def test_a_query_value_carrying_header_injection_is_refused() -> None:
    with pytest.raises(ValueError):
        await _transport().probe_get("/v1/x", query={"k": "a\r\nX-Evil: 1"}, label="bad")


@respx.mock
@pytest.mark.asyncio
async def test_an_off_allowlist_host_is_refused_before_the_socket_opens() -> None:
    from breezy.ingest.http import DisallowedHostError

    budget = RequestBudget(limit=3)
    transport = _transport(budget=budget, base_url="https://api.open-meteo.com")
    # A base_url whose host is not allowlisted must fail on the finished URL.
    rogue = ProbeTransport(
        base_url="https://evil.example",
        allowed_hosts=frozenset({"api.open-meteo.com"}),
        budget=budget,
        max_body_bytes=1024,
        user_agent=PROBE_UA,
        accept="application/json",
        clock=_clock,
    )
    with pytest.raises(DisallowedHostError):
        await rogue.probe_get_strict("/v1/x")
    assert transport is not None


# ==========================================================================
# Probe B -- the pre-registered PASS bar, as a COMPUTED verdict
# ==========================================================================


def _sample(
    *,
    products: int,
    sites: int,
    parsed: int,
    issuance: int,
    zoned: int,
) -> Any:
    return probe_b.ParseCensus(
        products=products,
        sites=sites,
        highs_extracted=parsed,
        issuance_recoverable=issuance,
        zone_attributable=zoned,
    )


def test_probe_b_passes_only_when_every_pre_registered_clause_holds() -> None:
    verdict = probe_b.evaluate_verdict(
        _sample(products=50, sites=2, parsed=45, issuance=50, zoned=50)
    )
    assert verdict.passed is True
    assert verdict.failures == ()


@pytest.mark.parametrize(
    ("census", "expected_failure"),
    [
        ({"products": 49, "sites": 2, "parsed": 49, "issuance": 49, "zoned": 49}, "products"),
        ({"products": 60, "sites": 1, "parsed": 60, "issuance": 60, "zoned": 60}, "sites"),
        ({"products": 60, "sites": 2, "parsed": 53, "issuance": 60, "zoned": 60}, "parse_rate"),
        ({"products": 60, "sites": 2, "parsed": 60, "issuance": 59, "zoned": 60}, "issuance_time"),
        (
            {"products": 60, "sites": 2, "parsed": 60, "issuance": 60, "zoned": 59},
            "zone_attribution",
        ),
    ],
)
def test_probe_b_fails_when_any_single_clause_fails(
    census: dict[str, int], expected_failure: str
) -> None:
    verdict = probe_b.evaluate_verdict(_sample(**census))
    assert verdict.passed is False
    assert any(expected_failure in failure for failure in verdict.failures), verdict.failures


def test_probe_b_parse_rate_bar_is_exactly_ninety_percent() -> None:
    """89.9% fails, 90.0% passes -- the bar is computed, not judged."""
    assert (
        probe_b.evaluate_verdict(
            _sample(products=1000, sites=2, parsed=899, issuance=1000, zoned=1000)
        ).passed
        is False
    )
    assert (
        probe_b.evaluate_verdict(
            _sample(products=1000, sites=2, parsed=900, issuance=1000, zoned=1000)
        ).passed
        is True
    )


def test_probe_b_reports_the_parse_rate_it_measured() -> None:
    verdict = probe_b.evaluate_verdict(
        _sample(products=100, sites=2, parsed=72, issuance=100, zoned=100)
    )
    assert verdict.parse_rate == pytest.approx(0.72)


def test_probe_b_verdict_on_zero_products_is_a_fail_not_a_divide_by_zero() -> None:
    verdict = probe_b.evaluate_verdict(_sample(products=0, sites=0, parsed=0, issuance=0, zoned=0))
    assert verdict.passed is False
    assert verdict.parse_rate == 0.0


def test_probe_b_pass_bar_constants_match_the_pre_registration() -> None:
    assert probe_b.MIN_PRODUCTS == 50
    assert probe_b.MIN_SITES == 2
    assert probe_b.MIN_PARSE_RATE == 0.90


# ==========================================================================
# Probe A -- the nine questions are each covered by a labelled request
# ==========================================================================


def test_probe_a_request_plan_covers_every_pre_registered_question() -> None:
    plan = probe_a.build_request_plan()
    covered = {question for step in plan for question in step.questions}
    assert covered == set(probe_a.QUESTIONS)


def test_probe_a_request_plan_fits_inside_its_hard_budget() -> None:
    assert len(probe_a.build_request_plan()) <= probe_a.REQUEST_BUDGET


def test_probe_a_targets_only_its_own_host() -> None:
    assert probe_a.ALLOWED_HOSTS == frozenset({"api.open-meteo.com"})
    for step in probe_a.build_request_plan():
        assert step.path.startswith("/v1/")


def test_probe_b_targets_only_its_own_host() -> None:
    assert probe_b.ALLOWED_HOSTS == frozenset({"mesonet.agron.iastate.edu"})


@pytest.mark.parametrize("module", [probe_a, probe_b], ids=["open_meteo", "iem_afos"])
def test_neither_probe_names_the_settlement_host(module: ModuleType) -> None:
    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    assert "api.weather.gov" not in source
    assert "weather.gov" not in source
