"""Memory-bound regression for the REPLAY-INCR warm-cache census path."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _warm_cache_delta_kib(instance_count: int, tmp_path: Path) -> int:
    code = r"""
import json
import resource
import sys
import tempfile
from pathlib import Path

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


class _Window:
    std_utc_offset_hours = -8.0


class _Registry:
    def pairs(self):
        return (("polymarket_us", "SFO"),)

    def climate_day_window(self, _venue, _station):
        return _Window()


catalog = root / "catalog"
cache_path = root / "instance_spans.v2.jsonl"
for idx in range(instance_count):
    instance_id = f"instance-{idx:03d}"
    instance_dir = catalog / "live" / instance_id
    instance_dir.mkdir(parents=True)
    (instance_dir / "binary_option_0.feather").write_bytes(f"payload-{idx}".encode())
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
        spans={("SFO", "2026-09-01"): span},
        station_offsets={"SFO": -8.0},
        last_full_scan="2026-09-27",
        files=files,
    )
    append_instance_span_cache_entry(
        cache_path,
        (instance_id, fingerprint, SPAN_ALGO_VERSION, PREFLIGHT_CLASSIFIER_VERSION),
        entry,
    )

census.default_registry = lambda: _Registry()
census._read_station_candidates = lambda path: ()
census.scan_instance = lambda *args, **kwargs: (_ for _ in ()).throw(
    AssertionError("warm cache path must not scan")
)
baseline = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
census.run_census(
    catalog_root=catalog,
    subdirectory="live",
    work_root=root / "work",
    station_candidates_path=root / "station_candidates.jsonl",
    computed_day="2026-09-27",
    now_ns=1,
    instance_spans_cache_path=cache_path,
)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print(json.dumps({"delta_kib": after - baseline}))
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
    return int(json.loads(result.stdout.splitlines()[-1])["delta_kib"])


def test_warm_cache_rss_is_flat_in_instance_count(tmp_path: Path) -> None:
    small = _warm_cache_delta_kib(2, tmp_path)
    large = _warm_cache_delta_kib(20, tmp_path)

    assert large - small <= 15 * 1024
