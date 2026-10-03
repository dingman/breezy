"""ARCH-0 seam 4a: the autonomy envelope scans (ARCH Rev 9.2 section 4.7, seam A AC 7/17/26).

Each test is an AST scan that is a pure function of ``(path, source)``. The real-tree test runs the
scan over every judged file and asserts a minimum judged count (so a scan that walks nothing cannot
pass); a parametrised control test runs the same scan over planted sources and requires a hit for
every form the scan claims to catch, plus clean sources it must not flag.

Judged sets. "Autonomy sources" are every ``autonomy`` package under ``src/breezy`` plus any
``*autonomy*.py`` module or script. The "core" is ``breezy.persistence.autonomy``. The sets grow as
seams land; the minimums are the sizes at seam 4a and only ever protect against a vacuous scan.

The operator-reserved control names are never spelt in this file (L-39): tokens are derived from
``operator_controls.OPERATOR_RESERVED_CONTROL_ENV_VARS`` and planted sources interpolate them at
runtime, exactly as ``test_operator_control_assignment_scan`` does.
"""

from __future__ import annotations

import ast
import hashlib
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Final

import pytest

from breezy.adapters.polymarket_us import operator_controls, safety
from breezy.runtime import settings as runtime_settings
from breezy.runtime import trade_supervisor_core
from tests.support.autonomy_scan import (
    Finding,
    ScanFn,
    autonomy_source_files,
    core_source_files,
    imported_modules,
    package_of,
    relative_path,
    scan_files,
    walk_with_scope,
)
from tests.support.entry_points import REPO_ROOT, SCRIPTS_DIR, SRC_DIR

#: Sizes at seam 4a: 16 autonomy modules, 12 of them in the core.
MIN_AUTONOMY_FILES: Final = 14
MIN_CORE_FILES: Final = 11
#: All of ``src`` and ``scripts`` (375 files at seam 4a).
MIN_REPO_FILES: Final = 300

_PLANTED_PATH: Final = "src/breezy/persistence/autonomy/planted.py"


def _parse(path: str, source: str) -> ast.Module:
    return ast.parse(source, filename=path)


def _plants(findings_fn: ScanFn, cases: dict[str, str], *, path: str = _PLANTED_PATH) -> list[str]:
    """Names of planted cases the scan failed to flag."""
    return [name for name, source in cases.items() if not findings_fn(path, _render(source))]


def _render(source: str) -> str:
    """Interpolate the operator-control names at runtime so this file never spells them."""
    daily, position = sorted(CONTROL_ENV_VAR_NAMES)
    return source.replace("<DAILY>", daily).replace("<POSITION>", position)


def _matches_prefix(module: str, prefixes: Iterable[str]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


def _import_scan(rule: str, prefixes: Iterable[str]) -> ScanFn:
    banned = tuple(prefixes)

    def scan(path: str, source: str) -> list[Finding]:
        tree = _parse(path, source)
        return [
            Finding(path, lineno, rule, module)
            for module, lineno in imported_modules(tree, package=package_of(path))
            if _matches_prefix(module, banned)
        ]

    return scan


def _constant_strings(tree: ast.AST) -> Iterable[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value, node.lineno


def _identifiers(tree: ast.AST) -> Iterable[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.id, node.lineno
        elif isinstance(node, ast.Attribute):
            yield node.attr, node.lineno


def _token_scan(
    rule: str,
    *,
    literals: Iterable[str] = (),
    identifiers: Iterable[str] = (),
    module_prefixes: Iterable[str] = (),
) -> ScanFn:
    """Flag any string constant containing a literal, any identifier, and any module import."""
    literal_tokens = tuple(literals)
    identifier_tokens = frozenset(identifiers)
    prefixes = tuple(module_prefixes)

    def scan(path: str, source: str) -> list[Finding]:
        tree = _parse(path, source)
        found = [
            Finding(path, lineno, rule, "string literal")
            for text, lineno in _constant_strings(tree)
            if any(token in text for token in literal_tokens)
        ]
        found.extend(
            Finding(path, lineno, rule, f"identifier {name}")
            for name, lineno in _identifiers(tree)
            if name in identifier_tokens
        )
        found.extend(
            Finding(path, lineno, rule, f"import {module}")
            for module, lineno in imported_modules(tree, package=package_of(path))
            if _matches_prefix(module, prefixes)
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom | ast.Import):
                names = [alias.name for alias in node.names]
                found.extend(
                    Finding(path, node.lineno, rule, f"import name {name}")
                    for name in names
                    if name in identifier_tokens
                )
        return found

    return scan


def _assert_clean(files: list[Path], scan: ScanFn, *, minimum: int) -> None:
    assert len(files) >= minimum, f"judged {len(files)} files, expected at least {minimum}"
    findings = scan_files(files, scan)
    assert findings == [], [(f.path, f.lineno, f.rule, f.detail) for f in findings]


# ---------------------------------------------------------------------------
# 1. Operator-reserved controls: never read, written, passed or computed
# ---------------------------------------------------------------------------

CONTROL_ENV_VAR_NAMES: Final = frozenset(operator_controls.OPERATOR_RESERVED_CONTROL_ENV_VARS)
CONTROL_IDENTIFIERS: Final = (
    frozenset(
        name
        for name, value in vars(operator_controls).items()
        if isinstance(value, str) and value in CONTROL_ENV_VAR_NAMES
    )
    | {"OPERATOR_RESERVED_CONTROL_ENV_VARS"}
    | {name for name in vars(operator_controls) if name.startswith("operator_max_")}
    | {"_read_operator_money", "_require_operator_value"}
)
_scan_operator_controls: Final = _token_scan(
    "operator_control",
    literals=CONTROL_ENV_VAR_NAMES,
    identifiers=CONTROL_IDENTIFIERS,
    module_prefixes=(operator_controls.__name__,),
)

_PLANTED_OPERATOR: Final[dict[str, str]] = {
    "literal_read": 'import os\nCAP = os.environ.get("<DAILY>")\n',
    "literal_in_a_tuple": 'NAMES = ("<POSITION>",)\n',
    "literal_inside_a_longer_string": 'MSG = "see <DAILY> for the cap"\n',
    "constant_identifier": (
        "from breezy.adapters.polymarket_us.operator_controls import (\n"
        "    MAX_DAILY_BUDGET_USD_ENV_VAR,\n"
        ")\n"
    ),
    "constant_attribute": (
        "from breezy.adapters.polymarket_us import operator_controls\n"
        "NAME = operator_controls.MAX_POSITION_COST_USD_ENV_VAR\n"
    ),
    "inventory_tuple": (
        "from breezy.adapters.polymarket_us.operator_controls import "
        "OPERATOR_RESERVED_CONTROL_ENV_VARS\nX = list(OPERATOR_RESERVED_CONTROL_ENV_VARS)\n"
    ),
    "sanctioned_reader_call": (
        "from breezy.adapters.polymarket_us.operator_controls import (\n"
        "    operator_max_daily_budget_usd,\n)\n"
        "def f():\n    return operator_max_daily_budget_usd()\n"
    ),
    "module_import_only": "import breezy.adapters.polymarket_us.operator_controls\n",
    "private_reader_chain": "def f(safety):\n    return safety._read_operator_money('x')\n",
}


def test_autonomy_never_reads_or_writes_operator_controls() -> None:
    assert CONTROL_ENV_VAR_NAMES and len(CONTROL_ENV_VAR_NAMES) >= 2
    assert {"OPERATOR_RESERVED_CONTROL_ENV_VARS", "operator_max_daily_budget_usd"} <= (
        CONTROL_IDENTIFIERS
    )
    _assert_clean(autonomy_source_files(), _scan_operator_controls, minimum=MIN_AUTONOMY_FILES)


def test_operator_control_scan_fires_on_every_planted_form() -> None:
    assert _plants(_scan_operator_controls, _PLANTED_OPERATOR) == []


def test_operator_control_scan_ignores_unrelated_environment_names() -> None:
    clean = 'import os\nHOME = os.environ.get("HOME")\nX = "BREEZY_SENDING_FAMILY_ID"\n'
    assert _scan_operator_controls(_PLANTED_PATH, clean) == []


# ---------------------------------------------------------------------------
# 2. Enablement, the order permit and the NO-SEND firewall are untouched
# ---------------------------------------------------------------------------

_SAFETY_ENV_VARS: Final = {
    value
    for name, value in vars(safety).items()
    if name.endswith("_ENV_VAR") and isinstance(value, str)
}
ENABLEMENT_LITERALS: Final = frozenset(
    _SAFETY_ENV_VARS
    | {
        runtime_settings.ORDERS_ENABLED_VAR,
        trade_supervisor_core.PERMIT_EXPIRY_CEILING_NS_ENV_VAR,
        "BREEZY_TEST_OS_EGRESS_BLOCK",
    }
)
ENABLEMENT_IDENTIFIERS: Final = frozenset(
    {name for name in vars(safety) if name.endswith("_ENV_VAR")}
    | {
        "issue_live_trading_permit",
        "LiveTradingPermit",
        "LiveOrderSubmissionAuthorization",
        "assert_live_order_submission_permitted",
        "OrderSubmissionPermit",
        "orders_enabled_requested",
        "restore_live_trading_budget",
        "seed_permit_budget_from_prior_spend",
        "os_egress_block_attested",
    }
)
ENABLEMENT_MODULES: Final = (
    "breezy.adapters.polymarket_us.safety",
    "breezy.runtime.order_enablement",
    "breezy.runtime.backtest_order_guard",
)
_scan_enablement: Final = _token_scan(
    "enablement_permit_firewall",
    literals=ENABLEMENT_LITERALS,
    identifiers=ENABLEMENT_IDENTIFIERS,
    module_prefixes=ENABLEMENT_MODULES,
)

_PLANTED_ENABLEMENT: Final[dict[str, str]] = {
    "import_safety": "from breezy.adapters.polymarket_us import safety\n",
    "import_safety_module": "import breezy.adapters.polymarket_us.safety\n",
    "import_order_enablement": (
        "from breezy.runtime.order_enablement import OrderSubmissionPermit\n"
    ),
    "orders_enabled_literal": 'import os\nX = os.environ.get("BREEZY_ORDERS_ENABLED")\n',
    "trading_enabled_literal": 'FLAG = "BREEZY_TRADING_ENABLED"\n',
    "permit_ceiling_literal": 'KEY = "BREEZY_PERMIT_EXPIRY_CEILING_NS"\n',
    "firewall_attestation_literal": 'KEY = "BREEZY_TEST_OS_EGRESS_BLOCK"\n',
    "permit_issue_call": (
        "def f(issue_live_trading_permit):\n    return issue_live_trading_permit()\n"
    ),
    "permit_type": "def f(p: LiveTradingPermit) -> None: ...\n",
    "settings_flag_attribute": "def f(s):\n    return s.orders_enabled_requested\n",
}


def test_autonomy_never_touches_enablement_permit_or_firewall() -> None:
    assert "BREEZY_TRADING_ENABLED" in ENABLEMENT_LITERALS
    assert "BREEZY_ORDERS_ENABLED" in ENABLEMENT_LITERALS
    assert "TRADING_ENABLED_ENV_VAR" in ENABLEMENT_IDENTIFIERS
    _assert_clean(autonomy_source_files(), _scan_enablement, minimum=MIN_AUTONOMY_FILES)


def test_enablement_scan_fires_on_every_planted_form() -> None:
    assert _plants(_scan_enablement, _PLANTED_ENABLEMENT) == []


def test_enablement_scan_ignores_the_permit_lapsed_veto_reason() -> None:
    clean = 'PERMIT_LAPSED = "permit_lapsed"\n'
    assert _scan_enablement(_PLANTED_PATH, clean) == []


# ---------------------------------------------------------------------------
# 3. The order path is never imported
# ---------------------------------------------------------------------------

ORDER_PATH_PREFIXES: Final = (
    "breezy.adapters.polymarket_us.exec",
    "breezy.adapters.polymarket_us.factories",
    "breezy.adapters.polymarket_us.write_transport",
    "breezy.runtime.order_enablement",
    "breezy.app",
    "nautilus_trader.execution",
    "nautilus_trader.live",
    "nautilus_trader.model.orders",
    "nautilus_trader.risk",
)
_scan_order_path: Final = _import_scan("order_path_import", ORDER_PATH_PREFIXES)

_PLANTED_ORDER_PATH: Final[dict[str, str]] = {
    "exec_client": (
        "from breezy.adapters.polymarket_us.exec.client import PolymarketUSExecutionClient\n"
    ),
    "exec_package_name": "from breezy.adapters.polymarket_us import exec\n",
    "factories": "import breezy.adapters.polymarket_us.factories\n",
    "write_transport": "from breezy.adapters.polymarket_us.write_transport import X\n",
    "app_trade": "from breezy.app.trade import main\n",
    "nautilus_execution": "from nautilus_trader.execution.engine import ExecutionEngine\n",
    "nautilus_live": "import nautilus_trader.live.node\n",
    "nautilus_orders": "from nautilus_trader.model.orders import LimitOrder\n",
    "under_type_checking": (
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
        "    from breezy.adapters.polymarket_us.exec.client import PolymarketUSExecutionClient\n"
    ),
    "function_local": (
        "def f():\n    from breezy.adapters.polymarket_us.exec import client\n    return client\n"
    ),
    "relative_climb_to_exec": "from ...adapters.polymarket_us.exec import client\n",
}


def test_autonomy_never_imports_order_path() -> None:
    _assert_clean(autonomy_source_files(), _scan_order_path, minimum=MIN_AUTONOMY_FILES)


def test_order_path_scan_fires_on_every_planted_form() -> None:
    cases = dict(_PLANTED_ORDER_PATH)
    relative = cases.pop("relative_climb_to_exec")
    assert _plants(_scan_order_path, cases) == []
    assert _scan_order_path("src/breezy/persistence/autonomy/planted.py", relative)


def test_order_path_scan_ignores_neighbouring_modules() -> None:
    clean = (
        "from breezy.adapters.polymarket_us.exec_report import X\n"
        "from breezy.persistence.live_orders_gate import verify\n"
        "from nautilus_trader.model.identifiers import InstrumentId\n"
    )
    assert _scan_order_path(_PLANTED_PATH, clean) == []


# ---------------------------------------------------------------------------
# 4. Alert egress is not widened
# ---------------------------------------------------------------------------

#: Autonomy code has no network client of its own: alerts leave through the existing outbox and
#: ``alerts.env`` key. A reviewed new egress path re-pins this set (ARCH section 4.6).
ALERT_EGRESS_ALLOWED_IMPORTS: Final[frozenset[str]] = frozenset()
NETWORK_MODULE_PREFIXES: Final = (
    "socket", "ssl", "http", "urllib", "requests", "httpx", "aiohttp", "websockets", "websocket",
    "smtplib", "ftplib", "telnetlib", "xmlrpc", "grpc", "nautilus_pyo3", "urllib3",
)  # fmt: skip
_WEBHOOK_KEY: Final = "BREEZY_ALERT_WEBHOOK_URL"
_URL_RE: Final = re.compile(r"\b(?:https?|wss?|ftp)://", re.IGNORECASE)


def _scan_alert_egress(path: str, source: str) -> list[Finding]:
    tree = _parse(path, source)
    found = [
        Finding(path, lineno, "alert_egress", f"import {module}")
        for module, lineno in imported_modules(tree, package=package_of(path))
        if _matches_prefix(module, NETWORK_MODULE_PREFIXES)
        and module not in ALERT_EGRESS_ALLOWED_IMPORTS
    ]
    found.extend(
        Finding(path, lineno, "alert_egress", "webhook key or URL literal")
        for text, lineno in _constant_strings(tree)
        if _WEBHOOK_KEY in text or _URL_RE.search(text)
    )
    return found


_PLANTED_EGRESS: Final[dict[str, str]] = {
    "urllib_request": "import urllib.request\n",
    "from_http_client": "from http.client import HTTPSConnection\n",
    "requests": "import requests\n",
    "httpx": "import httpx\n",
    "raw_socket": "import socket\n",
    "native_client": "from nautilus_pyo3 import HttpClient\n",
    "webhook_key": 'KEY = "BREEZY_ALERT_WEBHOOK_URL"\n',
    "new_host": 'HOST = "https://hooks.example.test/alerts"\n',
    "websocket_url": 'URL = "wss://example.test/feed"\n',
}


def test_autonomy_alert_egress_not_widened() -> None:
    assert ALERT_EGRESS_ALLOWED_IMPORTS == frozenset()
    _assert_clean(autonomy_source_files(), _scan_alert_egress, minimum=MIN_AUTONOMY_FILES)


def test_alert_egress_scan_fires_on_every_planted_form() -> None:
    assert _plants(_scan_alert_egress, _PLANTED_EGRESS) == []


def test_alert_egress_scan_ignores_non_network_modules() -> None:
    clean = "import json\nimport hashlib\nfrom pathlib import Path\nLABEL = 'http_status'\n"
    assert _scan_alert_egress(_PLANTED_PATH, clean) == []


# ---------------------------------------------------------------------------
# 5. Payload hygiene
# ---------------------------------------------------------------------------

_ABSOLUTE_PATH_RE: Final = re.compile(
    r"(?:\A|[\s'\"=(\[,])(?:/(?:home|root|tmp|var|etc|usr|opt|mnt|srv|proc|dev)\b|~/)"
)
#: Names whose value must not be interpolated into a message or payload: paths, environment
#: values, credentials, and account or venue order identifiers (ARCH section 4.1, payload hygiene).
_UNSAFE_INTERPOLATION_NAMES: Final = frozenset(
    {
        "path", "paths", "root", "directory", "dirpath", "filename", "file_path", "abs_path",
        "absolute_path", "environ", "getenv", "env", "environment", "__file__", "getcwd", "cwd",
        "home", "expanduser",
        "order_id", "client_order_id", "venue_order_id", "account", "account_id",
        "api_key", "secret", "token", "password", "credential", "credentials",
    }
)  # fmt: skip


def _interpolated_expressions(tree: ast.AST) -> Iterable[ast.expr]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FormattedValue):
            yield node.value
        elif (
            isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Mod)
            and isinstance(node.left, ast.Constant)
            and isinstance(node.left.value, str)
        ):
            yield node.right
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "format"
            and isinstance(node.func.value, ast.Constant)
        ):
            yield from node.args
            yield from (kw.value for kw in node.keywords)


def _scan_payload_hygiene(path: str, source: str) -> list[Finding]:
    tree = _parse(path, source)
    found = [
        Finding(path, lineno, "payload_hygiene", "absolute path literal")
        for text, lineno in _constant_strings(tree)
        if _ABSOLUTE_PATH_RE.search(text)
    ]
    for expr in _interpolated_expressions(tree):
        names = {n.id.lower() for n in ast.walk(expr) if isinstance(n, ast.Name)} | {
            n.attr.lower() for n in ast.walk(expr) if isinstance(n, ast.Attribute)
        }
        unsafe = sorted(names & _UNSAFE_INTERPOLATION_NAMES)
        if unsafe:
            found.append(
                Finding(path, expr.lineno, "payload_hygiene", f"interpolates {', '.join(unsafe)}")
            )
    return found


_PLANTED_HYGIENE: Final[dict[str, str]] = {
    "absolute_home_path": 'ROOT = "/home/jon/.local/share/breezy"\n',
    "absolute_tmp_path": 'SCRATCH = "/tmp/x"\n',
    "tilde_path": 'CFG = "~/.config/breezy"\n',
    "path_in_message": 'def f(path):\n    raise ValueError(f"cannot read {path}")\n',
    "path_attribute_in_message": 'def f(p):\n    return f"bad {p.path}"\n',
    "percent_format_path": 'def f(root):\n    return "bad %s" % root\n',
    "str_format_env": 'def f(env):\n    return "x {}".format(env)\n',
    "environ_value": "import os\ndef f():\n    return f\"v={os.environ['X']}\"\n",
    "order_id": 'def f(client_order_id):\n    return f"order {client_order_id}"\n',
    "account": 'def f(account_id):\n    return {"k": f"{account_id}"}\n',
    "dunder_file": 'def f():\n    return f"at {__file__}"\n',
    "getcwd": 'import os\ndef f():\n    return f"in {os.getcwd()}"\n',
    "path_home": 'from pathlib import Path\ndef f():\n    return f"{Path.home()}"\n',
}


def test_autonomy_payload_hygiene_scan() -> None:
    _assert_clean(autonomy_source_files(), _scan_payload_hygiene, minimum=MIN_AUTONOMY_FILES)


def test_payload_hygiene_scan_fires_on_every_planted_form() -> None:
    assert _plants(_scan_payload_hygiene, _PLANTED_HYGIENE) == []


def test_payload_hygiene_scan_ignores_enum_only_messages() -> None:
    clean = (
        "def f(reason, venue, seq):\n"
        '    return f"refused {reason.value} venue={venue} seq={seq}"\n'
        'X = "/" + "a"\n'
        'URLISH = "registry/engine.lock"\n'
        "from pathlib import Path\n"
        "HERE = Path(__file__).resolve().parents[3]\n"
        "ROOT = Path.home() / '.local'\n"
    )
    assert _scan_payload_hygiene(_PLANTED_PATH, clean) == []


# ---------------------------------------------------------------------------
# 6. BREEZY_FAMILY_SOURCE is read only by the resolver and the child-env builder
# ---------------------------------------------------------------------------

FAMILY_SOURCE_LITERAL: Final = "BREEZY_FAMILY_SOURCE"
#: (module, enclosing function or None for the whole module) allowed to name the variable. The
#: resolver and ``build_child_env`` (AUT-5 r7 U14) land with AUT-5; absence is accepted.
FAMILY_SOURCE_ALLOWED: Final[tuple[tuple[str, str | None], ...]] = (
    ("breezy.persistence.autonomy.resolver", None),
    ("breezy.runtime.trade_supervisor_core", "build_child_env"),
)


def _scan_family_source(path: str, source: str) -> list[Finding]:
    tree = _parse(path, source)
    module = ".".join(Path(path).with_suffix("").parts)
    module = module.removeprefix("src.")
    found: list[Finding] = []
    for node, scope in walk_with_scope(tree):
        named = (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and FAMILY_SOURCE_LITERAL in node.value
        ) or (
            isinstance(node, ast.Name | ast.Attribute)
            and "FAMILY_SOURCE" in (node.id if isinstance(node, ast.Name) else node.attr)
        )
        if not named:
            continue
        allowed = any(
            module == allowed_module and (fn is None or scope == fn or scope.startswith(f"{fn}."))
            for allowed_module, fn in FAMILY_SOURCE_ALLOWED
        )
        if not allowed:
            found.append(Finding(path, getattr(node, "lineno", 0), "family_source", "named", scope))
    return found


def _python_sources() -> list[Path]:
    return sorted({*SRC_DIR.rglob("*.py"), *SCRIPTS_DIR.rglob("*.py")})


_PLANTED_FAMILY_SOURCE: Final[dict[str, str]] = {
    "literal_read": 'import os\nX = os.environ.get("BREEZY_FAMILY_SOURCE")\n',
    "literal_write": 'import os\nos.environ["BREEZY_FAMILY_SOURCE"] = "registry"\n',
    "constant_identifier": "from m import FAMILY_SOURCE_ENV_VAR\nX = FAMILY_SOURCE_ENV_VAR\n",
    "other_function_in_supervisor": 'def other():\n    return "BREEZY_FAMILY_SOURCE"\n',
}


def test_family_source_read_only_by_resolver_and_child_env() -> None:
    files = _python_sources()
    assert len(files) >= MIN_REPO_FILES
    findings = scan_files(files, _scan_family_source)
    assert findings == [], [(f.path, f.lineno, f.scope) for f in findings]


def test_family_source_scan_fires_on_every_planted_form() -> None:
    cases = dict(_PLANTED_FAMILY_SOURCE)
    other = cases.pop("other_function_in_supervisor")
    assert _plants(_scan_family_source, cases, path="src/breezy/runtime/settings.py") == []
    assert _scan_family_source("src/breezy/runtime/trade_supervisor_core.py", other)


def test_family_source_scan_accepts_the_two_named_readers() -> None:
    resolver = 'import os\nX = os.environ.get("BREEZY_FAMILY_SOURCE")\n'
    assert _scan_family_source("src/breezy/persistence/autonomy/resolver.py", resolver) == []
    builder = (
        'def build_child_env(base):\n    base["BREEZY_FAMILY_SOURCE"] = "x"\n    return base\n'
    )
    assert _scan_family_source("src/breezy/runtime/trade_supervisor_core.py", builder) == []


# ---------------------------------------------------------------------------
# 7. No dataclasses.asdict / astuple (AC 5: explicit to_wire/from_wire only)
# ---------------------------------------------------------------------------

_BANNED_DATACLASS_HELPERS: Final = frozenset({"asdict", "astuple"})


def _scan_asdict(path: str, source: str) -> list[Finding]:
    tree = _parse(path, source)
    return [
        Finding(path, lineno, "asdict", name)
        for name, lineno in _identifiers(tree)
        if name in _BANNED_DATACLASS_HELPERS
    ] + [
        Finding(path, node.lineno, "asdict", alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name in _BANNED_DATACLASS_HELPERS
    ]


_PLANTED_ASDICT: Final[dict[str, str]] = {
    "attribute": "import dataclasses\ndef f(x):\n    return dataclasses.asdict(x)\n",
    "astuple_attribute": "import dataclasses\ndef f(x):\n    return dataclasses.astuple(x)\n",
    "aliased_module": "import dataclasses as dc\ndef f(x):\n    return dc.asdict(x)\n",
    "from_import": "from dataclasses import asdict\n",
    "from_import_aliased": (
        "from dataclasses import asdict as to_dict\ndef f(x):\n    return to_dict(x)\n"
    ),
    "bare_call": "def f(x, asdict):\n    return asdict(x)\n",
}


def test_no_asdict_in_autonomy() -> None:
    _assert_clean(autonomy_source_files(), _scan_asdict, minimum=MIN_AUTONOMY_FILES)


def test_asdict_scan_fires_on_every_planted_form() -> None:
    assert _plants(_scan_asdict, _PLANTED_ASDICT) == []


def test_asdict_scan_ignores_other_dataclass_helpers() -> None:
    clean = "from dataclasses import dataclass, field, fields\nX = fields\n"
    assert _scan_asdict(_PLANTED_PATH, clean) == []


# ---------------------------------------------------------------------------
# 8. No wall clock in the core (now_ns is always explicit)
# ---------------------------------------------------------------------------

_WALL_CLOCK_ATTRS: Final = frozenset({"time", "time_ns", "now", "utcnow", "today"})
_WALL_CLOCK_TIME_NAMES: Final = frozenset({"time", "time_ns"})


def _scan_wall_clock(path: str, source: str) -> list[Finding]:
    tree = _parse(path, source)
    found: list[Finding] = []
    time_aliases = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "time"
        for alias in node.names
        if alias.name in _WALL_CLOCK_TIME_NAMES
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in _WALL_CLOCK_ATTRS:
            if func.attr in _WALL_CLOCK_TIME_NAMES and not (
                isinstance(func.value, ast.Name) and func.value.id in {"time", "_time"}
            ):
                continue  # e.g. some other object's .time() method
            found.append(Finding(path, node.lineno, "wall_clock", f".{func.attr}()"))
        elif isinstance(func, ast.Name) and func.id in time_aliases:
            found.append(Finding(path, node.lineno, "wall_clock", f"{func.id}()"))
        elif (
            isinstance(func, ast.Attribute)
            and func.attr in {"gmtime", "localtime", "ctime"}
            and not node.args
        ):
            found.append(Finding(path, node.lineno, "wall_clock", f".{func.attr}()"))
    return found


_PLANTED_WALL_CLOCK: Final[dict[str, str]] = {
    "time_time": "import time\nT = time.time()\n",
    "time_time_ns": "import time\nT = time.time_ns()\n",
    "from_time_import": "from time import time as clock\nT = clock()\n",
    "datetime_now": "from datetime import datetime\nT = datetime.now()\n",
    "datetime_utcnow": "import datetime\nT = datetime.datetime.utcnow()\n",
    "date_today": "from datetime import date\nT = date.today()\n",
    "gmtime_no_args": "import time\nT = time.gmtime()\n",
    "pandas_now": "import pandas as pd\nT = pd.Timestamp.now()\n",
}


def test_no_wall_clock_in_core() -> None:
    _assert_clean(core_source_files(), _scan_wall_clock, minimum=MIN_CORE_FILES)


def test_wall_clock_scan_fires_on_every_planted_form() -> None:
    assert _plants(_scan_wall_clock, _PLANTED_WALL_CLOCK) == []


def test_wall_clock_scan_ignores_explicit_instants_and_other_time_attributes() -> None:
    clean = (
        "import time\nfrom datetime import date\n"
        "def f(now_ns, iso, ts):\n"
        "    return date.fromisoformat(iso), time.gmtime(ts), now_ns, ts.time()\n"
    )
    assert _scan_wall_clock(_PLANTED_PATH, clean) == []


# ---------------------------------------------------------------------------
# 9. No threads, timers or asyncio in the core
# ---------------------------------------------------------------------------

CONCURRENCY_MODULE_PREFIXES: Final = (
    "threading", "_thread", "asyncio", "concurrent", "multiprocessing", "sched", "trio", "anyio",
    "gevent", "greenlet",
)  # fmt: skip
_CONCURRENCY_CALLS: Final = frozenset({"alarm", "setitimer", "Timer", "Thread", "start_new_thread"})


def _scan_concurrency(path: str, source: str) -> list[Finding]:
    tree = _parse(path, source)
    found = [
        Finding(path, lineno, "concurrency", f"import {module}")
        for module, lineno in imported_modules(tree, package=package_of(path))
        if _matches_prefix(module, CONCURRENCY_MODULE_PREFIXES)
    ]
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.Await | ast.AsyncFor | ast.AsyncWith):
            found.append(Finding(path, node.lineno, "concurrency", type(node).__name__))
        elif isinstance(node, ast.Call):
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", "")
            )
            if name in _CONCURRENCY_CALLS:
                found.append(Finding(path, node.lineno, "concurrency", f"{name}()"))
    return found


_PLANTED_CONCURRENCY: Final[dict[str, str]] = {
    "threading": "import threading\n",
    "from_threading": "from threading import Lock\n",
    "low_level_thread": "import _thread\n",
    "asyncio": "import asyncio\n",
    "from_asyncio": "from asyncio import sleep\n",
    "executor": "from concurrent.futures import ThreadPoolExecutor\n",
    "multiprocessing": "import multiprocessing\n",
    "sched": "import sched\n",
    "async_def": "async def f():\n    return 1\n",
    "await": "async def f(x):\n    await x\n",
    "signal_alarm": "import signal\ndef f():\n    signal.alarm(5)\n",
    "timer_call": "def f(mod):\n    mod.Timer(1, f)\n",
}


def test_no_threads_or_asyncio_in_core() -> None:
    _assert_clean(core_source_files(), _scan_concurrency, minimum=MIN_CORE_FILES)


def test_concurrency_scan_fires_on_every_planted_form() -> None:
    assert _plants(_scan_concurrency, _PLANTED_CONCURRENCY) == []


def test_concurrency_scan_ignores_neighbouring_names() -> None:
    clean = "import subprocess\nimport concurrently_named_but_not\nX = 'asyncio'\n"
    assert _scan_concurrency(_PLANTED_PATH, clean) == []


# ---------------------------------------------------------------------------
# 10. allow_draft=True is never passed
# ---------------------------------------------------------------------------


def _is_literal_false(expr: ast.expr | None) -> bool:
    return isinstance(expr, ast.Constant) and expr.value is False


def _scan_allow_draft(path: str, source: str) -> list[Finding]:
    tree = _parse(path, source)
    found: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            found.extend(
                Finding(path, node.lineno, "allow_draft", ast.unparse(kw.value))
                for kw in node.keywords
                if kw.arg == "allow_draft" and not _is_literal_false(kw.value)
            )
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            args = node.args
            positional = [*args.posonlyargs, *args.args]
            defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
            pairs = list(zip(positional, defaults, strict=True)) + list(
                zip(args.kwonlyargs, args.kw_defaults, strict=True)
            )
            found.extend(
                Finding(path, node.lineno, "allow_draft", f"default of {arg.arg}")
                for arg, default in pairs
                if arg.arg == "allow_draft"
                and default is not None
                and not _is_literal_false(default)
            )
    return found


_PLANTED_ALLOW_DRAFT: Final[dict[str, str]] = {
    "keyword_true": (
        "def f(raw, p):\n    return parse_family_manifest(raw, path=p, allow_draft=True)\n"
    ),
    "keyword_variable": (
        "def f(raw, p, d):\n    return parse_family_manifest(raw, path=p, allow_draft=d)\n"
    ),
    "keyword_truthy_expression": (
        "def f(raw, p):\n    return g(raw, path=p, allow_draft=not False)\n"
    ),
    "partial": (
        "import functools\nparse = functools.partial(parse_family_manifest, allow_draft=True)\n"
    ),
    "default_true": "def f(raw, *, allow_draft=True):\n    return raw\n",
    "positional_default_true": "def f(raw, allow_draft=True):\n    return raw\n",
}


def test_autonomy_never_passes_allow_draft_true() -> None:
    _assert_clean(autonomy_source_files(), _scan_allow_draft, minimum=MIN_AUTONOMY_FILES)


def test_allow_draft_scan_fires_on_every_planted_form() -> None:
    assert _plants(_scan_allow_draft, _PLANTED_ALLOW_DRAFT) == []


def test_allow_draft_scan_accepts_literal_false() -> None:
    clean = (
        "def f(raw, p):\n    return parse_family_manifest(raw, path=p, allow_draft=False)\n"
        "def g(raw, *, allow_draft=False):\n    return raw\n"
    )
    assert _scan_allow_draft(_PLANTED_PATH, clean) == []


# ---------------------------------------------------------------------------
# 11. The exec client is never edited
# ---------------------------------------------------------------------------

_EXEC_CLIENT: Final[Path] = REPO_ROOT / "src/breezy/adapters/polymarket_us/exec/client.py"
_PIN_SOURCE: Final[Path] = (
    REPO_ROOT / "tests/unit/test_forecast_quantile_ladder_manifest_and_markers.py"
)
_PIN_NAME: Final = "_EXEC_CLIENT_SHA256"
_SHA256_RE: Final = re.compile(r"\A[0-9a-f]{64}\Z")


def _read_pin(source: str) -> str:
    """The V7 byte pin, read by AST from its single home (never imported, never restated)."""
    for node in ast.parse(source).body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == _PIN_NAME for t in node.targets)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise AssertionError(f"{_PIN_NAME} not found")


def exec_client_drifted(data: bytes, pin: str) -> bool:
    return hashlib.sha256(data).hexdigest() != pin


_NAMES_EXEC_CLIENT_FILE: Final = re.compile(r"exec/client(?:\.py)?\b")


def _scan_exec_client_reference(path: str, source: str) -> list[Finding]:
    tree = _parse(path, source)
    return [
        Finding(path, lineno, "exec_client", "names the exec client file")
        for text, lineno in _constant_strings(tree)
        if _NAMES_EXEC_CLIENT_FILE.search(text)
    ]


def test_exec_client_never_edited() -> None:
    pin = _read_pin(_PIN_SOURCE.read_text(encoding="utf-8"))
    assert _SHA256_RE.match(pin)
    assert not exec_client_drifted(_EXEC_CLIENT.read_bytes(), pin), (
        "exec/client.py differs from its V7 byte pin; it is never edited by the autonomy programme"
    )
    _assert_clean(autonomy_source_files(), _scan_exec_client_reference, minimum=MIN_AUTONOMY_FILES)


def test_exec_client_drift_is_detected_on_planted_bytes() -> None:
    pin = _read_pin(_PIN_SOURCE.read_text(encoding="utf-8"))
    original = _EXEC_CLIENT.read_bytes()
    assert exec_client_drifted(original + b"\n", pin)
    assert exec_client_drifted(original[:-1], pin)
    assert exec_client_drifted(b"", pin)


def test_exec_client_pin_reader_fails_closed_when_the_pin_is_absent() -> None:
    with pytest.raises(AssertionError):
        _read_pin("OTHER = 'x'\n")


def test_exec_client_reference_scan_fires_on_planted_forms() -> None:
    planted = {
        "path_literal": 'P = "src/breezy/adapters/polymarket_us/exec/client.py"\n',
        "relative_literal": 'P = "exec/client"\n',
    }
    assert _plants(_scan_exec_client_reference, planted) == []


# ---------------------------------------------------------------------------
# Judged sets
# ---------------------------------------------------------------------------


def test_judged_sets_are_nested_and_repo_relative() -> None:
    autonomy = {relative_path(p) for p in autonomy_source_files()}
    core = {relative_path(p) for p in core_source_files()}
    assert core <= autonomy
    assert all(path.startswith(("src/", "scripts/")) for path in autonomy)
    assert "src/breezy/persistence/autonomy/single_read.py" in core
