"""
Blackwater OED — Persistence Layer
Saves and loads daily state to disk so P&L, positions, and logs
survive app restarts.

Files saved under logs/
  logs/YYYY-MM-DD_session.json   ← daily session (positions + trade log)
  logs/pnl_history.json          ← cumulative P&L across all days
  config/token.json              ← today's access token (auto-cleared at midnight)
"""

import json
import os
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

BASE_DIR  = Path(__file__).parent.parent
LOGS_DIR  = BASE_DIR / "logs"
CFG_DIR   = LOGS_DIR  # save token alongside logs, no separate config folder
PNL_FILE  = LOGS_DIR / "pnl_history.json"
TOKEN_FILE = CFG_DIR / "token.json"

LOGS_DIR.mkdir(exist_ok=True)
# CFG_DIR same as LOGS_DIR, already created above


def _ist_today() -> date:
    IST = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(timezone.utc).astimezone(IST).date()


def _session_file(d: date = None) -> Path:
    d = d or _ist_today()
    return LOGS_DIR / f"{d.isoformat()}_session.json"


# ── Session (positions + trade log) ──────────────────────────────────────────

def save_session(positions: list, trade_log: list, daily_pnl: float):
    """Save today's session to disk."""
    data = {
        "date":       _ist_today().isoformat(),
        "saved_at":   datetime.utcnow().isoformat(),
        "daily_pnl":  daily_pnl,
        "positions":  _serialise(positions),
        "trade_log":  _serialise(trade_log),
    }
    with open(_session_file(), "w") as f:
        json.dump(data, f, indent=2)


def load_session(d: date = None) -> dict | None:
    """Load session for a given date (default today)."""
    path = _session_file(d)
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def list_sessions() -> list[dict]:
    """Return summary of all saved sessions, newest first."""
    sessions = []
    for f in sorted(LOGS_DIR.glob("*_session.json"), reverse=True):
        try:
            with open(f) as fp:
                data = json.load(fp)
            sessions.append({
                "date":      data.get("date"),
                "daily_pnl": data.get("daily_pnl", 0),
                "trades":    len(data.get("trade_log", [])),
            })
        except Exception:
            pass
    return sessions


# ── Cumulative P&L history ────────────────────────────────────────────────────

def update_pnl_history(daily_pnl: float):
    """Append today's P&L to the running history file."""
    history = load_pnl_history()
    today   = _ist_today().isoformat()
    # Update or insert today
    for entry in history:
        if entry["date"] == today:
            entry["pnl"] = daily_pnl
            break
    else:
        history.append({"date": today, "pnl": daily_pnl})
    history.sort(key=lambda x: x["date"])
    with open(PNL_FILE, "w") as f:
        json.dump(history, f, indent=2)


def load_pnl_history() -> list[dict]:
    """Load full P&L history [{date, pnl}, ...]."""
    if not PNL_FILE.exists():
        return []
    with open(PNL_FILE) as f:
        return json.load(f)


def total_pnl() -> float:
    return sum(e["pnl"] for e in load_pnl_history())


# ── Token persistence ─────────────────────────────────────────────────────────

def save_token(api_key: str, access_token: str):
    """Save today's token to disk."""
    data = {
        "date":         _ist_today().isoformat(),
        "api_key":      api_key,
        "access_token": access_token,
    }
    with open(TOKEN_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_token() -> dict | None:
    """Load token if it was saved today, else return None."""
    if not TOKEN_FILE.exists():
        return None
    with open(TOKEN_FILE) as f:
        data = json.load(f)
    if data.get("date") == _ist_today().isoformat():
        return data
    return None   # expired (different day)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _serialise(obj):
    """Make objects JSON-safe (convert date/datetime to string)."""
    import copy
    obj = copy.deepcopy(obj)
    if isinstance(obj, list):
        return [_serialise(i) for i in obj]
    if isinstance(obj, dict):
        return {k: _serialise(v) for k, v in obj.items()}
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return obj
