# main.py

import os, time, threading
import requests, hashlib, hmac, base64
import numpy as np, pandas as pd
from http.server import HTTPServer, BaseHTTPRequestHandler

# ———— 环境变量 ————
TELEBOT    = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID")

# ———— 策略／回测参数 ————
SYMBOLS     = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
               "ADAUSDT","MATICUSDT","DOGEUSDT","LINKUSDT","AVAXUSDT"]
PRODUCT     = "usdt-futures"
TF          = "1m"
SINCE_MIN   = 1440      # 回测 1 天共 1440 条 1m K 线
GRID_PARAMS = {
    "bb_mul": [1.5, 2.0, 2.5],
    "rsi_hi": [70,   80],
    "rsi_lo": [30,   20],
    "adx_th": [20,   25,  30],
}
LIVE_INT    = 60 * 5    # 正式 5 分钟

# ———— Healthcheck HTTP 服务 ————
class Health(BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200); self.end_headers()
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"OK")

def start_health():
    port = int(os.getenv("PORT","10000"))
    HTTPServer(("0.0.0.0", port), Health).serve_forever()

# ———— 推送到 Telegram ————
def notify(txt):
    if not TELEBOT or not CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEBOT}/sendMessage",
            data={"chat_id": CHAT_ID, "text": txt},
            timeout=5
        )
    except:
        pass

# ———— 拉 Bitget K 线 ————
def fetch_closes(sym, granularity, limit):
    url = (
        "https://api.bitget.com"
        f"/api/v2/mix/market/candles"
        f"?symbol={sym}"
        f"&productType={PRODUCT}"
        f"&granularity={granularity}"
        f"&limit={limit}"
    )
    try:
        data = requests.get(url, timeout=8).json().get("data") or []
    except:
        return []
    # 每条 [ts, open, high, low, close, volume]
    closes = []
    for c in data[::-1]:
        try:
            closes.append(float(c[4]))
        except:
            pass
    return closes

# ———— 多因子信号 & 回测 ————
def compute_signals(df, bb_mul, rsi_hi, rsi_lo, adx_th):
    # 布林带
    df["ma20"]    = df["close"].rolling(20).mean()
    df["sd20"]    = df["close"].rolling(20).std()
    df["upper"]   = df["ma20"] + bb_mul*df["sd20"]
    df["lower"]   = df["ma20"] - bb_mul*df["sd20"]
    # RSI14
    d             = df["close"].diff()
    up, down      = d.clip(lower=0), -d.clip(upper=0)
    df["rsi"]     = 100 - 100/(1 + up.rolling(14).mean()/(down.rolling(14).mean()+1e-8))
    # ADX14
    df["tr"]      = np.maximum.reduce([
        df["high"]-df["low"],
        (df["high"]-df["close"].shift()).abs(),
        (df["low"]-df["close"].shift()).abs()
    ])
    df["+dm"]     = np.where((df["high"]-df["high"].shift()) > (df["low"].shift()-df["low"]),
                              df["high"]-df["high"].shift(), 0)
    df["-dm"]     = np.where((df["low"].shift()-df["low"]) > (df["high"]-df["high"].shift()),
                              df["low"].shift()-df["low"], 0)
    atr           = df["tr"].rolling(14).mean()
    plus          = df["+dm"].rolling(14).mean()/atr*100
    minus         = df["-dm"].rolling(14).mean()/atr*100
    df["adx"]     = abs(plus-minus)/(plus+minus)*100
    # 生成信号
    df["signal"]  = 0
    cond_long     = (df["close"]>df["upper"]) & (df["rsi"]<rsi_hi) & (df["adx"]>adx_th)
    cond_short    = (df["close"]<df["lower"]) & (df["rsi"]>rsi_lo) & (df["adx"]>adx_th)
    df.loc[cond_long,  "signal"] =  1
    df.loc[cond_short, "signal"] = -1
    return df

def backtest(df):
    entry, wins, trades = 0,0,0
    for i in range(len(df)-1):
        sig   = df["signal"].iat[i]
        price = df["close"].iat[i]
        if entry==0 and sig!=0:
            entry = price*sig
        elif entry!=0 and sig==0:
            trades +=1
            exitp   = df["close"].iat[i-1]*np.sign(entry)
            if exitp*entry>0:
                wins+=1
            entry=0
    return wins/trades if trades else 0

# ———— 网格优化 ————
def optimize_params(sym):
    closes = fetch_closes(sym, TF, SINCE_MIN)
    highs  = fetch_closes(sym, TF, SINCE_MIN)  # 这里复用 highs/ lows 只是示意
    lows   = highs.copy()
    if len(closes)<50:
        return None
    df = pd.DataFrame({
        "close": closes,
        "high":  highs,
        "low":   lows
    })
    best = (0, None)
    for bb in GRID_PARAMS["bb_mul"]:
        for hi in GRID_PARAMS["rsi_hi"]:
            for lo in GRID_PARAMS["rsi_lo"]:
                for adx in GRID_PARAMS["adx_th"]:
                    df2 = compute_signals(df.copy(), bb, hi, lo, adx)
                    wr  = backtest(df2)
                    if wr>best[0]:
                        best = (wr, {"bb_mul":bb,"rsi_hi":hi,"rsi_lo":lo,"adx_th":adx})
    return best[1]

# ———— 大数据回测 ＋ 线上信号 ————
def main_loop():
    # 1) 对每个币种做参数优化
    params_map = {}
    for sym in SYMBOLS:
        notify(f"🔍 回测优化 {sym} …")
        p = optimize_params(sym)
        params_map[sym] = p
        notify(f"✅ {sym} 最佳: {p}")

    # 2) 启动信号推送
    notify(f"🤖【全市场信号】启动，每{LIVE_INT//60}分钟 10 币种")
    while True:
        for sym in SYMBOLS:
            p = params_map.get(sym)
            if not p:
                continue
            closes = fetch_closes(sym, TF, 50)
            highs  = fetch_closes(sym, TF, 50)
            lows   = highs.copy()
            df     = pd.DataFrame({"close":closes,"high":highs,"low":lows})
            df2    = compute_signals(df, **p)
            sig    = df2["signal"].iat[-1]
            price  = closes[-1]
            lev    = int(max(5, min(50, 2/(df["close"].diff().abs().mean()+1e-8))))
            emoji  = {1:"🚀", -1:"🛑", 0:"⏸️"}[sig]
            text   = f"{emoji} [{sym}] 建议：{'开多' if sig==1 else '开空' if sig==-1 else '观望'} 价{price:.2f} 杠杆x{lev}"
            notify(text)
            time.sleep(1)
        time.sleep(LIVE_INT)

if __name__=="__main__":
    threading.Thread(target=start_health, daemon=True).start()
    main_loop()
