# main.py

import os, time, threading
import requests, numpy as np, pandas as pd
from http.server import HTTPServer, BaseHTTPRequestHandler

# ———— Telegram 推送 ————
TELEBOT = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
def notify(txt):
    if not TELEBOT or not CHAT_ID: return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEBOT}/sendMessage",
            data={"chat_id":CHAT_ID,"text":txt},
            timeout=5
        )
    except:
        pass

# ———— Healthcheck HTTP 服务 ————
class Health(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200); self.end_headers()
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
def start_health():
    port = int(os.getenv("PORT","10000"))
    HTTPServer(("0.0.0.0",port),Health).serve_forever()

# ———— 参数配置 ————
SYMBOLS     = [
    "BTCUSDT_UMCBL","ETHUSDT_UMCBL","SOLUSDT_UMCBL","BNBUSDT_UMCBL","XRPUSDT_UMCBL",
    "ADAUSDT_UMCBL","MATICUSDT_UMCBL","DOGEUSDT_UMCBL","LINKUSDT_UMCBL","AVAXUSDT_UMCBL"
]
PRODUCT     = "umcbl"
TF          = "1m"
LIMIT       = 200      # 最大200条
GRID_PARAMS = {
    "bb_mul": [1.5, 2.0, 2.5],
    "rsi_hi": [70,    80],
    "rsi_lo": [30,    20],
    "adx_th": [20,    25,  30],
}
LIVE_INT    = 60*5     # 每5分钟

# ———— 拉公开K线 ————
def fetch_closes(sym, granularity, limit):
    url = (
      "https://api.bitget.com"
      f"/api/v2/mix/market/candles"
      f"?symbol={sym}&productType={PRODUCT}"
      f"&granularity={granularity}&limit={limit}"
    )
    try:
        data = requests.get(url, timeout=8).json().get("data") or []
    except:
        return []
    closes = []
    for c in data[::-1]:
        try:
            closes.append(float(c[4]))
        except:
            pass
    return closes

# ———— 多因子信号 & 回测 ————
def compute_signals(df, bb_mul, rsi_hi, rsi_lo, adx_th):
    df["ma20"]  = df["close"].rolling(20).mean()
    df["sd20"]  = df["close"].rolling(20).std()
    df["upper"] = df["ma20"] + bb_mul*df["sd20"]
    df["lower"] = df["ma20"] - bb_mul*df["sd20"]

    d          = df["close"].diff()
    up, down   = d.clip(lower=0), -d.clip(upper=0)
    df["rsi"]  = 100-100/(1+up.rolling(14).mean()/(down.rolling(14).mean()+1e-8))

    df["tr"]   = np.maximum.reduce([
        df["high"]-df["low"],
        (df["high"]-df["close"].shift()).abs(),
        (df["low"]-df["close"].shift()).abs()
    ])
    df["+dm"]  = np.where(
        (df["high"]-df["high"].shift()) > (df["low"].shift()-df["low"]),
        df["high"]-df["high"].shift(),0
    )
    df["-dm"]  = np.where(
        (df["low"].shift()-df["low"]) > (df["high"]-df["high"].shift()),
        df["low"].shift()-df["low"],0
    )
    atr        = df["tr"].rolling(14).mean()
    plus       = df["+dm"].rolling(14).mean()/atr*100
    minus      = df["-dm"].rolling(14).mean()/atr*100
    df["adx"]  = abs(plus-minus)/(plus+minus)*100

    df["signal"]=0
    df.loc[
      (df["close"]>df["upper"])&(df["rsi"]<rsi_hi)&(df["adx"]>adx_th),
      "signal"
    ]=1
    df.loc[
      (df["close"]<df["lower"])&(df["rsi"]>rsi_lo)&(df["adx"]>adx_th),
      "signal"
    ]=-1
    return df

def backtest(df):
    entry=wins=trades=0
    for i in range(len(df)-1):
        s = df["signal"].iat[i]
        p = df["close"].iat[i]
        if entry==0 and s!=0:
            entry = p*s
        elif entry!=0 and s==0:
            trades+=1
            exitp = df["close"].iat[i-1]*np.sign(entry)
            if exitp*entry>0: wins+=1
            entry=0
    return wins/trades if trades else 0

def optimize_params(sym):
    closes = fetch_closes(sym, TF, LIMIT)
    highs  = fetch_closes(sym, TF, LIMIT)  # Bitget 不分高低，示意复用
    lows   = highs.copy()
    if len(closes)<50:
        return None
    df = pd.DataFrame({"close":closes,"high":highs,"low":lows})
    best=(0,None)
    for bb in GRID_PARAMS["bb_mul"]:
      for hi in GRID_PARAMS["rsi_hi"]:
        for lo in GRID_PARAMS["rsi_lo"]:
          for adx in GRID_PARAMS["adx_th"]:
            df2=compute_signals(df.copy(),bb,hi,lo,adx)
            wr = backtest(df2)
            if wr>best[0]:
                best=(wr,{"bb_mul":bb,"rsi_hi":hi,"rsi_lo":lo,"adx_th":adx})
    return best[1]

# ———— 全市场回测 + 线上推送 ————
def main_loop():
    params_map={}
    for sym in SYMBOLS:
        notify(f"🔍 回测优化 {sym}")
        p = optimize_params(sym)
        params_map[sym]=p
        notify(f"✅ {sym} 最佳：{p}")

    notify(f"🤖【全市场信号】启动 10 币种 · 1m · 每{LIVE_INT//60}分钟")
    while True:
        for sym in SYMBOLS:
            p = params_map.get(sym)
            if not p: continue
            closes=fetch_closes(sym,TF,50)
            highs = closes; lows=closes
            df    = pd.DataFrame({"close":closes,"high":highs,"low":lows})
            df2   = compute_signals(df,**p)
            sig   = df2["signal"].iat[-1]
            price = closes[-1] if closes else 0
            emo   = {1:"🚀",0:"⏸️",-1:"🛑"}[sig]
            txt   = f"{emo}[{sym}] 建议：{'开多' if sig==1 else '观望' if sig==0 else '开空'} 价{price:.2f}"
            notify(txt)
            time.sleep(1)
        time.sleep(LIVE_INT)

if __name__=="__main__":
    threading.Thread(target=start_health,daemon=True).start()
    main_loop()
