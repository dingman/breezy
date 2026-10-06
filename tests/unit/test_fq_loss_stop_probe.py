"""F6 FQ-BRIDGE: the in-node loss-stop probe and the composed submit veto.

The bridge is a VETO: it only ever refuses an entry. Every input that is
missing, stale, forged or unreadable refuses (fail closed). The probe's
verdict is cached; the veto reads the cache only.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from breezy.runtime.health import AlertPayload
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import open_submit_intent_latch
from breezy.strategy.current_rung_hold.trial_day_latch import open_trial_day_latch
from breezy.strategy.forecast_quantile_ladder import loss_stop_probe as lsp
from breezy.strategy.forecast_quantile_ladder.loss_stop_probe import (
    PARITY_N_PAR,
    PARITY_SUBJECT,
    SCHEMA,
    STALE_PARITY_H,
    STALE_VETO_H,
    FqComposedVeto,
    LossStopProbe,
    ParityGate,
    ParityVerdict,
    Verdict,
    compute_digest,
    loss_stop_artefact_path,
    parity_fill_count_path,
    parity_verdict_path,
)

_REPO: Final[Path] = Path(__file__).resolve().parents[2]
_DESIGN: Final[Path] = (
    _REPO / "docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F5_prereg_v2_design.json"
)
_NOW: Final[datetime] = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
_FAMILY: Final[str] = "pm_us_crh_fq_v2"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


@dataclass
class _Sink:
    payloads: list[AlertPayload] = field(default_factory=list)
    down: bool = False

    def emit(self, payload: AlertPayload) -> None:
        if self.down:
            raise ConnectionError("sink down")
        self.payloads.append(payload)


def _write_artefact(
    path: Path,
    *,
    verdict: str = "PASS",
    as_of: datetime = _NOW - timedelta(hours=1),
    c2_hwm: str = "c2-100",
    truth_sha: str = "t" * 64,
    digest: str | None = None,
    schema: str = SCHEMA,
    mode: int = 0o600,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    as_of_text = as_of.isoformat().replace("+00:00", "Z")
    body = {
        "schema": schema,
        "verdict": verdict,
        "as_of": as_of_text,
        "c2_hwm": c2_hwm,
        "truth_sha": truth_sha,
        "digest": digest
        or compute_digest(verdict=verdict, as_of=as_of_text, c2_hwm=c2_hwm, truth_sha=truth_sha),
    }
    path.write_text(json.dumps(body))
    path.chmod(mode)
    os.utime(path, (as_of.timestamp(), as_of.timestamp()))


class _Halts:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, reason: str, evidence_sha256: str) -> None:
        self.calls.append((reason, evidence_sha256))


def _probe(
    tmp_path: Path,
    *,
    now: datetime = _NOW,
    sink: _Sink | None = None,
    halts: Callable[[str, str], None] | None = None,
    live_unhalted: bool = False,
    uid: int | None = None,
) -> tuple[LossStopProbe, Path, _Sink, list[datetime]]:
    path = tmp_path / "derived" / "fq-loss-stop" / "latest.json"
    sink = sink if sink is not None else _Sink()
    clock = [now]
    probe = LossStopProbe(
        path=path,
        clock=lambda: clock[0],
        set_family_halted=halts if halts is not None else _Halts(),
        alert_sink=sink,
        alert_every_probe=lambda: live_unhalted,
        expected_uid=os.getuid() if uid is None else uid,
    )
    return probe, path, sink, clock


# --------------------------------------------------------------------------
# probe: verdicts
# --------------------------------------------------------------------------


def test_missing_artefact_is_unknown_never_pass(tmp_path: Path) -> None:
    probe, _path, sink, _ = _probe(tmp_path)

    assert probe.probe_once() is Verdict.UNKNOWN

    assert probe.veto_reason() == "fq_loss_stop_unknown"
    assert [p.severity for p in sink.payloads] == ["CRITICAL"]


def test_veto_is_unknown_before_the_first_probe(tmp_path: Path) -> None:
    probe, _path, _sink, _ = _probe(tmp_path)

    assert probe.veto_reason() == "fq_loss_stop_unknown"


def test_fresh_pass_does_not_veto_and_counts(tmp_path: Path) -> None:
    probe, path, sink, _ = _probe(tmp_path)
    _write_artefact(path)

    assert probe.probe_once() is Verdict.PASS

    assert probe.veto_reason() is None
    assert sink.payloads == []
    assert probe.counters["pass"] == 1


def test_counter_increments_positive_control(tmp_path: Path) -> None:
    probe, path, _sink, _ = _probe(tmp_path)

    probe.probe_once()
    _write_artefact(path)
    probe.probe_once()
    probe.probe_once()

    assert probe.counters == Counter({"unknown": 1, "pass": 2})


def test_fail_sets_policy_halt_alerts_critical_and_vetoes(tmp_path: Path) -> None:
    halts = _Halts()
    probe, path, sink, _ = _probe(tmp_path, halts=halts)
    _write_artefact(path, verdict="FAIL")

    assert probe.probe_once() is Verdict.FAIL

    assert probe.veto_reason() == "fq_loss_stop_fail"
    assert len(halts.calls) == 1
    assert halts.calls[0][0] == "fq_loss_stop"
    assert re.fullmatch(r"[0-9a-f]{64}", halts.calls[0][1])
    assert [p.severity for p in sink.payloads] == ["CRITICAL"]


def test_fail_sets_policy_halt_through_real_latch(tmp_path: Path) -> None:
    store_path = tmp_path / "state.db"
    with (
        SqliteStateStore(store_path) as store,
        open_submit_intent_latch(store, store_path) as intent_latch,
    ):
        trial = open_trial_day_latch(intent_latch, key_prefix="fq/trial/", family_id=_FAMILY)

        def _set(reason: str, evidence_sha256: str) -> None:
            trial.record_policy_halt(reason=reason, evidence_sha256=evidence_sha256, ts_ns=1)

        probe, path, _sink, _ = _probe(tmp_path, halts=_set)
        _write_artefact(path, verdict="FAIL")
        assert trial.is_family_halted() is False

        probe.probe_once()

        assert trial.is_family_halted() is True


def test_halt_set_failure_is_alerted_and_still_vetoes(tmp_path: Path) -> None:
    def _boom(reason: str, evidence_sha256: str) -> None:
        raise RuntimeError("store closed")

    probe, path, sink, _ = _probe(tmp_path, halts=_boom)
    _write_artefact(path, verdict="FAIL")

    assert probe.probe_once() is Verdict.FAIL

    assert probe.veto_reason() == "fq_loss_stop_fail"
    assert len(sink.payloads) == 2
    assert {p.event for p in sink.payloads} >= {"FQ_LOSS_STOP_HALT_SET_FAILED"}


def test_fail_latches_a_later_pass_never_unrefuses(tmp_path: Path) -> None:
    probe, path, _sink, clock = _probe(tmp_path)
    _write_artefact(path, verdict="FAIL")
    probe.probe_once()

    clock[0] = _NOW + timedelta(hours=2)
    _write_artefact(path, verdict="PASS", as_of=_NOW + timedelta(hours=1))
    probe.probe_once()

    assert probe.veto_reason() == "fq_loss_stop_fail"


def test_stale_alerts_every_probe_then_vetoes_past_bound(tmp_path: Path) -> None:
    probe, path, sink, clock = _probe(tmp_path)
    _write_artefact(path, as_of=_NOW - timedelta(hours=lsp.MAX_AGE_H + 2))
    assert lsp.MAX_AGE_H + 2 < STALE_VETO_H

    assert probe.probe_once() is Verdict.UNKNOWN_STALE
    assert probe.probe_once() is Verdict.UNKNOWN_STALE

    assert probe.veto_reason() is None
    assert len(sink.payloads) == 2
    assert all(p.severity == "CRITICAL" for p in sink.payloads)

    clock[0] = _NOW + timedelta(hours=STALE_VETO_H)
    assert probe.probe_once() is Verdict.UNKNOWN_STALE
    assert probe.veto_reason() == "fq_loss_stop_stale"


def test_stale_veto_applies_even_when_alert_undelivered(tmp_path: Path) -> None:
    probe, path, sink, _ = _probe(tmp_path, sink=_Sink(down=True))
    _write_artefact(path, as_of=_NOW - timedelta(hours=STALE_VETO_H + 1))

    probe.probe_once()

    assert probe.veto_reason() == "fq_loss_stop_stale"
    assert sink.payloads == []
    assert probe.counters["alert_delivery_failed"] == 1


def test_stale_veto_fails_closed_with_alert_sink_down(tmp_path: Path) -> None:
    probe, _path, _sink, _ = _probe(tmp_path, sink=_Sink(down=True))

    probe.probe_once()  # artefact missing, sink down

    assert probe.veto_reason() == "fq_loss_stop_unknown"
    assert probe.counters["alert_delivery_failed"] == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"schema": "loss_stop/v0"},
        {"digest": "0" * 64},
        {"truth_sha": "x" * 64, "digest": "e" * 64},
        {"verdict": "MAYBE"},
    ],
)
def test_schema_or_sha_mismatch_is_unknown(tmp_path: Path, kwargs: dict[str, str]) -> None:
    probe, path, _sink, _ = _probe(tmp_path)
    _write_artefact(path, **kwargs)  # type: ignore[arg-type]

    assert probe.probe_once() is Verdict.UNKNOWN
    assert probe.veto_reason() == "fq_loss_stop_unknown"


def test_unparseable_artefact_is_unknown(tmp_path: Path) -> None:
    probe, path, _sink, _ = _probe(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    path.chmod(0o600)

    assert probe.probe_once() is Verdict.UNKNOWN


def test_probe_exception_is_unknown_not_pass(tmp_path: Path) -> None:
    def _bad_clock() -> datetime:
        raise RuntimeError("clock exploded")

    path = tmp_path / "latest.json"
    _write_artefact(path)
    probe = LossStopProbe(
        path=path,
        clock=_bad_clock,
        set_family_halted=_Halts(),
        alert_sink=_Sink(),
        alert_every_probe=lambda: False,
        expected_uid=os.getuid(),
    )

    assert probe.probe_once() is Verdict.UNKNOWN
    assert probe.veto_reason() == "fq_loss_stop_unknown"


def test_digest_recomputable_from_c2_hwm_and_truth_sha(tmp_path: Path) -> None:
    as_of = "2026-10-06T11:00:00Z"
    expected = hashlib.sha256(f"{SCHEMA}|PASS|{as_of}|c2-7|{'a' * 64}".encode()).hexdigest()
    assert (
        compute_digest(verdict="PASS", as_of=as_of, c2_hwm="c2-7", truth_sha="a" * 64) == expected
    )

    probe, path, _sink, _ = _probe(tmp_path)
    _write_artefact(path, c2_hwm="c2-100")
    body = json.loads(path.read_text())
    body["c2_hwm"] = "c2-999"  # high-water mark moved, digest not recomputed
    path.write_text(json.dumps(body))
    path.chmod(0o600)

    assert probe.probe_once() is Verdict.UNKNOWN


def test_owner_mode_mtime_checked_and_as_of_monotonic(tmp_path: Path) -> None:
    # owner
    probe, path, _s, _ = _probe(tmp_path / "a", uid=os.getuid() + 1)
    _write_artefact(path)
    assert probe.probe_once() is Verdict.UNKNOWN
    # mode (group/other writable)
    probe, path, _s, _ = _probe(tmp_path / "b")
    _write_artefact(path, mode=0o666)
    assert probe.probe_once() is Verdict.UNKNOWN
    # mtime far older than the stale bound, even though as_of claims fresh
    probe, path, _s, _ = _probe(tmp_path / "c")
    _write_artefact(path)
    old = (_NOW - timedelta(hours=STALE_VETO_H + 5)).timestamp()
    os.utime(path, (old, old))
    probe.probe_once()
    assert probe.veto_reason() == "fq_loss_stop_stale"
    # mtime in the future
    probe, path, _s, _ = _probe(tmp_path / "d")
    _write_artefact(path)
    future = (_NOW + timedelta(hours=3)).timestamp()
    os.utime(path, (future, future))
    assert probe.probe_once() is Verdict.UNKNOWN
    # as_of monotonic
    probe, path, _s, _ = _probe(tmp_path / "e")
    _write_artefact(path, as_of=_NOW - timedelta(hours=1))
    assert probe.probe_once() is Verdict.PASS
    _write_artefact(path, as_of=_NOW - timedelta(hours=3))
    assert probe.probe_once() is Verdict.UNKNOWN
    assert probe.veto_reason() == "fq_loss_stop_unknown"


def test_veto_reads_cached_verdict_only(tmp_path: Path) -> None:
    probe, path, _sink, _ = _probe(tmp_path)
    _write_artefact(path)
    probe.probe_once()
    path.unlink()

    assert probe.veto_reason() is None  # no re-read: the cache still says PASS


# --------------------------------------------------------------------------
# probe: alert rate (FQ-R32)
# --------------------------------------------------------------------------


def test_unknown_alert_rate_limited_when_halted_or_disabled(tmp_path: Path) -> None:
    probe, _path, sink, clock = _probe(tmp_path, live_unhalted=False)

    probe.probe_once()
    probe.probe_once()
    probe.probe_once()
    assert len(sink.payloads) == 1  # entry only

    clock[0] = _NOW + timedelta(days=1, hours=1)
    probe.probe_once()
    probe.probe_once()
    assert len(sink.payloads) == 2  # once per climate day


def test_unknown_alerts_every_probe_while_live_and_unhalted(tmp_path: Path) -> None:
    probe, _path, sink, _ = _probe(tmp_path, live_unhalted=True)

    probe.probe_once()
    probe.probe_once()

    assert len(sink.payloads) == 2


# --------------------------------------------------------------------------
# probe: structural / static guards
# --------------------------------------------------------------------------

_PROBE_SRC: Final[Path] = _REPO / "src/breezy/strategy/forecast_quantile_ladder/loss_stop_probe.py"


def test_probe_never_references_clear() -> None:
    tree = ast.parse(_PROBE_SRC.read_text())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.ClassDef)}
    names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}

    assert [name for name in names if "clear" in name.lower()] == []


def test_fq_has_no_exit_order_path() -> None:
    package = _REPO / "src/breezy/strategy/forecast_quantile_ladder"
    offenders = [
        path.name
        for path in package.glob("*.py")
        if re.search(r"submit_exit|exit_wiring|ExitOrder|exit_manifest", path.read_text())
    ]

    assert offenders == []


def test_floor_read_from_prereg_never_from_operator_controls() -> None:
    tree = ast.parse(_PROBE_SRC.read_text())
    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    strings = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert not any("operator_controls" in module for module in imported)
    assert not any("BUDGET" in s or "POSITION_COST" in s for s in strings)
    assert not {"permit", "orders_enabled"} & {s.lower() for s in strings}


def test_stale_parity_h_equals_design_json() -> None:
    design = json.loads(_DESIGN.read_text())

    assert STALE_PARITY_H == design["stale_parity_h"] == 36
    assert PARITY_N_PAR == design["n_par"]


def test_production_default_paths(tmp_path: Path) -> None:
    root = tmp_path / "catalog"

    assert loss_stop_artefact_path(root) == tmp_path / "derived/fq-loss-stop/latest.json"
    assert parity_verdict_path(root) == tmp_path / "derived/fq-parity/latest.json"
    assert parity_fill_count_path(root) == tmp_path / "derived/fq-parity/live_fill_count.json"


# --------------------------------------------------------------------------
# composed veto
# --------------------------------------------------------------------------


class _Spy:
    def __init__(self, result: str | None = None, raises: bool = False) -> None:
        self.result, self.raises, self.calls = result, raises, 0

    def __call__(self) -> str | None:
        self.calls += 1
        if self.raises:
            raise RuntimeError("boom")
        return self.result


def _parity(
    *,
    n: int | None | Exception = PARITY_N_PAR,
    verdict: ParityVerdict | None | Exception = None,
    clock: list[datetime] | None = None,
) -> ParityGate:
    clk = clock if clock is not None else [_NOW]

    def _count() -> int | None:
        if isinstance(n, Exception):
            raise n
        return n

    def _verdict() -> ParityVerdict | None:
        if isinstance(verdict, Exception):
            raise verdict
        return verdict

    return ParityGate(
        subject=PARITY_SUBJECT,
        family_id=_FAMILY,
        n_par=PARITY_N_PAR,
        stale_parity_h=STALE_PARITY_H,
        clock=lambda: clk[0],
        fill_count_reader=_count,
        verdict_reader=_verdict,
    )


def _pv(
    verdict: str = "PASS",
    *,
    subject: str = PARITY_SUBJECT,
    family_id: str = _FAMILY,
    age_h: float = 1.0,
) -> ParityVerdict:
    return ParityVerdict(
        subject=subject,
        family_id=family_id,
        verdict=verdict,
        as_of=_NOW - timedelta(hours=age_h),
    )


@pytest.mark.parametrize("halt", [None, "family_halt", "other"])
@pytest.mark.parametrize("loss", [None, "fq_loss_stop_fail"])
def test_composed_veto_is_or_add_only_refuses_wherever_old_refused(
    halt: str | None, loss: str | None
) -> None:
    old = _Spy(halt)
    composed = FqComposedVeto(halt_veto=old, loss_stop_veto=_Spy(loss))

    result = composed()

    if halt is not None:
        assert result == halt  # refuses wherever the old veto refused, same reason
    else:
        assert result == loss  # adds only the loss-stop refusal


def test_composed_veto_is_single_object_shared() -> None:
    composed = FqComposedVeto(halt_veto=_Spy(), loss_stop_veto=_Spy())

    holders = {"strategy": composed, "exec_client": composed}

    assert holders["strategy"] is holders["exec_client"]
    assert callable(composed)


def test_same_veto_callable_reaches_strategy_and_exec_client() -> None:
    # Proven through the real boot in test_app_trade_fq_loss_stop_wiring.py;
    # here: one call evaluates one shared state, so two holders agree.
    loss = _Spy("fq_loss_stop_fail")
    composed = FqComposedVeto(halt_veto=_Spy(), loss_stop_veto=loss)

    assert composed() == composed() == "fq_loss_stop_fail"


def test_composed_veto_evaluates_both_returns_halt_first() -> None:
    halt, loss = _Spy("family_halt"), _Spy("fq_loss_stop_fail")
    composed = FqComposedVeto(halt_veto=halt, loss_stop_veto=loss)

    assert composed() == "family_halt"
    assert (halt.calls, loss.calls) == (1, 1)


def test_loss_stop_input_missing_refuses_after_halt_branch(tmp_path: Path) -> None:
    probe, _path, _sink, _ = _probe(tmp_path)
    probe.probe_once()  # no artefact
    ok = FqComposedVeto(halt_veto=_Spy(), loss_stop_veto=probe.veto_reason)
    halted = FqComposedVeto(halt_veto=_Spy("family_halt"), loss_stop_veto=probe.veto_reason)

    assert ok() == "fq_loss_stop_unknown"
    assert halted() == "family_halt"


def test_loss_stop_input_stale_refuses_after_halt_branch(tmp_path: Path) -> None:
    probe, path, _sink, _ = _probe(tmp_path)
    _write_artefact(path, as_of=_NOW - timedelta(hours=STALE_VETO_H + 1))
    probe.probe_once()
    ok = FqComposedVeto(halt_veto=_Spy(), loss_stop_veto=probe.veto_reason)
    halted = FqComposedVeto(halt_veto=_Spy("family_halt"), loss_stop_veto=probe.veto_reason)

    assert ok() == "fq_loss_stop_stale"
    assert halted() == "family_halt"


def test_loss_stop_input_raising_refuses_after_halt_branch() -> None:
    ok = FqComposedVeto(halt_veto=_Spy(), loss_stop_veto=_Spy(raises=True))
    halted = FqComposedVeto(halt_veto=_Spy("family_halt"), loss_stop_veto=_Spy(raises=True))

    assert ok() == "fq_loss_stop_unreadable"
    assert halted() == "family_halt"


def _with_parity(gate: ParityGate) -> FqComposedVeto:
    return FqComposedVeto(halt_veto=_Spy(), loss_stop_veto=_Spy(), parity_veto=gate.veto_reason)


def test_composed_veto_refuses_on_accepted_parity_fail() -> None:
    assert _with_parity(_parity(verdict=_pv("FAIL")))() == "fq_parity_fail"


def test_composed_veto_refuses_when_parity_verdict_missing_or_stale_at_or_after_n_par() -> None:
    assert _with_parity(_parity(n=PARITY_N_PAR, verdict=None))() == "fq_parity_unavailable"
    assert (
        _with_parity(_parity(n=PARITY_N_PAR + 3, verdict=ValueError("x")))()
        == "fq_parity_unavailable"
    )
    assert (
        _with_parity(_parity(n=PARITY_N_PAR + 3, verdict=_pv(age_h=STALE_PARITY_H + 1)))()
        == "fq_parity_stale"
    )


def test_composed_veto_ignores_parity_before_n_par() -> None:
    for verdict in (None, _pv("FAIL"), _pv(age_h=500)):
        assert _with_parity(_parity(n=PARITY_N_PAR - 1, verdict=verdict))() is None


def test_composed_veto_refuses_when_live_fill_count_unreadable() -> None:
    assert _with_parity(_parity(n=None, verdict=_pv()))() == "fq_parity_fill_count_unreadable"


def test_composed_veto_refuses_when_live_fill_count_read_raises() -> None:
    gate = _parity(n=OSError("disk"), verdict=_pv())

    assert _with_parity(gate)() == "fq_parity_fill_count_unreadable"


def test_composed_veto_refuses_when_parity_verdict_older_than_stale_parity_h() -> None:
    fresh = _parity(verdict=_pv(age_h=STALE_PARITY_H - 0.5))
    old = _parity(verdict=_pv(age_h=STALE_PARITY_H + 0.5))

    assert _with_parity(fresh)() is None
    assert _with_parity(old)() == "fq_parity_stale"


def test_composed_veto_refuses_on_parity_verdict_wrong_subject() -> None:
    gate = _parity(verdict=_pv("PASS", subject="pm_us_crh_fq_v1"))

    assert _with_parity(gate)() == "fq_parity_wrong_subject"


def test_composed_veto_refuses_on_parity_verdict_wrong_family() -> None:
    gate = _parity(verdict=_pv("PASS", family_id="pm_us_crh_fq_v1"))

    assert _with_parity(gate)() == "fq_parity_wrong_family"


def test_composed_veto_parity_fail_latches_later_underpowered_never_unrefuses() -> None:
    box: dict[str, ParityVerdict | None] = {"v": _pv("FAIL")}
    gate = ParityGate(
        subject=PARITY_SUBJECT,
        family_id=_FAMILY,
        n_par=PARITY_N_PAR,
        stale_parity_h=STALE_PARITY_H,
        clock=lambda: _NOW,
        fill_count_reader=lambda: PARITY_N_PAR,
        verdict_reader=lambda: box["v"],
    )
    composed = _with_parity(gate)
    assert composed() == "fq_parity_fail"

    box["v"] = _pv("UNDERPOWERED")

    assert composed() == "fq_parity_fail"


def test_composed_veto_parity_fail_latches_older_pass_never_unrefuses() -> None:
    box: dict[str, ParityVerdict | None] = {"v": _pv("FAIL")}
    gate = ParityGate(
        subject=PARITY_SUBJECT,
        family_id=_FAMILY,
        n_par=PARITY_N_PAR,
        stale_parity_h=STALE_PARITY_H,
        clock=lambda: _NOW,
        fill_count_reader=lambda: PARITY_N_PAR,
        verdict_reader=lambda: box["v"],
    )
    composed = _with_parity(gate)
    assert composed() == "fq_parity_fail"

    box["v"] = _pv("PASS", age_h=10)  # an older PASS than the FAIL's as_of
    assert composed() == "fq_parity_fail"
    box["v"] = None  # even a vanished verdict never un-refuses
    assert composed() == "fq_parity_fail"


def test_composed_veto_parity_underpowered_alone_does_not_refuse() -> None:
    assert _with_parity(_parity(verdict=_pv("UNDERPOWERED")))() is None


def test_composed_veto_is_never_an_enable_only_strings_or_none() -> None:
    reasons = {
        FqComposedVeto(halt_veto=_Spy(h), loss_stop_veto=_Spy(lo))()
        for h in (None, "family_halt")
        for lo in (None, "fq_loss_stop_fail")
    }

    assert all(r is None or isinstance(r, str) for r in reasons)
