import os, threading, time
from flask import Flask
import urllib.request, json

print("=== GOLD ULTRA MINIMAL ===", flush=True)
app = Flask(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN","")
CHAT = os.getenv("CHAT_ID","")

def send(msg):
    if not TOKEN or not CHAT: 
        print(f"SKIP {msg}", flush=True)
        return
    try:
        data = json.dumps({"chat_id": CHAT, "text": msg}).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data, headers={"Content-Type":"application/json"})
        urllib.request.urlopen(req, timeout=10)
        print("TG OK", flush=True)
    except Exception as e:
        print(f"TG err {e}", flush=True)

def loop():
    time.sleep(3)
    print("LOOP LIVE", flush=True)
    send("Bot GOLD ULTRA MINIMAL LIVE! No requests needed - Render OK")

threading.Thread(target=loop, daemon=True).start()

@app.route("/")
def home():
    return "GOLD ULTRA MINIMAL LIVE"

@app.route("/health")
def h():
    return "OK",200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
