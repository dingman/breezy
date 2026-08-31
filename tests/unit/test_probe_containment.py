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
    MANIFEST_COLUMNS,
    PROBE_PAYLOAD_SUFFIX,
    SETTLEMENT_HOSTS,
    ProbeEvidenceWriter,
    ProbeExchange,
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
PROBE_C_PATH: Final[Path] = REPO_ROOT / "scripts/venue/open_meteo_coverage_bisect_probe.py"
PROBE_PATHS: Final[tuple[Path, ...]] = (PROBE_A_PATH, PROBE_B_PATH, PROBE_C_PATH)

PROBE_A_REL: Final[str] = "scripts/venue/open_meteo_previous_runs_probe.py"
PROBE_B_REL: Final[str] = "scripts/venue/iem_afos_forecast_pil_probe.py"
PROBE_C_REL: Final[str] = "scripts/venue/open_meteo_coverage_bisect_probe.py"

LIVE_TEST_PATHS: Final[tuple[Path, ...]] = (
    REPO_ROOT / "tests/live/test_open_meteo_previous_runs_probe_live.py",
    REPO_ROOT / "tests/live/test_iem_afos_forecast_pil_probe_live.py",
)

PROBE_UA: Final[str] = "breezy-probe (contact: ops@example.invalid)"

#: Derived, never restated: the manifest column a non-2xx must not call ``ok``.
MANIFEST_OUTCOME_COLUMN: Final[int] = MANIFEST_COLUMNS.index("outcome")


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
probe_c = _load_script(PROBE_C_PATH)


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


@pytest.mark.parametrize("rel", [PROBE_A_REL, PROBE_B_REL, PROBE_C_REL])
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


@pytest.mark.parametrize("rel", [PROBE_A_REL, PROBE_B_REL, PROBE_C_REL])
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


@pytest.mark.parametrize("rel", [PROBE_A_REL, PROBE_B_REL, PROBE_C_REL])
def test_probes_import_no_http_client_other_than_breezy_ingest_http(rel: str) -> None:
    source = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert find_foreign_http_client_imports(rel, source) == []


@pytest.mark.parametrize("rel", [PROBE_A_REL, PROBE_B_REL, PROBE_C_REL])
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


@pytest.mark.parametrize("rel", [PROBE_A_REL, PROBE_B_REL, PROBE_C_REL])
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
    """Coverage is over DISCOVERY + the main plan; a question may be served by either."""
    covered = {question for step in probe_a.build_request_plan() for question in step.questions}
    covered |= {question for step in probe_a.build_discovery_plan() for question in step.questions}
    assert covered == set(probe_a.QUESTIONS)


def test_probe_a_request_plan_fits_inside_its_hard_budget() -> None:
    """Discovery spends from the SAME budget, so the sum must fit -- not the plan alone."""
    total = probe_a.DISCOVERY_BUDGET + len(probe_a.build_request_plan())
    assert total <= probe_a.REQUEST_BUDGET


def test_probe_a_targets_only_open_meteo_hosts() -> None:
    assert probe_a.ALLOWED_HOSTS == frozenset(
        {"api.open-meteo.com", "previous-runs-api.open-meteo.com"}
    )
    for shape in probe_a.CANDIDATE_SHAPES:
        assert shape.host in probe_a.ALLOWED_HOSTS
    for step in probe_a.build_request_plan():
        assert step.path.startswith("/v1/")


def test_probe_a_does_not_widen_the_shipped_default_allowlist() -> None:
    """A second host is permitted PER PROBE; the shipped default must not move."""
    from breezy.ingest.shared_state import DEFAULT_ALLOWED_HOSTS

    assert SETTLEMENT_HOSTS <= DEFAULT_ALLOWED_HOSTS
    assert not (probe_a.ALLOWED_HOSTS & DEFAULT_ALLOWED_HOSTS)
    tree = ast.parse(PROBE_A_PATH.read_text(encoding="utf-8"))
    referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    referenced |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    referenced |= {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "DEFAULT_ALLOWED_HOSTS" not in referenced, (
        "the shipped default allowlist must be neither read nor widened by a probe"
    )


def test_probe_b_targets_only_its_own_host() -> None:
    assert probe_b.ALLOWED_HOSTS == frozenset({"mesonet.agron.iastate.edu"})


def test_probe_c_targets_only_the_previous_runs_host() -> None:
    """Probe C inherits Probe A's ESTABLISHED origin -- and nothing wider."""
    assert probe_c.ALLOWED_HOSTS == frozenset({"previous-runs-api.open-meteo.com"})
    assert probe_c.ALLOWED_HOSTS < probe_a.ALLOWED_HOSTS
    assert probe_c.PATH.startswith("/v1/")


def test_probe_c_phase_ceilings_fit_inside_its_hard_budget() -> None:
    """All three phases spend the SAME budget, so the sum must fit."""
    total = probe_c.MATRIX_BUDGET + probe_c.BISECT_BUDGET + probe_c.CONTIGUITY_BUDGET
    assert total <= probe_c.REQUEST_BUDGET
    assert probe_c.REQUEST_BUDGET == 16, "16 is the ceiling that was authorised for Probe C"


@pytest.mark.parametrize("module", [probe_a, probe_b, probe_c])
def test_no_probe_widens_the_shipped_default_allowlist(module: ModuleType) -> None:
    """A per-probe host is permitted; the shipped default must not move."""
    from breezy.ingest.shared_state import DEFAULT_ALLOWED_HOSTS

    assert SETTLEMENT_HOSTS <= DEFAULT_ALLOWED_HOSTS
    assert not (module.ALLOWED_HOSTS & DEFAULT_ALLOWED_HOSTS)
    tree = ast.parse(Path(module.__file__ or "").read_text(encoding="utf-8"))
    referenced = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    referenced |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    referenced |= {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "DEFAULT_ALLOWED_HOSTS" not in referenced, (
        "the shipped default allowlist must be neither read nor widened by a probe"
    )


@pytest.mark.parametrize(
    "module", [probe_a, probe_b, probe_c], ids=["open_meteo", "iem_afos", "coverage_bisect"]
)
def test_neither_probe_names_the_settlement_host(module: ModuleType) -> None:
    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    assert "api.weather.gov" not in source
    assert "weather.gov" not in source


# ==========================================================================
# Probe A -- Defect 1: a non-2xx is a FINDING, never an answer
#
# 2026-08-31T003816Z: every one of 22 live requests returned HTTP 404 and the
# report called each of them `ok`, marked all nine questions `answered` and
# said "Findings: None recorded." A reader could have concluded Branch H was
# viable from a run that carried no data at all. These tests pin the three
# properties that make that impossible, and the fourth that stops the run
# spending 21 further requests to re-learn the same 404.
# ==========================================================================


def _probe_exchange(
    *,
    label: str,
    status: int = 200,
    body: str | None = None,
    ordinal: int = 1,
    outcome: str | None = None,
    finding: str | None = None,
) -> ProbeExchange:
    ok = 200 <= status < 300
    return ProbeExchange(
        ordinal=ordinal,
        requested_at_utc="2026-08-31T00:00:00+00:00",
        label=label,
        url=f"https://api.open-meteo.com/v1/forecast?label={label}",
        status_code=status,
        body_bytes=len(body.encode("utf-8")) if body is not None else 0,
        content_type="application/json",
        outcome=outcome if outcome is not None else ("ok" if ok else f"http_{status}"),
        sha256="0" * 64 if body is not None else None,
        text=body,
        finding=finding if finding is not None else (None if ok else f"HTTP {status}"),
    )


def _previous_runs_body(
    *,
    times: tuple[str, ...] = ("2026-08-29",),
    max_index: int = 5,
    base: float = 30.0,
    surface: str = "daily",
) -> str:
    variable = "temperature_2m_max" if surface == "daily" else "temperature_2m"
    block: dict[str, Any] = {
        "time": list(times),
        variable: [base + offset for offset in range(len(times))],
    }
    for index in range(1, max_index + 1):
        block[f"{variable}_previous_day{index}"] = [
            base + offset - index for offset in range(len(times))
        ]
    return json.dumps({"latitude": 40.78, "longitude": -73.97, surface: block})


NOT_FOUND_BODY: Final[str] = '{"error":true,"reason":"Not Found"}'


def _by_question(outcomes: Any) -> dict[str, Any]:
    return {outcome.question: outcome for outcome in outcomes}


def _transport_factory(budget: RequestBudget) -> Any:
    def make(shape: Any) -> ProbeTransport:
        return ProbeTransport(
            base_url=shape.base_url,
            allowed_hosts=frozenset({shape.host}),
            budget=budget,
            max_body_bytes=4096,
            user_agent=PROBE_UA,
            accept="application/json",
            clock=_clock,
        )

    return make


# -- 1. classification at the transport ------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_a_non_2xx_is_recorded_as_a_finding_not_as_ok() -> None:
    respx.get("https://api.open-meteo.com/v1/missing").mock(
        return_value=httpx.Response(404, text=NOT_FOUND_BODY)
    )

    exchange = await _transport().probe_get("/v1/missing", label="missing")

    assert exchange.status_code == 404
    assert exchange.succeeded is False
    assert exchange.outcome != "ok", "a 404 reported as `ok` is the 2026-08-31 defect"
    assert "404" in exchange.outcome
    assert exchange.finding is not None
    assert "404" in exchange.finding


@respx.mock
@pytest.mark.asyncio
async def test_a_2xx_is_still_recorded_as_ok_with_no_finding() -> None:
    respx.get("https://api.open-meteo.com/v1/here").mock(
        return_value=httpx.Response(200, text='{"ok":true}')
    )

    exchange = await _transport().probe_get("/v1/here", label="here")

    assert exchange.succeeded is True
    assert exchange.outcome == "ok"
    assert exchange.finding is None


@respx.mock
@pytest.mark.asyncio
async def test_the_manifest_row_for_a_non_2xx_is_not_classified_ok(tmp_path: Path) -> None:
    respx.get("https://api.open-meteo.com/v1/missing").mock(
        return_value=httpx.Response(404, text=NOT_FOUND_BODY)
    )
    writer = ProbeEvidenceWriter(tmp_path)

    writer.record("missing", await _transport().probe_get("/v1/missing", label="missing"))

    row = (tmp_path / "request_manifest.tsv").read_text(encoding="utf-8").splitlines()[1]
    outcome = row.split("\t")[MANIFEST_OUTCOME_COLUMN]
    assert outcome != "ok"
    assert "404" in outcome


# -- 2. a question is answered only by a 2xx that carried its datum ---------


def test_a_question_is_unanswered_when_every_step_returned_non_2xx() -> None:
    plan = probe_a.build_request_plan()
    outcomes = [
        probe_a.evaluate_step(
            step, _probe_exchange(label=step.label, status=404, body=NOT_FOUND_BODY)
        )
        for step in plan
    ]

    questions = probe_a.evaluate_questions(plan, outcomes)

    assert [question.question for question in questions] == list(probe_a.QUESTIONS)
    assert all(question.answered is False for question in questions)
    assert all(question.reason for question in questions)
    assert all(question.answered_by == () for question in questions)


def test_a_question_is_unanswered_when_a_2xx_carried_no_datum() -> None:
    step = next(
        candidate
        for candidate in probe_a.build_request_plan()
        if "q2_variable_naming_and_real_max_n" in candidate.questions
    )

    outcome = probe_a.evaluate_step(
        step, _probe_exchange(label=step.label, status=200, body='{"latitude":40.78}')
    )

    assert outcome.succeeded is True
    assert outcome.datum is None
    assert outcome.reason is not None
    question = _by_question(probe_a.evaluate_questions([step], [outcome]))[
        "q2_variable_naming_and_real_max_n"
    ]
    assert question.answered is False


def test_a_question_with_no_planned_step_is_unanswered_not_silently_dropped() -> None:
    questions = probe_a.evaluate_questions([], [])

    assert len(questions) == len(probe_a.QUESTIONS)
    assert all(question.answered is False for question in questions)


def test_a_question_is_answered_when_a_2xx_yielded_its_datum() -> None:
    step = next(
        candidate
        for candidate in probe_a.build_request_plan()
        if "q2_variable_naming_and_real_max_n" in candidate.questions
        and "boundary" not in candidate.label
        and "hourly" not in candidate.label
    )

    outcome = probe_a.evaluate_step(
        step,
        _probe_exchange(label=step.label, status=200, body=_previous_runs_body(max_index=7)),
    )

    assert outcome.datum is not None
    assert outcome.datum["max_previous_day_index"] == 7
    question = _by_question(probe_a.evaluate_questions([step], [outcome]))[
        "q2_variable_naming_and_real_max_n"
    ]
    assert question.answered is True
    assert step.label in question.answered_by


def test_the_restatement_question_is_never_answered_from_a_single_run() -> None:
    """Q6 is a cross-run diff. One execution captures a baseline; it answers nothing."""
    steps = [
        step for step in probe_a.build_request_plan() if "q6_values_ever_restated" in step.questions
    ]
    assert steps
    outcomes = [
        probe_a.evaluate_step(
            step, _probe_exchange(label=step.label, status=200, body=_previous_runs_body())
        )
        for step in steps
    ]

    question = _by_question(probe_a.evaluate_questions(steps, outcomes))["q6_values_ever_restated"]

    assert question.answered is False
    assert question.reason is not None
    assert "run" in question.reason.lower()


# -- 3. anchoring is CLASSIFIED from the captures, never asserted -----------


def test_valid_time_anchoring_is_classified_from_the_window_and_the_control() -> None:
    window = {
        "times": ["2026-08-23", "2026-08-26", "2026-08-29"],
        "series": {"temperature_2m_max_previous_day1": [20.0, 25.0, 29.0]},
    }
    control = {
        "times": ["2026-08-29"],
        "series": {"temperature_2m_max_previous_day1": [29.0]},
    }

    assert probe_a.classify_anchor(window, control) == "valid_time"


def test_run_time_anchoring_is_classified_when_the_window_moves_the_values() -> None:
    window = {
        "times": ["2026-08-23", "2026-08-26", "2026-08-29"],
        "series": {"temperature_2m_max_previous_day1": [20.0, 25.0, 29.0]},
    }
    control = {
        "times": ["2026-08-29"],
        "series": {"temperature_2m_max_previous_day1": [11.5]},
    }

    assert probe_a.classify_anchor(window, control) == "run_time"


@pytest.mark.parametrize(
    ("window", "control"),
    [
        (None, {"times": ["2026-08-29"], "series": {"x_previous_day1": [1.0]}}),
        ({"times": ["2026-08-29"], "series": {"x_previous_day1": [1.0]}}, None),
        (
            {"times": ["2026-08-23"], "series": {"x_previous_day1": [1.0]}},
            {"times": ["2026-08-29"], "series": {"x_previous_day1": [1.0]}},
        ),
    ],
    ids=["no_window", "no_control", "no_overlap"],
)
def test_anchoring_is_unclassifiable_without_two_comparable_captures(
    window: Any, control: Any
) -> None:
    assert probe_a.classify_anchor(window, control) is None


# -- 4. the VERDICT is computed from the answered set ----------------------


def _answered(question: str, datum: dict[str, Any]) -> Any:
    return probe_a.QuestionOutcome(
        question=question,
        answered=True,
        answered_by=("step",),
        data=(datum,),
        reason=None,
    )


def _unanswered(question: str) -> Any:
    return probe_a.QuestionOutcome(
        question=question,
        answered=False,
        answered_by=(),
        data=(),
        reason="no 2xx step yielded the datum",
    )


def _bar_clearing_questions() -> tuple[Any, ...]:
    return (
        _answered("q1_unkeyed_and_on_which_host", {"unkeyed": True}),
        _answered("q2_variable_naming_and_real_max_n", {"max_previous_day_index": 7}),
        _answered(
            "q3_archive_depth_for_one_site",
            {"step": probe_a.ARCHIVE_BAR_LABEL, "first_time": "2024-01-01"},
        ),
        _answered(
            "q4_valid_time_or_run_time_anchored",
            {"anchor": "valid_time", "corroborated_by": "q3_archive_depth_2022"},
        ),
    )


def test_the_verdict_is_viable_only_when_every_bar_clause_is_satisfied() -> None:
    verdict = probe_a.evaluate_verdict(
        _bar_clearing_questions(), shape=probe_a.CANDIDATE_SHAPES[0], keyed=False
    )

    assert verdict.verdict == probe_a.VERDICT_VIABLE
    assert verdict.refuted == ()
    assert verdict.unresolved == ()


def test_the_verdict_is_not_viable_when_the_endpoint_is_absent() -> None:
    verdict = probe_a.evaluate_verdict((), shape=None, keyed=False)

    assert verdict.verdict == probe_a.VERDICT_NOT_VIABLE
    assert any("endpoint" in clause for clause in verdict.refuted)


def test_the_verdict_is_not_viable_when_the_endpoint_requires_a_key() -> None:
    verdict = probe_a.evaluate_verdict(
        _bar_clearing_questions(), shape=probe_a.CANDIDATE_SHAPES[0], keyed=True
    )

    assert verdict.verdict == probe_a.VERDICT_NOT_VIABLE
    assert any("unkeyed" in clause for clause in verdict.refuted)


def test_the_verdict_is_not_viable_when_the_series_is_run_time_anchored() -> None:
    questions = [
        outcome
        for outcome in _bar_clearing_questions()
        if outcome.question != "q4_valid_time_or_run_time_anchored"
    ]
    questions.append(_answered("q4_valid_time_or_run_time_anchored", {"anchor": "run_time"}))

    verdict = probe_a.evaluate_verdict(questions, shape=probe_a.CANDIDATE_SHAPES[0], keyed=False)

    assert verdict.verdict == probe_a.VERDICT_NOT_VIABLE
    assert any("anchor" in clause for clause in verdict.refuted)


def test_the_verdict_is_not_viable_when_max_n_is_below_the_bar() -> None:
    questions = [
        outcome
        for outcome in _bar_clearing_questions()
        if outcome.question != "q2_variable_naming_and_real_max_n"
    ]
    questions.append(_answered("q2_variable_naming_and_real_max_n", {"max_previous_day_index": 3}))

    verdict = probe_a.evaluate_verdict(questions, shape=probe_a.CANDIDATE_SHAPES[0], keyed=False)

    assert verdict.verdict == probe_a.VERDICT_NOT_VIABLE


def test_the_verdict_is_inconclusive_when_a_bar_clause_is_unresolved() -> None:
    questions = [
        outcome
        for outcome in _bar_clearing_questions()
        if outcome.question != "q3_archive_depth_for_one_site"
    ]
    questions.append(_unanswered("q3_archive_depth_for_one_site"))

    verdict = probe_a.evaluate_verdict(questions, shape=probe_a.CANDIDATE_SHAPES[0], keyed=False)

    assert verdict.verdict == probe_a.VERDICT_INCONCLUSIVE
    assert any("archive" in clause for clause in verdict.unresolved)


# -- 5. the report tells the truth and ENDS with the verdict ---------------


def _rendered_report_for_a_total_404() -> str:
    plan = probe_a.build_request_plan()
    discovery_plan = probe_a.build_discovery_plan()
    discovery_exchanges = tuple(
        _probe_exchange(label=step.label, status=404, body=NOT_FOUND_BODY, ordinal=index + 1)
        for index, step in enumerate(discovery_plan)
    )
    discovery = probe_a.DiscoveryResult(
        shape=None,
        exchanges=discovery_exchanges,
        outcomes=tuple(
            probe_a.evaluate_step(step, exchange)
            for step, exchange in zip(discovery_plan, discovery_exchanges, strict=True)
        ),
        keyed=False,
        aborted="No candidate endpoint shape returned previous-run data.",
    )
    execution = probe_a.ExecutionResult(
        exchanges=(),
        outcomes=(),
        aborted=discovery.aborted,
        skipped=tuple(step.label for step in plan),
    )
    questions = probe_a.evaluate_questions((*discovery_plan, *plan), discovery.outcomes)
    verdict = probe_a.evaluate_verdict(questions, shape=None, keyed=False)
    # ``probe_a`` is imported from a path at runtime, so ``render_report`` is
    # typed ``Any``. Narrow it by checking the value, not by casting: the
    # report is the probe's only human-readable artifact, and a renderer that
    # returned bytes or ``None`` should fail here rather than downstream.
    report = probe_a.render_report(
        discovery=discovery,
        plan=plan,
        execution=execution,
        questions=questions,
        verdict=verdict,
        budget=RequestBudget(limit=probe_a.REQUEST_BUDGET),
    )
    assert isinstance(report, str), f"render_report must return text, got {type(report)!r}"
    return report


def test_the_report_lists_every_non_2xx_under_findings() -> None:
    report = _rendered_report_for_a_total_404()

    findings = report.split("## Findings", 1)[1]
    assert "None recorded" not in findings, "the 2026-08-31 report claimed no findings from 22 404s"
    assert "404" in findings


def test_the_report_marks_every_question_unanswered_when_nothing_returned_data() -> None:
    report = _rendered_report_for_a_total_404()

    coverage = report.split("## Question coverage", 1)[1].split("## Findings", 1)[0]
    assert coverage.strip()
    for question in probe_a.QUESTIONS:
        line = next(line for line in coverage.splitlines() if question in line)
        assert "UNANSWERED" in line, line


def test_the_report_ends_with_an_explicit_branch_h_verdict() -> None:
    report = _rendered_report_for_a_total_404()

    last = report.strip().splitlines()[-1]
    assert last.startswith("VERDICT:")
    assert probe_a.VERDICT_NOT_VIABLE in last


def test_the_report_names_how_many_steps_were_skipped_and_why() -> None:
    report = _rendered_report_for_a_total_404()

    assert "skipped" in report.lower()
    assert str(len(probe_a.build_request_plan())) in report


# -- 6. a failed baseline aborts the rest of the plan ----------------------


@respx.mock
@pytest.mark.asyncio
async def test_a_failed_baseline_aborts_the_remaining_plan(tmp_path: Path) -> None:
    """21 further requests re-learning the same 404 is the waste the counter prevents."""
    route = respx.get(url__startswith="https://api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(404, text=NOT_FOUND_BODY)
    )
    budget = RequestBudget(limit=probe_a.REQUEST_BUDGET)
    plan = probe_a.build_request_plan()

    result = await probe_a.execute(
        _transport(budget=budget), ProbeEvidenceWriter(tmp_path), plan, pause_seconds=0.0
    )

    assert route.call_count == 1
    assert budget.spent == 1
    assert result.aborted is not None
    assert "baseline" in result.aborted.lower()
    assert len(result.skipped) == len(plan) - 1


@respx.mock
@pytest.mark.asyncio
async def test_a_healthy_baseline_lets_the_plan_continue(tmp_path: Path) -> None:
    respx.get(url__startswith="https://api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(200, text=_previous_runs_body(max_index=7))
    )
    budget = RequestBudget(limit=probe_a.REQUEST_BUDGET)
    plan = probe_a.build_request_plan()

    result = await probe_a.execute(
        _transport(budget=budget), ProbeEvidenceWriter(tmp_path), plan, pause_seconds=0.0
    )

    assert result.aborted is None
    assert result.skipped == ()
    assert len(result.exchanges) == len(plan)


# -- 7. Defect 2: a LOW-BUDGET discovery phase finds the real shape --------


def test_discovery_tries_the_regular_forecast_endpoint_before_the_dedicated_host() -> None:
    plan = probe_a.build_discovery_plan()

    assert 0 < len(plan) <= probe_a.DISCOVERY_BUDGET
    hosts = [step.shape.host for step in plan]
    assert hosts[0] == "api.open-meteo.com"
    assert "previous-runs-api.open-meteo.com" in hosts
    assert hosts.index("previous-runs-api.open-meteo.com") > 0
    for step in plan:
        assert step.shape.path.startswith("/v1/")


@respx.mock
@pytest.mark.asyncio
async def test_discovery_stops_at_the_first_shape_that_serves_previous_run_data(
    tmp_path: Path,
) -> None:
    respx.get(url__startswith="https://api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(200, text=_previous_runs_body(max_index=3))
    )
    dedicated = respx.get(
        url__startswith="https://previous-runs-api.open-meteo.com/v1/forecast"
    ).mock(return_value=httpx.Response(200, text=_previous_runs_body(max_index=3)))
    budget = RequestBudget(limit=probe_a.REQUEST_BUDGET)

    result = await probe_a.run_discovery(
        _transport_factory(budget),
        ProbeEvidenceWriter(tmp_path),
        probe_a.build_discovery_plan(),
        pause_seconds=0.0,
    )

    assert result.shape is not None
    assert result.shape.host == "api.open-meteo.com"
    assert dedicated.call_count == 0
    assert budget.spent == 1


@respx.mock
@pytest.mark.asyncio
async def test_discovery_falls_through_to_the_dedicated_host(tmp_path: Path) -> None:
    respx.get(url__startswith="https://api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(400, text='{"error":true,"reason":"invalid variable"}')
    )
    respx.get(url__startswith="https://previous-runs-api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(200, text=_previous_runs_body(max_index=7))
    )
    budget = RequestBudget(limit=probe_a.REQUEST_BUDGET)

    result = await probe_a.run_discovery(
        _transport_factory(budget),
        ProbeEvidenceWriter(tmp_path),
        probe_a.build_discovery_plan(),
        pause_seconds=0.0,
    )

    assert result.shape is not None
    assert result.shape.host == "previous-runs-api.open-meteo.com"
    assert result.keyed is False
    assert budget.spent <= probe_a.DISCOVERY_BUDGET


@respx.mock
@pytest.mark.asyncio
async def test_discovery_aborts_within_its_low_budget_when_no_shape_answers(
    tmp_path: Path,
) -> None:
    respx.get(url__startswith="https://api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(404, text=NOT_FOUND_BODY)
    )
    respx.get(url__startswith="https://previous-runs-api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(404, text=NOT_FOUND_BODY)
    )
    budget = RequestBudget(limit=probe_a.REQUEST_BUDGET)

    result = await probe_a.run_discovery(
        _transport_factory(budget),
        ProbeEvidenceWriter(tmp_path),
        probe_a.build_discovery_plan(),
        pause_seconds=0.0,
    )

    assert result.shape is None
    assert result.aborted is not None
    assert budget.spent <= probe_a.DISCOVERY_BUDGET


@respx.mock
@pytest.mark.asyncio
async def test_a_key_requirement_is_a_finding_that_closes_branch_h(tmp_path: Path) -> None:
    """No authentication is attempted: a keyed endpoint is recorded and closes the branch."""
    respx.get(url__startswith="https://api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(401, text='{"error":true,"reason":"API key required"}')
    )
    respx.get(url__startswith="https://previous-runs-api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(401, text='{"error":true,"reason":"API key required"}')
    )
    budget = RequestBudget(limit=probe_a.REQUEST_BUDGET)

    result = await probe_a.run_discovery(
        _transport_factory(budget),
        ProbeEvidenceWriter(tmp_path),
        probe_a.build_discovery_plan(),
        pause_seconds=0.0,
    )

    assert result.keyed is True
    assert result.shape is None
    verdict = probe_a.evaluate_verdict((), shape=None, keyed=True)
    assert verdict.verdict == probe_a.VERDICT_NOT_VIABLE


# ==========================================================================
# Probe A -- three over-claims the LIVE 2026-08-31T005421Z data exposed
#
# The endpoint exists, and answering from it surfaced three ways the
# evaluation could still report more than the payloads support:
#   * `api.open-meteo.com/v1/forecast` ACCEPTS `temperature_2m_previous_day1`
#     and returns 200 with an ALL-NULL series -- a named variable is not a
#     served variable;
#   * the archive is NON-CONTIGUOUS (2022-01 populated, 2024-01 all null), so
#     "some older window had data" must not satisfy "the archive reaches
#     2024-01";
#   * window-vs-control invariance rules out request-window anchoring but NOT
#     a run chosen relative to the request instant. Only a historical capture
#     discriminates those, and Q4 is the question that matters most.
# ==========================================================================


def _mixed_null_body(*, populated: int, named: int) -> str:
    hourly: dict[str, Any] = {
        "time": ["2026-08-29T00:00", "2026-08-29T01:00"],
        "temperature_2m": [20.0, 21.0],
    }
    for index in range(1, named + 1):
        hourly[f"temperature_2m_previous_day{index}"] = (
            [20.0 - index, 21.0 - index] if index <= populated else [None, None]
        )
    return json.dumps({"latitude": 40.78, "hourly": hourly})


def test_a_named_but_all_null_series_is_not_a_datum() -> None:
    """The live regular-forecast endpoint answers 200 with every value null."""
    exchange = _probe_exchange(
        label="all_null", status=200, body=_mixed_null_body(populated=0, named=1)
    )

    assert probe_a.extract_previous_day_variables(exchange) is None


def test_max_previous_day_index_counts_only_populated_series() -> None:
    exchange = _probe_exchange(
        label="ladder", status=200, body=_mixed_null_body(populated=3, named=8)
    )

    datum = probe_a.extract_previous_day_variables(exchange)

    assert datum is not None
    assert datum["max_previous_day_index"] == 3, "an all-null day8 is not a served day8"
    assert datum["previous_day_variables"] == (
        "temperature_2m_previous_day1",
        "temperature_2m_previous_day2",
        "temperature_2m_previous_day3",
    )


def _archive_questions(*data: dict[str, Any]) -> tuple[Any, ...]:
    others = [
        outcome
        for outcome in _bar_clearing_questions()
        if outcome.question != "q3_archive_depth_for_one_site"
    ]
    archive = probe_a.QuestionOutcome(
        question="q3_archive_depth_for_one_site",
        answered=bool(data),
        answered_by=tuple(str(item["step"]) for item in data),
        data=tuple(data),
        reason=None if data else "no window returned values",
    )
    return (*others, archive)


def test_the_archive_clause_is_satisfied_only_by_the_step_that_tested_the_bar() -> None:
    verdict = probe_a.evaluate_verdict(
        _archive_questions({"step": probe_a.ARCHIVE_BAR_LABEL, "first_time": "2024-01-01T00:00"}),
        shape=probe_a.CANDIDATE_SHAPES[0],
        keyed=False,
    )

    assert probe_a.CLAUSE_ARCHIVE in verdict.satisfied
    assert verdict.verdict == probe_a.VERDICT_VIABLE


def test_a_non_contiguous_archive_is_inconclusive_not_a_pass() -> None:
    """2022-01 populated while 2024-01 is empty is an anomaly, not a clearance."""
    verdict = probe_a.evaluate_verdict(
        _archive_questions({"step": "q3_archive_depth_2022", "first_time": "2022-01-01T00:00"}),
        shape=probe_a.CANDIDATE_SHAPES[0],
        keyed=False,
    )

    assert probe_a.CLAUSE_ARCHIVE in verdict.unresolved
    assert probe_a.CLAUSE_ARCHIVE not in verdict.satisfied
    assert verdict.verdict == probe_a.VERDICT_INCONCLUSIVE


def test_the_archive_clause_is_refuted_when_nothing_reaches_the_bar() -> None:
    verdict = probe_a.evaluate_verdict(
        _archive_questions({"step": "q3_archive_depth_recent", "first_time": "2026-08-01T00:00"}),
        shape=probe_a.CANDIDATE_SHAPES[0],
        keyed=False,
    )

    assert probe_a.CLAUSE_ARCHIVE in verdict.refuted
    assert verdict.verdict == probe_a.VERDICT_NOT_VIABLE


def _anchor_questions(datum: dict[str, Any]) -> tuple[Any, ...]:
    others = [
        outcome
        for outcome in _bar_clearing_questions()
        if outcome.question != "q4_valid_time_or_run_time_anchored"
    ]
    return (*others, _answered("q4_valid_time_or_run_time_anchored", datum))


def test_valid_time_anchoring_alone_does_not_satisfy_the_clause() -> None:
    """Window-invariance cannot tell a valid-time series from a run-relative one."""
    verdict = probe_a.evaluate_verdict(
        _anchor_questions({"anchor": "valid_time", "corroborated_by": None}),
        shape=probe_a.CANDIDATE_SHAPES[0],
        keyed=False,
    )

    assert probe_a.CLAUSE_ANCHOR in verdict.unresolved
    assert verdict.verdict == probe_a.VERDICT_INCONCLUSIVE


def test_a_historical_capture_corroborates_valid_time_anchoring() -> None:
    verdict = probe_a.evaluate_verdict(
        _anchor_questions({"anchor": "valid_time", "corroborated_by": "q3_archive_depth_2022"}),
        shape=probe_a.CANDIDATE_SHAPES[0],
        keyed=False,
    )

    assert probe_a.CLAUSE_ANCHOR in verdict.satisfied
    assert verdict.verdict == probe_a.VERDICT_VIABLE


def test_the_corroborating_capture_is_found_from_the_run_itself() -> None:
    """A window whose valid times are long past cannot come from a run chosen now."""
    recent = probe_a.StepOutcome(
        label="q4_anchor_daily_window",
        status_code=200,
        succeeded=True,
        datum={"first_time": "2026-08-23T00:00", "last_time": "2026-08-29T23:00"},
        reason=None,
    )
    historical = probe_a.StepOutcome(
        label="q3_archive_depth_2022",
        status_code=200,
        succeeded=True,
        datum={"first_time": "2022-01-01T00:00", "last_time": "2022-01-07T23:00"},
        reason=None,
    )

    assert probe_a.corroborating_historical_capture((recent, historical)) == "q3_archive_depth_2022"
    assert probe_a.corroborating_historical_capture((recent,)) is None
    assert probe_a.corroborating_historical_capture(()) is None
