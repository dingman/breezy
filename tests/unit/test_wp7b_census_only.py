"""Card A ``--census-only`` guards.

Synthetic fixtures only: no catalog, no network, no real store.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import socket
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

import pyarrow.parquet as pq
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts" / "analysis").as_posix())

import wp7b_census as census  # type: ignore[import-not-found]
from h4_preliminary_economic_read import parse_rung  # type: ignore[import-not-found]
from wp7b_market_as_forecaster import (  # type: ignore[import-not-found]
    assert_complete_partition,
    main,
)

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.domain.exec_intent import (
    FILL_BY_FINGERPRINT_KEY_PREFIX,
    FILL_KEY_PREFIX,
    utc_day_for_ns,
)
from breezy.runtime.submit_intent import (
    CURRENT_INTENT_KEY,
    SubmitIntent,
    SubmitIntentState,
    history_key,
)
from breezy.runtime.submit_intent_slots import encode_v2

_NS = 1_000_000_000
DAY = dt.date(2026, 9, 22)
TARGET = "2026-09-21T18:00:00+00:00"
LOW_ID = "tc-temp-nychigh-2026-09-22-lt76f.POLYMARKET_US"
HIGH_ID = "tc-temp-nychigh-2026-09-22-gte76f.POLYMARKET_US"
NO_ID = "tc-temp-nychigh-2026-09-22-lt76f^no.POLYMARKET_US"
BASE = "tc-temp-nychigh-2026-09-22-lt76f"
INTENT_ID = "ab" * 16
FINGERPRINT = "cd" * 32
CREATED_NS = 1_761_955_200 * _NS
VENUE_ORDER_ID = "VENUE-ORDER-SHOULD-NOT-APPEAR"
CLIENT_ORDER_ID = "CLIENT-ORDER-SHOULD-NOT-APPEAR"


def _ns(iso: str) -> int:
    value = dt.datetime.fromisoformat(iso)
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    delta = value.astimezone(dt.UTC) - dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
    return delta.days * 86_400 * _NS + delta.seconds * _NS + delta.microseconds * 1_000


def _quote(
    iso: str,
    ask: str | None,
    bid: str | None,
    *,
    ask_size: str = "1",
    bid_size: str = "1",
) -> census.Quote:
    return census.Quote(
        ts_ns=_ns(iso),
        ask=None if ask is None else Decimal(ask),
        ask_size=Decimal(ask_size),
        bid=None if bid is None else Decimal(bid),
        bid_size=Decimal(bid_size),
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _freeze(directory: Path, sha: str, *, status: str = "FROZEN") -> Path:
    path = directory / "FREEZE_card_a.txt"
    path.write_text(
        "\n".join(
            (
                "prereg_path docs/plans/backlog/STRAT_DESIGN_2026-10-31/prereg_card_a.md",
                f"prereg_sha256 {sha}",
                "frozen_at_commit abcdef0",
                "frozen_at_utc 2026-10-31T00:00:00Z",
                "looks_allowed 1",
                f"status {status}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _arm(
    tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    status: str = "FROZEN",
    store: Path | None = None,
) -> str:
    prereg = tmp / "prereg.md"
    prereg.write_text("card A frozen rule\n", encoding="utf-8")
    digest = _sha(prereg)
    freeze = _freeze(tmp, digest, status=status)
    out = tmp / "out"
    out.mkdir()
    catalog = tmp / "catalog"
    catalog.mkdir()
    monkeypatch.setattr(census, "PREREG_PATH", prereg)
    monkeypatch.setattr(census, "FREEZE_PATH", freeze)
    monkeypatch.setattr(census, "OUTPUT_DIR", out)
    monkeypatch.setattr(census, "CATALOG", catalog)
    if store is not None:
        monkeypatch.setenv("POLYMARKET_US_EXEC_STATE_DB", str(store))
    return digest


def _empty_store(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE state (key TEXT PRIMARY KEY, value BLOB NOT NULL)")
    connection.commit()
    connection.close()


def _insert(path: Path, rows: list[tuple[str, bytes]]) -> None:
    connection = sqlite3.connect(path)
    connection.executemany("INSERT INTO state (key, value) VALUES (?, ?)", rows)
    connection.commit()
    connection.close()


def _intent(*, slug: str | None) -> bytes:
    return SubmitIntent(
        intent_id=INTENT_ID,
        fingerprint=FINGERPRINT,
        created_ns=CREATED_NS,
        state=SubmitIntentState.OPEN,
        retired_ns=None,
        retirement_reason=None,
        slug=slug,
    ).to_bytes()


def _fill(instrument_id: str) -> bytes:
    return DurableFillRecord(
        venue_order_id=VENUE_ORDER_ID,
        client_order_id=CLIENT_ORDER_ID,
        instrument_id=instrument_id,
        order_side="BUY",
        cumulative_qty=Decimal(1),
        cumulative_cost=Decimal("0.40"),
        cumulative_fee=Decimal("0.00"),
        fee_reconciled=False,
        ts_event=CREATED_NS,
    ).to_bytes()


def _listing(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


def test_sha_mismatch_refuses_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _arm(tmp_path, monkeypatch)
    out = tmp_path / "out"
    before = _listing(out)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--census-only",
                "--prereg-sha",
                "0" * 64,
                "--output",
                str(tmp_path / "ignored.md"),
            ]
        )
    assert exc.value.code == 2
    assert "prereg sha256 mismatch" in capsys.readouterr().err
    assert _listing(out) == before


def test_pending_or_missing_freeze_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    digest = _arm(tmp_path, monkeypatch, status="PENDING")
    with pytest.raises(SystemExit) as pending:
        main(["--census-only", "--prereg-sha", digest, "--output", str(tmp_path / "a.md")])
    assert pending.value.code == 2
    assert "PENDING" in capsys.readouterr().err
    monkeypatch.setattr(census, "FREEZE_PATH", tmp_path / "absent.txt")
    with pytest.raises(SystemExit) as missing:
        main(["--census-only", "--prereg-sha", digest, "--output", str(tmp_path / "b.md")])
    assert missing.value.code == 2
    assert "missing" in capsys.readouterr().err
    assert _listing(tmp_path / "out") == []


def test_tape_with_census_only_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    digest = _arm(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "--census-only",
                "--prereg-sha",
                digest,
                "--tape",
                str(tmp_path / "tape"),
                "--output",
                str(tmp_path / "ignored.md"),
            ]
        )
    assert exc.value.code == 2
    assert "--tape" in capsys.readouterr().err
    assert _listing(tmp_path / "out") == []


def test_frame_selector_nearest_tie_missing_rung_and_lag() -> None:
    early = "2026-09-21T16:00:00+00:00"
    nearer = "2026-09-21T18:00:05+00:00"
    farther = "2026-09-21T18:00:40+00:00"
    chosen = census.select_frame(
        climate_day=DAY,
        quotes={
            LOW_ID: (
                _quote(farther, "0.40", "0.30"),
                _quote(early, "0.10", "0.05"),
                _quote(nearer, "0.20", "0.10"),
            ),
            HIGH_ID: (
                _quote(farther, "0.40", "0.30"),
                _quote(early, "0.10", "0.05"),
                _quote(nearer, "0.20", "0.10"),
            ),
        },
    )
    assert chosen.kind == "FRAME"
    assert [quote.ts_ns for _iid, quote in chosen.chosen] == [_ns(nearer), _ns(nearer)]

    before = "2026-09-21T17:59:50+00:00"
    after = "2026-09-21T18:00:10+00:00"
    tied = census.select_frame(
        climate_day=DAY,
        quotes={
            LOW_ID: (
                _quote(after, "0.40", "0.30"),
                _quote(early, "0.10", "0.05"),
                _quote(before, "0.20", "0.10"),
            ),
            HIGH_ID: (
                _quote(after, "0.40", "0.30"),
                _quote(early, "0.10", "0.05"),
                _quote(before, "0.20", "0.10"),
            ),
        },
    )
    assert tied.kind == "FRAME"
    assert tied.chosen[0][1].ts_ns == _ns(before)

    missing = census.select_frame(
        climate_day=DAY,
        quotes={
            LOW_ID: (_quote(early, "0.10", "0.05"), _quote(nearer, "0.20", "0.10")),
            HIGH_ID: (),
        },
    )
    assert missing.kind == "MISSING"
    assert "rung" in missing.reason

    on_target = "2026-09-21T18:00:00+00:00"
    lag = census.select_frame(
        climate_day=DAY,
        quotes={
            LOW_ID: (_quote(on_target, "0.20", "0.10"),),
            HIGH_ID: (_quote(on_target, "0.20", "0.10"),),
        },
    )
    assert lag.kind == "MISSING"
    assert "60" in lag.reason


def test_leg_inequalities_on_a_hand_built_partition() -> None:
    assert_complete_partition([parse_rung(LOW_ID), parse_rung(HIGH_ID)])
    passing = census.evaluate_book(
        (
            (Decimal("0.07"), Decimal(1), Decimal("0.06"), Decimal(1)),
            (Decimal("0.88"), Decimal(1), Decimal("0.87"), Decimal(1)),
        )
    )
    failing = census.evaluate_book(
        (
            (Decimal("0.07"), Decimal(1), Decimal("0.05"), Decimal(1)),
            (Decimal("0.89"), Decimal(1), Decimal("0.88"), Decimal(1)),
        )
    )
    crossed = census.evaluate_book(
        (
            (Decimal("0.40"), Decimal(1), Decimal("0.50"), Decimal(1)),
            (Decimal("0.20"), Decimal(1), Decimal("0.10"), Decimal(1)),
        )
    )
    one_sided = census.evaluate_book(
        (
            (None, Decimal(0), Decimal("0.06"), Decimal(1)),
            (None, Decimal(0), Decimal("0.98"), Decimal(1)),
        )
    )
    assert passing.crossed is False
    assert passing.leg1_clear is True and passing.leg2_clear is False
    assert census.leg1_slack_cents((Decimal("0.07"), Decimal("0.88"))) == 0
    assert census.leg2_slack_cents((Decimal("0.06"), Decimal("0.98"))) == 0
    assert failing.leg1_clear is False and failing.leg2_clear is False
    assert census.leg1_slack_cents((Decimal("0.07"), Decimal("0.89"))) == -1
    assert census.leg2_slack_cents((Decimal("0.05"), Decimal("0.98"))) == -1
    assert crossed.crossed is True
    assert crossed.leg1_clear is False and crossed.leg2_clear is False
    assert one_sided.crossed is False
    assert one_sided.leg1_clear is False and one_sided.leg2_clear is True


def test_fee_rounding_q1_per_contract_and_q25_once_per_fill() -> None:
    from breezy.adapters.polymarket_us.fees import taker_fee_at_fill
    from breezy.strategy.current_rung_hold.decision import fee_on_ask

    price = Decimal("0.50")
    theta = Decimal("0.0695")
    per_contract = fee_on_ask(price, theta)
    assert census.rounded_fill_fee(price, 1) == per_contract
    once = census.rounded_fill_fee(price, 25)
    venue = taker_fee_at_fill(
        quantity=Decimal(25),
        price=price,
        ts_event_ns=1,
        fee_coefficient_at_fill=theta,
    )
    assert venue is not None
    assert once == venue.as_decimal()
    assert once != per_contract * 25


def test_own_order_normalizes_no_leg_and_excludes_at_or_after(tmp_path: Path) -> None:
    store = tmp_path / "exec.sqlite"
    _empty_store(store)
    day = utc_day_for_ns(CREATED_NS).isoformat()
    venue_id = "vid-1"
    _insert(
        store,
        [
            (history_key(INTENT_ID), _intent(slug=None)),
            (f"{FILL_BY_FINGERPRINT_KEY_PREFIX}{day}:{FINGERPRINT}", venue_id.encode()),
            (f"{FILL_KEY_PREFIX}{venue_id}", _fill(NO_ID)),
        ],
    )
    own = census.read_own_orders(store)
    assert own.instrument_ids == (BASE,)
    assert VENUE_ORDER_ID not in census.format_own_set(own)
    assert CLIENT_ORDER_ID not in census.format_own_set(own)
    assert census.frame_excluded(CREATED_NS, [HIGH_ID, LOW_ID], own.first_ns) is True
    assert census.frame_excluded(CREATED_NS - 1, [LOW_ID], own.first_ns) is False


def test_slugless_never_filled_exits_before_any_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "exec.sqlite"
    _empty_store(store)
    _insert(store, [(history_key(INTENT_ID), _intent(slug=None))])
    digest = _arm(tmp_path, monkeypatch, store=store)
    out = tmp_path / "out"
    before = _listing(tmp_path)
    with pytest.raises(SystemExit) as exc:
        main(["--census-only", "--prereg-sha", digest, "--output", str(tmp_path / "ignored.md")])
    assert exc.value.code == 2
    assert "slug-less" in capsys.readouterr().err
    assert _listing(out) == []
    assert _listing(tmp_path) == before


def test_unreadable_slot_row_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store = tmp_path / "exec.sqlite"
    _empty_store(store)
    _insert(store, [(CURRENT_INTENT_KEY, encode_v2({}, {"badslot": b"{}"}, {}))])
    digest = _arm(tmp_path, monkeypatch, store=store)
    with pytest.raises(SystemExit) as exc:
        main(["--census-only", "--prereg-sha", digest, "--output", str(tmp_path / "ignored.md")])
    assert exc.value.code == 2
    assert "unreadable slot" in capsys.readouterr().err
    assert _listing(tmp_path / "out") == []


def test_atomic_emit_and_same_sha_refusal(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    sha = "a" * 64
    markdown = f"# Card A census\n\nprereg_sha256: {sha}\n"
    records = ({"station": "NYC", "climate_day": "2026-09-22", "status": "MISSING"},)
    census.emit_census(out, markdown, records, sha, dry_run=False)
    written = sorted(path.name for path in out.iterdir())
    assert written == ["card_a_census.md", "card_a_census.parquet"]
    assert sha in (out / "card_a_census.md").read_text(encoding="utf-8")
    table = pq.read_table(out / "card_a_census.parquet")
    assert (table.schema.metadata or {})[b"prereg_sha256"] == sha.encode()
    before = (out / "card_a_census.md").read_bytes()
    with pytest.raises(SystemExit) as exc:
        census.emit_census(out, markdown + "second\n", records, sha, dry_run=False)
    assert exc.value.code == 2
    assert (out / "card_a_census.md").read_bytes() == before


def test_dry_run_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network")

    monkeypatch.setattr(socket, "create_connection", _refuse)
    store = tmp_path / "exec.sqlite"
    _empty_store(store)
    digest = _arm(tmp_path, monkeypatch, store=store)
    root = tmp_path / "out"
    before = _listing(tmp_path)
    assert (
        main(
            [
                "--census-only",
                "--dry-run",
                "--prereg-sha",
                digest,
                "--output",
                str(tmp_path / "ignored.md"),
            ]
        )
        == 0
    )
    assert _listing(tmp_path) == before
    assert _listing(root) == []


# ---- review r0 code items C1-C7 -------------------------------------------------------------


def _c(value: int) -> Decimal:
    return Decimal(value) / 100


def _fee_cents(price: Decimal, q: int) -> int:
    """Independent once-rounded q-fill fee in cents (q=1 is the per-contract gate)."""
    from breezy.adapters.polymarket_us.fees import taker_fee_at_fill
    from breezy.strategy.current_rung_hold.decision import fee_on_ask

    if q == 1:
        return int(fee_on_ask(price, Decimal("0.0695")) * 100)
    money = taker_fee_at_fill(
        quantity=Decimal(q),
        price=price,
        ts_event_ns=1,
        fee_coefficient_at_fill=Decimal("0.0695"),
    )
    assert money is not None
    return int(money.as_decimal() * 100)


def _expected_slack(prices: tuple[Decimal, ...], q: int, *, side: str) -> int:
    n = len(prices)
    cents = q * sum(int(price * 100) for price in prices)
    if side == "ask":
        return q * (100 - 2 * n) - (cents + sum(_fee_cents(price, q) for price in prices))
    return (cents - sum(_fee_cents(Decimal(1) - price, q) for price in prices)) - q * (100 + 2 * n)


def _pairs() -> list[tuple[Decimal, Decimal]]:
    return [(_c(a), _c(b)) for a in range(1, 50) for b in range(40, 100)]


def _denom(prices: tuple[Decimal, ...], *, side: str, size: int = 100) -> census._Denom:
    sizes = tuple(Decimal(size) for _ in prices)
    ask = side == "ask"
    return census._Denom(
        day=DAY,
        asks=prices if ask else (),
        ask_sizes=sizes if ask else (),
        bids=() if ask else prices,
        bid_sizes=() if ask else sizes,
        leg1=ask,
        leg2=not ask,
    )


@pytest.mark.parametrize("q", census.Q_GRID)
@pytest.mark.parametrize("side", ["ask", "bid"])
def test_slack_at_q_is_whole_fill_cents_and_boundary_exact(q: int, side: str) -> None:
    on_boundary: list[tuple[Decimal, ...]] = []
    short: list[tuple[int, tuple[Decimal, ...]]] = []
    for pair in _pairs():
        got = census._slack_at_q(pair, q, side=side)
        assert got == _expected_slack(pair, q, side=side)
        if q == 1:
            per_contract = (
                census.leg1_slack_cents(pair) if side == "ask" else census.leg2_slack_cents(pair)
            )
            assert got == per_contract
        if got == 0:
            on_boundary.append(pair)
        elif got < 0:
            short.append((got, pair))
    assert on_boundary, "the grid must hit the exact boundary"
    closest = max(short)[1]
    clearing = _prize_count(on_boundary[0], q, side)
    failing = _prize_count(closest, q, side)
    assert clearing == 1
    assert failing == 0


def _prize_count(prices: tuple[Decimal, ...], q: int, side: str) -> int:
    lines = census._prize_lines("PASS", [_denom(prices, side=side)], side=side)
    line = next(item for item in lines if item.startswith(f"q={q} "))
    return int(line.split("frames=")[1].split()[0])


def test_slack_at_q_pinned_literal_q5_boundary() -> None:
    assert census._slack_at_q((_c(5), _c(90)), 5, side="ask") == 0
    assert census._slack_at_q((_c(6), _c(90)), 5, side="ask") < 0
    assert census._slack_at_q((_c(10), _c(95)), 5, side="bid") == 0
    assert census._slack_at_q((_c(10), _c(94)), 5, side="bid") < 0


def test_zero_pad_does_not_satisfy_the_unit_line() -> None:
    from types import SimpleNamespace

    def inst(size: float) -> SimpleNamespace:
        return SimpleNamespace(ask_size=size)

    assert census._recover_unit([inst(0.0), inst(0.0)], 100.0) == (None, False)
    assert census._recover_unit([inst(0.0), inst(0.05)], 100.0) == (5, False)
    assert census._recover_unit([inst(0.0), inst(0.0123)], 100.0) == (None, True)
    assert census._label(5, 40, 10, False) == "INCONCLUSIVE"
    rows = [
        {"station": "NYC", "climate_day": "d", "status": "FRAME", "leg1": "clear", "leg2": "no"}
    ]
    scrubbed = census.scrub_legs_without_unit(rows, False)
    assert scrubbed[0]["leg1"] == "" and scrubbed[0]["leg2"] == ""
    assert scrubbed[0]["status"] == "FRAME"
    assert census.scrub_legs_without_unit(rows, True) == rows
    assert rows[0]["leg1"] == "clear"


@pytest.mark.parametrize(
    ("clears", "denominator", "dates", "expected"),
    [
        (5, 30, 7, "PASS"),
        (5, 29, 7, "INCONCLUSIVE"),
        (5, 30, 6, "INCONCLUSIVE"),
        (0, 30, 7, "KILL"),
        (0, 29, 7, "INCONCLUSIVE"),
        (0, 30, 6, "INCONCLUSIVE"),
        (1, 29, 6, "INCONCLUSIVE"),
    ],
)
def test_label_floors(clears: int, denominator: int, dates: int, expected: str) -> None:
    assert census._label(clears, denominator, dates, True) == expected


def test_ro_percent_quotes_the_path(tmp_path: Path) -> None:
    odd = tmp_path / "a?b#c d"
    odd.mkdir()
    store = odd / "exec.sqlite"
    _empty_store(store)
    own = census.read_own_orders(store)
    assert own.instrument_ids == ()
    assert own.never_filled == 0


def test_lone_parquet_is_a_prior_look_and_parquet_is_replaced_before_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sha = "b" * 64
    out = tmp_path / "out"
    out.mkdir()
    census._write_parquet(out / "card_a_census.parquet", [], sha)
    assert census._carries_sha(out, sha) is True
    with pytest.raises(SystemExit) as exc:
        census.emit_census(out, f"prereg_sha256: {sha}\n", [], sha)
    assert exc.value.code == 2
    assert not (out / "card_a_census.md").exists()

    fresh = tmp_path / "fresh"
    order: list[str] = []
    real = census.os.replace

    def spy(src: object, dst: object) -> None:
        order.append(Path(str(dst)).name)
        real(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(census.os, "replace", spy)
    census.emit_census(fresh, f"prereg_sha256: {sha}\n", [], sha)
    assert order == ["card_a_census.parquet", "card_a_census.md"]


def test_render_prints_the_real_slugless_count() -> None:
    own = census.OwnSet(instrument_ids=(BASE,), first_ns={BASE: 1}, never_filled=3)
    text = census._render(
        "c" * 64, own, notes=[], denoms=[], sum_rows=0, impossible=0, leg1="X", leg2="Y"
    )
    assert "slug-less never-filled intents: 3" in text


def test_low_directory_match_is_anchored(tmp_path: Path) -> None:
    root = tmp_path / "order_book_depths"
    root.mkdir()
    for name in (
        "tc-temp-mdwlow-2026-10-15-gte52lt53f.POLYMARKET_US",
        "x-tc-temp-mdwlow-2026-10-15-gte52lt53f.POLYMARKET_US",
    ):
        (root / name).mkdir()
    notes: list[str] = []
    grouped, _impossible = census._walk_dirs(root, notes)
    assert grouped == {}
    assert "skipped low dir: tc-temp-mdwlow-2026-10-15-gte52lt53f.POLYMARKET_US" in notes
    assert "skipped unparsed dir: x-tc-temp-mdwlow-2026-10-15-gte52lt53f.POLYMARKET_US" in notes


def test_off_tick_price_is_refused_not_rounded() -> None:
    off = Decimal("0.075")
    with pytest.raises(census.OffTickError):
        census._slack_at_q((off, _c(90)), 1, side="ask")
    with pytest.raises(census.OffTickError):
        census.leg2_slack_cents((off, _c(90)))
    with pytest.raises(census.OffTickError):
        census.evaluate_book(((off, Decimal(1), _c(5), Decimal(1)),))


def _two_rungs(
    low_rows: tuple[census.Quote, ...], high_rows: tuple[census.Quote, ...]
) -> census.FrameSelection:
    return census.select_frame(climate_day=DAY, quotes={LOW_ID: low_rows, HIGH_ID: high_rows})


def test_bid_equal_ask_is_crossed_via_select_frame() -> None:
    early = _quote("2026-09-21T16:00:00+00:00", "0.20", "0.10")
    equal = _quote("2026-09-21T18:00:00+00:00", "0.20", "0.20")
    fine = _quote("2026-09-21T18:00:00+00:00", "0.20", "0.19")
    crossed = _two_rungs((early, equal), (early, fine))
    assert (crossed.kind, crossed.reason) == ("MISSING", "crossed rung")
    assert _two_rungs((early, fine), (early, fine)).kind == "FRAME"


def test_age_cap_is_inclusive_at_60s_and_closed_at_60_001s() -> None:
    early = _quote("2026-09-21T16:00:00+00:00", "0.20", "0.10")
    at_cap = _quote("2026-09-21T18:01:00+00:00", "0.20", "0.10")
    past = _quote("2026-09-21T18:01:00.001000+00:00", "0.20", "0.10")
    assert _two_rungs((early, at_cap), (early, at_cap)).kind == "FRAME"
    over = _two_rungs((early, past), (early, past))
    assert (over.kind, over.reason) == ("MISSING", "missing rung")


def test_stale_only_rung_is_missing() -> None:
    early = _quote("2026-09-21T16:00:00+00:00", "0.20", "0.10")
    now = _quote("2026-09-21T18:00:00+00:00", "0.20", "0.10")
    stale = _quote("2026-09-21T18:02:00+00:00", "0.20", "0.10")
    result = _two_rungs((early, now), (stale,))
    assert (result.kind, result.reason) == ("MISSING", "missing rung")


def test_lead_boundary_is_exactly_60_minutes() -> None:
    now = _quote("2026-09-21T18:00:00+00:00", "0.20", "0.10")
    on = _quote("2026-09-21T17:00:00+00:00", "0.20", "0.10")
    late = _quote("2026-09-21T17:00:01+00:00", "0.20", "0.10")
    assert _two_rungs((on, now), (on, now)).kind == "FRAME"
    short = _two_rungs((on, now), (late, now))
    assert short.kind == "MISSING" and "60 minutes" in short.reason


def test_size_zero_on_a_present_side_blocks_that_leg() -> None:
    one, zero = Decimal(1), Decimal(0)
    ok = census.evaluate_book(
        ((_c(7), one, _c(6), one), (_c(88), one, _c(87), one)),
    )
    ask_zero = census.evaluate_book(
        ((_c(7), zero, _c(6), one), (_c(88), one, _c(87), one)),
    )
    assert ok.leg1_clear is True and ask_zero.leg1_clear is False
    bids_ok = census.evaluate_book(((_c(99), one, _c(6), one), (_c(99), one, _c(98), one)))
    bid_zero = census.evaluate_book(((_c(99), one, _c(6), one), (_c(99), one, _c(98), zero)))
    assert bids_ok.leg2_clear is True and bid_zero.leg2_clear is False
    assert bid_zero.leg1_clear is False


def test_intent_slug_branch_builds_the_own_set(tmp_path: Path) -> None:
    store = tmp_path / "exec.sqlite"
    _empty_store(store)
    _insert(store, [(history_key(INTENT_ID), _intent(slug=BASE))])
    own = census.read_own_orders(store)
    assert own.instrument_ids == (BASE,)
    assert own.first_ns == {BASE: CREATED_NS}
    assert own.never_filled == 0
