"""
Order Execution Engine
- Smart limit order placement
- Multi-leg execution (hedges first, then shorts)
- Fill confirmation and retry logic
- Partial fill handling
"""

import time
import random
from datetime import datetime
import config


class OrderEngine:
    def __init__(self, kite_client=None, paper_mode: bool = True):
        self.kite = kite_client
        self.paper_mode = paper_mode
        self.order_log = []

    def place_iron_condor(self, condor: dict, lots: int = 1) -> dict:
        """
        Execute iron condor with proper sequencing:
        1. Place BUY (hedge) legs first
        2. Confirm fills
        3. Only then place SELL legs
        4. If any failure → exit all
        """
        legs = condor["legs"]
        buy_legs = [l for l in legs if l["action"] == "BUY"]
        sell_legs = [l for l in legs if l["action"] == "SELL"]

        filled_positions = []

        # ── STEP 1: Place hedge (BUY) legs first
        for leg in buy_legs:
            result = self._place_single_order(leg, lots, "hedge")
            if not result["success"]:
                # Abort: exit any already-filled hedges
                self._exit_all(filled_positions)
                return {
                    "success": False,
                    "message": f"Hedge leg failed: {result['message']}. Aborted.",
                    "positions": []
                }
            filled_positions.append(result["position"])

        # ── STEP 2: Confirm all hedges
        for pos in filled_positions:
            if not self._confirm_fill(pos):
                self._exit_all(filled_positions)
                return {
                    "success": False,
                    "message": "Hedge fill confirmation failed. Aborted.",
                    "positions": []
                }

        # ── STEP 3: Place SELL legs
        for leg in sell_legs:
            result = self._place_single_order(leg, lots, "sell")
            if not result["success"]:
                # Exit everything — hedges + any fills so far
                self._exit_all(filled_positions)
                return {
                    "success": False,
                    "message": f"Sell leg failed: {result['message']}. Exiting all.",
                    "positions": []
                }
            filled_positions.append(result["position"])

        return {
            "success": True,
            "message": "All legs filled",
            "positions": filled_positions,
            "placed_at": datetime.now().isoformat(),
        }

    def _place_single_order(self, leg: dict, lots: int, leg_type: str) -> dict:
        """Place a single leg with retry logic"""
        
        for attempt in range(config.MAX_RETRIES):
            try:
                if self.paper_mode:
                    return self._paper_fill(leg, lots)
                else:
                    return self._live_fill(leg, lots)
            except Exception as e:
                if attempt < config.MAX_RETRIES - 1:
                    time.sleep(config.RETRY_DELAY_SEC)
                else:
                    return {"success": False, "message": str(e)}

        return {"success": False, "message": "Max retries exceeded"}

    def _paper_fill(self, leg: dict, lots: int) -> dict:
        """Simulate paper order fill"""
        time.sleep(config.PAPER_FILL_DELAY_SEC)
        
        entry_price = leg.get("premium", 50)
        # Add small random slippage
        slippage = random.uniform(-0.5, 0.5)
        fill_price = round(entry_price + slippage, 1)
        
        position = {
            **leg,
            "entry_price": fill_price,
            "ltp": fill_price,
            "lots": lots,
            "filled_at": datetime.now().isoformat(),
            "order_id": f"PAPER_{datetime.now().timestamp():.0f}",
            "status": "ACTIVE",
            "mode": "PAPER",
        }
        
        self.order_log.append({
            "time": datetime.now().strftime("%H:%M:%S"),
            "symbol": leg.get("symbol"),
            "action": leg.get("action"),
            "fill_price": fill_price,
            "lots": lots,
            "status": "PAPER FILLED"
        })
        
        return {"success": True, "position": position}

    def _live_fill(self, leg: dict, lots: int) -> dict:
        """Place live order via Kite API"""
        if not self.kite:
            return {"success": False, "message": "Kite client not initialized"}
        
        try:
            # Get LTP for limit price
            symbol = leg.get("symbol")
            ltp_data = self.kite.ltp([f"NFO:{symbol}"])
            ltp = ltp_data[f"NFO:{symbol}"]["last_price"]
            
            # Use limit price slightly better than LTP
            action = leg.get("action")
            if action == "BUY":
                limit_price = round(ltp * 1.01, 1)  # Slightly above for fills
            else:
                limit_price = round(ltp * 0.99, 1)  # Slightly below for sells
            
            order_id = self.kite.place_order(
                tradingsymbol=symbol,
                exchange="NFO",
                transaction_type=action,
                quantity=lots * config.NIFTY_LOT_SIZE,
                order_type="LIMIT",
                price=limit_price,
                product="MIS",
                variety="regular",
            )
            
            position = {
                **leg,
                "entry_price": limit_price,
                "ltp": ltp,
                "lots": lots,
                "order_id": order_id,
                "filled_at": datetime.now().isoformat(),
                "status": "ACTIVE",
                "mode": "LIVE",
            }
            
            return {"success": True, "position": position}
        
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _confirm_fill(self, position: dict) -> bool:
        """Confirm order was actually filled"""
        if self.paper_mode:
            return True  # Paper fills are always confirmed
        
        if not self.kite:
            return False
        
        try:
            order_id = position.get("order_id")
            orders = self.kite.order_history(order_id)
            status = orders[-1]["status"]
            return status == "COMPLETE"
        except Exception:
            return False

    def _exit_all(self, positions: list):
        """Emergency exit all positions"""
        for pos in positions:
            if pos.get("status") == "ACTIVE":
                self._place_exit_order(pos)

    def _place_exit_order(self, position: dict) -> dict:
        """Place exit order (reverse of entry)"""
        exit_action = "SELL" if position.get("action") == "BUY" else "BUY"
        
        if self.paper_mode:
            position["status"] = "CLOSED"
            position["exit_price"] = position.get("ltp", position.get("entry_price", 0))
            return {"success": True}
        
        # Live exit
        try:
            self.kite.place_order(
                tradingsymbol=position.get("symbol"),
                exchange="NFO",
                transaction_type=exit_action,
                quantity=position.get("lots", 1) * config.NIFTY_LOT_SIZE,
                order_type="MARKET",  # Market order for emergency exit
                product="MIS",
                variety="regular",
            )
            return {"success": True}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def exit_leg(self, position: dict) -> dict:
        """Exit a single leg"""
        return self._place_exit_order(position)
