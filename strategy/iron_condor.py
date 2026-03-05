"""
Iron Condor Strategy Engine
- Selects strikes based on ATR and delta targets
- Builds condor structure with all 4 legs
- Computes payoff, max profit, max loss, breakevens
"""

import numpy as np
from datetime import datetime, date, timedelta
import config


class IronCondorStrategy:
    def __init__(self, params: dict = None):
        self.params = params or {}
        self.atr_multiplier = self.params.get("atr_multiplier", config.ATR_MULTIPLIER)
        self.sell_delta = self.params.get("sell_delta", config.SELL_DELTA)
        self.buy_delta = self.params.get("buy_delta", config.BUY_DELTA)
        self.sl_pct = self.params.get("sl_pct", config.SL_PCT)
        # Use lot_size from params if provided (sidebar override), else config default
        self.lot_size = int(self.params.get("lot_size", config.NIFTY_LOT_SIZE))
        self.strike_step = config.NIFTY_STRIKE_STEP

    def round_to_strike(self, price: float) -> int:
        """Round to nearest valid NIFTY strike (multiples of 50)"""
        return round(price / self.strike_step) * self.strike_step

    def estimate_premium_from_delta(self, spot: float, strike: float,
                                     option_type: str, delta: float,
                                     vix: float = 14.5, dte: int = 14) -> float:
        """
        Offline premium estimator using BS with NIFTY vol surface.
        Calibrated to NSE market prices: VIX=14.5, 13 DTE, 6.8% OTM CE → ~₹18.
        """
        import math
        def _N(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
        CE_M = [1.00,1.10,1.18,1.25,1.30,1.34,1.37,1.38,1.35,1.30,1.25]
        PE_M = [1.00,1.15,1.25,1.38,1.52,1.68,1.85,2.05,2.28,2.55,2.85]
        mults = CE_M if option_type == "CE" else PE_M
        otm_pct = abs(strike - spot) / spot * 100
        idx = min(int(otm_pct), len(mults) - 2)
        frac = otm_pct - idx
        mult = mults[idx] + frac * (mults[min(idx+1, len(mults)-1)] - mults[idx])
        sigma = (vix * mult) / 100.0
        T = max(dte / 365.0, 1/365)
        r = 0.065
        d1 = (math.log(spot / strike) + (r + 0.5*sigma**2)*T) / (sigma*math.sqrt(T))
        d2 = d1 - sigma*math.sqrt(T)
        if option_type == "CE":
            p = spot*_N(d1) - strike*math.exp(-r*T)*_N(d2)
        else:
            p = strike*math.exp(-r*T)*(1-_N(d2)) - spot*(1-_N(d1))
        return round(max(0.5, p), 1)

    def _kite_symbol(self, strike: int, option_type: str, expiry_date) -> str:
        """
        Build Kite-compatible NFO symbol.
        Format: NIFTY{YY}{M}{DD}{strike}{CE/PE}
        Example: NIFTY2631026700CE  (2026-03-10, strike 26700)
        YY = 2-digit year, M = month no leading zero, DD = 2-digit day
        """
        from datetime import date as date_type
        if isinstance(expiry_date, date_type):
            yy  = expiry_date.strftime("%y")   # "26"
            m   = str(expiry_date.month)
            dd  = str(expiry_date.day)
            return f"NIFTY{yy}{m}{dd}{int(strike)}{option_type}"
        return f"NIFTY{int(strike)}{option_type}"

    def build_condor(self, spot: float, atr: float, vix: float = 14.5, dte: int = 14, kite_client=None) -> dict:
        """
        Build full iron condor structure.
        
        Returns:
            dict with legs, max_profit, max_loss, breakevens, margin
        """
        strike_distance = atr * self.atr_multiplier

        # ── Sell strikes (closer to money, ~0.15 delta)
        ce_sell_strike = self.round_to_strike(spot + strike_distance)
        pe_sell_strike = self.round_to_strike(spot - strike_distance)

        # ── Buy strikes (hedge): fixed 200pts further OTM than sell
        # 200pt wing matches standard NIFTY spread sizing (per Sensibull/NSE norms)
        hedge_pts = int(self.params.get("hedge_pts", 200))
        ce_buy_strike = self.round_to_strike(ce_sell_strike + hedge_pts)
        pe_buy_strike = self.round_to_strike(pe_sell_strike - hedge_pts)

        # ── Get premiums — real from Kite if available, else estimate
        expiry_tmp = self.get_next_week_expiry(int(self.params.get("dte_target", 14)))["expiry_date_raw"]
        def _get_prem(strike, otype, delta_fallback):
            if kite_client:
                try:
                    sym = self._kite_symbol(strike, otype, expiry_tmp)
                    price = kite_client.get_option_ltp(sym)
                    if price and price > 0.5:
                        return round(price, 1)
                except Exception:
                    pass
            return self.estimate_premium_from_delta(spot, strike, otype, delta_fallback, vix, dte)

        ce_sell_prem = _get_prem(ce_sell_strike, "CE", self.sell_delta)
        pe_sell_prem = _get_prem(pe_sell_strike, "PE", self.sell_delta)
        ce_buy_prem  = _get_prem(ce_buy_strike,  "CE", self.buy_delta)
        pe_buy_prem  = _get_prem(pe_buy_strike,  "PE", self.buy_delta)

        # ── Net credit per lot
        net_credit = (ce_sell_prem + pe_sell_prem) - (ce_buy_prem + pe_buy_prem)

        # ── Wing widths
        ce_wing_width = ce_buy_strike - ce_sell_strike
        pe_wing_width = pe_sell_strike - pe_buy_strike

        # ── Max profit = net credit * lot_size
        max_profit = net_credit * self.lot_size

        # ── Max loss per wing — use per-wing NC (not total condor NC)
        # Iron Condor max loss = worst wing: (wing_width - that_wing_NC) × lot_size
        # CE wing NC = ce_sell_prem - ce_buy_prem
        # PE wing NC = pe_sell_prem - pe_buy_prem
        ce_wing_nc   = ce_sell_prem - ce_buy_prem
        pe_wing_nc   = pe_sell_prem - pe_buy_prem
        max_loss_ce  = (ce_wing_width - ce_wing_nc) * self.lot_size
        max_loss_pe  = (pe_wing_width - pe_wing_nc) * self.lot_size
        max_loss     = max(max_loss_ce, max_loss_pe)

        # ── Breakevens
        breakeven_upper = ce_sell_strike + net_credit
        breakeven_lower = pe_sell_strike - net_credit

        # ── SL levels per sell leg
        ce_sl = ce_sell_prem * (1 + self.sl_pct)
        pe_sl = pe_sell_prem * (1 + self.sl_pct)

        # ── Margin: NSE SPAN ≈ 3% of notional for hedged spread
        margin_required = round(spot * self.lot_size * 0.03, 0)

        expiry = self.get_next_week_expiry()

        legs = [
            {
                "option_type": "CE",
                "action": "BUY",
                "strike": ce_buy_strike,
                "delta": self.buy_delta,
                "premium": ce_buy_prem,
                "sl_level": None,  # Buy legs don't have SL
                "tp_level": None,
                "lot_size": self.lot_size,
                "lots": 1,
                "type": "CE BUY (Hedge)",
                "symbol": self._kite_symbol(ce_buy_strike,  "CE", expiry["expiry_date_raw"]),
            },
            {
                "option_type": "CE",
                "action": "SELL",
                "strike": ce_sell_strike,
                "delta": self.sell_delta,
                "premium": ce_sell_prem,
                "sl_level": round(ce_sl, 1),
                "tp_level": round(ce_sell_prem * 0.5, 1),
                "lot_size": self.lot_size,
                "lots": 1,
                "type": "CE SELL",
                "symbol": self._kite_symbol(ce_sell_strike, "CE", expiry["expiry_date_raw"]),
            },
            {
                "option_type": "PE",
                "action": "SELL",
                "strike": pe_sell_strike,
                "delta": self.sell_delta,
                "premium": pe_sell_prem,
                "sl_level": round(pe_sl, 1),
                "tp_level": round(pe_sell_prem * 0.5, 1),
                "lot_size": self.lot_size,
                "lots": 1,
                "type": "PE SELL",
                "symbol": self._kite_symbol(pe_sell_strike, "PE", expiry["expiry_date_raw"]),
            },
            {
                "option_type": "PE",
                "action": "BUY",
                "strike": pe_buy_strike,
                "delta": self.buy_delta,
                "premium": pe_buy_prem,
                "sl_level": None,
                "tp_level": None,
                "lot_size": self.lot_size,
                "lots": 1,
                "type": "PE BUY (Hedge)",
                "symbol": self._kite_symbol(pe_buy_strike,  "PE", expiry["expiry_date_raw"]),
            },
        ]

        return {
            "legs":            legs,
            "net_credit":      round(net_credit, 2),
            "max_profit":      round(max_profit, 0),
            "max_loss":        round(max_loss, 0),
            "breakeven_upper": round(breakeven_upper, 0),
            "breakeven_lower": round(breakeven_lower, 0),
            "margin_required": round(margin_required, 0),
            "margin_per_lot":  round(spot * self.lot_size * 0.03, 0),
            "wing_width":      max(ce_wing_width, pe_wing_width),
            "spot_at_entry":   spot,
            "atr":             atr,
            "strike_distance": round(strike_distance, 0),
        }

    def compute_payoff(self, price_range: np.ndarray, condor: dict) -> np.ndarray:
        """Compute P&L at expiry for each price in range"""
        legs = condor["legs"]
        payoff = np.zeros(len(price_range))

        for leg in legs:
            strike = leg["strike"]
            premium = leg["premium"]
            opt_type = leg["option_type"]
            action = leg["action"]
            lot_size = leg["lot_size"]

            if opt_type == "CE":
                intrinsic = np.maximum(price_range - strike, 0)
            else:
                intrinsic = np.maximum(strike - price_range, 0)

            if action == "SELL":
                leg_payoff = (premium - intrinsic) * lot_size
            else:
                leg_payoff = (intrinsic - premium) * lot_size

            payoff += leg_payoff

        return payoff

    def get_next_week_expiry(self, dte_target: int = 14) -> dict:
        """
        Get Tuesday expiry closest to dte_target days from today.
        dte_target=14 → ~2 weeks, dte_target=21 → ~3 weeks.
        Always ≥ 3 DTE.
        """
        today           = date.today()
        days_to_tue     = (1 - today.weekday()) % 7
        this_tue        = today + timedelta(days=days_to_tue)
        tuesdays        = [this_tue + timedelta(weeks=i) for i in range(6)]
        valid           = [t for t in tuesdays if (t - today).days >= 3]
        best            = min(valid, key=lambda t: abs((t - today).days - dte_target))
        dte             = (best - today).days
        return {
            "expiry_date":     best.strftime("%d %b %Y"),
            "expiry_date_raw": best,
            "dte":             dte,
            "week":            "NEXT",
        }
