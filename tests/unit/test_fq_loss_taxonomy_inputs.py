"""TE-2 WP0 (RED): the I/O wrappers and gates of the FQ v1 loss taxonomy.

Plan: TE-2_plan_r3_2.md section 5 (WP0 tests 33-46, 48, 49). Offline and synthetic.
Per L-55 each injected fake is paired with a production default path: the real
``NwsCliFinal`` over a tmp Parquet catalog, the real ``SubprocessGit`` over a tmp git repo,
the real ``C1Epoch`` over an empty data root, and the real ``read_durable_fills`` over a store
written by the real writer.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import inspect
import os
import subprocess
import tracemalloc
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from breezy.analysis.labeling.decision_link import parse_log_line, read_log_events
from breezy.analysis.labeling.fill_source import FillStoreCorruption, read_durable_fills
from breezy.analysis.labeling.settlement_source import NwsCliFinal
from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.persistence.catalog import open_station_catalog, write_records
from breezy.runtime.sqlite_store import SqliteStateStore
from scripts.analysis.fq_loss_taxonomy_core import (
    classify_s0d_miss,
    holdout_violations,
    reproduction_gate,
    s0d_compare,
)
from scripts.analysis.fq_loss_taxonomy_inputs import (
    Boot,
    ClippingSettlementSource,
    PhaseAProjection,
    S0ACounts,
    SnapshotShaMismatch,
    SubprocessGit,
    UnclassifiedFillsStop,
    alt_truth_summary,
    attribute_fills,
    iter_partition_events,
    partition_union,
    phase_b_refusals,
    pin_label,
    post_hoc_violations,
    project_phase_a,
    refreeze_status,
    reproduce_audit,
    resolve_pins,
    s0a_counts,
    stream_take_events,
    truth_status,
)
from tests.support.aut2_fixtures import FILL_KEY_PREFIX, seed_fills
from tests.support.te2_fixtures import (
    fq_durable_fills,
    fq_september_fills,
    fq_settlement_records,
    log_filled,
    log_init,
    log_refuse,
    log_take,
    nws_record,
)

_REPO = Path(__file__).resolve().parents[2]
_LAX_YES = "tc-temp-laxhigh-2026-10-02-gte89lt90f.POLYMARKET_US"
_D6, _D7 = dt.date(2026, 10, 6), dt.date(2026, 10, 7)
_SCRIPTS = [
    _REPO / "scripts/analysis/fq_v1_loss_taxonomy.py",
    _REPO / "scripts/analysis/fq_loss_taxonomy_core.py",
    _REPO / "scripts/analysis/fq_loss_taxonomy_inputs.py",
]
#: Reviewed import allowlist (module equals an entry or sits under it). Never ``exec.*``.
_ALLOWED = (
    "__future__", "argparse", "collections", "dataclasses", "datetime", "decimal", "hashlib",
    "itertools", "json", "math", "pathlib", "re", "subprocess", "sys", "typing",
    "breezy.analysis.labeling", "breezy.analysis.nbp_calibration", "breezy.domain.nws_climate_day",
    "breezy.persistence.catalog", "breezy.settlement", "breezy.registry", "breezy.normalize",
    "breezy.strategy.forecast_quantile_ladder", "breezy.strategy.ladder_ev",
    "scripts.analysis",
)  # fmt: skip


def _git(root: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    ident = ["-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
    done = subprocess.run(
        ["git", *ident, *args], cwd=root, env=env, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def _tmp_repo(root: Path, versions: Sequence[str]) -> list[str]:
    """A hermetic repo whose ``manifest.json`` takes each content in turn; the commit shas."""
    _git(root, "init", "-q", "-b", "main")
    commits = []
    for index, content in enumerate(versions):
        (root / "manifest.json").write_text(content)
        _git(root, "add", "manifest.json")
        _git(root, "commit", "-q", "-m", f"v{index}")
        commits.append(_git(root, "rev-parse", "HEAD"))
    return commits


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class _Src:
    def __init__(self, records: dict[tuple[str, dt.date], NwsClimateDay]) -> None:
        self.records = records
        self.asked: list[dt.date] = []

    def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None:
        self.asked.append(climate_day)
        return self.records.get((station, climate_day))


class _CatalogRouter:
    """The production ``NwsCliFinal`` over one real tmp catalog per station."""

    def __init__(self, base: Path, records: Sequence[NwsClimateDay]) -> None:
        self._sources = {}
        for station in sorted({r.station for r in records}):
            catalog = open_station_catalog(base, "polymarket_us", station)
            write_records(catalog, [r for r in records if r.station == station])
            self._sources[station] = NwsCliFinal(catalog)

    def record(self, station: str, climate_day: dt.date) -> NwsClimateDay | None:
        return self._sources[station].record(station, climate_day)


def test_clipping_wrapper_implements_settlement_source_and_clips_after_2026_10_06(
    tmp_path: Path,
) -> None:
    inner = _Src(
        {("LAX", _D6): nws_record("LAX", _D6, 90), ("LAX", _D7): nws_record("LAX", _D7, 91)}
    )
    clip = ClippingSettlementSource(inner, _D6)

    assert clip.record("LAX", _D6) is inner.records[("LAX", _D6)]
    assert clip.record("LAX", _D7) is None
    assert _D7 not in inner.asked  # the clipped day never reaches the inner source
    assert list(inspect.signature(clip.record).parameters) == ["station", "climate_day"]
    # production default path: the real NwsCliFinal over a real tmp catalog
    router = _CatalogRouter(tmp_path, [nws_record("LAX", _D6, 90), nws_record("LAX", _D7, 91)])
    real = ClippingSettlementSource(router, _D6)
    record = real.record("LAX", _D6)
    assert record is not None and record.tmax_f == 90
    assert real.record("LAX", _D7) is None


def test_phase_a_projection_without_tmax_f_passes_when_tmax_f_raises() -> None:
    class Explosive:
        station, climate_day = "LAX", _D6
        is_final, is_superseded, correction_flag, revision_seq = True, False, False, 1

        @property
        def tmax_f(self) -> int:
            raise AssertionError("Phase A read tmax_f")

    projection = project_phase_a(cast(NwsClimateDay, Explosive()))

    assert projection == PhaseAProjection("LAX", _D6, True, False, False, 1)
    assert "tmax_f" not in {f.name for f in dataclasses.fields(PhaseAProjection)}


def test_truth_unsettled_for_flagged_or_superseded_day() -> None:
    def status(**over: Any) -> str:
        return truth_status(project_phase_a(nws_record("LAX", _D6, 90, **over)))

    assert status() == "SETTLED"
    assert status(correction_flag=True) == "TRUTH_UNSETTLED"
    assert status(is_superseded=True) == "TRUTH_UNSETTLED"
    assert status(is_final=False) == "TRUTH_UNSETTLED"


def test_ast_pin_allowlist_forbids_open_holdout_attribute_and_string_access() -> None:
    clean = "import datetime as dt\nfrom breezy.settlement.trial_scorer import score_trial\n"
    bad_sources = {
        "name": "from breezy.analysis.nbp_calibration import open_holdout\n",
        "attribute": "import breezy.analysis.nbp_calibration as nc\nnc.open_holdout()\n",
        "string": "import breezy.analysis.nbp_calibration as nc\ngetattr(nc, 'open_holdout')\n",
        "m1v3 path": "p = '/home/jon/breezy/data/m1v3/holdout.parquet'\n",
        "off-list": "import requests\n",
        "direct exec": "from breezy.adapters.polymarket_us.exec.client import DurableFillRecord\n",
    }

    assert holdout_violations(clean, _ALLOWED) == ()
    for label, source in bad_sources.items():
        assert holdout_violations(source, _ALLOWED), label
    for script in _SCRIPTS:
        assert holdout_violations(script.read_text(encoding="utf-8"), _ALLOWED) == (), script.name


class _FakeGit:
    def __init__(self, blobs: dict[str, str], *, clean: bool = True, ancestors: Any = ()) -> None:
        self.blobs, self.clean, self.ancestors = blobs, clean, set(ancestors)

    def head_blob_sha256(self, path: str) -> str:
        return self.blobs[path]

    def porcelain_clean(self, paths: Sequence[str]) -> bool:
        return self.clean

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        return (ancestor, descendant) in self.ancestors

    def blob_sha256(self, commit: str, path: str) -> str | None:
        raise AssertionError("not used by the Phase B gate")

    def tree_shas(self, commit: str, paths: Sequence[str]) -> tuple[str, ...]:
        raise AssertionError("not used by the Phase B gate")


def test_phase_b_refuses_without_head_blob_pins_clean_path_and_ancestor_commit(
    tmp_path: Path,
) -> None:
    pins = {"scripts/a.py": "aa", "scripts/b.py": "bb"}
    good = _FakeGit(pins, ancestors={("PRE", "HEAD")})

    assert phase_b_refusals(pins, "PRE", good) == ()
    drift = phase_b_refusals(
        pins, "PRE", _FakeGit({**pins, "scripts/b.py": "zz"}, ancestors=good.ancestors)
    )
    assert (
        len(drift) == 1 and drift[0].startswith("head_blob_mismatch") and "scripts/b.py" in drift[0]
    )
    assert phase_b_refusals(pins, "PRE", _FakeGit(pins, clean=False, ancestors=good.ancestors)) == (
        "dirty_pinned_path",
    )
    assert phase_b_refusals(pins, "PRE", _FakeGit(pins)) == ("predeclaration_not_ancestor",)
    # production default path: the real SubprocessGit over a hermetic repo
    first, second = _tmp_repo(tmp_path, ["one", "two"])
    real = SubprocessGit(tmp_path)
    assert phase_b_refusals({"manifest.json": _sha("two")}, first, real) == ()
    assert phase_b_refusals({"manifest.json": _sha("one")}, second, real)  # HEAD blob is "two"
    assert phase_b_refusals(
        {"manifest.json": _sha("two")}, second, real
    )  # not strictly... see below


def test_refreeze_rule_requires_new_predeclaration_commit() -> None:
    frozen = {"core.py": "aa", "cli.py": "bb"}
    changed = {"core.py": "cc", "cli.py": "bb"}

    assert refreeze_status(frozen, frozen, None) == "OK"
    assert refreeze_status(frozen, changed, None) == "REFREEZE_REQUIRED"
    assert refreeze_status(frozen, changed, frozen) == "REFREEZE_REQUIRED"  # stale re-pin
    assert refreeze_status(frozen, changed, changed) == "REFROZEN"


def test_post_hoc_verifier_checks_artefact_commit_is_after_predeclaration(tmp_path: Path) -> None:
    fake = _FakeGit({}, ancestors={("PRE", "ART")})

    assert post_hoc_violations("PRE", "ART", fake) == ()
    assert post_hoc_violations("PRE", "PRE", _FakeGit({}, ancestors={("PRE", "PRE")}))
    assert post_hoc_violations("ART", "PRE", fake)
    # production default path
    pre, art = _tmp_repo(tmp_path, ["pre", "art"])
    real = SubprocessGit(tmp_path)
    assert post_hoc_violations(pre, art, real) == ()
    assert post_hoc_violations(art, pre, real)
    assert post_hoc_violations(pre, pre, real)


def test_s0a_count_only_runs_without_any_outcome(tmp_path: Path) -> None:
    store = tmp_path / "exec.db"
    seed_fills(store, [*fq_durable_fills(), *fq_september_fills()])

    counts = s0a_counts(store, dt.date(2026, 10, 5))

    assert counts == S0ACounts(
        n_fills=25, n_instruments=25, n_no_leg=0, n_open_ended=6, n_station_days=14,
        n_clusters=7, n_clusters_excluding_k1b=6, n_k1b_fills=5, n_k1b_station_days=3,
    )  # fmt: skip
    params = set(inspect.signature(s0a_counts).parameters)
    assert not params & {"catalog", "settlement", "source", "tmax"}
    assert not {f.name for f in dataclasses.fields(S0ACounts)} & {"n_wins", "pnl", "tmax"}
    writer = SqliteStateStore(store)
    try:
        writer.set(f"{FILL_KEY_PREFIX}vo-bad", b"{not json")
    finally:
        writer.close()
    with pytest.raises(FillStoreCorruption):  # require_clean: corruption is a STOP, never a skip
        s0a_counts(store, dt.date(2026, 10, 5))


class _EpochReader:
    def __init__(self, start: int | None) -> None:
        self._start = start

    def epoch_start_ns(self) -> int | None:
        return self._start

    def order_link(self, client_order_id: str) -> None:
        return None

    def earliest_order_link_ns(self) -> None:
        return None


def _fq_log(path: Path, *, skip_take_for: int | None = None) -> Path:
    lines = ["noise line without a stamp"]
    for index, fill in enumerate(fq_durable_fills()):
        t = 10.0 * index
        if index != skip_take_for:
            lines.append(log_take(t, fill.instrument_id))
        lines.append(log_init(t + 1, fill.client_order_id, fill.instrument_id))
        lines.append(
            log_filled(t + 2, fill.client_order_id, cast(str, fill.trade_id), fill.instrument_id)
        )
    lines += [
        log_take(300.0 + n, f"tc-temp-laxhigh-2026-10-02-lt{60 + n}f.POLYMARKET_US")
        for n in range(7)
    ]
    path.write_text("\n".join(lines) + "\n")
    return path


def test_all_25_fills_attribute_or_stop_unclassified(tmp_path: Path) -> None:
    fills = fq_durable_fills()
    log = _fq_log(tmp_path / "boot.log")
    (tmp_path / "root").mkdir()

    fake = attribute_fills(
        fills, [log], data_root=tmp_path / "root", epoch_reader=_EpochReader(None)
    )
    default = attribute_fills(fills, [log], data_root=tmp_path / "root")  # production C1Epoch

    for result in (fake, default):
        assert (result.report.n, result.report.matched, result.report.p_null_count) == (25, 25, 0)
        assert result.matches[0].p_at_decision == pytest.approx(0.38)
    missing = _fq_log(tmp_path / "missing.log", skip_take_for=7)
    with pytest.raises(UnclassifiedFillsStop):
        attribute_fills(
            fills, [missing], data_root=tmp_path / "root", epoch_reader=_EpochReader(None)
        )
    with pytest.raises(UnclassifiedFillsStop):  # an epoch that is not PRE_EPOCH never bridges
        attribute_fills(fills, [log], data_root=tmp_path / "root", epoch_reader=_EpochReader(1))


def test_s0d_perturbed_vector_mismatches_and_is_classed_k1a() -> None:
    logged = {f"f{i}": 0.38 + 0.001 * i for i in range(25)}
    reproduced: dict[str, float | None] = dict(logged)

    assert s0d_compare(logged, reproduced).n_match == 25
    reproduced["f3"] = logged["f3"] + 1e-6  # the positive control
    reproduced["f4"] = logged["f4"] + 5e-10  # inside the 1e-9 tolerance
    reproduced["f5"] = None
    result = s0d_compare(logged, reproduced)

    assert result.n_match == 23
    assert set(result.mismatched_fill_ids) == {"f3", "f5"}
    assert classify_s0d_miss(
        bulletin_available=True, bulletin_reissued=False,
        cycle_selection_matches=True, delta_survives_root_cause=True,
    ) == "K1a"  # fmt: skip


def test_unavailable_bulletin_is_untestable_and_cycle_mismatch_is_cycle_ambiguous() -> None:
    def miss(**over: bool) -> str:
        base = {
            "bulletin_available": True, "bulletin_reissued": False,
            "cycle_selection_matches": True, "delta_survives_root_cause": True,
        }  # fmt: skip
        return classify_s0d_miss(**{**base, **over})

    assert miss(bulletin_available=False) == "UNTESTABLE"
    assert miss(bulletin_reissued=True) == "UNTESTABLE"
    assert miss(cycle_selection_matches=False) == "CYCLE_AMBIGUOUS"
    assert miss(bulletin_available=False, cycle_selection_matches=False) == "UNTESTABLE"


_SNAP_ROWS = [
    ("2026-10-01T13:39:52", "000000000000", "60290e9ddd29"),
    ("2026-10-01T16:01:36", "60290e9ddd29", "99067d4a9e7a"),
    ("2026-10-02T16:00:52", "99067d4a9e7a", "7dfd1af114c1"),
    ("2026-10-02T20:05:01", "7dfd1af114c1", "6e99a7ae2dbe"),
    ("2026-10-02T20:54:53", "6e99a7ae2dbe", "3eb4a1085dbf"),
    ("2026-10-03T15:01:45", "3eb4a1085dbf", "f45f5a6558cd"),
    ("2026-10-04T16:28:31", "f45f5a6558cd", "c893e13e603e"),
    ("2026-10-04T17:11:31", "c893e13e603e", "2be63d85aaaa"),  # carries a rebased 4ac87414
    ("2026-10-04T22:35:21", "2be63d85aaaa", "4ba7f10cd1f6"),
]  # fmt: skip
_BOOT_TIMES = [
    "2026-10-01T15:12:02", "2026-10-01T16:01:58", "2026-10-01T16:50:11", "2026-10-02T16:50:39",
    "2026-10-02T20:05:26", "2026-10-02T20:55:21", "2026-10-03T16:50:45", "2026-10-04T16:50:12",
    "2026-10-05T16:50:40",
]  # fmt: skip
_EXPECTED = [
    "60290e9ddd29", "99067d4a9e7a", "99067d4a9e7a", "7dfd1af114c1", "6e99a7ae2dbe", "3eb4a1085dbf",
    "f45f5a6558cd", "c893e13e603e", "4ba7f10cd1f6",
]  # fmt: skip
_TREES = {"60290e9ddd29": "T1", "c893e13e603e": "T3", "4ba7f10cd1f6": "T4"}


class _PinGit:
    """Dict-backed git: blobs equal the logged shas except for one corrupted commit."""

    def __init__(self, bad_blob_commit: str | None = None) -> None:
        self.bad = bad_blob_commit

    def head_blob_sha256(self, path: str) -> str:
        raise AssertionError("pin corroboration must read the blob AT the commit, never HEAD")

    def porcelain_clean(self, paths: Sequence[str]) -> bool:
        raise AssertionError("not used")

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        raise AssertionError("not used")

    def blob_sha256(self, commit: str, path: str) -> str | None:
        return "bad" if commit == self.bad else {"m": "logged-m", "a": "logged-a"}[path]

    def tree_shas(self, commit: str, paths: Sequence[str]) -> tuple[str, ...]:
        return (_TREES.get(commit, "T2"),)


def _snapshot(path: Path) -> tuple[Path, str]:
    body = "".join(f"{ts}+00:00 old={old} new={new} commit: x\n" for ts, old, new in _SNAP_ROWS)
    text = f"# Captured\n# source: .git/logs/HEAD\n{body}# source: .git/logs/refs/heads/b\n{body}"
    path.write_text(text)
    return path, _sha(text)


def _boot(number: int, stamp: str, manifest: str = "logged-m", artefact: str = "logged-a") -> Boot:
    when = dt.datetime.fromisoformat(stamp).replace(tzinfo=dt.UTC)
    return Boot(number, when, manifest, artefact)


_PIN_KW: dict[str, Any] = {"manifest_path": "m", "artefact_path": "a", "widened_paths": ["src/x"]}


def test_pin_resolver_reads_reflog_snapshot_file_not_live_reflog_and_never_committer_time(
    tmp_path: Path,
) -> None:
    path, digest = _snapshot(tmp_path / "REFLOG.txt")
    git = _PinGit()
    boots = [_boot(i + 1, t) for i, t in enumerate(_BOOT_TIMES)]

    pins = resolve_pins(path, digest, boots, git, **_PIN_KW)

    assert [p.commit for p in pins] == _EXPECTED  # boot 8 is c893e13e603e, never the rebased commit
    assert [p.near_boundary for p in pins] == [
        False,
        True,
        False,
        False,
        True,
        True,
        False,
        False,
        False,
    ]
    assert pins[1].state == "UNTESTABLE" and "tree" in (pins[1].reason or "")
    assert {p.state for i, p in enumerate(pins) if i != 1} == {"PINNED"}
    both = resolve_pins(path, digest, boots, git, reproduces_under=lambda n, c: True, **_PIN_KW)
    assert both[1].commit == "99067d4a9e7a" and both[1].state == "PINNED"
    one_sided = resolve_pins(
        path, digest, boots, git, reproduces_under=lambda n, c: c != "60290e9ddd29", **_PIN_KW
    )
    assert one_sided[1].state == "UNTESTABLE"
    with pytest.raises(SnapshotShaMismatch):
        resolve_pins(path, "0" * 64, boots, git, **_PIN_KW)
    early = resolve_pins(path, digest, [_boot(1, "2026-09-30T00:00:00")], git, **_PIN_KW)
    assert early[0].commit is None and early[0].state == "UNTESTABLE"
    corrupted = resolve_pins(path, digest, boots, _PinGit("4ba7f10cd1f6"), **_PIN_KW)
    assert corrupted[8].state == "UNTESTABLE" and corrupted[7].state == "PINNED"
    assert pin_label([]) == "STABLE" and pin_label(["20aa5ea5"]) == "INFERRED"
    assert reproduction_gate([None] * 3 + [True] * 22).passed is False  # UNTESTABLE = non-match
    assert reproduction_gate([None] * 2 + [True] * 23).passed is True
    # production default path: the real SubprocessGit over a hermetic repo
    repo = tmp_path / "repo"
    repo.mkdir()
    old, new = _tmp_repo(repo, ["old-content", "new-content"])
    rows = [
        ("2026-10-01T00:00:00", "0" * 12, old[:12]),
        ("2026-10-02T00:00:00", old[:12], new[:12]),
    ]
    body = "".join(f"{ts}+00:00 old={o} new={n} commit: x\n" for ts, o, n in rows)
    snap = tmp_path / "REFLOG2.txt"
    snap.write_text(f"# source: .git/logs/HEAD\n{body}")
    kw: dict[str, Any] = {"manifest_path": "manifest.json", "artefact_path": "manifest.json"}
    kw["widened_paths"] = ["manifest.json"]
    o_sha, n_sha = _sha("old-content"), _sha("new-content")
    real_boots = [
        _boot(1, "2026-10-01T12:00:00", o_sha, o_sha),
        _boot(2, "2026-10-02T12:00:00", o_sha, o_sha),  # logged the stale blob: corroboration fails
        _boot(3, "2026-10-02T13:00:00", n_sha, n_sha),
    ]
    real = SubprocessGit(repo)
    real_pins = resolve_pins(snap, _sha(snap.read_text()), real_boots, real, **kw)
    assert real.blob_sha256(old, "manifest.json") == o_sha  # at the commit, not HEAD
    assert real.tree_shas(old, ["manifest.json"]) != real.tree_shas(new, ["manifest.json"])
    assert [(p.commit, p.state) for p in real_pins] == [
        (old[:12], "PINNED"),
        (new[:12], "UNTESTABLE"),
        (new[:12], "PINNED"),
    ]


def _write_log(path: Path, lines: Sequence[str]) -> Path:
    path.write_text("\n".join(lines) + "\n")
    return path


def test_streaming_reader_is_a_lazy_generator_or_tracemalloc_bounded_and_keeps_a_take_split_across_a_prefilter_boundary(  # noqa: E501
    tmp_path: Path,
) -> None:
    takes = [log_take(t, f"tc-temp-laxhigh-2026-10-02-lt{60 + t}f.POLYMARKET_US") for t in range(3)]
    small = _write_log(tmp_path / "small.log", ["x" * 100, takes[0], "y" * 70, takes[1], takes[2]])
    expected = [e for e in (parse_log_line(t) for t in takes) if e is not None]

    stream = stream_take_events(small, chunk_size=64)  # every Take straddles several chunks

    assert iter(stream) is stream  # lazy: a generator, never a list
    assert list(stream) == expected == [e for e in read_log_events([small]) if e.kind == "take"]
    assert list(stream_take_events(small)) == expected  # production default chunk size
    filler = "z" * 2000
    big = tmp_path / "big.log"
    with big.open("w") as handle:
        for index in range(12_000):  # ~24 MB
            handle.write(filler + "\n")
            if index % 4000 == 0:
                handle.write(takes[0] + "\n")
    tracemalloc.start()
    try:
        count = sum(1 for _ in stream_take_events(big))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert count == 3
    assert peak < 8 * 1024 * 1024


def test_partition_union_reader_includes_refuse_lines(tmp_path: Path) -> None:
    log = _write_log(
        tmp_path / "boot.log",
        [
            log_take(1, _LAX_YES, station="LAX", rung_id="89_90"),
            log_refuse(2, _LAX_YES, station="LAX", rung_id="87_88"),
            log_refuse(3, _LAX_YES, station="LAX", rung_id="91_92"),
            log_refuse(4, _LAX_YES, station="MIA", rung_id="86_87"),
        ],
    )

    union = partition_union(iter_partition_events(log))

    day = dt.date(2026, 10, 2)
    assert union[("LAX", day)] == frozenset({"89_90", "87_88", "91_92"})
    assert union[("MIA", day)] == frozenset({"86_87"})
    assert len(read_log_events([log])) == 1  # the bridge reader keeps only the Take


def test_alt_truth_unavailable_marks_untestable_not_zero() -> None:
    absent = alt_truth_summary(None, None)
    empty = alt_truth_summary({}, {})
    flips = alt_truth_summary({"f1": True, "f2": False}, {"f1": False})

    assert (absent.k3_status, absent.k3_count, absent.k4_status, absent.k4_count) == (
        "UNTESTABLE", None, "UNTESTABLE", None,
    )  # fmt: skip
    assert (empty.k3_status, empty.k3_count, empty.k4_count) == ("TESTED", 0, 0)
    assert (flips.k3_count, flips.k4_count) == (1, 0)


def test_reproduces_audit_25_fills_2_wins_minus_2_17(tmp_path: Path) -> None:
    store = tmp_path / "exec.db"
    seed_fills(store, [*fq_durable_fills(), *fq_september_fills()])  # the real writer path
    fills = read_durable_fills(store).require_clean().fills  # L-42: through the real reader
    (tmp_path / "catalog").mkdir()
    source = _CatalogRouter(tmp_path / "catalog", fq_settlement_records())  # real NwsCliFinal
    now_ns = 1_800_000_000_000_000_000

    def audit(subset: Sequence[Any]) -> Any:
        return reproduce_audit(subset, source, now_ns=now_ns)

    full = audit(fills)
    october = audit([f for f in fills if "-2026-10-" in f.instrument_id])
    september = audit([f for f in fills if "-2026-09-" in f.instrument_id])

    assert (full.n_fills, full.n_wins, full.n_refused) == (34, 4, 0)
    assert abs(full.net_pnl - Decimal("-2.63")) <= Decimal("0.005")
    assert (october.n_fills, october.n_wins) == (25, 2)
    assert abs(october.net_pnl - Decimal("-2.17")) <= Decimal("0.005")
    assert (september.n_fills, september.n_wins) == (9, 2)
    assert abs(september.net_pnl - Decimal("-0.46")) <= Decimal("0.005")
    assert set(october.wins) == {  # the upper edge of the inclusive band is a win
        ("tc-temp-miahigh-2026-10-03-gte86lt87f.POLYMARKET_US", 87),
        ("tc-temp-miahigh-2026-10-05-gte89lt90f.POLYMARKET_US", 90),
    }
