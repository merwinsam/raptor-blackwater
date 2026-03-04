"""
Position Monitor
- Real-time MTM tracking
- SL/TP monitoring per leg
- Auto-trigger exits
- Leg-wise P&L
"""

from datetime import datetime
import config


class PositionMonitor:
    def __init__(self, kite_client=None, paper_mode: bool = True):
        self.kite = kite_client
        self.paper_mode = paper_mode

    def update_ltps(self, positions: list) -> list:
        """Update LTPs for all active positions"""
        if self.paper_mode:
            return positions  # LTPs updated manually in paper mode

        for pos in positions:
            if pos.get("status") != "ACTIVE":
                continue
            try:
                symbol = f"NFO:{pos['symbol']}"
                ltp_data = self.kite.ltp([symbol])
                pos["ltp"] = ltp_data[symbol]["last_price"]
            except Exception:
                pass  # Keep last LTP on error

        return positions

    def check_all_sl_tp(self, positions: list, order_engine=None) -> tuple:
        """
        Check SL/TP for all positions.
        Key logic: If one leg SL hit → other legs CONTINUE to TP.
        
        Returns: (updated_positions, events)
        """
        events = []

        for pos in positions:
            if pos.get("status") != "ACTIVE":
                continue
            if pos.get("action") != "SELL":
                continue

            ltp = pos.get("ltp", 0)
            sl = pos.get("sl_level", float("inf"))
            tp = pos.get("tp_level", 0)

            # SL check
            if ltp >= sl:
                pos["status"] = "SL_HIT"
                pos["exit_price"] = ltp
                pos["exit_time"] = datetime.now().isoformat()
                
                events.append({
                    "type": "SL_HIT",
                    "symbol": pos.get("symbol"),
                    "strike": pos.get("strike"),
                    "option_type": pos.get("option_type"),
                    "ltp": ltp,
                    "sl_level": sl,
                    "message": f"🚨 SL HIT: {pos['symbol']} LTP ₹{ltp} ≥ SL ₹{sl}"
                })
                
                if order_engine:
                    order_engine.exit_leg(pos)
                
                # NOTE: Other legs CONTINUE — this is by design
                # Only this specific leg exits

            # TP check
            elif ltp <= tp:
                pos["status"] = "TP_HIT"
                pos["exit_price"] = ltp
                pos["exit_time"] = datetime.now().isoformat()
                
                events.append({
                    "type": "TP_HIT",
                    "symbol": pos.get("symbol"),
                    "strike": pos.get("strike"),
                    "option_type": pos.get("option_type"),
                    "ltp": ltp,
                    "tp_level": tp,
                    "message": f"✅ TP HIT: {pos['symbol']} LTP ₹{ltp} ≤ TP ₹{tp}"
                })
                
                if order_engine:
                    order_engine.exit_leg(pos)

        return positions, events

    def compute_mtm(self, positions: list) -> dict:
        """Compute real-time MTM P&L"""
        total = 0
        by_leg = []

        for pos in positions:
            entry = pos.get("entry_price", 0)
            ltp = pos.get("ltp", entry)
            action = pos.get("action", "SELL")
            lots = pos.get("lots", 1)
            lot_size = pos.get("lot_size", config.NIFTY_LOT_SIZE)

            if action == "SELL":
                pnl = (entry - ltp) * lots * lot_size
            else:
                pnl = (ltp - entry) * lots * lot_size

            total += pnl
            by_leg.append({
                "symbol": pos.get("symbol"),
                "action": action,
                "entry": entry,
                "ltp": ltp,
                "pnl": round(pnl, 2),
                "status": pos.get("status"),
            })

        return {
            "total_pnl": round(total, 2),
            "by_leg": by_leg,
            "timestamp": datetime.now().isoformat(),
        }
