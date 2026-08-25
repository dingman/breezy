> ## Documentation Index
> Fetch the complete documentation index at: https://docs.polymarket.us/llms.txt
> Use this file to discover all available pages before exploring further.

# Price Impact

> Learn how order size moves prices and affects your execution

Price impact is the change in execution price caused by the size of your order. If your order is larger than the size posted at the best price, it fills at higher prices, raising your average fill price.

## Depth Structure

The order book lists posted size at each price. If the best price cannot fill your entire order, the remaining size fills at the next available price levels. The distribution of size across those price levels determines where your order fills.

**Example:** Best ask is 15¢ with 9,150 shares posted. A 50,000-share buy clears 15¢, sweeps 16¢, and finishes partway through 17¢.

Price impact increases when available liquidity is thin at the best price.

## Order Size and Fill Behavior

Small orders typically fill at a single price level. Larger orders fill at higher prices because each level has limited posted size. What counts as small or large depends entirely on current depth.

**Example:** 9,150 shares fill at 15¢. Any remaining size fills at 16¢ and then higher prices if needed.

## Thin Depth Conditions

Posted size often drops during quiet periods, before major announcements, and near deadlines when traders cancel resting orders. When depth is low at the best price, even relatively small trades can fill at higher prices.

**Example:** At 99¢ only 2,249 shares are posted. Any buy large enough to clear that size fills at the next available price levels.

## Estimating Impact

Check posted size across the first few price levels and compare it with the size you plan to trade. If your order is larger than the combined size across those levels, it fills at higher prices and increases your average fill price.

**Example:** At 15¢, 16¢, and 17¢ there are about 92,000 shares in total. Any order larger than that fills at 18¢ and above.

## Reducing Execution Cost

Break large orders into smaller clips so each one interacts with fewer price levels and gives new liquidity time to post between trades.

**Example:** If depth is thin around 15–17¢ and you plan to buy \$2,000, splitting the order into several smaller clips can prevent it from filling at 18¢.
