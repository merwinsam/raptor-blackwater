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
        Rough premium estimate using Black-Scholes approximation.
        For paper trading — gives realistic ballpark numbers.
        """
        sigma = vix / 100
        t = dte / 365
        moneyness = abs(spot - strike) / spot
        
        # Simple approximation: OTM premium ≈ intrinsic adjusted by vol
        vol_premium = spot * sigma * np.sqrt(t) * delta * 1.5
        
        # Add small base premium
        base = max(5, vol_premium)
        return round(base, 1)

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
            m   = str(expiry_date.month)          # "3"  no leading zero
            dd  = str(expiry_date.day)            # "10" no leading zero
            return f"NIFTY{yy}{m}{dd}{strike}{option_type}"
        return f"NIFTY{strike}{option_type}"

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

        # ── Buy strikes (further OTM, ~0.10 delta)
        # Approximate additional distance for buy legs
        buy_extra = atr * 0.25  # ~25% more OTM than sell
        ce_buy_strike = self.round_to_strike(ce_sell_strike + buy_extra)
        pe_buy_strike = self.round_to_strike(pe_sell_strike - buy_extra)

        # ── Get premiums — real from Kite if available, else estimate
        expiry_tmp = self.get_next_week_expiry()["expiry_date_raw"]
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

        # ── Max loss per wing = (wing_width - net_credit) * lot_size
        # Use each wing independently (handles asymmetric condors correctly)
        max_loss_ce = (ce_wing_width - net_credit) * self.lot_size
        max_loss_pe = (pe_wing_width - net_credit) * self.lot_size
        max_loss = max(max_loss_ce, max_loss_pe)  # worst case wing

        # ── Breakevens
        breakeven_upper = ce_sell_strike + net_credit
        breakeven_lower = pe_sell_strike - net_credit

        # ── SL levels per sell leg
        ce_sl = ce_sell_prem * (1 + self.sl_pct)
        pe_sl = pe_sell_prem * (1 + self.sl_pct)

        # ── Margin (rough estimate: wing_width * lot_size)
        margin_required = max(ce_wing_width, pe_wing_width) * self.lot_size

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
            # margin_per_lot = SPAN worst-case = max wing × lot_size
            "margin_per_lot":  round(max(ce_wing_width, pe_wing_width) * self.lot_size, 0),
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

    def get_next_week_expiry(self) -> dict:
        """
        Get the NEXT week's Tuesday expiry (NIFTY weekly).
        NIFTY 50 weekly options changed to Tuesday expiry from Sept 2025.
        Always picks NEXT week's Tuesday, not the current week.
        """
        today = date.today()
        # Tuesday = weekday 1
        days_to_tuesday = (1 - today.weekday()) % 7
        this_tuesday = today + timedelta(days=days_to_tuesday)

        # Always go to NEXT week's Tuesday
        if days_to_tuesday == 0:
            next_tuesday = this_tuesday + timedelta(weeks=1)
        else:
            next_tuesday = this_tuesday + timedelta(weeks=1)

        dte = (next_tuesday - today).days

        return {
            "expiry_date": next_tuesday.strftime("%d %b %Y"),
            "expiry_date_raw": next_tuesday,
            "dte": dte,
            "week": "NEXT",
        }
