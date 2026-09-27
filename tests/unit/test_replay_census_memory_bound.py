"""Instrumented warm-cache work bound for REPLAY-INCR.

This replaces the old RSS delta check: synthetic fixtures are too small for
`ru_maxrss` to prove anything reliably. The invariant that matters for the
warm path is that cached CLEAN instances do not scan bytes and do not create
converter objects as N grows.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _warm_cache_work(instance_count: int, tmp_path: Path) -> dict[str, int]:
    code = r"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

repo = Path(sys.argv[1])
instance_count = int(sys.argv[2])
root = Path(sys.argv[3])
sys.path.insert(0, str(repo / "scripts/analysis"))

import replay_sufficiency_census as census
from breezy.analysis.instance_span_cache import (
    SPAN_ALGO_VERSION,
    CachedInstanceSpans,
    append_instance_span_cache_entry,
)
from breezy.analysis.replay_sufficiency import InstanceSpan
from breezy.persistence.feather_preflight import PREFLIGHT_CLASSIFIER_VERSION


class _Registry:
    def pairs(self):
        return (("polymarket_us", "SFO"),)

    def climate_day_window(self, _venue, _station):
        return SimpleNamespace(std_utc_offset_hours=-8.0)


catalog = root / "catalog"
cache_path = root / "instance_spans.v2.jsonl"
for idx in range(instance_count):
    instance_id = f"instance-{idx:03d}"
    instance_dir = catalog / "live" / instance_id
    instance_dir.mkdir(parents=True)
    payload = (f"payload-{idx}" * 128).encode()
    (instance_dir / "binary_option_0.feather").write_bytes(payload)
    files = census._instance_file_fingerprints(instance_dir)
    fingerprint = census._instance_fingerprint(files)
    span = InstanceSpan(
        instance_id=instance_id,
        verdict="CLEAN",
        depth_window_minutes=45.0,
        quote_window_minutes=0.0,
        distinct_instruments=1,
    )
    entry = CachedInstanceSpans(
        spans={(f"SFO", f"2026-09-{idx + 1:02d}"): span},
        station_offsets={"SFO": -8.0},
        last_full_scan="2026-09-27",
        files=files,
    )
    append_instance_span_cache_entry(
        cache_path,
        (instance_id, fingerprint, SPAN_ALGO_VERSION, PREFLIGHT_CLASSIFIER_VERSION),
        entry,
    )

work = {"scan_bytes": 0, "converter_objects": 0}
census.default_registry = lambda: _Registry()
census.list_instance_ids = lambda _root, _subdir: tuple(
    f"instance-{idx:03d}" for idx in range(instance_count)
)
census._read_station_candidates = lambda path: ()
census._corrupt_instance_station_days = lambda quote_catalog, subdirectory, corrupt_ids: set()
census._live_instance_registrations = lambda quote_catalog, subdirectory, live_ids: {}


def _scan(root, instance_id, subdirectory):
    path = root / subdirectory / instance_id / "binary_option_0.feather"
    work["scan_bytes"] += path.stat().st_size
    return instance_id


def _convert(**kwargs):
    work["converter_objects"] += 1
    raise AssertionError("warm cache path must not convert")


census.scan_instance = _scan
census._discover_clean_spans = _convert
census.run_census(
    catalog_root=catalog,
    subdirectory="live",
    work_root=root / "work",
    station_candidates_path=root / "station_candidates.jsonl",
    computed_day="2026-09-27",
    now_ns=1,
    instance_spans_cache_path=cache_path,
)
print(json.dumps(work))
"""
    run_root = tmp_path / f"n{instance_count}"
    run_root.mkdir()
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{REPO_ROOT / 'src'}:{env.get('PYTHONPATH', '')}"
    result = subprocess.run(
        [sys.executable, "-c", code, str(REPO_ROOT), str(instance_count), str(run_root)],
        capture_output=True,
        check=True,
        env=env,
        text=True,
    )
    return json.loads(result.stdout.splitlines()[-1])


def test_warm_cache_work_is_independent_of_instance_count(tmp_path: Path) -> None:
    small = _warm_cache_work(2, tmp_path)
    large = _warm_cache_work(20, tmp_path)

    assert small == {"scan_bytes": 0, "converter_objects": 0}
    assert large == {"scan_bytes": 0, "converter_objects": 0}
