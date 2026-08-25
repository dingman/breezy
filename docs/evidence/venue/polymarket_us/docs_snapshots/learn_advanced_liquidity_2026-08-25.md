> ## Documentation Index
> Fetch the complete documentation index at: https://docs.polymarket.us/llms.txt
> Use this file to discover all available pages before exploring further.

# Liquidity

> Learn how posted size across price levels affects where your order fills

Liquidity is the size available at each price level on the order book. Where your order fills depends on how much liquidity is available at or near the best price.

## Depth and Posted Size

Liquidity comes from resting orders that other users have placed and are waiting to be matched.

Each price level shows how many shares are available to buy or sell. The more liquidity near the current price, the easier it is to trade without moving the price. When liquidity is low or disappears, even smaller trades can move through multiple price levels.

### Example

At 30¢ there are **120 shares** available, at 31¢ there are **300 shares**, and at 32¢ there are **600 shares**. Those amounts show how much can trade at each price before orders begin filling at the next level.

| Price           | Shares |
| --------------- | ------ |
| 30¢             | 120    |
| 31¢             | 300    |
| 32¢             | 600    |
| Total up to 32¢ | 1,020  |

## Order Interaction With Liquidity

Orders fill against available liquidity starting at the best available price. If there isn't enough available at that price to fill your full order, the remaining shares fill at the next price levels.

### Example

You place a buy for **500 shares**.

* 120 shares fill at 30¢
* 300 shares fill at 31¢
* 80 shares fill at 32¢

| Price | Shares available | Total up to |
| ----- | ---------------- | ----------- |
| 30¢   | 120              | 120         |
| 31¢   | 300              | 420         |
| 32¢   | 600              | 1,020       |

As a result, your average fill price ends up higher than **30¢** because there wasn't enough liquidity available at the best price.

## Thin Liquidity Conditions

Liquidity can become thin—or even disappear entirely—when traders pull their orders. This is especially common in **live sports**, including:

* Late in the 4th quarter or final minutes
* Overtime
* Right after a major play (turnover, touchdown, penalty, injury)
* Right before the match ends, when the outcome looks nearly certain

In these moments, orders can be added or removed quickly, and prices can move sharply.

**Why this matters**: Thin liquidity can cause **slippage**, which means your order fills at worse prices than expected. In fast-moving markets, this can quickly lead to paying more or receiving less than expected.

### Example

At 75¢, there are only **40 shares** available. If you place a buy for 120 shares, part of your order will fill at 76¢ or higher.

| Price           | Shares |
| --------------- | ------ |
| 75¢             | 40     |
| 76¢             | 60     |
| 77¢             | 80     |
| Total up to 77¢ | 180    |

## Reducing Liquidity Risk

Polymarket US is a **peer-to-peer market**. Prices and available liquidity change as other traders place or cancel orders.

Orders execute against available liquidity at the best available price. You cannot set a custom limit price, so the price you receive depends on what is available at the moment your order is submitted. Any unfilled portion of your order rests on the book at your executed price until it fills or is canceled. Treat the displayed price as dynamic, especially in live sports.

### Practical ways to protect yourself

* **Pay close attention to the price right before you submit**. In fast-moving markets, prices can change in seconds.
* **Consider placing smaller orders instead of one large order** to reduce the chance your order sweeps through multiple price levels.
* **Be extra cautious near the end of games or matches**, where liquidity often thins out or disappears.
* **If the price is moving quickly, consider pausing briefly** and re-checking the current price before submitting.

### Example

You want to buy **\$100** worth of shares at 50¢ (**200 shares**).

| Price           | Shares |
| --------------- | ------ |
| 50¢             | 50     |
| 51¢             | 80     |
| 52¢             | 70     |
| Total up to 52¢ | 200    |

If liquidity is thin, submitting a buy for **200 shares** at once may result in part of your order filling at **51¢**, **52¢**, **or higher**, instead of 50¢.

Instead, try submitting **4 smaller trades of \$25** (**50 shares each**). This can reduce price impact during periods of thin liquidity.

## Evaluating Available Liquidity

Before placing a larger order—especially in live sports—compare the size you want to trade to what's available near your expected price, as larger orders may fill at worse levels.

### Example

You want to buy around **75¢**. Available shares near that price:

| Price           | Shares |
| --------------- | ------ |
| 75¢             | 10     |
| 76¢             | 40     |
| 77¢             | 60     |
| Total up to 77¢ | 110    |

A buy for **150 shares** would result in at least **40 shares** filling at **78¢ or higher**, raising your average purchase price.

### Simple rule of thumb

If your order size is close to or larger than the liquidity available near your expected price—especially late in a game—consider placing **smaller orders** and pay close attention to the price right before you submit to reduce slippage.
