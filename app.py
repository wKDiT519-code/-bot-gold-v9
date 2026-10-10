
import os, threading, time, json, urllib.request
from flask import Flask
from datetime import datetime
import pytz

print("=== BOT GOLD V168 FULL - RENDER ===", flush=True)
app = Flask(__name__)

# ENV
TOKEN = os.getenv("TELEGRAM_TOKEN","")
CHAT = os.getenv("CHAT_ID","")
# ใช้ CHAT_ID เดียวกับที่ ULTRA MINIMAL ใช้

def send_tg(msg):
    if not TOKEN or not CHAT:
        print(f"SKIP TG {msg[:100]}", flush=True)
        return
    try:
        data = json.dumps({"chat_id": CHAT, "text": msg, "parse_mode":"HTML"}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data, headers={"Content-Type":"application/json"})
        urllib.request.urlopen(req, timeout=15)
        print(f"TG SENT {msg[:80]}", flush=True)
    except Exception as e:
        print(f"TG ERR {e}", flush=True)

# ลอง import ccxt ถ้ามี
try:
    import ccxt
    HAS_CCXT = True
    print("CCXT OK", flush=True)
except:
    HAS_CCXT = False
    print("CCXT NOT INSTALLED - using public API", flush=True)

def get_gold_price():
    # ถ้ามี ccxt ใช้ ccxt
    if HAS_CCXT:
        try:
            ex = ccxt.mexc()
            t = ex.fetch_ticker('XAUT/USDT')
            return float(t['last'])
        except Exception as e:
            print(f"CCXT err {e}", flush=True)
    # fallback ใช้ MEXC public API ไม่ต้องใช้ ccxt
    try:
        url = "https://api.mexc.com/api/v3/ticker/price?symbol=XAUTUSDT"
        with urllib.request.urlopen(url, timeout=10) as r:
            d = json.loads(r.read())
            return float(d['price'])
    except Exception as e:
        print(f"Price err {e}", flush=True)
        return None

def bot_loop():
    time.sleep(5)
    send_tg("🚀 <b>Bot GOLD V168 LIVE on Render!</b>\n✅ ULTRA MINIMAL -> FULL\n⏰ Monitoring XAU/USDT [MEXC]")
    last_price = 0
    while True:
        try:
            tz = pytz.timezone('Asia/Bangkok')
            now = datetime.now(tz)
            price = get_gold_price()
            if price:
                print(f"[{now.strftime('%H:%M:%S')}] XAUT {price}", flush=True)
                # ส่งทุกชั่วโมง หรือถ้าราคาเปลี่ยนเยอะ
                if abs(price - last_price) > 5 or now.minute == 0:
                    # ไม่ spam ถ้าเปลี่ยนนิดเดียว
                    if now.minute == 0 or last_price == 0:
                        msg = f"⏰ <b>[{now.strftime('%d/%m/%Y %H:%M ICT')}] XAUT/USDT {price:,.2f}$</b>\n"
                        msg += f"ว่าง - ไม่มีไม้ค้าง 💰 ราคาปัจจุบัน"
                        send_tg(msg)
                    last_price = price
            time.sleep(60)
        except Exception as e:
            print(f"LOOP ERR {e}", flush=True)
            time.sleep(60)

threading.Thread(target=bot_loop, daemon=True).start()

@app.route("/")
def home():
    return "GOLD V168 FULL LIVE - Render OK"

@app.route("/health")
def health():
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
