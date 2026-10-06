"""M1-v3: the pre-registered forward NO-longshot execution-structure screen.

Plan: docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/M1v3-no-longshot-forward-screen_plan.md
(r1 < r2 < r3 < r3.1; rulings M1V3-R1..R18). Fixtures are synthetic: catalogs written through
Nautilus' own ``ParquetDataCatalog`` writer, truth CSVs written here, and real temporary git
repositories for the freeze checks. Nothing reads live data and nothing touches the network.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, REPO_ROOT.as_posix())
from scripts.analysis import no_longshot_pooled_test as tool

_NS = 1_000_000_000
_PREREG_SRC = REPO_ROOT / "docs" / "evidence" / "m1v3" / "PREREG.json"
_COMMIT_ISO = "2026-10-10T20:00:00+00:00"
_FIRST_FORWARD = dt.date(2026, 10, 11)
_AS_OF_EARLY = dt.date(2026, 10, 20)
_AS_OF_READ = _FIRST_FORWARD + dt.timedelta(days=61)
_B = 400  # small bootstrap for the end-to-end tests; the pinned B is checked separately


# --------------------------------------------------------------------------- pure helpers


def _take(
    day: dt.date,
    *,
    ask: str = "0.90",
    hit: bool = True,
    station: str = "LAX",
    rung: str = "r",
    depth: str | None = None,
) -> Any:
    return tool.Take(
        station, day, rung, Decimal(ask), hit, 1, None if depth is None else Decimal(depth)
    )


def _days(n: int, start: dt.date = _FIRST_FORWARD) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range(n)]


def _edge_takes(n_days: int = 60, per_day: int = 12, loss_every: int = 40) -> list[Any]:
    takes: list[Any] = []
    for i in range(n_days * per_day):
        day = _FIRST_FORWARD + dt.timedelta(days=i // per_day)
        takes.append(_take(day, hit=(i % loss_every != 0), rung=f"r{i % per_day}"))
    return takes


def _pooled(**kw: Any) -> Any:
    base: dict[str, Any] = {
        "n_takes": 700,
        "n_days": 50,
        "loss_days": 12,
        "n_losses": 20,
        "loss_rate": 0.03,
        "mean": 0.02,
        "lb_primary": 0.01,
        "lb_bca": 0.01,
        "p_cell": 0.01,
    }
    base.update(kw)
    return tool.Pooled(**base)


# --------------------------------------------------------------------------- fee and cost


def test_fee_theta_equals_evidenced_theta() -> None:
    from breezy.analysis.hypothesis_ledger import EVIDENCED_FEE_THETA

    assert tool.THETA == Decimal(str(EVIDENCED_FEE_THETA))
    assert tool.THETA is tool.m1.THETA


def test_net_ev_includes_fee_and_slippage() -> None:
    win = tool.net_ev(Decimal("0.92"), True)
    assert win == Decimal(1) - (Decimal("0.92") + Decimal("0.01") + Decimal("0.01"))
    loss = tool.net_ev(Decimal("0.97"), False)
    unrounded = Decimal("0.0695") * Decimal("0.97") * Decimal("0.03")
    assert loss == -(Decimal("0.97") + unrounded + Decimal("0.01"))
    assert tool.net_ev(Decimal("0.92"), True, slippage=Decimal(0)) == Decimal("0.07")


def test_fee_primary_is_max_of_rounded_and_unrounded() -> None:
    for cents in range(90, 100):
        ask = Decimal(cents) / 100
        rounded = tool.m1.venue_fee(ask)
        unrounded = tool.THETA * ask * (Decimal(1) - ask)
        assert tool.fee(ask, "primary") == max(rounded, unrounded)
        assert tool.fee(ask, "rounded") == rounded
        assert tool.fee(ask, "unrounded") == unrounded
    with pytest.raises(ValueError):
        tool.fee(Decimal("0.9"), "bogus")


def test_fee_rounding_in_090_100_band() -> None:
    assert tool.m1.venue_fee(Decimal("0.92")) == Decimal("0.01")
    for cents in range(93, 100):
        ask = Decimal(cents) / 100
        assert tool.m1.venue_fee(ask) == Decimal("0.00")
        assert tool.fee(ask, "primary") > 0  # the conservative basis never rounds to zero


def test_ask_090_boundary_inclusive() -> None:
    def obs(ask: str, side: str = "NO", window: str = "D_12Z") -> Any:
        return tool.m1.Observation(
            "LAX", _FIRST_FORWARD, window, "r", side, Decimal(ask), 5, 9, True
        )

    kept = tool.select_takes(
        [obs("0.90"), obs("0.8999"), obs("0.99"), obs("0.95", "YES"), obs("0.95", window="D_17Z")]
    )
    assert [t.ask for t in kept] == [Decimal("0.90"), Decimal("0.99")]


def test_ask_bin_composition_reported() -> None:
    takes = [_take(_FIRST_FORWARD, ask=a) for a in ("0.90", "0.92", "0.93", "0.95", "0.96", "0.99")]
    table = tool.ask_bin_table(takes)
    assert [row["bin"] for row in table] == ["0.90-0.92", "0.93-0.95", "0.96-0.99"]
    assert [row["n"] for row in table] == [2, 2, 2]


# --------------------------------------------------------------------------- statistics


def test_day_cluster_bootstrap_resamples_whole_days(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    real = tool.m1._bootstrap_stats

    def spy(s_mat: Any, n_mat: Any, resamples: int, seed: int) -> Any:
        seen.update(s=s_mat.copy(), n=n_mat.copy(), resamples=resamples, seed=seed)
        return real(s_mat, n_mat, resamples, seed)

    monkeypatch.setattr(tool.m1, "_bootstrap_stats", spy)
    days = _days(4)
    takes = [_take(days[0]), _take(days[0], hit=False), _take(days[2])]  # days 1 and 3: no takes
    pooled = tool.pool(takes, days, resamples=_B)
    assert seen["s"].shape == (4, 1) and seen["n"].shape == (4, 1)  # one row per whole day
    assert seen["n"][:, 0].tolist() == [2.0, 0.0, 1.0, 0.0]  # zero-take days stay in the vector
    assert seen["seed"] == tool.SEED and seen["resamples"] == _B
    assert pooled.n_days == 4 and pooled.n_takes == 3


def test_tool_builds_own_cost_matrix_not_m1_excess(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("M1's cost path must not be used")

    monkeypatch.setattr(tool.m1, "excess", boom)
    monkeypatch.setattr(tool.m1, "_day_matrices", boom)
    captured: dict[str, Any] = {}
    real = tool.m1._bootstrap_stats

    def spy(s_mat: Any, n_mat: Any, resamples: int, seed: int) -> Any:
        captured["s"] = s_mat.copy()
        return real(s_mat, n_mat, resamples, seed)

    monkeypatch.setattr(tool.m1, "_bootstrap_stats", spy)
    days = _days(2)
    tool.pool(
        [_take(days[0], ask="0.92"), _take(days[1], ask="0.97", hit=False)], days, resamples=_B
    )
    expected = [
        float(tool.net_ev(Decimal("0.92"), True)),
        float(tool.net_ev(Decimal("0.97"), False)),
    ]
    assert captured["s"][:, 0].tolist() == pytest.approx(expected)


def test_primary_lower_bound_is_fifth_percentile_of_draws() -> None:
    days = _days(60)
    takes = _edge_takes()
    pooled = tool.pool(takes, days, resamples=2000)
    s = np.zeros((60, 1))
    n = np.zeros((60, 1))
    for t in takes:
        s[(t.day - _FIRST_FORWARD).days, 0] += float(tool.net_ev(t.ask, t.hit))
        n[(t.day - _FIRST_FORWARD).days, 0] += 1
    boot = tool.m1._bootstrap_stats(s, n, 2000, tool.SEED)
    expected = float(boot.observed[0] + np.percentile(boot.centred[:, 0], 5))
    assert pooled.lb_primary == pytest.approx(expected)
    assert pooled.mean == pytest.approx(float(s.sum() / n.sum()))
    assert pooled.n_losses == 18 and pooled.loss_days == 18


def test_verdict_underpowered_below_takes_days_or_loss_days_floor() -> None:
    assert tool.decide(_pooled()) == "WINNER"
    assert tool.decide(_pooled(n_takes=619)) == "UNDERPOWERED"
    assert tool.decide(_pooled(n_takes=620)) == "WINNER"
    assert tool.decide(_pooled(n_days=39)) == "UNDERPOWERED"
    assert tool.decide(_pooled(loss_days=4)) == "UNDERPOWERED"
    assert tool.decide(_pooled(loss_days=5)) == "WINNER"
    # a floor miss outranks a negative bound: UNDERPOWERED is a verdict about power
    assert tool.decide(_pooled(n_days=10, lb_primary=-0.1, lb_bca=-0.1)) == "UNDERPOWERED"


def test_winner_requires_both_lbs_above_zero() -> None:
    assert tool.decide(_pooled(lb_primary=0.001, lb_bca=0.001)) == "WINNER"
    assert tool.decide(_pooled(lb_primary=0.001, lb_bca=0.0)) == "NO-EDGE"
    assert tool.decide(_pooled(lb_primary=0.0, lb_bca=0.001)) == "NO-EDGE"
    assert tool.decide(_pooled(lb_primary=0.001, lb_bca=float("nan"))) == "NO-EDGE"
    assert tool.decide(_pooled(lb_primary=0.001, lb_bca=None)) == "NO-EDGE"


def test_real_edge_sample_is_winner_through_both_bounds() -> None:
    pooled = tool.pool(_edge_takes(), _days(60), resamples=2000)
    assert pooled.lb_primary is not None and pooled.lb_primary > 0
    assert pooled.lb_bca is not None and pooled.lb_bca > 0
    assert tool.decide(pooled) == "WINNER"


def test_all_win_sample_never_winner() -> None:
    takes = [_take(_FIRST_FORWARD + dt.timedelta(days=i // 12)) for i in range(720)]
    pooled = tool.pool(takes, _days(60), resamples=500)
    assert pooled.n_losses == 0 and pooled.loss_days == 0
    assert tool.decide(pooled) != "WINNER"


def test_pool_with_no_takes_is_defined() -> None:
    pooled = tool.pool([], _days(3), resamples=_B)
    assert pooled.n_takes == 0 and pooled.mean is None and pooled.lb_primary is None
    assert tool.decide(pooled) == "UNDERPOWERED"


def test_per_ladder_secondary_computed() -> None:
    days = _days(2)
    takes = [
        _take(days[0], rung="a", hit=True),
        _take(days[0], rung="b", hit=False),  # same ladder: at most one rung loses
        _take(days[0], rung="c", hit=True),
        _take(days[1], rung="a", hit=True),
        _take(days[1], rung="a", station="SFO", hit=True),
    ]
    out = tool.per_ladder(takes, days, resamples=_B)
    assert out["n_ladders"] == 3
    ladder_one = (
        float(tool.net_ev(Decimal("0.9"), True)) * 2 + float(tool.net_ev(Decimal("0.9"), False))
    ) / 3
    expected = (ladder_one + 2 * float(tool.net_ev(Decimal("0.9"), True))) / 3
    assert out["mean"] == pytest.approx(expected)
    assert out["ladders_with_loss"] == 1


# --------------------------------------------------------------------------- the prereg draft


def test_draft_prereg_is_unfrozen_and_pinned_to_the_tool_constants() -> None:
    design = json.loads(_PREREG_SRC.read_text())
    assert design["frozen_sha"] == "UNFROZEN"
    assert tool.check_pins(design) == []
    assert design["window"] == "D_12Z"
    assert (design["min_takes"], design["min_days"], design["min_loss_days"]) == (620, 40, 5)


def test_check_pins_flags_every_drifted_pin() -> None:
    design = json.loads(_PREREG_SRC.read_text())
    for key, bad in (
        ("theta", "0.06"),
        ("window", "D_17Z"),
        ("bootstrap_B", 5),
        ("bootstrap_seed", 1),
        ("slippage", "0.02"),
        ("ask_threshold", "0.85"),
        ("min_takes", 500),
    ):
        drifted = {**design, key: bad}
        assert any(key in m for m in tool.check_pins(drifted)), key
    missing = {k: v for k, v in design.items() if k != "theta"}
    assert any("theta" in m for m in tool.check_pins(missing))


# --------------------------------------------------------------------------- end to end


def _depth(
    slug: str, ts: int, bids: list[tuple[str, str]], asks: list[tuple[str, str]] | None = None
) -> OrderBookDepth10:
    def side(
        levels: list[tuple[str, str]], order_side: OrderSide
    ) -> tuple[list[BookOrder], list[int]]:
        orders = [
            BookOrder(order_side, Price(float(p), 2), Quantity(float(s), 2), 0) for p, s in levels
        ]
        counts = [1] * len(orders)
        filler = BookOrder(order_side, Price(0, 2), Quantity(0, 2), 0)
        while len(orders) < 10:
            orders.append(filler)
            counts.append(0)
        return orders, counts

    bid_orders, bid_counts = side(bids, OrderSide.BUY)
    ask_orders, ask_counts = side(asks or [], OrderSide.SELL)
    return OrderBookDepth10(
        InstrumentId.from_str(f"{slug}.POLYMARKET_US"),
        bid_orders,
        ask_orders,
        bid_counts,
        ask_counts,
        0,
        ts,
        ts,
        ts,
    )


def _ns_of(day: dt.date, hour: int, minute: int = 0) -> int:
    moment = dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=dt.UTC)
    return int(moment.timestamp()) * _NS


class _Rung:
    def __init__(
        self,
        bucket: str,
        bid: str | None,
        *,
        hour: int = 12,
        size: str = "20",
        ask: str | None = None,
    ) -> None:
        self.bucket, self.bid, self.hour, self.size, self.ask = bucket, bid, hour, size, ask


class _Ladder:
    def __init__(self, station: str, tmax: int, rungs: Sequence[_Rung]) -> None:
        self.station, self.tmax, self.rungs = station, tmax, rungs


def _stage(
    root: Path, days: dict[dt.date, list[_Ladder]], *, issued_offset: int = 1
) -> tuple[Path, Path]:
    rows: dict[str, list[OrderBookDepth10]] = {}
    truth: list[dict[str, str]] = []
    for day, ladders in days.items():
        for ladder in ladders:
            for rung in ladder.rungs:
                slug = f"tc-temp-{ladder.station.lower()}high-{day.isoformat()}-{rung.bucket}f"
                bids = [] if rung.bid is None else [(rung.bid, rung.size)]
                asks = None if rung.ask is None else [(rung.ask, rung.size)]
                row = _depth(slug, _ns_of(day, rung.hour, 5), bids, asks)
                rows.setdefault(str(row.instrument_id), []).append(row)
            issued = dt.datetime(day.year, day.month, day.day, 12, tzinfo=dt.UTC) + dt.timedelta(
                days=issued_offset
            )
            truth.append(
                {
                    "station": ladder.station,
                    "climate_day": day.isoformat(),
                    "status": "FINAL",
                    "is_final": "True",
                    "tmax_f": str(ladder.tmax),
                    "issued_at_utc": issued.isoformat(),
                }
            )
    catalog_root = root / "cat"
    catalog = ParquetDataCatalog(catalog_root)
    for batch in rows.values():
        catalog.write_data(sorted(batch, key=lambda r: r.ts_event))
    truth_path = root / "truth.csv"
    with truth_path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["station", "climate_day", "status", "is_final", "tmax_f", "issued_at_utc"],
        )
        writer.writeheader()
        writer.writerows(truth)
    return catalog_root, truth_path


def _lax(
    tmax: int = 75, *, lt70: str | None = "0.05", mid: str | None = "0.04", top: str | None = "0.08"
) -> _Ladder:
    """tmax 75: lt70 and gte70lt71 are NO winners (asks 0.95/0.96); gte72 hits: NO loses at 0.92."""
    return _Ladder("LAX", tmax, [_Rung("lt70", lt70), _Rung("gte70lt71", mid), _Rung("gte72", top)])


def _git(cwd: Path, *args: str, when: str | None = None) -> str:
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE")}
    if when is not None:
        env.update(GIT_COMMITTER_DATE=when, GIT_AUTHOR_DATE=when)
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def _freeze(
    root: Path, *, commit_iso: str = _COMMIT_ISO, mutate: dict[str, Any] | None = None
) -> tuple[Path, str]:
    repo = root / "repo"
    path = repo / "docs" / "evidence" / "m1v3" / "PREREG.json"
    path.parent.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    design = json.loads(_PREREG_SRC.read_text())
    design.update(mutate or {})
    path.write_text(json.dumps(design, indent=2, sort_keys=True))
    _git(repo, "add", "docs")
    _git(repo, "commit", "-q", "-m", "freeze", when=commit_iso)
    sha = _git(repo, "rev-parse", "HEAD")
    path.write_text(json.dumps({**design, "frozen_sha": sha}, indent=2, sort_keys=True))
    return path, sha


@pytest.fixture
def world(tmp_path: Path) -> dict[str, Any]:
    prereg, sha = _freeze(tmp_path)
    return {"root": tmp_path, "prereg": prereg, "sha": sha}


def _run(
    world: dict[str, Any], catalog: Path, truth: Path, **kw: Any
) -> tuple[dict[str, Any], int]:
    return tool.run_screen(
        prereg=world["prereg"],
        catalog=catalog,
        truth=truth,
        out_dir=kw.pop("out_dir", None),
        as_of=kw.pop("as_of", _AS_OF_READ),
        resamples=kw.pop("resamples", _B),
    )


def _forward_world(world: dict[str, Any]) -> tuple[Path, Path]:
    days = {
        dt.date(2026, 10, 9): [_lax()],
        dt.date(2026, 10, 10): [_lax()],
        dt.date(2026, 10, 11): [_lax()],
        dt.date(2026, 10, 12): [_lax()],
    }
    return _stage(world["root"], days)


def test_refuses_when_unfrozen(world: dict[str, Any]) -> None:
    design = json.loads(world["prereg"].read_text())
    world["prereg"].write_text(json.dumps({**design, "frozen_sha": "UNFROZEN"}))
    catalog, truth = _forward_world(world)
    with pytest.raises(tool.Refusal, match="UNFROZEN"):
        _run(world, catalog, truth)


def test_refuses_when_frozen_blob_differs(world: dict[str, Any]) -> None:
    design = json.loads(world["prereg"].read_text())
    world["prereg"].write_text(json.dumps({**design, "alpha": 0.5}))
    catalog, truth = _forward_world(world)
    with pytest.raises(tool.Refusal, match="FROZEN_BLOB_DIFFERS"):
        _run(world, catalog, truth)


def test_refuses_when_frozen_sha_not_ancestor(world: dict[str, Any]) -> None:
    repo = world["root"] / "repo"
    _git(repo, "checkout", "-q", "-b", "side")
    design = json.loads(world["prereg"].read_text())
    side = {**design, "note": "side"}
    world["prereg"].write_text(json.dumps(side))
    _git(repo, "add", "docs")
    _git(repo, "commit", "-q", "-m", "side", when=_COMMIT_ISO)
    side_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    world["prereg"].write_text(json.dumps({**side, "frozen_sha": side_sha}))
    catalog, truth = _forward_world(world)
    with pytest.raises(tool.Refusal, match="FROZEN_SHA_NOT_ANCESTOR"):
        _run(world, catalog, truth)


def test_refuses_when_a_pin_drifted_even_if_frozen(tmp_path: Path) -> None:
    prereg, _ = _freeze(tmp_path, mutate={"theta": "0.06"})
    world = {"root": tmp_path, "prereg": prereg}
    catalog, truth = _forward_world(world)
    with pytest.raises(tool.Refusal, match="theta"):
        _run(world, catalog, truth)


def test_first_forward_day_derived_from_git_not_json(tmp_path: Path) -> None:
    # 2026-10-10T23:30-05:00 is 2026-10-11T04:30Z: the UTC committer date is the 11th.
    prereg, _ = _freeze(tmp_path, commit_iso="2026-10-10T23:30:00-05:00")
    world = {"root": tmp_path, "prereg": prereg}
    catalog, truth = _forward_world(world)
    report, _code = _run(world, catalog, truth)
    assert report["first_forward_day"] == "2026-10-12"
    assert report["read_date"] == (dt.date(2026, 10, 12) + dt.timedelta(days=61)).isoformat()
    # R21: as_of is before this read date, so the report is counts-only (progress)
    assert report["progress"]["n_days"] == 1  # only 10-12 is a forward day


def test_json_first_forward_day_that_disagrees_with_git_is_refused(tmp_path: Path) -> None:
    prereg, _ = _freeze(tmp_path, mutate={"first_forward_day": "2026-10-01"})
    world = {"root": tmp_path, "prereg": prereg}
    catalog, truth = _forward_world(world)
    with pytest.raises(tool.Refusal, match="first_forward_day"):
        _run(world, catalog, truth)


def test_forward_filter_excludes_pre_freeze_days(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog, truth = _forward_world(world)
    scanned: list[set[dt.date]] = []
    real = tool.m1.collect

    def spy(root: Path, rows: Any, last: Any, windows: Any = None, **kw: Any) -> Any:
        scanned.append({day for _s, day in rows})
        return real(root, rows, last, windows, **kw) if windows else real(root, rows, last, **kw)

    monkeypatch.setattr(tool.m1, "collect", spy)
    report, _ = _run(world, catalog, truth)
    assert report["first_forward_day"] == "2026-10-11"
    assert report["counts"]["n_days"] == 2
    assert all(day >= _FIRST_FORWARD for days in scanned for day in days)
    assert {d for days in scanned for d in days} == {dt.date(2026, 10, 11), dt.date(2026, 10, 12)}


def test_pooled_uses_single_window_per_rung_day(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog, truth = _forward_world(world)
    calls: list[tuple[Any, set[dt.date]]] = []
    real = tool.m1.collect

    def spy(root: Path, rows: Any, last: Any, windows: Any = None, **kw: Any) -> Any:
        calls.append((tuple(windows) if windows else None, {d for _s, d in rows}))
        return real(root, rows, last, windows, **kw) if windows else real(root, rows, last, **kw)

    monkeypatch.setattr(tool.m1, "collect", spy)
    report, _ = _run(world, catalog, truth)
    primary = [c for c in calls if c[0] is not None and c[0][0].label == "D_12Z"]
    assert all(c[0] is not None and len(c[0]) == 1 for c in calls)  # never a window sum
    assert sorted(next(iter(d)) for _w, d in primary) == [
        dt.date(2026, 10, 11),
        dt.date(2026, 10, 12),
    ]
    assert all(len(d) == 1 for _w, d in primary)  # one collect per forward climate day
    assert report["window"] == "D_12Z"
    assert report["counts"]["n_takes"] == 2 * 3  # three rungs per ladder, one window each


def test_no_ask_none_when_bid_side_empty_counted_not_synthesised(world: dict[str, Any]) -> None:
    days = {
        dt.date(2026, 10, 11): [_lax(mid=None)],  # empty YES bid side on one rung
        dt.date(2026, 10, 12): [_lax()],
    }
    catalog, truth = _stage(world["root"], days)
    report, _ = _run(world, catalog, truth)
    per_day = {row["day"]: row for row in report["population"]["per_day"]}
    assert per_day["2026-10-11"]["no_bid_side"] == 1
    assert per_day["2026-10-11"]["takes"] == 2  # the empty rung is a denominator, not a take
    assert per_day["2026-10-12"]["no_bid_side"] == 0
    assert report["population"]["skipped_no_bid_side"] == 1


def test_incomplete_day_excluded_whole_day(world: dict[str, Any]) -> None:
    late = _Ladder(
        "SFO", 75, [_Rung("lt70", "0.05"), _Rung("gte72", "0.08", hour=11)]
    )  # 11Z: no D_12Z row
    days = {
        dt.date(2026, 10, 11): [_lax(), late],  # SFO excluded whole, LAX kept
        dt.date(2026, 10, 12): [late],  # no station-day survives: the climate day is excluded
    }
    catalog, truth = _stage(world["root"], days)
    report, _ = _run(world, catalog, truth)
    pop = report["population"]
    assert report["counts"]["n_days"] == 1
    assert report["counts"]["n_takes"] == 3  # LAX's three; none of SFO's observed rung
    assert pop["excluded_station_days"] == 2
    assert pop["excluded_days"] == ["2026-10-12"]
    assert all(row["station_days_used"] >= 1 for row in pop["per_day"])


def test_no_verdict_before_read_date(world: dict[str, Any]) -> None:
    catalog, truth = _forward_world(world)
    early, code = _run(world, catalog, truth, as_of=_AS_OF_EARLY)
    assert code == 0 and early["status"] == "PROGRESS"
    assert "verdict" not in early and "stats" not in early
    assert "lb_primary" not in json.dumps(early) and "mean" not in json.dumps(early)
    read, code = _run(world, catalog, truth, as_of=_AS_OF_READ)
    assert code == 0 and read["status"] == "READ"
    assert read["verdict"] == "UNDERPOWERED"  # 6 takes over 2 days: every floor is missed
    assert read["stats"]["alpha"] == 0.05


def test_report_embeds_provenance_and_descriptives(world: dict[str, Any]) -> None:
    catalog, truth = _forward_world(world)
    report, _ = _run(world, catalog, truth)
    assert report["frozen_sha"] == world["sha"]
    assert report["head_sha"] == _git(world["root"] / "repo", "rev-parse", "HEAD")
    assert report["truth_sha256"] == hashlib.sha256(truth.read_bytes()).hexdigest()
    days = "2026-10-09\n2026-10-10\n2026-10-11\n2026-10-12"
    assert report["catalog_day_list_sha256"] == hashlib.sha256(days.encode()).hexdigest()
    assert report["depth"]["share_ge_10"] == 1.0  # fixture bids are 20 contracts deep
    assert {
        "rounded_fee_only",
        "unrounded_fee_only",
        "slippage_0c",
        "slippage_2c",
        "ask_0.90-0.97",
    } <= set(report["sensitivities"])
    assert {"D-1_18Z", "D_17Z"} <= set(report["window_sensitivities"])
    assert len(report["ask_bins"]) == 3 and "per_ladder" in report
    assert report["notice"].startswith("Lane E")


def test_depth_share_counts_thin_books(world: dict[str, Any]) -> None:
    thin = _Ladder("LAX", 75, [_Rung("lt70", "0.05", size="3"), _Rung("gte72", "0.08", size="30")])
    catalog, truth = _stage(world["root"], {dt.date(2026, 10, 11): [thin]})
    report, _ = _run(world, catalog, truth)
    assert report["depth"]["share_ge_10"] == 0.5


def test_lookahead_raise_path_is_invalid(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog, truth = _forward_world(world)

    def raising(*_a: Any, **_k: Any) -> Any:
        raise tool.m1.LookAheadError("row escaped window")

    monkeypatch.setattr(tool.m1, "collect", raising)
    report, code = _run(world, catalog, truth)
    assert code == 2 and report["verdict"] == "INVALID"
    assert any("look-ahead" in r for r in report["invalid_reasons"])
    assert "stats" not in report


def test_lookahead_failed_observation_is_invalid(world: dict[str, Any]) -> None:
    # settlement published a day BEFORE the reference row: assert_no_lookahead fails in _observe_row
    days = {dt.date(2026, 10, 11): [_lax()], dt.date(2026, 10, 12): [_lax()]}
    catalog, truth = _stage(world["root"], days, issued_offset=-1)
    report, code = _run(world, catalog, truth)
    assert code == 2 and report["verdict"] == "INVALID"
    assert any("look-ahead" in r for r in report["invalid_reasons"])


def test_degenerate_ask_is_invalid(world: dict[str, Any]) -> None:
    # a YES bid of 1.00 makes the NO ask exactly 0: a degenerate ask is INVALID, as in M1
    days = {dt.date(2026, 10, 11): [_lax(lt70="1.00")]}
    catalog, truth = _stage(world["root"], days)
    report, code = _run(world, catalog, truth)
    assert code == 2 and report["verdict"] == "INVALID"


def test_refuses_to_write_under_live_data_root(
    world: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    live = tmp_path / "live"
    monkeypatch.setattr(tool.m1, "LIVE_DATA_ROOT", live)
    catalog, truth = _forward_world(world)
    with pytest.raises(tool.Refusal, match="live data root"):
        _run(world, catalog, truth, out_dir=live / "derived" / "m1v3")
    assert not live.exists()
    out = tmp_path / "out"
    _run(world, catalog, truth, out_dir=out)
    written = json.loads((out / "no_longshot_report.json").read_text())
    assert written["frozen_sha"] == world["sha"]


def test_main_exit_codes(
    world: dict[str, Any], capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    catalog, truth = _forward_world(world)
    base = [
        "--prereg", str(world["prereg"]),
        "--catalog", str(catalog),
        "--truth", str(truth),
        "--out", str(tmp_path / "o"),
        "--as-of", "2026-10-20",
    ]  # fmt: skip
    clock = lambda: dt.date(2026, 10, 20)  # R20: --as-of cannot pass the clock
    assert tool.main(base, clock=clock) == 0
    # the committed DRAFT is UNFROZEN: the tool refuses and exits 3 with no verdict
    unfrozen = [*base]
    unfrozen[1] = str(_PREREG_SRC)
    assert tool.main(unfrozen, clock=clock) == 3
    assert "UNFROZEN" in capsys.readouterr().err
