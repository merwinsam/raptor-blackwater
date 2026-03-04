"""
Raptor — Spread Strategies
Bear Call Spread : SELL CE (closer to money) + BUY CE (200pts further OTM)
Bull Put Spread  : SELL PE (closer to money) + BUY PE (200pts further OTM)

Margin (NSE SPAN approximation):
  Spread margin = wing_width × lot_size
  Net margin    = (wing_width - net_credit) × lot_size

Max Loss  = (wing_width - net_credit) × lot_size
Max Profit = net_credit × lot_size
Breakeven  = sell_strike + net_credit  (CE) / sell_strike - net_credit  (PE)
"""

import math
import numpy as np
from datetime import date, timedelta
import config


# ── Vol surface (shared with option_chain.py) ─────────────────────────────────
_CE_MULTS = [1.00, 1.10, 1.18, 1.25, 1.30, 1.34, 1.37, 1.38, 1.35, 1.30, 1.25]
_PE_MULTS = [1.00, 1.15, 1.25, 1.38, 1.52, 1.68, 1.85, 2.05, 2.28, 2.55, 2.85]

def _N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def _vol_mult(otm_pct, opt_type):
    mults = _CE_MULTS if opt_type == "CE" else _PE_MULTS
    idx   = min(int(otm_pct), len(mults) - 2)
    frac  = otm_pct - idx
    return mults[idx] + frac * (mults[min(idx + 1, len(mults) - 1)] - mults[idx])

def _bs_price(S, K, T, r, sigma, opt_type):
    if T <= 0:
        return max(S - K, 0) if opt_type == "CE" else max(K - S, 0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type == "CE":
        return S * _N(d1) - K * math.exp(-r * T) * _N(d2)
    else:
        return K * math.exp(-r * T) * (1 - _N(d2)) - S * (1 - _N(d1))

def _estimate_prem(spot, strike, opt_type, vix, dte, r=0.065):
    """
    Offline premium estimator — BS with NIFTY vol surface.
    Only used when Kite disconnected. Calibrated to NSE market prices.
    """
    T       = max(dte / 365.0, 1 / 365)
    otm_pct = abs(strike - spot) / spot * 100
    sigma   = (vix * _vol_mult(otm_pct, opt_type)) / 100.0
    p       = _bs_price(spot, strike, T, r, sigma, opt_type)
    return round(max(0.5, p), 1)

def _estimate_delta(spot, strike, opt_type, vix, dte, r=0.065):
    T       = max(dte / 365.0, 1 / 365)
    otm_pct = abs(strike - spot) / spot * 100
    sigma   = (vix * _vol_mult(otm_pct, opt_type)) / 100.0
    d1      = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    delta   = _N(d1) if opt_type == "CE" else _N(d1) - 1
    return round(delta, 3)


# ── Kite symbol helpers ───────────────────────────────────────────────────────

def _kite_symbol(strike: int, option_type: str, expiry_date) -> str:
    yy = expiry_date.strftime("%y")
    m  = str(expiry_date.month)
    dd = str(expiry_date.day)
    return f"NIFTY{yy}{m}{dd}{strike}{option_type}"


def _get_next_expiry() -> date:
    """
    Get appropriate weekly Tuesday expiry (≥ 3 DTE).
    Matches NSE behaviour: skip current week if expiry is too close.
    """
    today       = date.today()
    days_to_tue = (1 - today.weekday()) % 7
    this_tue    = today + timedelta(days=days_to_tue)
    if (this_tue - today).days < 3:
        this_tue += timedelta(weeks=1)
    return this_tue


def _expiry_dict(d: date) -> dict:
    return {
        "expiry_date":     d.strftime("%d %b %Y"),
        "expiry_date_raw": d,
        "dte":             (d - date.today()).days,
        "week":            "NEXT",
    }


class BearCallSpread:
    """
    Bear Call Spread — SELL lower CE + BUY higher CE (hedge 200pts OTM).
    Profit when market stays below sell strike at expiry.

    Max profit  = net_credit × lot_size
    Max loss    = (wing - net_credit) × lot_size
    Breakeven   = sell_strike + net_credit
    """

    def __init__(self, params: dict = None):
        self.params      = params or {}
        self.sell_delta  = self.params.get("sell_delta", config.SELL_DELTA)
        self.buy_delta   = self.params.get("buy_delta",  config.BUY_DELTA)
        self.sl_pct      = self.params.get("sl_pct",     config.SL_PCT)
        self.lot_size    = int(self.params.get("lot_size", config.NIFTY_LOT_SIZE))
        self.strike_step = config.NIFTY_STRIKE_STEP
        self.hedge_pts   = int(self.params.get("hedge_pts", 200))

    def round_strike(self, p: float) -> int:
        return round(p / self.strike_step) * self.strike_step

    def build(self, spot: float, atr: float, vix: float = 14.5,
              kite_client=None, chain_data: dict = None) -> dict:

        expiry   = _get_next_expiry()
        expiry_d = _expiry_dict(expiry)
        dte      = expiry_d["dte"]

        if chain_data and chain_data.get("scan_meta"):
            # ── Live chain (connected) ────────────────────────────────────────
            meta          = chain_data["scan_meta"]
            ce_sell_s     = meta["ce_sell"]["strike"]
            ce_sell_prem  = meta["ce_sell"]["ltp"]
            ce_sell_delta = meta["ce_sell"]["delta"]
            # BUY leg: 200pts further OTM from SELL strike (fixed hedge distance)
            ce_buy_s      = ce_sell_s + self.hedge_pts
            # Try to get live price for the buy leg
            ce_buy_prem   = meta["ce_buy"]["ltp"]
            ce_buy_delta  = meta["ce_buy"]["delta"]
            # If scanner picked a different buy strike, override with 200pt hedge
            if meta["ce_buy"]["strike"] != ce_buy_s:
                ce_buy_prem  = _estimate_prem(spot, ce_buy_s, "CE", vix, dte)
                ce_buy_delta = _estimate_delta(spot, ce_buy_s, "CE", vix, dte)
                if kite_client:
                    try:
                        p = kite_client.get_option_ltp(_kite_symbol(ce_buy_s, "CE", expiry))
                        if p and p > 0.5:
                            ce_buy_prem = round(p, 1)
                    except Exception:
                        pass
        else:
            # ── Offline fallback ─────────────────────────────────────────────
            # Sell strike: ATR × multiplier OTM from spot
            dist         = atr * self.params.get("atr_multiplier", config.ATR_MULTIPLIER)
            ce_sell_s    = self.round_strike(spot + dist)
            ce_buy_s     = ce_sell_s + self.hedge_pts   # fixed 200pts hedge
            ce_sell_prem  = _estimate_prem(spot, ce_sell_s, "CE", vix, dte)
            ce_buy_prem   = _estimate_prem(spot, ce_buy_s,  "CE", vix, dte)
            ce_sell_delta = _estimate_delta(spot, ce_sell_s, "CE", vix, dte)
            ce_buy_delta  = _estimate_delta(spot, ce_buy_s,  "CE", vix, dte)

        nc     = ce_sell_prem - ce_buy_prem
        wing   = ce_buy_s - ce_sell_s
        ls     = self.lot_size
        mp     = round(nc * ls, 0)
        ml     = round((wing - nc) * ls, 0)
        margin = round(wing * ls, 0)
        be     = ce_sell_s + nc
        ce_sl  = round(ce_sell_prem * (1 + self.sl_pct), 1)
        ce_tp  = round(ce_sell_prem * 0.5, 1)

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
            "max_profit":      mp,
            "max_loss":        ml,
            "margin_per_lot":  margin,
            "wing_width":      wing,
            "breakeven":       round(be, 0),
            "breakeven_upper": round(be, 0),
            "breakeven_lower": 0,
            "spot_at_entry":   spot,
            "strike_distance": round(ce_sell_s - spot, 0),
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
    Bull Put Spread — SELL higher PE + BUY lower PE (hedge 200pts OTM).
    Profit when market stays above sell strike at expiry.

    Max profit  = net_credit × lot_size
    Max loss    = (wing - net_credit) × lot_size
    Breakeven   = sell_strike - net_credit
    """

    def __init__(self, params: dict = None):
        self.params      = params or {}
        self.sell_delta  = self.params.get("sell_delta", config.SELL_DELTA)
        self.buy_delta   = self.params.get("buy_delta",  config.BUY_DELTA)
        self.sl_pct      = self.params.get("sl_pct",     config.SL_PCT)
        self.lot_size    = int(self.params.get("lot_size", config.NIFTY_LOT_SIZE))
        self.strike_step = config.NIFTY_STRIKE_STEP
        self.hedge_pts   = int(self.params.get("hedge_pts", 200))

    def round_strike(self, p: float) -> int:
        return round(p / self.strike_step) * self.strike_step

    def build(self, spot: float, atr: float, vix: float = 14.5,
              kite_client=None, chain_data: dict = None) -> dict:

        expiry   = _get_next_expiry()
        expiry_d = _expiry_dict(expiry)
        dte      = expiry_d["dte"]

        if chain_data and chain_data.get("scan_meta"):
            # ── Live chain ────────────────────────────────────────────────────
            meta          = chain_data["scan_meta"]
            pe_sell_s     = meta["pe_sell"]["strike"]
            pe_sell_prem  = meta["pe_sell"]["ltp"]
            pe_sell_delta = meta["pe_sell"]["delta"]
            # BUY leg: 200pts further OTM (lower)
            pe_buy_s      = pe_sell_s - self.hedge_pts
            pe_buy_prem   = meta["pe_buy"]["ltp"]
            pe_buy_delta  = meta["pe_buy"]["delta"]
            if meta["pe_buy"]["strike"] != pe_buy_s:
                pe_buy_prem  = _estimate_prem(spot, pe_buy_s, "PE", vix, dte)
                pe_buy_delta = _estimate_delta(spot, pe_buy_s, "PE", vix, dte)
                if kite_client:
                    try:
                        p = kite_client.get_option_ltp(_kite_symbol(pe_buy_s, "PE", expiry))
                        if p and p > 0.5:
                            pe_buy_prem = round(p, 1)
                    except Exception:
                        pass
        else:
            # ── Offline fallback ─────────────────────────────────────────────
            dist          = atr * self.params.get("atr_multiplier", config.ATR_MULTIPLIER)
            pe_sell_s     = self.round_strike(spot - dist)
            pe_buy_s      = pe_sell_s - self.hedge_pts
            pe_sell_prem  = _estimate_prem(spot, pe_sell_s, "PE", vix, dte)
            pe_buy_prem   = _estimate_prem(spot, pe_buy_s,  "PE", vix, dte)
            pe_sell_delta = _estimate_delta(spot, pe_sell_s, "PE", vix, dte)
            pe_buy_delta  = _estimate_delta(spot, pe_buy_s,  "PE", vix, dte)

        nc     = pe_sell_prem - pe_buy_prem
        wing   = pe_sell_s - pe_buy_s
        ls     = self.lot_size
        mp     = round(nc * ls, 0)
        ml     = round((wing - nc) * ls, 0)
        margin = round(wing * ls, 0)
        be     = pe_sell_s - nc
        pe_sl  = round(pe_sell_prem * (1 + self.sl_pct), 1)
        pe_tp  = round(pe_sell_prem * 0.5, 1)

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
            "max_profit":      mp,
            "max_loss":        ml,
            "margin_per_lot":  margin,
            "wing_width":      wing,
            "breakeven":       round(be, 0),
            "breakeven_upper": 0,
            "breakeven_lower": round(be, 0),
            "spot_at_entry":   spot,
            "strike_distance": round(spot - pe_sell_s, 0),
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
