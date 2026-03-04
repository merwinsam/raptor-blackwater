"""
Raptor — Option Chain Scanner
Fetches live NIFTY option chain from Kite Connect and finds
strikes closest to target delta using real market Greeks.
"""

import math
import numpy as np
from datetime import date, datetime, timezone, timedelta
from typing import Optional


# ── Black-Scholes delta (fallback when Kite Greeks unavailable) ───────────────

def _bs_delta(spot: float, strike: float, tte: float,
              sigma: float, option_type: str) -> float:
    """
    Black-Scholes delta. tte = time to expiry in years.
    Returns positive delta for CE, negative for PE.
    """
    if tte <= 0 or sigma <= 0:
        return 0.0
    try:
        from scipy.stats import norm
        d1 = (math.log(spot / strike) + 0.5 * sigma ** 2 * tte) / (sigma * math.sqrt(tte))
        if option_type == "CE":
            return norm.cdf(d1)
        else:
            return norm.cdf(d1) - 1
    except ImportError:
        # Fallback without scipy — simple approximation
        d1 = (math.log(spot / strike) + 0.5 * sigma ** 2 * tte) / (sigma * math.sqrt(tte))
        # Approximate normal CDF
        cdf = 0.5 * (1 + math.erf(d1 / math.sqrt(2)))
        if option_type == "CE":
            return cdf
        else:
            return cdf - 1


def _implied_sigma(vix: float) -> float:
    """Convert India VIX (annualised %) to daily sigma."""
    return vix / 100.0


class OptionChainScanner:
    """
    Scans NIFTY option chain from Kite and finds strikes
    whose delta is closest to the target.
    """

    STRIKE_RANGE = 3000   # scan ±3000 pts from spot
    STRIKE_STEP  = 50     # NIFTY strike step

    def __init__(self, kite_client):
        self.kite = kite_client

    # ── Instrument cache ──────────────────────────────────────────────────────

    def _get_nfo_instruments(self) -> list:
        """Fetch full NFO instrument dump from Kite (cached in session)."""
        import streamlit as st
        cache_key = "_nfo_instruments_cache"
        cache_date_key = "_nfo_instruments_date"
        today = date.today().isoformat()

        if (st.session_state.get(cache_date_key) == today
                and st.session_state.get(cache_key)):
            return st.session_state[cache_key]

        instruments = self.kite.kite.instruments("NFO")
        st.session_state[cache_key]      = instruments
        st.session_state[cache_date_key] = today
        return instruments

    def _get_expiry(self) -> date:
        """Get next weekly Tuesday expiry."""
        today = date.today()
        days_to_tue = (1 - today.weekday()) % 7
        this_tue    = today + timedelta(days=days_to_tue)
        next_tue    = this_tue + timedelta(weeks=1)
        return next_tue

    # ── Main scan ─────────────────────────────────────────────────────────────

    def scan(self,
             spot:         float,
             vix:          float,
             sell_delta:   float = 0.15,
             buy_delta:    float = 0.10,
             sl_pct:       float = 0.50,
             lot_size:     int   = 50) -> dict:
        """
        Scan live option chain and return a complete condor structure
        with strikes chosen by delta proximity.

        Returns same dict shape as IronCondorStrategy.build_condor()
        so app.py needs zero changes downstream.
        """
        expiry     = self._get_expiry()
        dte        = (expiry - date.today()).days
        tte        = dte / 365.0
        sigma      = _implied_sigma(vix)

        # ── Step 1: Get all NIFTY options for this expiry ─────────────────────
        instruments = self._get_nfo_instruments()
        nifty_opts  = [
            i for i in instruments
            if (i["name"] == "NIFTY"
                and i["instrument_type"] in ("CE", "PE")
                and isinstance(i.get("expiry"), date)
                and i["expiry"] == expiry
                and abs(i["strike"] - spot) <= self.STRIKE_RANGE)
        ]

        if not nifty_opts:
            raise ValueError(
                f"No NIFTY options found for expiry {expiry}. "
                "Check Kite connection and ensure market is open."
            )

        # ── Step 2: Fetch live quotes (Greeks + LTP) ──────────────────────────
        # Kite quote() returns Greeks when market is open
        tokens    = [str(i["instrument_token"]) for i in nifty_opts]
        sym_map   = {str(i["instrument_token"]): i for i in nifty_opts}

        # Batch into chunks of 500 (Kite limit)
        quotes    = {}
        for chunk_start in range(0, len(tokens), 500):
            chunk = tokens[chunk_start:chunk_start + 500]
            try:
                q = self.kite.kite.quote(chunk)
                quotes.update(q)
            except Exception:
                pass

        # ── Step 3: Build chain rows with delta ───────────────────────────────
        chain = []
        for token, instr in sym_map.items():
            q     = quotes.get(token, {})
            ltp   = (q.get("last_price") or
                     q.get("ohlc", {}).get("close") or 0.0)
            greeks = q.get("greeks") or {}

            # Use Kite Greeks if available, else compute BS delta
            raw_delta = greeks.get("delta")
            if raw_delta is not None:
                delta = float(raw_delta)
            else:
                delta = _bs_delta(spot, instr["strike"], tte,
                                  sigma, instr["instrument_type"])

            if ltp < 0.5:
                continue   # skip illiquid / zero-price strikes

            chain.append({
                "strike":      instr["strike"],
                "type":        instr["instrument_type"],
                "ltp":         round(ltp, 2),
                "delta":       round(abs(delta), 4),
                "delta_raw":   round(delta, 4),
                "token":       token,
                "symbol":      instr["tradingsymbol"],
            })

        if not chain:
            raise ValueError(
                "Option chain fetched but all premiums are zero. "
                "Market may be closed — prices unavailable outside trading hours."
            )

        ce_chain = sorted([r for r in chain if r["type"] == "CE"],
                          key=lambda x: x["strike"])
        pe_chain = sorted([r for r in chain if r["type"] == "PE"],
                          key=lambda x: x["strike"], reverse=True)

        # ── Step 4: Find strikes closest to target delta ──────────────────────
        def closest(rows, target_delta):
            return min(rows, key=lambda r: abs(r["delta"] - target_delta))

        ce_sell = closest([r for r in ce_chain if r["strike"] > spot], sell_delta)
        pe_sell = closest([r for r in pe_chain if r["strike"] < spot], sell_delta)

        # Buy legs: further OTM than sell legs
        ce_buy = closest(
            [r for r in ce_chain if r["strike"] > ce_sell["strike"]],
            buy_delta
        )
        pe_buy = closest(
            [r for r in pe_chain if r["strike"] < pe_sell["strike"]],
            buy_delta
        )

        # ── Step 5: Build condor dict ─────────────────────────────────────────
        nc   = (ce_sell["ltp"] + pe_sell["ltp"]) - (ce_buy["ltp"] + pe_buy["ltp"])
        ls   = int(lot_size)  # from sidebar

        ce_wing = ce_buy["strike"]  - ce_sell["strike"]
        pe_wing = pe_sell["strike"] - pe_buy["strike"]

        mp   = nc * ls
        ml   = (max(ce_wing, pe_wing) - nc) * ls
        be_u = ce_sell["strike"] + nc
        be_d = pe_sell["strike"] - nc

        ce_sl_level = round(ce_sell["ltp"] * (1 + sl_pct), 1)
        pe_sl_level = round(pe_sell["ltp"] * (1 + sl_pct), 1)

        def _expiry_str(d: date) -> str:
            return d.strftime("%d %b %Y")

        legs = [
            {
                "option_type": "CE", "action": "BUY",
                "strike": ce_buy["strike"], "delta": ce_buy["delta"],
                "premium": ce_buy["ltp"],
                "sl_level": None, "tp_level": None,
                "lot_size": ls, "lots": 1,
                "type": "CE BUY (Hedge)",
                "symbol": ce_buy["symbol"],
            },
            {
                "option_type": "CE", "action": "SELL",
                "strike": ce_sell["strike"], "delta": ce_sell["delta"],
                "premium": ce_sell["ltp"],
                "sl_level": ce_sl_level,
                "tp_level": round(ce_sell["ltp"] * 0.5, 1),
                "lot_size": ls, "lots": 1,
                "type": "CE SELL",
                "symbol": ce_sell["symbol"],
            },
            {
                "option_type": "PE", "action": "SELL",
                "strike": pe_sell["strike"], "delta": pe_sell["delta"],
                "premium": pe_sell["ltp"],
                "sl_level": pe_sl_level,
                "tp_level": round(pe_sell["ltp"] * 0.5, 1),
                "lot_size": ls, "lots": 1,
                "type": "PE SELL",
                "symbol": pe_sell["symbol"],
            },
            {
                "option_type": "PE", "action": "BUY",
                "strike": pe_buy["strike"], "delta": pe_buy["delta"],
                "premium": pe_buy["ltp"],
                "sl_level": None, "tp_level": None,
                "lot_size": ls, "lots": 1,
                "type": "PE BUY (Hedge)",
                "symbol": pe_buy["symbol"],
            },
        ]

        return {
            "legs":              legs,
            "net_credit":        round(nc, 2),
            "max_profit":        round(nc * ls, 0),   # 1-lot base; app.py × lots
            "max_loss":          round((max(ce_wing, pe_wing) - nc) * ls, 0),
            "breakeven_upper":   round(be_u, 0),
            "breakeven_lower":   round(be_d, 0),
            "margin_required":   round(max(ce_wing, pe_wing) * ls, 0),
            "spot_at_entry":     spot,
            "atr":               0,
            "strike_distance":   round(ce_sell["strike"] - spot, 0),
            # Chain metadata — shown in UI
            "scan_meta": {
                "ce_sell": ce_sell,
                "pe_sell": pe_sell,
                "ce_buy":  ce_buy,
                "pe_buy":  pe_buy,
                "expiry":  _expiry_str(expiry),
                "expiry_date_raw": expiry,
                "dte":     dte,
                "source":  "LIVE CHAIN",
            },
        }
