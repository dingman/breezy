# Codex adversarial review — live fill → scored-trial chain (2026-09-05)

**Provenance.** Two independent read-only passes by Codex (codex MCP, `sandbox=read-only`,
cwd = repo, no tests, no network): pass 1 over `389928f^..54ae8bd` (I1a, I1b, cage pin,
counter, coverage table, deploy) and pass 2 over the same plus `d3e44b5 3a0f62a cac328a
5cd169a 7eef3f2`. Claude reviewers ran in parallel (security, python, domain — all APPROVE
or REVISE-then-fixed; their findings are in the commit messages). Coordinator dispositions
below; every line-cited claim was verified by the fixing agent's RED test before its commit.

## Pass 1 (verdict BLOCK) — dispositions

| Sev | Finding (Codex) | Disposition |
|---|---|---|
| CRITICAL | Wrapper invokes `score_live_trials.py --family-manifest` without `--fills`; committed scorer still required `--fills` | EXPECTED transient: I2 was in flight; timer NOT enabled until I2 landed. Closed by `5cd169a` (pass 2: CLOSED). |
| HIGH | `_durable_execution` picks the first row with `lastPx/lastShares/tradeId` regardless of `type`; a stale CANCELED row before the FILL row → AMBIGUOUS, no record, no `OrderFilled` | FIXED `d3e44b5` (fill-type rows only; RED reproduced `'ambiguous' == 'accept_fill'`). |
| HIGH | Per-pid `/proc/<pid>/cmdline` `OSError` escapes the pre-flight | FIXED `3a0f62a` (→ `DISCOVERY_FAILED`, value-free). |
| HIGH | A successful morning run's marker survives a later same-day failure | FIXED `3a0f62a` (`rm -f` of the marker first; sole writer unchanged). |
| MEDIUM | `sed` extraction accepts any file with matching lines | FIXED `3a0f62a` (braces + exactly-one `count`/`fetch_start` line, ≥1 station line) and ``1964567`` (counter JSON removed before the counter runs — always this run's). Residual: shape, not parse; trust boundary = our own script, same run, same uid. |
| MEDIUM | Coverage lines with blank identity keys pass | FIXED `cac328a` (blank `venue_order_id` refuses; blank trial identity only for `no_taken_latch`). |

## Pass 2 (verdict BLOCK; prior six CLOSED) — dispositions

| Sev | Finding (Codex) | Disposition |
|---|---|---|
| CRITICAL | A fill record whose bytes fail `from_bytes` is skipped → lost, exit 0 | FIXED ``2f5c50b``: store corruption REFUSES the run (`FillSourceUnreadableError`, non-zero, no marker), never a skip, never an exclusion. |
| HIGH | A corrupt latch is skipped → a valid fill downgraded to `no_taken_latch` | FIXED ``2f5c50b`` (same refusal). |
| MEDIUM | Wrappers trust grep/sed shape, not a manifest-hash/census binding | PARTIAL: ``1964567`` guarantees the JSON is this run's counter output; a sha binding is not reproducible in shell without `$PY -c` (stub-idiom collision, plan round 4). RESIDUAL, stated in plan §5. |
| MEDIUM | The scorer logs the env-derived state-DB path | BY DESIGN (plan §5 NOTE-3): a repo-pinned non-secret path, logged once; the `/proc` comparison prints only the enum. Not a secret, not an enablement value. |

**Also found during I5 (contract test), not by Codex:** a `commissionNotionalCollected`
with more decimals than the instrument's price precision is refused by the pre-existing
`parse_fill_report` and classifies the fill AMBIGUOUS (evidence kept at the venue, not in
the store). The fee model tests use cent-rounded values; the first real fill's commission
format must be checked against this (blocker register).

**Closed by Claude reviewers in the same batch:** cross-city fill scan writing false
`no_taken_latch` lines for other cities (security, HIGH → ``2f5c50b``); `DivisionByZero`
on a zero-qty record and a non-exhaustive pre-flight enum (python, HIGH/LOW → `7eef3f2`).
