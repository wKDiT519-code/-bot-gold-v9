"""
V82 ADAPTIVE SILVER - สำหรับ SILVER โดยเฉพาะ
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
FLAG_FILE = os.path.join(DATA_DIR, "trading_enabled_silver_adaptive.json")
OFFSET_FILE = os.path.join(DATA_DIR, "telegram_offset_silver_adaptive.txt")
REGIME_FILE = os.path.join(DATA_DIR, "adaptive_regime_silver.json")

def load_trading():
    try:
        if os.path.exists(FLAG_FILE): return json.load(open(FLAG_FILE)).get("enabled", True)
    except: pass
    return True
def save_trading(en):
    try: json.dump({"enabled":en}, open(FLAG_FILE,'w'))
    except: pass
def save_regime(data):
    try: json.dump(data, open(REGIME_FILE,'w'))
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
    return None, None

def calc_indicators(df):
    df['SMA20']=df['c'].rolling(20).mean(); df['STD20']=df['c'].rolling(20).std()
    df['BB_UP']=df['SMA20']+2*df['STD20']; df['BB_LOW']=df['SMA20']-2*df['STD20']
    df['BB_WIDTH']=(df['BB_UP']-df['BB_LOW'])/df['SMA20']*100
    df['EMA12']=df['c'].ewm(span=12, adjust=False).mean(); df['EMA26']=df['c'].ewm(span=26, adjust=False).mean(); df['EMA50']=df['c'].ewm(span=50, adjust=False).mean()
    delta=df['c'].diff(); gain=delta.where(delta>0,0).rolling(14).mean(); loss=-delta.where(delta<0,0).rolling(14).mean()
    df['RSI']=100-(100/(1+gain/(loss.replace(0,0.001))))
    df['H-L']=df['h']-df['l']; df['H-pC']=(df['h']-df['c'].shift(1)).abs(); df['L-pC']=(df['l']-df['c'].shift(1)).abs(); df['TR']=df[['H-L','H-pC','L-pC']].max(axis=1)
    df['H-pH']=df['h']-df['h'].shift(1); df['pL-L']=df['l'].shift(1)-df['l']
    df['+DM']=np.where((df['H-pH'] > df['pL-L']) & (df['H-pH'] > 0), df['H-pH'], 0.0); df['-DM']=np.where((df['pL-L'] > df['H-pH']) & (df['pL-L'] > 0), df['pL-L'], 0.0)
    df['TR14']=df['TR'].rolling(14).sum(); df['+DM14']=pd.Series(df['+DM']).rolling(14).sum(); df['-DM14']=pd.Series(df['-DM']).rolling(14).sum()
    df['+DI']=100*df['+DM14']/df['TR14']; df['-DI']=100*df['-DM14']/df['TR14']; df['DX']=100*(df['+DI']-df['-DI']).abs()/(df['+DI']+df['-DI']).replace(0,0.001); df['ADX']=df['DX'].rolling(14).mean()
    df['TP']=(df['h']+df['l']+df['c'])/3; df['TPV']=df['TP']*df['v']; df['VWAP']=df['TPV'].rolling(20).sum()/df['v'].rolling(20).sum()
    df['V_SMA20']=df['v'].rolling(20).mean(); df['VolSpike']=df['v']/df['V_SMA20']
    return df.dropna()

def detect_regime(df):
    recent = df.tail(50); avg_adx = recent['ADX'].mean(); avg_bb_width = recent['BB_WIDTH'].mean(); avg_vol = recent['VolSpike'].mean()
    if avg_adx > 25 and avg_bb_width > 3.0 and avg_vol > 1.2:
        regime = "TRENDING"; strategy = "Trend TP3 SL1.5"; reason = f"ADX {avg_adx:.1f}>25 BB {avg_bb_width:.1f}%>3% Vol {avg_vol:.1f}>1.2 มีเทรนด์"
    elif avg_adx < 22 and avg_bb_width < 3.0:
        regime = "SIDEWAY"; strategy = "MeanRev BB+RSI TP1.5 SL0.8"; reason = f"ADX {avg_adx:.1f}<22 BB {avg_bb_width:.1f}%<3% Sideway $55-$58"
    else:
        regime = "WAIT"; strategy = "WAIT ไม่เทรด"; reason = f"ADX {avg_adx:.1f} BB {avg_bb_width:.1f}% ไม่ชัด ถ้าออกรบแล้วไม่ชนะไม่ออกดีกว่า"
    return regime, strategy, reason, avg_adx, avg_bb_width

def run_bt_adaptive(df):
    stats={"total":0,"wins":0,"losses":0,"pnl_sum":0.0,"max_dd":0,"trend_tr":0,"sideway_tr":0,"wait_skip":0}
    bal=40.16; high=bal; pos=[]; current_regime="UNKNOWN"
    for i in range(200, len(df)):
        last=df.iloc[i]
        if i % 96 == 0 or current_regime=="UNKNOWN":
            window = df.iloc[max(0,i-50):i]; avg_adx = window['ADX'].mean(); avg_bb_width = window['BB_WIDTH'].mean()
            if avg_adx > 25 and avg_bb_width > 3.0: current_regime="TRENDING"
            elif avg_adx < 22 and avg_bb_width < 3.0: current_regime="SIDEWAY"
            else: current_regime="WAIT"
        if current_regime=="WAIT": stats["wait_skip"]+=1; continue
        price=float(last['c'])
        if current_regime=="TRENDING":
            up_trend = last['EMA12']>last['EMA26'] and last['EMA26']>last['EMA50'] and price>last['VWAP']
            down_trend = last['EMA12']<last['EMA26'] and last['EMA26']<last['EMA50'] and price<last['VWAP']
            up = last['+DI']>last['-DI'] and last['+DI']>18 and up_trend; down = last['-DI']>last['+DI'] and last['-DI']>18 and down_trend
            body = abs(last['c']-last['o']); rng = last['h']-last['l']
            buy = up and body > rng*0.3 and last['c']>last['o'] and 40 <= last['RSI'] <= 72
            sell = down and body > rng*0.3 and last['o']>last['c'] and 28 <= last['RSI'] <= 62
            tp, sl, max_hold = 3.0, 1.5, 96
        else:
            near_bb_low = price <= last['BB_LOW']*1.02; near_bb_up = price >= last['BB_UP']*0.98
            buy = near_bb_low and last['RSI'] <= 40; sell = near_bb_up and last['RSI'] >= 60
            tp, sl, max_hold = 1.5, 0.8, 48
        if not pos and buy: pos.append({"entry":price,"side":"long","idx":i,"regime":current_regime})
        elif not pos and sell: pos.append({"entry":price,"side":"short","idx":i,"regime":current_regime})
        if pos:
            entry=pos[0]['entry']; side=pos[0]['side']; regime=pos[0]['regime']; hold=(i-pos[0]['idx'])*0.25
            pnl=(price-entry)/entry*100 if side=='long' else (entry-price)/entry*100
            reason=None
            if pnl>=tp: reason="TP"
            elif pnl<=-sl: reason="SL"
            elif hold>=max_hold: reason="HOLD"
            if reason:
                stats["total"]+=1
                if regime=="TRENDING": stats["trend_tr"]+=1
                else: stats["sideway_tr"]+=1
                if pnl>0: stats["wins"]+=1
                else: stats["losses"]+=1
                stats["pnl_sum"]+=pnl; bal=bal*(1+pnl/100*0.1); high=max(high,bal)
                stats["max_dd"]=max(stats["max_dd"], (high-bal)/high*100 if high>0 else 0); pos=[]
    wr=(stats["wins"]/stats["total"]*100) if stats["total"]>0 else 0
    return stats, wr, bal

bt_results={}; bt_status="Idle"; LIVE_PRICE=0; CURRENT_REGIME={}
def bt_job():
    global bt_results, bt_status, LIVE_PRICE, CURRENT_REGIME
    bt_status="Running..."
    try:
        send_telegram(f"📊 [{thai_time()}] V82 ADAPTIVE SILVER เริ่ม BT 30D\nTRENDING ADX>25 BB>3% -> Trend TP3 SL1.5\nSIDEWAY ADX<22 BB<3% -> MeanRev BB RSI TP1.5 SL0.8")
        df, sym = get_klines_silver(30)
        if df is None: bt_status="Fail"; send_telegram("🔴 SILVER ดึงกราฟไม่ได้"); return
        df=calc_indicators(df); LIVE_PRICE=float(df.iloc[-1]['c'])
        regime, strategy, reason, avg_adx, avg_bb_width = detect_regime(df)
        CURRENT_REGIME={"regime":regime,"strategy":strategy,"reason":reason,"adx":avg_adx,"bb_width":avg_bb_width,"price":LIVE_PRICE}; save_regime(CURRENT_REGIME)
        s,w,b=run_bt_adaptive(df); bt_results["SILVER_USDT"]={"wr":w,"stats":s,"balance":b,"regime":CURRENT_REGIME,"sym_used":sym,"live_price":LIVE_PRICE}; bt_status="Done"
        emoji="🟢" if w>=60 and s['pnl_sum']>0 else "🟡" if w>=50 else "🔴"
        msg=f"{emoji} [{thai_time()}] V82 ADAPTIVE SILVER BT เสร็จ\n{sym} ${LIVE_PRICE:.2f} ตอนนี้ {regime}\n{reason}\nกลยุทธ์: {strategy}\n\nBT 30D: WR {w:.1f}% PnL {s['pnl_sum']:+.2f}% Tr {s['total']} (Trend {s['trend_tr']} Sideway {s['sideway_tr']} Wait {s['wait_skip']})\nBal 40.16→{b:.2f} DD {s['max_dd']:.1f}%"
        send_telegram(msg)
    except Exception as e:
        bt_status=f"Error {e}"; send_telegram(f"🔴 BT Error {e}")

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
    if t in ["/stats","/bt","/regime"]:
        if bt_status=="Running...": send_telegram("⏳ ADAPTIVE SILVER กำลังรัน...")
        elif not bt_results:
            threading.Thread(target=bt_job, daemon=True).start(); send_telegram("📊 เริ่ม BT V82 ADAPTIVE SILVER 30D...")
        else:
            b=bt_results["SILVER_USDT"]; r=b['regime']; send_telegram(f"📊 ADAPTIVE SILVER {b['sym_used']} ${b['live_price']:.2f}\nตอนนี้ {r['regime']} {r['reason']}\nกลยุทธ์: {r['strategy']}\nBT WR {b['wr']:.1f}% PnL {b['stats']['pnl_sum']:+.2f}%")
    elif t in ["/status"]:
        if CURRENT_REGIME:
            r=CURRENT_REGIME; send_telegram(f"📍 SILVER [{thai_time()}] {r['regime']} {r['reason']}\nกลยุทธ์: {r['strategy']} {'✅' if TRADING_ENABLED else '🛑'}")
        else:
            send_telegram(f"📍 SILVER ADAPTIVE {bt_status} {'✅' if TRADING_ENABLED else '🛑'} /bt /regime")
    elif t in ["/stop"]: TRADING_ENABLED=False; save_trading(False); send_telegram(f"🛑 ปิด ADAPTIVE SILVER {thai_time()}")
    elif t in ["/start"]: TRADING_ENABLED=True; save_trading(True); send_telegram(f"✅ เปิด ADAPTIVE SILVER {thai_time()}")

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
    if not b: return f"<h2>V82 ADAPTIVE SILVER {bt_status}</h2>"
    r=b['regime']; return f"<h2>SILVER ADAPTIVE {r['regime']} WR {b['wr']:.1f}%</h2>"
@app.route('/health')
def health(): return jsonify({"status":"ok","version":"V82 ADAPTIVE SILVER","trading":TRADING_ENABLED,"bt":bt_results,"regime":CURRENT_REGIME,"time":thai_time()})

send_telegram(f"🚀 [{thai_time()}] V82 ADAPTIVE SILVER Live\nTRENDING ADX>25 BB>3% -> Trend\nSIDEWAY ADX<22 BB<3% -> MeanRev\nWAIT -> ไม่เทรด ถ้าออกรบแล้วไม่ชนะไม่ออกดีกว่า\n/bt /regime /status")
threading.Thread(target=lambda: (time.sleep(3), bt_job()), daemon=True).start()
threading.Thread(target=poll, daemon=True).start()
if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
