"""An out-of-band witness that detects the whole state-DB file being deleted.

Background
----------
``breezy.ingest.gate`` already closes one integrity hole: a bootstrap
sentinel (``gate:__bootstrap__``) stored ALONGSIDE the global UA-trap entry
lets it tell "genuine first boot" apart from "a specific row vanished from
a store that otherwise still answers" -- see
``gate._load_global``/``gate._GLOBAL_BOOTSTRAP_KEY`` and the regression test
``test_a_wiped_global_row_fails_closed_instead_of_laundering_the_ua_trap``.

That fix is explicitly documented (in ``tests/unit/test_ingest_gate.py``) as
**not** solving whole-file deletion: if the entire SQLite file is deleted and
recreated, the sentinel is gone too, and "everything was wiped" becomes
indistinguishable from "nothing was ever written" through the store's own
``get``/``set`` alone. A witness stored inside the medium cannot survive
that medium's destruction -- this is a structural limit, not an oversight.

What this module adds
----------------------
A second witness, stored OUTSIDE the state-DB file, at a path derived from
``catalog_base`` (a directory the deployment already owns, and -- whenever
``BREEZY_STATE_DB`` is set independently of ``BREEZY_CATALOG_BASE`` -- a
genuinely separate filesystem path from the state DB). At the first
successful store open it never saw before, this module stamps BOTH a key
inside the store and a marker file outside it. On every later open:

* Witness key present in the store -> this store has been through this
  check before and is still the same store. Nothing to do (the file is
  re-stamped if it went missing, to restore the pairing for next time).
* Witness key absent AND marker file absent -> genuine first boot. Stamp
  both.
* Witness key absent BUT marker file present -> the store answers as if it
  had never been opened before, yet something outside the store remembers
  otherwise. The only way to reach this state is the state-DB file being
  deleted and recreated (or replaced with an empty one) while the
  out-of-band marker survived. This is exactly the case
  ``gate._GLOBAL_BOOTSTRAP_KEY`` cannot see, because by definition every row
  inside the destroyed file -- including its own sentinel -- is gone too.

Rather than inventing a second, parallel BLOCKED/latch mechanism, this
module extends the existing one: on detecting the case above, it replants
``gate._GLOBAL_BOOTSTRAP_KEY`` into the store WITHOUT writing a global
entry. ``SettlementGate._load_global`` already treats "bootstrap sentinel
present, global entry absent" as ``GateReason.STATE_STORE_TAMPERED`` and
fails every site closed until an operator calls
``acknowledge_ua_trap_resolved()`` -- the identical, already-tested recovery
path the row-deletion fix uses. No new latch, no new acknowledgement verb,
no new failure mode for an operator to learn.

``gate.py`` is read-only for this change; ``_GLOBAL_BOOTSTRAP_KEY`` is
imported directly (not duplicated as a literal) so the two modules can never
drift apart silently -- if gate.py ever renames or removes that constant,
this module fails to import rather than silently comparing against a stale
string.

Residual limit (stated plainly, not oversold)
----------------------------------------------
An actor who deletes BOTH the state-DB file AND this witness file (or
recreates both from a stale backup taken together) is still undetectable --
two independent out-of-band witnesses stored at the SAME path pair every
time are, from the outside, just one witness. What this closes is the
common real-world case: a botched restore or deletion of the DB file alone,
leaving anything else on the host (including this marker) untouched. It
raises the bar from "delete one file" to "delete two files in two different
locations", nothing more.
"""

from __future__ import annotations

import logging
from pathlib import Path

from breezy.ingest.gate import _GLOBAL_BOOTSTRAP_KEY as _GATE_GLOBAL_BOOTSTRAP_KEY
from breezy.ingest.gate import StateStore

logger = logging.getLogger(__name__)

#: This module's own out-of-band bookkeeping key, in a namespace disjoint
#: from ``gate:`` and ``productidx:`` and from ``durability:probe`` -- it
#: must never collide with real state any other module reads.
WITNESS_STORE_KEY = "runtime:bootstrap_witness"

#: The marker file's name, placed directly under ``catalog_base``. Hidden
#: (leading dot) and named distinctly from ``persistence.catalog``'s
#: ``.breezy-writer.lock`` so the two can never be confused on disk.
WITNESS_FILENAME = ".breezy-bootstrap-witness"

#: Bytes stamped into both the store key and the marker file. The value
#: carries no meaning beyond "this checkpoint ran" -- callers must not parse
#: it.
_WITNESS_VALUE = b"1"


def witness_file_path(catalog_base: Path | str) -> Path:
    """Return the out-of-band witness marker's path for ``catalog_base``."""
    return Path(catalog_base) / WITNESS_FILENAME


def enforce_bootstrap_witness(store: StateStore, *, catalog_base: Path | str) -> None:
    """Detect whole-state-DB-file deletion and fail the gate closed.

    Call once per process, against the SAME store the gate and the product
    index will use, before either is constructed. Never raises on the
    tampered path -- it instead arranges for
    ``SettlementGate.status()``/``require_open()`` to report
    ``GateReason.STATE_STORE_TAMPERED`` and BLOCK every site, exactly as the
    already-shipped row-deletion fix does, so operators have exactly one
    recovery verb (``acknowledge_ua_trap_resolved()``) to learn regardless
    of which of the two tamper shapes they hit.
    """
    marker = witness_file_path(catalog_base)
    store_has_witness = store.get(WITNESS_STORE_KEY) is not None
    marker_exists = marker.exists()

    if store_has_witness:
        # Continuing store: this check has run against it before. Restore
        # the marker if it went missing so the pairing is intact for next
        # time -- this is bookkeeping repair, not a tamper verdict, because
        # the store itself already proves continuity.
        if not marker_exists:
            _stamp_marker(marker)
        return

    if not marker_exists:
        # Genuine first boot: neither witness has ever been written. Stamp
        # both, in this order -- the store write is the durable half; if the
        # process dies between the two, the next boot sees a store witness
        # with no marker file and simply repairs the marker above, rather
        # than a marker with no store witness, which would misread an
        # ordinary crash as tampering.
        store.set(WITNESS_STORE_KEY, _WITNESS_VALUE)
        _stamp_marker(marker)
        return

    # Store witness absent, marker present: the store answers as though it
    # were never opened before, yet something outside it remembers
    # otherwise. Replant the gate's own bootstrap sentinel (no global entry)
    # so `SettlementGate._load_global` fails every site closed under
    # STATE_STORE_TAMPERED via its own, already-tested logic.
    logger.critical(
        "runtime: out-of-band bootstrap witness at %s exists but the state "
        "store has no record of ever being checked before -- this is not "
        "first boot, the state-DB file was deleted and recreated. Failing "
        "closed: replanting the gate bootstrap sentinel so every site "
        "BLOCKS under STATE_STORE_TAMPERED until an operator investigates "
        "and calls acknowledge_ua_trap_resolved().",
        marker,
    )
    store.set(_GATE_GLOBAL_BOOTSTRAP_KEY, _WITNESS_VALUE)
    store.set(WITNESS_STORE_KEY, _WITNESS_VALUE)
    _stamp_marker(marker)


def _stamp_marker(marker: Path) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(_WITNESS_VALUE)
