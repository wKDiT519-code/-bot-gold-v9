"""
V77 SILVER DEMO FIXED - แก้ Symbol SILVER_USDT (ของจริง MEXC)
- Symbol ที่ถูก: SILVER_USDT = SILVER(XAG)USDT Perpetual【2124339121803360029†L20-L23】
"""

import requests, pandas as pd, os, time, json
from flask import Flask, jsonify
from datetime import datetime
import pytz
import threading

DATA_DIR = "./data"
try:
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists("/mnt/data") and os.access("/mnt/data", os.W_OK):
        DATA_DIR = "/mnt/data"
except: pass

BOT_TOKEN = (os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
CHAT_ID = (os.environ.get("CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
FLAG_FILE = os.path.join(DATA_DIR, "silver_trading_enabled.json")
OFFSET_FILE = os.path.join(DATA_DIR, "silver_offset.txt")
DEMO_BAL_FILE = os.path.join(DATA_DIR, "silver_demo_balance.json")
POS_FILE = os.path.join(DATA_DIR, "silver_demo_position.json")

def load_trading():
    try:
        if os.path.exists(FLAG_FILE): return json.load(open(FLAG_FILE)).get("enabled", True)
    except: pass
    return True
def save_trading(en):
    try: json.dump({"enabled":en,"updated":datetime.now().isoformat()}, open(FLAG_FILE,'w'))
    except: pass

TRADING_ENABLED = load_trading()
DEMO_BALANCE = 40.16
DEMO_POSITION = None
try:
    if os.path.exists(DEMO_BAL_FILE): DEMO_BALANCE = json.load(open(DEMO_BAL_FILE)).get("balance", 40.16)
except: pass
try:
    if os.path.exists(POS_FILE): DEMO_POSITION = json.load(open(POS_FILE))
except: pass

print(f"=== V77 FIXED START BAL={DEMO_BALANCE} ===")

app = Flask(__name__)
def thai_now(): return datetime.now(pytz.timezone('Asia/Bangkok'))
def thai_time(): return thai_now().strftime("%d/%m/%Y %H:%M ICT")
def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID: return False,"missing"
    try:
        url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r=requests.post(url, json={"chat_id":CHAT_ID,"text":msg,"parse_mode":"HTML","disable_web_page_preview":True}, timeout=15)
        print(f"[TELE] {r.status_code}")
        return r.status_code==200, r.text
    except Exception as e: print(e); return False,str(e)

def get_klines_fixed(symbol="SILVER_USDT", interval="Min15", days=30):
    # ลอง SILVER_USDT ก่อน (ตัวจริง MEXC)
    symbols_try = ["SILVER_USDT", "SILVER/USDT", "XAG_USDT", "AG_USDT", "XAGUSDT", "SILVERUSDT"]
    for sym in symbols_try:
        try:
            url=f"https://contract.mexc.com/api/v1/contract/kline/{sym}"
            r=requests.get(url, params={"interval":interval}, timeout=10)
            j=r.json()
            if 'data' not in j: continue
            d=j['data']
            if 'time' in d:
                df=pd.DataFrame({'ot':d['time'],'o':d['open'],'h':d['high'],'l':d['low'],'c':d['close'],'v':d['vol']})
            else:
                df=pd.DataFrame(d, columns=['ot','o','h','l','c','v'])
            df=df.tail(days*96)
            for col in ['o','h','l','c','v']: df[col]=df[col].astype(float)
            if len(df)>200:
                print(f"[KLINE FIXED] {sym} OK {len(df)} last={df.iloc[-1]['c']}")
                return df, sym
        except Exception as e:
            print(f"[KLINE] {sym} fail {e}")
            continue

    # Fallback: ลอง spot API
    try:
        url="https://api.mexc.com/api/v3/klines"
        params={"symbol":"SILVERUSDT","interval":"15m","limit":500}
        r=requests.get(url, params=params, timeout=10)
        arr=r.json()
        if isinstance(arr, list) and len(arr)>200:
            df=pd.DataFrame(arr, columns=['ot','o','h','l','c','v','ct','qv','n','taker_v','taker_qv','ig'])
            for col in ['o','h','l','c','v']: df[col]=df[col].astype(float)
            print(f"[KLINE SPOT] SILVERUSDT OK {len(df)}")
            return df, "SILVERUSDT-SPOT"
    except Exception as e:
        print(f"[KLINE SPOT] fail {e}")

    return None, None

def calc_indicators(df):
    df['EMA12']=df['c'].ewm(span=12, adjust=False).mean()
    df['EMA26']=df['c'].ewm(span=26, adjust=False).mean()
    delta=df['c'].diff(); gain=delta.where(delta>0,0).rolling(14).mean(); loss=-delta.where(delta<0,0).rolling(14).mean()
    df['RSI']=100-(100/(1+gain/(loss.replace(0,0.001))))
    tr1=df['h']-df['l']; tr2=(df['h']-df['c'].shift()).abs(); tr3=(df['l']-df['c'].shift()).abs()
    df['TR']=pd.concat([tr1,tr2,tr3], axis=1).max(axis=1)
    df['+DM']=df.apply(lambda x: x['h']-x['h'].shift() if (x['h']-x['h'].shift())>(x['l'].shift()-x['l']) and (x['h']-x['h'].shift())>0 else 0, axis=1)
    df['-DM']=df.apply(lambda x: x['l'].shift()-x['l'] if (x['l'].shift()-x['l'])>(x['h']-x['h'].shift()) and (x['l'].shift()-x['l'])>0 else 0, axis=1)
    df['TR14']=df['TR'].rolling(14).sum(); df['+DM14']=df['+DM'].rolling(14).sum(); df['-DM14']=df['-DM'].rolling(14).sum()
    df['+DI']=100*df['+DM14']/df['TR14']; df['-DI']=100*df['-DM14']/df['TR14']
    df['DX']=100*(df['+DI']-df['-DI']).abs()/(df['+DI']+df['-DI']); df['ADX']=df['DX'].rolling(14).mean()
    df['TP']=(df['h']+df['l']+df['c'])/3; df['TPV']=df['TP']*df['v']; df['VWAP']=df['TPV'].rolling(20).sum()/df['v'].rolling(20).sum()
    df['V_SMA20']=df['v'].rolling(20).mean(); df['VolSpike']=df['v']/df['V_SMA20']
    return df.dropna()

def dist_pct(price, step): return abs(price-round(price/step)*step)/price*100

def run_bt_silver(df):
    cfg={"tp":3.0,"sl":1.5,"max_hold":24,"adx":28,"di":23,"vol":1.6,"round_step":0.5,"round_pct":0.3,"short":False}
    stats={"total":0,"wins":0,"losses":0,"pnl_sum":0.0,"max_dd":0,"skip":{"adx":0,"vol":0,"round":0}}
    bal=40.16; high=bal; pos=[]
    for i in range(200, len(df)):
        last=df.iloc[i]; price=float(last['c'])
        if last['ADX']<cfg["adx"]: stats["skip"]["adx"]+=1; continue
        if last['VolSpike']<cfg["vol"]: stats["skip"]["vol"]+=1; continue
        # Silver round 0.5$ (เช่น 50.0, 50.5)
        if dist_pct(price, cfg["round_step"])<cfg["round_pct"]: stats["skip"]["round"]+=1; continue
        up=last['+DI']>last['-DI'] and last['+DI']>cfg["di"] and price>last['VWAP'] and last['EMA12']>last['EMA26']
        strong_bull=(last['c']-last['o'])>(last['h']-last['l'])*0.35
        rsi_up=45<=last['RSI']<=78
        buy=up and strong_bull and rsi_up
        if not pos and buy: pos.append({"entry":price,"idx":i})
        if pos:
            entry=pos[0]['entry']; hold=(i-pos[0]['idx'])*0.25
            pnl=(price-entry)/entry*100
            reason=None
            if pnl>=cfg["tp"]: reason=f"TP {cfg['tp']}%"
            elif pnl<=-cfg["sl"]: reason=f"SL -{cfg['sl']}%"
            elif hold>=cfg["max_hold"]: reason=f"HOLD"
            if reason:
                stats["total"]+=1
                if pnl>0: stats["wins"]+=1
                else: stats["losses"]+=1
                stats["pnl_sum"]+=pnl
                bal=bal*(1+pnl/100*0.1); high=max(high,bal)
                dd=(high-bal)/high*100 if high>0 else 0
                stats["max_dd"]=max(stats["max_dd"],dd)
                pos=[]
    wr=(stats["wins"]/stats["total"]*100) if stats["total"]>0 else 0
    return stats, wr, bal, cfg

bt_results={}; bt_status="Starting..."; LIVE_PRICE=0

def bt_and_demo():
    global bt_results, bt_status, LIVE_PRICE, DEMO_POSITION
    bt_status="Running SILVER FIXED..."
    send_telegram(f"⚪ [{thai_time()}] V77 FIXED เริ่ม\nSymbol: SILVER_USDT (ตัวจริง MEXC)\nกำลังดึงกราฟ...")

    df, sym_used = get_klines_fixed("SILVER_USDT","Min15",30)
    if df is not None:
        df=calc_indicators(df)
        LIVE_PRICE=float(df.iloc[-1]['c'])
        s,w,b,c=run_bt_silver(df)
        bt_results["XAGUSDT"]={"wr":w,"stats":s,"balance":b,"cfg":c,"candles":len(df),"sym_used":sym_used,"live_price":LIVE_PRICE}
    else:
        bt_results["XAGUSDT"]={"wr":0,"stats":{"total":0,"wins":0,"losses":0,"pnl_sum":0,"max_dd":0,"skip":{}},"balance":40.16,"cfg":{},"candles":0,"live_price":0}
        send_telegram(f"🔴 [{thai_time()}] V77 ดึงกราฟ SILVER ไม่ได้ ลองเช็ค API")

    bt_status="Done"
    res=bt_results["XAGUSDT"]
    msg=f"⚪ [{thai_time()}] V77 FIXED BT เสร็จ | {'✅' if TRADING_ENABLED else '🛑'}\n\n"
    status="✅ ผ่าน" if res['wr']>=60 and res['stats']['pnl_sum']>0 else "⚪ เทส"
    emoji="🟢" if res['wr']>=60 else "⚪"
    msg+=f"{emoji} SILVER_USDT {status}\nSymbol จริง: {res.get('sym_used')}\nPrice: ${res.get('live_price',0):.2f}\nTrades {res['stats']['total']} WR {res['wr']:.1f}% PnL {res['stats']['pnl_sum']:+.2f}%\nBal 40.16→{res['balance']:.2f} DD {res['stats']['max_dd']:.1f}%\n\n"
    msg+=f"Demo Bal: {DEMO_BALANCE:.2f}\nพิมพ์ /status /buy"
    send_telegram(msg)

def save_demo():
    try:
        json.dump({"balance":DEMO_BALANCE}, open(DEMO_BAL_FILE,'w'))
        if DEMO_POSITION: json.dump(DEMO_POSITION, open(POS_FILE,'w'))
        else:
            if os.path.exists(POS_FILE): os.remove(POS_FILE)
    except: pass

def demo_loop():
    global DEMO_BALANCE, DEMO_POSITION, LIVE_PRICE
    print("[DEMO] loop start")
    while True:
        try:
            time.sleep(60)
            if not TRADING_ENABLED: continue
            df,_=get_klines_fixed("SILVER_USDT","Min1",1)
            if df is None: continue
            df=calc_indicators(df)
            last=df.iloc[-1]; price=float(last['c']); LIVE_PRICE=price
            if DEMO_POSITION:
                entry=DEMO_POSITION['entry']; pnl=(price-entry)/entry*100
                cfg=bt_results.get("XAGUSDT",{}).get("cfg",{"tp":3.0,"sl":1.5,"max_hold":24})
                hold=(datetime.now()-datetime.fromisoformat(DEMO_POSITION['time'])).total_seconds()/3600 if 'time' in DEMO_POSITION else 0
                reason=None
                if pnl>=cfg["tp"]: reason="TP"
                elif pnl<=-cfg["sl"]: reason="SL"
                elif hold>=cfg["max_hold"]: reason="HOLD"
                if reason:
                    DEMO_BALANCE=DEMO_BALANCE*(1+pnl/100*0.1); save_demo()
                    send_telegram(f"⚪ [{thai_time()}] SILVER DEMO ปิด {pnl:+.2f}% {reason}\nEntry {entry:.2f}→{price:.2f} Bal {DEMO_BALANCE:.2f}")
                    DEMO_POSITION=None; save_demo()
            else:
                up=last['+DI']>last['-DI'] and last['+DI']>23 and price>last['VWAP'] and last['EMA12']>last['EMA26'] and last['ADX']>28 and last['VolSpike']>1.6 and 45<=last['RSI']<=78
                if up:
                    DEMO_POSITION={"side":"long","entry":price,"time":datetime.now().isoformat()}
                    save_demo()
                    send_telegram(f"⚪ [{thai_time()}] SILVER DEMO เปิด Long ${price:.2f} ADX {last['ADX']:.1f}")
        except Exception as e:
            print(e); time.sleep(10)

def get_off():
    try:
        if os.path.exists(OFFSET_FILE): return int(open(OFFSET_FILE).read().strip())
    except: pass
    return 0
def save_off(o):
    try: open(OFFSET_FILE,'w').write(str(o))
    except: pass

def handle(text, cid):
    global TRADING_ENABLED, DEMO_BALANCE, DEMO_POSITION
    if CHAT_ID and str(cid)!=str(CHAT_ID): return
    t=(text or "").lower().strip()
    if t in ["/stats","/bt"]:
        if bt_status!="Done": send_telegram(f"⏳ {bt_status}")
        else:
            r=bt_results["XAGUSDT"]
            send_telegram(f"⚪ [{thai_time()}] SILVER FIXED V77\n{ r.get('sym_used')} ${r.get('live_price',0):.2f}\nWR {r['wr']:.1f}% PnL {r['stats']['pnl_sum']:+.2f}% Tr {r['stats']['total']}\nDemo {DEMO_BALANCE:.2f} {'✅' if TRADING_ENABLED else '🛑'}")
    elif t in ["/status","/demo"]:
        pos_txt=f"Long {DEMO_POSITION['entry']:.2f}" if DEMO_POSITION else "ไม่มีออเดอร์"
        r=bt_results.get("XAGUSDT",{})
        send_telegram(f"📍 [{thai_time()}] SILVER FIXED STATUS\nTrading {'✅' if TRADING_ENABLED else '🛑'}\nDemo Bal {DEMO_BALANCE:.2f}\nPos: {pos_txt}\nLive: ${LIVE_PRICE:.2f} ({r.get('sym_used','SILVER_USDT')})\nBT WR {r.get('wr',0):.1f}%\n/stop /start /buy")
    elif t in ["/stop","/ปิดบอท"]:
        TRADING_ENABLED=False; save_trading(False); send_telegram(f"🛑 [{thai_time()}] ปิด SILVER DEMO")
    elif t in ["/start","/เปิดบอท"]:
        TRADING_ENABLED=True; save_trading(True); send_telegram(f"✅ [{thai_time()}] เปิด SILVER DEMO Bal {DEMO_BALANCE:.2f}")
    elif t in ["/buy","/long"]:
        if DEMO_POSITION: send_telegram(f"มีออเดอร์แล้ว {DEMO_POSITION['entry']:.2f}")
        else:
            df,_=get_klines_fixed("SILVER_USDT","Min1",1)
            price=float(df.iloc[-1]['c']) if df is not None else LIVE_PRICE or 50.0
            DEMO_POSITION={"side":"long","entry":price,"time":datetime.now().isoformat()}
            save_demo()
            send_telegram(f"🧪 [{thai_time()}] SILVER FIXED เทสเปิด Long ${price:.2f} Bal {DEMO_BALANCE:.2f}")
    elif t in ["/close","/sell"]:
        if not DEMO_POSITION: send_telegram("ไม่มีออเดอร์")
        else:
            df,_=get_klines_fixed("SILVER_USDT","Min1",1)
            price=float(df.iloc[-1]['c']) if df is not None else LIVE_PRICE
            entry=DEMO_POSITION['entry']; pnl=(price-entry)/entry*100
            DEMO_BALANCE=DEMO_BALANCE*(1+pnl/100*0.1)
            send_telegram(f"⚪ ปิด ${entry:.2f}→${price:.2f} {pnl:+.2f}% Bal {DEMO_BALANCE:.2f}")
            DEMO_POSITION=None; save_demo()
    elif t in ["/reset"]:
        DEMO_BALANCE=40.16; DEMO_POSITION=None; save_demo(); send_telegram(f"🔄 รีเซ็ต Bal 40.16")
    elif t in ["/help"]:
        send_telegram("📖 V77 FIXED\n/stats BT\n/status Bal+Price\n/start /stop\n/buy เทส Long\n/close ปิด\n/reset รีเซ็ต")

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
        except Exception as e: print(e); time.sleep(5)

@app.route('/')
def home():
    r=bt_results.get("XAGUSDT")
    if not r: return f"<h2>V77 FIXED {bt_status}</h2>"
    return f"<h2>V77 FIXED {r.get('sym_used')} ${r.get('live_price',0):.2f} WR {r['wr']:.1f}% Bal {DEMO_BALANCE:.2f}</h2>"

@app.route('/health')
def health(): return jsonify({"status":"ok","version":"V77 FIXED SILVER_USDT","trading":TRADING_ENABLED,"balance":DEMO_BALANCE,"bt":bt_results,"time":thai_time()})
@app.route('/test_tele')
def test(): ok,_=send_telegram(f"⚪ V77 FIXED Test {thai_time()} Bal {DEMO_BALANCE:.2f}"); return jsonify({"ok":ok})

send_telegram(f"🚀 [{thai_time()}] V77 FIXED Live\nSILVER_USDT ตัวจริง MEXC\nBal {DEMO_BALANCE:.2f} (เดโม่)\nพิมพ์ /status /buy")

threading.Thread(target=lambda: (time.sleep(5), bt_and_demo()), daemon=True).start()
threading.Thread(target=poll, daemon=True).start()
threading.Thread(target=demo_loop, daemon=True).start()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
