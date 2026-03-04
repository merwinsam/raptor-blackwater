"""
Raptor — Spread Strategies
Bear Call Spread  : SELL CE (closer) + BUY CE (further OTM)
Bull Put Spread   : SELL PE (closer) + BUY PE (further OTM)

Margin calculation (NSE SPAN approximation):
  Spread margin = wing_width × lot_size × lots
  Premium received offsets initial outflow.
  Net margin = (wing_width - net_credit) × lot_size × lots

For live margin use Kite margin API; this is a conservative estimate.
"""

import numpy as np
from datetime import date, timedelta
import config


def _kite_symbol(strike: int, option_type: str, expiry_date) -> str:
    yy = expiry_date.strftime("%y")
    m  = str(expiry_date.month)
    dd = str(expiry_date.day)
    return f"NIFTY{yy}{m}{dd}{strike}{option_type}"


def _get_next_tuesday() -> date:
    today = date.today()
    days  = (1 - today.weekday()) % 7
    this_tue = today + timedelta(days=days)
    return this_tue + timedelta(weeks=1)


def _expiry_dict(d: date) -> dict:
    return {
        "expiry_date":     d.strftime("%d %b %Y"),
        "expiry_date_raw": d,
        "dte":             (d - date.today()).days,
        "week":            "NEXT",
    }


class BearCallSpread:
    """
    Bear Call Spread — profit when market stays below sell strike.
    SELL lower CE (closer to money) + BUY higher CE (hedge).

    Max profit  = net_credit × lot_size          (per lot)
    Max loss    = (wing_width - net_credit) × lot_size
    Margin req  = wing_width × lot_size          (SPAN worst-case)
    Breakeven   = sell_strike + net_credit
    """

    def __init__(self, params: dict = None):
        self.params    = params or {}
        self.sell_delta = self.params.get("sell_delta", config.SELL_DELTA)
        self.buy_delta  = self.params.get("buy_delta",  config.BUY_DELTA)
        self.sl_pct     = self.params.get("sl_pct",     config.SL_PCT)
        self.lot_size   = int(self.params.get("lot_size", config.NIFTY_LOT_SIZE))
        self.strike_step = config.NIFTY_STRIKE_STEP

    def round_strike(self, p: float) -> int:
        return round(p / self.strike_step) * self.strike_step

    def build(self, spot: float, atr: float, vix: float = 14.5,
              kite_client=None, chain_data: dict = None) -> dict:
        """
        Build Bear Call Spread.
        Uses live chain data if provided (from option chain scanner),
        else falls back to ATR-based strike estimation.
        """
        expiry    = _get_next_tuesday()
        expiry_d  = _expiry_dict(expiry)

        strike_mode = self.params.get("strike_mode", "Delta")
        hedge_pts   = int(self.params.get("hedge_pts", 200))

        if strike_mode == "ATR":
            # ATR mode: sell at spot + ATR × multiplier, hedge 200pts further OTM
            dist         = atr * self.params.get("atr_multiplier", 1.25)
            ce_sell_s    = self.round_strike(spot + dist)
            ce_buy_s     = self.round_strike(ce_sell_s + hedge_pts)
            ce_sell_delta = self.sell_delta
            ce_buy_delta  = self.buy_delta
            ce_sell_prem = _estimate_prem(spot, ce_sell_s, "CE", ce_sell_delta, vix, expiry_d["dte"])
            ce_buy_prem  = _estimate_prem(spot, ce_buy_s,  "CE", ce_buy_delta,  vix, expiry_d["dte"])
            if kite_client:
                try:
                    from strategy.iron_condor import IronCondorStrategy
                    tmp = IronCondorStrategy(self.params)
                    expiry_raw = expiry
                    p = kite_client.get_option_ltp(tmp._kite_symbol(ce_sell_s, "CE", expiry_raw))
                    if p and p > 0.5: ce_sell_prem = round(p, 1)
                    p = kite_client.get_option_ltp(tmp._kite_symbol(ce_buy_s,  "CE", expiry_raw))
                    if p and p > 0.5: ce_buy_prem  = round(p, 1)
                except Exception:
                    pass
        elif chain_data and chain_data.get("scan_meta"):
            # Delta mode with live chain scan
            meta         = chain_data["scan_meta"]
            ce_sell_s    = meta["ce_sell"]["strike"]
            ce_buy_s     = meta["ce_buy"]["strike"]
            ce_sell_prem = meta["ce_sell"]["ltp"]
            ce_buy_prem  = meta["ce_buy"]["ltp"]
            ce_sell_delta = meta["ce_sell"]["delta"]
            ce_buy_delta  = meta["ce_buy"]["delta"]
        else:
            # Delta mode ATR fallback (no chain data)
            dist         = atr * self.params.get("atr_multiplier", config.ATR_MULTIPLIER)
            ce_sell_s    = self.round_strike(spot + dist)
            ce_buy_s     = self.round_strike(ce_sell_s + atr * 0.25)
            ce_sell_delta = self.sell_delta
            ce_buy_delta  = self.buy_delta
            ce_sell_prem = _estimate_prem(spot, ce_sell_s, "CE", ce_sell_delta, vix, expiry_d["dte"])
            ce_buy_prem  = _estimate_prem(spot, ce_buy_s,  "CE", ce_buy_delta,  vix, expiry_d["dte"])

        nc       = ce_sell_prem - ce_buy_prem
        wing     = ce_buy_s - ce_sell_s
        ls       = self.lot_size

        mp       = nc * ls                          # per lot
        ml       = (wing - nc) * ls                 # per lot
        margin   = wing * ls                        # SPAN worst-case per lot
        be       = ce_sell_s + nc

        ce_sl    = round(ce_sell_prem * (1 + self.sl_pct), 1)
        ce_tp    = round(ce_sell_prem * 0.5, 1)

        legs = [
            {
                "option_type": "CE", "action": "SELL",
                "strike": ce_sell_s, "delta": ce_sell_delta,
                "premium": ce_sell_prem,
                "sl_level": ce_sl, "tp_level": ce_tp,
                "lot_size": ls, "lots": 1,
                "type": "CE SELL",
                "symbol": _kite_symbol(ce_sell_s, "CE", expiry),
            },
            {
                "option_type": "CE", "action": "BUY",
                "strike": ce_buy_s, "delta": ce_buy_delta,
                "premium": ce_buy_prem,
                "sl_level": None, "tp_level": None,
                "lot_size": ls, "lots": 1,
                "type": "CE BUY (Hedge)",
                "symbol": _kite_symbol(ce_buy_s, "CE", expiry),
            },
        ]

        return {
            "strategy":        "Bear Call Spread",
            "legs":            legs,
            "net_credit":      round(nc, 2),
            "max_profit":      round(mp, 0),
            "max_loss":        round(ml, 0),
            "margin_per_lot":  round(margin, 0),
            "wing_width":      wing,
            "breakeven":       round(be, 0),
            "breakeven_upper": round(be, 0),
            "breakeven_lower": 0,
            "spot_at_entry":   spot,
        }

    def compute_payoff(self, price_range: np.ndarray, spread: dict) -> np.ndarray:
        payoff = np.zeros(len(price_range))
        for leg in spread["legs"]:
            intrinsic = np.maximum(price_range - leg["strike"], 0)
            if leg["action"] == "SELL":
                payoff += (leg["premium"] - intrinsic) * leg["lot_size"]
            else:
                payoff += (intrinsic - leg["premium"]) * leg["lot_size"]
        return payoff


class BullPutSpread:
    """
    Bull Put Spread — profit when market stays above sell strike.
    SELL higher PE (closer to money) + BUY lower PE (hedge).

    Max profit  = net_credit × lot_size          (per lot)
    Max loss    = (wing_width - net_credit) × lot_size
    Margin req  = wing_width × lot_size          (SPAN worst-case)
    Breakeven   = sell_strike - net_credit
    """

    def __init__(self, params: dict = None):
        self.params    = params or {}
        self.sell_delta = self.params.get("sell_delta", config.SELL_DELTA)
        self.buy_delta  = self.params.get("buy_delta",  config.BUY_DELTA)
        self.sl_pct     = self.params.get("sl_pct",     config.SL_PCT)
        self.lot_size   = int(self.params.get("lot_size", config.NIFTY_LOT_SIZE))
        self.strike_step = config.NIFTY_STRIKE_STEP

    def round_strike(self, p: float) -> int:
        return round(p / self.strike_step) * self.strike_step

    def build(self, spot: float, atr: float, vix: float = 14.5,
              kite_client=None, chain_data: dict = None) -> dict:
        expiry   = _get_next_tuesday()
        expiry_d = _expiry_dict(expiry)

        strike_mode = self.params.get("strike_mode", "Delta")
        hedge_pts   = int(self.params.get("hedge_pts", 200))

        if strike_mode == "ATR":
            dist         = atr * self.params.get("atr_multiplier", 1.25)
            pe_sell_s    = self.round_strike(spot - dist)
            pe_buy_s     = self.round_strike(pe_sell_s - hedge_pts)
            pe_sell_delta = self.sell_delta
            pe_buy_delta  = self.buy_delta
            pe_sell_prem = _estimate_prem(spot, pe_sell_s, "PE", pe_sell_delta, vix, expiry_d["dte"])
            pe_buy_prem  = _estimate_prem(spot, pe_buy_s,  "PE", pe_buy_delta,  vix, expiry_d["dte"])
            if kite_client:
                try:
                    from strategy.iron_condor import IronCondorStrategy
                    tmp = IronCondorStrategy(self.params)
                    expiry_raw = expiry
                    p = kite_client.get_option_ltp(tmp._kite_symbol(pe_sell_s, "PE", expiry_raw))
                    if p and p > 0.5: pe_sell_prem = round(p, 1)
                    p = kite_client.get_option_ltp(tmp._kite_symbol(pe_buy_s,  "PE", expiry_raw))
                    if p and p > 0.5: pe_buy_prem  = round(p, 1)
                except Exception:
                    pass
        elif chain_data and chain_data.get("scan_meta"):
            meta         = chain_data["scan_meta"]
            pe_sell_s    = meta["pe_sell"]["strike"]
            pe_buy_s     = meta["pe_buy"]["strike"]
            pe_sell_prem = meta["pe_sell"]["ltp"]
            pe_buy_prem  = meta["pe_buy"]["ltp"]
            pe_sell_delta = meta["pe_sell"]["delta"]
            pe_buy_delta  = meta["pe_buy"]["delta"]
        else:
            dist         = atr * self.params.get("atr_multiplier", config.ATR_MULTIPLIER)
            pe_sell_s    = self.round_strike(spot - dist)
            pe_buy_s     = self.round_strike(pe_sell_s - atr * 0.25)
            pe_sell_delta = self.sell_delta
            pe_buy_delta  = self.buy_delta
            pe_sell_prem = _estimate_prem(spot, pe_sell_s, "PE", pe_sell_delta, vix, expiry_d["dte"])
            pe_buy_prem  = _estimate_prem(spot, pe_buy_s,  "PE", pe_buy_delta,  vix, expiry_d["dte"])

        nc       = pe_sell_prem - pe_buy_prem
        wing     = pe_sell_s - pe_buy_s
        ls       = self.lot_size

        mp       = nc * ls
        ml       = (wing - nc) * ls
        margin   = wing * ls
        be       = pe_sell_s - nc

        pe_sl    = round(pe_sell_prem * (1 + self.sl_pct), 1)
        pe_tp    = round(pe_sell_prem * 0.5, 1)

        legs = [
            {
                "option_type": "PE", "action": "SELL",
                "strike": pe_sell_s, "delta": pe_sell_delta,
                "premium": pe_sell_prem,
                "sl_level": pe_sl, "tp_level": pe_tp,
                "lot_size": ls, "lots": 1,
                "type": "PE SELL",
                "symbol": _kite_symbol(pe_sell_s, "PE", expiry),
            },
            {
                "option_type": "PE", "action": "BUY",
                "strike": pe_buy_s, "delta": pe_buy_delta,
                "premium": pe_buy_prem,
                "sl_level": None, "tp_level": None,
                "lot_size": ls, "lots": 1,
                "type": "PE BUY (Hedge)",
                "symbol": _kite_symbol(pe_buy_s, "PE", expiry),
            },
        ]

        return {
            "strategy":        "Bull Put Spread",
            "legs":            legs,
            "net_credit":      round(nc, 2),
            "max_profit":      round(mp, 0),
            "max_loss":        round(ml, 0),
            "margin_per_lot":  round(margin, 0),
            "wing_width":      wing,
            "breakeven":       round(be, 0),
            "breakeven_upper": 0,
            "breakeven_lower": round(be, 0),
            "spot_at_entry":   spot,
        }

    def compute_payoff(self, price_range: np.ndarray, spread: dict) -> np.ndarray:
        payoff = np.zeros(len(price_range))
        for leg in spread["legs"]:
            intrinsic = np.maximum(leg["strike"] - price_range, 0)
            if leg["action"] == "SELL":
                payoff += (leg["premium"] - intrinsic) * leg["lot_size"]
            else:
                payoff += (intrinsic - leg["premium"]) * leg["lot_size"]
        return payoff


def _estimate_prem(spot, strike, opt_type, delta, vix, dte):
    import math
    sigma = vix / 100
    t     = max(dte / 365, 0.001)
    vol_p = spot * sigma * math.sqrt(t) * delta * 1.5
    return round(max(5.0, vol_p), 1)
