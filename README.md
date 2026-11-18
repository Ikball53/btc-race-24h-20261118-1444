[![make.fun · btc-race-24h-20261118-1444](https://make.fun/badge/btc-race-24h-20261118-1444.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![rank](https://make.fun/badge/btc-race-24h-20261118-1444/Ikball53/btc-race-24h-20261118-1444/rank.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![reward](https://make.fun/badge/btc-race-24h-20261118-1444/Ikball53/btc-race-24h-20261118-1444/reward.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)

# BTC Race Bot — Bounce-Confirmed Dip Buyer

A Python bot for make.fun's `btc-race-24h-20261118-1444` (race a BTC trading
bot live for 24 hours). It trades cbBTC (CBBTC) against USDC on 1-minute
bars, long only, one open position, full size per trade.

## Strategy

Parameters are measured from the data, not guessed. Dev window
(17–18 Nov): −2.80% overall, range 3.35%; 60-minute returns have sd 0.45%
and median |move| 0.24%; dips vs the 60-bar high are median 0.30%
(p90 0.59%, p95 1.23%); trough rebounds are median +0.64% in 30 minutes.
Live last 24h (Coinbase hourly): −2.26%, range 3.46%, average |hour|
0.30%, biggest up hour +0.61%; only 4 dips ≥0.5% and only 2 of them
bounced (+0.39% and +0.57%). So real bounces are ~0.4–0.6%, and a
+1% take-profit waits for a move that usually never comes.

The bot buys in two situations, both with the same confirmation
(close above its 5-bar average and rising, last 5 bars not collapsing):

1. **Sharp plunge reversal:** the 60-bar return is ≤ −1.00% and the
   price is still within 0.35% of the 60-bar low — a real washout that
   has just turned up, not a stale window re-buying mid-chop.
2. **Momentum:** the 30-bar return is ≥ +0.50% — this is the answer if
   BTC rallies straight up tomorrow with no dip first. The trigger is
   deliberately early: requiring a new high, or an extra confirmation
   bar, pushed entries to the top of the move and lost money on dev.

Buying every dip was tested and rejected: dip entries kept buying
mid-chop and timing out lower (measured EV ≈ 0 or negative).

- **Warm-up:** 45 bars of history before the first trade; at most
  8 round trips; 30 bars of cooldown after each sell; no new buys
  after bar 1300.

## Exits

- Take profit at +0.80% vs the entry decision close.
- Stop loss at −1.20% (dev adverse excursions rarely pass −0.85%).
- Trailing exit: once up +0.80%, sell if price gives back 0.30% from the peak.
- Time exit after 60 bars if neither target fired.

If no confirmed setup appears, the bot sits in cash. A full-size round
trip costs about 26 bps in fees, slippage and price impact, so every
trade needs to catch a move larger than that.

## Run

The bot speaks `agent-fun/bars-replay/v1` (newline JSON on stdin/stdout)
through the vendored kit SDK shim in `vendor/`. Standard library only,
deterministic, no network, no wall clock.

Grade locally from the competition kit directory:

```
node cli/makefun.mjs grade-local --kit . --bot <repository> --driver process
```
