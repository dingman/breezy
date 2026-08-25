> ## Documentation Index
> Fetch the complete documentation index at: https://docs.polymarket.us/llms.txt
> Use this file to discover all available pages before exploring further.

# Fee Schedule

> Trading fee schedule, rebates, and examples

<Info>Effective exchange-wide from 12 AM ET, Wednesday July 1, 2026.</Info>

## Trading Fees

Fees are computed using a symmetric formula that scales with price uncertainty:

```
Fee = Θ × C × p × (1 - p)
```

Where:

* **C** is the number of contracts
* **p** is the trade price (\$0.01 to \$0.99)
* **Θ** (theta) is the fee coefficient

|                  | Theta   | Max (p = \$0.50) |
| ---------------- | ------- | ---------------- |
| **Taker Fee**    | 0.06    | \$1.50           |
| **Maker Rebate** | -0.0125 | -\$0.31          |

* **Maker rebate** is applied at the point of trade.
* **Taker rebate**: Participants who trade over \$250,000 in taker volume during the prior calendar month receive rebates according to the following schedule. A Participant's tier for a given month is determined by their notional taker volume in the immediately preceding calendar month. Rebates are paid out weekly.

| Prior calendar-month taker volume | % Taker fee rebate |
| --------------------------------- | ------------------ |
| \$250,000 - \$999,999             | 10%                |
| \$1,000,000 - \$9,999,999         | 25%                |
| \$10,000,000+                     | 50%                |

**Accelerated Tier Placement**: A Participant may provide verifiable proof of their trailing-30-day notional trading volume on another prediction market and be assigned to the rebate tier corresponding to that volume.

<Note>
  API integrators: `C` is the number of **contracts** and `p` the **decimal** price. Execution reports carry these as fixed-point integers, and the collected fee in scaled notional units — see [Fees on execution reports](/partners/orders/data-model#fees-on-execution-reports) for how to decode `commission_notional_collected` with `price_scale` and `fractional_quantity_scale`.
</Note>

### Fee Schedule by Price

| Price  | Trade Value (100-lot) | Taker Pays (100-lot) | Maker Receives (100-lot) |
| ------ | --------------------- | -------------------- | ------------------------ |
| \$0.01 | \$1                   | \$0.06               | \$0.01                   |
| \$0.02 | \$2                   | \$0.12               | \$0.02                   |
| \$0.03 | \$3                   | \$0.17               | \$0.04                   |
| \$0.04 | \$4                   | \$0.23               | \$0.05                   |
| \$0.05 | \$5                   | \$0.28               | \$0.06                   |
| \$0.06 | \$6                   | \$0.34               | \$0.07                   |
| \$0.07 | \$7                   | \$0.39               | \$0.08                   |
| \$0.08 | \$8                   | \$0.44               | \$0.09                   |
| \$0.09 | \$9                   | \$0.49               | \$0.10                   |
| \$0.10 | \$10                  | \$0.54               | \$0.11                   |
| \$0.11 | \$11                  | \$0.59               | \$0.12                   |
| \$0.12 | \$12                  | \$0.63               | \$0.13                   |
| \$0.13 | \$13                  | \$0.68               | \$0.14                   |
| \$0.14 | \$14                  | \$0.72               | \$0.15                   |
| \$0.15 | \$15                  | \$0.76               | \$0.16                   |
| \$0.16 | \$16                  | \$0.81               | \$0.17                   |
| \$0.17 | \$17                  | \$0.85               | \$0.18                   |
| \$0.18 | \$18                  | \$0.89               | \$0.18                   |
| \$0.19 | \$19                  | \$0.92               | \$0.19                   |
| \$0.20 | \$20                  | \$0.96               | \$0.20                   |
| \$0.21 | \$21                  | \$1.00               | \$0.21                   |
| \$0.22 | \$22                  | \$1.03               | \$0.21                   |
| \$0.23 | \$23                  | \$1.06               | \$0.22                   |
| \$0.24 | \$24                  | \$1.09               | \$0.23                   |
| \$0.25 | \$25                  | \$1.12               | \$0.23                   |
| \$0.26 | \$26                  | \$1.15               | \$0.24                   |
| \$0.27 | \$27                  | \$1.18               | \$0.25                   |
| \$0.28 | \$28                  | \$1.21               | \$0.25                   |
| \$0.29 | \$29                  | \$1.24               | \$0.26                   |
| \$0.30 | \$30                  | \$1.26               | \$0.26                   |
| \$0.31 | \$31                  | \$1.28               | \$0.27                   |
| \$0.32 | \$32                  | \$1.31               | \$0.27                   |
| \$0.33 | \$33                  | \$1.33               | \$0.28                   |
| \$0.34 | \$34                  | \$1.35               | \$0.28                   |
| \$0.35 | \$35                  | \$1.36               | \$0.28                   |
| \$0.36 | \$36                  | \$1.38               | \$0.29                   |
| \$0.37 | \$37                  | \$1.40               | \$0.29                   |
| \$0.38 | \$38                  | \$1.41               | \$0.29                   |
| \$0.39 | \$39                  | \$1.43               | \$0.30                   |
| \$0.40 | \$40                  | \$1.44               | \$0.30                   |
| \$0.41 | \$41                  | \$1.45               | \$0.30                   |
| \$0.42 | \$42                  | \$1.46               | \$0.30                   |
| \$0.43 | \$43                  | \$1.47               | \$0.31                   |
| \$0.44 | \$44                  | \$1.48               | \$0.31                   |
| \$0.45 | \$45                  | \$1.48               | \$0.31                   |
| \$0.46 | \$46                  | \$1.49               | \$0.31                   |
| \$0.47 | \$47                  | \$1.49               | \$0.31                   |
| \$0.48 | \$48                  | \$1.50               | \$0.31                   |
| \$0.49 | \$49                  | \$1.50               | \$0.31                   |
| \$0.50 | \$50                  | \$1.50               | \$0.31                   |
| \$0.51 | \$51                  | \$1.50               | \$0.31                   |
| \$0.52 | \$52                  | \$1.50               | \$0.31                   |
| \$0.53 | \$53                  | \$1.49               | \$0.31                   |
| \$0.54 | \$54                  | \$1.49               | \$0.31                   |
| \$0.55 | \$55                  | \$1.48               | \$0.31                   |
| \$0.56 | \$56                  | \$1.48               | \$0.31                   |
| \$0.57 | \$57                  | \$1.47               | \$0.31                   |
| \$0.58 | \$58                  | \$1.46               | \$0.30                   |
| \$0.59 | \$59                  | \$1.45               | \$0.30                   |
| \$0.60 | \$60                  | \$1.44               | \$0.30                   |
| \$0.61 | \$61                  | \$1.43               | \$0.30                   |
| \$0.62 | \$62                  | \$1.41               | \$0.29                   |
| \$0.63 | \$63                  | \$1.40               | \$0.29                   |
| \$0.64 | \$64                  | \$1.38               | \$0.29                   |
| \$0.65 | \$65                  | \$1.36               | \$0.28                   |
| \$0.66 | \$66                  | \$1.35               | \$0.28                   |
| \$0.67 | \$67                  | \$1.33               | \$0.28                   |
| \$0.68 | \$68                  | \$1.31               | \$0.27                   |
| \$0.69 | \$69                  | \$1.28               | \$0.27                   |
| \$0.70 | \$70                  | \$1.26               | \$0.26                   |
| \$0.71 | \$71                  | \$1.24               | \$0.26                   |
| \$0.72 | \$72                  | \$1.21               | \$0.25                   |
| \$0.73 | \$73                  | \$1.18               | \$0.25                   |
| \$0.74 | \$74                  | \$1.15               | \$0.24                   |
| \$0.75 | \$75                  | \$1.12               | \$0.23                   |
| \$0.76 | \$76                  | \$1.09               | \$0.23                   |
| \$0.77 | \$77                  | \$1.06               | \$0.22                   |
| \$0.78 | \$78                  | \$1.03               | \$0.21                   |
| \$0.79 | \$79                  | \$1.00               | \$0.21                   |
| \$0.80 | \$80                  | \$0.96               | \$0.20                   |
| \$0.81 | \$81                  | \$0.92               | \$0.19                   |
| \$0.82 | \$82                  | \$0.89               | \$0.18                   |
| \$0.83 | \$83                  | \$0.85               | \$0.18                   |
| \$0.84 | \$84                  | \$0.81               | \$0.17                   |
| \$0.85 | \$85                  | \$0.76               | \$0.16                   |
| \$0.86 | \$86                  | \$0.72               | \$0.15                   |
| \$0.87 | \$87                  | \$0.68               | \$0.14                   |
| \$0.88 | \$88                  | \$0.63               | \$0.13                   |
| \$0.89 | \$89                  | \$0.59               | \$0.12                   |
| \$0.90 | \$90                  | \$0.54               | \$0.11                   |
| \$0.91 | \$91                  | \$0.49               | \$0.10                   |
| \$0.92 | \$92                  | \$0.44               | \$0.09                   |
| \$0.93 | \$93                  | \$0.39               | \$0.08                   |
| \$0.94 | \$94                  | \$0.34               | \$0.07                   |
| \$0.95 | \$95                  | \$0.28               | \$0.06                   |
| \$0.96 | \$96                  | \$0.23               | \$0.05                   |
| \$0.97 | \$97                  | \$0.17               | \$0.04                   |
| \$0.98 | \$98                  | \$0.12               | \$0.02                   |
| \$0.99 | \$99                  | \$0.06               | \$0.01                   |

### Fee Rules

* Fees are symmetric around p = 0.50 and lowest near the extremes (0 and 1).
* All fees and rebates are rounded to the nearest \$0.01 using banker's rounding (round half to even).
* When an aggressive order fills against multiple resting orders, each fill is charged its banker's-rounded fee, adjusted so that the total commission collected across the order's fills never exceeds the banker's rounding of the cumulative exact fee. The adjustment can only reduce a fill's charge, never increase it. Maker rebates are computed per fill, independently.

## Examples

#### Example 1: Buy 1,000 contracts at \$0.10 — cheap contract

Buying a long shot. The fee scales with price uncertainty: p × (1 − p) = 0.10 × 0.90 = 0.09.

* **Buyer (taker):** 0.06 × 1,000 × 0.10 × 0.90 = **−\$5.40**
* **Seller (maker):** 0.0125 × 1,000 × 0.10 × 0.90 = **+\$1.12**

***

#### Example 2: Buy 1,000 contracts at \$0.65 — expensive contract

Buying a likely outcome. Higher price but lower p × (1 − p) than midpoint.

* **Buyer (taker):** 0.06 × 1,000 × 0.65 × 0.35 = **−\$13.65**
* **Seller (maker):** 0.0125 × 1,000 × 0.65 × 0.35 = **+\$2.84**

***

#### Example 3: Sell 1,000 contracts at \$0.30 — sell low probability

The seller is the aggressor. Both sides pay based on the same p × (1 − p) factor.

* **Seller (taker):** 0.06 × 1,000 × 0.30 × 0.70 = **−\$12.60**
* **Buyer (maker):** 0.0125 × 1,000 × 0.30 × 0.70 = **+\$2.62**

***

#### Example 4: Sell 1,000 contracts at \$0.90 — sell high probability

When the price is close to \$1.00, p × (1 − p) is small and fees are minimal.

* **Seller (taker):** 0.06 × 1,000 × 0.90 × 0.10 = **−\$5.40**
* **Buyer (maker):** 0.0125 × 1,000 × 0.90 × 0.10 = **+\$1.12**

***

#### Example 5: Buy 1,000 contracts at \$0.50 — coin flip market

A 50/50 market. This is where the fee is highest per contract because p × (1 − p) = 0.25.

* **Buyer (taker):** 0.06 × 1,000 × 0.50 × 0.50 = **−\$15.00**
* **Seller (maker):** 0.0125 × 1,000 × 0.50 × 0.50 = **+\$3.12**

## FAQ

### Are fees deducted from my balance automatically?

Yes. Taker fees are deducted from your balance at the time of the trade. Maker rebates are credited to your balance at the time of the fill.

### Can fees ever be zero?

Yes. Fees are rounded to the nearest cent. On small trades (low quantity or prices near \$0.00 or \$1.00), the fee can round down to \$0.00.

### Do I pay fees when my order is canceled or expires?

No. Fees are only charged when a trade executes. If your order is canceled, expires, or is rejected, no fee is charged.

### What is banker's rounding?

Fees are rounded to the nearest cent using banker's rounding (round half to even). For example, \$0.025 rounds to \$0.02 (down to even), while \$0.035 rounds to \$0.04 (up to even).
