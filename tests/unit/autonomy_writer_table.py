"""One-writer data for ``test_autonomy_files_have_one_writer`` (ARCH-0 seam A; L-50).

Two tables, both data. Wave 1 owners extend them in the commit that adds the writer.

``AUTONOMY_FILE_WRITERS`` documents which mechanism owns each autonomy path (seam A "One writer
(L-50)" table). ``WRITE_SITE_ALLOWLIST`` is what the AST scan enforces: a filesystem write site in
autonomy code that is not inside one of these (module, function) pairs fails.

Module-level rows and function-level rows differ on purpose. ``registry_store`` owns its SQLite file
and journal and is allowed as a whole module. ``single_read`` is allowed only inside the named
functions (and the private helpers they call), so a new write path in that module still fails.

Entries for code that has not landed (``live_orders_gate._verify_ruling_file``) are accepted while
absent: an allowlist row matching no site never fails the scan. They are named now so the owner
who lands the code does not have to widen the gate to ship it.
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
        "native_stream_writer",  # AUT-1: one boot's StreamingFeatherWriter (E-7 rule 4)
        "replace_atomic",  # single_read.replace_atomic, under the owning unit's own lock
        "append_fsync",  # AUT-6 health: fsynced O_APPEND sample line, under its own lock
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
    # AUT-1 WP1 part B (L-12): the capture stream and the epoch file. Plan r12 sections 3.4.2, 3.15.
    FileWriter(
        "derived/capture_stream/<venue>/<source>/<instance_id>/<table>_<ts_ns>.feather",
        "the boot's one native StreamingFeatherWriter, owned by CaptureStreamWriter (a fresh "
        "instance_id per boot, so no two processes share a directory)",
        "native_stream_writer",
    ),
    FileWriter(
        "evidence/capture/epoch/<family_id>.json",
        "the first composing boot, through capture_epoch.write_epoch_once",
        "write_once",
    ),
    # AUT-1 WP5-B (plan r12 section 3.12): the settlement unit is the only writer.
    FileWriter(
        "<decisions_dir>/settlement_<climate_day>.jsonl",
        "breezy-capture-settlement (analysis.capture_settlement), rewritten whole through "
        "single_read.replace_atomic under .capture_settlement.lock; the node never writes it",
        "replace_atomic",
    ),
    # AUT-1 WP5 stage 2a (plan r12 sections 3.11.4, 3.13): the daily audit unit is the only writer
    # of its per-day audit files and of its own E-8 cache directory.
    FileWriter(
        "evidence/capture/audit/<family>/<D>[_<ts_ns>].json",
        "breezy-capture-audit (analysis.capture_audit.write_audit_file), write-once, mode 0444; a "
        "re-audit writes a new <ts_ns> name and the newest wins",
        "write_once",
    ),
    FileWriter(
        "cache/capture_audit/<key>",
        "breezy-capture-audit (analysis.capture_audit_inputs.write_scan_cache): per-log reducer "
        "outputs of an immutable rotated log, replaced atomically; never read as evidence",
        "replace_atomic",
    ),
    # AUT-1 WP5 stage 3a (design r3 D5-D8, S3-R16, S3-R35): the stage-3 writers. The rows name the
    # one writer of each path; the code lands with S1, S2 and 3c, which add their write-site rows.
    FileWriter(
        "evidence/capture/heal/<kill_date>/<kill_ts_ns>_audit_breezy-quote-tape.json",
        "breezy-capture-audit (analysis.capture_heal_io), write-once, mode 0444: the recorder's "
        "watchdog heal, taken at first write (a rerun is a no-op)",
        "write_once",
    ),
    FileWriter(
        "evidence/capture/heal_alert_abandoned/<heal_sha|gap_key>.json",
        "breezy-capture-audit (analysis.capture_heal_io), write-once, written only after a "
        "delivered=true record of the abandon alert",
        "write_once",
    ),
    FileWriter(
        "evidence/capture/live_proof/live_proof_<family>_<asof>.json",
        "breezy-capture-live-proof (analysis.capture_live_proof_cli), replaced atomically at 0444",
        "replace_atomic",
    ),
    FileWriter(
        "evidence/capture/live_proof/sent/<asof>/<event>_<family>.json",
        "breezy-capture-live-proof (analysis.capture_live_proof_cli), write-once, written only "
        "after accepted=True: the per-asof dedupe of the dead-man alerts",
        "write_once",
    ),
    # AUT-2 r7 WP2 (plan section 3.2.2): the C2 label store. The file is published through
    # single_read.write_once; the one parquet serialisation site writes to an in-memory buffer.
    FileWriter(
        "derived/labels/<family_id>/labels_<now_ns>.parquet",
        "the label run (analysis.labeling.label_run), under the studies flock, once per run "
        "through label_store.write_labels",
        "write_once",
    ),
    # AUT-2 r7 WP2 (plan section 3.12): the unresolved-fill journal, written once per label run
    # through single_read.write_once (attribution.write_unresolved_journal).
    FileWriter(
        "evidence/aut2/unresolved/<day>/<now_ns>_label_run.json",
        "the label run (analysis.labeling.label_run), once per run with unresolved fills, through "
        "attribution.write_unresolved_journal",
        "write_once",
    ),
    # AUT-2 r7 WP5 (plan section 3.2.2): the position-compare, lock-skip and CRITICAL-dedup
    # journals.
    # Each file is created once through skip_journal.write_json_once -> single_read.write_once.
    FileWriter(
        "evidence/aut2/position_compare/<day>/<snapshot_ns>_<mode>.json",
        "recon_run (intraday and post_stop) under the reconcile lock, once per snapshot through "
        "reconcile.write_position_compare",
        "write_once",
    ),
    FileWriter(
        "evidence/aut2/skips/<day>/<now_ns>_<unit>.json",
        "the --record-skip path of label_run and recon_run (no lock; the name is unique by now_ns) "
        "through skip_journal.record_skip",
        "write_once",
    ),
    FileWriter(
        "evidence/aut2/critical_dedup/<day>/<key_sha>.json",
        "the three AUT-2 entrypoints, each under the lock it holds, only after a delivered proof, "
        "through delivery.deliver_critical; an O_EXCL loser treats the key as delivered (L3)",
        "write_once",
    ),
    # AUT-2 r7 WP6 (plan sections 3.2.2 and 3.12): the run marker, the label-hold journal and the
    # measured-peak artefact. Each goes through single_read.write_once (label_store.write_marker,
    # skip_journal.write_json_once); the marker is always the last write of a run.
    FileWriter(
        "derived/label_outcomes/<day>/marker_<now_ns>.json",
        "the label run (analysis.labeling.label_core), under the studies flock, last write of a "
        "run, through label_store.write_marker; never written on exit 1",
        "write_once",
    ),
    FileWriter(
        "evidence/aut2/holds/<day>/<now_ns>_label-outcomes.json",
        "the label unit's memory-gate hold path (analysis.labeling.label_run.run_unit), under the "
        "studies flock, through memory_gate.record_hold",
        "write_once",
    ),
    FileWriter(
        "evidence/aut2/memory/label_run_peak_<now_ns>.json",
        "label_run --measure-peak, once per measurement under --output-root only, through "
        "skip_journal.write_json_once",
        "write_once",
    ),
    # AUT-2 r7 WP8 (plan sections 3.2.2, 3.8, 6): the canary path and the live-proof artefact. All
    # three go through single_read.write_once (write-once); the canary day file is written whole,
    # never appended, so no raw write site exists.
    FileWriter(
        "derived/canary/<venue>/canary_fills_<YYYY-MM-DD>.jsonl",
        "label_run --canary (analysis.labeling.label_run), under the studies flock, only on a UTC "
        "day with zero real fills, through canary_store.write_canary_fills",
        "write_once",
    ),
    FileWriter(
        "derived/labels_canary/<family_id>/labels_<now_ns>.parquet",
        "label_run --canary, through label_store.write_labels with the canary labels directory; "
        "never read by a consumer of labels/",
        "write_once",
    ),
    FileWriter(
        "evidence/aut2_live_proof/window_<start>_<end>.json",
        "label_run --proof-window (analysis.labeling.label_run), inside the label unit, once per "
        "window range through skip_journal.write_json_once",
        "write_once",
    ),
    # AUT-6 WP1 (plan r15 sections 3.6.2, 3.6.3; U3): the delivery journal and the durable outbox.
    # Both are published by alert_outbox._publish (mkstemp, fsync, os.link: write-once, no replace).
    FileWriter(
        "evidence/alerts/<YYYY-MM-DD>/<ts_ns>_<writer>_<d|f>.json",
        "each delivering process writes its own attempt record, under its own writer id "
        "(node, intraday, daily, health, redeliver, canary, check, deadman, engine, probe or "
        "legacy_<component>); alert_outbox.DeliveryRecordWriter, 0600 in 0700 directories",
        "write_once",
    ),
    FileWriter(
        "evidence/alerts/outbox/*.json",
        "create: every originating process through alert_outbox.AlertOutbox.write_entry; claim: "
        "the drainer's utime then rename into outbox/claimed/<drainer>/ (E-1; the originator for "
        "its own entry, the node worker, redeliver, deadman); remove: the current claimant only, "
        "after its delivered record was written",
        "write_once",
    ),
    # AUT-6 WP2 (plan r15 section 3.7.1, F1): the write-once arming marker. Published by
    # alert_outbox.write_armed_marker (mkstemp, fsync, os.link at 0444; EEXIST is success).
    FileWriter(
        "evidence/alerts/armed.json",
        "breezy-autonomy-canary only, after its first delivered canary record, through "
        "alert_outbox.write_armed_marker; never rewritten and never deleted by any code",
        "write_once",
    ),
    # AUT-6 WP3 S3 (plan r15 sections 3.9 and 3.11): the unit health pass. One writer, the
    # breezy-autonomy-health pass (unit_health_store), under evidence/unit_health/.health.lock.
    FileWriter(
        "evidence/unit_health/<YYYY-MM-DD>/{<unit>__<invocation>__class,<unit>__<invocation>__action,"
        "cursor_reset__<ts_ns>}.json",
        "the breezy-autonomy-health pass only (unit_health_store.write_once: mkstemp, fsync, "
        "os.link, 0444; an existing name is reused, never replaced)",
        "write_once",
    ),
    FileWriter(
        "evidence/unit_health/{cursor,heartbeat}.json, day_<YYYY-MM-DD>.json, seen/<unit>.json",
        "the breezy-autonomy-health pass only, under .health.lock "
        "(unit_health_store.replace_atomic: mkstemp, fsync, os.replace, 0600); the cursor is "
        "written last",
        "replace_atomic",
    ),
    FileWriter(
        "evidence/unit_health/memavail_<YYYY-MM-DD>.jsonl",
        "the breezy-autonomy-health pass only, under .health.lock (one fsynced O_APPEND line per "
        "completed pass, F10)",
        "append_fsync",
    ),
    FileWriter(
        "derived/verdicts/health/<family>/** (capture family verdicts only)",
        "breezy-capture-audit and breezy-capture-live-proof write capture-family verdicts into "
        "derived/verdicts and nothing else there (design S3-R16, S3-R35)",
        "write_once",
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
_HOOK: Final = "breezy.runtime.capture_recorder_hook_cli"

WRITE_SITE_ALLOWLIST: Final[tuple[WriteSiteRule, ...]] = (
    WriteSiteRule(_SINGLE_READ, "write_once", "the one write-once publisher (AC 7)"),
    WriteSiteRule(_SINGLE_READ, "replace_atomic", "the one atomic replacer (AC 7)"),
    WriteSiteRule(
        _SINGLE_READ, "write_once_tmpfile", "the O_TMPFILE write-once publisher (A5b-R4)"
    ),
    WriteSiteRule(_SINGLE_READ, "ensure_dir", "the one directory creator (A4-R4)"),
    # Private helpers of the three entries above. They hold the actual os.open / os.link /
    # os.replace / os.unlink calls and are named so a new helper needs a reviewed row.
    WriteSiteRule(_SINGLE_READ, "_write_temp", "write_once and replace_atomic temp file"),
    WriteSiteRule(_SINGLE_READ, "_finish", "write_once and replace_atomic temp cleanup"),
    WriteSiteRule(_SINGLE_READ, "_cleanup_temp", "write_once and replace_atomic temp cleanup"),
    WriteSiteRule(_SINGLE_READ, "_link_temp", "write_once hard-link publish"),
    WriteSiteRule(
        "breezy.persistence.autonomy.registry_store",
        None,
        "owns registry.sqlite under registry/engine.lock (seam 6e)",
    ),
    WriteSiteRule(
        "breezy.persistence.autonomy.registry_export",
        "RegistryReader._connect",
        "the reader's one sqlite3.connect: mode=ro, query_only; export files are written only "
        "through single_read.write_once_tmpfile, so write_export holds no site (seam 6f)",
    ),
    # AUT-1 WP3 step 1 (plan r12 section 3.15 "Recorder stop hook"): the evidence-only hook is the
    # one writer of evidence/capture/stall/ and health/recorder_watchdog/. These are its four
    # write scopes, reviewed in WP3-R3 and confirmed in WP2-R5; a new write path needs a new row.
    WriteSiteRule(_HOOK, "_open_child_dir", "stop hook: 0700 day directory under a dir fd"),
    WriteSiteRule(_HOOK, "_write_once", "stop hook: atomic write-once stall record (link)"),
    WriteSiteRule(_HOOK, "_atomic_replace", "stop hook: health file temp + rename"),
    WriteSiteRule(_HOOK, "_acquire_lock", "stop hook: the per-directory flock file"),
    # AUT-1 WP5-B: the settlement writer's own lock file (the only write site in the module; the
    # data file goes through single_read.replace_atomic).
    WriteSiteRule(
        "breezy.analysis.capture_settlement",
        "_acquire_lock",
        "settlement unit: its own flock file in <decisions_dir>",
    ),
    # AUT-2 r7 WP2: parquet bytes are serialised to an in-memory io.BytesIO; the file itself is
    # published through single_read.write_once (an allowlisted site), never by pyarrow.
    WriteSiteRule(
        "breezy.persistence.autonomy.label_store",
        "_serialise",
        "label/v1 parquet serialised to memory; the file is published by single_read.write_once",
    ),
    WriteSiteRule(
        "breezy.persistence.live_orders_gate",
        "_verify_ruling_file",
        "the one named exemption: a move-only extraction (AC 7; landed in seam 8a)",
    ),
    # AUT-1 WP5 stage 2b W3: the audit's three read-only ``journalctl`` calls (one per template; the
    # closure lint pins each argv, its time slots the validated names ``since`` and ``until``).
    WriteSiteRule(
        "breezy.analysis.capture_audit_host",
        "_run_template",
        "audit unit: the three literal journalctl argvs, read-only (closure lint row argvs)",
    ),
)
