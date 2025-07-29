# main.py

import os, time, threading
import requests, hmac, hashlib, base64, json, uuid
import numpy as np, pandas as pd, ccxt
from http.server import HTTPServer, BaseHTTPRequestHandler

# ———— 环境变量 ————
BITGET_API_KEY        = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET     = os.getenv("BITGET_API_SECRET")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
TELEBOT               = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID               = os.getenv("TELEGRAM_CHAT_ID")

# ———— 策略／回测参数 ————
SYMBOLS      = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","XRP/USDT",
                "ADA/USDT","MATIC/USDT","DOGE/USDT","LINK/USDT","AVAX/USDT"]
TIMEFRAME    = '1m'
SINCE_DAYS   = 30          # 回测近30天
GRID_PARAMS  = {
    'bb_mul':[1.5,2.0,2.5],
    'rsi_hi':[70,80],
    'rsi_lo':[30,20],
    'adx_th':[20,25,30]
}
LIVE_INTERVAL= 60*5        # 线上每5分钟推送一次

# ———— CCXT 初始化 ————
exchange = ccxt.binance({
    'enableRateLimit': True
})

# ———— HTTP 健康检查 ————
class HealthHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200); self.end_headers()
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b'OK')

def start_health_server():
    port= int(os.getenv("PORT","10000"))
    HTTPServer(('0.0.0.0',port),HealthHandler).serve_forever()

# ———— 通用推送 ————
def notify(msg):
    if not TELEBOT or not CHAT_ID: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEBOT}/sendMessage",
                      data={"chat_id":CHAT_ID,"text":msg},timeout=5)
    except: pass

# ———— 拉历史K线 ————
def fetch_ohlcv(symbol, since, limit=1000):
    # symbol 格式 'BTC/USDT'
    return exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, since=since, limit=limit)

# ———— 回测网格搜索 ————
def optimize_params(symbol):
    now = exchange.milliseconds()
    since = now - SINCE_DAYS*24*3600*1000
    ohlcv = fetch_ohlcv(symbol, since, limit= SINCE_DAYS*24*60)
    df = pd.DataFrame(ohlcv, columns=['ts','o','h','l','c','v'])
    df['close']=df['c']
    best = (0, None)
    for bb_mul in GRID_PARAMS['bb_mul']:
      for rsi_hi in GRID_PARAMS['rsi_hi']:
        for rsi_lo in GRID_PARAMS['rsi_lo']:
          for adx_th in GRID_PARAMS['adx_th']:
            # 计算信号
            df2 = compute_signals(df, bb_mul, rsi_hi, rsi_lo, adx_th)
            wr = backtest(df2)
            if wr > best[0]:
                best = (wr, {'bb_mul':bb_mul,'rsi_hi':rsi_hi,'rsi_lo':rsi_lo,'adx_th':adx_th})
    return best[1]

# ———— 信号计算 & 回测函数 ————
def compute_signals(df, bb_mul, rsi_hi, rsi_lo, adx_th):
    # 布林带
    df['ma20']=df['close'].rolling(20).mean()
    df['sd20']=df['close'].rolling(20).std()
    df['upper']=df['ma20']+bb_mul*df['sd20']
    df['lower']=df['ma20']-bb_mul*df['sd20']
    # RSI
    d = df['close'].diff()
    up = d.clip(lower=0); down = -d.clip(upper=0)
    df['rsi']=100-100/(1+up.rolling(14).mean()/down.rolling(14).mean())
    # ADX
    df['tr']=np.maximum.reduce([df['h']-df['l'],(df['h']-df['c'].shift()).abs(),(df['l']-df['c'].shift()).abs()])
    df['+dm']=np.where((df['h']-df['h'].shift())>(df['l'].shift()-df['l']),df['h']-df['h'].shift(),0)
    df['-dm']=np.where((df['l'].shift()-df['l'])>(df['h']-df['h'].shift()),df['l'].shift()-df['l'],0)
    atr= df['tr'].rolling(14).mean()
    plus= df['+dm'].rolling(14).mean()/atr*100
    minus= df['-dm'].rolling(14).mean()/atr*100
    df['adx']=abs(plus-minus)/(plus+minus)*100
    # 信号
    df['signal']=0
    df.loc[(df['close']>df['upper'])&(df['rsi']<rsi_hi)&(df['adx']>adx_th),'signal']=1
    df.loc[(df['close']<df['lower'])&(df['rsi']>rsi_lo)&(df['adx']>adx_th),'signal']=-1
    return df

def backtest(df):
    entry=0;wins=0;trades=0
    for i in range(len(df)-1):
        sig=df['signal'].iat[i]
        price=df['close'].iat[i]
        if entry==0 and sig!=0:
            entry=price*sig
        elif entry!=0 and sig==0:
            trades+=1
            exitp=df['close'].iat[i-1]*np.sign(entry)
            if exitp*entry>0: wins+=1
            entry=0
    return wins/trades if trades else 0

# ———— 线上信号循环 ————
def live_loop(all_params):
    notify(f"🤖【全市场信号】启动，最佳参数已加载，{len(SYMBOLS)} 币种·{TIMEFRAME}")
    while True:
        for sym in SYMBOLS:
            params = all_params.get(sym)
            if not params: continue
            # 拉实时1m & 15m
            o1=fetch_ohlcv(sym,exchange.milliseconds()-60*1000,limit=MA_LONG*2)
            o15=fetch_ohlcv(sym,exchange.milliseconds()-15*60*1000,limit=MA_LONG*2)
            closes1 = np.array([x[4] for x in o1])
            closes15= np.array([x[4] for x in o15])
            # 复用compute_signals只取signal
            df_dummy=pd.DataFrame({'close':closes1,'h':closes15,'l':closes15})
            sig_df=compute_signals(df_dummy, **params)
            sig=sig_df['signal'].iat[-1]
            price=closes1[-1]
            txt = {
              1: f"🚀 [{sym}] 建议→开多 价{price:.2f} 杠{params['bb_mul']}",
             -1: f"🛑 [{sym}] 建议→开空 价{price:.2f} 杠{params['bb_mul']}",
              0: f"⏸️ [{sym}] 观望 价{price:.2f}"
            }[sig]
            notify(txt)
            time.sleep(1)
        time.sleep(LIVE_INTERVAL)

if __name__=='__main__':
    # 1. 参数优化（大数据回测）
    all_params={}
    for sym in SYMBOLS:
        notify(f"🔍 回测优化 {sym} …")
        best = optimize_params(sym)
        all_params[sym]=best
        notify(f"✅ {sym} 参数: {best}")
    # 2. 并行启动健康检查 + 实盘信号
    threading.Thread(target=start_health_server,daemon=True).start()
    live_loop(all_params)
