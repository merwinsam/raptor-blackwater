"""
ATR Model - Computes Average True Range for strike selection
Uses VIX proxy when historical data unavailable (paper mode)
"""

import numpy as np
from datetime import datetime, timedelta
import config


class ATRModel:
    """
    Computes ATR for NIFTY to determine strike distance.
    
    In live mode: fetches OHLC from Kite and computes real ATR
    In paper mode: uses VIX-based approximation
    """

    def __init__(self, period: int = 14):
        self.period = period

    def compute_atr_from_ohlc(self, ohlc_data: list) -> float:
        """
        Compute ATR from OHLC candles.
        ohlc_data: list of dicts with keys 'high', 'low', 'close'
        """
        if len(ohlc_data) < 2:
            return 300.0  # fallback

        true_ranges = []
        for i in range(1, len(ohlc_data)):
            high = ohlc_data[i]["high"]
            low = ohlc_data[i]["low"]
            prev_close = ohlc_data[i - 1]["close"]

            tr = max(
                high - low,
                abs(high - prev_close),
                abs(low - prev_close)
            )
            true_ranges.append(tr)

        # Wilder's smoothing
        atr = sum(true_ranges[:self.period]) / self.period
        for tr in true_ranges[self.period:]:
            atr = (atr * (self.period - 1) + tr) / self.period

        return round(atr, 2)

    def compute_atr_from_vix(self, spot: float, vix: float) -> float:
        """
        Paper mode: approximate daily ATR using VIX.
        
        Formula: ATR ≈ (VIX / 100) / sqrt(252) * spot * sqrt(14)
        This gives 14-day expected move range as proxy for ATR.
        """
        daily_move_pct = (vix / 100) / np.sqrt(252)
        daily_atr = daily_move_pct * spot
        # Scale to 14-day equivalent
        atr_14d = daily_atr * np.sqrt(self.period)
        return round(atr_14d, 2)

    def get_strike_distance(self, spot: float, atr: float, multiplier: float = None) -> float:
        """
        Returns strike distance from spot = ATR * multiplier
        """
        if multiplier is None:
            multiplier = config.ATR_MULTIPLIER
        return round(atr * multiplier, 0)

    def expected_move(self, spot: float, vix: float, dte: int) -> dict:
        """
        Compute expected move for a given DTE.
        Used for sanity checking strikes.
        """
        daily_vol = (vix / 100) / np.sqrt(252)
        move = spot * daily_vol * np.sqrt(dte)
        return {
            "expected_move_pts": round(move, 0),
            "expected_move_pct": round(daily_vol * np.sqrt(dte) * 100, 2),
            "upper_bound": round(spot + move, 0),
            "lower_bound": round(spot - move, 0),
            "one_sigma_up": round(spot + move, 0),
            "one_sigma_dn": round(spot - move, 0),
        }
