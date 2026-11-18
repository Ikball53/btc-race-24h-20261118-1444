"""Bounce-confirmed dip buyer for cbBTC (CBBTC/USDC), 1-minute bars.

Idea: BTC in a downtrend keeps making lower lows, so buying every dip
bleeds. This bot only buys after a dip AND a confirmed turn back up:
price fell a set amount from its recent high, then the close pushed back
above its short moving average with two up closes in a row. It then
takes a quick profit, cuts the loss if the bounce fails, and otherwise
exits on a clock so no position is held through a long grind down.
If no confirmed bounce appears, it sits in cash. Full size per trade,
at most 8 round trips, one open position at a time.

Protocol: agent-fun/bars-replay/v1 via the vendored kit shim.
Deterministic: no clock, no network, no randomness, stdlib only.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# --- tunable strategy parameters (variant V12: V11 + TP 80 -> 130) ---
# Round-2 sweep (18 Nov): raising TP lets the trailing exit do the work.
# With TP 80 the TP check fires first, so the trail (trigger +0.80%,
# giveback 0.30%) could never capture a runner. With TP 130 the trail
# banks bounces that run +0.8-1.3% and TP 130 caps the top. Measured dev:
# TP 110/120 +$10.89, TP 130 +$13.56, TP 140/150 +$13.27 (plateau);
# TP 160+ collapses (-$2.30, one runner fell back past the time exit).
# Hold 45/60/75/90 all positive (+$4.76/13.56/9.52/8.38); giveback
# 20/30/40/50 all +$12.80-13.99; SHARP 80/100/120 all +$12.01-13.56.
# Small TP is worse (TP 50 -$5.08/+$1.23, TP 60 -$1.34/+$5.00);
# momentum entry stays: dip-only scores only +$3.42-7.12 (1 round trip).
# MOM trigger stays knife-edge on this window (45 +$3.36, 55 -$2.88),
# same fragility as V11; entries unchanged, so no new risk is added.
# Dev window (17-18 Nov): -2.80% overall, range 3.35%; 60m returns sd 0.45%,
# median |60m| 0.24%; dips vs 60-bar high median 0.30%, p90 0.59%, p95 1.23%;
# trough rebounds median +0.64% in 30m, +0.71% in 60m (only 6 true troughs).
# Live last 24h (Coinbase hourly): -2.26%, range 3.46%, avg |hour| 0.30%,
# biggest up hour +0.61%; dips >=0.5% only 4x (-0.59/-0.98/-0.80/-1.05%),
# only 2 of 4 bounced, and only +0.39%/+0.57%. Bounces that DO run on the
# dev window run further than +0.8% (see trade log), which is why TP 130
# + trail beats TP 80 despite the live-hourly caution above.
WARMUP = 45            # bars of history before the first trade is allowed
LOOKBACK = 60          # bars over which the recent high is measured
DIP_BPS = 70           # dip entry: close >= 0.70% below the 60-bar high
SHARP_DROP_BPS = 100   # sharp entry: 60-bar return <= -1.00% (a real plunge)
MOMENTUM_BPS = 50      # momentum entry: 30-bar return >= +0.50% (BTC rallies
                       # straight up with no dip first: we still buy)
MA_LEN = 5             # short moving average used for bounce confirmation
TAKE_PROFIT_BPS = 130  # sell at +1.30% vs the decision-bar close at entry
                       # (V12: raised from 80 so the trailing exit can bank
                       # runners between +0.80% and +1.30% instead of the
                       # TP check cutting them at +0.80%)
STOP_LOSS_BPS = 120    # sell at -1.20%: dev adverse excursions rarely pass -0.85%
TRAIL_TRIGGER_BPS = 80  # only on a big runner: trail once up +0.80%
TRAIL_GIVEBACK_BPS = 30  # then sell if price falls 0.30% from the peak
MAX_HOLD_BARS = 60     # time-based exit if neither TP nor SL fires
COOLDOWN_BARS = 30     # bars to wait after a sell before the next buy
MAX_ROUND_TRIPS = 8    # hard cap on round trips for the whole window
NO_BUY_AFTER = 1300    # never open a new position this late in the window


class Bot:
    def __init__(self):
        self.closes = []          # close prices (ints, price-scale units)
        self.entry_close = None   # close at the bar the buy was decided on
        self.entry_bar = None     # seq of the entry decision bar
        self.peak_close = None    # highest close seen while in a position
        self.last_sell_bar = -10 ** 9
        self.round_trips = 0

    def _ma(self, n):
        if len(self.closes) < n:
            return None
        return sum(self.closes[-n:]) // n

    def on_batch(self, state, batch):
        if state.warming_up:
            return []
        close = state.close(SYMBOL)
        if close is None:
            return []
        self.closes.append(close)
        holding = SYMBOL in state.positions and state.positions[SYMBOL].qty > 0

        # Track a filled buy: once the position appears, anchor the entry
        # on the close of the bar before the fill (the decision close is
        # one bar behind the fill, so use the previous close as anchor).
        if holding and self.entry_close is None:
            anchor = self.closes[-2] if len(self.closes) >= 2 else close
            self.entry_close = anchor
            self.entry_bar = state.seq
            self.peak_close = close

        if holding:
            if close > self.peak_close:
                self.peak_close = close
            held_bars = state.seq - self.entry_bar if self.entry_bar is not None else 0
            entry = self.entry_close
            # Take profit: close >= entry * (1 + TP).
            if close * 10000 >= entry * (10000 + TAKE_PROFIT_BPS):
                return self._sell_all(state)
            # Stop loss: close <= entry * (1 - SL).
            if close * 10000 <= entry * (10000 - STOP_LOSS_BPS):
                return self._sell_all(state)
            # Trailing exit: gave back enough from the peak after a real run.
            if self.peak_close * 10000 >= entry * (10000 + TRAIL_TRIGGER_BPS):
                if close * 10000 <= self.peak_close * (10000 - TRAIL_GIVEBACK_BPS):
                    return self._sell_all(state)
            # Time exit: the bounce stalled, free the cash.
            if held_bars >= MAX_HOLD_BARS:
                return self._sell_all(state)
            return []

        # Flat: do not re-enter straight after a sell, and respect the cap.
        if state.seq - self.last_sell_bar < COOLDOWN_BARS:
            return []
        if self.round_trips >= MAX_ROUND_TRIPS:
            return []
        if len(self.closes) < WARMUP:
            return []

        # No new position too late in the window: there must be time left
        # for the bounce to play out before the final flatten.
        if state.seq >= NO_BUY_AFTER:
            return []
        # Bounce confirmation (mandatory: only ~50% of dips bounce at all,
        # and the freshest live dips have not bounced): the close must be
        # above its 5-bar average and rising.
        ma = self._ma(MA_LEN)
        if ma is None or close <= ma:
            return []
        if len(self.closes) < 3:
            return []
        if not (self.closes[-1] > self.closes[-2]):
            return []
        # Not still in freefall: the last 5 bars must not be collapsing.
        if len(self.closes) >= 6:
            if self.closes[-1] * 10000 < self.closes[-6] * (10000 - 100):
                return []
        recent_high = max(self.closes[-LOOKBACK:])
        dip_ok = close * 10000 <= recent_high * (10000 - DIP_BPS)
        # Entry A: a sharp 60-bar plunge that has just turned up, AND the
        # price is still near the plunge's trough (within 0.35% of the
        # 60-bar low). Without the recency check the 60m window stays
        # <= -1% for ~40 bars after the trough and re-buys mid-chop.
        sharp_ok = False
        if len(self.closes) > 60:
            sixty_ago = self.closes[-61]
            sixty_low = min(self.closes[-61:])
            sharp_ok = (close * 10000 <= sixty_ago * (10000 - SHARP_DROP_BPS)
                        and close * 10000 <= sixty_low * (10000 + 35))
        # Entry B (disabled since V6): a dip off the recent high with TWO up
        # closes in a row. Measured EV was ~zero/negative on the dev
        # window: dip entries kept buying mid-chop and timing out lower.
        dip_confirmed = dip_ok and self.closes[-2] > self.closes[-3]
        # Entry C (momentum): BTC rallies with no dip first. Buy when the
        # 30-bar return is >= +0.50% with the close above its MA and rising
        # (checked above). NO new-high requirement and NO extra delay:
        # V8/V10 showed any delay (new-high rule, 10-bar confirmation)
        # pushes the entry to the top of the move and loses money; the
        # plain early trigger is what works. Same TP/SL/protection.
        mom_ok = False
        if len(self.closes) > 30:
            thirty_ago = self.closes[-31]
            mom_ok = close * 10000 >= thirty_ago * (10000 + MOMENTUM_BPS)
        if not (sharp_ok or mom_ok):
            return []
        # Buy with all cash. max_slippage 200 bps covers the modelled
        # 2 bps slippage + impact on a full-size order with room to spare.
        cash = state.cash
        if cash <= 1_000_000:
            return []
        return [{"side": "buy", "symbol": SYMBOL,
                 "notional_quote_units": cash, "max_slippage_bps": 200}]

    def _sell_all(self, state):
        holding = state.positions.get(SYMBOL)
        if holding is None or holding.qty <= 0:
            return []
        self.entry_close = None
        self.entry_bar = None
        self.peak_close = None
        self.last_sell_bar = state.seq
        self.round_trips += 1
        return [{"side": "sell", "symbol": SYMBOL,
                 "qty": holding.qty, "max_slippage_bps": 200}]


def main():
    bot = Bot()
    makefun_bars.run(bot.on_batch)


if __name__ == "__main__":
    main()
