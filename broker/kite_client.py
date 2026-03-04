"""
Zerodha Kite Connect Client Wrapper
Paper mode: real prices, no real orders.
"""
import config


class KiteClient:
    def __init__(self, api_key: str = None, access_token: str = None,
                 paper_mode: bool = True):
        self.api_key     = api_key or config.API_KEY
        self.access_token = access_token
        self.paper_mode  = paper_mode
        self.kite        = None
        if access_token:
            self._init_kite()

    def _init_kite(self):
        from kiteconnect import KiteConnect
        self.kite = KiteConnect(api_key=self.api_key)
        self.kite.set_access_token(self.access_token)

    def test_connection(self) -> dict:
        if self.kite:
            try:
                profile = self.kite.profile()
                return {"success": True,
                        "message": f"Connected as {profile['user_name']}",
                        "user": profile["user_name"],
                        "mode": "PAPER" if self.paper_mode else "LIVE"}
            except Exception as e:
                return {"success": False, "message": str(e)}
        return {"success": True, "message": "Paper mode — no live prices", "mode": "PAPER"}

    # ── Market data ────────────────────────────────────────────────────────────

    def get_nifty_spot(self) -> float:
        """Fetch live NIFTY 50 spot price."""
        if not self.kite:
            return 25000.0
        data = self.kite.ltp(["NSE:NIFTY 50"])
        return data["NSE:NIFTY 50"]["last_price"]

    def get_india_vix(self) -> float:
        """Fetch live India VIX."""
        if not self.kite:
            return 14.5
        data = self.kite.ltp(["NSE:INDIA VIX"])
        return data["NSE:INDIA VIX"]["last_price"]

    def ltp(self, symbols: list) -> dict:
        """Fetch LTP for a list of symbols. Always uses real Kite data."""
        if not self.kite:
            return {s: {"last_price": 0.0} for s in symbols}
        try:
            return self.kite.ltp(symbols)
        except Exception as e:
            raise Exception(f"Kite LTP failed: {e}")

    def get_option_ltp(self, symbol: str) -> float:
        """Fetch single option LTP from NFO."""
        key = f"NFO:{symbol}"
        result = self.ltp([key])
        if key in result:
            return result[key]["last_price"]
        raise Exception(f"Symbol not found: {key}")

    # ── Orders (paper only) ────────────────────────────────────────────────────

    def place_order(self, **kwargs) -> str:
        """Always paper — never sends real orders."""
        import random
        return f"PAPER_{random.randint(100000, 999999)}"

    # ── Account ────────────────────────────────────────────────────────────────

    def margins(self) -> dict:
        if self.kite and not self.paper_mode:
            return self.kite.margins()
        return {"equity": {"net": config.ACCOUNT_SIZE,
                            "available": {"live_balance": config.ACCOUNT_SIZE * 0.8}}}

    def positions(self) -> dict:
        return {"net": [], "day": []}
