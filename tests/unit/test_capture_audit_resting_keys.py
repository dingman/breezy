"""ARM maker-sharp B6: the capture audit's advisory exec view must KNOW the resting-order keys.

The S4 resting path writes two key families into the exec store beside the fill records: the
per-order binding rows (``exec/polymarket_us/resting/<venue id>``) and the one index
(``exec/polymarket_us/resting_index``). The audit treats any unknown key under the exec
namespace as key-schema drift and refuses (``exec_key_prefix_unknown``), so a store that
ever held a bound rest would make the audit unreadable. The view ignores both families (they
carry no fill, order id map or resolver context the audit joins on); this file pins that.
"""

from __future__ import annotations

import pytest

from breezy.analysis import capture_audit_exec_view as exec_view
from breezy.analysis.capture_audit_model import AuditInputError

NAMESPACE = "exec/polymarket_us/"


@pytest.mark.parametrize("key", [f"{NAMESPACE}resting/ABCDEF123456"])
def test_a_resting_key_is_known_and_ignored_by_the_exec_view(key: str) -> None:
    view = exec_view._view_of([(key, b"{}")])
    assert view.fills == () and view.orders == () and view.resolvers == ()
    assert view.fill_by_day == {} and view.fill_by_fingerprint == {}


def test_an_unknown_exec_key_is_still_key_schema_drift() -> None:
    """Non-vacuity: only the two named families were added."""
    with pytest.raises(AuditInputError) as info:
        exec_view._view_of([(f"{NAMESPACE}resting_other", b"{}")])
    assert info.value.cause == "exec_key_prefix_unknown"
    with pytest.raises(AuditInputError):
        exec_view._view_of([(f"{NAMESPACE}something_new/x", b"{}")])
