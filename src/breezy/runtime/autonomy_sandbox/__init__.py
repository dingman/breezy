"""The autonomy sandbox: one shared bwrap wrapper, its table and its checks.

ARCH-0 seam B (plan r5, erratum E-7e). This package is **stdlib-only**: the
import-linter contract "ARCH-0 seam B: the autonomy sandbox package is
stdlib-only" forbids ``nautilus_trader``, ``breezy.adapters`` and
``breezy.strategy`` here, directly or indirectly, because the wrapper runs
before any of them may load and must keep working when they are broken.

**This ``__init__`` must stay import-free**, for the same reason as
``breezy.runtime``: importing any submodule runs it first, so an eager import
here would put every submodule's dependencies on the wrapper's own path.

Modules landed so far (WP-B2b-1): ``table`` (rows and ``validate_table``),
``binds`` (nofollow walks and fd-opened bind sources) and ``run_mounts`` (the
exact per-row ``/run`` re-bind set). The wrapper never creates a bind source.
"""
