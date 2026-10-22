"""ARM D1 scheduling: the harm-stop producer rides the existing daily post-truth-fetch job.

No unit of its own is created (the plan's "unit" is satisfied by ``ExecStartPost=`` on the
truth-dataset service, which runs after the 11:40Z fetch). Nothing is installed by this change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

DEPLOY: Final[Path] = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
DATASET: Final[Path] = DEPLOY / "breezy-truth-dataset.service"
PRODUCER: Final[str] = "scripts/analysis/maker_loss_stop_producer.py"


def _lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_the_producer_runs_as_execstartpost_of_the_truth_dataset_job() -> None:
    posts = [line for line in _lines(DATASET) if line.startswith("ExecStartPost=")]
    assert len(posts) == 1 and PRODUCER in posts[0]
    for station in ("lax", "sfo", "mdw", "mia"):
        assert f"--station {station}" in posts[0]
    assert "network" not in posts[0]


def test_the_dataset_job_keeps_its_failure_alert_and_runs_after_the_fetch() -> None:
    lines = _lines(DATASET)
    assert "OnFailure=breezy-study-failed@%n.service" in lines
    timer = _lines(DEPLOY / "breezy-truth-dataset.timer")
    assert "OnCalendar=*-*-* 12:40:00 UTC" in timer  # after breezy-truth-fetch.timer's 11:40Z
    assert "OnCalendar=*-*-* 11:40:00 UTC" in _lines(DEPLOY / "breezy-truth-fetch.timer")


def test_no_unit_of_its_own_exists_for_the_producer() -> None:
    own = [p.name for p in DEPLOY.iterdir() if "maker-loss-stop" in p.name or "harm-stop" in p.name]
    assert own == []
    carriers = [p.name for p in DEPLOY.glob("*.service") if PRODUCER in p.read_text()]
    assert carriers == ["breezy-truth-dataset.service"]
