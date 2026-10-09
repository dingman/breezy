"""ARCH-0 seam 3c: rung net-position guard and its key/side contracts (AC 22).

``net_position`` and ``entry_guard`` import nothing from ``breezy.domain`` or an adapter, so the
exec client's key and side vocabulary are pinned here by reading the real writer by AST only.
"""

from __future__ import annotations

import ast
import dataclasses
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Literal, get_args, get_type_hints

import pytest

from breezy.adapters.polymarket_us.symbology import no_leg_instrument_id, slug_to_instrument_id
from breezy.domain.instrument_leg import INSTRUMENT_SEPARATOR, NO_LEG_SUFFIX
from breezy.persistence.autonomy import entry_guard, net_position
from breezy.persistence.autonomy.entry_guard import (
    FillIndexAbsent,
    FillRow,
    GuardResult,
    guard_veto_reason,
    leg_instrument_ids,
    rung_has_net_position,
)
from breezy.persistence.autonomy.net_position import LegFill, UnknownSide, net_signed_qty
from breezy.persistence.autonomy.veto import VetoReason
from tests.support.entry_points import SRC_DIR

SUFFIX: Final[str] = ".POLYMARKET_US"
CLIENT_PATH: Final[Path] = SRC_DIR / "breezy/adapters/polymarket_us/exec/client.py"
REAL_SLUGS: Final[tuple[str, ...]] = (
    "aec-nhl-tor-bos-2026-10-03",
    "tsc-kord-high-temp-2026-10-03-gte-70",
    "a",
)
SLUG: Final[str] = "kxhigh-chi-26oct03-t70"
YES_ID: Final[str] = f"{SLUG}{SUFFIX}"
NO_ID: Final[str] = f"{SLUG}^no{SUFFIX}"


class DoubleReader:
    """In-memory ``FillReader``: an index of ids per instrument and a record per id."""

    def __init__(
        self,
        index: Mapping[str, Sequence[str]],
        records: Mapping[str, FillRow],
        *,
        intent_blocks: bool = False,
    ) -> None:
        self._index = index
        self._records = records
        self._intent_blocks = intent_blocks
        self.calls: list[str] = []

    def open_intent_blocks(self) -> bool:
        self.calls.append("open_intent_blocks")
        return self._intent_blocks

    def fill_index(self, instrument_id: str) -> tuple[str, ...]:
        self.calls.append(f"fill_index:{instrument_id}")
        if instrument_id not in self._index:
            raise FillIndexAbsent(instrument_id)
        return tuple(self._index[instrument_id])

    def fill_record(self, venue_order_id: str) -> FillRow:
        self.calls.append(f"fill_record:{venue_order_id}")
        return self._records[venue_order_id]


def _row(side: Literal["BUY", "SELL"], qty: str, ts: int = 1) -> FillRow:
    return FillRow(order_side=side, cumulative_qty=Decimal(qty), ts_event_ns=ts)


def _reader(
    yes: Mapping[str, FillRow] | None = None,
    no: Mapping[str, FillRow] | None = None,
    **kwargs: Any,
) -> DoubleReader:
    """Index each leg's rows under its instrument id. ``None`` leaves the index key absent."""
    index: dict[str, list[str]] = {}
    records: dict[str, FillRow] = {}
    for instrument_id, rows in ((YES_ID, yes), (NO_ID, no)):
        if rows is None:
            continue
        index[instrument_id] = list(rows)
        records.update(rows)
    return DoubleReader(index, records, **kwargs)


def _guard(reader: Any, slug: str = SLUG) -> GuardResult:
    return rung_has_net_position(slug, reader=reader, venue_suffix=SUFFIX)


# --- net_position ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("leg", "side", "expected"),
    [
        ("yes", "BUY", Decimal(5)),
        ("yes", "SELL", Decimal(-5)),
        ("no", "BUY", Decimal(-5)),
        ("no", "SELL", Decimal(5)),
    ],
)
def test_net_signed_qty_signs_each_leg_and_side(leg: str, side: str, expected: Decimal) -> None:
    fill = LegFill(leg=leg, side=side, qty=Decimal(5), ts_event_ns=1)  # type: ignore[arg-type]
    assert net_signed_qty([fill]) == expected


def test_net_signed_qty_no_leg_is_short_yes() -> None:
    """Buying NO lowers the YES-equivalent position; selling it back restores it."""
    buy_no = LegFill("no", "BUY", Decimal(3), 1)
    sell_no = LegFill("no", "SELL", Decimal(3), 2)
    assert net_signed_qty([buy_no]) == Decimal(-3)
    assert net_signed_qty([buy_no, sell_no]) == Decimal(0)


def test_net_signed_qty_empty_is_zero() -> None:
    assert net_signed_qty([]) == Decimal(0)


@pytest.mark.parametrize(("leg", "side"), [("yes", "BUY_SHORT"), ("maybe", "BUY"), ("no", "buy")])
def test_net_signed_qty_unknown_leg_or_side_is_refused(leg: str, side: str) -> None:
    fill = LegFill(leg=leg, side=side, qty=Decimal(1), ts_event_ns=1)  # type: ignore[arg-type]
    with pytest.raises(UnknownSide):
        net_signed_qty([fill])


def test_leg_fill_fields_frozen() -> None:
    fill = LegFill("yes", "BUY", Decimal(1), 7)
    assert [f.name for f in dataclasses.fields(LegFill)] == ["leg", "side", "qty", "ts_event_ns"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        fill.qty = Decimal(2)  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        fill.price = Decimal(2)  # type: ignore[attr-defined]
    doc = LegFill.__doc__ or ""
    assert "netting" in doc.lower()
    hints = get_type_hints(LegFill)
    assert get_args(hints["leg"]) == ("yes", "no")
    assert get_args(hints["side"]) == ("BUY", "SELL")


# --- key contract ---------------------------------------------------------------------------


def test_leg_suffix_equals_instrument_leg() -> None:
    """The guard restates the domain's NO-leg suffix so it never imports ``breezy.domain``."""
    assert f"{INSTRUMENT_SEPARATOR}{NO_LEG_SUFFIX}" == entry_guard.NO_LEG_SYMBOL_SUFFIX


@pytest.mark.parametrize("slug", REAL_SLUGS)
def test_leg_instrument_ids_match_real_symbology(slug: str) -> None:
    expected = (str(slug_to_instrument_id(slug)), str(no_leg_instrument_id(slug)))
    assert leg_instrument_ids(slug, venue_suffix=SUFFIX) == expected


def _parse_client() -> ast.Module:
    return ast.parse(CLIENT_PATH.read_text(encoding="utf-8"))


def _module_assign(tree: ast.Module, name: str) -> ast.AnnAssign:
    for node in tree.body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
        ):
            return node
    raise AssertionError(f"{name} not assigned at module level in {CLIENT_PATH}")


#: The instrument-id expressions the exec client joins onto the fill-index prefix.
_INDEX_KEY_ID_EXPRESSIONS: Final[frozenset[str]] = frozenset(
    {"instrument_id", "record.instrument_id", "instrument.id"}
)


def test_fill_index_key_matches_exec_client_writer() -> None:
    tree = _parse_client()
    namespace = _module_assign(tree, "STATE_KEY_NAMESPACE")
    assert isinstance(namespace.value, ast.Constant)
    assert namespace.value.value == "exec/polymarket_us/"

    prefix = _module_assign(tree, "FILL_INDEX_KEY_PREFIX")
    assert prefix.lineno == 421  # refreshed 2026-10-09 (AMBIG-LATCH-RESUME Phase B)
    assert isinstance(prefix.value, ast.JoinedStr)
    parts = prefix.value.values
    assert len(parts) == 2
    assert isinstance(parts[0], ast.FormattedValue)
    assert ast.unparse(parts[0].value) == "STATE_KEY_NAMESPACE"
    assert isinstance(parts[1], ast.Constant)
    assert parts[1].value == "fill_index/"

    joined: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr) or not node.values:
            continue
        first = node.values[0]
        if not (
            isinstance(first, ast.FormattedValue)
            and ast.unparse(first.value) == "FILL_INDEX_KEY_PREFIX"
        ):
            continue
        assert len(node.values) == 2, ast.unparse(node)
        second = node.values[1]
        assert isinstance(second, ast.FormattedValue), ast.unparse(node)
        joined.append(ast.unparse(second.value))
    assert joined, "no FILL_INDEX_KEY_PREFIX f-string found: the AST scan is blind"
    assert set(joined) <= _INDEX_KEY_ID_EXPRESSIONS

    # The writer keys by ``str(InstrumentId)``; the guard must build those exact strings.
    for slug in REAL_SLUGS:
        yes_id, no_id = leg_instrument_ids(slug, venue_suffix=SUFFIX)
        assert yes_id == str(slug_to_instrument_id(slug))
        assert no_id == str(no_leg_instrument_id(slug))
        assert no_id == f"{slug}^no{SUFFIX}"


def _record_signs(tree: ast.Module) -> dict[str, int]:
    long_only = _module_assign(tree, "LONG_ONLY_SIDE").value
    assert isinstance(long_only, ast.Constant)
    signs = _module_assign(tree, "_RECORD_SIGNS").value
    assert isinstance(signs, ast.Dict)
    out: dict[str, int] = {}
    for key, value in zip(signs.keys, signs.values, strict=True):
        if isinstance(key, ast.Name) and key.id == "LONG_ONLY_SIDE":
            side = long_only.value
        else:
            assert isinstance(key, ast.Constant)
            side = key.value
        assert isinstance(value, ast.Call)
        out[str(side)] = int(ast.literal_eval(value.args[0]))
    return out


def test_fill_row_side_vocabulary_matches_exec_record_signs() -> None:
    signs = _record_signs(_parse_client())
    assert signs == {"BUY": 1, "SELL": -1}
    assert set(signs) == set(get_args(get_type_hints(FillRow)["order_side"]))
    # The YES leg's sign is the record's sign, so netting agrees with the writer's own.
    for side, sign in signs.items():
        fill = LegFill("yes", side, Decimal(1), 1)  # type: ignore[arg-type]
        assert net_signed_qty([fill]) == Decimal(sign)


# --- rung_has_net_position ------------------------------------------------------------------


@pytest.mark.parametrize("reader_kind", ["double"])
def test_rung_net_position_veto_crosses_legs_and_families(reader_kind: str) -> None:
    """Fills from several families share one index; the YES and NO legs net against each other."""
    assert reader_kind == "double"
    both_legs_balanced = _reader(
        yes={"fam_a-1": _row("BUY", "5"), "fam_b-1": _row("BUY", "2")},
        no={"fam_b-2": _row("BUY", "7")},
    )
    assert _guard(both_legs_balanced) is GuardResult.FLAT
    assert guard_veto_reason(_guard(both_legs_balanced)) is None

    no_leg_still_held = _reader(
        yes={"fam_a-1": _row("BUY", "5")},
        no={"fam_b-2": _row("BUY", "3")},
    )
    assert _guard(no_leg_still_held) is GuardResult.HELD
    assert guard_veto_reason(_guard(no_leg_still_held)) is VetoReason.RUNG_NET_POSITION_HELD


def test_negative_net_vetoes() -> None:
    assert _guard(_reader(no={"o1": _row("BUY", "4")})) is GuardResult.HELD


def test_closed_position_is_flat() -> None:
    reader = _reader(yes={"o1": _row("BUY", "4", 1), "o2": _row("SELL", "4", 2)})
    assert _guard(reader) is GuardResult.FLAT


def test_absent_index_on_both_legs_is_flat() -> None:
    reader = _reader()
    assert _guard(reader) is GuardResult.FLAT
    assert reader.calls == ["open_intent_blocks", f"fill_index:{YES_ID}", f"fill_index:{NO_ID}"]


def test_absent_index_on_one_leg_counts_as_no_fills() -> None:
    assert _guard(_reader(yes={"o1": _row("BUY", "1")})) is GuardResult.HELD


@pytest.mark.parametrize("leg", ["yes", "no"])
def test_empty_index_is_unreadable(leg: str) -> None:
    reader = _reader(**{leg: {}})
    assert _guard(reader) is GuardResult.UNREADABLE


def test_entry_guard_unreadable_index_vetoes() -> None:
    class BrokenReader(DoubleReader):
        def fill_index(self, instrument_id: str) -> tuple[str, ...]:
            raise OSError("exec store unreadable")

    result = _guard(BrokenReader({}, {}))
    assert result is GuardResult.UNREADABLE
    assert guard_veto_reason(result) is VetoReason.RUNG_NET_POSITION_HELD


def test_open_intent_is_unreadable_and_checked_first() -> None:
    reader = _reader(yes={"o1": _row("BUY", "1")}, intent_blocks=True)
    assert _guard(reader) is GuardResult.UNREADABLE
    assert reader.calls == ["open_intent_blocks"]


def test_open_intent_is_checked_before_the_slug_is_validated() -> None:
    reader = _reader(intent_blocks=True)
    assert _guard(reader, slug="") is GuardResult.UNREADABLE
    assert reader.calls == ["open_intent_blocks"]


@pytest.mark.parametrize("slug", ["", ".", "^", "a.b", "a^no", "^no"])
def test_bad_slug_is_unreadable(slug: str) -> None:
    reader = _reader()
    assert _guard(reader, slug=slug) is GuardResult.UNREADABLE
    assert not [c for c in reader.calls if c.startswith("fill_")]


@pytest.mark.parametrize("slug", ["", ".", "^", "a.b", "a^no"])
def test_leg_instrument_ids_refuse_bad_slugs(slug: str) -> None:
    with pytest.raises(ValueError, match="slug"):
        leg_instrument_ids(slug, venue_suffix=SUFFIX)


@pytest.mark.parametrize(
    "break_reader",
    [
        lambda r: setattr(r, "open_intent_blocks", _raiser(RuntimeError("boom"))),
        lambda r: setattr(r, "fill_record", _raiser(KeyError("o1"))),
        lambda r: setattr(r, "fill_index", lambda _id: 5),
    ],
    ids=["intent", "record", "index_not_iterable"],
)
def test_guard_body_exception_is_unreadable(break_reader: Callable[[DoubleReader], None]) -> None:
    reader = _reader(yes={"o1": _row("BUY", "1")})
    break_reader(reader)
    assert _guard(reader) is GuardResult.UNREADABLE


def test_unknown_record_side_is_unreadable() -> None:
    bad = FillRow(order_side="BUY_SHORT", cumulative_qty=Decimal(1), ts_event_ns=1)  # type: ignore[arg-type]
    assert _guard(_reader(yes={"o1": bad})) is GuardResult.UNREADABLE


def _raiser(exc: Exception) -> Callable[..., Any]:
    def raise_it(*_args: Any, **_kwargs: Any) -> Any:
        raise exc

    return raise_it


def test_guard_veto_reason_maps_every_result() -> None:
    assert guard_veto_reason(GuardResult.HELD) is VetoReason.RUNG_NET_POSITION_HELD
    assert guard_veto_reason(GuardResult.UNREADABLE) is VetoReason.RUNG_NET_POSITION_HELD
    assert guard_veto_reason(GuardResult.FLAT) is None


def test_guard_docstring_states_the_venue_global_intent_scope() -> None:
    assert "venue-global" in (rung_has_net_position.__doc__ or "").lower()


def test_fill_row_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _row("BUY", "1").cumulative_qty = Decimal(2)  # type: ignore[misc]


def test_modules_import_nothing_from_domain_or_adapters() -> None:
    for module in (net_position, entry_guard):
        tree = ast.parse(Path(str(module.__file__)).read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not [m for m in imported if m.startswith(("breezy.domain", "breezy.adapters"))]
