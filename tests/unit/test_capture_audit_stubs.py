"""AUT-1 WP5 stage 2a: the stage-2b stub modules pin their public signatures (design S2-R15).

Three parallel builders (W1 fill legs, W2 reconciliation, W3 I/O and orchestration) code against
these signatures, so any change to one is a deliberate edit of this table. Until a builder lands its
module, every public function raises ``NotImplementedError`` and holds only a docstring.
"""

import ast
import importlib
from pathlib import Path
from typing import Any, Final

import pytest

from tests.support.capture_closure_lint import AUT1_WRITE_AUTHORITY

_AN: Final = "breezy.analysis"
_INP: Final = "inp: AuditInputs"

#: ``module -> {qualified name -> "(<args>) -> <returns>"}`` exactly as written in the source.
EXPECTED: Final[dict[str, dict[str, str]]] = {
    # -- W1: fill legs -------------------------------------------------------------------------
    f"{_AN}.capture_audit_fill_legs": {
        "audit_fills": f"({_INP}) -> tuple[FillAudit, ...]",
        "leg_o": f"({_INP}) -> LegResult",
        "leg_f": f"({_INP}) -> LegResult",
        "leg_r6": f"({_INP}) -> LegResult",
        "tape_marks": f"({_INP}) -> tuple[TapeMark, ...]",
    },
    # -- W2: reconciliation --------------------------------------------------------------------
    f"{_AN}.capture_audit_replay": {
        "BootReplay.__init__": "(self) -> None",
        "BootReplay.feed": "(self, event: NodeLogEvent) -> None",
        "BootReplay.results": "(self) -> Mapping[tuple[str, dt.date], ReplayResult]",
        "leg_r1": f"({_INP}) -> LegResult",
        "leg_r2": f"({_INP}) -> LegResult",
        "leg_r3": f"({_INP}) -> LegResult",
    },
    f"{_AN}.capture_audit_log_markers": {
        "MarkerParser.__init__": "(self) -> None",
        "MarkerParser.feed": "(self, event: NodeLogEvent) -> None",
        "MarkerParser.markers": "(self) -> Mapping[tuple[str, dt.date], LogMarkers]",
    },
    f"{_AN}.capture_audit_stream_legs": {
        "leg_r4": f"({_INP}) -> LegResult",
        "leg_r5": f"({_INP}) -> LegResult",
        "leg_r7": f"({_INP}) -> LegResult",
        "leg_w": f"({_INP}) -> tuple[LegResult, tuple[WatchdogGap, ...]]",
        "leg_t": f"({_INP}) -> LegResult",
        "leg_n": f"({_INP}) -> LegResult",
        "positive_control": f"({_INP}) -> LegResult",
    },
}

#: W3 is built (stage 2b): its pinned signatures must still hold, in the module that now defines
#: each name (``RecorderCatalogTape``, ``read_exec_view`` and ``write_scan_cache`` moved to
#: ``capture_audit_tape`` / ``_exec_view`` / ``_cache`` to keep every module under 800 lines; the
#: inputs module re-exports them).
W3_PINNED: Final[dict[str, dict[str, str]]] = {
    f"{_AN}.capture_audit_inputs": {
        "RecorderCatalogTape.__init__": (
            "(self, catalog_root: Path, day: dt.date, instruments: frozenset[str]) -> None"
        ),
        "RecorderCatalogTape.lookup": (
            "(self, frame_kind: str, instrument_id: str, ts_event: int) -> Mapping[str, Any] | None"
        ),
        "RecorderCatalogTape.quote_rows": (
            "(self, instrument_id: str, start_ns: int, end_ns: int) -> Iterable[Mapping[str, Any]]"
        ),
        "RecorderCatalogTape.depth_rows": (
            "(self, instrument_id: str, start_ns: int, end_ns: int) -> Iterable[Mapping[str, Any]]"
        ),
        "RecorderCatalogTape.best_ask_at": (
            "(self, instrument_id: str, ts_ns: int) -> float | None"
        ),
        "boot_census": (
            "(data_root: Path, day: dt.date, *, supervisor_journal: str) -> tuple[str, ...]"
        ),
        "read_exec_view": "(data_root: Path) -> ExecView",
        "gather_inputs": (
            "(data_root: Path, family_id: str, day: dt.date, *, now_ns: int) -> AuditInputs"
        ),
        "write_scan_cache": "(data_root: Path, key: str, body: bytes) -> None",
    },
    f"{_AN}.capture_audit_host": {
        "run_journal": (
            "(template: Sequence[str], since: str, until: str, *, "
            "timeout_s: float=JOURNAL_TIMEOUT_S) -> str"
        ),
        "read_recorder_props": "(data_root: Path, *, now_ns: int) -> RecorderProps",
        "read_ingest_exit_ns": "(data_root: Path, *, now_ns: int) -> int | None",
    },
    f"{_AN}.capture_audit": {
        "audit_day": "(inp: AuditInputs) -> AuditResult",
        "days_to_audit": (
            "(today: dt.date, audited: Mapping[dt.date, DayStatus]) -> tuple[dt.date, ...]"
        ),
        "write_audit_file": "(data_root: Path, result: AuditResult, *, ts_ns: int) -> None",
        "run_audit": (
            "(data_root: Path, family_id: str, today: dt.date, *, now_ns: int, "
            "offer: AlertOffer) -> int"
        ),
    },
    f"{_AN}.capture_audit_cli": {
        "main": "(argv: Sequence[str] | None=None) -> int",
    },
}


#: Modules whose stage-2b builder has landed: their signatures stay pinned, but they are no longer
#: ``NotImplementedError`` stubs (each has its own behaviour tests).
REAL_MODULES: Final[frozenset[str]] = frozenset({f"{_AN}.capture_audit_fill_legs"})
STUB_MODULES: Final[list[str]] = sorted(set(EXPECTED) - REAL_MODULES)


def _source(module: str) -> Path:
    return Path(importlib.import_module(module).__file__ or "")


def _defs(module: str) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(_source(module).read_text(encoding="utf-8"))
    found: dict[str, ast.FunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            found[node.name] = node
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    found[f"{node.name}.{item.name}"] = item
    return found


def _signature(node: ast.FunctionDef) -> str:
    assert node.returns is not None
    return f"({ast.unparse(node.args)}) -> {ast.unparse(node.returns)}"


@pytest.mark.parametrize("module", sorted(EXPECTED))
def test_the_stub_signature_set_is_exactly_the_design_set(module: str) -> None:
    found = {name: _signature(node) for name, node in _defs(module).items()}
    assert found == EXPECTED[module]


@pytest.mark.parametrize("module", STUB_MODULES)
def test_every_stub_has_a_docstring_and_only_raises_not_implemented(module: str) -> None:
    tree = ast.parse(_source(module).read_text(encoding="utf-8"))
    assert ast.get_docstring(tree)
    for name, node in _defs(module).items():
        body = node.body[1:] if ast.get_docstring(node) else node.body
        assert len(body) == 1 and isinstance(body[0], ast.Raise), name
        exc = body[0].exc
        assert isinstance(exc, ast.Call | ast.Name)
        called = exc.func if isinstance(exc, ast.Call) else exc
        assert isinstance(called, ast.Name) and called.id == "NotImplementedError", name


@pytest.mark.parametrize("module", STUB_MODULES)
def test_every_stub_raises_not_implemented_when_called(module: str) -> None:
    mod = importlib.import_module(module)
    for name, node in _defs(module).items():
        owner, _, method = name.rpartition(".")
        target: Any = getattr(mod, owner) if owner else getattr(mod, method)
        fn = getattr(target, method) if owner else target
        nargs = len(node.args.posonlyargs) + len(node.args.args)
        keywords = {arg.arg: None for arg in node.args.kwonlyargs}
        with pytest.raises(NotImplementedError):
            fn(*([None] * nargs), **keywords)


def test_a_landed_module_is_real_and_keeps_its_docstring() -> None:
    for module in sorted(REAL_MODULES):
        tree = ast.parse(_source(module).read_text(encoding="utf-8"))
        assert ast.get_docstring(tree)
        raising = [
            name
            for name, node in _defs(module).items()
            if any(isinstance(n, ast.Raise) and _is_not_implemented(n) for n in ast.walk(node))
        ]
        assert raising == [], module


def _is_not_implemented(node: ast.Raise) -> bool:
    exc = node.exc
    called = exc.func if isinstance(exc, ast.Call) else exc
    return isinstance(called, ast.Name) and called.id == "NotImplementedError"


def test_the_stage_2b_modules_are_not_modules_of_the_stage_2a_model() -> None:
    """Dependency direction: the shared model must not import any stub module."""
    for name in ("capture_audit_model", "capture_audit_input_types", "capture_audit_wire"):
        tree = ast.parse(_source(f"{_AN}.{name}").read_text(encoding="utf-8"))
        imported = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        stubs = [
            m for m in imported if m.startswith(f"{_AN}.capture_audit") and m != f"{_AN}.{name}"
        ]
        shared = {f"{_AN}.capture_audit_model", f"{_AN}.capture_audit_input_types"}
        assert all(m in shared for m in stubs), (name, stubs)


def test_each_stub_module_has_an_authority_row_with_no_write_scope_for_w1_and_w2() -> None:
    rows = {row.module: row for row in AUT1_WRITE_AUTHORITY}
    for module in EXPECTED:
        assert module in rows, module
        assert rows[module].min_calls >= 1, module
    for module in (
        f"{_AN}.capture_audit_fill_legs",
        f"{_AN}.capture_audit_replay",
        f"{_AN}.capture_audit_log_markers",
        f"{_AN}.capture_audit_stream_legs",
    ):
        row = rows[module]
        assert not row.writes and not row.write_imports and not row.argvs and not row.sqlite
    for module in (f"{_AN}.capture_audit_model", f"{_AN}.capture_audit_input_types"):
        assert module in rows, module
    assert f"{_AN}.capture_audit_wire" in rows
    assert f"{_AN}.capture_node_log_markers" in rows
    assert f"{_AN}.capture_node_log_sinks" in rows


_W3_HOME: Final[dict[str, str]] = {
    "RecorderCatalogTape": f"{_AN}.capture_audit_tape",
    "read_exec_view": f"{_AN}.capture_audit_exec_view",
    "write_scan_cache": f"{_AN}.capture_audit_cache",
}


@pytest.mark.parametrize("module", sorted(W3_PINNED))
def test_the_built_w3_modules_keep_every_pinned_signature(module: str) -> None:
    for name, signature in W3_PINNED[module].items():
        owner = name.split(".")[0]
        home = _W3_HOME.get(owner, module)
        assert _signature(_defs(home)[name]) == signature, name
        assert hasattr(importlib.import_module(module), owner), (module, owner)
