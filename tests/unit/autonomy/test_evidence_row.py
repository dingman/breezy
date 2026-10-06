"""F7b-core: the sealed evidence loader (`analysis/autonomy/evidence_row.py`), FQ-R37 / FQ-R54 M2.

Honesty (F7B-R9): the module-private token and the AST bans are an ACCIDENT GUARD, not a security
boundary -- `_TOKEN` is importable. Real provenance comes from the store-kind-derived reader,
`ref_ts < take_ts` at load and the reviewed consumer table.

F7B-R8: `load_evidence_rows(store_kind)` takes only the store kind; each reader resolves its own
root when its owner WP wires it. Tests patch `evidence_row._READERS` and the loader must read that
module global at call time (F7B-R28).
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import inspect
import pickle
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any, Final

import pytest

from breezy.analysis.autonomy import evidence_row
from breezy.analysis.autonomy.evidence_row import (
    STORE_CLASS,
    EvidenceClass,
    EvidenceRefused,
    EvidenceRow,
    EvidenceUnavailable,
    LoadedEvidence,
    RawEvidence,
    StoreKind,
    is_sealed_row,
    load_evidence_rows,
    require_loaded_evidence,
)

SRC: Final = Path(__file__).resolve().parents[3] / "src" / "breezy"
EVIDENCE_SRC: Final = SRC / "analysis" / "autonomy" / "evidence_row.py"


def raw_row(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "evidence_tag": "shadow",
        "climate_day": "2026-03-01",
        "decision_ts_ns": 2_000,
        "ref_ts_ns": 1_000,
        "station": "KNYC",
        "rung_id": "r1",
        "side": "yes",
        "be": "0.3760128",
        "raw_ask": "0.35",
        "p_model": "0.5",
        "h": 1,
        "void": False,
    }
    return {**base, **over}


def patch_reader(
    monkeypatch: pytest.MonkeyPatch,
    kind: StoreKind,
    rows: list[dict[str, object]],
    covered: tuple[str, ...] = ("2026-03-01",),
) -> None:
    def reader() -> RawEvidence:
        return RawEvidence(rows=tuple(rows), covered_days=covered)

    monkeypatch.setattr(evidence_row, "_READERS", MappingProxyType({kind: reader}))


def loaded(monkeypatch: pytest.MonkeyPatch, **over: object) -> LoadedEvidence:
    patch_reader(monkeypatch, StoreKind.NODE_C1_SHADOW_TAKES, [raw_row(**over)])
    return load_evidence_rows(StoreKind.NODE_C1_SHADOW_TAKES)


# ------------------------------------------------------------------ AST ban scanners


def _is_object_attr(node: ast.expr, attr: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == attr
        and isinstance(node.value, ast.Name)
        and node.value.id == "object"
    )


def forgery_violations(source: str, *, in_evidence_module: bool) -> list[str]:
    """`object.__new__(EvidenceRow|LoadedEvidence)`, and `object.__setattr__` on anything but
    `self` (or at all inside `evidence_row.py`)."""
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if _is_object_attr(node.func, "__new__") and node.args:
            first = node.args[0]
            if isinstance(first, ast.Name) and first.id in {"EvidenceRow", "LoadedEvidence"}:
                out.append(f"object.__new__({first.id})")
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "__new__"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in {"EvidenceRow", "LoadedEvidence"}
        ):
            out.append(f"{node.func.value.id}.__new__")
        if _is_object_attr(node.func, "__setattr__"):
            target = node.args[0] if node.args else None
            is_self = isinstance(target, ast.Name) and target.id == "self"
            if in_evidence_module or not is_self:
                out.append("object.__setattr__")
    return out


def _pickle_names(tree: ast.AST) -> tuple[set[str], set[str]]:
    modules, funcs = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {a.asname or a.name for a in node.names if a.name == "pickle"}
        elif isinstance(node, ast.ImportFrom) and node.module == "pickle":
            funcs |= {a.asname or a.name for a in node.names}
    return modules, funcs


_PICKLE_LOADERS: Final = {"load", "loads", "Unpickler"}


def pickle_setstate_violations(source: str, *, in_evidence_module: bool) -> list[str]:
    tree = ast.parse(source)
    modules, funcs = _pickle_names(tree)
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if (
                isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name)
                and f.value.id in modules | {"pickle"}
                and f.attr in _PICKLE_LOADERS
            ):
                out.append(f"pickle.{f.attr}")
            if isinstance(f, ast.Name) and f.id in funcs and f.id in _PICKLE_LOADERS:
                out.append(f"pickle.{f.id}")
        if isinstance(node, ast.FunctionDef) and node.name == "__setstate__":
            only_raise = (
                in_evidence_module
                and len(node.body) == 1
                and isinstance(node.body[0], ast.Raise)
                and isinstance(node.body[0].exc, ast.Call)
                and isinstance(node.body[0].exc.func, ast.Name)
                and node.body[0].exc.func.id == "TypeError"
            )
            if not only_raise:
                out.append("__setstate__")
    return out


def _src_files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


# ------------------------------------------------------------------ loader contract


def test_evidence_row_single_loader_contract() -> None:
    """`EvidenceRow(...)` is built only inside `evidence_row.py`; the loader is the constructor."""
    for path in _src_files():
        if path == EVIDENCE_SRC:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"EvidenceRow", "LoadedEvidence"}, path
    assert callable(load_evidence_rows)
    with pytest.raises(TypeError):
        EvidenceRow(  # type: ignore[call-arg]
            evidence_class=EvidenceClass.SHADOW,
            climate_day=date(2026, 3, 1),
            decision_ts_ns=2,
            ref_ts_ns=1,
            station="K",
            rung_id="r",
            side="yes",
            be=Decimal("0.4"),
            raw_ask=Decimal("0.3"),
            p_model=Decimal("0.5"),
            h=1,
            void=False,
        )


def test_load_evidence_rows_accepts_no_path_argument() -> None:
    params = inspect.signature(load_evidence_rows).parameters
    assert list(params) == ["store_kind"]
    assert not any("path" in name.lower() or "root" in name.lower() for name in params)
    for p in params.values():
        assert p.annotation not in (Path, "Path", "str | Path", Path | str)


def test_load_reads_the_patched_readers_global_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F7B-R8 / R28: the loader looks `_READERS` up by global name when it is CALLED."""
    tree = ast.parse(EVIDENCE_SRC.read_text(encoding="utf-8"))
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "load_evidence_rows"
    )
    assert not fn.args.defaults and not fn.args.kw_defaults  # no default-argument binding
    uses = [n for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == "_READERS"]
    assert uses and all(isinstance(n.ctx, ast.Load) for n in uses)

    # Planted case: a default-argument binding is captured at definition time and would NOT see
    # the patch; the real loader does.
    def planted(store_kind: StoreKind, readers: Mapping[Any, Any] = evidence_row._READERS) -> Any:
        return readers[store_kind]()

    patch_reader(monkeypatch, StoreKind.NODE_C1_SHADOW_TAKES, [raw_row()])
    got = load_evidence_rows(StoreKind.NODE_C1_SHADOW_TAKES)
    assert len(got.rows) == 1
    with pytest.raises(EvidenceUnavailable):
        planted(StoreKind.NODE_C1_SHADOW_TAKES)  # the stale binding still raises the default


def test_store_kind_is_a_closed_mapping() -> None:
    assert dict(STORE_CLASS) == {
        StoreKind.C2_LABEL_STORE: EvidenceClass.LIVE,
        StoreKind.NODE_C1_SHADOW_TAKES: EvidenceClass.SHADOW,
        StoreKind.HARNESS: EvidenceClass.BACKTEST,
        StoreKind.FS_REPLAY: EvidenceClass.BACKTEST,
    }
    assert isinstance(STORE_CLASS, MappingProxyType)
    for bad in ("nope", "", None, 3):
        with pytest.raises(EvidenceRefused, match="unknown_store_kind"):
            load_evidence_rows(bad)  # type: ignore[arg-type]


def test_every_store_reader_refuses_until_its_owner_lands() -> None:
    reasons = set()
    for kind in StoreKind:
        with pytest.raises(EvidenceUnavailable) as err:
            load_evidence_rows(kind)
        reasons.add(err.value.reason)
    assert len(reasons) == len(StoreKind)  # each refusal is named and distinct
    assert all(r.endswith("_reader_not_wired") for r in reasons)
    assert isinstance(evidence_row._READERS, MappingProxyType)
    assert set(evidence_row._READERS) == set(StoreKind)


def test_loader_returns_sealed_loaded_evidence_and_consumers_require_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ev = loaded(monkeypatch)
    assert type(ev) is LoadedEvidence
    assert ev.store_kind is StoreKind.NODE_C1_SHADOW_TAKES
    assert ev.evidence_class is EvidenceClass.SHADOW
    assert isinstance(ev.rows, tuple) and type(ev.rows[0]) is EvidenceRow
    assert ev.covered_days == frozenset({date(2026, 3, 1)})
    row = ev.rows[0]
    assert (row.be, row.raw_ask, row.p_model) == (
        Decimal("0.3760128"),
        Decimal("0.35"),
        Decimal("0.5"),
    )
    assert row.climate_day == date(2026, 3, 1) and row.h == 1 and row.void is False
    assert require_loaded_evidence(ev) is ev
    for not_loaded in (ev.rows, list(ev.rows), None, SimpleNamespace(rows=ev.rows)):
        with pytest.raises(EvidenceRefused, match="evidence_not_loaded"):
            require_loaded_evidence(not_loaded)


# ------------------------------------------------------------------ sealing


def test_evidence_row_cannot_be_forged_via_replace_or_pickle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = loaded(monkeypatch).rows[0]
    with pytest.raises((ValueError, TypeError)):
        dataclasses.replace(row, station="KSFO")  # type: ignore[call-arg]  # InitVar, no default
    with pytest.raises((ValueError, TypeError)):
        copy.replace(row, station="KSFO")
    with pytest.raises(TypeError):
        pickle.dumps(row)
    with pytest.raises(TypeError):
        row.__setstate__({})
    with pytest.raises(dataclasses.FrozenInstanceError):
        row.station = "KSFO"  # type: ignore[misc]


def test_evidence_row_copy_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    ev = loaded(monkeypatch)
    for obj in (ev.rows[0], ev):
        with pytest.raises(TypeError):
            copy.copy(obj)
        with pytest.raises(TypeError):
            copy.deepcopy(obj)
        with pytest.raises(TypeError):
            obj.__reduce__()
        with pytest.raises(TypeError):
            obj.__reduce_ex__(4)


def test_evidence_row_is_final_subclass_refused() -> None:
    with pytest.raises(TypeError):

        class Sub(EvidenceRow):  # type: ignore[misc]
            pass

    with pytest.raises(TypeError):

        class SubLoaded(LoadedEvidence):  # type: ignore[misc]
            pass

    assert getattr(EvidenceRow, "__final__", False) is True
    assert getattr(LoadedEvidence, "__final__", False) is True


def test_evidence_row_object_setattr_banned_by_ast() -> None:
    for path in _src_files():
        src = path.read_text(encoding="utf-8")
        assert forgery_violations(src, in_evidence_module=path == EVIDENCE_SRC) == [], path
    assert forgery_violations("object.__setattr__(row, 'h', 0)", in_evidence_module=False)
    assert forgery_violations("object.__setattr__(self, 'h', 0)", in_evidence_module=True)
    assert not forgery_violations("object.__setattr__(self, 'h', 0)", in_evidence_module=False)


def test_evidence_row_object_new_path_refused_by_consumers_and_banned_by_ast() -> None:
    forged_row = object.__new__(EvidenceRow)  # the forgery the AST ban flags at the call site
    forged_loaded = object.__new__(LoadedEvidence)
    assert type(forged_row) is EvidenceRow
    assert is_sealed_row(forged_row) is False  # the type matches but the seal is absent
    with pytest.raises(EvidenceRefused, match="evidence_not_loaded"):
        require_loaded_evidence(forged_loaded)
    assert forgery_violations("x = object.__new__(EvidenceRow)", in_evidence_module=False) == [
        "object.__new__(EvidenceRow)"
    ]
    assert forgery_violations("x = object.__new__(LoadedEvidence)", in_evidence_module=False)
    assert forgery_violations("x = EvidenceRow.__new__(EvidenceRow)", in_evidence_module=False)


def test_forged_rows_inside_a_loaded_container_are_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ev = loaded(monkeypatch)
    forged = object.__new__(EvidenceRow)
    bad = object.__new__(LoadedEvidence)
    # even with plausible-looking attributes, the container's own seal is absent
    bad.__dict__.update(
        {"store_kind": ev.store_kind, "rows": (forged,), "covered_days": frozenset()}
    )
    with pytest.raises(EvidenceRefused, match="evidence_not_loaded"):
        require_loaded_evidence(bad)


def test_consumers_require_exact_type_evidence_row(monkeypatch: pytest.MonkeyPatch) -> None:
    row = loaded(monkeypatch).rows[0]

    @dataclasses.dataclass(frozen=True)
    class Lookalike:
        station: str = "KNYC"

    assert is_sealed_row(row) is True
    assert is_sealed_row(Lookalike()) is False
    assert is_sealed_row(SimpleNamespace(**dataclasses.asdict(row))) is False
    assert is_sealed_row(None) is False
    # a duck-typed row cannot hide inside a real LoadedEvidence: the loader builds every row
    ev = loaded(monkeypatch)
    assert all(type(r) is EvidenceRow and is_sealed_row(r) for r in ev.rows)


def test_no_pickle_load_or_setstate_in_analysis_autonomy_ast() -> None:
    """Verify-first (F7B-R9): the existing `analysis/autonomy/*` modules are clean, and a
    `__setstate__` is allowed only in `evidence_row.py` as a single `raise TypeError(...)`."""
    root = SRC / "analysis" / "autonomy"
    for path in root.rglob("*.py"):
        found = pickle_setstate_violations(
            path.read_text(encoding="utf-8"), in_evidence_module=path == EVIDENCE_SRC
        )
        assert found == [], path
    assert "__setstate__" in EVIDENCE_SRC.read_text(encoding="utf-8")  # the refusing one exists

    planted = [
        "import pickle\nx = pickle.loads(b'')",
        "import pickle as pk\nx = pk.load(f)",
        "from pickle import Unpickler\nx = Unpickler(f)",
        "class A:\n    def __setstate__(self, s):\n        self.x = s",
        # a raising __setstate__ is still refused outside evidence_row.py
    ]
    for src in planted:
        assert pickle_setstate_violations(src, in_evidence_module=False), src
    non_raising = "class A:\n    def __setstate__(self, s):\n        self.x = s"
    assert pickle_setstate_violations(non_raising, in_evidence_module=True) == ["__setstate__"]
    raising = "class A:\n    def __setstate__(self, s):\n        raise TypeError('sealed')"
    assert pickle_setstate_violations(raising, in_evidence_module=True) == []
    assert pickle_setstate_violations(raising, in_evidence_module=False) == ["__setstate__"]
    raising_more = (
        "class A:\n    def __setstate__(self, s):\n        s.x = 1\n        raise TypeError('x')"
    )
    assert pickle_setstate_violations(raising_more, in_evidence_module=True) == ["__setstate__"]


def test_the_module_docstring_states_the_token_is_an_accident_guard() -> None:
    doc = " ".join((evidence_row.__doc__ or "").split())
    assert "accident guard" in doc.lower() and "not a security boundary" in doc
    assert "_TOKEN" in doc and "importable" in doc


# ------------------------------------------------------------------ validate-and-seal at load


def test_ref_ts_lt_take_ts_enforced_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    for ref in (2_000, 2_001):  # equal and later are both refused
        patch_reader(monkeypatch, StoreKind.NODE_C1_SHADOW_TAKES, [raw_row(ref_ts_ns=ref)])
        with pytest.raises(EvidenceRefused, match="ref_ts_not_before_take_ts"):
            load_evidence_rows(StoreKind.NODE_C1_SHADOW_TAKES)
    patch_reader(monkeypatch, StoreKind.NODE_C1_SHADOW_TAKES, [raw_row(ref_ts_ns=1_999)])
    assert len(load_evidence_rows(StoreKind.NODE_C1_SHADOW_TAKES).rows) == 1


def test_untagged_row_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    no_tag = raw_row()
    del no_tag["evidence_tag"]
    for row, reason in (
        (no_tag, "untagged_row"),
        (raw_row(evidence_tag=None), "untagged_row"),
        (raw_row(evidence_tag="gold"), "unknown_tag"),
        (raw_row(evidence_tag="live"), "tag_mismatch"),  # a live tag in a shadow store
        (raw_row(evidence_tag="backtest"), "tag_mismatch"),
    ):
        patch_reader(monkeypatch, StoreKind.NODE_C1_SHADOW_TAKES, [row])
        with pytest.raises(EvidenceRefused, match=reason):
            load_evidence_rows(StoreKind.NODE_C1_SHADOW_TAKES)


def test_row_shape_and_numeric_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    extra = raw_row(surprise=1)
    missing = raw_row()
    del missing["raw_ask"]
    cases: list[tuple[dict[str, object], str]] = [
        (extra, "unexpected_key"),
        (missing, "missing_key"),
        (raw_row(be=0.376), "wrong_type"),  # a float is refused: Decimal at the seal
        (raw_row(be=True), "wrong_type"),
        (raw_row(be="NaN"), "bad_number"),
        (raw_row(be="0"), "bad_number"),
        (raw_row(raw_ask="1.5"), "bad_number"),
        (raw_row(p_model="-0.1"), "bad_number"),
        (raw_row(h=2), "bad_outcome"),
        (raw_row(h=True), "bad_outcome"),
        (raw_row(void=True, h=1), "void_with_outcome"),
        (raw_row(void="yes"), "wrong_type"),
        (raw_row(climate_day="2026-13-40"), "bad_date"),
        (raw_row(decision_ts_ns="2000"), "wrong_type"),
        (raw_row(station=""), "bad_key"),
        (raw_row(station="KNYC\u00e9"), "bad_key"),
    ]
    for row, reason in cases:
        patch_reader(monkeypatch, StoreKind.NODE_C1_SHADOW_TAKES, [row])
        with pytest.raises(EvidenceRefused, match=reason):
            load_evidence_rows(StoreKind.NODE_C1_SHADOW_TAKES)
    patch_reader(monkeypatch, StoreKind.NODE_C1_SHADOW_TAKES, [["not", "a", "mapping"]])  # type: ignore[list-item]
    with pytest.raises(EvidenceRefused, match="wrong_type"):
        load_evidence_rows(StoreKind.NODE_C1_SHADOW_TAKES)


def test_unsettled_and_void_rows_load_and_are_judged_downstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The loader keeps `h=None` (unsettled) and `void=True` as they are; R23 refuses downstream."""
    ev = loaded(monkeypatch, h=None)
    assert ev.rows[0].h is None and ev.rows[0].void is False
    ev = loaded(monkeypatch, h=None, void=True)
    assert ev.rows[0].void is True


def test_bad_covered_day_and_reader_output_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_reader(monkeypatch, StoreKind.NODE_C1_SHADOW_TAKES, [raw_row()], covered=("junk",))
    with pytest.raises(EvidenceRefused, match="bad_date"):
        load_evidence_rows(StoreKind.NODE_C1_SHADOW_TAKES)
    monkeypatch.setattr(
        evidence_row,
        "_READERS",
        MappingProxyType({StoreKind.NODE_C1_SHADOW_TAKES: lambda: [raw_row()]}),
    )
    with pytest.raises(EvidenceRefused, match="reader_output"):
        load_evidence_rows(StoreKind.NODE_C1_SHADOW_TAKES)
    monkeypatch.setattr(evidence_row, "_READERS", MappingProxyType({}))
    with pytest.raises(EvidenceUnavailable):
        load_evidence_rows(StoreKind.NODE_C1_SHADOW_TAKES)
