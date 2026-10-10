import os, threading, time, requests
from flask import Flask
print("=== GOLD MINIMAL TEST ===", flush=True)
app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN","")
CHAT_ID = os.getenv("CHAT_ID","")

def send_tg(msg):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print(f"SKIP TG {msg[:50]}", flush=True)
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id":CHAT_ID,"text":msg}, timeout=10)
        print("TG SENT", flush=True)
    except Exception as e:
        print(f"TG err {e}", flush=True)

def loop():
    time.sleep(2)
    print("LOOP OK", flush=True)
    send_tg("Bot GOLD Render TEST LIVE! Flask+requests OK")

threading.Thread(target=loop, daemon=True).start()

@app.route("/")
def home():
    return "GOLD BOT TEST LIVE - Flask OK"

@app.route("/health")
def health():
    return "OK",200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
