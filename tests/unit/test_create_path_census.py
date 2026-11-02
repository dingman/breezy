"""GAP-5a reverse-join census: synthetic inputs, no adapter imports or live reads."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.analysis.gap5_create_path_census import (
    JOIN_SLACK_S,
    MESSAGES,
    RESTING_CONFIRM_DEADLINE_S,
    classify_create,
    derive_backoff,
    evaluate_predicates,
    hygiene_scan,
    match_line,
    render,
    segment_creates,
    strip_ansi,
    verify_sources,
)

ROOT = Path(__file__).resolve().parents[2]
CREATE = "create-order classified kind=ambiguous status=200 body_kind=empty-executions"
EXITS = {
    "ALLOWLIST": "resting confirm: the venue order id failed the allowlist; holding",
    "TIMEOUT": "resting confirm: the GET timed out; holding",
    "REFUSED": "resting confirm: GET refused (HTTP status 404); retrying",
    "DIDNOTMAP": "resting confirm: GET did not map (ValueError); retrying",
    "ECHO": "resting confirm: not a clean matching NEW; holding",
    "NONNEW": "resting confirm: a non-NEW state (filled, partial or terminal); holding",
    "DEADLINE": "resting confirm: deadline reached without a NEW; holding",
    "BIND_RAISED": "resting bind raised; holding exc_type=ValueError client_order_id=synthetic",
}


def line(seconds: float, message: str, level: str = "WARN") -> str:
    stamp = f"2026-11-01T17:00:{int(seconds):02d}.{round(seconds % 1 * 1e9):09d}Z"
    return f"\x1b[1m{stamp}\x1b[0m \x1b[33m[{level}] sink: {message}\x1b[0m"


def anchor(seconds: float = 10, key: str = "synthetic") -> str:
    return line(seconds, f"{CREATE} client_order_id={key}", "ERROR")


def accepted(seconds: float = 11, key: str = "synthetic") -> str:
    return line(seconds, f"<--[EVT] OrderAccepted(client_order_id={key}, other=omitted)", "INFO")


def hold_row(signature: str = "SIG_H2_ECHO", **extra: Any) -> dict[str, Any]:
    return {"signature": signature, "bind_delay_s": "never bound", "waits": [], **extra}


def test_strip_ansi() -> None:
    assert strip_ansi("\x1b[1mhello\x1b[0m") == "hello"


def test_local_parser_accepts_ansi_and_error_without_leaking_text() -> None:
    parsed = match_line(line(9, EXITS["ALLOWLIST"], "ERROR"), 42)
    assert parsed is not None and parsed["kind"] == "ALLOWLIST" and parsed["line"] == 42
    assert "raw" not in parsed and "message" not in parsed


@pytest.mark.parametrize(
    ("kinds", "signature"),
    [
        (["REFUSED", "DEADLINE"], "SIG_H1_404_DEADLINE"),
        (["ECHO"], "SIG_H2_ECHO"),
        (["NONNEW"], "SIG_H3_NONNEW"),
        (["TIMEOUT"], "SIG_X_TIMEOUT"),
        (["ALLOWLIST"], "SIG_X_ALLOWLIST"),
        (["REFUSED", "BIND_RAISED"], "SIG_X_BIND_RAISED"),
        (["DIDNOTMAP", "DEADLINE"], "SIG_DIDNOTMAP"),
        (["REFUSED"], "SIG_NO_EXIT"),
        (["DEADLINE"], "UNKNOWN"),
    ],
)
def test_each_exit_signature(kinds: list[str], signature: str) -> None:
    lines = [
        line(8 + i / 10, EXITS[k], "ERROR" if k in {"ALLOWLIST", "BIND_RAISED"} else "WARN")
        for i, k in enumerate(kinds)
    ]
    row = segment_creates([*lines, anchor()])[0]
    assert row["signature"] == signature
    assert row["sequence"] == kinds
    assert row["exit_lines"] == list(range(1, len(kinds) + 1))


def test_new_requires_an_observed_matching_emitter() -> None:
    rows = segment_creates([anchor(), accepted()])
    assert rows[0]["signature"] == "SIG_NEW"
    assert rows[0]["new_label"] == "observed"


def test_bind_clear_is_also_an_info_new_emitter() -> None:
    row = segment_creates(
        [anchor(), line(11, "resting bind: cleared the AMBIGUOUS trading refusal", "INFO")]
    )[0]
    assert row["signature"] == "SIG_NEW"


def test_absent_new_is_no_exit_and_never_fabricated() -> None:
    assert segment_creates([anchor()])[0]["signature"] == "SIG_NO_EXIT"


def test_unkeyed_late_bind_is_not_guessed() -> None:
    row = segment_creates(
        [
            line(9, EXITS["TIMEOUT"]),
            anchor(),
            line(55, "resting bind: cleared the AMBIGUOUS trading refusal", "INFO"),
        ]
    )[0]
    assert row["bind_delay_s"] == "never bound"


def test_clear_without_orderaccepted_does_not_prove_churn_precondition() -> None:
    row = segment_creates(
        [
            anchor(),
            line(10.1, "REPLACED client_order_id=synthetic"),
            line(11, "resting bind: cleared the AMBIGUOUS trading refusal", "INFO"),
        ]
    )[0]
    assert row["replaced_before_accepted"] == 0


def test_confirm_then_anchor_is_reverse_joined() -> None:
    row = segment_creates([line(8, EXITS["ECHO"]), anchor()])[0]
    assert row["signature"] == "SIG_H2_ECHO"
    assert row["create_line"] == 2 and row["exit_lines"] == [1]


def test_404_then_timeout_last_terminal_wins() -> None:
    row = segment_creates([line(8, EXITS["REFUSED"]), line(9, EXITS["TIMEOUT"]), anchor()])[0]
    assert row["signature"] == "SIG_X_TIMEOUT"
    assert row["sequence"] == ["REFUSED", "TIMEOUT"]


def test_last_terminal_wins_even_with_later_retry() -> None:
    row = segment_creates(
        [line(7, EXITS["ECHO"]), line(8, EXITS["TIMEOUT"]), line(9, EXITS["REFUSED"]), anchor()]
    )[0]
    assert row["signature"] == "SIG_X_TIMEOUT"


def test_echo_is_never_new_even_if_accepted_later() -> None:
    row = segment_creates([line(9, EXITS["ECHO"]), anchor(), accepted()])[0]
    assert row["signature"] == "SIG_H2_ECHO" and row["bind_delay_s"] == 1


def test_debug_poll_is_ignored() -> None:
    row = segment_creates(
        [line(9, "resting confirm: order not yet ACCEPTED; polling", "DEBUG"), anchor()]
    )[0]
    assert row["sequence"] == [] and row["signature"] == "SIG_NO_EXIT"


@pytest.mark.parametrize(
    ("offset", "signature"), [(7, "SIG_H2_ECHO"), (7.000000001, "SIG_NO_EXIT")]
)
def test_reverse_window_inclusive_slack_boundary(offset: float, signature: str) -> None:
    assert RESTING_CONFIRM_DEADLINE_S == 5 and JOIN_SLACK_S == 2.0
    assert (
        segment_creates([line(10 - offset, EXITS["ECHO"]), anchor()])[0]["signature"] == signature
    )


@pytest.mark.parametrize(("distance", "overlap"), [(6, True), (7, True), (7.000000001, False)])
def test_overlapping_windows_are_unknown_including_boundary(distance: float, overlap: bool) -> None:
    rows = segment_creates(
        [anchor(), line(10.5, EXITS["TIMEOUT"]), anchor(10 + distance, "second")]
    )
    assert [r["signature"] for r in rows] == (
        ["UNKNOWN", "UNKNOWN"] if overlap else ["SIG_NO_EXIT", "SIG_X_TIMEOUT"]
    )
    assert all(r["join_label"] == ("unassignable" if overlap else "joined") for r in rows)


def test_bind_raised_requires_matching_private_key() -> None:
    row = segment_creates(
        [line(8, EXITS["REFUSED"]), line(9, EXITS["BIND_RAISED"], "ERROR"), anchor(key="other")]
    )[0]
    assert row["signature"] == "SIG_NO_EXIT"


def test_non404_refused_deadline_is_unknown() -> None:
    row = segment_creates(
        [line(8, EXITS["REFUSED"].replace("404", "503")), line(9, EXITS["DEADLINE"]), anchor()]
    )[0]
    assert row["signature"] == "UNKNOWN"


def test_pure_classifier() -> None:
    assert classify_create(["REFUSED", "TIMEOUT"], refused_404=True) == "SIG_X_TIMEOUT"


@pytest.mark.parametrize(
    ("failures", "expected"), [(0, 5), (1, 5), (2, 10), (3, 20), (7, 300), (10000, 300)]
)
def test_backoff_formula(failures: int, expected: float) -> None:
    assert derive_backoff(failures) == expected


def test_backoff_unknown_after_success_or_without_marker() -> None:
    assert derive_backoff(4, success_window=True) == "UNKNOWN"
    assert derive_backoff(None) == "UNKNOWN"


def test_wait_inherits_hold_backoff_and_duplicates_are_not_double_counted() -> None:
    rows = segment_creates(
        [
            line(6, "resolver (backoff: 4 consecutive failure(s))"),
            line(9, EXITS["TIMEOUT"]),
            anchor(),
            line(
                12,
                "Refusing: submit intent is already OPEN for this account; wait for it to resolve",
                "ERROR",
            ),
            line(
                12.1,
                "OrderDenied(client_order_id=wait, reason='submit intent is already OPEN "
                "for this account; wait for it to resolve')",
            ),
        ]
    )
    assert rows[0]["backoff_in_force"] == 40
    assert rows[0]["waits"] == [{"line": 5, "backoff_in_force": 40, "delay_s": 2.1}]


def test_success_invalidates_backoff_marker_and_hold_delay_is_separate() -> None:
    rows = segment_creates(
        [
            line(1, "resolver (backoff: 4 consecutive failure(s))"),
            anchor(2, "first"),
            accepted(3, "first"),
            line(19, EXITS["ECHO"]),
            anchor(20),
            accepted(55),
        ]
    )
    assert rows[1]["backoff_in_force"] == "UNKNOWN"
    assert rows[1]["bind_delay_s"] == 35 and rows[1]["hold_bind_delay_s"] == 36


@pytest.mark.parametrize(("count", "confirmed"), [(500, True), (499, False)])
def test_half_threshold_is_inclusive(count: int, confirmed: bool) -> None:
    rows = [hold_row() for _ in range(count)] + [
        hold_row("SIG_X_TIMEOUT") for _ in range(1000 - count)
    ]
    assert ("H2" in evaluate_predicates(rows)["confirmed"]) is confirmed


def test_h2_stop_report_and_no_conditional_go_key() -> None:
    verdict = evaluate_predicates([hold_row()])
    assert "L-37 names-only logging gap" in verdict["stop_report_reasons"]
    assert "5b_conditional_GO" not in json.dumps(verdict)


def test_x_dominance_is_aggregated() -> None:
    verdict = evaluate_predicates(
        [
            hold_row("SIG_X_TIMEOUT"),
            hold_row("SIG_X_ALLOWLIST"),
            hold_row(),
            hold_row("SIG_H3_NONNEW"),
        ]
    )
    assert verdict["x_dominant"] is True
    assert any("STOP-REPORT" in r for r in verdict["stop_report_reasons"])


def test_h5_unknown_at_half_is_undecidable() -> None:
    rows = [
        hold_row(bind_delay_s=40, hold_bind_delay_s=41, backoff_in_force=b) for b in ["UNKNOWN", 40]
    ]
    verdict = evaluate_predicates(rows)
    assert verdict["h5"] == "UNDECIDABLE" and "GO" not in json.dumps(verdict)


@pytest.mark.parametrize(("backoff", "state"), [(40, "H5a"), (30, "H5b")])
def test_h5_split(backoff: float, state: str) -> None:
    verdict = evaluate_predicates(
        [hold_row(bind_delay_s=31, hold_bind_delay_s=32, backoff_in_force=backoff)]
    )
    assert verdict["h5"] == state


def test_h4_requires_churn_before_acceptance() -> None:
    row = hold_row(bind_delay_s=4, replaced_before_accepted=0, waits=[{"delay_s": 2}])
    assert "H4" not in evaluate_predicates([row])["confirmed"]
    row["replaced_before_accepted"] = 1
    assert "H4" in evaluate_predicates([row])["confirmed"]


def test_step2_only_when_h3_confirmed() -> None:
    assert evaluate_predicates([hold_row("SIG_H3_NONNEW")])["step2_schema_check"] is True
    assert evaluate_predicates([hold_row()])["step2_schema_check"] is False


def test_empty_denominator_is_unexplained_without_division() -> None:
    verdict = evaluate_predicates([])
    assert verdict["UNEXPLAINED"] is True and verdict["h5"] == "UNDECIDABLE"


def test_drift_guard_reads_client_as_text() -> None:
    citations = verify_sources(ROOT)
    assert len(MESSAGES) == 8 and all(citations["client.py"][k] for k in MESSAGES)
    assert citations["submit_chain.py"]["deadline"] == [164]


def test_drift_guard_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="source drift"):
        verify_sources(tmp_path)


@pytest.mark.parametrize(
    "secret",
    [
        "client_order_id=abc",
        "DF3DN0WG12WQ",
        "Bearer abc",
        "account_number=12345678",
        "-----BEGIN PRIVATE KEY-----",
        "0x" + "ab" * 32,
    ],
)
def test_hygiene_rejects_planted_sensitive_text(secret: str) -> None:
    with pytest.raises(ValueError, match="hygiene"):
        hygiene_scan(secret)


def test_render_whitelists_rows_and_has_zero_sink_proof() -> None:
    row = segment_creates([anchor(), accepted()])[0]
    payload = {
        "git_sha": "a" * 40,
        "citations": verify_sources(ROOT),
        "logs": [],
        "rows": [row],
        "verdict": evaluate_predicates([row]),
    }
    machine, markdown = render(payload)
    hygiene_scan(machine + markdown)
    assert "synthetic" not in machine + markdown
    assert "verdict" not in markdown and "CONFIRMED" not in markdown
    assert "ZERO" in markdown and "WARN" in markdown and "sink" in markdown
    assert "5b_conditional_GO" not in machine + markdown


def test_writer_has_no_adapter_imports_and_respects_size_limits() -> None:
    source = (ROOT / "scripts/analysis/gap5_create_path_census.py").read_text()
    tree = ast.parse(source)
    imports = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(name and name.startswith("breezy.adapters") for name in imports)
    assert len(source.splitlines()) <= 400
    assert all(
        (node.end_lineno or node.lineno) - node.lineno + 1 <= 50
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
