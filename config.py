"""
Raptor by Blackwater — Configuration
Secrets loaded from Streamlit secrets (cloud) or environment variables (local).
Never hardcode API keys here.
"""
import os

def _get_secret(key, default=""):
    """Read from Streamlit secrets first, then env vars, then default."""
    try:
        import streamlit as st
        return st.secrets.get(key, os.environ.get(key, default))
    except Exception:
        return os.environ.get(key, default)

# ─── BROKER ───────────────────────────────────
API_KEY      = _get_secret("KITE_API_KEY", "")
ACCESS_TOKEN = ""
BROKER       = "zerodha"

# ─── ACCOUNT ──────────────────────────────────
ACCOUNT_SIZE      = 1_000_000
MAX_LOSS_PCT      = 0.05
DAILY_KILL_PCT    = 0.02

# ─── STRATEGY ─────────────────────────────────
ATR_MULTIPLIER    = 1.2
ATR_PERIOD        = 14
SELL_DELTA        = 0.15
BUY_DELTA         = 0.10
SL_PCT            = 0.50
TP_PCT            = 0.50
DTE_TARGET        = 14
EXPIRY_WEEK       = "NEXT"

# ─── NIFTY ────────────────────────────────────
NIFTY_LOT_SIZE    = 65  # Sensibull-confirmed lot size for current weekly series
NIFTY_STRIKE_STEP = 50
SYMBOL            = "NIFTY"

# ─── EXECUTION ────────────────────────────────
ORDER_TYPE        = "LIMIT"
MAX_RETRIES       = 3
RETRY_DELAY_SEC   = 2
SLIPPAGE_THRESHOLD= 2.0

# ─── RISK ─────────────────────────────────────
MAX_MARGIN_UTILIZATION = 0.40
MAX_OPEN_POSITIONS     = 4
BID_ASK_SPREAD_MAX     = 5.0

# ─── PAPER TRADING ────────────────────────────
PAPER_MODE            = True
PAPER_FILL_DELAY_SEC  = 0.5

# ─── LOGGING ──────────────────────────────────
LOG_DIR   = "logs"
LOG_LEVEL = "INFO"
