"""F13 Phase A runner: the pin guards that bind the frozen prereg to the evidence (PIN-R6..R8).

Pure checks that raise :class:`Refusal`; the runner calls them before any model is fitted.

* PIN-R6 (:func:`check_pinned_lags_cover_c1`): every pinned ``source_lags_ns`` value must be at
  least that source's C1 observed p99. The C1 evidence file carries the per-source UNCENSORED
  samples (``late`` rows are right-censored and excluded upstream, F13-R21) under
  ``lag_samples_ns``, keyed like the pin (``lamp-mdl``, ``lav-iem``, ``pfm``, ``mos-gfs``,
  ``obs``). The p99 is the nearest-rank quantile.
* PIN-R7 (:func:`check_breaks_pinned`): every source break the builder observed
  (``source_breaks_observed`` in the sidecar: LAMP basis breaks overall and per horizon, NBP version
  breaks) must be in the pinned flat ``source_breaks`` list. Breaks define folds, so an unpinned
  one would silently move the M0 fold SD and the floor.
* PIN-R8b (:func:`check_not_refrozen`): the prereg file's git history (``git log --follow``) may
  hold at most one commit whose content carries a non-UNFROZEN ``frozen_sha``; a second one means
  the prereg was re-frozen. Adapted from ``no_longshot_pooled_test.check_freeze_introduction``.

Amendments (PIN-R8d): a prereg is never edited after its freeze. An amendment is a NEW file
(``..._v2.json``) with an amendment record, frozen once on its own; both results are reported.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

from scripts.analysis.multisource_blend_refusal import Refusal

__all__ = [
    "check_breaks_pinned",
    "check_not_refrozen",
    "check_pinned_lags_cover_c1",
    "flatten_observed_breaks",
    "observed_p99_ns",
]

UNFROZEN: Final[str] = "UNFROZEN"
_GIT_TIMEOUT_S: Final[int] = 20
_P99_NUMERATOR: Final[int] = 99
_P99_DENOMINATOR: Final[int] = 100
_COMMIT_PREFIX: Final[str] = "COMMIT "


# ------------------------------------------------------------------ PIN-R6


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def observed_p99_ns(samples: Sequence[int]) -> int:
    """Nearest-rank 99th percentile: the ceil(0.99 n)-th smallest sample (integer arithmetic)."""
    ordered = sorted(samples)
    rank = -(-_P99_NUMERATOR * len(ordered) // _P99_DENOMINATOR)
    return ordered[max(rank, 1) - 1]


def _samples_for(raw: Mapping[str, Any], source: str) -> list[int]:
    values = raw.get(source)
    if not isinstance(values, list) or not values or not all(_is_int(v) and v >= 0 for v in values):
        raise Refusal(
            f"C1 evidence has no usable samples for source {source!r} in lag_samples_ns: it must "
            f"be a non-empty list of non-negative integer ns (uncensored), was {values!r}; the "
            "p99 rule cannot be checked"
        )
    return list(values)


def check_pinned_lags_cover_c1(pinned: Mapping[str, int], raw_samples: object) -> None:
    """Refuse unless every pinned lag is >= the source's C1 observed p99 (PIN-R6)."""
    if not isinstance(raw_samples, Mapping):
        raise Refusal(
            "C1 evidence has no lag_samples_ns object {source: [uncensored lag ns, ...]}; "
            "the pinned lags cannot be checked against the C1 p99 (PIN-R6)"
        )
    below: list[str] = []
    for source in sorted(pinned):
        p99 = observed_p99_ns(_samples_for(raw_samples, source))
        if pinned[source] < p99:
            below.append(
                f"pins.source_lags_ns.{source} = {pinned[source]} ns is below the C1 observed "
                f"p99 {p99} ns"
            )
    if below:
        raise Refusal("; ".join(below) + " (PIN-R6)")


# ------------------------------------------------------------------ PIN-R7


def flatten_observed_breaks(observed: object) -> set[str]:
    """Every ISO date anywhere in the sidecar's ``source_breaks_observed`` (lists and objects)."""
    if not isinstance(observed, Mapping):
        raise TypeError(f"must be an object of date lists, was {observed!r}")
    found: set[str] = set()
    pending: list[object] = list(observed.values())
    while pending:
        item = pending.pop()
        if isinstance(item, Mapping):
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, str):
            dt.date.fromisoformat(item)  # ValueError on a non-date
            found.add(item)
        else:
            raise TypeError(f"holds {item!r}, which is not an ISO date")
    return found


def check_breaks_pinned(meta: Mapping[str, Any], pinned: Sequence[str], path: Path) -> None:
    """Refuse unless the sidecar's observed breaks are a subset of the pinned ``source_breaks``."""
    try:
        observed = flatten_observed_breaks(meta["source_breaks_observed"])
    except (ValueError, TypeError) as exc:
        raise Refusal(f"{path}: source_breaks_observed is unusable: {exc}") from exc
    missing = sorted(observed - set(pinned))
    if missing:
        raise Refusal(
            f"{path}: the builder observed source break(s) {missing} that are not in "
            "pins.source_breaks; breaks define folds and must be pinned before stage A (PIN-R7)"
        )


# ------------------------------------------------------------------ PIN-R8b


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT_S,
    )


def _history(root: Path, rel: str) -> list[tuple[str, str]]:
    """(commit, path at that commit) for every commit touching the file, following renames.

    ``git log --follow`` also follows COPIES: a new ``_v2.json`` amendment (PIN-R8d) is a near-copy
    of the frozen v1, and v1's commits would then count as v2's own freezes. A commit under another
    name counts only if that name is gone from HEAD, i.e. it was a real rename of this file.
    """
    done = _git(root, "log", "--follow", f"--format={_COMMIT_PREFIX}%H", "--name-only", "--", rel)
    if done.returncode != 0:
        raise Refusal(f"cannot read the git history of {rel}: {done.stderr.strip()}")
    entries: list[tuple[str, str]] = []
    sha = ""
    for line in done.stdout.splitlines():
        if line.startswith(_COMMIT_PREFIX):
            sha = line[len(_COMMIT_PREFIX) :].strip()
        elif line.strip() and sha:
            entries.append((sha, line.strip()))
    return [(sha, name) for sha, name in entries if name == rel or not _exists_at_head(root, name)]


def _exists_at_head(root: Path, name: str) -> bool:
    return _git(root, "cat-file", "-e", f"HEAD:{name}").returncode == 0


def _carries_a_freeze(root: Path, sha: str, name: str) -> bool:
    blob = _git(root, "show", f"{sha}:{name}")
    if blob.returncode != 0:
        return False
    try:
        body = json.loads(blob.stdout)
    except ValueError:
        return False
    stamp = body.get("frozen_sha") if isinstance(body, Mapping) else None
    return isinstance(stamp, str) and stamp != UNFROZEN


def check_not_refrozen(prereg: Path) -> None:
    """Refuse when more than one commit of the prereg file carries a non-UNFROZEN ``frozen_sha``."""
    top = _git(prereg.resolve().parent, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        raise Refusal(f"{prereg} is not inside a git repository; its freeze history is unknown")
    root = Path(top.stdout.strip())
    rel = prereg.resolve().relative_to(root.resolve()).as_posix()
    frozen = [sha for sha, name in _history(root, rel) if _carries_a_freeze(root, sha, name)]
    if len(frozen) > 1:
        raise Refusal(
            f"the prereg was re-frozen: {len(frozen)} commits of {rel} carry a non-UNFROZEN "
            f"frozen_sha ({', '.join(s[:12] for s in frozen)}); a freeze is made once, and an "
            "amendment goes into a new _v2 file (PIN-R8)"
        )
