"""One-writer data for ``test_autonomy_files_have_one_writer`` (ARCH-0 seam A; L-50).

Two tables, both data. Wave 1 owners extend them in the commit that adds the writer.

``AUTONOMY_FILE_WRITERS`` documents which mechanism owns each autonomy path (seam A "One writer
(L-50)" table). ``WRITE_SITE_ALLOWLIST`` is what the AST scan enforces: a filesystem write site in
autonomy code that is not inside one of these (module, function) pairs fails.

Module-level rows and function-level rows differ on purpose. ``registry_store`` owns its SQLite file
and journal and is allowed as a whole module. ``single_read`` is allowed only inside the named
functions (and the private helpers they call), so a new write path in that module still fails.

Entries for code that has not landed (``ensure_dir``, ``registry_store``,
``live_orders_gate._verify_ruling_file``) are accepted while absent: an allowlist row matching no
site never fails the scan. They are named now so the owner who lands the code does not have to widen
the gate to ship it.
"""

from __future__ import annotations

from typing import Final, NamedTuple

__all__ = [
    "AUTONOMY_FILE_WRITERS",
    "WRITE_MECHANISMS",
    "WRITE_SITE_ALLOWLIST",
    "FileWriter",
    "WriteSiteRule",
]

#: The mechanisms a path row may name.
WRITE_MECHANISMS: Final[frozenset[str]] = frozenset(
    {
        "engine_lock_store",  # registry_store, under registry/engine.lock
        "write_once",  # single_read.write_once
        "write_root_copy",  # family_bytes.write_root_copy (6d)
        "write_monotone",  # hwm.write_monotone, under the intent flock (7e)
    }
)


class FileWriter(NamedTuple):
    path: str
    writers: str
    mechanism: str


AUTONOMY_FILE_WRITERS: Final[tuple[FileWriter, ...]] = (
    FileWriter(
        "registry/registry.sqlite",
        "the engine and the HWM-reset CLI, under registry/engine.lock",
        "engine_lock_store",
    ),
    FileWriter(
        "evidence/registry/registry_<venue>_<date>[_hwm<k>].jsonl",
        "the engine and the reset CLI",
        "write_once",
    ),
    FileWriter("evidence/registry/hwm_reset_<ts>.json", "the reset CLI", "write_once"),
    FileWriter("derived/verdicts/**", "producers", "write_once"),
    FileWriter(
        "registry/demand/<venue>/*", "the engine and DEMAND_WRITER_PRODUCER_IDS", "write_once"
    ),
    FileWriter("evidence/journal/<venue>/<kind>/<seq>.json", "the engine", "write_once"),
    FileWriter(
        "derived/artefacts/<model_class>/<sha>/{artefact.json,roots/<family_id>.json}",
        "the engine bootstrap; AUT-3 refits write into a fresh <sha>/ only",
        "write_root_copy",
    ),
    FileWriter(
        "exec-store key autonomy/registry_hwm/<venue>",
        "the node (boot and ticks) and the L1 cut-over, through hwm.write_monotone under the "
        "intent flock; the reset CLI is the only bypass",
        "write_monotone",
    ),
)


class WriteSiteRule(NamedTuple):
    """Write sites are allowed in ``module`` inside ``function`` (any function if ``None``).

    ``function`` matches a qualified name (``Class.method``) exactly or as an enclosing prefix, so a
    closure inside an allowed function is allowed too.
    """

    module: str
    function: str | None
    reason: str
    #: A transitional row names who retires it and what replaces it (ruling A4-R4); a permanent
    #: row leaves both empty.
    owner: str = ""
    closing: str = ""


_SINGLE_READ: Final = "breezy.persistence.autonomy.single_read"

WRITE_SITE_ALLOWLIST: Final[tuple[WriteSiteRule, ...]] = (
    WriteSiteRule(_SINGLE_READ, "write_once", "the one write-once publisher (AC 7)"),
    WriteSiteRule(_SINGLE_READ, "replace_atomic", "the one atomic replacer (AC 7)"),
    WriteSiteRule(
        _SINGLE_READ, "write_once_tmpfile", "the O_TMPFILE write-once publisher (A5b-R4)"
    ),
    WriteSiteRule(_SINGLE_READ, "ensure_dir", "the one directory creator (not yet landed)"),
    # Private helpers of the three entries above. They hold the actual os.open / os.link /
    # os.replace / os.unlink calls and are named so a new helper needs a reviewed row.
    WriteSiteRule(_SINGLE_READ, "_write_temp", "write_once and replace_atomic temp file"),
    WriteSiteRule(_SINGLE_READ, "_finish", "write_once and replace_atomic temp cleanup"),
    WriteSiteRule(_SINGLE_READ, "_cleanup_temp", "write_once and replace_atomic temp cleanup"),
    WriteSiteRule(_SINGLE_READ, "_link_temp", "write_once hard-link publish"),
    # Transitional: walk_dirs(create=True) creates directories itself until ensure_dir lands.
    # test_walk_dirs_mkdir_row_retired (strict xfail, owner 6d) forces this row's removal.
    WriteSiteRule(
        _SINGLE_READ,
        "walk_dirs",
        "create=True mkdir; superseded by ensure_dir",
        owner="ARCH-0 6d",
        closing="replace by single_read.ensure_dir",
    ),
    WriteSiteRule(
        "breezy.persistence.autonomy.registry_store",
        None,
        "owns registry.sqlite under registry/engine.lock (seam 6e; not yet landed)",
    ),
    WriteSiteRule(
        "breezy.persistence.live_orders_gate",
        "_verify_ruling_file",
        "the one named exemption: a move-only extraction (AC 7; not yet landed)",
    ),
)
