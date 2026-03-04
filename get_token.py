"""
Raptor by Blackwater — Daily Token Generator
Run once each morning: python3 get_token.py
Opens Kite login in browser, captures token automatically.
Reads API_KEY and API_SECRET from environment variables.
"""

import sys
import os
import webbrowser
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

# ── Load from environment (set in .env or shell) ──────────────────────────────
API_KEY    = os.environ.get("KITE_API_KEY")
API_SECRET = os.environ.get("KITE_API_SECRET")

if not API_KEY or not API_SECRET:
    print("ERROR: KITE_API_KEY and KITE_API_SECRET must be set as environment variables.")
    print("\nRun first:")
    print("  export KITE_API_KEY=your_api_key")
    print("  export KITE_API_SECRET=your_api_secret")
    print("\nOr add them to a .env file (see .env.example).")
    sys.exit(1)

PORT       = 8765
TOKEN_FILE = Path(__file__).parent / "logs" / "token.json"
request_token_captured = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global request_token_captured
        params = parse_qs(urlparse(self.path).query)
        rt     = params.get("request_token", [None])[0]
        status = params.get("status", [""])[0]

        if rt and status == "success":
            request_token_captured = rt
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
            <html><body style='font-family:monospace;background:#03060A;color:#22c55e;
                               display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>
              <div style='text-align:center'>
                <div style='font-size:48px'>&#10003;</div>
                <div style='font-size:20px;margin-top:16px'>TOKEN CAPTURED</div>
                <div style='color:#4a5568;margin-top:8px'>Return to Raptor - no manual pasting needed.</div>
              </div>
            </body></html>""")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Login failed or cancelled.")

    def log_message(self, format, *args):
        pass


def run():
    from kiteconnect import KiteConnect
    from datetime import date

    today = date.today().isoformat()

    # Check if token already saved for today
    if TOKEN_FILE.exists():
        with open(TOKEN_FILE) as f:
            saved = json.load(f)
        if saved.get("date") == today:
            print(f"{'='*50}")
            print(f"✅  Token already valid for today ({today})")
            print(f"{'='*50}")
            print("Raptor will auto-connect on startup.")
            return

    kite      = KiteConnect(api_key=API_KEY)
    login_url = f"https://kite.trade/connect/login?api_key={API_KEY}&v=3"

    print(f"{'='*50}")
    print("RAPTOR BY BLACKWATER — Daily Token")
    print(f"{'='*50}")
    print("\nOpening Kite login in your browser...")
    print(f"  {login_url}\n")
    webbrowser.open(login_url)

    print(f"Listening for callback on localhost:{PORT}...")
    server = HTTPServer(("127.0.0.1", PORT), CallbackHandler)
    server.timeout = 120

    while request_token_captured is None:
        server.handle_request()

    print(f"\n✅  Request token captured.")
    data         = kite.generate_session(request_token_captured, api_secret=API_SECRET)
    access_token = data["access_token"]

    TOKEN_FILE.parent.mkdir(exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump({"date": today, "api_key": API_KEY, "access_token": access_token}, f, indent=2)

    print(f"✅  Access token saved to logs/token.json")
    print(f"\n{'='*50}")
    print("Raptor will auto-connect. Run: streamlit run app.py")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    run()
