"""AUT-1 WP2: the guard is family-agnostic (plan r12 section 4 WP2).

``::test_every_full_plugin_kind_strategy_subclasses_capture_guard`` is deliberately NOT here: it is
RED until WP7 re-bases FQ on the guard, and the plan forbids ``xfail`` and ``skip``. It lives in
``pending_wp7_capture_guard_subclass.py`` (a name pytest does not collect by default), so the merge
gate stays green without the test being hidden: run it by path and it fails. WP7 moves it back
here, where it must pass.
"""

from breezy.persistence.exit_tags import (
    DECISION_ID_TAG_PREFIX,
    EXIT_CLIENT_ORDER_ID_TAG_PREFIX,
    EXIT_FAMILY_TAG_PREFIX,
    EXIT_POSITION_TAG_PREFIX,
    EXIT_RULE_TAG_PREFIX,
)

_EXIT_PREFIXES = (
    EXIT_RULE_TAG_PREFIX,
    EXIT_POSITION_TAG_PREFIX,
    EXIT_FAMILY_TAG_PREFIX,
    EXIT_CLIENT_ORDER_ID_TAG_PREFIX,
)


def test_decision_id_tag_prefix_never_collides_with_exit_prefixes() -> None:
    """MUTATION: a decision prefix that starts with an exit prefix (or the reverse) would make the
    exit test ("any tag starts with ``exit_rule=``") match an entry order."""
    assert len({DECISION_ID_TAG_PREFIX, *_EXIT_PREFIXES}) == 5
    for prefix in _EXIT_PREFIXES:
        assert not DECISION_ID_TAG_PREFIX.startswith(prefix)
        assert not prefix.startswith(DECISION_ID_TAG_PREFIX)
