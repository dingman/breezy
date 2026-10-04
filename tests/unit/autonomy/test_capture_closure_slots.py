"""AUT-1 WP5 stage 2c, S2-R21: the closure lint's ``{slot}`` argv extension is a strict extension.

A slot-templated argv is accepted only when every slot is drawn from a closed, pinned set of names,
each in its own flag position, and the call passes the bare name the module validates before the
call. A free-form slot, a literal or expression in a slot position, or a path-carrying slot is
refused. The pre-existing lint tests stay unchanged in ``test_capture_read_only_closure.py``.
"""

from typing import Final

import pytest

from tests.support.autonomy_scan import Finding
from tests.support.capture_closure_lint import (
    ALLOWED_ARGV_SLOTS,
    AUT1_WRITE_AUTHORITY,
    AuthorityRow,
    lint_source,
)

_MODULE: Final = "breezy.persistence.autonomy.capture_planted"
_PATH: Final = "src/breezy/persistence/autonomy/capture_planted.py"
_TEMPLATE: Final = ("journalctl", "--user", "-u", "x", "--since", "{since}", "--until", "{until}")
_ROW: Final = AuthorityRow(_MODULE, argvs=(_TEMPLATE,), min_calls=0)


def _lint(call: str, row: AuthorityRow = _ROW) -> list[Finding]:
    source = f"import subprocess\ndef f(since, until, path, x):\n    subprocess.run({call})\n"
    return lint_source(_PATH, source, module=_MODULE, authority=(row,))


_GOOD: Final = "['journalctl', '--user', '-u', 'x', '--since', since, '--until', until]"


def test_the_pinned_slot_names_are_exactly_the_two_time_slots() -> None:
    assert frozenset({"since", "until"}) == ALLOWED_ARGV_SLOTS


def test_the_bare_validated_names_in_their_own_flag_positions_are_admitted() -> None:
    assert _lint(_GOOD) == []


@pytest.mark.parametrize(
    "call",
    [
        "['journalctl', '--user', '-u', 'x', '--since', path, '--until', until]",
        "['journalctl', '--user', '-u', 'x', '--since', since, '--until', path]",
        "['journalctl', '--user', '-u', 'x', '--since', '/etc/shadow', '--until', until]",
        "['journalctl', '--user', '-u', 'x', '--since', since + path, '--until', until]",
        "['journalctl', '--user', '-u', 'x', '--since', f'{since}', '--until', until]",
        "['journalctl', '--user', '-u', 'x', '--since', until, '--until', since]",
        "['journalctl', '--user', '-u', 'x', '--since', since, '--until', until, path]",
        "['journalctl', '--user', '-u', 'other', '--since', since, '--until', until]",
    ],
)
def test_any_other_value_in_a_slot_position_is_refused(call: str) -> None:
    """MUTATION (red): a lint that admits any element where a slot stands lets all of these by."""
    assert _lint(call), call


def test_a_template_with_a_free_form_slot_is_refused_even_when_the_call_matches_it() -> None:
    row = AuthorityRow(_MODULE, argvs=(("cat", "{path}"),), min_calls=0)
    assert _lint("['cat', path]", row)


def test_a_slot_must_stand_directly_after_its_own_flag() -> None:
    row = AuthorityRow(_MODULE, argvs=(("journalctl", "{since}", "--since", "x"),), min_calls=0)
    assert _lint("['journalctl', since, '--since', 'x']", row)


def test_the_real_rows_use_only_pinned_slots_after_their_flags() -> None:
    import re

    slot = re.compile(r"\{(?P<name>[a-z_]+)\}")
    seen = 0
    for row in AUT1_WRITE_AUTHORITY:
        for argv in row.argvs:
            for index, token in enumerate(argv):
                match = slot.fullmatch(token)
                if match is None:
                    continue
                seen += 1
                assert match["name"] in ALLOWED_ARGV_SLOTS, (row.module, token)
                assert argv[index - 1] == f"--{match['name']}", (row.module, token)
    assert seen == 6  # three journalctl templates, two slots each
