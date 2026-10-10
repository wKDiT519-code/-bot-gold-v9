import os, time, threading, requests, sys
print("=== BOT GOLD v9 STARTING $100 ===", flush=True)
from flask import Flask, jsonify
import ccxt
import pandas as pd

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "") or os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "") or os.getenv("TELEGRAM_CHAT_ID", "")

SYMBOL = "XAU/USDT"   # ทอง
TIMEFRAME = "1h"      # 1H กรองหลอก
START_BALANCE = 100.0
RISK_PER_TRADE = 10.0  # ทองเสี่ยงน้อยกว่า BTC
LEVERAGE = 5          # ทอง x5 พอ
COOLDOWN_SEC = 60*60  # ทอง 1H เทรดชั่วโมงละครั้งพอ

portfolio = {
    "balance": START_BALANCE,
    "start_balance": START_BALANCE,
    "symbol": SYMBOL,
    "trades": [],
    "wins": 0,
    "losses": 0,
    "position": None,
    "last_price": 0,
    "last_update": "",
    "bot_type": "GOLD"
}

print(f"GOLD BOT: {SYMBOL} {TIMEFRAME} TELEGRAM set {bool(TELEGRAM_TOKEN)} CHAT {bool(CHAT_ID)}", flush=True)

try:
    exchange = ccxt.mexc()
    print("MEXC OK", flush=True)
except Exception as e:
    print(f"MEXC FAIL {e}", flush=True)
    exchange = None

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(f"SKIP TG: {msg[:60]}", flush=True)
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        print(f"TG sent {r.status_code}", flush=True)
    except Exception as e:
        print(f"TG error {e}", flush=True)

def get_ohlcv():
    ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=150)
    df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","vol"])
    return df

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

def paper_check_close(price):
    pos = portfolio["position"]
    if not pos:
        return
    if pos["side"]=="LONG":
        if price <= pos["sl"]:
            pnl = (pos["sl"]-pos["entry"])/pos["entry"] * pos["amount"] * LEVERAGE
            portfolio["balance"]+=pnl
            portfolio["losses"]+=1
            portfolio["trades"].append({"pnl":pnl,"result":"SL","price":price})
            send_telegram(f"🛑 *GOLD SL HIT* LONG\nEntry ${pos['entry']:.2f} -> SL ${pos['sl']:.2f}\nPnL ${pnl:.2f}\n💰 พอร์ตทอง ${portfolio['balance']:.2f} ({(portfolio['balance']/START_BALANCE-1)*100:+.2f}%) W{portfolio['wins']} L{portfolio['losses']}")
            portfolio["position"]=None
            return
        if price >= pos["tp3"]:
            pnl1 = (pos["tp1"]-pos["entry"])/pos["entry"]*pos["amount"]*LEVERAGE*0.5
            pnl2 = (pos["tp2"]-pos["entry"])/pos["entry"]*pos["amount"]*LEVERAGE*0.3
            pnl3 = (pos["tp3"]-pos["entry"])/pos["entry"]*pos["amount"]*LEVERAGE*0.2
            pnl = pnl1+pnl2+pnl3
            portfolio["balance"]+=pnl
            portfolio["wins"]+=1
            portfolio["trades"].append({"pnl":pnl,"result":"TP3","price":price})
            send_telegram(f"✅ *GOLD TP3 HIT* LONG\nEntry ${pos['entry']:.2f}\nTPs ${pos['tp1']:.1f} / ${pos['tp2']:.1f} / ${pos['tp3']:.1f}\nPnL +${pnl:.2f}\n💰 พอร์ตทอง ${portfolio['balance']:.2f} ({(portfolio['balance']/START_BALANCE-1)*100:+.2f}%) W{portfolio['wins']} L{portfolio['losses']}")
            portfolio["position"]=None

def bot_loop():
    print("GOLD LOOP STARTED", flush=True)
    last_signal=0
    time.sleep(5)
    send_telegram(f"🏆 Bot GOLD v9 LIVE!\n💰 พอร์ตทองจำลอง ${START_BALANCE}\nSymbol {SYMBOL} TF {TIMEFRAME}\nRisk ${RISK_PER_TRADE}/ไม้ x{LEVERAGE}\nATR SL x2.2 TP x1.5/3.0/4.5\nADX>25 RSI 55-72")
    while True:
        try:
            df = get_ohlcv()
            df = calc_indicators(df)
            last = df.iloc[-1]
            price = float(last["close"])
            rsi = float(last["rsi"]) if not pd.isna(last["rsi"]) else 50
            adx = float(last["adx"]) if not pd.isna(last["adx"]) else 0
            atr = float(last["atr"]) if not pd.isna(last["atr"]) else price*0.002
            
            portfolio["last_price"]=price
            portfolio["last_update"]=time.strftime("%H:%M:%S")
            print(f"GOLD SCAN {portfolio['last_update']} XAU ${price:.2f} RSI {rsi:.1f} ADX {adx:.1f} ATR {atr:.2f} Bal ${portfolio['balance']:.2f} Pos {portfolio['position'] is not None}", flush=True)
            
            paper_check_close(price)
            
            if portfolio["position"] is None and time.time()-last_signal>COOLDOWN_SEC:
                trend_up = last["plus_di"] > last["minus_di"]
                # สูตรทอง: ADX>25 RSI 55-72
                if adx>25 and 55<rsi<72 and trend_up:
                    entry=price
                    sl=entry - atr*2.2
                    tp1=entry + atr*1.5
                    tp2=entry + atr*3.0
                    tp3=entry + atr*4.5
                    amount=min(RISK_PER_TRADE, portfolio["balance"]*0.1)
                    portfolio["position"]={"side":"LONG","entry":entry,"amount":amount,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"opened_at":time.time()}
                    last_signal=time.time()
                    send_telegram(f"🚀 *GOLD SIGNAL LONG*\nXAU ${entry:.2f} RSI {rsi:.1f} ADX {adx:.1f} ATR {atr:.2f}\nTP1 ${tp1:.2f} TP2 ${tp2:.2f} TP3 ${tp3:.2f}\nSL ${sl:.2f}\nเปิด ${amount:.2f} x{LEVERAGE} พอร์ตทอง ${portfolio['balance']:.2f}")
        except Exception as e:
            print(f"GOLD Bot error {e}", flush=True)
            import traceback; traceback.print_exc()
        time.sleep(300)  # ทอง 1H เช็คทุก 5 นาทีพอ

@app.route("/")
def home():
    return f"GOLD Bot v9 LIVE - {SYMBOL} ${portfolio['last_price']} Bal ${portfolio['balance']:.2f} W{portfolio['wins']} L{portfolio['losses']} Updated {portfolio['last_update']}"

@app.route("/portfolio")
def port():
    return jsonify(portfolio)

@app.route("/health")
def health():
    return "OK", 200

threading.Thread(target=bot_loop, daemon=True).start()
print("Gold Thread started", flush=True)

if __name__=="__main__":
    port=int(os.environ.get("PORT",10000))
    app.run(host="0.0.0.0", port=port)
