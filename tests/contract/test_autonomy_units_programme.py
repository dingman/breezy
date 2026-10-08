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
from dataclasses import dataclass
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
_RETURN = re.compile(r"\breturn\s+(\d+)\b")


# `exit 0` must sit INSIDE the `$resolve_rc -eq N` branch: the body lines are
# consumed only while they do not open the next column-0 elif/else/fi, so a
# later unrelated `exit 0` elsewhere in the file can never satisfy the rule.
_IN_BLOCK_EXIT_0 = (
    r'"\$resolve_rc" -eq {rc} \]; then[^\n]*\n'
    r"(?:(?!(?:elif|else|fi)\b)[^\n]*\n)*?[ \t]*exit 0\b"
)


@dataclass(frozen=True)
class _CarveOut:
    """A benign skip whose ``say`` is NOT followed by an ``exit`` and so cannot
    be read off the lines around it. Each entry names the documented path that
    turns it into exit 0; the rule verifies both the shape after the say and
    that the caller/tail path is really present in the file."""

    wrapper: str
    message: re.Pattern[str]
    ret: int | None  # `return N` the next statement must be; None = fall through
    path: re.Pattern[str]  # must match the wrapper text: the path that exits 0
    reason: str


_CARVE_OUTS: tuple[_CarveOut, ...] = (
    _CarveOut(
        "replay-daily-run.sh",
        re.compile(r"composition_kind=forecast_quantile_ladder"),
        3,
        re.compile(_IN_BLOCK_EXIT_0.format(rc=3), re.MULTILINE),
        "resolve_family_manifest returns 3; the caller maps rc 3 to exit 0",
    ),
    _CarveOut(
        "score-live-trials-run.sh",
        re.compile(r"composition_kind=forecast_quantile_ladder"),
        2,
        re.compile(_IN_BLOCK_EXIT_0.format(rc=2), re.MULTILINE),
        "resolve_sending_family_manifest returns 2; caller writes .skipped, exits 0",
    ),
    _CarveOut(
        "asos-refresh-run.sh",
        re.compile(r"SKIPPED-LOCK"),
        None,
        re.compile(r"^exit \$\(\( FAILED \? 1 : 0 \)\)\s*$", re.MULTILINE),
        "contention does not exit early; the tail exits 0 unless a fetch step FAILED",
    ),
)


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


def _carve_out_problem(
    name: str, text: str, lines: list[tuple[int, str]], index: int, message: str
) -> str | None:
    """None when a benign skip with no ``exit`` is an allowlisted, verified
    carve-out; otherwise why it is not."""
    entry = next((c for c in _CARVE_OUTS if c.wrapper == name and c.message.search(message)), None)
    if entry is None:
        return "benign skip has no exit and no documented carve-out"
    following = lines[index + 1][1] if index + 1 < len(lines) else ""
    returned = _RETURN.search(lines[index][1]) or _RETURN.search(following)
    if entry.ret is None:
        if returned:
            return f"carve-out expects fall-through but found return {returned.group(1)}"
    elif not returned or int(returned.group(1)) != entry.ret:
        return f"carve-out expects `return {entry.ret}` right after the say"
    if not entry.path.search(text):
        return f"carve-out path to exit 0 not found ({entry.reason})"
    return None


def _offenders(name: str, text: str) -> list[str]:
    lines = _statements(text)
    offenders: list[str] = []
    for index, (number, line) in enumerate(lines):
        for message in _SAY.findall(line):
            code = _first_exit_after(lines, index)
            if _BENIGN_SKIP.search(message) and code is None:
                problem = _carve_out_problem(name, text, lines, index, message)
                if problem:
                    offenders.append(f"{name}:{number} {problem}: {message}")
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


def test_a_benign_skip_without_an_exit_or_carve_out_is_flagged() -> None:
    fixture = 'say "SKIPPED -- another study holds the studies lock"\ncontinue\n'
    assert len(_offenders("fixture.sh", fixture)) == 1


def test_a_carve_out_whose_caller_path_is_gone_is_flagged() -> None:
    fixture = (
        'f() {\n  say "REPLAY DAILY SKIPPED -- composition_kind=forecast_quantile_ladder x"\n'
        "  return 3\n}\nf\nexit 1\n"
    )
    assert len(_offenders("replay-daily-run.sh", fixture)) == 1


def test_a_carve_out_with_the_wrong_return_code_is_flagged() -> None:
    fixture = (
        'say "REPLAY DAILY SKIPPED -- composition_kind=forecast_quantile_ladder x"\nreturn 1\n'
    )
    assert len(_offenders("replay-daily-run.sh", fixture)) == 1


def test_a_carve_out_whose_branch_exits_one_is_flagged_despite_a_later_exit_zero() -> None:
    fixture = (
        'f() {\n  say "REPLAY DAILY SKIPPED -- composition_kind=forecast_quantile_ladder x"\n'
        "  return 3\n}\nf\nresolve_rc=$?\n"
        'if [ "$resolve_rc" -eq 3 ]; then\n  exit 1\nelif [ "$resolve_rc" -ne 0 ]; then\n'
        "  exit 1\nfi\nexit 0\n"
    )
    assert len(_offenders("replay-daily-run.sh", fixture)) == 1


@pytest.mark.parametrize("entry", _CARVE_OUTS, ids=lambda c: c.wrapper)
def test_every_carve_out_is_live_and_documented(entry: _CarveOut) -> None:
    """Non-vacuous: a stale allowlist row (wrapper renamed, message reworded)
    fails here instead of silently excusing nothing."""
    text = (_SYSTEMD_DIR / entry.wrapper).read_text()
    lines = _statements(text)
    hits = [
        i
        for i, (_, line) in enumerate(lines)
        if any(entry.message.search(m) and _BENIGN_SKIP.search(m) for m in _SAY.findall(line))
    ]
    assert hits, f"{entry.wrapper}: no benign say matches the carve-out"
    assert entry.reason.strip()
    assert _offenders(entry.wrapper, text) == []


def test_portfolio_roi_no_input_says_resolve_to_exit_zero() -> None:
    text = (_SYSTEMD_DIR / "portfolio-roi-run.sh").read_text()
    lines = _statements(text)
    codes = [
        _first_exit_after(lines, index)
        for index, (_, line) in enumerate(lines)
        if any("NO_INPUT -- upstream skipped" in m for m in _SAY.findall(line))
    ]
    assert codes == [0]
