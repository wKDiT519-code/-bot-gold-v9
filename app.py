import os, time, threading, requests
from flask import Flask, jsonify
import ccxt
import pandas as pd

print("=== BOT GOLD v9.2 RENDER FINAL ===", flush=True)
app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
SYMBOL = "XAU/USDT"
TIMEFRAME = "1h"
START_BALANCE = 100.0

portfolio = {"balance": START_BALANCE, "last_price": 0, "last_update": "", "status": "starting", "wins":0, "losses":0, "position": None, "trades":[]}

try:
    exchange = ccxt.mexc({'enableRateLimit': True})
    print("MEXC OK", flush=True)
except Exception as e:
    print(f"MEXC FAIL {e}", flush=True)
    exchange = None

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(f"SKIP TG: {msg[:100]}", flush=True)
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": msg}, timeout=10)
        print(f"TG {r.status_code}", flush=True)
    except Exception as e:
        print(f"TG err {e}", flush=True)

def get_ohlcv():
    ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=150)
    return pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","vol"])

def calc_indicators(df):
    delta = df["close"].diff()
    gain = delta.where(delta>0,0).rolling(14).mean()
    loss = -delta.where(delta<0,0).rolling(14).mean()
    rs = gain/loss
    df["rsi"] = 100 - (100/(1+rs))
    df["tr"] = pd.concat([df["high"]-df["low"], (df["high"]-df["close"].shift()).abs(), (df["low"]-df["close"].shift()).abs()], axis=1).max(axis=1)
    df["atr"] = df["tr"].rolling(14).mean()
    df["up"] = df["high"].diff()
    df["down"] = -df["low"].diff()
    df["plus_dm"] = df.apply(lambda x: x["up"] if x["up"]>x["down"] and x["up"]>0 else 0, axis=1)
    df["minus_dm"] = df.apply(lambda x: x["down"] if x["down"]>x["up"] and x["down"]>0 else 0, axis=1)
    df["plus_di"] = 100 * (df["plus_dm"].rolling(14).mean() / df["atr"])
    df["minus_di"] = 100 * (df["minus_dm"].rolling(14).mean() / df["atr"])
    df["dx"] = 100 * abs(df["plus_di"]-df["minus_di"]) / (df["plus_di"]+df["minus_di"])
    df["adx"] = df["dx"].rolling(14).mean()
    return df

def bot_loop():
    print("LOOP STARTED", flush=True)
    portfolio["status"] = "running"
    time.sleep(3)
    send_telegram(f"Bot GOLD v9.2 LIVE Render FIXED!\nPort $100 Symbol {SYMBOL} TF {TIMEFRAME}")
    last_signal = 0
    while True:
        try:
            df = get_ohlcv()
            df = calc_indicators(df)
            last = df.iloc[-1]
            price = float(last["close"])
            rsi = float(last["rsi"]) if not pd.isna(last["rsi"]) else 50
            adx = float(last["adx"]) if not pd.isna(last["adx"]) else 0
            portfolio["last_price"] = price
            portfolio["last_update"] = time.strftime("%H:%M:%S")
            print(f"SCAN {portfolio['last_update']} ${price:.2f} RSI {rsi:.1f} ADX {adx:.1f}", flush=True)
            if portfolio["position"] is None and time.time()-last_signal > 3600:
                trend_up = last["plus_di"] > last["minus_di"]
                if adx>25 and 55<rsi<72 and trend_up:
                    portfolio["position"] = {"side":"LONG","entry":price}
                    last_signal = time.time()
                    send_telegram(f"GOLD LONG Signal ${price:.2f} RSI {rsi:.1f} ADX {adx:.1f}")
        except Exception as e:
            print(f"Loop err {e}", flush=True)
            import traceback; traceback.print_exc()
        time.sleep(300)

@app.route("/")
def home():
    return f"GOLD v9.2 LIVE ${portfolio['last_price']} {portfolio['last_update']} {portfolio['status']}"

@app.route("/health")
def health():
    return "OK", 200

@app.route("/portfolio")
def port():
    return jsonify(portfolio)

# start thread
threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
