"""ARM D1 scheduling: the maker harm stop is its OWN parked unit and timer.

``breezy-maker-loss-stop.service`` collects the venue settlements (ExecStartPre, the only network
step) and then runs the producer (ExecStart); ``.timer`` fires it at 12:50Z. The FQ truth-dataset
job is untouched (review J1). Nothing here is installed, enabled or daemon-reloaded.
"""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Final

from breezy.strategy.no_ladder_maker.harm_stop import maker_loss_stop_artefact_path
from scripts.analysis import maker_loss_stop_producer as producer

DEPLOY: Final[Path] = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
SERVICE: Final[Path] = DEPLOY / "breezy-maker-loss-stop.service"
TIMER: Final[Path] = DEPLOY / "breezy-maker-loss-stop.timer"
DATASET: Final[Path] = DEPLOY / "breezy-truth-dataset.service"
PRODUCER: Final[str] = "scripts/analysis/maker_loss_stop_producer.py"
COLLECTOR: Final[str] = "scripts/venue/maker_settlement_collect.py"


def _lines(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _exec(prefix: str) -> list[str]:
    found = [line for line in _lines(SERVICE) if line.startswith(f"{prefix}=")]
    assert len(found) == 1, f"exactly one {prefix}= expected"
    return found[0].split("=", 1)[1].split()


def test_the_truth_dataset_job_is_untouched_by_the_maker_stop() -> None:
    text = DATASET.read_text()
    assert "maker" not in text and PRODUCER not in text
    assert not [line for line in _lines(DATASET) if line.startswith("ExecStartPost=")]
    assert "OnFailure=breezy-study-failed@%n.service" in _lines(DATASET)


def test_the_service_collects_first_then_produces_and_alerts_on_any_failure() -> None:
    lines = _lines(SERVICE)
    assert "OnFailure=breezy-study-failed@%n.service" in lines
    assert "Type=oneshot" in lines
    pre, main = _exec("ExecStartPre"), _exec("ExecStart")
    assert any(COLLECTOR in token for token in pre)
    assert any(PRODUCER in token for token in main)
    assert [line for line in lines if line.startswith("ExecStartPre=")] == [
        line for line in lines if COLLECTOR in line
    ]


def test_no_exit_status_is_masked() -> None:
    code = "\n".join(_lines(SERVICE))
    assert "SuccessExitStatus" not in code and "RestartPreventExitStatus" not in code
    for line in _lines(SERVICE):
        if line.split("=", 1)[0] in {"ExecStart", "ExecStartPre", "ExecStartPost"}:
            assert not line.split("=", 1)[1].startswith(("-", "+", "!", ":", "@")), line


def test_the_unit_is_parked_and_never_sees_operator_controls() -> None:
    code = "\n".join(_lines(SERVICE))
    assert "[Install]" not in SERVICE.read_text()
    for forbidden in ("breezy-trade.env", "operator.env", "BREEZY_SENDING_FAMILY_ID", "orders"):
        assert forbidden not in code
    assert "EnvironmentFile=-%h/.config/breezy/polymarket.env" in _lines(SERVICE)


def test_the_paths_are_explicit_and_the_producer_path_is_the_probes_path() -> None:
    main = _exec("ExecStart")
    pre = _exec("ExecStartPre")
    for tokens in (main, pre):
        for flag in ("--catalog-root", "--catalog-base", "--data-root"):
            assert flag in tokens, f"{flag} must be explicit"
        for station in ("lax", "sfo", "mdw", "mia"):
            assert ["--station", station] in [tokens[i : i + 2] for i in range(len(tokens))]
    root = Path(main[main.index("--catalog-root") + 1])
    assert pre[pre.index("--catalog-root") + 1] == str(root), "collector and producer agree"
    assert producer.artefact_path(root) == maker_loss_stop_artefact_path(root)
    assert producer.artefact_path(root).parent == root.parent / "derived" / "maker-loss-stop"


def test_the_timer_fires_daily_at_1250z_after_the_truth_jobs() -> None:
    timer = _lines(TIMER)
    assert "OnCalendar=*-*-* 12:50:00 UTC" in timer
    assert "Unit=breezy-maker-loss-stop.service" in timer
    assert "OnCalendar=*-*-* 11:40:00 UTC" in _lines(DEPLOY / "breezy-truth-fetch.timer")
    assert "OnCalendar=*-*-* 12:40:00 UTC" in _lines(DEPLOY / "breezy-truth-dataset.timer")
    assert not [line for line in timer if line.startswith("Persistent")]
    assert "WantedBy=timers.target" in timer


def test_the_command_lines_parse() -> None:
    for prefix in ("ExecStartPre", "ExecStart"):
        assert shlex.split(" ".join(_exec(prefix)))[0].endswith("/.venv/bin/python")
