"""M6: the F13-C1 US-source ingest can never reach the order path (plan r3 R10, R22, R30, R34).

``lint-imports`` covers ``src/`` only (``pyproject.toml`` ``root_packages``), so this
module is the ONLY import check over ``scripts/``. It is deliberately NOT the cage's
``BANNED_EXEC_TRANSPORT_MODULES`` set: it carries its own banned set, scans by
directory (a new file is covered with no registration step) and follows imports
transitively.

What counts as reaching the order path (each citation is verified by
``test_every_banned_module_citation_resolves``, so a moved symbol fails here):

* the write transport, ``PolymarketUSWriteTransport``;
* the order sender, the ``_order_sender.post_order`` call inside the exec client;
* the permit, ``LiveTradingPermit`` and ``OrderSubmissionPermit``;
* ``breezy.runtime`` (the whole package: it owns the settings, the supervisor and the
  permit plumbing);
* the exec client and the ``breezy.adapters.polymarket_us.exec`` package;
* ``breezy.exec`` (no such package today; reserved so a future one is covered).

Scan rules:

* A C1-OWNED file (every ``.py`` under ``scripts/collect/`` and the five new ``src``
  modules) is scanned for EVERY import, at any nesting depth, and for dotted-string
  references to a banned module.
* A file REACHED from a C1 entry point is followed through its MODULE-LEVEL imports
  only, because that is what Python loads at import time (``breezy/__init__.py`` keeps
  its ``breezy.runtime`` import function-local for exactly this reason). The ancestor
  packages' ``__init__`` files are part of the closure.
* A pre-existing file under ``scripts/venue/`` or ``src/breezy/ingest/`` is exempt ONLY
  while its sha256 equals the recorded ``M6_PREEXISTING_BASELINE`` digest (R30). A
  modified baseline file is scanned like a new file, and a C1-closure file is scanned
  whether or not it is listed.
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections.abc import Iterable, Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
SCRIPTS = REPO_ROOT / "scripts"
COLLECT_DIR = SCRIPTS / "collect"

#: module (or package prefix) -> (citation file, line, text that must be on that line)
BANNED_MODULES: dict[str, tuple[str, int, str]] = {
    "breezy.adapters.polymarket_us.write_transport": (
        "src/breezy/adapters/polymarket_us/write_transport.py",
        147,
        "class PolymarketUSWriteTransport",
    ),
    "breezy.adapters.polymarket_us.exec": (
        "src/breezy/adapters/polymarket_us/exec/client.py",
        1593,
        "class PolymarketUSExecutionClient",
    ),
    "breezy.adapters.polymarket_us.safety": (
        "src/breezy/adapters/polymarket_us/safety.py",
        385,
        "class LiveTradingPermit",
    ),
    "breezy.runtime": (
        "src/breezy/runtime/order_enablement.py",
        155,
        "class OrderSubmissionPermit",
    ),
    "breezy.exec": (
        "src/breezy/adapters/polymarket_us/exec/client.py",
        5550,
        "self._order_sender.post_order",
    ),
}

#: Names that must not be imported from ANY module (aliasing cannot hide them).
BANNED_NAMES: frozenset[str] = frozenset(
    {
        "PolymarketUSWriteTransport",
        "Ed25519WriteRequestSigner",
        "PolymarketUSExecutionClient",
        "LiveTradingPermit",
        "OrderSubmissionPermit",
    }
)

#: The C1-owned library modules (``scripts/collect/*.py`` is added by directory).
C1_SRC_MODULES: tuple[str, ...] = (
    "src/breezy/ingest/mdl_lamp_transport.py",
    "src/breezy/ingest/lamp_archive_stream.py",
    "src/breezy/ingest/lamp_parse.py",
    "src/breezy/ingest/pfm_parse.py",
    "src/breezy/ingest/us_source_availability.py",
    "src/breezy/persistence/us_source_request.py",
    "src/breezy/persistence/us_source_revision_store.py",
)

#: Entry points of the transitive closure (R22).
CLOSURE_ENTRY_POINTS: tuple[str, ...] = (
    "scripts/collect/us_source_collector.py",
    "scripts/venue/iem_mos_probe_transport.py",
    "src/breezy/ingest/us_source_availability.py",
    "src/breezy/ingest/lamp_parse.py",
    "src/breezy/ingest/pfm_parse.py",
    *C1_SRC_MODULES,
)

#: Data transports: GET-only by AST. (``scripts/collect/us_source_alert.py`` is the single
#: sanctioned POST and is NOT a data transport; it has its own test below.)
DATA_TRANSPORT_FILES: tuple[str, ...] = (
    "src/breezy/ingest/mdl_lamp_transport.py",
    "src/breezy/ingest/lamp_archive_stream.py",
    "src/breezy/ingest/nbm_quantile_transport.py",
    "scripts/venue/iem_mos_probe_transport.py",
)

#: Files that name an allowlisted host (the closed host sets of the C1 data sources).
ALLOWLIST_FILES: tuple[str, ...] = (
    "src/breezy/ingest/mdl_lamp_transport.py",
    "src/breezy/ingest/nbm_quantile_transport.py",
    "scripts/venue/iem_mos_probe_transport.py",
)

SHA256_HEX = re.compile(r"[0-9a-f]{64}")

#: Frozen at F13-C1 S4. Additive-only: a new pre-existing-file entry may be appended,
#: nothing is ever removed or re-digested to make a scan pass (R30).
M6_PREEXISTING_BASELINE: dict[str, str] = {
    "scripts/venue/_write_sequence.py": "d49c238293f0cf7aa64ce1d295960fa4eb4eeb03c6d82d7223d2feb304d9a2e8",  # noqa: E501
    "scripts/venue/fee_drift_evidence_pull.py": "bbaa9c098e61dae7c3dc32d9addfa3920132c4249d3a4c725bdff79d6a3b2950",  # noqa: E501
    "scripts/venue/iem_afos_forecast_pil_probe.py": "121af2d1945acec194d1bb2b5dab9bca795d88f6657f847908354f6c4aafb040",  # noqa: E501
    "scripts/venue/iem_mos_reachability_probe.py": "63ad3725c65cdfea57ca3a9658c91ec39b80654c443343ec77bd0c25fad10b7f",  # noqa: E501
    "scripts/venue/iem_mos_txn_occupancy_probe.py": "40c156ea7d6dcdbff16cfd7e247ce7d8ac4a3a6589beb8104d1370b56fdf4d19",  # noqa: E501
    "scripts/venue/nbm_nomads_discovery_probe.py": "9eb1d8ec7c17dd0f1acb62a0f9cd8ca449c94d829550531c3a64686aefe434dc",  # noqa: E501
    "scripts/venue/open_meteo_coverage_bisect_probe.py": "95d2fc343d70be78fdc02b8b8fdbdfc84602d1dc2675616ffb1831b52ebeb679",  # noqa: E501
    "scripts/venue/open_meteo_previous_runs_probe.py": "505f5868b8096426cc4960dde69100b730fd962db95f7e33bdfdfb566498f9d2",  # noqa: E501
    "scripts/venue/polymarket_us_auth_smoke.py": "82390f6a1abd1ca4595a63e12a476565fceea1bdc9c508ea3437a2f2765dd43a",  # noqa: E501
    "scripts/venue/polymarket_us_capital_flow_pull.py": "56005638006617e6e50bd0196b82ab084c34523428c54f75484adc823f15113d",  # noqa: E501
    "scripts/venue/polymarket_us_positions_value_capture.py": "593f676d53269d3c000a8118879d976aaa6a3c67bb943dd213bd65ed9504b54a",  # noqa: E501
    "scripts/venue/polymarket_us_private_shape_probe.py": "5e295f20f097e521ca3b7d86cd1ed5497637ecb2f225d25acbe05d19e558af7f",  # noqa: E501
    "scripts/venue/polymarket_us_shape_capture.py": "0117997dbe576465f206cc0e75afc78eaa496de929f11de876ece890cf3fa633",  # noqa: E501
    "scripts/venue/polymarket_us_write_signing_probe.py": "fbc925a7a09be883ccdd53d84307ee047c24aa6ad45c988f53091bc2af99043f",  # noqa: E501
    "src/breezy/ingest/_nbm_text_common.py": "62dbb22751260cb9ee62f795ab7dc5634b2876c85ac2cb2d880ea24ca9126837",  # noqa: E501
    "src/breezy/ingest/gaps.py": "5d62031c75747b804f019d291fe423d557ce060c1dbec6acb8c2b443cfec0c96",
    "src/breezy/ingest/iem_observations.py": "91cfe28c52972eece997e9375bcb4ec367d8c4bf964777f9838668ccfe355f87",  # noqa: E501
    "src/breezy/ingest/nbm_forecast_data_type.py": "551ec95b1f709dae6f853e815a676411a8ca58bd11deceb1ddf27d8e56b87d47",  # noqa: E501
    "src/breezy/ingest/nbm_quantile_actor.py": "2e5253f01a96ea11a35ca319dfdf17c647243c48e0922d0a7da9ac4e90629123",  # noqa: E501
    "src/breezy/ingest/nbm_quantile_parse.py": "0ce9080a9f07f1ab3c26483219fc3f128ac89180fb68029a64f30ad226e345b1",  # noqa: E501
    "src/breezy/ingest/nws_actor.py": "a887ebed10a4466cb6dd2888f0998b4c885dc9f6171e55febb7b1169325b641d",  # noqa: E501
    "src/breezy/ingest/nws_health.py": "fedf65636baaf792de3e3ffc00b4834ed6f16e09c1a6dbe9b0b1cea7318bbd12",  # noqa: E501
    "src/breezy/ingest/nws_observation_actor.py": "334bf1a9ef0e566fb1592de16895255d9dd58db5303770c4209f26013806e7d8",  # noqa: E501
    "src/breezy/ingest/nws_observation_config.py": "6501c81dfe821e8f82ad5457d2a5f90c87e123fa1925738d549fe83de8cd62ed",  # noqa: E501
    "src/breezy/ingest/nws_observation_rebuild.py": "600f6a425f878d312300490e6f82475b7e82f271054c060274731885cc89b300",  # noqa: E501
    "src/breezy/ingest/nws_observation_transport.py": "331e0ea6ec6043cdc27b172bb1de843b79a894b7d66a55569af1e0ddbd3adbc9",  # noqa: E501
    "src/breezy/ingest/nws_observations.py": "8a42ea14de812f2663907198e9581181b042cd2d5f0f80e4e83e1d66291816f6",  # noqa: E501
    "src/breezy/ingest/observation_sidecar.py": "4d6830ed1472d8b93061d0fa245ec6d94a2e95ce1b645a52aa3f89816774dd79",  # noqa: E501
}
M6_BASELINE_FROZEN_COUNT = 28


# --------------------------------------------------------------------------- parsing


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_banned(dotted: str) -> str | None:
    for banned in BANNED_MODULES:
        if dotted == banned or dotted.startswith(banned + "."):
            return banned
    return None


def _module_level_nodes(body: list[ast.stmt]) -> Iterator[ast.AST]:
    """Statements Python executes at import: everything except function bodies."""
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        yield node
        for field in ("body", "orelse", "finalbody"):
            nested = getattr(node, field, None)
            if isinstance(nested, list):
                yield from _module_level_nodes(nested)
        for handler in getattr(node, "handlers", []):
            yield from _module_level_nodes(handler.body)


def _package_parts(path: Path) -> tuple[str, ...]:
    if SRC in path.parents:
        return path.relative_to(SRC).with_suffix("").parts[:-1]
    return ()


def _imported_dotted_names(path: Path, *, module_level_only: bool) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    nodes: Iterable[ast.AST] = (
        _module_level_nodes(tree.body) if module_level_only else ast.walk(tree)
    )
    found: set[str] = set()
    package = _package_parts(path)
    for node in nodes:
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = list(package[: len(package) - (node.level - 1)])
                module = ".".join([*base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            if module:
                found.add(module)
            found.update(f"{module}.{alias.name}" for alias in node.names)
    return found


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }


def _string_references(path: Path) -> set[str]:
    """Dotted-string constants that name a banned module (importlib / __import__ hides)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def resolve_module(dotted: str) -> Path | None:
    parts = dotted.split(".")
    if parts[0] == "breezy":
        base = SRC.joinpath(*parts)
    elif parts[0] == "scripts":
        base = REPO_ROOT.joinpath(*parts)
    else:
        for sub in sorted(SCRIPTS.iterdir()):
            candidate = sub / f"{dotted}.py"
            if sub.is_dir() and candidate.is_file():
                return candidate
        return None
    if base.with_suffix(".py").is_file():
        return base.with_suffix(".py")
    if (base / "__init__.py").is_file():
        return base / "__init__.py"
    return None


def _c1_owned_files() -> list[Path]:
    collect = sorted(COLLECT_DIR.glob("*.py")) if COLLECT_DIR.is_dir() else []
    return [*collect, *(REPO_ROOT / rel for rel in C1_SRC_MODULES)]


def import_closure(entries: Iterable[Path]) -> dict[Path, set[str]]:
    """Every file reachable from ``entries``; C1-owned files contribute ALL imports."""
    owned = set(_c1_owned_files())
    seen: dict[Path, set[str]] = {}
    stack = list(entries)
    while stack:
        path = stack.pop()
        if path in seen:
            continue
        names = _imported_dotted_names(path, module_level_only=path not in owned)
        seen[path] = names
        for dotted in names:
            pieces = dotted.split(".")
            for end in range(1, len(pieces) + 1):
                resolved = resolve_module(".".join(pieces[:end]))
                if resolved is not None:
                    stack.append(resolved)
    return seen


def banned_hits(closure: dict[Path, set[str]]) -> list[str]:
    hits: list[str] = []
    owned = set(_c1_owned_files())
    for path, names in sorted(closure.items()):
        for dotted in sorted(names):
            if (banned := _is_banned(dotted)) is not None:
                hits.append(f"{_rel(path)} imports {dotted} (banned {banned})")
        if path in owned:
            hits.extend(
                f"{_rel(path)} imports the banned name {name}"
                for name in sorted(_imported_names(path) & BANNED_NAMES)
            )
            hits.extend(
                f"{_rel(path)} names the banned module {text!r} as a string"
                for text in sorted(_string_references(path))
                if _is_banned(text) is not None
            )
    return hits


def closure_files() -> set[Path]:
    entries = [REPO_ROOT / rel for rel in CLOSURE_ENTRY_POINTS if (REPO_ROOT / rel).is_file()]
    return set(import_closure(entries))


def baseline_exempts(path: Path, baseline: dict[str, str]) -> bool:
    """R30: exempt only while the current digest equals the recorded one."""
    recorded = baseline.get(_rel(path))
    return recorded is not None and recorded == _sha256(path)


def directory_scan_targets(baseline: dict[str, str]) -> list[Path]:
    """Every .py under scripts/venue and src/breezy/ingest the baseline does not exempt."""
    closure = closure_files()
    targets: list[Path] = []
    for directory in (SCRIPTS / "venue", SRC / "breezy" / "ingest"):
        for path in sorted(directory.rglob("*.py")):
            if path in closure or not baseline_exempts(path, baseline):
                targets.append(path)
    return targets


# ------------------------------------------------------------------------ the guard


def test_scripts_collect_exists_and_is_non_empty() -> None:
    assert COLLECT_DIR.is_dir(), "scripts/collect/ must exist"
    assert (COLLECT_DIR / "us_source_collector.py").is_file()
    assert list(COLLECT_DIR.glob("*.py")), "scripts/collect/ must not be an empty scan"


def test_every_banned_module_citation_resolves() -> None:
    for module, (file, line, needle) in BANNED_MODULES.items():
        lines = (REPO_ROOT / file).read_text(encoding="utf-8").splitlines()
        assert needle in lines[line - 1], f"{module}: {file}:{line} no longer holds {needle!r}"


def test_data_transports_have_no_transitive_import_of_write_transport_order_sender_permit_runtime_exec_client_or_exec() -> (  # noqa: E501
    None
):
    entries = [REPO_ROOT / rel for rel in CLOSURE_ENTRY_POINTS if (REPO_ROOT / rel).is_file()]
    assert len(entries) == len(CLOSURE_ENTRY_POINTS), "a C1 entry point is missing"
    assert banned_hits(import_closure(entries)) == []


def test_m6_scans_by_directory_including_iem_mos_probe_transport() -> None:
    targets = {_rel(p) for p in directory_scan_targets(M6_PREEXISTING_BASELINE)}
    assert "scripts/venue/iem_mos_probe_transport.py" in targets
    assert "src/breezy/ingest/mdl_lamp_transport.py" in targets
    # Every directory target is scanned directly, not only through the closure.
    assert banned_hits(import_closure(REPO_ROOT / rel for rel in sorted(targets))) == []


def test_every_c1_owned_file_is_scanned_for_all_imports() -> None:
    owned = {_rel(p) for p in _c1_owned_files()}
    assert {"scripts/collect/us_source_collector.py", *C1_SRC_MODULES} <= owned


def test_m6_baseline_excludes_c1_closure() -> None:
    exempt_closure = sorted(_rel(p) for p in closure_files() if _rel(p) in M6_PREEXISTING_BASELINE)
    assert exempt_closure == []
    assert not {rel for rel in M6_PREEXISTING_BASELINE if rel.startswith("scripts/collect/")}
    assert not set(C1_SRC_MODULES) & set(M6_PREEXISTING_BASELINE)


def test_m6_modified_baseline_file_is_rescanned(tmp_path: Path) -> None:
    victim = SRC / "breezy" / "ingest" / "nws_actor.py"
    assert victim.is_file()
    honest = {_rel(victim): _sha256(victim)}
    tampered = {_rel(victim): "0" * 64}
    assert victim not in directory_scan_targets(honest) or victim in closure_files()
    assert victim in directory_scan_targets(tampered)
    assert baseline_exempts(victim, honest) is True
    assert baseline_exempts(victim, tampered) is False


def test_m6_baseline_is_well_formed_and_never_shrinks() -> None:
    assert len(M6_PREEXISTING_BASELINE) >= M6_BASELINE_FROZEN_COUNT > 0
    for rel, digest in M6_PREEXISTING_BASELINE.items():
        assert SHA256_HEX.fullmatch(digest), rel
        assert (REPO_ROOT / rel).is_file(), f"{rel} was removed; baseline entries are additive"
        assert rel.startswith(("scripts/venue/", "src/breezy/ingest/")), rel


def test_every_unexempted_preexisting_file_is_clean() -> None:
    """The baseline is the ONLY thing that may hide a banned import in these directories."""
    targets = directory_scan_targets(M6_PREEXISTING_BASELINE)
    assert targets
    for path in targets:
        assert banned_hits(import_closure([path])) == [], _rel(path)


def test_no_exec_or_runtime_module_imports_any_c1_module() -> None:
    c1_modules = {
        "breezy.ingest.mdl_lamp_transport",
        "breezy.ingest.lamp_archive_stream",
        "breezy.ingest.lamp_parse",
        "breezy.ingest.pfm_parse",
        "breezy.ingest.us_source_availability",
        "breezy.persistence.us_source_request",
        "breezy.persistence.us_source_revision_store",
    }
    roots = [
        SRC / "breezy" / "adapters",
        SRC / "breezy" / "runtime",
        SRC / "breezy" / "exec",
    ]
    scanned = 0
    offenders: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            scanned += 1
            for dotted in _imported_dotted_names(path, module_level_only=False):
                if dotted in c1_modules or dotted.startswith(
                    ("us_source_", "scripts.collect", "mdl_lamp_", "lamp_archive_")
                ):
                    offenders.append(f"{_rel(path)} imports {dotted}")
            for text in _string_references(path):
                if text in c1_modules:
                    offenders.append(f"{_rel(path)} names {text!r}")
    assert scanned > 50, "the reverse scan must actually reach the exec, runtime and adapters"
    assert offenders == []


# ------------------------------------------------------------- the GET-only AST rules

_WRITE_VERBS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_WRITE_ATTRS = frozenset({"post", "put", "patch", "delete"})


def _non_get_sites(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    sites: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _WRITE_ATTRS:
                sites.append(f"{path.name}:{node.lineno} .{node.func.attr}(")
            if node.func.attr in {"request", "stream", "send"} and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and str(first.value).upper() in _WRITE_VERBS:
                    sites.append(f"{path.name}:{node.lineno} verb {first.value!r}")
        if isinstance(node, ast.keyword) and node.arg in {"data", "content", "files"}:
            sites.append(f"{path.name}:{node.value.lineno} request body keyword {node.arg}=")
        if isinstance(node, ast.keyword) and node.arg == "method":
            value = node.value
            if isinstance(value, ast.Constant) and str(value.value).upper() != "GET":
                sites.append(f"{path.name}:{node.value.lineno} method={value.value!r}")
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.upper() in _WRITE_VERBS
        ):
            sites.append(f"{path.name}:{node.lineno} literal {node.value!r}")
    return sites


def test_data_transports_use_only_http_get() -> None:
    for rel in DATA_TRANSPORT_FILES:
        assert _non_get_sites(REPO_ROOT / rel) == [], rel


def test_get_only_detector_is_not_vacuous(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import httpx\n"
        "async def f(c: httpx.AsyncClient):\n"
        "    await c.post('https://x')\n"
        "    await c.request('PUT', 'https://x')\n",
        encoding="utf-8",
    )
    assert len(_non_get_sites(probe)) >= 2


def test_post_detector_flags_a_data_keyword_body(tmp_path: Path) -> None:
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import urllib.request\n"
        "def f(url: str) -> None:\n"
        "    urllib.request.urlopen(urllib.request.Request(url, data=b'x'))\n",
        encoding="utf-8",
    )
    assert any("data=" in site for site in _non_get_sites(probe))


def test_the_only_request_body_in_scripts_collect_is_the_alert_webhook() -> None:
    posting = {p.name for p in sorted(COLLECT_DIR.glob("*.py")) if _non_get_sites(p)}
    assert posting <= {"us_source_alert.py"}
    text = (COLLECT_DIR / "us_source_alert.py").read_text(encoding="utf-8")
    assert "http.client" not in text and "requests" not in text


def test_alert_poster_refuses_a_non_https_url_without_calling_the_opener() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "us_source_alert_probe", COLLECT_DIR / "us_source_alert.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls: list[object] = []

    def opener(*args: object, **kwargs: object) -> object:
        calls.append(args)
        raise AssertionError("the opener must not be reached")

    assert module.post_alert("http://hooks.example/x", "e", "s", "d", opener=opener) is False
    assert calls == []


def test_no_polymarket_kalshi_or_exec_host_in_any_allowlist() -> None:
    forbidden = re.compile(r"polymarket|kalshi|elections|trading\.|clob|gamma", re.IGNORECASE)
    for rel in ALLOWLIST_FILES:
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and "HOST" in t.id.upper() for t in node.targets)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                assert not forbidden.search(node.value.value), f"{rel}:{node.lineno}"
        hosts = re.findall(r'"([a-z0-9.-]+\.(?:gov|com|edu|org))"', (REPO_ROOT / rel).read_text())
        assert not [h for h in hosts if forbidden.search(h)], rel


def test_guard_runs_with_mock_transport_and_no_live_fetch() -> None:
    """The guard is a pure AST pass: it opens no socket and imports no transport."""
    imported = _imported_dotted_names(Path(__file__), module_level_only=False)
    assert not any(name.split(".")[0] in {"httpx", "socket", "urllib"} for name in imported)


# ----------------------------------------------- the firewall pins (WIDENED, never relaxed)

#: ``BANNED_EXEC_TRANSPORT_MODULES`` as it stood BEFORE F13-C1 S4 (recorded baseline).
X1_PIN_BASELINE: frozenset[str] = frozenset(
    {
        "breezy.adapters.polymarket_us.data",
        "breezy.adapters.polymarket_us.http",
        "breezy.adapters.polymarket_us.websocket",
        "breezy.ingest.http",
        "breezy.ingest.nws_observation_actor",
        "breezy.ingest.nws_observation_config",
        "breezy.ingest.nws_observation_transport",
        "breezy.ingest.nws_observations",
        "breezy.ingest.probe_transport",
        "breezy.runtime.health",
    }
)


def test_exec_import_pin_x1_is_superset_of_recorded_baseline() -> None:
    """The cage's equality pin (``test_cage_rule_constants_are_pinned``, row
    ``BANNED_EXEC_TRANSPORT_MODULES``) stays an EQUALITY. This is the additional
    never-narrow check: the live set contains every pre-C1 member."""
    import tests.unit.test_execution_egress_firewall_guard as firewall

    assert X1_PIN_BASELINE <= firewall.BANNED_EXEC_TRANSPORT_MODULES


def test_mdl_lamp_transport_in_banned_exec_transport_modules() -> None:
    import tests.unit.test_execution_egress_firewall_guard as firewall

    assert "breezy.ingest.mdl_lamp_transport" in firewall.BANNED_EXEC_TRANSPORT_MODULES
    assert firewall.BANNED_EXEC_TRANSPORT_MODULES - X1_PIN_BASELINE == {
        "breezy.ingest.mdl_lamp_transport"
    }
