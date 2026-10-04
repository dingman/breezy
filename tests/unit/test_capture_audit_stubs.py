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

#: W3 is built (stage 2b): the EXACT public surface of each module that now defines a W3 name, so
#: neither a new public function nor a changed signature slips in unreviewed (S2-R42). The names
#: ``RecorderCatalogTape``, ``read_exec_view`` and ``write_scan_cache`` moved to
#: ``capture_audit_tape`` / ``_exec_view`` / ``_cache`` to keep every module under 800 lines; the
#: inputs module re-exports them (``W3_REEXPORTED``).
W3_PINNED: Final[dict[str, dict[str, str]]] = {
    f"{_AN}.capture_audit_inputs": {
        "boot_census": (
            "(data_root: Path, day: dt.date, *, supervisor_journal: str) -> tuple[str, ...]"
        ),
        "gather_inputs": (
            "(data_root: Path, family_id: str, day: dt.date, *, now_ns: int) -> AuditInputs"
        ),
        "list_names": "(root: Path, rel: Sequence[str]) -> list[str]",
    },
    f"{_AN}.capture_audit_tape": {
        "catalog_instruments": "(catalog_root: Path, day: dt.date) -> frozenset[str]",
        "RecorderCatalogTape.__init__": (
            "(self, catalog_root: Path, day: dt.date, instruments: frozenset[str]) -> None"
        ),
        "RecorderCatalogTape.instruments": "(self) -> frozenset[str]",
        "RecorderCatalogTape.active_instruments": (
            "(self, start_ns: int, end_ns: int) -> frozenset[str]"
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
    },
    f"{_AN}.capture_audit_exec_view": {
        "read_exec_view": "(data_root: Path) -> ExecView",
    },
    f"{_AN}.capture_audit_cache": {
        "cache_dir_parts": "() -> tuple[str, ...]",
        "encode_result": "(result: LogResult, key: str) -> bytes",
        "ensure_cache_dir": "(data_root: Path) -> None",
        "log_key": "(path: Path) -> str",
        "read_scan_cache": "(data_root: Path, key: str) -> LogResult | None",
        "reducer_source_hash": "() -> str",
        "reducer_source_hash_of": "(source_dir: Path) -> str",
        "write_scan_cache": "(data_root: Path, key: str, body: bytes) -> None",
    },
    f"{_AN}.capture_audit_host": {
        "journal_slot": "(epoch_s: int) -> str",
        "parse_recorder_journal": "(text: str) -> tuple[RecorderJournalEntry, ...]",
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
        "error_cause_set": "(result: AuditResult) -> frozenset[str]",
        "error_result": (
            "(day: dt.date, family_id: str, cause: str, *, pre_capture: bool) -> AuditResult"
        ),
        "write_audit_file": "(data_root: Path, result: AuditResult, *, ts_ns: int) -> None",
        "run_audit": (
            "(data_root: Path, family_id: str, today: dt.date, *, now_ns: int, "
            "offer: AlertOffer) -> int"
        ),
    },
    f"{_AN}.capture_audit_cli": {
        "families_by_construction": (
            "(data_root: Path, explicit: Sequence[str]) -> tuple[str, ...]"
        ),
        "main": "(argv: Sequence[str] | None=None) -> int",
    },
}

#: Names the inputs module still exports although another module defines them.
W3_REEXPORTED: Final[tuple[str, ...]] = (
    "RecorderCatalogTape",
    "read_exec_view",
    "write_scan_cache",
)

#: ``min_calls`` floors a builder raised in ``AUT1_WRITE_AUTHORITY``; a floor may be raised, never
#: lowered. Every other pinned module stays at exactly 1 (S2-R42).
RAISED_FLOORS: Final[dict[str, int]] = {
    f"{_AN}.capture_audit_fill_legs": 150,
    f"{_AN}.capture_audit_replay": 160,
    f"{_AN}.capture_audit_log_markers": 13,
    f"{_AN}.capture_audit_stream_legs": 110,
    f"{_AN}.capture_audit_inputs": 250,
    f"{_AN}.capture_audit_tape": 80,
    f"{_AN}.capture_audit_exec_view": 65,
    f"{_AN}.capture_audit_cache": 70,
    f"{_AN}.capture_audit_host": 70,
    f"{_AN}.capture_audit": 150,
    f"{_AN}.capture_audit_cli": 22,
}


#: Modules whose stage-2b builder has landed: their signatures stay pinned, but they are no longer
#: ``NotImplementedError`` stubs (each has its own behaviour tests). W2 landed the reconciliation
#: modules (design S2-R15).
W2_REAL: Final[frozenset[str]] = frozenset(
    {
        f"{_AN}.capture_audit_replay",
        f"{_AN}.capture_audit_log_markers",
        f"{_AN}.capture_audit_stream_legs",
    }
)
REAL_MODULES: Final[frozenset[str]] = frozenset({f"{_AN}.capture_audit_fill_legs"}) | W2_REAL
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


def test_each_pinned_module_has_an_authority_row_with_its_floor() -> None:
    rows = {row.module: row for row in AUT1_WRITE_AUTHORITY}
    for module in {*EXPECTED, *W3_PINNED}:
        assert module in rows, module
        if module in RAISED_FLOORS:
            assert rows[module].min_calls >= RAISED_FLOORS[module], module
        else:
            assert rows[module].min_calls == 1, module
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


def _public(module: str) -> dict[str, str]:
    """The public surface: every top-level and method definition not starting with an underscore
    (``__init__`` counts)."""
    return {
        name: _signature(node)
        for name, node in _defs(module).items()
        if not name.rpartition(".")[2].startswith("_") or name.endswith(".__init__")
    }


@pytest.mark.parametrize("module", sorted(W3_PINNED))
def test_the_built_w3_modules_expose_exactly_the_pinned_surface(module: str) -> None:
    assert _public(module) == W3_PINNED[module]


def test_the_inputs_module_still_exports_the_names_that_moved_out_of_it() -> None:
    inputs = importlib.import_module(f"{_AN}.capture_audit_inputs")
    for name in W3_REEXPORTED:
        assert hasattr(inputs, name), name


@pytest.mark.parametrize("module", sorted(W2_REAL))
def test_the_w2_modules_are_real_implementations(module: str) -> None:
    """A W2 module keeps its docstring and its pinned signatures but no function body is a stub."""
    tree = ast.parse(_source(module).read_text(encoding="utf-8"))
    assert ast.get_docstring(tree)
    for name, node in _defs(module).items():
        body = node.body[1:] if ast.get_docstring(node) else node.body
        raises = [n for n in body if isinstance(n, ast.Raise)]
        assert not (len(body) == 1 and raises), f"{name} is still a stub"
    assert "NotImplementedError" not in _source(module).read_text(encoding="utf-8")
