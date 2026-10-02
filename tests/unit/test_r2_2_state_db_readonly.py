"""R2.2: the state-db reader still opens SQLite ``mode=ro`` and cannot write.

A ``continuous_rung_hold/`` store with zero census latches returns empty. The
connect the reader actually makes is a ``mode=ro`` URI, and a write on that
same URI raises ``sqlite3.OperationalError``.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from breezy.analysis.prereg_admission import read_filled_trials_state_db


def test_state_db_reader_opens_mode_ro_and_cannot_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "exec-state.sqlite"
    setup = sqlite3.connect(db)
    setup.execute("CREATE TABLE state (key TEXT PRIMARY KEY, value BLOB)")
    setup.commit()
    setup.close()

    seen: list[tuple[str, bool]] = []
    real_connect = sqlite3.connect

    def spy(target: str, *, uri: bool) -> sqlite3.Connection:
        seen.append((target, uri))
        return real_connect(target, uri=uri)

    # `_open_readonly` looks `sqlite3` up on the stdlib module, so patching
    # that module is the connect the reader makes.
    monkeypatch.setattr(sqlite3, "connect", spy)

    result = read_filled_trials_state_db(
        db,
        family_prefix="continuous_rung_hold/trial/",
        city="unused",
        cli_location="unused",
        since_climate_day="2026-01-01",
        stations=("UNUSED",),
    )
    assert result == ((), (), {}, {})
    assert seen == [(f"file:{db.as_posix()}?mode=ro", True)]

    write_conn = real_connect(seen[0][0], uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            write_conn.execute("INSERT INTO state (key, value) VALUES ('k', X'00')")
    finally:
        write_conn.close()
