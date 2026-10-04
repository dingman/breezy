"""The manual family-halt CLIs accept the live ``forecast_quantile_ladder``
family (SAFETY: the only live family had no working manual stop).

End to end through the REAL halt key: the CLI writes, then the FQ strategy's
own ``try_submit`` guard -- fed by ``family_halt_submit_veto`` over a latch
opened exactly as ``app/trade.py`` opens it for FQ (``FORECAST_QUANTILE_TRIAL_
KEY_PREFIX``) -- refuses. Every store here is a ``tmp_path`` store; the live
store and the real data root are never touched.
"""

from __future__ import annotations

import io
import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from breezy.runtime.exec_state_db_path import EXEC_STATE_DB_ENV_VAR
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.clear_family_halt_cli import main as clear_main
from breezy.strategy.current_rung_hold.composition import family_halt_submit_veto
from breezy.strategy.current_rung_hold.family_id_arg import (
    HALTABLE_COMPOSITION_KINDS,
    KINDS_WITH_EXIT_PATH,
)
from breezy.strategy.current_rung_hold.set_family_halt_cli import main as set_main
from breezy.strategy.current_rung_hold.trial_day_latch import (
    family_halt_key,
    open_trial_day_latch,
)
from breezy.strategy.forecast_quantile_ladder.persistent_latch import (
    FORECAST_QUANTILE_TRIAL_KEY_PREFIX,
)
from tests.strategy.forecast_quantile_ladder.test_strategy import _build, _open_permit, _take

FQ_FAMILY_ID = "pm_us_crh_fq_v1"
REASON = "operator manual stop of the forecast quantile ladder family"
EXIT_OK = 0
EXIT_REFUSED = 2


def _env(store_path: Path) -> dict[str, str]:
    return {EXEC_STATE_DB_ENV_VAR: str(store_path)}


def _evidence(tmp_path: Path) -> Path:
    path = tmp_path / "evidence.txt"
    path.write_text("fq halt evidence\n", encoding="utf-8")
    return path


def _flat() -> dict[str, Any]:
    return {"positions": {}, "eof": True}


def _open_reader(count: int = 5) -> Callable[[], dict[str, Any]]:
    def _reader() -> dict[str, Any]:
        slugs = (f"KSFO-2026-10-05-HIGH-{70 + i}" for i in range(count))
        return {"positions": {slug: {"netPosition": "1"} for slug in slugs}, "eof": True}

    return _reader


def _failing_reader() -> dict[str, Any]:
    raise ConnectionError("no route to venue")


def _set(
    tmp_path: Path,
    store_path: Path,
    family_id: str = FQ_FAMILY_ID,
    *extra: str,
    reader: Callable[[], dict[str, Any]] = _flat,
) -> tuple[int, str]:
    err = io.StringIO()
    code = set_main(
        [
            "--family-id", family_id, *extra,
            "--reason", REASON,
            "--evidence-path", str(_evidence(tmp_path)),
        ],
        env=_env(store_path),
        stdout=io.StringIO(),
        stderr=err,
        positions_reader=reader,
        proc_root=Path(tempfile.mkdtemp()),
    )
    return code, err.getvalue()


def _clear(tmp_path: Path, store_path: Path, family_id: str = FQ_FAMILY_ID) -> tuple[int, str]:
    err = io.StringIO()
    code = clear_main(
        [
            "--family-id", family_id,
            "--reason", REASON,
            "--evidence-path", str(_evidence(tmp_path)),
        ],
        env=_env(store_path),
        stdout=io.StringIO(),
        stderr=err,
    )
    return code, err.getvalue()


def _fq_try_submit(store_path: Path) -> str | None:
    """The FQ strategy's own guard, with the veto built the way trade.py builds it."""
    store = SqliteStateStore(store_path)
    try:
        with open_submit_intent_latch(store, store_path) as intent_latch:
            halt_latch = open_trial_day_latch(
                intent_latch,
                key_prefix=FORECAST_QUANTILE_TRIAL_KEY_PREFIX,
                family_id=FQ_FAMILY_ID,
            )
            veto: Callable[[], str | None] = family_halt_submit_veto(halt_latch)
            strategy = _build(order_submission_permit=_open_permit(), submit_veto=veto)
            return strategy.try_submit(_take())
    finally:
        store.close()


def test_fq_set_then_the_fq_strategy_veto_refuses_a_submit(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    SqliteStateStore(store_path).close()
    assert _fq_try_submit(store_path) is None

    code, err = _set(tmp_path, store_path)

    assert code == EXIT_OK, err
    assert _fq_try_submit(store_path) == "family_halt"
    store = SqliteStateStore(store_path)
    assert store.get(family_halt_key(FQ_FAMILY_ID)) is not None
    store.close()


def test_fq_clear_then_the_fq_strategy_veto_admits(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    SqliteStateStore(store_path).close()
    assert _set(tmp_path, store_path)[0] == EXIT_OK
    assert _fq_try_submit(store_path) == "family_halt"

    code, err = _clear(tmp_path, store_path)

    assert code == EXIT_OK, err
    assert _fq_try_submit(store_path) is None


def test_an_unknown_composition_kind_is_still_refused_by_set_and_clear(tmp_path: Path) -> None:
    families = tmp_path / "families"
    families.mkdir()
    real = json.loads(Path("deploy/families/pm_us_crh_fq_v1.json").read_text())
    (families / "pm_us_crh_odd.json").write_text(
        json.dumps(dict(real, family_id="pm_us_crh_odd", composition_kind="forecast_ladder"))
    )
    store_path = tmp_path / "state.db"
    SqliteStateStore(store_path).close()

    set_code, set_err = _set(
        tmp_path, store_path, "pm_us_crh_odd", "--families-dir", str(families)
    )
    clear_err = io.StringIO()
    clear_code = clear_main(
        [
            "--family-id", "pm_us_crh_odd",
            "--families-dir", str(families),
            "--reason", REASON,
            "--evidence-path", str(_evidence(tmp_path)),
        ],
        env=_env(store_path),
        stdout=io.StringIO(),
        stderr=clear_err,
    )

    assert (set_code, clear_code) == (EXIT_REFUSED, EXIT_REFUSED)
    assert "forecast_ladder" in set_err
    assert "forecast_ladder" in clear_err.getvalue()
    store = SqliteStateStore(store_path)
    assert store.get(family_halt_key("pm_us_crh_odd")) is None
    store.close()


def test_the_accepted_composition_kinds_are_pinned_exactly() -> None:
    assert HALTABLE_COMPOSITION_KINDS == frozenset(
        {"continuous_rung_hold", "forecast_quantile_ladder"}
    )


CONTINUOUS_FAMILY_ID = "pm_us_crh_v4"


def test_fq_set_proceeds_with_open_positions_and_the_veto_refuses(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    SqliteStateStore(store_path).close()

    code, err = _set(tmp_path, store_path, reader=_open_reader(5))

    assert code == EXIT_OK, err
    assert _fq_try_submit(store_path) == "family_halt"
    store = SqliteStateStore(store_path)
    raw = store.get(family_halt_key(FQ_FAMILY_ID))
    store.close()
    assert raw is not None
    assert "open_positions_at_halt=5" in json.loads(raw)["detail"]


def test_continuous_set_with_open_positions_is_still_refused(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    SqliteStateStore(store_path).close()

    code, err = _set(tmp_path, store_path, CONTINUOUS_FAMILY_ID, reader=_open_reader(5))

    assert code == EXIT_REFUSED
    assert "verdict=OPEN" in err
    store = SqliteStateStore(store_path)
    assert store.get(family_halt_key(CONTINUOUS_FAMILY_ID)) is None
    store.close()


def test_a_failed_positions_get_refuses_for_both_kinds(tmp_path: Path) -> None:
    for family_id in (FQ_FAMILY_ID, CONTINUOUS_FAMILY_ID):
        store_path = tmp_path / f"{family_id}.db"
        SqliteStateStore(store_path).close()

        code, err = _set(tmp_path, store_path, family_id, reader=_failing_reader)

        assert code == EXIT_REFUSED, family_id
        assert "LIVE_GET_FAILED:ConnectionError" in err
        store = SqliteStateStore(store_path)
        assert store.get(family_halt_key(family_id)) is None
        store.close()


def test_kinds_with_exit_path_is_pinned_exactly_and_within_the_haltable_kinds() -> None:
    assert KINDS_WITH_EXIT_PATH == frozenset({"continuous_rung_hold"})
    assert KINDS_WITH_EXIT_PATH <= HALTABLE_COMPOSITION_KINDS
