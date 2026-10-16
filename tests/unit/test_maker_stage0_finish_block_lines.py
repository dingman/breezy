"""MAKER-S2 second look C5r: ``finish`` passes the block lines to both report renderers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from scripts.analysis import maker_stage0_finish as fin
from scripts.analysis import maker_stage0_verdict as vd

_HOLD, _D5 = "SENTINEL-HOLDOUT-LINE", "SENTINEL-D5-LINE"
_PINS = {
    "git_commit": "c0",
    "amendment_final_sha256": "a0",
    "truth_csv_sha256_frozen_block": "t0",
    "nbp_consumed": {"sha256": "n0"},
    "installed_package_set_sha256": "p0",
    "ledger_path": "ledger",
    "theta_pin_site": "fees.py",
    "sidecars": {},
}


def _stub_world(monkeypatch: pytest.MonkeyPatch, *, stop: bool) -> None:
    def tables(*_a: Any, **_k: Any) -> dict[str, str]:
        if stop:
            raise vd.NoBidBearingDays("no bid-bearing days")
        return {"s3": '{"verdict": "V"}'}

    monkeypatch.setattr(fin, "block_lines", lambda _frozen: (_HOLD, _D5))
    monkeypatch.setattr(
        fin,
        "report",
        SimpleNamespace(score=lambda **_k: SimpleNamespace(sd_rows=[]), no_final_days=lambda _r: 0),
    )
    monkeypatch.setattr(fin, "_write_tables", lambda *_a: None)
    monkeypatch.setattr(fin, "pin_sources", lambda *_a: None)
    monkeypatch.setattr(fin, "pin_inputs", lambda _s: None)
    monkeypatch.setattr(fin, "seal_sidecars", lambda _i, _d: dict(_PINS))
    monkeypatch.setattr(fin, "_extra_pins", lambda *_a: {})
    monkeypatch.setattr(fin, "write_pins", lambda *_a: None)
    monkeypatch.setattr(fin, "tables_from_csvs", tables)
    monkeypatch.setattr(fin, "load_trade_unit", lambda _p: SimpleNamespace(hypotheses=list))
    monkeypatch.setattr(fin.modes, "write_manifest", lambda *_a, **_k: None)
    monkeypatch.setattr(
        fin.render,
        "render_report",
        lambda *_a, holdout_line, d5_line, **_k: f"{holdout_line}\n{d5_line}\n",
    )


def _run(tmp_path: Path) -> str:
    cfg = SimpleNamespace(
        out_dir=tmp_path, need=lambda k: tmp_path / k, truth_cross_check=None, tail_csv=None
    )
    pre = SimpleNamespace(frozen=object(), code_sha="c0", census=SimpleNamespace(values=list))
    out = SimpleNamespace(
        rows={"primary": []},
        seeds={},
        consumed=[],
        abstentions={},
        rounding={},
        listing_abstained=(),
        unknown_delta=0,
        parity=None,
    )
    manifest = SimpleNamespace(write=lambda _p: None)
    fin.finish(cfg, pre, out, manifest, [])  # type: ignore[arg-type]
    return (tmp_path / "report.md").read_text(encoding="utf-8")


def test_finish_passes_block_lines_to_the_normal_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_world(monkeypatch, stop=False)
    text = _run(tmp_path)
    assert _HOLD in text and _D5 in text


def test_finish_passes_block_lines_to_the_s4_stop_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_world(monkeypatch, stop=True)
    text = _run(tmp_path)
    assert f"{_HOLD}\n" in text and _D5 in text
    assert fin.render.STOP_S4 in text
