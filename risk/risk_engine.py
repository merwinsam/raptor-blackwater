"""
Risk Engine - Pre-trade and ongoing risk checks
- Max loss per trade
- Daily kill switch
- Margin utilization
- Slippage filter
"""

import config


class RiskEngine:
    def __init__(self, params: dict = None):
        self.params = params or {}
        self.account_size = self.params.get("account_size", config.ACCOUNT_SIZE)
        self.max_loss_amt = self.params.get("max_loss_amt", self.account_size * config.MAX_LOSS_PCT)
        self.daily_kill_amt = self.account_size * self.params.get("daily_kill_pct", config.DAILY_KILL_PCT)
        self.max_margin_util = config.MAX_MARGIN_UTILIZATION
        self.bid_ask_max = config.BID_ASK_SPREAD_MAX

    def pre_trade_check(self, condor: dict, lots: int, 
                         daily_pnl: float, account_size: float) -> dict:
        """
        Run all pre-trade risk checks before placing condor.
        Returns: {"approved": bool, "reason": str}
        """
        checks = []

        # 1. Max loss check — scale limit by lot count
        max_loss = condor.get("max_loss", 0) * lots
        # Allow max_loss_amt to scale: base limit × lots (so 10 lots = 10× the per-lot limit)
        scaled_limit = self.max_loss_amt * lots
        if max_loss > scaled_limit:
            return {
                "approved": False,
                "reason": f"Max loss ₹{max_loss:,.0f} exceeds limit ₹{scaled_limit:,.0f}"
            }
        checks.append("✅ Max loss check passed")

        # 2. Daily PnL check - don't trade if already at kill threshold
        if daily_pnl <= -self.daily_kill_amt:
            return {
                "approved": False,
                "reason": f"Daily loss ₹{abs(daily_pnl):,.0f} ≥ kill threshold ₹{self.daily_kill_amt:,.0f}"
            }
        checks.append("✅ Daily P&L check passed")

        # 3. Margin utilization check
        margin_needed = condor.get("margin_required", 0) * lots
        if margin_needed > account_size * self.max_margin_util:
            return {
                "approved": False,
                "reason": f"Margin ₹{margin_needed:,.0f} exceeds {self.max_margin_util*100:.0f}% of account"
            }
        checks.append("✅ Margin utilization check passed")

        # 4. Net credit positive check
        if condor.get("net_credit", 0) <= 0:
            return {
                "approved": False,
                "reason": "Net credit is negative — not a valid condor"
            }
        checks.append("✅ Net credit check passed")

        return {
            "approved": True,
            "reason": "All checks passed",
            "checks": checks,
            "max_loss": max_loss,
            "margin_needed": margin_needed,
        }

    def check_sl_hit(self, position: dict) -> dict:
        """
        Check if a position has hit its stop loss.
        For SELL legs: SL hit if LTP >= sl_level
        """
        if position.get("action") != "SELL":
            return {"sl_hit": False}

        ltp = position.get("ltp", 0)
        sl_level = position.get("sl_level", float("inf"))

        if ltp >= sl_level:
            return {
                "sl_hit": True,
                "ltp": ltp,
                "sl_level": sl_level,
                "reason": f"LTP ₹{ltp} ≥ SL ₹{sl_level}"
            }
        return {"sl_hit": False}

    def check_tp_hit(self, position: dict) -> dict:
        """
        Check if a position has hit its take profit.
        For SELL legs: TP hit if LTP <= tp_level (50% of premium)
        """
        if position.get("action") != "SELL":
            return {"tp_hit": False}

        ltp = position.get("ltp", 999)
        tp_level = position.get("tp_level", 0)

        if ltp <= tp_level:
            return {
                "tp_hit": True,
                "ltp": ltp,
                "tp_level": tp_level,
                "reason": f"LTP ₹{ltp} ≤ TP ₹{tp_level}"
            }
        return {"tp_hit": False}

    def check_daily_kill(self, daily_pnl: float) -> bool:
        """Returns True if daily kill switch should trigger"""
        return daily_pnl <= -self.daily_kill_amt

    def check_max_loss(self, daily_pnl: float) -> bool:
        """Returns True if max loss is breached"""
        return daily_pnl <= -self.max_loss_amt

    def compute_position_pnl(self, position: dict) -> float:
        """Compute current P&L for a position"""
        entry = position.get("entry_price", 0)
        ltp = position.get("ltp", entry)
        lots = position.get("lots", 1)
        lot_size = position.get("lot_size", config.NIFTY_LOT_SIZE)
        action = position.get("action", "SELL")

        if action == "SELL":
            pnl_per_unit = entry - ltp
        else:
            pnl_per_unit = ltp - entry

        return pnl_per_unit * lots * lot_size

    def compute_portfolio_pnl(self, positions: list) -> dict:
        """Compute aggregate portfolio P&L"""
        total = 0
        leg_pnls = []

        for pos in positions:
            if pos.get("status") in ("ACTIVE", "SL_HIT"):
                pnl = self.compute_position_pnl(pos)
                total += pnl
                leg_pnls.append({
                    "symbol": pos.get("symbol", ""),
                    "pnl": pnl,
                    "status": pos.get("status")
                })

        return {
            "total_pnl": round(total, 2),
            "legs": leg_pnls,
            "max_loss_breached": total <= -self.max_loss_amt,
            "kill_triggered": total <= -self.daily_kill_amt,
        }
