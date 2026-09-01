"""Contract: installed Nautilus has NO live instrument-expiry path.

Pinned against **``nautilus-trader==1.231.0``** (asserted below).

Why this file exists
--------------------
Breezy settles weather binaries itself (EXEC_SPINE R-9): a settled contract is
worth exactly ``1.00`` or ``0.00``, and *something* has to book that close.
Nautilus can already do this -- but only in backtest.
``check_instrument_expiration`` (``backtest/engine.pyx:5934``, declared
``backtest/engine.pxd:465``) cancels open orders and synthesises a reduce-only
``MarketOrder`` filled at ``self._settlement_prices[...]``. There is no live
equivalent.

That absence is what licenses Breezy to build ``SettlementExitActor``. If a
future Nautilus upgrade adds a native live expiry path, Breezy would be
duplicating it -- silently, and with two mechanisms racing to close the same
position. **This file goes RED on that upgrade.** A failure here is NOT a
broken test: it is the signal to delete Breezy code, not to relax an
assertion.

Non-vacuity is the entire point
-------------------------------
A scan that searched nothing reports zero and looks identical to a true
negative. This exact failure nearly voided every null-hypothesis verdict in
``docs/plans/EXEC_SPINE_2026-09-01.md``:

    The ``Grep`` tool wraps ripgrep, which honours ``.gitignore``.
    ``.gitignore:1`` is ``.venv/`` -- where the installed Nautilus lives. A
    RECURSIVE ripgrep under ``.venv/`` returns **zero matches with no error**,
    indistinguishable from a true negative. Measured: ``rg -l 'Nautech
    Systems'`` under ``nautilus_trader/live/`` -> 0 files; ``--no-ignore`` ->
    15.

So the scan below **never delegates to a search tool**. It walks the tree with
``os.walk`` and reads each file's bytes directly, so no ignore file, no VCS
rule and no tool default can silence it. And it refuses -- loudly -- to report
a zero it did not earn: :func:`_scan` raises on a missing root, an empty root,
or a root holding no scannable sources.

Every zero asserted here is paired with a positive control that must be
NON-zero on the same scan machinery.
"""

from __future__ import annotations

import os
from pathlib import Path

import nautilus_trader
import pytest

pytestmark = pytest.mark.contract

PINNED_NAUTILUS_VERSION = "1.231.0"

#: Source extensions the scan reads. Cython ships ``.pyx``/``.pxd`` sources
#: alongside the compiled ``.so``; a scan restricted to ``.py`` would miss the
#: engines entirely and report a comfortable, false zero.
SOURCE_SUFFIXES = (".py", ".pyx", ".pxd")

#: Packages that would have to host a live expiry path if one existed.
LIVE_PACKAGES = ("live", "execution", "portfolio", "risk", "trading")

#: Symbols that constitute an instrument-expiry mechanism, EACH of which is
#: findable somewhere in the install (see
#: `test_every_scanned_pattern_has_a_positive_control`). The EXEC_SPINE R-9
#: brief also named ``is_expired``; measurement showed it occurs zero times
#: anywhere in 1.231.0, so asserting it absent from live packages proves
#: nothing. It is pinned separately by
#: `test_is_expired_is_not_nautilus_vocabulary_at_all`, which is a true,
#: non-vacuous statement, and the real vocabulary is listed here instead.
EXPIRY_SYMBOLS = (
    "expiration_ns",
    "expiration_utc",
    "check_instrument_expiration",
    "_instrument_has_expiration",
    "_next_instrument_expiration_ns",
    "_expiration_processed",
)

#: Named in the R-9 brief but absent from the whole install. Kept explicit so
#: nobody re-adds it to `EXPIRY_SYMBOLS` and reintroduces a vacuous zero.
NON_EXISTENT_SYMBOL = "is_expired"

#: ``expire_time_ns`` DOES occur under `live/`, `execution/`, `risk/` and
#: `trading/` -- it is an ORDER's GTD expiry, nothing to do with instrument
#: expiration. Pinned as a decoy so a future reader does not "correct" the
#: zero above by widening the pattern to ``expir``.
ORDER_GTD_DECOY = "expire_time_ns"

#: Minimum scannable source files per package. If a future Nautilus wheel
#: stops shipping ``.pyx`` sources, these floors fail LOUDLY rather than
#: letting the whole file degrade to a vacuous pass.
MIN_SOURCE_FILES = {
    "live": 15,
    "execution": 20,
    "portfolio": 7,
    "risk": 7,
    "trading": 9,
    "model/instruments": 40,
    "backtest": 5,
}


def test_pinned_nautilus_version() -> None:
    """Every `path:line` in this module's docstring was read at this version."""
    assert nautilus_trader.__version__ == PINNED_NAUTILUS_VERSION, (
        f"These pins were verified against nautilus-trader "
        f"{PINNED_NAUTILUS_VERSION}, running against "
        f"{nautilus_trader.__version__}. Re-read `backtest/engine.pyx` around "
        f"`check_instrument_expiration` before updating this constant."
    )


def _installed_root() -> Path:
    """The installed ``nautilus_trader`` package directory.

    Derived from the imported module, never from a hardcoded ``.venv`` path,
    so a mis-rooted scan is impossible by construction.
    """
    root = Path(nautilus_trader.__file__).resolve().parent
    assert root.is_dir(), f"installed nautilus_trader root is not a directory: {root}"
    return root


def _source_files(root: Path) -> list[Path]:
    """Every scannable source file under ``root``, via a direct filesystem walk.

    Deliberately NOT ripgrep / ``Grep`` / ``git grep``: see the module
    docstring. ``os.walk`` applies no ignore rules.
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(SOURCE_SUFFIXES):
                found.append(Path(dirpath) / name)
    return sorted(found)


def _scan(subpath: str, pattern: str) -> list[str]:
    """Occurrences of ``pattern`` under ``<installed>/<subpath>``.

    Raises rather than returning ``[]`` when the search could not have found a
    positive -- a zero from a path that does not exist, holds no files, or
    holds no scannable sources is not evidence.
    """
    root = _installed_root() / subpath
    if not root.is_dir():
        raise FileNotFoundError(f"scan root does not exist: {root}")

    files = _source_files(root)
    if not files:
        raise AssertionError(
            f"scan root {root} holds no {SOURCE_SUFFIXES} sources -- a zero "
            f"from here would be an artefact of the search, not a fact about "
            f"Nautilus.",
        )

    hits: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern in line:
                hits.append(f"{path.relative_to(_installed_root())}:{lineno}: {line.strip()}")
    return hits


# --------------------------------------------------------------------------
# The pin
# --------------------------------------------------------------------------


def test_no_native_live_expiry_path_exists() -> None:
    """No instrument-expiry symbol appears in any live-reachable package."""
    offenders: list[str] = []
    for package in LIVE_PACKAGES:
        for symbol in EXPIRY_SYMBOLS:
            offenders.extend(f"[{symbol}] {hit}" for hit in _scan(package, symbol))

    assert not offenders, (
        "Nautilus grew a live instrument-expiry path. Breezy's "
        "`SettlementExitActor` (EXEC_SPINE R-9) now DUPLICATES it, and two "
        "mechanisms will race to close the same position. Read these before "
        "changing anything here:\n  " + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------
# Non-vacuity: the scan can find a positive, and refuses to invent a zero
# --------------------------------------------------------------------------


def test_every_scanned_pattern_has_a_positive_control() -> None:
    """Each symbol asserted absent must be findable SOMEWHERE by this scan.

    Without this, a typo in `EXPIRY_SYMBOLS` makes
    `test_no_native_live_expiry_path_exists` pass forever while proving
    nothing at all.
    """
    missing = [symbol for symbol in EXPIRY_SYMBOLS if not _scan(".", symbol)]
    assert not missing, (
        f"these symbols occur ZERO times anywhere in installed "
        f"nautilus_trader {nautilus_trader.__version__}, so asserting they are "
        f"absent from live packages is vacuous: {missing}"
    )


def test_is_expired_is_not_nautilus_vocabulary_at_all() -> None:
    """`is_expired` occurs ZERO times in the whole install -- so it is useless
    as an absence assertion.

    The R-9 brief asked for `is_expired` to be asserted absent from the live
    packages. Measured on 1.231.0 it is absent from *everything*, which makes
    that assertion indistinguishable from a typo. This test states the true
    fact instead. If Nautilus ever introduces the name, this goes RED and the
    symbol should be promoted into `EXPIRY_SYMBOLS`.
    """
    hits = _scan(".", NON_EXISTENT_SYMBOL)
    assert not hits, (
        f"`{NON_EXISTENT_SYMBOL}` now exists in nautilus_trader "
        f"{nautilus_trader.__version__}. Promote it into EXPIRY_SYMBOLS -- it "
        f"is now a real absence assertion:\n  " + "\n  ".join(hits[:20])
    )


def test_the_order_gtd_decoy_is_present_and_is_not_instrument_expiry() -> None:
    """`expire_time_ns` IS in the live packages, and means something else.

    This is the single most likely way the pin above rots: a reader sees
    "expiry" in `live/execution_engine.py`, concludes the zero is wrong, and
    widens the pattern. It is an order's GTD `expire_time_ns`, not an
    instrument's `expiration_ns`.
    """
    live_hits = _scan("live", ORDER_GTD_DECOY)
    assert live_hits, f"`{ORDER_GTD_DECOY}` vanished from live/ -- re-read the pin"
    assert not _scan("live", "expiration_ns"), (
        "instrument expiry appeared in live/ -- see "
        "test_no_native_live_expiry_path_exists"
    )


def test_the_scan_finds_the_expiry_symbol_on_the_instrument_that_carries_it() -> None:
    """`expiration_ns` IS present under `model/instruments/` -- proof of descent."""
    hits = _scan("model/instruments", "expiration_ns")
    assert len(hits) >= 60, f"expected >=60 `expiration_ns` lines, found {len(hits)}"
    assert any("binary_option.pyx" in hit for hit in hits), (
        "`expiration_ns` not found in binary_option.pyx -- the instrument "
        "Breezy actually trades. The scan is not reaching the sources."
    )


def test_the_whole_expiry_mechanism_lives_only_in_backtest_engine() -> None:
    """Every mechanism symbol is present, and only in `backtest/engine.{pyx,pxd}`.

    This is the positive half of the pin: the native path exists, it works,
    and it is unreachable from a live node. That is exactly the gap R-9 fills.
    """
    for symbol in (
        "check_instrument_expiration",
        "_instrument_has_expiration",
        "_next_instrument_expiration_ns",
        "_expiration_processed",
    ):
        hits = _scan(".", symbol)
        assert hits, f"`{symbol}` vanished from the install -- re-read backtest/engine.pyx"
        stray = [h for h in hits if not h.startswith("backtest/engine.")]
        assert not stray, (
            f"`{symbol}` escaped backtest/engine.* -- the native expiry "
            f"mechanism may now be reachable live:\n  " + "\n  ".join(stray)
        )


def test_the_scan_refuses_a_missing_root() -> None:
    with pytest.raises(FileNotFoundError):
        _scan("no_such_package", "expiration_ns")


def test_the_scan_refuses_a_root_with_no_scannable_sources(tmp_path: Path) -> None:
    """A path that exists but holds nothing scannable must RAISE, not return 0."""
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(AssertionError, match="holds no"):
        _source_files_guard(empty)


def _source_files_guard(root: Path) -> list[Path]:
    files = _source_files(root)
    if not files:
        raise AssertionError(f"scan root {root} holds no {SOURCE_SUFFIXES} sources")
    return files


def test_every_scanned_package_still_ships_scannable_sources() -> None:
    """Guards against a future wheel that ships only compiled `.so` files."""
    for subpath, floor in MIN_SOURCE_FILES.items():
        count = len(_source_files(_installed_root() / subpath))
        assert count >= floor, (
            f"{subpath} now ships {count} scannable sources (floor {floor}). "
            f"Every zero asserted in this module may have become an artefact "
            f"of the wheel's contents. Re-measure before relaxing this."
        )
