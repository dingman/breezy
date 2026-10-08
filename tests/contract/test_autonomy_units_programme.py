"""AUT-6 WP3 S1: programme-wide wrapper exit contract, derived from the files.

The unit set is every ``deploy/systemd/*-run.sh`` (no literal count). Two
vocabularies must never be confused in a journal, because the health pass reads
them to tell an expected skip from a failure:

* a benign skip (the studies lock is busy, an upstream composition has nothing
  to run, the upstream stage skipped by design) says SKIPPED/NO_INPUT and the
  wrapper exits 0 -- ``Persistent=true`` does not retrigger and no
  ``OnFailure=`` fires on a healthy skip;
* an infrastructure refusal (the lock directory/file cannot be opened, exit 75
  EX_TEMPFAIL) is a REAL failure and is the one sanctioned non-zero SKIPPED
  label, ``SKIPPED-INFRA`` (pinned loudly by
  ``test_every_flock_wrapper_refuses_loudly_when_the_lock_dir_is_unwritable``).
  Its unit keeps ``OnFailure=`` and does NOT declare ``SuccessExitStatus=75``:
  that would hide a broken lock dir that lets 10-24 GB studies overlap. The two
  labels must not be crossed: ``SKIPPED-INFRA`` always exits 75, and a plain
  ``SKIPPED`` never does.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract

_SYSTEMD_DIR = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
_WRAPPERS = sorted(_SYSTEMD_DIR.glob("*-run.sh"))
_SAY = re.compile(r'\bsay\s+"([^"]*)"')
_EXIT = re.compile(r"\bexit\s+(\d+)\b")
_INFRA_EXIT = 75
_INFRA_LABEL = "SKIPPED-INFRA"
_BENIGN_SKIP = re.compile(
    r"SKIPPED -- another study holds|SKIPPED-LOCK|composition_kind=|NO_INPUT -- upstream skipped"
)
_LOOKAHEAD = 3


def _statements(text: str) -> list[tuple[int, str]]:
    """(line number, code) for every non-comment line."""
    return [
        (n, line)
        for n, line in enumerate(text.splitlines(), start=1)
        if not line.lstrip().startswith("#")
    ]


def _first_exit_after(lines: list[tuple[int, str]], index: int) -> int | None:
    """The first ``exit N`` on the say line or within the next few lines,
    stopping at the next ``say``."""
    for offset, (_, line) in enumerate(lines[index : index + _LOOKAHEAD + 1]):
        if offset and _SAY.search(line):
            return None
        match = _EXIT.search(line)
        if match:
            return int(match.group(1))
    return None


def _offenders(name: str, text: str) -> list[str]:
    lines = _statements(text)
    offenders: list[str] = []
    for index, (number, line) in enumerate(lines):
        for message in _SAY.findall(line):
            code = _first_exit_after(lines, index)
            if _BENIGN_SKIP.search(message) and code not in (None, 0):
                offenders.append(f"{name}:{number} benign skip exits {code}: {message}")
            if _INFRA_LABEL in message and code not in (None, _INFRA_EXIT):
                offenders.append(f"{name}:{number} {_INFRA_LABEL} exits {code}: {message}")
            if "SKIPPED" in message and _INFRA_LABEL not in message and code == _INFRA_EXIT:
                offenders.append(f"{name}:{number} a plain SKIPPED exits {_INFRA_EXIT}: {message}")
    return offenders


def _exit_codes(text: str) -> set[int]:
    return {int(m.group(1)) for _, line in _statements(text) if (m := _EXIT.search(line))}


def _owning_units(wrapper: Path) -> list[Path]:
    return [
        unit
        for unit in sorted(_SYSTEMD_DIR.glob("*.service"))
        if re.search(rf"^ExecStart=\S*{re.escape(wrapper.name)}\b", unit.read_text(), re.MULTILINE)
    ]


def test_wrapper_set_is_derived_and_nonempty() -> None:
    assert _WRAPPERS, "no deploy/systemd/*-run.sh found"


@pytest.mark.parametrize("wrapper", _WRAPPERS, ids=lambda p: p.name)
def test_every_wrapper_skip_path_exits_success(wrapper: Path) -> None:
    offenders = _offenders(wrapper.name, wrapper.read_text())
    assert not offenders, "\n".join(offenders)


@pytest.mark.parametrize("wrapper", _WRAPPERS, ids=lambda p: p.name)
def test_infra_exit_75_stays_a_loud_failure_on_the_owning_unit(wrapper: Path) -> None:
    if _INFRA_EXIT not in _exit_codes(wrapper.read_text()):
        pytest.skip("wrapper has no exit 75 path")
    units = _owning_units(wrapper)
    assert units, f"no .service runs {wrapper.name}"
    for unit in units:
        directives = "\n".join(line for _, line in _statements(unit.read_text()))
        assert re.search(r"^OnFailure=", directives, re.MULTILINE), f"{unit.name} lost OnFailure="
        success = re.findall(r"^SuccessExitStatus=(.*)$", directives, re.MULTILINE)
        assert not any(str(_INFRA_EXIT) in value.split() for value in success), (
            f"{unit.name} hides exit {_INFRA_EXIT} behind SuccessExitStatus"
        )


def test_the_rule_flags_a_benign_skip_that_exits_nonzero() -> None:
    fixture = 'flock -n 9 || { say "SKIPPED -- another study holds the studies lock"; exit 1; }\n'
    assert len(_offenders("fixture.sh", fixture)) == 1


def test_the_rule_flags_a_plain_skipped_that_exits_75() -> None:
    fixture = 'mkdir -p "$D" || { say "SKIPPED -- no dir"; exit 75; }\n'
    assert len(_offenders("fixture.sh", fixture)) == 1


def test_the_rule_flags_an_infra_label_that_exits_zero() -> None:
    fixture = 'mkdir -p "$D" || { say "SKIPPED-INFRA -- no dir"; exit 0; }\n'
    assert len(_offenders("fixture.sh", fixture)) == 1


def test_the_rule_accepts_the_sanctioned_shapes() -> None:
    fixture = (
        'flock -n 9 || { say "SKIPPED -- another study holds the studies lock"; exit 0; }\n'
        'mkdir -p "$D" || { say "SKIPPED-INFRA -- no dir"; exit 75; }\n'
        'say "FAILED-INFRA -- tmp"\n'
        "exit 75\n"
    )
    assert _offenders("fixture.sh", fixture) == []
