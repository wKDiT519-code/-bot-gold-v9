"""
V78 SILVER FAST - แก้ BT ค้าง SILVER_USDT
- Symbol จริง SILVER_USDT【2124339121803360029†L20-L23】
- 3 ชั้น: contract -> spot -> ccxt
- FAST 15D
"""

import requests, pandas as pd, os, time, json
from flask import Flask, jsonify
from datetime import datetime
import pytz, threading, traceback

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
BAL_FILE = os.path.join(DATA_DIR, "silver_demo_balance.json")
POS_FILE = os.path.join(DATA_DIR, "silver_demo_position.json")

def load_trading():
    try:
        if os.path.exists(FLAG_FILE): return json.load(open(FLAG_FILE)).get("enabled", True)
    except: pass
    return True
def save_trading(en):
    try: json.dump({"enabled":en}, open(FLAG_FILE,'w'))
    except: pass

TRADING_ENABLED = load_trading()
DEMO_BALANCE=40.16
DEMO_POSITION=None
try:
    if os.path.exists(BAL_FILE): DEMO_BALANCE=json.load(open(BAL_FILE)).get("balance",40.16)
    if os.path.exists(POS_FILE): DEMO_POSITION=json.load(open(POS_FILE))
except: pass

print(f"=== V78 SILVER FAST START BAL={DEMO_BALANCE} ===")

app = Flask(__name__)
def thai_now(): return datetime.now(pytz.timezone('Asia/Bangkok'))
def thai_time(): return thai_now().strftime("%d/%m/%Y %H:%M ICT")
def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID: return False,"missing"
    try:
        url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r=requests.post(url, json={"chat_id":CHAT_ID,"text":msg,"parse_mode":"HTML","disable_web_page_preview":True}, timeout=10)
        print(f"[TELE SILVER] {r.status_code}")
        return r.status_code==200, r.text
    except Exception as e: print(e); return False,str(e)

def get_klines_fast(days=15):
    # 1. contract - SILVER_USDT ตัวจริง
    for sym in ["SILVER_USDT","SILVER/USDT","SILVER_USDT","XAG_USDT"]:
        try:
            print(f"[KLINE SILVER] Try {sym}")
            url=f"https://contract.mexc.com/api/v1/contract/kline/{sym}"
            r=requests.get(url, params={"interval":"Min15"}, timeout=5)
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
                print(f"[KLINE SILVER] {sym} OK {len(df)} last={df.iloc[-1]['c']}")
                return df, sym
        except Exception as e:
            print(f"[KLINE SILVER] {sym} fail {e}")

    # 2. spot SILVERUSDT
    try:
        print("[KLINE SILVER] Try spot SILVERUSDT")
        url="https://api.mexc.com/api/v3/klines"
        r=requests.get(url, params={"symbol":"SILVERUSDT","interval":"15m","limit":500}, timeout=5)
        arr=r.json()
        if isinstance(arr, list) and len(arr)>200:
            df=pd.DataFrame(arr, columns=['ot','o','h','l','c','v','ct','qv','n','taker_v','taker_qv','ig'])
            for col in ['o','h','l','c','v']: df[col]=df[col].astype(float)
            print(f"[KLINE SILVER SPOT] OK {len(df)}")
            return df, "SILVERUSDT-SPOT"
    except Exception as e:
        print(f"[KLINE SILVER SPOT] fail {e}")

    # 3. ccxt
    try:
        import ccxt
        print("[KLINE SILVER] Try ccxt SILVER/USDT")
        ex=ccxt.mexc({'enableRateLimit':True})
        # MEXC silver symbol in ccxt is SILVER/USDT
        for s in ['SILVER/USDT','XAG/USDT']:
            try:
                ohlcv=ex.fetch_ohlcv(s, '15m', limit=500)
                df=pd.DataFrame(ohlcv, columns=['ot','o','h','l','c','v'])
                for col in ['o','h','l','c','v']: df[col]=df[col].astype(float)
                if len(df)>200:
                    print(f"[KLINE SILVER CCXT] {s} OK")
                    return df, f"{s}-CCXT"
            except: continue
    except Exception as e:
        print(f"[KLINE CCXT] fail {e}")

    print("[KLINE SILVER] ALL FAILED")
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

def run_bt(df):
    cfg={"tp":3.0,"sl":1.5,"max_hold":24,"adx":28,"di":23,"vol":1.6,"round_step":0.5,"round_pct":0.3}
    stats={"total":0,"wins":0,"losses":0,"pnl_sum":0.0,"max_dd":0}
    bal=40.16; high=bal; pos=[]
    for i in range(200, len(df)):
        last=df.iloc[i]; price=float(last['c'])
        if last['ADX']<cfg["adx"]: continue
        if last['VolSpike']<cfg["vol"]: continue
        up=last['+DI']>last['-DI'] and last['+DI']>cfg["di"] and price>last['VWAP'] and last['EMA12']>last['EMA26']
        strong_bull=(last['c']-last['o'])>(last['h']-last['l'])*0.35
        if not pos and up and strong_bull and 45<=last['RSI']<=78:
            pos.append({"entry":price,"idx":i})
        if pos:
            entry=pos[0]['entry']; hold=(i-pos[0]['idx'])*0.25
            pnl=(price-entry)/entry*100
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
        send_telegram(f"⚪ [{thai_time()}] V78 SILVER FAST เริ่ม BT 15D\nดึง 3 ชั้น SILVER_USDT...")
        df, sym = get_klines_fast(15)
        if df is None:
            bt_status="Fail"; send_telegram(f"🔴 [{thai_time()}] SILVER ดึงกราฟไม่ได้ 3 ชั้น\nMEXC API อาจล่ม ลอง /bt ใหม่")
            return
        df=calc_indicators(df)
        LIVE_PRICE=float(df.iloc[-1]['c'])
        s,w,b,c=run_bt(df)
        bt_results["SILVER"]={"wr":w,"stats":s,"balance":b,"cfg":c,"sym_used":sym,"live_price":LIVE_PRICE}
        bt_status="Done"
        send_telegram(f"⚪ [{thai_time()}] V78 SILVER FAST เสร็จ ✅\n{sym} ${LIVE_PRICE:.2f} WR {w:.1f}% PnL {s['pnl_sum']:+.2f}% Tr {s['total']}\nBal 40.16→{b:.2f}")
    except Exception as e:
        bt_status=f"Error {e}"; traceback.print_exc()
        send_telegram(f"🔴 SILVER BT Error {e}")

def save_demo():
    try:
        json.dump({"balance":DEMO_BALANCE}, open(BAL_FILE,'w'))
        if DEMO_POSITION: json.dump(DEMO_POSITION, open(POS_FILE,'w'))
        else:
            if os.path.exists(POS_FILE): os.remove(POS_FILE)
    except: pass

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
        if bt_status=="Running...": send_telegram("⏳ SILVER BT กำลังรัน รอ 10 วิ")
        elif not bt_results:
            threading.Thread(target=bt_job, daemon=True).start()
            send_telegram("📊 เริ่ม SILVER BT FAST 15D รอ 10 วิ...")
        else:
            b=bt_results["SILVER"]; send_telegram(f"⚪ [{thai_time()}] {b['sym_used']} ${b['live_price']:.2f} WR {b['wr']:.1f}% PnL {b['stats']['pnl_sum']:+.2f}%")
    elif t in ["/status"]:
        b=bt_results.get("SILVER"); pos_txt=f"Long {DEMO_POSITION['entry']:.2f}" if DEMO_POSITION else "ไม่มี"
        if b: send_telegram(f"📍 [{thai_time()}] SILVER {b['sym_used']} ${b['live_price']:.2f} WR {b['wr']:.1f}% Bal {DEMO_BALANCE:.2f} Pos {pos_txt}")
        else: send_telegram(f"📍 SILVER {bt_status} Bal {DEMO_BALANCE:.2f} พิมพ์ /bt")
    elif t in ["/stop"]: TRADING_ENABLED=False; save_trading(False); send_telegram(f"🛑 ปิด SILVER {thai_time()}")
    elif t in ["/start"]: TRADING_ENABLED=True; save_trading(True); send_telegram(f"✅ เปิด SILVER Bal {DEMO_BALANCE:.2f}")
    elif t in ["/buy"]:
        if DEMO_POSITION: send_telegram(f"มีออเดอร์แล้ว {DEMO_POSITION['entry']}")
        else:
            df,_=get_klines_fast(1)
            price=float(df.iloc[-1]['c']) if df is not None else LIVE_PRICE or 50.0
            DEMO_POSITION={"side":"long","entry":price,"time":datetime.now().isoformat()}
            save_demo(); send_telegram(f"🧪 SILVER เปิด Long ${price:.2f} Bal {DEMO_BALANCE:.2f}")
    elif t in ["/close"]:
        if not DEMO_POSITION: send_telegram("ไม่มีออเดอร์")
        else:
            df,_=get_klines_fast(1)
            price=float(df.iloc[-1]['c']) if df is not None else LIVE_PRICE
            entry=DEMO_POSITION['entry']; pnl=(price-entry)/entry*100
            DEMO_BALANCE=DEMO_BALANCE*(1+pnl/100*0.1)
            send_telegram(f"⚪ ปิด ${entry:.2f}→${price:.2f} {pnl:+.2f}% Bal {DEMO_BALANCE:.2f}")
            DEMO_POSITION=None; save_demo()
    elif t in ["/reset"]: DEMO_BALANCE=40.16; DEMO_POSITION=None; save_demo(); send_telegram("🔄 รีเซ็ต 40.16")
    elif t in ["/help"]: send_telegram("/stats /bt FAST 15D\n/status ราคาสด\n/start /stop\n/buy /close\n/reset")

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
    b=bt_results.get("SILVER")
    if not b: return f"<h2>V78 SILVER FAST {bt_status}</h2>"
    return f"<h2>SILVER {b['sym_used']} ${b['live_price']:.2f} WR {b['wr']:.1f}%</h2>"
@app.route('/health')
def health(): return jsonify({"status":"ok","version":"V78 SILVER FAST","trading":TRADING_ENABLED,"bt":bt_results,"time":thai_time()})
@app.route('/test_tele')
def test(): ok,_=send_telegram(f"⚪ V78 FAST Test {thai_time()} {bt_status}"); return jsonify({"ok":ok})

send_telegram(f"🚀 [{thai_time()}] V78 SILVER FAST Live\nแก้ BT ค้าง SILVER_USDT 3 ชั้น\nพิมพ์ /bt /status")

threading.Thread(target=lambda: (time.sleep(3), bt_job()), daemon=True).start()
threading.Thread(target=poll, daemon=True).start()

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
