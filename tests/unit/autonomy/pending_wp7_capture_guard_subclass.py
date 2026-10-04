"""RED-PENDING-WP7 (AUT-1 plan r12 section 4 WP2): not collected by the merge gate.

The plan says this test "stays RED-pending-WP7", "recorded in the WP's evidence; not xfailed". A
RED test cannot sit in a collected directory without reddening the gate, and ``xfail`` / ``skip``
are forbidden because they hide it. So the file name does not match pytest's ``test_*.py``
pattern: ``pytest tests/unit/autonomy/pending_wp7_capture_guard_subclass.py`` runs it by path and
it FAILS today. WP7 re-bases ``ForecastQuantileLadderStrategy`` on ``CaptureGuardedStrategy``,
renames this file to ``test_capture_guard_family_agnostic.py`` (merging it with the tests there)
and the test then passes.
"""

from breezy.persistence.autonomy.plugin import is_complete
from breezy.strategy.autonomy.node_plugins import NODE_PLUGINS
from breezy.strategy.autonomy_capture.guarded_strategy import CaptureGuardedStrategy
from breezy.strategy.forecast_quantile_ladder.plugin import FQ_COMPOSITION_KIND, FqNodePlugin
from breezy.strategy.forecast_quantile_ladder.strategy import ForecastQuantileLadderStrategy

#: composition kind -> its strategy class. A new full plug-in kind must add its row.
_STRATEGY_BY_KIND: dict[str, type] = {FQ_COMPOSITION_KIND: ForecastQuantileLadderStrategy}


def _full_plugin_kinds() -> set[str]:
    kinds = {kind for kind, plugin in NODE_PLUGINS.items() if is_complete(plugin)}
    if is_complete(FqNodePlugin):
        kinds.add(FQ_COMPOSITION_KIND)
    return kinds


def test_every_full_plugin_kind_strategy_subclasses_capture_guard() -> None:
    kinds = _full_plugin_kinds()
    assert kinds, "no full plug-in kind found: the test would be vacuous"
    for kind in kinds:
        assert kind in _STRATEGY_BY_KIND, f"no strategy class registered for kind {kind}"
        assert issubclass(_STRATEGY_BY_KIND[kind], CaptureGuardedStrategy), kind
