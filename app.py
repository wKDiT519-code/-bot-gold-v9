import requests, pandas as pd, os, time, threading, ccxt
from flask import Flask
from datetime import datetime, timezone
import pytz

# === ENV ===
MEXC_API_KEY = os.environ.get("MEXC_API_KEY", "").strip()
MEXC_API_SECRET = os.environ.get("MEXC_API_SECRET", "").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
CHAT_ID = os.environ.get("CHAT_ID", "").strip()

# === CONFIG V6 SILVER EDITION - ปรับจาก GOLD สำหรับนิสัย SILVER ===
SYMBOL = "SILVER_USDT"
SYMBOL_CCXT = "SILVER/USDT:USDT"
# MEXC ใช้ SILVER, บางที่เรียก XAG
SYMBOL_FALLBACKS = ["SILVER/USDT:USDT", "SILVER_USDT", "XAG/USDT:USDT", "XAG_USDT", "XAG/USDT", "SILVER/USDT:USDT:USDT"]
RENDER_URL = "https://v6-cloud-bot-1.onrender.com"
INTERVAL = "15m"

# === SILVER ADJUSTED - ซิ่งกว่า GOLD 1.5x ===
ORDER_PERCENT = 6
LEVERAGE = 3              # จาก 5 -> 3 ลดความเสี่ยง Silver เหวี่ยงแรง
TP_PCT = 3.5              # จาก 2.5 -> 3.5
SL_PCT = 1.0              # จาก 0.6 -> 1.0 กันไส้
TRAIL_START_PCT = 0.7     # จาก 0.4 -> 0.7
TRAIL_PCT = 1.2           # จาก 0.7 -> 1.2
TRAIL_SUPER_PCT = 1.8     # จาก 1.2 -> 1.8
BE_PCT = 0.7              # จาก 0.45 -> 0.7

MAX_WOODS = 1
WOOD_DISTANCE_PCT = 1.4   # จาก 0.9 -> 1.4
COOLDOWN_HOURS = 2
MAX_HOLD_HOURS = 24       # จาก 48 -> 24 Silver ไม่ควรถือนาน
MAX_DAILY_LOSS_PCT = 3.0
FAIL_COOLDOWN_MIN = 10

AVOID_FUNDING_MINUTES = 10
FUNDING_TIMES_UTC = [0, 8, 16]
ADX_THRESHOLD = 25        # จาก 20 -> 25 กรอง Sideway เก่งขึ้น
VWAP_DIST_MAX = 9         # จาก 6 -> 9

app = Flask(__name__)
positions, highest, lowest = [], 0, 999999
stats = {"total_trades":0,"wins":0,"losses":0,"total_pnl_pct":0.0,"history":[],"daily_pnl":0.0,"last_reset_day":0}
cooldown_until = 0
trail_sl = 0
be_done = False
last_hourly = 0
last_hourly_report_minute = -1
last_price_source = "N/A"
fail_count = 0

mexc_public = ccxt.mexc({'enableRateLimit': True, 'rateLimit': 1000, 'options': {'defaultType': 'swap'}})
mexc = ccxt.mexc({
    'apiKey': MEXC_API_KEY, 
    'secret': MEXC_API_SECRET, 
    'enableRateLimit': True, 
    'rateLimit': 1500,
    'options': {'defaultType': 'swap'}
}) if MEXC_API_KEY and MEXC_API_SECRET else None

def thai_time():
    return datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%d/%m/%Y %H:%M ICT")
def thai_now():
    return datetime.now(pytz.timezone('Asia/Bangkok'))

def is_funding_time():
    try:
        now_utc = datetime.now(timezone.utc)
        for ft in FUNDING_TIMES_UTC:
            if now_utc.hour == ft and now_utc.minute < AVOID_FUNDING_MINUTES:
                return True
            if now_utc.hour == ft-1 and now_utc.minute >= (60-AVOID_FUNDING_MINUTES):
                return True
        return False
    except:
        return False

def check_max_hold():
    if not positions: return False
    try:
        ft = positions[0].get('time',0)
        return (time.time()-ft)/3600 >= MAX_HOLD_HOURS if ft else False
    except: return False

@app.route('/')
def home():
    wr = (stats["wins"]/stats["total_trades"]*100) if stats["total_trades"]>0 else 0
    side = positions[0]['side'] if positions else "ว่าง"
    return f"V6 SILVER 3X WR:{wr:.1f}% PnL:{stats['total_pnl_pct']:+.2f}% Pos:{len(positions)} {side} Src:{last_price_source} Fail:{fail_count}"

@app.route('/stats')
def stats_page():
    wr = (stats["wins"]/stats["total_trades"]*100) if stats["total_trades"]>0 else 0
    hist = "".join([f"{h['time']} {h['type']} {h['pnl']:+.2f}%<br>" for h in stats["history"][-15:]])
    side = positions[0]['side'] if positions else "ว่าง"
    return f"<h2>V6 SILVER LONG/SHORT 0.01 SILVER TP{TP_PCT}% SL{SL_PCT}% ADX>{ADX_THRESHOLD} {side} Trail:{trail_sl:.1f}</h2>Trades:{stats['total_trades']} WR:{wr:.1f}% Total:{stats['total_pnl_pct']:+.2f}% Daily:{stats['daily_pnl']:+.2f}% Fail:{fail_count} Src:{last_price_source}<br><hr>{hist}"

def send_telegram(msg):
    if not BOT_TOKEN or not CHAT_ID: return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", 
                          json={"chat_id": CHAT_ID, "text": msg, "parse_mode":"HTML", "disable_web_page_preview": True}, timeout=12)
        return r.status_code==200
    except Exception as e:
        print(f"Telegram err {e}")
        return False

def get_balance():
    if not mexc:
        return 0,0,0
    try:
        bal = mexc.fetch_balance()
        usdt = bal.get('USDT',{})
        total = float(usdt.get('total') or 0)
        free = float(usdt.get('free') or 0)
        return total, free, total
    except Exception as e:
        print(f"Balance err {e}")
        return 0.0, 0.0, 0.0

def format_balance_msg():
    total, free, _ = get_balance()
    wr = (stats["wins"]/stats["total_trades"]*100) if stats["total_trades"]>0 else 0
    return f"💰 {total:.2f}$ Free {free:.2f}$ | WR {wr:.1f}% PnL {stats['total_pnl_pct']:+.2f}% Daily {stats['daily_pnl']:+.2f}%", total, wr

def patch_mexc_markets():
    if not mexc:
        return False
    try:
        mexc.load_markets()
        print(f"[PATCH] Loaded {len(mexc.markets)} markets")
        for s in SYMBOL_FALLBACKS:
            if s in mexc.markets:
                print(f"[PATCH] Found {s}")
                return True
    except Exception as e:
        print(f"[PATCH] load_markets fail {e}")
    
    silver_market = {
        'id': 'SILVER_USDT',
        'symbol': 'SILVER/USDT:USDT',
        'base': 'SILVER',
        'quote': 'USDT',
        'settle': 'USDT',
        'baseId': 'SILVER',
        'quoteId': 'USDT',
        'type': 'swap',
        'spot': False,
        'swap': True,
        'future': False,
        'contract': True,
        'linear': True,
        'inverse': False,
        'active': True,
        'precision': {'amount': 0.0001, 'price': 0.01},
        'limits': {'amount': {'min': 0.001, 'max': 1000}, 'price': {'min': 0.01, 'max': 100000}}
    }
    for sym in SYMBOL_FALLBACKS:
        if sym not in mexc.markets:
            try:
                m = silver_market.copy()
                m['symbol'] = sym
                mexc.markets[sym] = m
                print(f"[PATCH] Injected {sym}")
            except:
                pass
    try:
        mexc.markets_by_id['SILVER_USDT'] = silver_market
        mexc.markets_by_id['XAG_USDT'] = silver_market
    except:
        pass
    return True

def get_price_mexc():
    global last_price_source
    sources = [
        ("SILVER/USDT:USDT", "ccxt"),
        ("SILVER_USDT", "ccxt_SILVER"),
        ("XAG/USDT:USDT", "ccxt_XAG"),
        ("XAG_USDT", "ccxt_XAG2"),
    ]
    for sym, name in sources:
        try:
            t = mexc_public.fetch_ticker(sym)
            price = float(t.get('last') or t.get('close') or t.get('bid') or 0)
            if price > 5:  # Silver > $5
                last_price_source = f"{sym} {price:.2f}"
                return price
        except Exception as e:
            print(f"[PRICE FAIL] {sym} {e}")
            time.sleep(0.5)
            continue
    try:
        r = requests.get("https://contract.mexc.com/api/v1/contract/ticker", params={"symbol": "SILVER_USDT"}, timeout=10)
        j = r.json()
        price = float(j.get('data', {}).get('lastPrice') or 0)
        if price > 5:
            last_price_source = f"REST {price:.2f}"
            return price
    except: pass
    try:
        r = requests.get("https://contract.mexc.com/api/v1/contract/ticker", params={"symbol": "XAG_USDT"}, timeout=10)
        j = r.json()
        price = float(j.get('data', {}).get('lastPrice') or 0)
        if price > 5:
            last_price_source = f"REST XAG {price:.2f}"
            return price
    except: pass
    return None

def get_klines_mexc(limit=200):
    symbols_try = ["SILVER/USDT:USDT", "SILVER_USDT", "XAG/USDT:USDT", "XAG_USDT"]
    for sym in symbols_try:
        try:
            ohlcv = mexc_public.fetch_ohlcv(sym, timeframe='15m', limit=limit)
            df = pd.DataFrame(ohlcv, columns=['ot','o','h','l','c','v'])
            if len(df) >= 50:
                return df
        except Exception as e:
            print(f"[KLINE FAIL] {sym} {e}")
            time.sleep(0.5)
            continue
    return None

def calc_lite(df):
    df['hlc3'] = (df['h'] + df['l'] + df['c']) / 3
    df['VWAP'] = df['hlc3'].ewm(span=96).mean()
    # SILVER: EMA ช้าลง จาก 20/50 -> 25/60 กรอง Noise
    df['EMA20'] = df['c'].ewm(span=25).mean()
    df['EMA50'] = df['c'].ewm(span=60).mean()
    df['H-pH'] = df['h'].diff()
    df['pL-L'] = df['l'].shift(1) - df['l']
    df['+DM'] = df['H-pH'].where((df['H-pH'] > df['pL-L']) & (df['H-pH'] > 0), 0.0)
    df['-DM'] = df['pL-L'].where((df['pL-L'] > df['H-pH']) & (df['pL-L'] > 0), 0.0)
    df['TR'] = pd.concat([df['h']-df['l'], (df['h']-df['c'].shift()).abs(), (df['l']-df['c'].shift()).abs()], axis=1).max(axis=1)
    df['ATR'] = df['TR'].rolling(14).mean()
    df['+DM14'] = df['+DM'].rolling(14).sum()
    df['-DM14'] = df['-DM'].rolling(14).sum()
    atr_sum = df['ATR'].rolling(14).sum().replace(0, 0.001)
    df['+DI'] = 100 * (df['+DM14'] / atr_sum)
    df['-DI'] = 100 * (df['-DM14'] / atr_sum)
    df['DX'] = 100 * (df['+DI'] - df['-DI']).abs() / (df['+DI'] + df['-DI']).replace(0, 0.001)
    df['ADX'] = df['DX'].rolling(14).mean()
    low_min=df['l'].rolling(14).min()
    high_max=df['h'].rolling(14).max()
    df['K']=100*(df['c']-low_min)/(high_max-low_min).replace(0,0.001)
    df['D']=df['K'].rolling(3).mean()
    delta=df['c'].diff()
    gain=delta.where(delta>0,0).rolling(14).mean()
    loss=-delta.where(delta<0,0).rolling(14).mean()
    df['RSI']=100-(100/(1+gain/(loss.replace(0,0.001))))
    df['VolEMA'] = df['v'].ewm(span=20).mean()
    # SILVER: Vol ต้องแรงกว่า Gold 1.3 -> 1.5
    df['VolSpike'] = df['v'] > df['VolEMA'] * 1.5
    df['Round10'] = (df['c'] / 1).round() * 1  # Silver ระดับ $1 ไม่ใช่ $10
    return df

def mexc_buy(price,factor):
    global fail_count, cooldown_until
    if not mexc: 
        return True, 0.01
    qty_silver = 0.1  # Silver ราคาถูกกว่า Gold ต้องใช้จำนวนมากกว่า 0.01 -> 0.1
    for sym in SYMBOL_FALLBACKS:
        try:
            try:
                mexc.set_leverage(LEVERAGE, sym)
            except: pass
            order = mexc.create_market_buy_order(sym, qty_silver)
            print(f"BUY OK {sym} {qty_silver} SILVER {order}")
            fail_count = 0
            return True, qty_silver
        except Exception as e:
            print(f"BUY FAIL {sym} {e}")
            time.sleep(0.5)
            continue
    try:
        params = {
            'symbol': 'SILVER_USDT',
            'price': 0,
            'vol': qty_silver,
            'side': 1,
            'type': 5,
            'openType': 1,
            'leverage': LEVERAGE,
        }
        order = None
        if hasattr(mexc, 'contract_private_post_order_submit'):
            order = mexc.contract_private_post_order_submit(params)
        elif hasattr(mexc, 'contractPrivatePostOrderSubmit'):
            order = mexc.contractPrivatePostOrderSubmit(params)
        else:
            order = mexc.private_post_order_submit(params) if hasattr(mexc, 'private_post_order_submit') else mexc.request('order/submit', 'contractPrivate', 'POST', params)
        print(f"BUY OK PRIVATE {order}")
        fail_count = 0
        return True, qty_silver
    except Exception as e:
        print(f"BUY PRIVATE FAIL {e}")
    
    fail_count += 1
    cooldown_until = time.time() + FAIL_COOLDOWN_MIN*60
    if fail_count == 1 or fail_count % 5 == 0:
        send_telegram(f"⚠ SILVER BUY ล้มเหลว {fail_count}ครั้ง พัก {FAIL_COOLDOWN_MIN}นาที | {str(e)[:200]}")
    return False, 0

def mexc_sell(price,factor):
    global fail_count, cooldown_until
    if not mexc: 
        return True, 0.01
    qty_silver = 0.1
    for sym in SYMBOL_FALLBACKS:
        try:
            try:
                mexc.set_leverage(LEVERAGE, sym)
            except: pass
            order = mexc.create_market_sell_order(sym, qty_silver)
            print(f"SELL OK {sym} {qty_silver} SILVER {order}")
            fail_count = 0
            return True, qty_silver
        except Exception as e:
            print(f"SELL FAIL {sym} {e}")
            time.sleep(0.5)
            continue
    fail_count += 1
    cooldown_until = time.time() + FAIL_COOLDOWN_MIN*60
    if fail_count % 3 == 1:
        send_telegram(f"⚠ SILVER SELL ล้มเหลว {fail_count}ครั้ง พัก {FAIL_COOLDOWN_MIN}นาที | Error: {str(e)[:200]}")
    return False, 0

def mexc_close_all():
    if not mexc: return True
    for sym in SYMBOL_FALLBACKS:
        try:
            mexc.create_order(sym, 'market', 'sell', 0, None, {'reduceOnly': True, 'closePosition': True})
            return True
        except:
            try:
                mexc.create_order(sym, 'market', 'buy', 0, None, {'reduceOnly': True, 'closePosition': True})
                return True
            except:
                continue
    return True

def close_position(price,typ):
    global positions,stats,trail_sl,be_done,cooldown_until
    if not positions: return
    avg = sum(p['entry']*abs(p['qty']) for p in positions)/sum(abs(p['qty']) for p in positions) if positions else price
    is_short = positions[0].get('side') == 'short'
    pnl = (avg - price)/avg*100*LEVERAGE if is_short else (price-avg)/avg*100*LEVERAGE
    today = thai_now().day
    if stats["last_reset_day"] != today:
        stats["daily_pnl"] = 0
        stats["last_reset_day"] = today
    stats["daily_pnl"] += pnl
    stats["total_trades"]+=1
    stats["total_pnl_pct"]+=pnl
    if pnl>0: stats["wins"]+=1
    else: 
        stats["losses"]+=1
        cooldown_until = time.time() + COOLDOWN_HOURS*3600
    stats["history"].append({"time":thai_time(),"type":typ,"pnl":pnl})
    mexc_close_all()
    bal_msg,_,wr=format_balance_msg()
    send_telegram(f"✅ [{thai_time()}] {typ} ปิด {pnl:+.2f}% {positions[0]['side']} WR {wr:.1f}%\n{bal_msg}")
    positions.clear()
    global highest, lowest
    highest=0
    lowest=999999
    trail_sl=0
    be_done=False

def should_send_hourly():
    global last_hourly, last_hourly_report_minute
    now = thai_now()
    time_ok = (time.time() - last_hourly) >= 3600
    hour_top = (now.minute == 0 and now.second < 20 and last_hourly_report_minute != now.hour)
    return time_ok or hour_top

def trading_loop():
    global positions,highest,lowest,last_hourly,cooldown_until,last_hourly_report_minute,trail_sl,be_done
    time.sleep(5)
    patch_mexc_markets()
    bal_msg,_,_=format_balance_msg()
    last_hourly = time.time()
    last_hourly_report_minute = thai_now().hour
    send_telegram(f"🚀 V6 SILVER EDITION LIVE {SYMBOL_CCXT} 0.1 SILVER 3X TP{TP_PCT}% SL{SL_PCT}% ADX>{ADX_THRESHOLD}\n{bal_msg}\n✅ SILVER: Lev 3x, EMA25/60, Vol 1.5x, Hold 24h")
    while True:
        try:
            if time.time() < cooldown_until:
                time.sleep(30)
                continue
            if is_funding_time():
                time.sleep(60)
                continue
            if stats["daily_pnl"] <= -MAX_DAILY_LOSS_PCT:
                time.sleep(3600)
                continue
            price=get_price_mexc()
            if not price:
                time.sleep(15)
                continue
            df=get_klines_mexc(150)
            if df is None or len(df)<80:
                time.sleep(15)
                continue
            df=calc_lite(df)
            if len(df)<30:
                time.sleep(15)
                continue
            last=df.iloc[-1]
            prev=df.iloc[-2]
            ema20=last['EMA20']
            ema50=last['EMA50']
            vwap=last['VWAP']
            rsi=last['RSI']
            adx=last['ADX']
            plus_di=last['+DI']
            minus_di=last['-DI']
            k=last['K']
            d=last['D']
            vol_spike=last['VolSpike']
            dist_ema = (last['c']-ema20)/ema20*100
            dist_vwap = (last['c']-vwap)/vwap*100
            super_up = plus_di > 25 and minus_di < 15 and adx > 25 and last['c']>ema20 and last['c']>vwap
            super_down = minus_di > 25 and plus_di < 15 and adx > 25 and last['c']<ema20 and last['c']<vwap
            uptrend = plus_di > minus_di and adx > ADX_THRESHOLD and last['c']>vwap
            downtrend = minus_di > plus_di and adx > ADX_THRESHOLD and last['c']<vwap
            has_trend = adx > ADX_THRESHOLD
            near_support = last['c'] <= last['Round10'] + 0.5
            near_resistance = last['c'] >= last['Round10'] - 0.5
            # SILVER: ยืดหยุ่นเรื่องเกาะ EMA จาก 0.5 -> 0.8
            touch_ema_buy = abs(dist_ema) < 0.8
            touch_ema_sell = abs(dist_ema) < 0.8
            bull_candle = last['c'] > last['o'] and (last['c']-last['o']) > (last['h']-last['l'])*0.5
            bear_candle = last['c'] < last['o'] and (last['o']-last['c']) > (last['h']-last['l'])*0.5
            candle_name = "BULL" if bull_candle else "BEAR" if bear_candle else "DOJI"
            buy=False
            sell=False
            buy_reason=""
            sell_reason=""
            # SILVER: RSI ไม่ไล่สูงเกิน 75
            if super_up and last['c']>ema20 and last['c']>vwap and 55<=rsi<=75 and bull_candle and vol_spike:
                buy=True
                buy_reason=f"SUPER_UP {candle_name} ADX{adx:.0f}"
            elif uptrend and last['c']>vwap and (touch_ema_buy or 0<=dist_ema<=8) and 48<=rsi<=75 and near_support and bull_candle:
                buy=True
                buy_reason=f"TREND_UP {candle_name} ADX{adx:.0f}"
            elif not has_trend and touch_ema_buy and 48<=rsi<=68 and near_support and bull_candle and vol_spike:
                buy=True
                buy_reason=f"SIDEWAY_UP {candle_name} ADX{adx:.0f}"
            if super_down and last['c']<ema20 and last['c']<vwap and 25<=rsi<=45 and bear_candle and vol_spike:
                sell=True
                sell_reason=f"SUPER_DOWN {candle_name} ADX{adx:.0f}"
            elif downtrend and last['c']<vwap and (touch_ema_sell or -8<=dist_ema<=0) and 25<=rsi<=52 and near_resistance and bear_candle:
                sell=True
                sell_reason=f"TREND_DOWN {candle_name} ADX{adx:.0f}"
            elif not has_trend and touch_ema_sell and 32<=rsi<=52 and near_resistance and bear_candle and vol_spike:
                sell=True
                sell_reason=f"SIDEWAY_DOWN {candle_name} ADX{adx:.0f}"
            if should_send_hourly():
                last_hourly=time.time()
                last_hourly_report_minute = thai_now().hour
                total,_,_=get_balance()
                if len(positions)==0:
                    status = f"ว่าง ADX{adx:.0f} {candle_name} VWAP{dist_vwap:+.1f}"
                else:
                    avg = positions[0]['entry']
                    is_s = positions[0]['side']=='short'
                    pnl = (avg-price)/avg*100*LEVERAGE if is_s else (price-avg)/avg*100*LEVERAGE
                    status = f"ถือ {positions[0]['side']} {len(positions)}ไม้ PnL {pnl:+.2f}% Trail {trail_sl:.1f}"
                send_telegram(f"⏰ [{thai_time()}] {SYMBOL_CCXT} {price:.2f}$ {status}\n💰 {total:.2f}$ Daily {stats['daily_pnl']:+.2f}% Fail:{fail_count}")
            if len(positions)==0:
                if buy:
                    ok,qty=mexc_buy(price,1)
                    if ok:
                        positions.append({'entry':price,'qty':qty,'side':'long','time':time.time()})
                        highest=price
                        lowest=999999
                        trail_sl=price*(1-SL_PCT/100)
                        be_done=False
                        bal_msg,_,_=format_balance_msg()
                        send_telegram(f"🟢 LONG SILVER {price:.2f}$ {buy_reason}\nSL {trail_sl:.2f} RSI{rsi:.0f}\n{bal_msg}")
                elif sell:
                    ok,qty=mexc_sell(price,1)
                    if ok:
                        positions.append({'entry':price,'qty':-qty,'side':'short','time':time.time()})
                        lowest=price
                        highest=0
                        trail_sl=price*(1+SL_PCT/100)
                        be_done=False
                        bal_msg,_,_=format_balance_msg()
                        send_telegram(f"🔴 SHORT SILVER {price:.2f}$ {sell_reason}\nSL {trail_sl:.2f} RSI{rsi:.0f}\n{bal_msg}")
            if positions:
                avg=positions[0]['entry']
                is_short = positions[0]['side']=='short'
                if is_short:
                    pnl=(avg-price)/avg*100*LEVERAGE
                    if price<lowest: lowest=price
                else:
                    pnl=(price-avg)/avg*100*LEVERAGE
                    if price>highest: highest=price
                if pnl>=BE_PCT and not be_done:
                    if is_short:
                        trail_sl=min(trail_sl, avg*0.999)
                    else:
                        trail_sl=max(trail_sl, avg*1.001)
                    be_done=True
                    send_telegram(f"🔒 SILVER ยกทุน {trail_sl:.2f} PnL {pnl:+.2f}% {positions[0]['side']}")
                if pnl>=TRAIL_START_PCT:
                    if is_short:
                        cur_pct = TRAIL_SUPER_PCT if super_down else TRAIL_PCT
                        new_trail=lowest*(1+cur_pct/100)
                        if new_trail < trail_sl or trail_sl==0:
                            trail_sl=new_trail
                            if pnl>=1.0:
                                send_telegram(f"📉 Trail SHORT SILVER {trail_sl:.2f} Low {lowest:.2f} PnL {pnl:+.2f}% ADX{adx:.0f}")
                    else:
                        cur_pct = TRAIL_SUPER_PCT if super_up else TRAIL_PCT
                        new_trail=highest*(1-cur_pct/100)
                        if new_trail>trail_sl:
                            trail_sl=new_trail
                            if pnl>=1.0:
                                send_telegram(f"📈 Trail LONG SILVER {trail_sl:.2f} High {highest:.2f} PnL {pnl:+.2f}% ADX{adx:.0f}")
                should_exit=False
                reason=""
                if is_short:
                    if price>=trail_sl and trail_sl>0:
                        if not (super_down and last['c']<vwap and last['c']<ema20):
                            should_exit=True
                            reason=f"TRAIL_SHORT {trail_sl:.1f}"
                    if (last['c']>vwap and last['c']>ema20 and rsi>55 and plus_di>minus_di and pnl>0.2):
                        should_exit=True
                        reason="TREND_BREAK_UP"
                    if bull_candle and pnl>0.5 and rsi<30:
                        should_exit=True
                        reason=f"BULL_CANDLE {candle_name}"
                else:
                    if price<=trail_sl and trail_sl>0:
                        if not (super_up and last['c']>vwap and last['c']>ema20):
                            should_exit=True
                            reason=f"TRAIL_LONG {trail_sl:.1f}"
                    if (last['c']<vwap and last['c']<ema20 and rsi<45 and minus_di>plus_di and pnl>0.2):
                        should_exit=True
                        reason="TREND_BREAK_DOWN"
                    if bear_candle and pnl>0.5 and rsi>70:
                        should_exit=True
                        reason=f"BEAR_CANDLE {candle_name}"
                if pnl>=TP_PCT:
                    should_exit=True
                    reason=f"TP {TP_PCT}%"
                if check_max_hold():
                    should_exit=True
                    reason=f"MAX_HOLD {MAX_HOLD_HOURS}h"
                if pnl <= -SL_PCT*1.5:
                    should_exit=True
                    reason=f"HARD_SL {pnl:.2f}%"
                if should_exit:
                    close_position(price, reason)
            time.sleep(15)
        except Exception as e:
            print(f"Loop err {e}")
            import traceback; traceback.print_exc()
            time.sleep(15)

threading.Thread(target=trading_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
