# NIFTY Iron Condor Execution System

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run the app
streamlit run app.py
```

## Kite API Setup (for LIVE mode)
1. Go to https://developers.kite.trade/
2. Create app → get API Key + API Secret
3. Login URL: https://kite.trade/connect/login?api_key=YOUR_KEY
4. Paste the request token → generate access token
5. Enter in sidebar → Connect

## Folder Structure
```
nifty_condor/
├── app.py              ← Main Streamlit UI
├── config.py           ← All parameters
├── requirements.txt
├── strategy/
│   ├── iron_condor.py  ← Strike selection, condor builder
│   └── atr_model.py    ← ATR computation
├── risk/
│   └── risk_engine.py  ← Pre-trade checks, SL/TP logic
├── execution/
│   └── order_engine.py ← Order placement, retry, multi-leg
├── broker/
│   └── kite_client.py  ← Zerodha Kite wrapper
├── monitor/
│   └── position_monitor.py ← MTM, SL/TP monitoring
├── utils/
│   └── helpers.py
├── data/               ← Historical data cache
└── logs/               ← Trade logs
```
