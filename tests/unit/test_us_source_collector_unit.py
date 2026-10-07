"""F13-C1 S4 H5: the collector unit, its bwrap ExecStart and the behavioural probe.

The unit files are READ and parsed here, never installed. The behavioural probe runs the
exact ExecStart argv (specifiers expanded, three bind SOURCES redirected to temp paths and
the worktree), with the trailing command swapped for the probe command, so what is proven
is the real profile and not a look-alike. It skips only when ``bwrap_profile_ok`` fails, and
the skip reason carries bwrap's stderr.
"""

from __future__ import annotations

import importlib.util
import itertools
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT_DIR = REPO_ROOT / "deploy" / "systemd"
COLLECT_DIR = REPO_ROOT / "scripts" / "collect"


def _load_guards() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "us_source_guards", COLLECT_DIR / "us_source_guards.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["us_source_guards"] = module
    spec.loader.exec_module(module)
    return module


guards = sys.modules.get("us_source_guards") or _load_guards()

REPO_LITERAL = "/home/jon/breezy"
SERVICE = UNIT_DIR / "us-source-collector@.service"
TIMER = UNIT_DIR / "us-source-collector@.timer"
INSTANCES = ("lamp", "pfm", "nbp", "lav", "mos", "obs")
#: C1-R1 poll-cadence bounds (seconds) of the first-seen precision for the new legs.
CADENCE_BOUND_S = {"lav": 15 * 60, "mos": 15 * 60}
HOME = str(Path.home())
ARCHIVE_DST = f"{HOME}/.local/share/breezy/us_source_archive"
ALERTS_DST = f"{HOME}/.config/breezy/alerts.env"
WINDOW_START_S = 16 * 3600 + 30 * 60
NS = 1_000_000_000


# ----------------------------------------------------------------------- unit parsing


def _logical_lines(text: str) -> list[str]:
    joined: list[str] = []
    buffer = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.endswith("\\"):
            buffer += line[:-1] + " "
            continue
        joined.append(buffer + line)
        buffer = ""
    return joined


def parse_unit(path: Path) -> dict[str, list[str]]:
    """``Section.Key`` -> every value in file order (an empty value is kept: it resets)."""
    values: dict[str, list[str]] = {}
    section = ""
    for line in _logical_lines(path.read_text(encoding="utf-8")):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            continue
        key, _, value = stripped.partition("=")
        values.setdefault(f"{section}.{key.strip()}", []).append(value.strip())
    return values


def effective(instance: str, kind: str, key: str) -> list[str]:
    """Template values, then the instance drop-ins, honouring systemd's empty-reset rule."""
    base = UNIT_DIR / f"us-source-collector@.{kind}"
    out = list(parse_unit(base).get(key, []))
    for conf in sorted((UNIT_DIR / f"us-source-collector@{instance}.{kind}.d").glob("*.conf")):
        for value in parse_unit(conf).get(key, []):
            if value == "":
                out = []
            else:
                out.append(value)
    return out


def execstart_argv(*, instance: str = "lamp") -> list[str]:
    [line] = parse_unit(SERVICE)["Service.ExecStart"]
    return expand(shlex.split(line), instance)


def expand(argv: list[str], instance: str) -> list[str]:
    table = {"%h": HOME, "%i": instance, "%t": f"/run/user/{os.getuid()}", "%%": "%"}
    return [re.sub(r"%[hit%]", lambda m: table[m.group(0)], arg) for arg in argv]


def bwrap_tail(argv: list[str]) -> list[str]:
    return argv[argv.index("/usr/bin/bwrap") :]


def profile_binds(argv: list[str]) -> list[tuple[str, str, str]]:
    """(flag, src, dst) for every bind flag in the bwrap argv."""
    out: list[tuple[str, str, str]] = []
    for i, arg in enumerate(argv):
        if arg in {"--bind", "--ro-bind", "--bind-try", "--ro-bind-try", "--dev-bind"}:
            out.append((arg, argv[i + 1], argv[i + 2]))
    return out


# --------------------------------------------------------------------- static profile


def test_unit_files_exist_in_the_repo_unit_directory() -> None:
    assert SERVICE.is_file() and TIMER.is_file()
    assert not (REPO_ROOT / "ops" / "systemd").exists()


def test_unit_execstart_is_the_bwrap_profile_with_clearenv_unshare_all_share_net_die_with_parent() -> (  # noqa: E501
    None
):
    argv = bwrap_tail(execstart_argv())
    assert argv[0] == "/usr/bin/bwrap"
    for flag in ("--clearenv", "--unshare-all", "--share-net", "--die-with-parent"):
        assert flag in argv, flag
    assert argv.index("--clearenv") < min(i for i, a in enumerate(argv) if a == "--setenv")
    assert argv.index("--unshare-all") < argv.index("--share-net")
    assert ["--tmpfs", HOME] in [argv[i : i + 2] for i in range(len(argv) - 1)]
    assert "--" in argv, "the profile must end in `-- <command>`"
    command = argv[argv.index("--") + 1 :]
    assert command[0] == f"{REPO_LITERAL}/.venv/bin/python"
    assert command[1] == f"{REPO_LITERAL}/scripts/collect/us_source_collector.py"
    assert "--source" in command and command[command.index("--source") + 1] == "lamp"
    assert "--alerts-env" in command and ALERTS_DST in command


def test_profile_root_is_read_only_minimal_and_never_the_host_root() -> None:
    argv = bwrap_tail(execstart_argv())
    binds = profile_binds(argv)
    assert not [b for b in binds if b[2] == "/" or b[1] == "/"]
    assert "--dev-bind" not in argv and "--dev-bind-try" not in argv
    ro_sources = {src for flag, src, _ in binds if flag.startswith("--ro-bind")}
    assert "/usr" in ro_sources
    remounted = {argv[i + 1] for i, a in enumerate(argv) if a == "--remount-ro"}
    assert {HOME, "/"} <= remounted, "the tmpfs root and home must be remounted read-only"


def test_profile_has_one_writable_bind_and_it_is_the_archive_directory() -> None:
    binds = profile_binds(bwrap_tail(execstart_argv()))
    writable = [b for b in binds if b[0] in {"--bind", "--bind-try"}]
    assert writable == [("--bind", ARCHIVE_DST, ARCHIVE_DST)]


def test_unit_has_no_credential_env_or_config_mount() -> None:
    values = parse_unit(SERVICE)
    assert "Service.EnvironmentFile" not in values
    assert "Service.PassEnvironment" not in values
    for entry in values.get("Service.Environment", []):
        assert not re.search(r"KEY|SECRET|TOKEN|PASSWORD|CRED|WEBHOOK", entry, re.IGNORECASE)
    argv = bwrap_tail(execstart_argv())
    config_mounts = [
        (flag, src, dst)
        for flag, src, dst in profile_binds(argv)
        if ".config" in src or ".config" in dst
    ]
    assert config_mounts == [("--ro-bind", ALERTS_DST, ALERTS_DST)]
    forbidden = ("operator.env", "polymarket", "breezy-trade", "secret", ".key", "breezy.env")
    assert not [a for a in argv if any(token in a.lower() for token in forbidden)]
    setenv_names = {argv[i + 1] for i, a in enumerate(argv) if a == "--setenv"}
    assert not [n for n in setenv_names if re.search(r"KEY|SECRET|TOKEN|PASSWORD", n)]
    assert not (Path(HOME) / ".local/share/breezy/trade").as_posix() in " ".join(argv)


def test_unit_sets_memory_nofile_tasks_caps() -> None:
    values = parse_unit(SERVICE)
    assert values["Service.LimitNOFILE"] == ["524288"]
    assert values["Service.MemoryMax"][0].endswith(("M", "G"))
    assert int(values["Service.TasksMax"][0]) > 0
    assert values["Service.UMask"] == ["0077"]
    # RuntimeMaxSec is ignored under Type=oneshot; the backstop only binds for exec/simple.
    assert values["Service.Type"] == ["exec"]


def test_unit_flock_skips_an_overlapping_run_without_failing() -> None:
    argv = execstart_argv()
    assert argv[0] == "/usr/bin/flock"
    assert "-n" in argv and "-E" in argv
    conflict = argv[argv.index("-E") + 1]
    assert parse_unit(SERVICE)["Service.SuccessExitStatus"] == [conflict]
    assert argv[argv.index("-E") + 2].endswith("us-source-collector-lamp.lock")
    assert "coverage.json.lock" not in " ".join(argv)


def test_service_is_never_installed_by_this_change() -> None:
    assert "Install.WantedBy" not in parse_unit(SERVICE)
    assert parse_unit(TIMER)["Install.WantedBy"] == ["timers.target"]


# ------------------------------------------------------------- the 16:30Z deadline


def _expand_field(field: str, limit: int) -> list[int]:
    """One OnCalendar time field: ``*``, ``N``, ``A..B`` and comma lists of those."""
    if field == "*":
        return list(range(limit))
    values: list[int] = []
    for part in field.split(","):
        low, _, high = part.partition("..")
        values.extend(range(int(low), int(high or low) + 1))
    return values


def _firing_seconds(instance: str) -> list[int]:
    seconds: list[int] = []
    for spec in effective(instance, "timer", "Timer.OnCalendar"):
        match = re.fullmatch(r"\*-\*-\* ([\d,.*]+):([\d,.*]+):(\d+) UTC", spec)
        assert match, f"unsupported OnCalendar form {spec!r}"
        hours, minutes = _expand_field(match[1], 24), _expand_field(match[2], 60)
        seconds.extend(h * 3600 + m * 60 + int(match[3]) for h in hours for m in minutes)
    return sorted(seconds)


@pytest.mark.parametrize("instance", INSTANCES)
def test_runtime_max_is_backstop_and_never_extends_past_16_30z(instance: str) -> None:
    runtime_s = int(effective(instance, "service", "Service.RuntimeMaxSec")[-1])  # last wins
    firings = _firing_seconds(instance)
    assert firings
    # Never extends past 16:30Z: any firing that starts before the window ends before it.
    for start in firings:
        if start < WINDOW_START_S:
            assert start + runtime_s <= WINDOW_START_S, (instance, start, runtime_s)
    # A backstop only: strictly beyond the in-process work budget, so it never pre-empts it.
    assert runtime_s > guards.MAX_WORK_SECONDS[instance]


@pytest.mark.parametrize("instance", INSTANCES)
def test_no_static_timer_slot_lies_inside_the_launch_window(instance: str) -> None:
    window_end = 17 * 3600 + 10 * 60
    assert [s for s in _firing_seconds(instance) if WINDOW_START_S <= s < window_end] == []


def test_timer_reruns_displaced_firings_at_17_10z() -> None:
    for instance in ("lamp", "pfm"):
        assert 17 * 3600 + 10 * 60 in _firing_seconds(instance), instance
    in_window = [s for s in _firing_seconds("nbp") if WINDOW_START_S <= s < 17 * 3600 + 10 * 60]
    assert in_window == []


def test_timer_never_catches_up_with_a_burst() -> None:
    values = parse_unit(TIMER)
    assert values.get("Timer.Persistent", ["false"]) == ["false"]  # never a catch-up burst
    assert values["Timer.AccuracySec"] == ["1s"]


# ------------------------------------------------------------- behavioural probe


def probe_argv(tmp_path: Path, command: list[str], *, instance: str = "lamp") -> list[str]:
    """The exact ExecStart bwrap argv, three bind SOURCES redirected, command replaced."""
    archive = tmp_path / "archive"
    archive.mkdir(exist_ok=True)
    alerts = tmp_path / "alerts.env"
    alerts.write_text("BREEZY_ALERT_WEBHOOK_URL=https://hooks.example/probe\n", encoding="utf-8")
    argv = bwrap_tail(execstart_argv(instance=instance))
    out: list[str] = []
    skip = 0
    for i, arg in enumerate(argv):
        if skip:
            skip -= 1
            continue
        if arg in {"--bind", "--ro-bind", "--ro-bind-try", "--bind-try"}:
            src, dst = argv[i + 1], argv[i + 2]
            if dst == ARCHIVE_DST:
                src = str(archive)
            elif dst == ALERTS_DST:
                src = str(alerts)
            elif dst.startswith(f"{REPO_LITERAL}/") and "/.venv" not in dst:
                src = str(REPO_ROOT / dst.removeprefix(f"{REPO_LITERAL}/"))
            out += [arg, src, dst]
            skip = 2
            continue
        out.append(arg)
    cut = out.index("--")
    return [*out[: cut + 1], *command]


def bwrap_profile_ok(tmp_path: Path) -> tuple[bool, str]:
    """Runs the exact C1 profile with ``true`` as the command; (ok, bwrap's stderr)."""
    if not Path("/usr/bin/bwrap").is_file():
        return False, "/usr/bin/bwrap is not installed"
    done = subprocess.run(
        probe_argv(tmp_path, ["/usr/bin/true"]),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return done.returncode == 0, done.stderr.strip()


@pytest.fixture
def profile(tmp_path: Path) -> Path:
    ok, stderr = bwrap_profile_ok(tmp_path)
    if not ok:
        pytest.skip(f"bwrap_profile_ok failed under this environment: {stderr or 'rc != 0'}")
    return tmp_path


def _run(tmp_path: Path, command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        probe_argv(tmp_path, command),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def test_bwrap_probe_blocks_credentials_and_writes_outside_archive_dir(profile: Path) -> None:
    # (a) the config directory holds exactly alerts.env; no credential files, no credential env.
    listing = _run(profile, ["/usr/bin/ls", "-A", f"{HOME}/.config/breezy"])
    assert listing.returncode == 0, listing.stderr
    assert listing.stdout.split() == ["alerts.env"]
    env_dump = _run(profile, ["/usr/bin/env"])
    names = {line.split("=", 1)[0] for line in env_dump.stdout.splitlines()}
    assert not [n for n in names if re.search(r"KEY|SECRET|TOKEN|PASSWORD|WEBHOOK|BREEZY", n)]
    secret_file = f"{HOME}/.config/breezy/polymarket.env"
    assert _run(profile, ["/usr/bin/test", "-e", secret_file]).returncode != 0

    # (b) a write outside the archive directory fails; inside it succeeds.
    for outside in (
        f"{HOME}/outside",
        "/usr/outside",
        f"{REPO_LITERAL}/src/outside",
        "/etc/outside",
    ):
        assert _run(profile, ["/usr/bin/touch", outside]).returncode != 0, outside
    inside = _run(profile, ["/usr/bin/touch", f"{ARCHIVE_DST}/probe-ok"])
    assert inside.returncode == 0, inside.stderr
    assert (profile / "archive" / "probe-ok").is_file()
    assert not (Path(HOME) / "outside").exists()


def test_bwrap_probe_alerts_env_is_present_and_read_only(profile: Path) -> None:
    assert _run(profile, ["/usr/bin/test", "-r", ALERTS_DST]).returncode == 0
    assert _run(profile, ["/usr/bin/touch", ALERTS_DST]).returncode != 0
    assert _run(profile, ["/usr/bin/rm", "-f", ALERTS_DST]).returncode != 0
    assert (
        (profile / "alerts.env").read_text(encoding="utf-8").startswith("BREEZY_ALERT_WEBHOOK_URL=")
    )


def test_bwrap_probe_real_collector_help_runs_under_the_profile(profile: Path) -> None:
    unit_command = bwrap_tail(execstart_argv())
    command = unit_command[unit_command.index("--") + 1 :]
    script = next(i for i, a in enumerate(command) if a.endswith("us_source_collector.py"))
    done = _run(profile, [*command[: script + 1], "--help"])
    assert done.returncode == 0, done.stderr
    assert "--source" in done.stdout


@pytest.mark.parametrize("instance", sorted(CADENCE_BOUND_S))
def test_new_leg_cadence_bounds_the_first_seen_precision_outside_the_launch_window(
    instance: str,
) -> None:
    firings = _firing_seconds(instance)
    window_end = 17 * 3600 + 10 * 60
    gaps = [
        b - a
        for a, b in zip(firings, [*firings[1:], firings[0] + 86_400], strict=True)
        if not (a < WINDOW_START_S and b >= window_end - 1)
    ]
    assert max(gaps) <= CADENCE_BOUND_S[instance], (instance, max(gaps))


@pytest.mark.parametrize("instance", sorted(CADENCE_BOUND_S))
def test_new_leg_instance_is_a_known_collector_source(instance: str) -> None:
    from tests.unit.test_us_source_collector import col

    assert instance in col.SOURCE_KEYS


def test_obs_timer_fires_are_report_minute_targeted_with_bounded_first_seen_gaps() -> None:
    """Hours 05-06 (full hours): per station, firings inside [routine minute, +35 min] leave gaps
    <= 5 min during the first 15 min after the report and <= 10 min afterwards."""
    routine = {"KLAX": 53, "KMDW": 53, "KMIA": 53, "KNYC": 51, "KSFO": 56}
    firings = [s - 5 * 3600 for s in _firing_seconds("obs") if 5 * 3600 <= s < 7 * 3600]
    assert len(firings) == 18  # nine an hour
    for station, minute in routine.items():
        start = minute * 60
        marks = [start, *(f for f in firings if start <= f <= start + 35 * 60)]
        for a, b in itertools.pairwise(marks):
            bound = 5 * 60 if a - start < 15 * 60 else 10 * 60
            assert b - a <= bound, (station, a, b)
