"""SP-1/I3 (2026-09-12): the ingest CLI's per-INSTANCE outcome must surface a
per-TYPE conversion failure truthfully.

Before this item, ``ingest_instance`` (``src/breezy/runtime/quote_tape_ingest_cli.py:766-805``)
logged a per-type ``ValueError`` (the native non-disjoint-interval refusal,
e.g. a republished-but-different range) as that type's own ``"failed"``
outcome, but then returned ``InstanceIngestResult(..., outcome="converted")``
UNCONDITIONALLY -- so ``run()``'s own check (``any(result.outcome ==
"failed" for result in results)``, ``:1342-1344``) never saw the failure and
the unit reported ``EXIT_OK`` (``systemd: Finished``) for a run that silently
dropped data. The sibling function ``_ingest_instance_per_file`` already
computed this correctly (``:1101-1115``) -- I3 makes ``ingest_instance``
match that existing precedent with the same one-statement shape, via the
existing ``_outcome_has_failure`` helper (``:826-833``).

``test_a_republished_overlapping_interval_reproduces_the_non_disjoint_refusal``
is a CONTRACT-style test on the NATIVE mechanism itself (A-13): it pins the
captured 2026-09-11 LAX collision as literal nanosecond intervals over a
minimal ``QuoteTick`` batch written directly via ``ParquetDataCatalog.write_data``
in a `tmp_path`-scoped catalog -- the production catalog
(``213d84f7-248c-4070-91fe-fa445b8c4327`` under
``~/.local/share/breezy/catalog/quote_tape/polymarket_us/live/``, an
actively rotating ~492 MB directory) is never opened. `skip_disjoint_check=True`
(``parquet.py:309,364``) exists natively and is deliberately never used here
-- it would admit overlapping intervals, the opposite of what this test
guards.
"""

from __future__ import annotations

import io
import os
import time
from pathlib import Path

import pytest
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.test_kit.providers import TestInstrumentProvider

from breezy.runtime.quote_tape_ingest_cli import (
    DEFAULT_LIVE_GRACE_MINUTES,
    EXIT_CONVERSION_FAILED,
    run,
    run_ingest,
)
from breezy.runtime.quote_tape_preflight_cli import CATALOG_ENV_VAR

_INSTANCE = "instance-1"

# A-12: the captured 2026-09-11 LAX collision. On disk under
# data/quote_tick/tc-temp-laxhigh-2026-09-11-gte84lt85f.POLYMARKET_US/, the
# EXISTING file is
# "...T00-00-04-539130527Z_2026-09-11T00-15-38-149459762Z.parquet"
# (5,415 B) = interval (1789084804539130527, 1789085738149459762). The
# INCOMING range that collided with it is (1789084804539130527,
# 1789117220353565962) -- same start, later end -- present on disk only
# under mark_price_update/ and custom_venue_settlement_snapshot/, never as a
# quote_tick parquet (that write is exactly the one this refusal blocked).
_EXISTING_INTERVAL = (1789084804539130527, 1789085738149459762)
_INCOMING_INTERVAL = (1789084804539130527, 1789117220353565962)


def _touch_feather(catalog_root: Path, instance_id: str, name: str) -> Path:
    """A zero-byte placeholder feather file, aged past the live-grace
    window -- this module never opens a real Arrow stream; the conversion
    itself is monkeypatched (tests 1-2) or bypassed entirely (test 3)."""
    path = catalog_root / "live" / instance_id / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    stamp = time.time() - (DEFAULT_LIVE_GRACE_MINUTES + 5) * 60
    os.utime(path, (stamp, stamp))
    return path


def _never_active() -> bool:
    return False


def _quote_tick_at(ts_ns: int) -> QuoteTick:
    instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD")
    return QuoteTick(
        instrument_id=instrument.id,
        bid_price=Price.from_str("1.00000"),
        ask_price=Price.from_str("1.00010"),
        bid_size=Quantity.from_int(1),
        ask_size=Quantity.from_int(1),
        ts_event=ts_ns,
        ts_init=ts_ns,
    )


def _raise_non_disjoint(
    self: ParquetDataCatalog, instance_id: str, data_cls: type, **kwargs: object
) -> None:
    raise ValueError("would create non-disjoint intervals")


def test_a_whole_instance_run_with_one_failed_type_reports_outcome_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The core I3 fix: before this item, this assertion was FALSE -- the
    instance-level outcome was unconditionally "converted" regardless of a
    per-type failure logged one line above it."""
    _touch_feather(tmp_path, _INSTANCE, "quote_tick_1.feather")
    monkeypatch.setattr(ParquetDataCatalog, "convert_stream_to_data", _raise_non_disjoint)

    results = run_ingest(tmp_path, data_types=(QuoteTick,), service_active_probe=_never_active)

    assert len(results) == 1
    assert results[0].type_results[0].outcome == "failed"
    assert results[0].outcome == "failed"
    assert results[0].reason != ""


def test_a_fully_converted_instance_still_reports_outcome_converted(tmp_path: Path) -> None:
    """Positive control (L-24): I3 must not over-report failure. A run with
    no injected failure must still report "converted", exactly as before."""
    _touch_feather(tmp_path, _INSTANCE, "quote_tick_1.feather")

    results = run_ingest(tmp_path, data_types=(QuoteTick,), service_active_probe=_never_active)

    assert len(results) == 1
    assert results[0].type_results[0].outcome == "converted"
    assert results[0].outcome == "converted"
    assert results[0].reason == ""


def test_run_returns_exit_conversion_failed_when_a_whole_instance_type_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: the CLI entrypoint itself must now return
    EXIT_CONVERSION_FAILED for this case -- before I3, `run()`'s own check
    (`any(result.outcome == "failed" ...)`, quote_tape_ingest_cli.py:1342-1344)
    never saw the failure because `ingest_instance` never reported it,
    despite the per-type ValueError already being logged. The sibling
    OnFailure= only becomes reachable once systemd sees a non-zero exit.

    `--service-unit` is pointed at a unit name that cannot exist on any
    host, so `default_service_active_probe`'s real (read-only)
    `systemctl --user is-active` query deterministically reports
    "inactive" regardless of whether this host's OWN
    `breezy-quote-tape.service` happens to be active -- this test must
    never depend on that.
    """
    _touch_feather(tmp_path, _INSTANCE, "quote_tick_1.feather")
    monkeypatch.setattr(ParquetDataCatalog, "convert_stream_to_data", _raise_non_disjoint)

    out, err = io.StringIO(), io.StringIO()
    code = run(
        ["--service-unit", "sp1-test-nonexistent-unit.service"],
        env={CATALOG_ENV_VAR: str(tmp_path)},
        stdout=out,
        stderr=err,
    )

    assert code == EXIT_CONVERSION_FAILED, err.getvalue()


def test_a_republished_overlapping_interval_reproduces_the_non_disjoint_refusal(
    tmp_path: Path,
) -> None:
    """A-13, contract-style: pins the NATIVE mechanism Breezy's ingest
    depends on, not Breezy's own code. If a future Nautilus bump silently
    changes this refusal (relaxes it, or the message shape), this test goes
    red -- never the production catalog, only a two-row hermetic batch
    reproducing the captured 2026-09-11 LAX collision's exact intervals."""
    catalog = ParquetDataCatalog(str(tmp_path))
    existing_start, existing_end = _EXISTING_INTERVAL
    incoming_start, incoming_end = _INCOMING_INTERVAL

    catalog.write_data(
        [_quote_tick_at(existing_start), _quote_tick_at(existing_end)],
        start=existing_start,
        end=existing_end,
    )

    try:
        catalog.write_data(
            [_quote_tick_at(incoming_start), _quote_tick_at(incoming_end)],
            start=incoming_start,
            end=incoming_end,
        )
    except ValueError as exc:
        assert "non-disjoint" in str(exc)
        assert str(existing_start) in str(exc)
    else:
        raise AssertionError(
            "ParquetDataCatalog.write_data no longer refuses a republished, "
            "non-disjoint QuoteTick interval -- the native guard I3 depends "
            "on may have changed"
        )
