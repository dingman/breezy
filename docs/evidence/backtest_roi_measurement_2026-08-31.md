# BL-17 resolved — the $100 report is a stale artifact, not a code bug

Date: 2026-08-31. Method: probe against the installed Nautilus 1.231.0 in
`.venv`, plus report-corpus comparison. Nautilus ran every engine; this
document only reads what it reported.

## Verdict

`STARTING_BALANCE_USD = 10_000` is correct and has been since the script was
first tracked (`201c67b`, 2026-08-31 00:31). The current source path **cannot**
emit a $100 base. BL-17's suspected cause (≈30 engines sharing
`trader_id`/`instance_id`) is disproved.

## Probe (venv `.venv`, `PYTHONPATH=src`)

    Money(10_000, USD)                        as_double = 10000.0
    from_raw(10000 * 10^(16-2), USD)          as_double =   100.0   # NOT used by Breezy
    AFTER run() with NO data                              = 10000.0
    HARNESS after engine.run                              = 10000.0
    AFTER run_backtest, real BinaryOption                 = 10000.0

`Money.__init__` (`objects.pyx:1189-1205`) takes `float(value)` then Rust
`money_new`; USD precision 2; `FIXED_PRECISION=16` is DOLLARS, not cents. The
only construction turning `10000` into `$100.00` is `Money.from_raw(...)`,
which Breezy never calls. `add_venue` stores the `Money` unchanged
(`engine.pyx:2880`); the account is minted from `starting_balances` on each
`run()` (`engine.pyx:3893-3908`); `balance_total` returns `AccountBalance.total`
(`accounts/base.pyx:226-260`). BinaryOption multiplier is 1; CASH init applies
no 1/100 scaling.

Hypotheses tested and **disproved**: Money/USD cents-vs-dollars; `AccountType.CASH`
+ `base_currency=USD` init; `balance_total` returning equity or notional;
disk-cache state keyed by `DEFAULT_BACKTEST_TRADER_ID` (`CacheConfig.database`
is `None`; only a Redis backing exists); in-process trader_id leakage (unique
and default ids both return 10000.0).

## Why the 17:49 report says 100.0

| Reports | Idle balance | Traded examples |
|---|---|---|
| 12 files, `...T223108` … `...T153807` | 10000.0 | 9994.59 / 10005.17 / 10015.51 |
| `...T174940` ONLY | 100.0 | 94.59 / 105.17 / 115.51 |

Dollar PnL is identical across both (`10000 - 5.41` vs `100 - 5.41`), and fill
notionals match. The T174940 run came from a script inode that no longer
exists: the worktree script is byte-identical to HEAD, its `stat` **Birth** is
2026-08-31T17:49:47.907Z, and the report's `generated_at_utc` is
2026-08-31T17:49:40.480925Z — **seven seconds earlier**.

UNKNOWN, and not worth chasing: the exact bytes of that previous inode.

## The ROI correction this forces

On the correct $10,000 base, the only real-provenance scenario
(`primary_real_preliminary`, MIA 91F / NYC 79F, both REAL) is
**-$5.41 = -0.054%**, NOT -5.41%. The sign is unchanged; the magnitude was
overstated 100x anywhere the $100 base was assumed.

Sizing in that run used the strategy's `starting_equity` ($10k), not the $100
cash figure, so fills and `realized_pnl` from T174940 remain usable; only ROI
computed against its cash base is wrong.

## Residual actions

1. Re-run HEAD to replace T174940.
2. Emit `starting_balance_usd` on every report row, and raise if an idle run's
   ending balance differs from it — so a stale base can never again be read as
   a real ROI. Adds a field and an assertion; changes no existing test.
