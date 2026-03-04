"""
NIFTY Iron Condor Execution System
Professional Trading Dashboard | Zerodha Kite Connect
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
import plotly.graph_objects as go

from strategy.iron_condor import IronCondorStrategy
from strategy.spreads import BearCallSpread, BullPutSpread
from strategy.atr_model import ATRModel
from risk.risk_engine import RiskEngine
from execution.order_engine import OrderEngine
from broker.kite_client import KiteClient
from data.option_chain import OptionChainScanner
from data.persistence import (save_session, load_session, list_sessions,
                               update_pnl_history, load_pnl_history, total_pnl,
                               save_token, load_token)
from monitor.position_monitor import PositionMonitor
from utils.helpers import format_currency, format_pct
import config

# Auto-refresh: re-runs page every 60s when armed so 9:45 trigger fires
try:
    from streamlit_autorefresh import st_autorefresh
    _autorefresh_available = True
except ImportError:
    _autorefresh_available = False

st.set_page_config(
    page_title="Raptor by Blackwater",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
/* Floating sidebar open button — always visible bottom-left */
#sidebar-open-btn {
    position: fixed;
    left: 0;
    top: 50%;
    transform: translateY(-50%);
    z-index: 99999;
    background: #1D4ED8;
    color: #fff;
    border: none;
    border-radius: 0 8px 8px 0;
    width: 22px;
    height: 56px;
    cursor: pointer;
    font-size: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    writing-mode: vertical-rl;
    letter-spacing: 0.08em;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 9px;
    font-weight: 600;
    opacity: 0.85;
    transition: opacity 0.2s, width 0.2s;
}
#sidebar-open-btn:hover { opacity: 1; width: 26px; }
/* Hide button when sidebar is open */
[data-testid="stSidebar"][aria-expanded="true"] ~ * #sidebar-open-btn { display: none; }
</style>
<button id="sidebar-open-btn" onclick="
    const sidebar = window.parent.document.querySelector('[data-testid=stSidebar]');
    const btn = window.parent.document.querySelector('[data-testid=collapsedControl]');
    if (btn) btn.click();
" title="Open sidebar">☰</button>
<script>
// Auto-hide button when sidebar is visible
const checkSidebar = () => {
    const sidebar = window.parent.document.querySelector('[data-testid=stSidebar]');
    const btn = window.parent.document.getElementById('sidebar-open-btn');
    if (!sidebar || !btn) return;
    const expanded = sidebar.getAttribute('aria-expanded');
    btn.style.display = (expanded === 'false' || !expanded) ? 'flex' : 'none';
};
setInterval(checkSidebar, 500);
</script>
<style>
/* Also make Streamlit's own collapse arrow more visible */
[data-testid="collapsedControl"] {
    background: #1D4ED8 !important;
    border-radius: 0 8px 8px 0 !important;
    width: 20px !important;
    min-height: 56px !important;
    opacity: 1 !important;
    visibility: visible !important;
}
[data-testid="collapsedControl"] svg { fill: white !important; }
</style>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@300;400;500&display=swap');

*, *::before, *::after { box-sizing: border-box; }

html, body, .stApp {
    background-color: #080C10 !important;
    color: #C8D0D8 !important;
    font-family: 'IBM Plex Sans', sans-serif;
}

[data-testid="stSidebar"] {
    background-color: #0C1117 !important;
    border-right: 1px solid #1C2530 !important;
}
[data-testid="stSidebar"] * { color: #8A9BB0 !important; }
[data-testid="stSidebar"] label {
    font-size: 11px !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #4A5568 !important;
}

#MainMenu, footer, header { visibility: hidden; }
.block-container { padding: 1.5rem 2rem !important; max-width: 100% !important; }

h1, h2, h3 {
    font-family: 'IBM Plex Mono', monospace !important;
    font-weight: 500 !important;
    letter-spacing: -0.02em;
}

[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background: transparent !important;
    border-bottom: 1px solid #1C2530 !important;
    gap: 0 !important;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
    background: transparent !important;
    color: #4A5568 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 11px !important;
    font-weight: 500 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    padding: 10px 20px !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
}
[data-testid="stTabs"] [aria-selected="true"] {
    color: #E2E8F0 !important;
    border-bottom: 2px solid #3B82F6 !important;
    background: transparent !important;
}

[data-testid="stMetric"] {
    background: #0C1117 !important;
    border: 1px solid #1C2530 !important;
    border-radius: 4px !important;
    padding: 14px 16px !important;
}
[data-testid="stMetricLabel"] {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 10px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.1em !important;
    color: #4A5568 !important;
}
[data-testid="stMetricValue"] {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 22px !important;
    font-weight: 500 !important;
    color: #E2E8F0 !important;
}

.stButton > button {
    background: #0C1117 !important;
    color: #8A9BB0 !important;
    border: 1px solid #1C2530 !important;
    border-radius: 3px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 11px !important;
    font-weight: 500 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.08em !important;
    padding: 8px 16px !important;
    transition: all 0.15s ease !important;
}
.stButton > button:hover {
    background: #1C2530 !important;
    color: #E2E8F0 !important;
    border-color: #3B82F6 !important;
}
.stButton > button[kind="primary"] {
    background: #3B82F6 !important;
    color: #fff !important;
    border-color: #3B82F6 !important;
}
.stButton > button[kind="primary"]:hover {
    background: #2563EB !important;
}

.stNumberInput input, .stTextInput input {
    background: #0C1117 !important;
    border: 1px solid #1C2530 !important;
    border-radius: 3px !important;
    color: #C8D0D8 !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 13px !important;
}

hr { border-color: #1C2530 !important; margin: 1.5rem 0 !important; }

.stInfo, .stSuccess, .stWarning, .stError {
    border-radius: 3px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 12px !important;
}

.panel {
    background: #0C1117;
    border: 1px solid #1C2530;
    border-radius: 4px;
    padding: 20px;
    margin-bottom: 12px;
}
.panel-title {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: #4A5568;
    margin-bottom: 14px;
    padding-bottom: 10px;
    border-bottom: 1px solid #1C2530;
}
.leg-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 10px 0;
    border-bottom: 1px solid #111820;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
}
.leg-row:last-child { border-bottom: none; }
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 2px;
    font-size: 10px;
    font-family: 'IBM Plex Mono', monospace;
    font-weight: 600;
    letter-spacing: 0.06em;
}
.badge-sell   { background: rgba(239,68,68,0.15);  color: #EF4444; border: 1px solid rgba(239,68,68,0.3); }
.badge-buy    { background: rgba(59,130,246,0.15);  color: #3B82F6; border: 1px solid rgba(59,130,246,0.3); }
.badge-active { background: rgba(34,197,94,0.15);   color: #22C55E; border: 1px solid rgba(34,197,94,0.3); }
.badge-sl     { background: rgba(239,68,68,0.2);    color: #EF4444; border: 1px solid #EF4444; }
.badge-tp     { background: rgba(34,197,94,0.2);    color: #22C55E; border: 1px solid #22C55E; }
.badge-closed { background: rgba(100,116,139,0.2);  color: #64748B; border: 1px solid rgba(100,116,139,0.3); }

.status-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; margin-right: 6px; }
.dot-green  { background: #22C55E; box-shadow: 0 0 6px #22C55E; }
.dot-red    { background: #EF4444; box-shadow: 0 0 6px #EF4444; }
.dot-gray   { background: #4A5568; }

.mono       { font-family: 'IBM Plex Mono', monospace; }
.text-muted { color: #4A5568; font-size: 11px; }
.pnl-pos    { color: #22C55E; font-family: 'IBM Plex Mono', monospace; font-weight: 500; }
.pnl-neg    { color: #EF4444; font-family: 'IBM Plex Mono', monospace; font-weight: 500; }

.header-bar {
    display: flex;
    align-items: baseline;
    gap: 16px;
    margin-bottom: 24px;
    padding-bottom: 16px;
    border-bottom: 1px solid #1C2530;
}
.exec-status {
    background: #0C1117;
    border: 1px solid #1C2530;
    border-left: 3px solid #3B82F6;
    border-radius: 4px;
    padding: 12px 16px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    color: #8A9BB0;
    margin-bottom: 12px;
}
.exec-status.armed { border-left-color: #F59E0B; background: rgba(245,158,11,0.04); }
.exec-status.live  { border-left-color: #22C55E; background: rgba(34,197,94,0.04); }

.kill-btn > button {
    background: rgba(239,68,68,0.08) !important;
    color: #EF4444 !important;
    border: 1px solid rgba(239,68,68,0.3) !important;
}
.kill-btn > button:hover {
    background: rgba(239,68,68,0.18) !important;
    border-color: #EF4444 !important;
}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# RAPTOR LOGIN SYSTEM
# Credentials stored in .streamlit/secrets.toml — never in code
# ══════════════════════════════════════════════════════════════════════════════

def _get_users() -> dict:
    """
    Load users exclusively from Streamlit secrets.
    - Cloud:  Streamlit Cloud → Settings → Secrets
    - Local:  .streamlit/secrets.toml  (never committed — in .gitignore)
    No credentials are stored in code.
    """
    try:
        users = dict(st.secrets.get("users", {}))
        if users:
            return users
    except Exception:
        pass
    return {}

def _check_login():
    """
    Professional login screen — restrained, institutional aesthetic.
    """
    if st.session_state.get("authenticated"):
        return True

    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

    .stApp,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"] {
        background-color: #080B10 !important;
    }
    [data-testid="stHeader"]  { background: transparent !important; display: none !important; }
    [data-testid="stSidebar"] { display: none !important; }
    [data-testid="stDecoration"] { display: none !important; }

    .block-container {
        padding-top: 4rem !important;
        padding-bottom: 2rem !important;
        max-width: 420px !important;
    }

    /* Inputs */
    div[data-testid="stTextInput"] input {
        background: #0D1117 !important;
        border: 1px solid #1E2A38 !important;
        border-radius: 4px !important;
        color: #E2E8F0 !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 14px !important;
        font-weight: 400 !important;
        letter-spacing: 0.01em !important;
        padding: 10px 14px !important;
        transition: border-color 0.15s ease !important;
    }
    div[data-testid="stTextInput"] input:focus {
        border-color: #3B82F6 !important;
        box-shadow: 0 0 0 3px rgba(59,130,246,0.12) !important;
        outline: none !important;
    }
    div[data-testid="stTextInput"] input::placeholder {
        color: #334155 !important;
        font-weight: 300 !important;
    }
    div[data-testid="stTextInput"] label {
        font-family: 'Inter', sans-serif !important;
        font-size: 11px !important;
        font-weight: 500 !important;
        letter-spacing: 0.06em !important;
        color: #64748B !important;
        text-transform: uppercase !important;
        margin-bottom: 4px !important;
    }
    div[data-testid="stTextInput"] {
        margin-bottom: 4px !important;
    }

    /* Sign in button */
    div[data-testid="stButton"] > button[kind="primary"] {
        background: #1D4ED8 !important;
        border: none !important;
        border-radius: 4px !important;
        color: #FFFFFF !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 13px !important;
        font-weight: 500 !important;
        letter-spacing: 0.02em !important;
        padding: 11px 20px !important;
        width: 100% !important;
        transition: background 0.15s ease !important;
        margin-top: 8px !important;
    }
    div[data-testid="stButton"] > button[kind="primary"]:hover {
        background: #1E40AF !important;
    }
    div[data-testid="stButton"] > button[kind="primary"]:active {
        background: #1E3A8A !important;
    }

    /* Error message */
    div[data-testid="stAlert"] {
        background: rgba(239,68,68,0.08) !important;
        border: 1px solid rgba(239,68,68,0.2) !important;
        border-radius: 4px !important;
        color: #FCA5A5 !important;
        font-family: 'Inter', sans-serif !important;
        font-size: 12px !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # Wordmark
    st.markdown("""
    <div style="margin:48px 0 32px;text-align:center">
        <div style="font-family:'JetBrains Mono',monospace;font-size:11px;
                    font-weight:500;letter-spacing:0.18em;color:#3B82F6;
                    margin-bottom:14px;text-transform:uppercase">
            Blackwater
        </div>
        <div style="font-family:'Inter',sans-serif;font-size:28px;font-weight:600;
                    color:#F1F5F9;letter-spacing:-0.02em;margin-bottom:6px">
            Raptor
        </div>
        <div style="font-family:'Inter',sans-serif;font-size:13px;font-weight:300;
                    color:#475569;letter-spacing:0.01em">
            Algorithmic Options Trading Platform
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Card
    st.markdown("""
    <div style="background:#0D1117;border:1px solid #1E2A38;border-radius:8px;
                padding:28px 28px 24px;margin-bottom:2px">
        <div style="font-family:'Inter',sans-serif;font-size:15px;font-weight:500;
                    color:#E2E8F0;margin-bottom:4px">
            Sign in
        </div>
        <div style="font-family:'Inter',sans-serif;font-size:12px;font-weight:300;
                    color:#475569;margin-bottom:20px">
            Access is restricted to authorised accounts.
        </div>
    </div>
    """, unsafe_allow_html=True)

    username = st.text_input("Username", placeholder="Enter your username",
                              key="login_user", label_visibility="visible")
    password = st.text_input("Password", placeholder="Enter your password",
                              type="password", key="login_pass",
                              label_visibility="visible")

    if st.button("Sign in", use_container_width=True, type="primary"):
        users = _get_users()
        if not users:
            st.error("No credentials configured. Add a [users] section to .streamlit/secrets.toml")
        elif username in users and users[username] == password:
            st.session_state.authenticated = True
            st.session_state.current_user  = username
            st.rerun()
        else:
            st.error("Incorrect username or password. Please try again.")

    # Platform info strip
    st.markdown("""
    <div style="margin-top:28px;padding-top:20px;border-top:1px solid #0F1923;
                display:flex;justify-content:space-between;align-items:center">
        <div style="font-family:'JetBrains Mono',monospace;font-size:10px;
                    color:#1E3A5F;letter-spacing:0.08em">
            NSE · NIFTY · Weekly
        </div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:10px;
                    color:#1E3A5F;letter-spacing:0.08em">
            v1.0
        </div>
    </div>
    """, unsafe_allow_html=True)

    return False

# ── Gate: stop here if not logged in ──────────────────────────────────────────
if not _check_login():
    st.stop()

# ── Show logged-in user in sidebar ───────────────────────────────────────────
if st.session_state.get("current_user"):
    with st.sidebar:
        st.markdown(f"""
        <div style="font-family:'Share Tech Mono',monospace;font-size:9px;
                    letter-spacing:0.2em;color:#607888;margin-bottom:4px">PILOT</div>
        <div style="font-family:'Share Tech Mono',monospace;font-size:12px;
                    letter-spacing:0.1em;color:#E8A020;margin-bottom:8px">
            {st.session_state.current_user.upper()}
        </div>
        """, unsafe_allow_html=True)
        if st.button("Sign Out", use_container_width=True):
            for key in ["authenticated", "current_user"]:
                st.session_state.pop(key, None)
            st.rerun()

# ── Auto-refresh ──────────────────────────────────────────────────────────────

if _autorefresh_available:
    has_active = any(p.get("status") == "ACTIVE" for p in st.session_state.get("positions", []))
    if st.session_state.get("auto_execute_armed", False) or (has_active and st.session_state.get("kite_connected")):
        # 30s refresh when positions are live, 60s when just armed
        interval = 30_000 if has_active else 60_000
        st_autorefresh(interval=interval, key="autorefresh_main")
else:
    if st.session_state.get("auto_execute_armed", False):
        st.warning("Install streamlit-autorefresh: pip install streamlit-autorefresh", icon="⚠️")

# ── Session State ──────────────────────────────────────────────────────────────
def init_session():
    defaults = {
        "strategy_active": False,
        "paper_mode": True,
        "positions": [],
        "trade_log": [],
        "mtm_history": [],
        "account_size": 1_000_000,
        "daily_pnl": 0.0,
        "total_pnl": 0.0,
        "kill_switch": False,
        "kite_connected": False,
        "spot_price": 25000.0,
        "vix": 14.5,
        "atr": 0.0,
        "strategy_params": {},
        "order_log": [],
        "auto_execute_armed": False,
        "last_execution_date": None,
        "execution_time": "09:45",
        "exit_days_before_expiry": 4,
        "lot_size": config.NIFTY_LOT_SIZE,   # always seeds from config (65)
        "auto_lots": 1,
        "strategy_type": "Bear Call Spread",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session()

# Force lot_size to config value — overrides stale cached values from old sessions
st.session_state.lot_size = config.NIFTY_LOT_SIZE

# ── Auto-load token + session on startup ──────────────────────────────────────
if not st.session_state.get("_startup_done"):
    st.session_state._startup_done = True

    # Load today's token if saved
    saved_tok = load_token()
    if saved_tok and not st.session_state.kite_connected:
        try:
            from broker.kite_client import KiteClient
            client = KiteClient(saved_tok["api_key"], saved_tok["access_token"], paper_mode=True)
            result = client.test_connection()
            if result["success"]:
                st.session_state.kite_client    = client
                st.session_state.kite_connected = True
                st.session_state._saved_api_key = saved_tok["api_key"]
                st.session_state._saved_token   = saved_tok["access_token"]
                try:
                    st.session_state.spot_price = client.get_nifty_spot()
                    st.session_state.vix        = client.get_india_vix()
                except Exception:
                    pass
        except Exception:
            pass

    # Load today's session only — skip if cleared or from a previous date
    if not st.session_state.get("session_cleared"):
        from datetime import timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
        today_ist = datetime.now(timezone.utc).astimezone(IST).date().isoformat()
        session = load_session()
        # Only restore if session is from TODAY and not empty
        if (session
                and session.get("date") == today_ist
                and session.get("positions")
                and not st.session_state.positions):
            st.session_state.positions = session.get("positions", [])
            st.session_state.trade_log = session.get("trade_log", [])
            st.session_state.daily_pnl = session.get("daily_pnl", 0.0)
        # Load cumulative P&L
        st.session_state.total_pnl = total_pnl()


# ── Auto-execute helpers ───────────────────────────────────────────────────────
def _close_paired_hedge(positions: list, sell_leg: dict, reason: str):
    """
    When a SELL leg hits SL or TP, immediately close its paired BUY hedge.
    CE SELL → close CE BUY hedge
    PE SELL → close PE BUY hedge
    """
    side = sell_leg.get("option_type")  # "CE" or "PE"
    for pos in positions:
        if (pos.get("action") == "BUY"
                and pos.get("option_type") == side
                and pos.get("status") == "ACTIVE"):
            pos["status"] = "CLOSED"
            pos["exit_reason"] = f"Hedge closed — paired SELL {reason}"
            break  # only close the matching hedge


def get_ist_now():
    """Get current time in IST (UTC+5:30) regardless of local timezone."""
    from datetime import timezone, timedelta
    IST = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(timezone.utc).astimezone(IST)

def should_auto_execute():
    """Check execution window in IST time."""
    ist_now   = get_ist_now()
    ist_today = ist_now.date()
    h, m      = map(int, st.session_state.execution_time.split(":"))
    from datetime import timezone, timedelta
    IST       = timezone(timedelta(hours=5, minutes=30))
    w_start   = datetime(ist_today.year, ist_today.month, ist_today.day, h, m, 0,  tzinfo=IST)
    w_end     = datetime(ist_today.year, ist_today.month, ist_today.day, h, m, 59, tzinfo=IST)
    ran_today = st.session_state.last_execution_date == ist_today
    return w_start <= ist_now <= w_end and not ran_today

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<p class="panel-title">Connection</p>', unsafe_allow_html=True)
    api_key      = st.text_input("API Key",      value=config.API_KEY,  type="password")
    access_token = st.text_input("Access Token", type="password")

    col1, col2 = st.columns([2, 1])
    with col1:
        if st.button("Connect", use_container_width=True):
            with st.spinner(""):
                try:
                    client = KiteClient(api_key, access_token, paper_mode=st.session_state.paper_mode)
                    result = client.test_connection()
                    st.session_state.kite_connected = result["success"]
                    st.session_state.kite_client = client
                    if result["success"]:
                        # Save token to disk for auto-load tomorrow
                        save_token(api_key, access_token)
                        # Auto-fetch live spot and VIX on connect
                        try:
                            st.session_state.spot_price = client.get_nifty_spot()
                            st.session_state.vix        = client.get_india_vix()
                        except Exception:
                            pass
                    else:
                        st.error(result["message"])
                except Exception as e:
                    client = KiteClient(api_key, access_token, paper_mode=True)
                    st.session_state.kite_client = client
                    st.session_state.kite_connected = True
    with col2:
        if st.session_state.kite_connected:
            st.markdown('<span class="status-dot dot-green"></span>On',  unsafe_allow_html=True)
        else:
            st.markdown('<span class="status-dot dot-gray"></span>Off', unsafe_allow_html=True)

    st.divider()
    st.markdown('<p class="panel-title">Mode</p>', unsafe_allow_html=True)
    paper_mode = st.toggle("Paper Trading", value=True)
    st.session_state.paper_mode = paper_mode

    st.divider()
    st.markdown('<p class="panel-title">Account</p>', unsafe_allow_html=True)
    account_size   = st.number_input("Size (₹)", value=st.session_state.account_size,
                                      min_value=100000, max_value=50000000, step=100000)
    st.session_state.account_size = account_size
    max_loss_pct   = st.slider("Max Loss %",    1.0, 10.0, 5.0, 0.5)
    daily_kill_pct = st.slider("Daily Kill %",  0.5,  5.0, 2.0, 0.5)
    max_loss_amt   = account_size * max_loss_pct / 100

    st.divider()
    st.markdown('<p class="panel-title">Strategy</p>', unsafe_allow_html=True)

    strike_mode = st.radio(
        "Strike Selection Mode",
        ["Delta", "ATR"],
        horizontal=True,
        help="Delta: pick strikes by target delta from live chain. ATR: sell at 1×ATR, hedge 200pts further OTM.",
    )
    st.session_state.strike_mode = strike_mode

    atr_multiplier = st.number_input("ATR Multiplier",    value=1.25 if strike_mode == "ATR" else 1.2,
                                      min_value=0.5, max_value=3.0, step=0.05,
                                      help="ATR mode: sell strike = spot ± ATR × multiplier")
    if strike_mode == "Delta":
        sell_delta = st.number_input("Sell Delta", value=0.15, min_value=0.05, max_value=0.30, step=0.01)
        buy_delta  = st.number_input("Buy Delta",  value=0.10, min_value=0.03, max_value=0.20, step=0.01)
        hedge_pts  = None
    else:
        sell_delta = 0.15   # unused in ATR mode but kept for fallback
        buy_delta  = 0.10
        hedge_pts  = st.number_input("Hedge Distance (pts)", value=200, min_value=50, max_value=500, step=50,
                                      help="ATR mode: buy (hedge) strike is this many points further OTM from sell strike")
    sl_pct         = st.number_input("SL % of Premium",  value=50,   min_value=20,   max_value=100,  step=5)
    dte_target     = st.number_input("Target DTE",        value=14,   min_value=7,    max_value=30,   step=1)
    lot_size       = st.number_input("Lot Size",          value=config.NIFTY_LOT_SIZE, min_value=1, max_value=500, step=1,
                                      help="NIFTY lot size (NSE: 75 from Feb 2025). P&L = (price diff) × lots × lot size")
    st.session_state.lot_size = lot_size

    st.divider()
    st.markdown('<p class="panel-title">Schedule</p>', unsafe_allow_html=True)
    exec_time = st.text_input("Entry Time (HH:MM)", value="09:45")
    st.session_state.execution_time = exec_time
    exit_dte  = st.number_input("Exit Days Before Expiry", value=4, min_value=1, max_value=10, step=1)
    st.session_state.exit_days_before_expiry = exit_dte
    auto_lots = st.number_input("Auto Lots", value=1, min_value=1, max_value=20, step=1,
                                 help="Number of lots for auto-execute at scheduled time")
    st.session_state.auto_lots = auto_lots
    auto_arm  = st.toggle("Arm Auto-Execute", value=False)
    st.session_state.auto_execute_armed = auto_arm

    st.divider()
    st.markdown('<div class="kill-btn">', unsafe_allow_html=True)
    if st.button("KILL SWITCH", use_container_width=True):
        st.session_state.kill_switch = True
        st.session_state.strategy_active = False
    st.markdown('</div>', unsafe_allow_html=True)

    st.divider()
    st.markdown('<p class="panel-title">Session</p>', unsafe_allow_html=True)
    if st.button("New Session", use_container_width=True, help="Clear all positions, P&L and trade log for a fresh start"):
        # Overwrite disk files with blank data (works on Streamlit Cloud)
        try:
            import json
            from pathlib import Path
            from datetime import timezone, timedelta
            IST = timezone(timedelta(hours=5, minutes=30))
            today_ist = datetime.now(timezone.utc).astimezone(IST).date().isoformat()
            logs_dir = Path("logs")
            logs_dir.mkdir(exist_ok=True)
            # Overwrite today's session with empty data
            blank_session = {"date": today_ist, "saved_at": "", "daily_pnl": 0.0, "positions": [], "trade_log": []}
            with open(logs_dir / f"{today_ist}_session.json", "w") as f:
                json.dump(blank_session, f)
            # Overwrite pnl history with empty list
            with open(logs_dir / "pnl_history.json", "w") as f:
                json.dump([], f)
            # Also wipe any older session files
            for old_f in logs_dir.glob("*_session.json"):
                if old_f.name != f"{today_ist}_session.json":
                    old_f.unlink(missing_ok=True)
        except Exception:
            pass
        # Wipe all in-memory state
        keys_to_clear = [
            "positions", "trade_log", "daily_pnl", "total_pnl",
            "mtm_history", "strategy_active", "kill_switch",
            "last_execution_date", "_startup_done"
        ]
        for k in keys_to_clear:
            if k in st.session_state:
                del st.session_state[k]
        st.session_state.session_cleared = True
        st.success("Session cleared — fresh start.")
        st.rerun()

    st.session_state.strategy_params = {
        "atr_multiplier": atr_multiplier,
        "sell_delta":     sell_delta,
        "buy_delta":      buy_delta,
        "sl_pct":         sl_pct / 100,
        "dte_target":     dte_target,
        "max_loss_pct":   max_loss_pct / 100,
        "max_loss_amt":   max_loss_amt,
        "daily_kill_pct": daily_kill_pct / 100,
        "account_size":   account_size,
        "lot_size":       lot_size,
        "strike_mode":    strike_mode,
        "hedge_pts":      hedge_pts if hedge_pts else 200,
    }

# ── Header ─────────────────────────────────────────────────────────────────────
mode_label = "PAPER" if st.session_state.paper_mode else "LIVE"
mode_color = "#F59E0B" if st.session_state.paper_mode else "#EF4444"

# Dual clock — IST and local (EST)
from datetime import timezone, timedelta
IST         = timezone(timedelta(hours=5, minutes=30))
ist_now     = datetime.now(timezone.utc).astimezone(IST)
local_now   = datetime.now()
ist_str     = ist_now.strftime("%d %b %Y  %H:%M:%S IST")
local_str   = local_now.strftime("%H:%M:%S EST")

# Market status
market_open  = ist_now.weekday() < 5 and (
    (ist_now.hour == 9 and ist_now.minute >= 15) or
    (10 <= ist_now.hour <= 14) or
    (ist_now.hour == 15 and ist_now.minute <= 30)
)
mkt_color  = "#22C55E" if market_open else "#4A5568"
mkt_label  = "MARKET OPEN" if market_open else "MARKET CLOSED"

st.markdown(f"""
<div class="header-bar">
    <span style="font-family:'IBM Plex Mono',monospace;font-size:18px;font-weight:500;color:#E2E8F0;">
        RAPTOR BY BLACKWATER
    </span>
    <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#4A5568;letter-spacing:0.1em;">
        OPTIONS EXECUTION DESK
    </span>
    <span style="margin-left:auto;font-family:'IBM Plex Mono',monospace;font-size:10px;
                 color:{mkt_color};letter-spacing:0.08em;border:1px solid {mkt_color};
                 padding:2px 8px;border-radius:2px;">
        {mkt_label}
    </span>
    <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;
                 color:{mode_color};letter-spacing:0.1em;border:1px solid {mode_color};
                 padding:2px 8px;border-radius:2px;">
        {mode_label}
    </span>
    <span style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:#8A9BB0;">
        {ist_str}
    </span>
    <span style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:#4A5568;">
        {local_str}
    </span>
</div>
""", unsafe_allow_html=True)

if st.session_state.kill_switch:
    st.error("KILL SWITCH ACTIVE — All trading halted.")
    if st.button("Reset Kill Switch"):
        st.session_state.kill_switch = False
        st.rerun()

# ── Auto-execute trigger ───────────────────────────────────────────────────────
params = st.session_state.strategy_params

if st.session_state.auto_execute_armed and not st.session_state.kill_switch:
    if should_auto_execute():
        atr_mdl      = ATRModel()
        spot         = st.session_state.spot_price
        atr          = atr_mdl.compute_atr_from_vix(spot, st.session_state.vix)
        auto_lots    = st.session_state.get("auto_lots", 1)
        auto_lot_sz  = st.session_state.get("lot_size", config.NIFTY_LOT_SIZE)
        params["lot_size"] = auto_lot_sz
        strat        = IronCondorStrategy(params)

        # Use scanned condor if available, else ATR model
        if st.session_state.get("_scanned_condor"):
            condor     = st.session_state["_scanned_condor"]
            expiry_raw = condor["scan_meta"]["expiry_date_raw"]
        else:
            condor     = strat.build_condor(spot, atr, vix=st.session_state.vix,
                                            kite_client=st.session_state.get("kite_client"))
            expiry_raw = strat.get_next_week_expiry()["expiry_date_raw"]

        risk  = RiskEngine(params)
        check = risk.pre_trade_check(condor, auto_lots, st.session_state.daily_pnl, account_size)
        if check["approved"]:
            engine = OrderEngine(paper_mode=st.session_state.paper_mode)
            result = engine.place_iron_condor(condor, auto_lots)
            if result["success"]:
                for pos in result["positions"]:
                    pos["status"]          = "ACTIVE"
                    pos["expiry_date_raw"] = expiry_raw
                    pos["lot_size"]        = auto_lot_sz
                st.session_state.positions.extend(result["positions"])
                st.session_state.last_execution_date = get_ist_now().date()
                st.session_state.strategy_active     = True
                st.session_state.trade_log.append({
                    "time":    datetime.now().strftime("%H:%M:%S"),
                    "date":    get_ist_now().date().isoformat(),
                    "action":  "AUTO ENTRY",
                    "details": f"Iron Condor @ {exec_time} · {auto_lots} lot(s) · Credit ₹{condor['net_credit']:.1f}",
                    "pnl":     0,
                    "status":  "FILLED",
                })

# ── Auto-fetch spot + VIX + LTPs on every refresh when connected ─────────────
kite_client_live = st.session_state.get("kite_client")
if kite_client_live and st.session_state.get("kite_connected"):
    try:
        st.session_state.spot_price = kite_client_live.get_nifty_spot()
        st.session_state.vix        = kite_client_live.get_india_vix()
    except Exception:
        pass
    # Auto-update LTPs for active positions
    active_live = [p for p in st.session_state.positions if p.get("status") == "ACTIVE"]
    if active_live:
        try:
            symbols = [f"NFO:{p['symbol']}" for p in active_live if p.get("symbol")]
            if symbols:
                quotes = kite_client_live.ltp(symbols)
                total_mtm = 0
                for pos in active_live:
                    key = f"NFO:{pos['symbol']}"
                    if key in quotes:
                        price = quotes[key]["last_price"]
                        if price > 1:
                            pos["ltp"] = price
                            if pos.get("action") == "SELL":
                                sl = pos.get("sl_level") or 999999
                                tp = pos.get("tp_level") or 0
                                if tp > 0 and price <= tp:
                                    pos["status"] = "TP_HIT"
                                    # Close paired BUY hedge on same side
                                    _close_paired_hedge(st.session_state.positions, pos, "TP_HIT")
                                elif sl < 999999 and price >= sl:
                                    pos["status"] = "SL_HIT"
                                    # Close paired BUY hedge on same side
                                    _close_paired_hedge(st.session_state.positions, pos, "SL_HIT")
                for p in st.session_state.positions:
                    entry  = p.get("entry_price", 0)
                    ltp_p  = p.get("ltp", entry)
                    action = p.get("action", "SELL")
                    pnl    = ((entry - ltp_p) if action == "SELL" else (ltp_p - entry)) * p.get("lots", 1) * p.get("lot_size", 50)
                    total_mtm += pnl
                st.session_state.daily_pnl = total_mtm
                st.session_state.mtm_history.append({"time": datetime.now(), "pnl": total_mtm})
                st.session_state.last_ltp_refresh = datetime.now().strftime("%H:%M:%S")
                # Persist to disk
                save_session(st.session_state.positions, st.session_state.trade_log, total_mtm)
                update_pnl_history(total_mtm)
        except Exception:
            pass

# ── DTE-based auto-exit ────────────────────────────────────────────────────────
for pos in st.session_state.positions:
    if pos.get("status") == "ACTIVE":
        expiry = pos.get("expiry_date_raw")
        if isinstance(expiry, date):
            dte = (expiry - get_ist_now().date()).days
            if dte <= st.session_state.exit_days_before_expiry:
                pos["status"]      = "CLOSED"
                pos["exit_reason"] = f"DTE ≤ {st.session_state.exit_days_before_expiry}"
                st.session_state.trade_log.append({
                    "time":    datetime.now().strftime("%H:%M:%S"),
                    "date":    get_ist_now().date().isoformat(),
                    "action":  "AUTO EXIT",
                    "details": f"{pos.get('symbol')} — DTE exit ({dte}d left)",
                    "pnl":     0,
                    "status":  "CLOSED",
                })
                save_session(st.session_state.positions, st.session_state.trade_log, st.session_state.daily_pnl)

# ── Tabs ───────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["OVERVIEW", "STRATEGY", "POSITIONS", "LOG"])

# ══════════════════════════════════════════════════════════════════════════════
# OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Daily P&L",
              format_currency(st.session_state.daily_pnl),
              delta=format_pct(st.session_state.daily_pnl / account_size))
    c2.metric("Total P&L",  format_currency(st.session_state.total_pnl))
    c3.metric("NIFTY Spot", f"₹{st.session_state.spot_price:,.0f}")
    c4.metric("India VIX",  f"{st.session_state.vix:.2f}")
    active_ct = len([p for p in st.session_state.positions if p.get("status") == "ACTIVE"])
    c5.metric("Active Legs", active_ct)

    st.markdown("<br>", unsafe_allow_html=True)
    col_l, col_r = st.columns([3, 1])

    with col_l:
        if st.session_state.mtm_history:
            df_mtm   = pd.DataFrame(st.session_state.mtm_history)
            last_val = df_mtm["pnl"].iloc[-1]
        else:
            x = pd.date_range(datetime.now(), periods=60, freq="1min")
            y = np.cumsum(np.random.randn(60) * 400)
            df_mtm   = pd.DataFrame({"time": x, "pnl": y})
            last_val = 0

        line_col = "#22C55E" if last_val >= 0 else "#EF4444"
        fill_col = "rgba(34,197,94,0.06)" if last_val >= 0 else "rgba(239,68,68,0.06)"

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_mtm["time"], y=df_mtm["pnl"],
            fill="tozeroy", fillcolor=fill_col,
            line=dict(color=line_col, width=1.5),
            hovertemplate="₹%{y:,.0f}<extra></extra>",
        ))
        fig.add_hline(y=0, line=dict(color="#1C2530", width=1, dash="dot"))
        fig.add_hline(y=-max_loss_amt,
                      line=dict(color="rgba(239,68,68,0.4)", width=1, dash="dash"),
                      annotation_text=f"Max Loss  ₹{max_loss_amt:,.0f}",
                      annotation_font=dict(color="#EF4444", size=10))
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0C1117", plot_bgcolor="#0C1117",
            height=280, margin=dict(l=0, r=0, t=20, b=0),
            showlegend=False,
            xaxis=dict(showgrid=False, zeroline=False,
                       tickfont=dict(family="IBM Plex Mono", size=10, color="#4A5568")),
            yaxis=dict(showgrid=True, gridcolor="#111820", zeroline=False,
                       tickfont=dict(family="IBM Plex Mono", size=10, color="#4A5568"),
                       tickprefix="₹"),
        )
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    with col_r:
        h, m      = map(int, st.session_state.execution_time.split(":"))
        from datetime import timezone, timedelta
        IST_tz    = timezone(timedelta(hours=5, minutes=30))
        ist_cur   = datetime.now(timezone.utc).astimezone(IST_tz)
        ist_today = ist_cur.date()
        next_exec_ist = datetime(ist_today.year, ist_today.month, ist_today.day,
                                  h, m, 0, tzinfo=IST_tz)
        mins_to   = max(0, int((next_exec_ist - ist_cur).total_seconds() / 60))
        # Convert next execution to local time for display
        next_exec_local = next_exec_ist.astimezone().strftime("%I:%M %p")
        armed     = st.session_state.auto_execute_armed

        sc   = "armed" if armed else ""
        stxt  = f"ARMED · {st.session_state.execution_time} IST ({next_exec_local} EST)" if armed else f"SCHEDULED · {st.session_state.execution_time} IST ({next_exec_local} EST)"
        stxt2 = f"{mins_to} min to execution (IST)" if armed else "Auto-execute not armed"

        st.markdown(f"""
        <div class="exec-status {sc}">
            <div style="color:#C8D0D8;margin-bottom:4px;">{stxt}</div>
            <div class="text-muted">{stxt2}</div>
        </div>
        <div class="exec-status">
            <div style="color:#C8D0D8;margin-bottom:4px;">EXIT RULE</div>
            <div class="text-muted">DTE ≤ {st.session_state.exit_days_before_expiry} days</div>
            <div class="text-muted">or SL / TP hit per leg</div>
        </div>
        """, unsafe_allow_html=True)

        used    = min(abs(st.session_state.daily_pnl) / max_loss_amt * 100, 100) if max_loss_amt else 0
        bar_col = "#22C55E" if used < 40 else "#F59E0B" if used < 70 else "#EF4444"
        st.markdown(f"""
        <div class="panel" style="margin-top:0">
            <div class="panel-title">Risk Usage</div>
            <div style="font-family:'IBM Plex Mono',monospace;font-size:22px;
                        color:{bar_col};margin-bottom:10px;">{used:.1f}%</div>
            <div style="background:#111820;border-radius:2px;height:4px;width:100%;">
                <div style="background:{bar_col};height:4px;border-radius:2px;width:{used}%;"></div>
            </div>
            <div style="display:flex;justify-content:space-between;margin-top:6px;">
                <span class="text-muted">₹0</span>
                <span class="text-muted">₹{max_loss_amt:,.0f}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    if st.session_state.paper_mode:
        st.divider()
        st.markdown('<p class="panel-title">Market Data</p>', unsafe_allow_html=True)
        if st.session_state.get("kite_connected"):
            st.markdown(f"""
            <div class="exec-status live">
                <div style="color:#C8D0D8;margin-bottom:4px;">AUTO-FETCHING FROM KITE</div>
                <div class="text-muted">NIFTY Spot: ₹{st.session_state.spot_price:,.0f} &nbsp;·&nbsp; VIX: {st.session_state.vix:.2f}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            mc1, mc2 = st.columns(2)
            with mc1:
                new_spot = st.number_input("NIFTY Spot", value=st.session_state.spot_price, step=10.0)
                st.session_state.spot_price = new_spot
            with mc2:
                new_vix = st.number_input("India VIX", value=st.session_state.vix, step=0.1)
                st.session_state.vix = new_vix

# ══════════════════════════════════════════════════════════════════════════════
# STRATEGY
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    atr_mdl = ATRModel()
    spot    = st.session_state.spot_price
    vix     = st.session_state.vix
    atr     = atr_mdl.compute_atr_from_vix(spot, vix)
    st.session_state.atr = atr
    params["lot_size"] = st.session_state.get("lot_size", config.NIFTY_LOT_SIZE)

    # ── Strategy Selector ─────────────────────────────────────────────────────
    st.markdown('<p class="panel-title">Strategy</p>', unsafe_allow_html=True)
    strategy_type = st.radio(
        "Select strategy",
        ["Bear Call Spread", "Bull Put Spread", "Iron Condor"],
        horizontal=True,
        label_visibility="collapsed",
        key="strategy_type_radio",
    )
    st.session_state.strategy_type = strategy_type
    st.divider()

    strat = IronCondorStrategy(params)

    # ── Option Chain Scanner ──────────────────────────────────────────────────
    kite_client_ref = st.session_state.get("kite_client")
    is_connected    = st.session_state.get("kite_connected") and kite_client_ref

    scan_col1, scan_col2 = st.columns([3, 1])
    with scan_col1:
        st.markdown("""
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">
            <span style="font-size:11px;letter-spacing:0.08em;color:#94A3B8;font-weight:500">
                STRIKE SELECTION
            </span>
            <span style="font-size:10px;color:#475569;letter-spacing:0.06em" id="chain-src">
                {} source
            </span>
        </div>
        """.format("LIVE CHAIN" if is_connected else "ATR MODEL"), unsafe_allow_html=True)
    with scan_col2:
        scan_clicked = st.button(
            "⟳ Scan Chain" if is_connected else "⟳ Recalculate",
            use_container_width=True,
            help="Scan live option chain and auto-fill strikes by delta" if is_connected
                 else "Connect to Kite for live chain scanning",
            type="primary"
        )

    # ── Run scan or use cached result ─────────────────────────────────────────
    scan_error = None
    if scan_clicked and is_connected:
        with st.spinner("Scanning option chain..."):
            try:
                scanner = OptionChainScanner(kite_client_ref)
                scanned = scanner.scan(
                    spot       = spot,
                    vix        = vix,
                    sell_delta = params.get("sell_delta", 0.15),
                    buy_delta  = params.get("buy_delta",  0.10),
                    sl_pct     = params.get("sl_pct",     0.50),
                    lot_size   = st.session_state.get("lot_size", config.NIFTY_LOT_SIZE),
                )
                st.session_state._scanned_condor = scanned
                st.success(
                    f"Chain scanned — "
                    f"CE {scanned['scan_meta']['ce_sell']['strike']} "
                    f"({scanned['scan_meta']['ce_sell']['delta']:.2f}Δ)  |  "
                    f"PE {scanned['scan_meta']['pe_sell']['strike']} "
                    f"({scanned['scan_meta']['pe_sell']['delta']:.2f}Δ)"
                )
            except Exception as e:
                scan_error = str(e)
                st.warning(f"Chain scan failed — using ATR model. ({e})")
                st.session_state._scanned_condor = None

    # ── Build strategy from scan or ATR model ────────────────────────────────
    scanned      = st.session_state.get("_scanned_condor") if not scan_error else None
    current_lot_size = st.session_state.get("lot_size", config.NIFTY_LOT_SIZE)

    if scanned:
        # Show live chain badge
        st.markdown("""
        <div style="display:inline-flex;align-items:center;gap:6px;
                    background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2);
                    border-radius:4px;padding:4px 10px;margin-bottom:12px">
            <span style="width:6px;height:6px;border-radius:50%;
                         background:#22C55E;display:inline-block"></span>
            <span style="font-size:10px;color:#22C55E;letter-spacing:0.1em;font-weight:500">
                LIVE CHAIN · DELTA-SELECTED
            </span>
        </div>
        """, unsafe_allow_html=True)

        # Delta confirmation table — filter rows by strategy
        meta = scanned["scan_meta"]
        if strategy_type == "Bear Call Spread":
            chain_rows = [
                {"Leg": "CE SELL", "Strike": meta["ce_sell"]["strike"],
                 "Delta": f"{meta['ce_sell']['delta']:.3f}Δ", "LTP": f"₹{meta['ce_sell']['ltp']:.1f}"},
                {"Leg": "CE BUY",  "Strike": meta["ce_buy"]["strike"],
                 "Delta": f"{meta['ce_buy']['delta']:.3f}Δ",  "LTP": f"₹{meta['ce_buy']['ltp']:.1f}"},
            ]
        elif strategy_type == "Bull Put Spread":
            chain_rows = [
                {"Leg": "PE SELL", "Strike": meta["pe_sell"]["strike"],
                 "Delta": f"{meta['pe_sell']['delta']:.3f}Δ", "LTP": f"₹{meta['pe_sell']['ltp']:.1f}"},
                {"Leg": "PE BUY",  "Strike": meta["pe_buy"]["strike"],
                 "Delta": f"{meta['pe_buy']['delta']:.3f}Δ",  "LTP": f"₹{meta['pe_buy']['ltp']:.1f}"},
            ]
        else:
            chain_rows = [
                {"Leg": "CE SELL", "Strike": meta["ce_sell"]["strike"],
                 "Delta": f"{meta['ce_sell']['delta']:.3f}Δ", "LTP": f"₹{meta['ce_sell']['ltp']:.1f}"},
                {"Leg": "CE BUY",  "Strike": meta["ce_buy"]["strike"],
                 "Delta": f"{meta['ce_buy']['delta']:.3f}Δ",  "LTP": f"₹{meta['ce_buy']['ltp']:.1f}"},
                {"Leg": "PE SELL", "Strike": meta["pe_sell"]["strike"],
                 "Delta": f"{meta['pe_sell']['delta']:.3f}Δ", "LTP": f"₹{meta['pe_sell']['ltp']:.1f}"},
                {"Leg": "PE BUY",  "Strike": meta["pe_buy"]["strike"],
                 "Delta": f"{meta['pe_buy']['delta']:.3f}Δ",  "LTP": f"₹{meta['pe_buy']['ltp']:.1f}"},
            ]
        st.dataframe(pd.DataFrame(chain_rows), use_container_width=True,
                     hide_index=True, height=140 if strategy_type != "Iron Condor" else 178)

    # ── Instantiate strategy ──────────────────────────────────────────────────
    _base_expiry = strat.get_next_week_expiry()
    _scan_expiry = {
        "expiry_date":     scanned["scan_meta"]["expiry"]          if scanned else _base_expiry["expiry_date"],
        "expiry_date_raw": scanned["scan_meta"]["expiry_date_raw"] if scanned else _base_expiry["expiry_date_raw"],
        "dte":             scanned["scan_meta"]["dte"]             if scanned else _base_expiry["dte"],
    }

    if strategy_type == "Bear Call Spread":
        spread_obj = BearCallSpread(params)
        trade      = spread_obj.build(spot, atr, vix,
                                      kite_client=kite_client_ref,
                                      chain_data=scanned)
        expiry     = _scan_expiry
        payoff_fn  = spread_obj.compute_payoff

    elif strategy_type == "Bull Put Spread":
        spread_obj = BullPutSpread(params)
        trade      = spread_obj.build(spot, atr, vix,
                                      kite_client=kite_client_ref,
                                      chain_data=scanned)
        expiry     = _scan_expiry
        payoff_fn  = spread_obj.compute_payoff

    else:  # Iron Condor
        if scanned:
            trade  = scanned
            expiry = {"expiry_date":     scanned["scan_meta"]["expiry"],
                      "expiry_date_raw": scanned["scan_meta"]["expiry_date_raw"],
                      "dte":             scanned["scan_meta"]["dte"]}
        else:
            trade  = strat.build_condor(spot, atr, vix, kite_client=kite_client_ref)
            expiry = strat.get_next_week_expiry()
        payoff_fn = strat.compute_payoff

    st.divider()

    col_l, col_r = st.columns([3, 2])

    with col_l:
        strikes = np.arange(spot - 2000, spot + 2000, 25)
        payoff  = payoff_fn(strikes, trade)

        fig2 = go.Figure()
        pm = payoff >= 0
        fig2.add_trace(go.Scatter(
            x=strikes[pm], y=payoff[pm], fill="tozeroy",
            fillcolor="rgba(34,197,94,0.08)",
            line=dict(color="#22C55E", width=1.5), showlegend=False,
            hovertemplate="NIFTY %{x:,.0f} → ₹%{y:,.0f}<extra></extra>",
        ))
        fig2.add_trace(go.Scatter(
            x=strikes[~pm], y=payoff[~pm], fill="tozeroy",
            fillcolor="rgba(239,68,68,0.08)",
            line=dict(color="#EF4444", width=1.5), showlegend=False,
            hovertemplate="NIFTY %{x:,.0f} → ₹%{y:,.0f}<extra></extra>",
        ))
        fig2.add_vline(x=spot, line=dict(color="#4A5568", width=1, dash="dot"),
                       annotation_text=f"  {spot:,.0f}",
                       annotation_font=dict(color="#8A9BB0", size=10))
        for leg in trade["legs"]:
            c = "#EF4444" if leg["action"] == "SELL" else "#3B82F6"
            fig2.add_vline(x=leg["strike"], line=dict(color=c, width=1, dash="dot"), opacity=0.5)
        fig2.add_hline(y=0, line=dict(color="#1C2530", width=1))
        fig2.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0C1117", plot_bgcolor="#0C1117",
            height=260, margin=dict(l=0, r=0, t=30, b=0), showlegend=False,
            title=dict(text=f"Payoff at Expiry — {strategy_type}",
                       font=dict(family="IBM Plex Mono", size=11, color="#4A5568"), x=0),
            xaxis=dict(showgrid=False,
                       tickfont=dict(family="IBM Plex Mono", size=10, color="#4A5568")),
            yaxis=dict(showgrid=True, gridcolor="#111820", zeroline=False,
                       tickfont=dict(family="IBM Plex Mono", size=10, color="#4A5568"),
                       tickprefix="₹"),
        )
        st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

        st.markdown('<p class="panel-title">Legs</p>', unsafe_allow_html=True)
        rows = []
        for leg in trade["legs"]:
            rows.append({
                "Instrument": leg["symbol"],
                "Side":       leg["action"],
                "Strike":     f"{leg['strike']:,}",
                "Delta":      f"{leg['delta']:.2f}",
                "Premium":    f"₹{leg['premium']:.1f}",
                "SL":         f"₹{leg['sl_level']:.1f}" if leg.get("sl_level") else "—",
                "TP":         f"₹{leg['tp_level']:.1f}" if leg.get("tp_level") else "—",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=175)

    with col_r:
        nc   = trade.get("net_credit", 0)
        mp   = trade.get("max_profit", 0)
        ml   = trade.get("max_loss",   0)
        be_u = trade.get("breakeven_upper", 0)
        be_d = trade.get("breakeven_lower", 0)
        wing = trade.get("wing_width", 0)
        mpl  = trade.get("margin_per_lot", wing * current_lot_size if wing else 0)

        if not st.session_state.kill_switch:
            lots = st.number_input("Lots", value=1, min_value=1, max_value=20)
        else:
            lots = 1

        mp_total  = mp * lots
        ml_total  = ml * lots
        margin_total = mpl * lots

        # ── Summary panel ─────────────────────────────────────────────────────
        # Strategy-specific breakeven display
        if strategy_type == "Bear Call Spread":
            be_html = f"<div class='leg-row'><span class='text-muted'>BREAKEVEN</span><span class='mono'>{be_u:,.0f}</span></div>"
            profit_range_html = ""
        elif strategy_type == "Bull Put Spread":
            be_html = f"<div class='leg-row'><span class='text-muted'>BREAKEVEN</span><span class='mono'>{be_d:,.0f}</span></div>"
            profit_range_html = ""
        else:
            be_html = (
                f"<div class='leg-row'><span class='text-muted'>BREAKEVEN UP</span><span class='mono'>{be_u:,.0f}</span></div>"
                f"<div class='leg-row'><span class='text-muted'>BREAKEVEN DN</span><span class='mono'>{be_d:,.0f}</span></div>"
            )
            profit_range_html = f"<div class='leg-row'><span class='text-muted'>PROFIT RANGE</span><span class='mono'>{be_u - be_d:,.0f} pts</span></div>"

        rr = f"{ml_total/mp_total:.1f}x" if mp_total else "—"
        lots_label = f"{lots} lot{'s' if lots > 1 else ''}"

        st.markdown(
            "<div class='panel'>"
            f"<div class='panel-title'>{strategy_type} &middot; {lots_label} &times; {current_lot_size}</div>"
            f"<div class='leg-row'><span class='text-muted'>NET CREDIT</span>"
            f"<span class='mono' style='color:#22C55E'>&#8377;{nc:.1f}/unit"
            f"<span style='color:#4A5568;font-size:11px'> &times; {lots} &times; {current_lot_size}</span></span></div>"
            f"<div class='leg-row'><span class='text-muted'>MAX PROFIT</span>"
            f"<span class='mono' style='color:#22C55E'>&#8377;{mp_total:,.0f}</span></div>"
            f"<div class='leg-row'><span class='text-muted'>MAX LOSS</span>"
            f"<span class='mono' style='color:#EF4444'>&#8377;{ml_total:,.0f}</span></div>"
            + be_html
            + profit_range_html
            + f"<div class='leg-row'><span class='text-muted'>R / R</span>"
            f"<span class='mono'>{rr}</span></div>"
            "</div>",
            unsafe_allow_html=True,
        )

        other_html = f"""
        <div class="panel">
            <div class="panel-title">Margin</div>
            <div class="leg-row"><span class="text-muted">PER LOT</span>
                <span class="mono">&#8377;{mpl:,.0f}</span></div>
            <div class="leg-row"><span class="text-muted">TOTAL ({lots} lots)</span>
                <span class="mono" style="color:#F59E0B">&#8377;{margin_total:,.0f}</span></div>
            <div class="leg-row"><span class="text-muted">BASIS</span>
                <span class="mono" style="font-size:10px">Wing &times; Lot size (SPAN)</span></div>
        </div>
        <div class="panel">
            <div class="panel-title">Expiry</div>
            <div class="leg-row"><span class="text-muted">DATE</span>
                <span class="mono">{expiry['expiry_date']}</span></div>
            <div class="leg-row"><span class="text-muted">DTE</span>
                <span class="mono">{expiry['dte']} days</span></div>
            <div class="leg-row"><span class="text-muted">EXIT TRIGGER</span>
                <span class="mono">DTE &le; {st.session_state.exit_days_before_expiry}</span></div>
        </div>
        <div class="panel">
            <div class="panel-title">Strike Selection</div>
            <div class="leg-row"><span class="text-muted">ATR (14D)</span>
                <span class="mono">{atr:.0f} pts</span></div>
            <div class="leg-row"><span class="text-muted">MULTIPLIER</span>
                <span class="mono">{params.get('atr_multiplier', 1.2):.1f}&times;</span></div>
            <div class="leg-row"><span class="text-muted">DISTANCE</span>
                <span class="mono">{atr * params.get('atr_multiplier', 1.2):.0f} pts</span></div>
        </div>
        """
        st.markdown(other_html, unsafe_allow_html=True)

        if not st.session_state.kill_switch:
            # Risk check
            risk_engine   = RiskEngine(params)
            check_preview = risk_engine.pre_trade_check(trade, lots, st.session_state.daily_pnl, account_size)
            if not check_preview["approved"]:
                st.warning(f"⚠ {check_preview['reason']}", icon=None)
                override_risk = st.checkbox("Override risk check and place anyway",
                                            value=False, key="risk_override")
            else:
                override_risk = False

            btn_label = f"Place {strategy_type}"
            if st.button(btn_label, type="primary", use_container_width=True):
                if check_preview["approved"] or override_risk:
                    engine = OrderEngine(paper_mode=st.session_state.paper_mode)
                    result = engine.place_iron_condor(trade, lots)
                    if result["success"]:
                        expiry_raw = expiry["expiry_date_raw"]
                        for pos in result["positions"]:
                            pos["status"]          = "ACTIVE"
                            pos["expiry_date_raw"] = expiry_raw
                            pos["lot_size"]        = current_lot_size
                            pos["strategy"]        = strategy_type
                        st.session_state.positions.extend(result["positions"])
                        st.session_state.strategy_active = True
                        tag = "MANUAL ENTRY" + (" [RISK OVERRIDE]" if override_risk else "")
                        st.session_state.trade_log.append({
                            "time":    datetime.now().strftime("%H:%M:%S"),
                            "date":    get_ist_now().date().isoformat(),
                            "action":  tag,
                            "details": f"{strategy_type} · {lots} lot(s) · Credit ₹{nc:.1f}",
                            "pnl": 0, "status": "FILLED",
                        })
                        save_session(st.session_state.positions, st.session_state.trade_log,
                                     st.session_state.daily_pnl)
                        st.success(f"Placed — {len(result['positions'])} legs active")
                        st.rerun()
                    else:
                        st.error(result["message"])
                else:
                    st.error(check_preview["reason"])

# ══════════════════════════════════════════════════════════════════════════════
# POSITIONS
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    if not st.session_state.positions:
        st.markdown('<div class="panel"><span class="text-muted">No positions.</span></div>',
                    unsafe_allow_html=True)
    else:
        active_pos = [p for p in st.session_state.positions if p.get("status") == "ACTIVE"]
        sl_pos     = [p for p in st.session_state.positions if p.get("status") == "SL_HIT"]
        cl_pos     = [p for p in st.session_state.positions if p.get("status") in ("CLOSED","TP_HIT")]

        pc1, pc2, pc3 = st.columns(3)
        pc1.metric("Active", len(active_pos))
        pc2.metric("SL Hit", len(sl_pos))
        pc3.metric("Closed", len(cl_pos))

        st.markdown("<br>", unsafe_allow_html=True)


        rows = []
        for pos in st.session_state.positions:
            status  = pos.get("status", "ACTIVE")
            entry   = pos.get("entry_price", 0)
            ltp     = pos.get("ltp", entry)
            action  = pos.get("action", "SELL")
            lots    = pos.get("lots", 1)
            lot_sz  = pos.get("lot_size", 50)
            pnl     = ((entry - ltp) if action == "SELL" else (ltp - entry)) * lots * lot_sz
            sl      = pos.get("sl_level") or 0
            tp      = pos.get("tp_level") or 0
            expiry  = pos.get("expiry_date_raw")
            dte_val = (expiry - get_ist_now().date()).days if isinstance(expiry, date) else 0
            rows.append({
                "Instrument": pos.get("symbol", "—"),
                "Side":       action,
                "Entry":      round(entry, 1),
                "LTP":        round(ltp, 1),
                "SL":         round(sl, 1),
                "TP":         round(tp, 1),
                "DTE":        dte_val,
                "P&L":        round(pnl, 0),
                "Status":     status,
            })

        df_pos = pd.DataFrame(rows)

        def colour_pnl(val):
            if isinstance(val, (int, float)):
                return "color:#22C55E;font-weight:500" if val >= 0 else "color:#EF4444;font-weight:500"
            return ""

        def colour_status(val):
            m = {"ACTIVE":"color:#22C55E","SL_HIT":"color:#EF4444","TP_HIT":"color:#22C55E","CLOSED":"color:#4A5568"}
            return m.get(val, "")

        styled = (
            df_pos.style
            .applymap(colour_pnl, subset=["P&L"])
            .applymap(colour_status, subset=["Status"])
            .set_properties(**{"font-family":"IBM Plex Mono,monospace","font-size":"12px"})
            .set_table_styles([{"selector":"th","props":[
                ("background-color","#080C10"),("color","#4A5568"),
                ("font-family","IBM Plex Mono,monospace"),("font-size","10px"),
                ("text-transform","uppercase"),("letter-spacing","0.08em"),
            ]}])
        )
        st.dataframe(styled, use_container_width=True, hide_index=True, height=min(200 + len(rows)*38, 450))


        # LTP update
        if active_pos:
            st.divider()
            st.markdown('<p class="panel-title">Live Prices</p>', unsafe_allow_html=True)

            # ── Live fetch via Kite (works in paper mode too) ──────────────────
            def fetch_live_ltps():
                """Fetch real LTPs from Kite for all active positions."""
                kite_client = st.session_state.get("kite_client")
                if not kite_client or not st.session_state.kite_connected:
                    return False, "Not connected to Kite"
                try:
                    symbols = [f"NFO:{p['symbol']}" for p in active_pos if p.get("symbol")]
                    if not symbols:
                        return False, "No symbols to fetch"
                    quotes = kite_client.ltp(symbols)
                    updated = 0
                    missing = []
                    for pos in active_pos:
                        key = f"NFO:{pos['symbol']}"
                        if key in quotes:
                            fetched_price = quotes[key]["last_price"]
                            if fetched_price > 1:
                                pos["ltp"] = fetched_price
                                updated += 1
                                if pos.get("action") == "SELL":
                                    sl = pos.get("sl_level") or 999999
                                    tp = pos.get("tp_level") or 0
                                    if tp > 0 and pos["ltp"] <= tp:
                                        pos["status"] = "TP_HIT"
                                    elif sl < 999999 and pos["ltp"] >= sl:
                                        pos["status"] = "SL_HIT"
                        else:
                            missing.append(pos['symbol'])
                    if missing:
                        return False, f"Symbols not found in Kite: {', '.join(missing)}"
                    return True, f"Updated {updated} prices"
                except Exception as e:
                    return False, str(e)

            col_fix, col_btn1, col_btn2, col_status = st.columns([1, 1, 1, 2])

            with col_fix:
                if st.button("Fix Symbols", use_container_width=True):
                    from datetime import timezone, timedelta
                    IST_tz  = timezone(timedelta(hours=5, minutes=30))
                    expiry  = get_ist_now().date()
                    # Find next Tuesday
                    days_to_tue = (1 - expiry.weekday()) % 7
                    if days_to_tue == 0:
                        days_to_tue = 7
                    next_tue = expiry + timedelta(days=days_to_tue + 7)
                    import re
                    yy  = next_tue.strftime("%y")       # "26"
                    mo  = str(next_tue.month)            # "3"  no leading zero
                    dd  = str(next_tue.day)              # "10" no leading zero
                    prefix = f"NIFTY{yy}{mo}{dd}"       # "NIFTY26310"
                    fixed = 0
                    for pos in st.session_state.positions:
                        sym = pos.get("symbol", "")
                        # Extract just the strike+type from end of any symbol format
                        m2 = re.search(r"(\d{5,6})(CE|PE)$", sym)
                        if m2:
                            strike = m2.group(1)
                            otype  = m2.group(2)
                            new_sym = f"{prefix}{strike}{otype}"
                            if sym != new_sym:
                                pos["symbol"] = new_sym
                                fixed += 1
                    if fixed:
                        st.success(f"Fixed {fixed} symbols → {prefix}XXXX")
                        st.rerun()
                    else:
                        st.info("All symbols already in correct format")

            with col_btn1:
                if st.button("Fetch Live Prices", type="primary", use_container_width=True):
                    success, msg = fetch_live_ltps()
                    if success:
                        # Recompute MTM
                        total = sum(
                            ((p.get("entry_price", 0) - p.get("ltp", p.get("entry_price", 0)))
                             if p.get("action") == "SELL"
                             else (p.get("ltp", p.get("entry_price", 0)) - p.get("entry_price", 0)))
                            * p.get("lots", 1) * p.get("lot_size", 50)
                            for p in st.session_state.positions
                        )
                        st.session_state.daily_pnl = total
                        st.session_state.mtm_history.append({"time": datetime.now(), "pnl": total})
                        if total <= -max_loss_amt:
                            st.session_state.kill_switch = True
                        st.session_state.last_ltp_refresh = datetime.now().strftime("%H:%M:%S")
                        st.rerun()
                    else:
                        st.error(f"Failed: {msg}")

            with col_btn2:
                if st.button("Refresh MTM", use_container_width=True):
                    total = sum(
                        ((p.get("entry_price", 0) - p.get("ltp", p.get("entry_price", 0)))
                         if p.get("action") == "SELL"
                         else (p.get("ltp", p.get("entry_price", 0)) - p.get("entry_price", 0)))
                        * p.get("lots", 1) * p.get("lot_size", 50)
                        for p in st.session_state.positions
                    )
                    st.session_state.daily_pnl = total
                    st.session_state.mtm_history.append({"time": datetime.now(), "pnl": total})
                    if total <= -max_loss_amt:
                        st.session_state.kill_switch = True
                    st.rerun()

            with col_status:
                last_refresh = st.session_state.get("last_ltp_refresh", "Never")
                st.markdown(f'<span class="text-muted">Last fetched: {last_refresh}</span>',
                            unsafe_allow_html=True)

            # ── Manual override inputs ─────────────────────────────────────────
            with st.expander("Manual LTP Override"):
                n_cols   = min(len(active_pos), 4)
                ltp_cols = st.columns(n_cols)
                for i, pos in enumerate(active_pos):
                    with ltp_cols[i % n_cols]:
                        new_ltp = st.number_input(
                            pos.get("symbol", f"Leg {i}"),
                            value=float(pos.get("ltp", pos.get("entry_price", 50))),
                            step=0.5, key=f"ltp_{i}"
                        )
                        pos["ltp"] = new_ltp
                        if pos.get("action") == "SELL":
                            sl = pos.get("sl_level") or 999999
                            tp = pos.get("tp_level") or 0
                            if tp > 0 and new_ltp <= tp:
                                pos["status"] = "TP_HIT"
                            elif sl < 999999 and new_ltp >= sl:
                                pos["status"] = "SL_HIT"
                        # BUY legs: never auto-close, always stay ACTIVE

        st.markdown("<br>", unsafe_allow_html=True)
        for i, pos in enumerate(st.session_state.positions):
            if pos.get("status") == "ACTIVE":
                if st.button(f"Exit  {pos.get('symbol', f'Leg {i}')}", key=f"exit_{i}"):
                    pos["status"] = "CLOSED"
                    st.session_state.trade_log.append({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "date": get_ist_now().date().isoformat(),
                        "action": "MANUAL EXIT",
                        "details": pos.get("symbol", ""),
                        "pnl": 0, "status": "CLOSED",
                    })
                    st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# LOG
# ══════════════════════════════════════════════════════════════════════════════
with tab4:
    log_sub1, log_sub2 = st.tabs(["TODAY", "HISTORY"])

    with log_sub1:
        col_h, col_c = st.columns([5, 1])
        with col_c:
            if st.button("Clear", use_container_width=True):
                st.session_state.trade_log = []
                st.rerun()

        if st.session_state.trade_log:
            st.dataframe(pd.DataFrame(st.session_state.trade_log),
                         use_container_width=True, hide_index=True)
            pnl_vals = [t["pnl"] for t in st.session_state.trade_log
                        if isinstance(t.get("pnl"), (int, float))]
            if pnl_vals:
                lc1, lc2, lc3, lc4 = st.columns(4)
                lc1.metric("Entries",  len(st.session_state.trade_log))
                lc2.metric("Winners",  len([x for x in pnl_vals if x > 0]))
                lc3.metric("Losers",   len([x for x in pnl_vals if x < 0]))
                lc4.metric("Net P&L",  format_currency(sum(pnl_vals)))
        else:
            st.markdown('<div class="panel"><span class="text-muted">No log entries today.</span></div>',
                        unsafe_allow_html=True)

    with log_sub2:
        pnl_hist = load_pnl_history()
        sessions  = list_sessions()
        if pnl_hist:
            st.markdown('<p class="panel-title">Cumulative P&L</p>', unsafe_allow_html=True)
            # Summary metrics
            total   = sum(e["pnl"] for e in pnl_hist)
            winners = len([e for e in pnl_hist if e["pnl"] > 0])
            losers  = len([e for e in pnl_hist if e["pnl"] < 0])
            avg_day = total / len(pnl_hist) if pnl_hist else 0
            h1, h2, h3, h4 = st.columns(4)
            h1.metric("Total P&L",   format_currency(total))
            h2.metric("Trading Days", len(pnl_hist))
            h3.metric("Win Days",    f"{winners}/{len(pnl_hist)}")
            h4.metric("Avg/Day",     format_currency(avg_day))

            # P&L chart
            hist_df = pd.DataFrame(pnl_hist)
            hist_df["cumulative"] = hist_df["pnl"].cumsum()
            import plotly.graph_objects as go
            fig = go.Figure()
            fig.add_bar(x=hist_df["date"], y=hist_df["pnl"],
                        marker_color=["#22C55E" if v >= 0 else "#EF4444" for v in hist_df["pnl"]],
                        name="Daily P&L")
            fig.add_scatter(x=hist_df["date"], y=hist_df["cumulative"],
                            line=dict(color="#3B82F6", width=2), name="Cumulative")
            fig.update_layout(
                paper_bgcolor="#080C10", plot_bgcolor="#0D1117",
                font=dict(family="IBM Plex Mono", color="#8A9BB0", size=11),
                xaxis=dict(gridcolor="#1C2530"), yaxis=dict(gridcolor="#1C2530"),
                legend=dict(bgcolor="#080C10"), margin=dict(l=0, r=0, t=20, b=0),
                height=300
            )
            st.plotly_chart(fig, use_container_width=True)

            # Daily breakdown table
            st.markdown('<p class="panel-title">Daily Breakdown</p>', unsafe_allow_html=True)
            st.dataframe(
                hist_df[["date","pnl","cumulative"]].rename(
                    columns={"date":"Date","pnl":"P&L","cumulative":"Cumulative"}
                ).sort_values("Date", ascending=False),
                use_container_width=True, hide_index=True
            )
        else:
            st.markdown('<div class="panel"><span class="text-muted">No history yet — data builds up as you trade daily.</span></div>',
                        unsafe_allow_html=True)

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="margin-top:32px;padding-top:16px;border-top:1px solid #1C2530;
            display:flex;justify-content:space-between;align-items:center;">
    <span class="text-muted">RAPTOR BY BLACKWATER</span>
    <span class="text-muted">Account ₹{account_size:,.0f} · Max Loss ₹{max_loss_amt:,.0f}</span>
    <span class="text-muted">{'PAPER' if st.session_state.paper_mode else 'LIVE'} · {datetime.now().strftime('%H:%M:%S')}</span>
</div>
""", unsafe_allow_html=True)
