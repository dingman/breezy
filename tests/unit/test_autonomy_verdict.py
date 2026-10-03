"""ARCH-0 seam 5a: the C4 ``verdict/v1`` record, its id, and its write-once store."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.persistence.autonomy.canonical import canonical_json
from breezy.persistence.autonomy.paths import AutonomyPaths, ShadowPaths
from breezy.persistence.autonomy.pins import MAX_VERDICT_VALIDITY_H
from breezy.persistence.autonomy.single_read import WriteOutcome
from breezy.persistence.autonomy.verdict import (
    ActionClass,
    Assumption,
    Verdict,
    VerdictIdCollision,
    VerdictInput,
    VerdictKind,
    VerdictOutcome,
    VerdictRefusalReason,
    VerdictRefused,
    VerdictUnreadable,
    read_verdict,
    write_verdict,
)
from breezy.persistence.autonomy.wire import (
    WireRefusalReason,
    WireRefused,
    parse_json_exact,
)

SHA_A, SHA_B, SHA_C, SHA_D = ("a" * 64, "b" * 64, "c" * 64, "d" * 64)
HOUR_NS = 3_600 * 10**9
PRODUCED = int(datetime(2026, 10, 4, 6, 0, tzinfo=UTC).timestamp()) * 10**9
FAMILY = "pm_us_crh_fq_v1"

#: The exact ``verdict/v1`` key set (ARCH C4), plus ``schema``.
EXPECTED_KEYS = frozenset(
    {
        "schema", "verdict_id", "kind", "subject_family_id", "subject_artefact_sha256",
        "comparator_family_id", "outcome", "detector", "declared_action_class", "metrics", "n",
        "n_min", "power", "mde", "eta_to_verdict_days", "alpha_spent", "k_life", "alpha_k",
        "n_min_eff", "n_cap", "inputs", "policy_ruling_sha256", "family_prereg_sha256",
        "produced_at_ns", "valid_until_ns", "producer_code_sha", "assumptions",
    }
)  # fmt: skip


def make(**overrides: Any) -> Verdict:
    fields: dict[str, Any] = {
        "kind": VerdictKind.HEALTH,
        "subject_family_id": FAMILY,
        "outcome": VerdictOutcome.PASS,
        "detector": "health.capture_join",
        "declared_action_class": ActionClass.NONE,
        "metrics": (("join_ratio", Decimal(1)),),
        "n": 12,
        "n_min": 10,
        "inputs": (VerdictInput("labels", SHA_C),),
        "policy_ruling_sha256": SHA_D,
        "produced_at_ns": PRODUCED,
        "valid_until_ns": PRODUCED + 8 * HOUR_NS,
        "producer_code_sha": SHA_B,
    }
    fields.update(overrides)
    return Verdict(**fields)


def forward_shadow(**overrides: Any) -> Verdict:
    fields: dict[str, Any] = {
        "kind": VerdictKind.FORWARD_SHADOW,
        "subject_artefact_sha256": SHA_A,
        "comparator_family_id": "pm_us_crh_v4",
        "power": Decimal("0.8"),
        "mde": Decimal("0.0125"),
        "eta_to_verdict_days": Decimal("41.5"),
        "alpha_spent": Decimal("0.025"),
        "k_life": 2,
        "alpha_k": Decimal("0.0125"),
        "n_min_eff": 403,
        "n_cap": 480,
    }
    fields.update(overrides)
    return make(**fields)


def refusal(exc: pytest.ExceptionInfo[WireRefused]) -> WireRefusalReason:
    return exc.value.reason


# --- the record -----------------------------------------------------------------------------


def test_verdict_exact_set_and_closed_enums() -> None:
    wire = forward_shadow().to_wire()
    assert set(wire) == EXPECTED_KEYS
    assert wire["schema"] == "verdict/v1"
    assert {k.value for k in VerdictKind} == {
        "OFFLINE_CHALLENGER", "FORWARD_SHADOW", "LIVE_SEQUENTIAL", "DRIFT", "HEALTH",
        "RECONCILIATION",
    }  # fmt: skip
    assert {o.value for o in VerdictOutcome} == {
        "PASS", "FAIL", "UNDERPOWERED", "INCONCLUSIVE", "ERROR",
    }  # fmt: skip
    assert {a.value for a in ActionClass} == {"NONE", "ALERT", "SELF_HEAL", "DEMOTE", "HALT"}
    assert {a.value for a in Assumption} == {
        "slippage_champion_proxy", "slippage_floor_aud12a", "fill_survivorship_unmodelled",
        "no_policy_ruling", "drill",
    }  # fmt: skip


def test_roundtrip_through_bytes_is_lossless() -> None:
    original = forward_shadow(
        assumptions=(Assumption.DRILL, Assumption.SLIPPAGE_CHAMPION_PROXY),
        inputs=(VerdictInput("champion_labels", SHA_A), VerdictInput("labels", SHA_C)),
    )
    parsed = Verdict.from_wire(parse_json_exact(canonical_json(original.to_wire())))
    assert parsed == original
    assert parsed.verdict_id == original.verdict_id


@pytest.mark.parametrize("key", sorted(EXPECTED_KEYS - {"schema"}))
def test_from_wire_refuses_a_missing_key(key: str) -> None:
    wire = forward_shadow().to_wire()
    del wire[key]
    with pytest.raises(WireRefused) as info:
        Verdict.from_wire(wire)
    assert refusal(info) is WireRefusalReason.MISSING_KEY


def test_from_wire_refuses_an_unknown_key_and_a_wrong_schema() -> None:
    wire = make().to_wire()
    with pytest.raises(WireRefused) as info:
        Verdict.from_wire({**wire, "extra": 1})
    assert refusal(info) is WireRefusalReason.UNKNOWN_KEY
    with pytest.raises(WireRefused) as info:
        Verdict.from_wire({**wire, "schema": "lineage/v1"})
    assert refusal(info) is WireRefusalReason.BAD_VALUE


@pytest.mark.parametrize(
    "key, bad",
    [
        ("kind", "OTHER"),
        ("outcome", "pass"),
        ("declared_action_class", "RESTART"),
        ("assumptions", ["unknown_assumption"]),
        ("subject_family_id", "../x"),
        ("producer_code_sha", "A" * 64),
        ("policy_ruling_sha256", "short"),
    ],
)
def test_from_wire_refuses_a_closed_set_or_shape_violation(key: str, bad: object) -> None:
    wire = make().to_wire()
    wire[key] = bad
    with pytest.raises(WireRefused):
        Verdict.from_wire(wire)


def test_from_wire_refuses_a_verdict_id_that_is_not_the_body_hash() -> None:
    wire = make().to_wire()
    wire["verdict_id"] = SHA_A
    with pytest.raises(WireRefused) as info:
        Verdict.from_wire(wire)
    assert refusal(info) is WireRefusalReason.BAD_VALUE


def test_forward_shadow_columns_are_null_on_every_other_kind() -> None:
    for column, value in (
        ("k_life", 1),
        ("alpha_k", Decimal("0.01")),
        ("n_min_eff", 5),
        ("n_cap", 9),
    ):
        with pytest.raises(WireRefused):
            make(**{column: value})
    with pytest.raises(WireRefused):
        make(family_prereg_sha256=SHA_A)  # LIVE_SEQUENTIAL only
    assert make(kind=VerdictKind.LIVE_SEQUENTIAL, family_prereg_sha256=SHA_A)


def test_null_policy_ruling_requires_the_no_policy_ruling_assumption() -> None:
    with pytest.raises(WireRefused):
        make(policy_ruling_sha256=None)
    assert make(policy_ruling_sha256=None, assumptions=(Assumption.NO_POLICY_RULING,))


def test_inputs_and_assumptions_must_be_canonically_ordered_and_unique() -> None:
    with pytest.raises(WireRefused):
        make(inputs=(VerdictInput("z", SHA_A), VerdictInput("a", SHA_A)))
    with pytest.raises(WireRefused):
        make(inputs=(VerdictInput("a", SHA_B), VerdictInput("a", SHA_A)))  # same role, unsorted
    with pytest.raises(WireRefused):
        make(assumptions=(Assumption.DRILL, Assumption.DRILL))
    with pytest.raises(WireRefused):
        make(assumptions=(Assumption.NO_POLICY_RULING, Assumption.DRILL))


@pytest.mark.parametrize("role", ["/home/x", "a/b", "..", "", "A", "x" * 65])
def test_input_roles_carry_no_paths(role: str) -> None:
    with pytest.raises(WireRefused):
        VerdictInput(role, SHA_A)


def test_decimal_fields_canonical_strings() -> None:
    wire = forward_shadow(power=Decimal("0.80"), mde=Decimal(0)).to_wire()
    assert wire["power"] == "0.8"
    assert wire["mde"] == "0"
    assert wire["alpha_k"] == "0.0125"
    assert wire["metrics"] == {"join_ratio": "1"}
    # Every non-integer number on the wire is a string, never a JSON float.
    raw = canonical_json(wire).decode()
    parse_json_exact(raw)  # no float token anywhere
    for column in ("power", "mde", "eta_to_verdict_days", "alpha_spent", "alpha_k"):
        assert isinstance(wire[column], str)


@pytest.mark.parametrize("bad", ["0.80", "1e-2", "+1", " 1", "NaN", "Infinity", "", "1."])
def test_decimal_fields_refuse_noncanonical_text(bad: str) -> None:
    wire = forward_shadow().to_wire()
    wire["power"] = bad
    with pytest.raises(WireRefused):
        Verdict.from_wire(wire)


def test_decimal_fields_refuse_floats_and_nonfinite() -> None:
    wire = forward_shadow().to_wire()
    wire["power"] = 0.8
    with pytest.raises(WireRefused) as info:
        Verdict.from_wire(wire)
    assert refusal(info) is WireRefusalReason.WRONG_TYPE
    with pytest.raises(WireRefused) as info:
        parse_json_exact('{"schema":"verdict/v1","power":0.8}')
    assert refusal(info) is WireRefusalReason.FLOAT_TOKEN
    with pytest.raises(WireRefused):
        forward_shadow(power=Decimal("NaN"))


# --- the id ---------------------------------------------------------------------------------


def test_verdict_id_is_sha256_of_the_body_without_id_and_produced_at() -> None:
    verdict = forward_shadow()
    body = verdict.to_wire()
    del body["verdict_id"], body["produced_at_ns"]
    expected = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    assert verdict.verdict_id == expected


def test_verdict_id_excludes_produced_at() -> None:
    first = forward_shadow(produced_at_ns=PRODUCED)
    later = forward_shadow(produced_at_ns=PRODUCED + 1)
    assert first.verdict_id == later.verdict_id
    assert first.to_wire() != later.to_wire()
    # Any other field moves the id, valid_until_ns (slot anchor) included.
    assert forward_shadow(valid_until_ns=PRODUCED + HOUR_NS).verdict_id != first.verdict_id
    assert forward_shadow(n=13).verdict_id != first.verdict_id


def test_verdict_id_golden() -> None:
    # Independently derived: sha256 of the literal body (sorted keys, compact separators).
    assert make().verdict_id == "a99c03789a35384e5321b3333e52b94c5fc47d72cdfe1c107b4f8698d30a222d"


def test_recompute_same_slot_same_inputs_same_verdict_id(tmp_path: Path) -> None:
    paths = AutonomyPaths(tmp_path)
    first = write_verdict(paths, forward_shadow(produced_at_ns=PRODUCED))
    again = write_verdict(paths, forward_shadow(produced_at_ns=PRODUCED + 7 * 10**9))
    assert (first, again) == (WriteOutcome.WRITTEN, WriteOutcome.EXISTS_EQUAL)
    files = list((tmp_path / "derived" / "verdicts").rglob("*.json"))
    assert len(files) == 1
    kept = parse_json_exact(files[0].read_bytes())
    assert kept["produced_at_ns"] == PRODUCED  # the first writer's bytes stay


# --- the store ------------------------------------------------------------------------------


def test_write_lands_under_the_valid_until_utc_date_with_mode_0600(tmp_path: Path) -> None:
    verdict = make(valid_until_ns=PRODUCED + 20 * HOUR_NS)  # 2026-10-05T02:00Z
    write_verdict(AutonomyPaths(tmp_path), verdict)
    path = tmp_path / "derived" / "verdicts" / FAMILY / "2026-10-05" / f"{verdict.verdict_id}.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert path.read_bytes() == canonical_json(verdict.to_wire())


def test_date_is_taken_in_utc_at_the_day_boundary(tmp_path: Path) -> None:
    midnight = int(datetime(2026, 10, 5, 0, 0, tzinfo=UTC).timestamp()) * 10**9
    before = make(produced_at_ns=midnight - 2 * HOUR_NS, valid_until_ns=midnight - 1)
    after = make(produced_at_ns=midnight - 2 * HOUR_NS, valid_until_ns=midnight)
    assert before.valid_until_date() == "2026-10-04"
    assert after.valid_until_date() == "2026-10-05"


def test_shadow_paths_write_under_their_own_root(tmp_path: Path) -> None:
    verdict = make()
    assert write_verdict(ShadowPaths(tmp_path), verdict) is WriteOutcome.WRITTEN
    assert (
        read_verdict(ShadowPaths(tmp_path), FAMILY, verdict.valid_until_date(), verdict.verdict_id)
        == verdict
    )


def test_differing_body_same_id_refused(tmp_path: Path) -> None:
    paths = AutonomyPaths(tmp_path)
    verdict = make()
    write_verdict(paths, verdict)
    path = paths.verdict_file(FAMILY, verdict.valid_until_date(), verdict.verdict_id)
    # A valid, self-consistent verdict with another body sits under this id: only the body
    # compare can refuse it.
    path.write_bytes(canonical_json(make(n=99).to_wire()))
    with pytest.raises(VerdictIdCollision):
        write_verdict(paths, verdict)
    # A body whose own hash is not this id is refused too.
    forged = dict(make(n=99).to_wire(), verdict_id=verdict.verdict_id)
    path.write_bytes(canonical_json(forged))
    with pytest.raises(VerdictIdCollision):
        write_verdict(paths, verdict)
    # Unparseable bytes under the id are a collision too, never a silent no-op.
    path.write_bytes(b"not json")
    with pytest.raises(VerdictIdCollision):
        write_verdict(paths, verdict)


def test_differing_only_in_produced_at_is_a_noop_not_a_collision(tmp_path: Path) -> None:
    paths = AutonomyPaths(tmp_path)
    write_verdict(paths, make(produced_at_ns=PRODUCED))
    assert write_verdict(paths, make(produced_at_ns=PRODUCED + 1)) is WriteOutcome.EXISTS_EQUAL


@pytest.mark.parametrize("writer", ["writer"])
def test_verdict_validity_ceiling(writer: str, tmp_path: Path) -> None:
    ceiling = MAX_VERDICT_VALIDITY_H * HOUR_NS
    ok = make(valid_until_ns=PRODUCED + ceiling)
    assert write_verdict(AutonomyPaths(tmp_path), ok) is WriteOutcome.WRITTEN
    over = make(valid_until_ns=PRODUCED + ceiling + 1)
    with pytest.raises(VerdictRefused) as info:
        write_verdict(AutonomyPaths(tmp_path), over)
    assert info.value.reason is VerdictRefusalReason.VALIDITY_ABOVE_CEILING
    assert not list((tmp_path / "derived" / "verdicts" / FAMILY).glob(f"*/{over.verdict_id}.json"))


def test_read_verdict_roundtrips_and_names_each_failure(tmp_path: Path) -> None:
    paths = AutonomyPaths(tmp_path)
    verdict = make()
    write_verdict(paths, verdict)
    day = verdict.valid_until_date()
    assert read_verdict(paths, FAMILY, day, verdict.verdict_id) == verdict

    with pytest.raises(VerdictUnreadable):  # absent
        read_verdict(paths, FAMILY, day, SHA_A)
    path = paths.verdict_file(FAMILY, day, verdict.verdict_id)
    link = paths.verdict_file(FAMILY, day, SHA_A)
    os.symlink(path, link)
    with pytest.raises(VerdictUnreadable):  # symlink
        read_verdict(paths, FAMILY, day, SHA_A)
    path.write_bytes(b"{")
    with pytest.raises(VerdictUnreadable):  # malformed
        read_verdict(paths, FAMILY, day, verdict.verdict_id)
    path.write_bytes(canonical_json(make(n=1).to_wire()))
    with pytest.raises(VerdictUnreadable):  # body hash is not the filename id
        read_verdict(paths, FAMILY, day, verdict.verdict_id)
    path.write_bytes(b"x" * (1 << 20))
    with pytest.raises(VerdictUnreadable):  # oversize
        read_verdict(paths, FAMILY, day, verdict.verdict_id)


def test_read_verdict_refuses_a_file_filed_under_another_family(tmp_path: Path) -> None:
    paths = AutonomyPaths(tmp_path)
    verdict = make()
    write_verdict(paths, verdict)
    day = verdict.valid_until_date()
    other = paths.verdict_file("pm_us_crh_v4", day, verdict.verdict_id)
    other.parent.mkdir(parents=True)
    other.write_bytes(paths.verdict_file(FAMILY, day, verdict.verdict_id).read_bytes())
    with pytest.raises(VerdictUnreadable):
        read_verdict(paths, "pm_us_crh_v4", day, verdict.verdict_id)


def test_refusal_messages_carry_no_path(tmp_path: Path) -> None:
    paths = AutonomyPaths(tmp_path)
    with pytest.raises(VerdictUnreadable) as info:
        read_verdict(paths, FAMILY, "2026-10-05", SHA_A)
    assert str(tmp_path) not in str(info.value)


# --- A5-R2 metrics values, A5-R3 inputs, A5-R5 verdict LOW items -------------------------------


def test_metric_values_admit_decimal_text_bool_and_null() -> None:
    verdict = make(
        metrics=(
            ("cause_class", "RECOVERABLE_INFRA"),
            ("day_status", "NO_INPUT"),
            ("exec_snapshot_advisory", True),
            ("join_ratio", Decimal("0.98")),
            ("reason", "INCONCLUSIVE(calibration_buckets_below_min)"),
            ("statistic", None),
        )
    )
    wire = verdict.to_wire()
    assert wire["metrics"] == {
        "cause_class": "RECOVERABLE_INFRA",
        "day_status": "NO_INPUT",
        "exec_snapshot_advisory": True,
        "join_ratio": "0.98",
        "reason": "INCONCLUSIVE(calibration_buckets_below_min)",
        "statistic": None,
    }
    assert Verdict.from_wire(parse_json_exact(canonical_json(wire))) == verdict


def test_metric_text_golden_with_day_status_no_input() -> None:
    verdict = make(metrics=(("day_status", "NO_INPUT"),))
    # Independently derived: sha256 of the literal body (sorted keys, compact separators).
    assert verdict.verdict_id == "e94075769c3ad70cd1f9f43d961b633df3b7184451522b189afe6dea08d35590"


@pytest.mark.parametrize(
    "bad", ["has space", "a/b", "é", "x" * 129, "semi;colon", "", "tab\t", "/home/x"]
)
def test_metric_text_outside_the_charset_or_length_is_refused(bad: str) -> None:
    with pytest.raises(WireRefused):
        make(metrics=(("m", bad),))
    wire = make().to_wire()
    wire["metrics"] = {"m": bad}
    with pytest.raises(WireRefused):
        Verdict.from_wire(wire)


def test_metric_text_at_the_length_limit_and_every_charset_member_is_admitted() -> None:
    assert make(metrics=(("m", "a" * 128),))
    assert make(metrics=(("m", "AZaz09_:.()=,-"),))


def test_metric_values_refuse_ints_floats_and_decimal_shaped_text() -> None:
    for bad in (3, 0.5, ["x"], {"x": 1}, "12", "0.5"):  # "12" must be a Decimal, not text
        with pytest.raises(WireRefused):
            make(metrics=(("m", bad),))
    wire = make().to_wire()
    wire["metrics"] = {"m": 3}
    with pytest.raises(WireRefused):
        Verdict.from_wire(wire)
    with pytest.raises(WireRefused):
        parse_json_exact('{"schema":"verdict/v1","metrics":{"m":0.5}}')


def test_two_refit_run_inputs_are_admitted_and_exact_duplicates_refused() -> None:
    two = make(
        inputs=(
            VerdictInput("refit_run", SHA_A),
            VerdictInput("refit_run", SHA_B),
            VerdictInput("tape_snapshot", SHA_A),
        )
    )
    assert Verdict.from_wire(parse_json_exact(canonical_json(two.to_wire()))) == two
    with pytest.raises(WireRefused):
        make(inputs=(VerdictInput("refit_run", SHA_A), VerdictInput("refit_run", SHA_A)))
    with pytest.raises(WireRefused):
        make(inputs=(VerdictInput("refit_run", SHA_B), VerdictInput("refit_run", SHA_A)))


def test_valid_until_before_produced_at_is_refused() -> None:
    with pytest.raises(WireRefused):
        make(valid_until_ns=PRODUCED - 1)
    assert make(valid_until_ns=PRODUCED)


def test_a_policy_ruling_with_the_no_policy_ruling_assumption_is_refused() -> None:
    with pytest.raises(WireRefused):
        make(policy_ruling_sha256=SHA_D, assumptions=(Assumption.NO_POLICY_RULING,))
