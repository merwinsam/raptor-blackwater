"""
Raptor — Option Chain Scanner
Fetches live NIFTY option chain from Kite Connect and finds
strikes closest to target delta using real market Greeks.
"""

import math
import numpy as np
from datetime import date, datetime, timezone, timedelta
from typing import Optional


# ── Vol surface constants (calibrated to NSE NIFTY market data) ───────────────
# CE: roughly symmetric smile, peaks ~7% OTM
# PE: monotonically increasing reverse skew (India market characteristic)
_CE_MULTS = [1.00, 1.10, 1.18, 1.25, 1.30, 1.34, 1.37, 1.38, 1.35, 1.30, 1.25]
_PE_MULTS = [1.00, 1.15, 1.25, 1.38, 1.52, 1.68, 1.85, 2.05, 2.28, 2.55, 2.85]

def _vol_mult(otm_pct: float, opt_type: str) -> float:
    """Interpolated vol surface multiplier for given moneyness."""
    mults = _CE_MULTS if opt_type == "CE" else _PE_MULTS
    idx   = min(int(otm_pct), len(mults) - 2)
    frac  = otm_pct - idx
    return mults[idx] + frac * (mults[min(idx + 1, len(mults) - 1)] - mults[idx])

def _N(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def _bs_price(S, K, T, r, sigma, opt_type):
    if T <= 0:
        return max(S - K, 0) if opt_type == "CE" else max(K - S, 0)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type == "CE":
        return S * _N(d1) - K * math.exp(-r * T) * _N(d2)
    else:
        return K * math.exp(-r * T) * (1 - _N(d2)) - S * (1 - _N(d1))

def _bs_delta(spot: float, strike: float, tte: float,
              vix: float, option_type: str, r: float = 0.065) -> float:
    """
    Black-Scholes delta with NIFTY vol surface.
    Uses vix × moneyness_multiplier for realistic OTM delta estimates.
    """
    if tte <= 0:
        return 0.0
    otm_pct = abs(strike - spot) / spot * 100
    sigma   = (vix * _vol_mult(otm_pct, option_type)) / 100.0
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * tte) / (sigma * math.sqrt(tte))
    if option_type == "CE":
        return _N(d1)
    else:
        return _N(d1) - 1


def estimate_offline_prem(spot: float, strike: float, opt_type: str,
                           vix: float, dte: int, r: float = 0.065) -> float:
    """
    Offline premium estimator using BS with NIFTY vol surface.
    Only used when Kite is disconnected (paper mode / market closed).
    Calibrated: for VIX=14.5, 13 DTE, 6.8% OTM CE → ~₹18 (market shows ₹18.15).
    """
    T       = max(dte / 365.0, 1 / 365)
    otm_pct = abs(strike - spot) / spot * 100
    sigma   = (vix * _vol_mult(otm_pct, opt_type)) / 100.0
    p       = _bs_price(spot, strike, T, r, sigma, opt_type)
    return round(max(0.5, p), 1)


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
        """Fetch full NFO instrument dump from Kite (cached daily)."""
        import streamlit as st

        if self.kite is None or getattr(self.kite, "kite", None) is None:
            raise ValueError(
                "Kite session not initialized. "
                "Connect with a valid API key and access token first."
            )

        cache_key      = "_nfo_instruments_cache"
        cache_date_key = "_nfo_instruments_date"
        today          = date.today().isoformat()

        if (st.session_state.get(cache_date_key) == today
                and st.session_state.get(cache_key)):
            return st.session_state[cache_key]

        instruments = self.kite.kite.instruments("NFO")
        st.session_state[cache_key]      = instruments
        st.session_state[cache_date_key] = today
        return instruments

    def _get_expiry(self) -> date:
        """
        Get appropriate weekly Tuesday expiry.
        Rules (matching NSE / Sensibull behaviour):
          - If today's expiry has ≥ 3 DTE → use it
          - Otherwise use the following Tuesday
        This prevents picking an expiry that's about to expire today/tomorrow.
        """
        today       = date.today()
        wd          = today.weekday()  # 0=Mon … 6=Sun
        days_to_tue = (1 - wd) % 7
        this_tue    = today + timedelta(days=days_to_tue)

        # If this Tuesday is today (wd==1) or already passed, step forward
        if (this_tue - today).days < 3:
            this_tue += timedelta(weeks=1)

        return this_tue

    # ── Main scan ─────────────────────────────────────────────────────────────

    def scan(self,
             spot:       float,
             vix:        float,
             sell_delta: float = 0.15,
             buy_delta:  float = 0.10,
             sl_pct:     float = 0.50,
             lot_size:   int   = 65) -> dict:
        """
        Scan live option chain and return a complete condor structure
        with strikes chosen by delta proximity.
        """
        expiry = self._get_expiry()
        dte    = (expiry - date.today()).days
        tte    = dte / 365.0

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
        tokens  = [str(i["instrument_token"]) for i in nifty_opts]
        sym_map = {str(i["instrument_token"]): i for i in nifty_opts}

        quotes = {}
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
            q      = quotes.get(token, {})
            ltp    = (q.get("last_price") or q.get("ohlc", {}).get("close") or 0.0)
            greeks = q.get("greeks") or {}

            raw_delta = greeks.get("delta")
            if raw_delta is not None:
                delta = float(raw_delta)
            else:
                # Fallback: BS delta with vol surface
                delta = _bs_delta(spot, instr["strike"], tte,
                                  vix, instr["instrument_type"])

            if ltp < 0.5:
                continue

            chain.append({
                "strike":  instr["strike"],
                "type":    instr["instrument_type"],
                "ltp":     round(ltp, 2),
                "delta":   round(abs(delta), 4),
                "delta_raw": round(delta, 4),
                "token":   token,
                "symbol":  instr["tradingsymbol"],
                "liquid":  ltp >= 5.0,
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
            if not rows:
                raise ValueError("No liquid strikes found near target delta.")
            return min(rows, key=lambda r: abs(r["delta"] - target_delta))

        liquid_ce = [r for r in ce_chain if r["strike"] > spot and r.get("liquid")]
        liquid_pe = [r for r in pe_chain if r["strike"] < spot and r.get("liquid")]

        if not liquid_ce or not liquid_pe:
            raise ValueError(
                "Insufficient liquid strikes found. "
                "Market may be closed or option chain data unavailable."
            )

        ce_sell = closest(liquid_ce, sell_delta)
        pe_sell = closest(liquid_pe, sell_delta)

        ce_buy_candidates = [r for r in ce_chain if r["strike"] > ce_sell["strike"]]
        pe_buy_candidates = [r for r in pe_chain if r["strike"] < pe_sell["strike"]]

        if not ce_buy_candidates or not pe_buy_candidates:
            raise ValueError("Could not find hedge strikes beyond sell strikes.")

        ce_buy = closest(ce_buy_candidates, buy_delta)
        pe_buy = closest(pe_buy_candidates, buy_delta)

        # ── Step 5: Build condor dict ─────────────────────────────────────────
        ce_nc  = ce_sell["ltp"] - ce_buy["ltp"]   # CE wing net credit
        pe_nc  = pe_sell["ltp"] - pe_buy["ltp"]   # PE wing net credit
        nc     = ce_nc + pe_nc                     # total condor net credit
        ls     = int(lot_size)

        ce_wing = ce_buy["strike"]  - ce_sell["strike"]
        pe_wing = pe_sell["strike"] - pe_buy["strike"]

        # Max loss per wing = wing_width - that_wing_nc (not total nc)
        # For Iron Condor, broker blocks margin on the wider wing only
        ml_ce  = (ce_wing - ce_nc) * ls
        ml_pe  = (pe_wing - pe_nc) * ls
        ml     = max(ml_ce, ml_pe)                 # worst-case wing

        mp     = nc * ls
        be_u   = ce_sell["strike"] + nc
        be_d   = pe_sell["strike"] - nc

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
            "legs":            legs,
            "net_credit":      round(nc, 2),
            "max_profit":      round(mp, 0),
            "max_loss":        round(ml, 0),
            "breakeven_upper": round(be_u, 0),
            "breakeven_lower": round(be_d, 0),
            "margin_required": round(max(ce_wing, pe_wing) * ls, 0),
            "margin_per_lot":  round(max(ce_wing, pe_wing) * ls, 0),
            "wing_width":      max(ce_wing, pe_wing),
            "spot_at_entry":   spot,
            "atr":             0,
            "strike_distance": round(ce_sell["strike"] - spot, 0),
            "scan_meta": {
                "ce_sell":         ce_sell,
                "pe_sell":         pe_sell,
                "ce_buy":          ce_buy,
                "pe_buy":          pe_buy,
                "expiry":          _expiry_str(expiry),
                "expiry_date_raw": expiry,
                "dte":             dte,
                "source":          "LIVE CHAIN",
            },
        }
