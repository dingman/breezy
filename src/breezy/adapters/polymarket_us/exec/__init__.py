"""Polymarket.us execution package -- EMPTY BY DESIGN, and armed before use.

This package holds no code. It exists so that barrier N2's rule E0
(``tests/unit/test_execution_egress_firewall_guard.py``) has a directory to
classify BEFORE anything is written into it.

Why an empty package is the point. E0 says: every module under this path is an
execution-egress surface, by path alone. The other three rules cannot say that.
E1 matches a fixed list of basenames; E2 needs a class that looks like an
execution client; E3 needs a function named after an order verb. A module here
that is a table of endpoint path templates -- data, no class, no function --
matches none of them, and it is exactly the module that would hold the venue's
order-path literals. So the directory is classified first and populated later,
never the other way round.

The consequence, which is deliberate: from the commit that created this file,
a plain ``pytest`` run ABORTS at ``pytest_sessionstart`` before collecting a
single test, unless the OS-level egress firewall is both attested and proven
by a real blocked connect. Run the suite through
``scripts/ci/run_tests_no_egress.sh``, which is what CI already does.

Nothing here creates, or is a step towards, any ability to send an order. This
package is read-only-by-construction today because it is empty, and every
barrier in the read-only guard applies to whatever lands in it later.
"""

from __future__ import annotations
