"""
V80 SILVER LOWER FILTER - แก้เงียบ
V79 ADX28 Vol1.6 สูงเกิน Tr6 เอง WR33.3% PnL-1.15% Pos ไม่มี
ลดเป็น ADX22 Vol1.2 เท่า BTC ให้เทรดได้
"""

import requests, pandas as pd, numpy as np, os, time, json
from flask import Flask, jsonify
from datetime import datetime
import pytz, threading

DATA_DIR = "./data"
try:
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists("/mnt/data") and os.access("/mnt/data", os.W_OK):
        DATA_DIR = "/mnt/data"
except: pass

BOT_TOKEN = (os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID = (os.environ.get("CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
FLAG_FILE = os.path.join(DATA_DIR, "trading_enabled_silver.json")
OFFSET_FILE = os.path.join(DATA_DIR, "telegram_offset_silver.txt")

def load_trading():
    try:
        if os.path.exists(FLAG_FILE): return json.load(open(FLAG_FILE)).get("enabled", True)
    except: pass
    return True
def save_trading(en):
    try: json.dump({"enabled":en}, open(FLAG_FILE,'w'))
    except: pass

TRADING_ENABLED = load_trading()
app = Flask(__name__)
def thai_now(): return datetime.now(pytz.timezone('Asia/Bangkok'))
def thai_time(): return thai_now().strftime("%d/%m/%Y %H:%M ICT")
def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID: return False
    try:
        url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r=requests.post(url, json={"chat_id":CHAT_ID,"text":msg,"parse_mode":"HTML","disable_web_page_preview":True}, timeout=10)
        return r.status_code==200
    except: return False

def get_klines_silver(days=30):
    for sym in ["SILVER_USDT","AG_USDT","XAG_USDT"]:
        try:
            url=f"https://contract.mexc.com/api/v1/contract/kline/{sym}"
            r=requests.get(url, params={"interval":"Min15"}, timeout=5)
            j=r.json()
            if 'data' not in j: continue
            d=j['data']
            df=pd.DataFrame({'ot':d['time'],'o':d['open'],'h':d['high'],'l':d['low'],'c':d['close'],'v':d['vol']}) if 'time' in d else pd.DataFrame(d, columns=['ot','o','h','l','c','v'])
            df=df.tail(days*96)
            for col in ['o','h','l','c','v']: df[col]=df[col].astype(float)
            if len(df)>300: return df, sym
        except: continue
    try:
        r=requests.get("https://api.mexc.com/api/v3/klines", params={"symbol":"SILVERUSDT","interval":"15m","limit":1000}, timeout=5)
        arr=r.json()
        if isinstance(arr, list) and len(arr)>300:
            df=pd.DataFrame(arr, columns=['ot','o','h','l','c','v','ct','qv','n','taker_v','taker_qv','ig'])
            for col in ['o','h','l','c','v']: df[col]=df[col].astype(float)
            return df.tail(30*96), "SILVERUSDT-SPOT"
    except: pass
    return None, None

def calc_indicators(df):
    df['EMA12']=df['c'].ewm(span=12, adjust=False).mean()
    df['EMA26']=df['c'].ewm(span=26, adjust=False).mean()
    df['EMA50']=df['c'].ewm(span=50, adjust=False).mean()
    delta=df['c'].diff(); gain=delta.where(delta>0,0).rolling(14).mean(); loss=-delta.where(delta<0,0).rolling(14).mean()
    df['RSI']=100-(100/(1+gain/(loss.replace(0,0.001))))
    df['H-L']=df['h']-df['l']; df['H-pC']=(df['h']-df['c'].shift(1)).abs(); df['L-pC']=(df['l']-df['c'].shift(1)).abs()
    df['TR']=df[['H-L','H-pC','L-pC']].max(axis=1)
    df['H-pH']=df['h']-df['h'].shift(1); df['pL-L']=df['l'].shift(1)-df['l']
    df['+DM']=np.where((df['H-pH'] > df['pL-L']) & (df['H-pH'] > 0), df['H-pH'], 0.0)
    df['-DM']=np.where((df['pL-L'] > df['H-pH']) & (df['pL-L'] > 0), df['pL-L'], 0.0)
    df['TR14']=df['TR'].rolling(14).sum(); df['+DM14']=pd.Series(df['+DM']).rolling(14).sum(); df['-DM14']=pd.Series(df['-DM']).rolling(14).sum()
    df['+DI']=100*df['+DM14']/df['TR14']; df['-DI']=100*df['-DM14']/df['TR14']
    df['DX']=100*(df['+DI']-df['-DI']).abs()/(df['+DI']+df['-DI']).replace(0,0.001); df['ADX']=df['DX'].rolling(14).mean()
    df['TP']=(df['h']+df['l']+df['c'])/3; df['TPV']=df['TP']*df['v']; df['VWAP']=df['TPV'].rolling(20).sum()/df['v'].rolling(20).sum()
    df['V_SMA20']=df['v'].rolling(20).mean(); df['VolSpike']=df['v']/df['V_SMA20']
    return df.dropna()

def dist_pct(price, step): return abs(price-round(price/step)*step)/price*100

def run_bt_silver(df):
    # V80 LOWER FILTER: ลด ADX28->22 Vol1.6->1.2 เท่า BTC ให้เทรดได้
    # SILVER ผันผวนแรงกว่า BTC แต่ Filter สูงเกิน Tr6 เงียบ
    cfg={"tp":3.0,"sl":1.5,"max_hold":96,"adx":22,"di":18,"vol":1.2,"round_step":0.5,"round_pct":0.3,"short":True}
    # TP3.0 SL1.5 RR2.0 Hold24H ADX22 Vol1.2 = ลดลงจาก V79 ADX28 Vol1.6
    stats={"total":0,"wins":0,"losses":0,"pnl_sum":0.0,"max_dd":0,"skip":{"adx":0,"vol":0,"round":0}}
    bal=40.16; high=bal; pos=[]
    for i in range(200, len(df)):
        last=df.iloc[i]; price=float(last['c'])
        if last['ADX']<cfg["adx"]: stats["skip"]["adx"]+=1; continue
        if last['VolSpike']<cfg["vol"]: stats["skip"]["vol"]+=1; continue
        if dist_pct(price, cfg["round_step"])<cfg["round_pct"]: stats["skip"]["round"]+=1; continue
        up_trend = last['EMA12']>last['EMA26'] and last['EMA26']>last['EMA50'] and price>last['VWAP']
        down_trend = last['EMA12']<last['EMA26'] and last['EMA26']<last['EMA50'] and price<last['VWAP']
        up = last['+DI']>last['-DI'] and last['+DI']>cfg["di"] and up_trend
        down = last['-DI']>last['+DI'] and last['-DI']>cfg["di"] and down_trend and cfg["short"]
        body = abs(last['c']-last['o']); rng = last['h']-last['l']
        strong_bull = body > rng*0.3 and last['c']>last['o']
        strong_bear = body > rng*0.3 and last['o']>last['c']
        rsi_ok_long = 40 <= last['RSI'] <= 72
        rsi_ok_short = 28 <= last['RSI'] <= 62
        buy = up and strong_bull and rsi_ok_long
        sell = down and strong_bear and rsi_ok_short
        if not pos and buy: pos.append({"entry":price,"side":"long","idx":i})
        elif not pos and sell: pos.append({"entry":price,"side":"short","idx":i})
        if pos:
            entry=pos[0]['entry']; side=pos[0]['side']; hold=(i-pos[0]['idx'])*0.25
            pnl=(price-entry)/entry*100 if side=='long' else (entry-price)/entry*100
            reason=None
            if pnl>=cfg["tp"]: reason="TP"
            elif pnl<=-cfg["sl"]: reason="SL"
            elif hold>=cfg["max_hold"]: reason="HOLD"
            if reason:
                stats["total"]+=1
                if pnl>0: stats["wins"]+=1
                else: stats["losses"]+=1
                stats["pnl_sum"]+=pnl
                bal=bal*(1+pnl/100*0.1); high=max(high,bal)
                stats["max_dd"]=max(stats["max_dd"], (high-bal)/high*100 if high>0 else 0)
                pos=[]
    wr=(stats["wins"]/stats["total"]*100) if stats["total"]>0 else 0
    return stats, wr, bal, cfg

bt_results={}; bt_status="Idle"; LIVE_PRICE=0

def bt_job():
    global bt_results, bt_status, LIVE_PRICE
    bt_status="Running..."
    try:
        send_telegram(f"📊 [{thai_time()}] V80 SILVER LOWER FILTER เริ่ม BT 30D\nแก้เงียบ V79 ADX28 Vol1.6 Tr6 WR33.3% -> V80 ADX22 Vol1.2 ให้เทรดได้\nTP3.0 SL1.5 RR2.0 Hold24H...")
        df, sym = get_klines_silver(30)
        if df is None: bt_status="Fail"; send_telegram("🔴 SILVER ดึงกราฟไม่ได้"); return
        df=calc_indicators(df)
        LIVE_PRICE=float(df.iloc[-1]['c'])
        s,w,b,c=run_bt_silver(df)
        bt_results["SILVER_USDT"]={"wr":w,"stats":s,"balance":b,"cfg":c,"sym_used":sym,"live_price":LIVE_PRICE}
        bt_status="Done"
        emoji="🟢" if w>=60 and s['pnl_sum']>0 else "🟡" if w>=50 else "🔴"
        msg=f"{emoji} [{thai_time()}] V80 SILVER LOWER FILTER BT เสร็จ\n{sym} ${LIVE_PRICE:.2f}\nWR {w:.1f}% PnL {s['pnl_sum']:+.2f}% Tr {s['total']} Bal 40.16→{b:.2f}\nDD {s['max_dd']:.1f}% Skip ADX{s['skip']['adx']} Vol{s['skip']['vol']} Round{s['skip']['round']}\n"
        if w>=60 and s['pnl_sum']>0: msg+="✅ FINAL ผ่าน! WR60%+ PnL บวก ไม่เงียบแล้ว!\n"
        else: msg+=f"WR {w:.1f}% PnL {s['pnl_sum']:+.2f}% Tr {s['total']}\n"
        msg+="TP3.0 SL1.5 RR2.0 Hold24H ADX22 Vol1.2 เท่า BTC"
        send_telegram(msg)
    except Exception as e:
        bt_status=f"Error {e}"
        send_telegram(f"🔴 BT Error {e}")

def get_off():
    try:
        if os.path.exists(OFFSET_FILE): return int(open(OFFSET_FILE).read().strip())
    except: pass
    return 0
def save_off(o):
    try: open(OFFSET_FILE,'w').write(str(o))
    except: pass

def handle(text, cid):
    global TRADING_ENABLED
    if CHAT_ID and str(cid)!=str(CHAT_ID): return
    t=(text or "").lower().strip()
    if t in ["/stats","/bt"]:
        if bt_status=="Running...": send_telegram("⏳ SILVER LOWER FILTER กำลังรัน...")
        elif not bt_results:
            threading.Thread(target=bt_job, daemon=True).start()
            send_telegram("📊 เริ่ม BT V80 SILVER LOWER FILTER 30D รอ 15 วิ...")
        else:
            b=bt_results["SILVER_USDT"]; send_telegram(f"📊 SILVER {b['sym_used']} ${b['live_price']:.2f} WR {b['wr']:.1f}% PnL {b['stats']['pnl_sum']:+.2f}% Tr {b['stats']['total']}")
    elif t in ["/status"]:
        b=bt_results.get("SILVER_USDT")
        if b: send_telegram(f"📍 SILVER {b['sym_used']} ${b['live_price']:.2f} WR {b['wr']:.1f}% PnL {b['stats']['pnl_sum']:+.2f}% {'✅' if TRADING_ENABLED else '🛑'} Pos {'มี' if False else 'ไม่มี'}")
        else: send_telegram(f"📍 SILVER {bt_status} {'✅' if TRADING_ENABLED else '🛑'} /bt")
    elif t in ["/stop"]: TRADING_ENABLED=False; save_trading(False); send_telegram(f"🛑 ปิด SILVER {thai_time()}")
    elif t in ["/start"]: TRADING_ENABLED=True; save_trading(True); send_telegram(f"✅ เปิด SILVER {thai_time()}")

def poll():
    off=get_off()
    while True:
        try:
            if not BOT_TOKEN: time.sleep(10); continue
            r=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", params={"offset":off+1,"timeout":20}, timeout=25)
            if r.status_code!=200: time.sleep(5); continue
            data=r.json()
            if not data.get("ok"): time.sleep(3); continue
            for upd in data.get("result",[]):
                off=max(off, upd.get("update_id",0)); save_off(off)
                msg=upd.get("message") or {}; txt=msg.get("text",""); cid=msg.get("chat",{}).get("id")
                if txt: handle(txt, cid)
        except: time.sleep(5)

@app.route('/')
def home():
    b=bt_results.get("SILVER_USDT")
    if not b: return f"<h2>V80 SILVER LOWER FILTER {bt_status}</h2>"
    return f"<h2>SILVER WR {b['wr']:.1f}% PnL {b['stats']['pnl_sum']:+.2f}%</h2>"
@app.route('/health')
def health(): return jsonify({"status":"ok","version":"V80 SILVER LOWER FILTER","trading":TRADING_ENABLED,"bt":bt_results,"time":thai_time()})

send_telegram(f"🚀 [{thai_time()}] V80 SILVER LOWER FILTER Live\nแก้เงียบ V79 ADX28 Vol1.6 Tr6 WR33.3% -> V80 ADX22 Vol1.2 ให้เทรดได้\nพิมพ์ /bt /status")

threading.Thread(target=lambda: (time.sleep(3), bt_job()), daemon=True).start()
threading.Thread(target=poll, daemon=True).start()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
