# main.py

import os
import time
import threading
import requests
import json
import hmac
import hashlib
import base64
import uuid
import numpy as np
import pandas as pd
from http.server import HTTPServer, BaseHTTPRequestHandler

# ———— 环境变量 ————
BITGET_API_KEY        = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET     = os.getenv("BITGET_API_SECRET")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
TELEBOT               = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID               = os.getenv("TELEGRAM_CHAT_ID")

# ———— 策略参数 ————
SYMBOLS      = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
                "ADAUSDT","MATICUSDT","DOGEUSDT","LINKUSDT","AVAXUSDT"]
PRODUCT      = "usdt-futures"
GRAN_1M      = "1m"
GRAN_15M     = "15m"
LIMIT_1M     = 50
LIMIT_15M    = 50
MA_SHORT     = 5
MA_LONG      = 20
RISK_PCT     = 0.01       # 每次交易风险占权益的 1%
INTERVAL     = 60 * 5     # 每5分钟推送一次

# ———— HTTP 健康检查服务 ————
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def start_health_server():
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Health server listening on port {port}")
    server.serve_forever()

# ———— 通用函数 ————
def notify(text: str):
    if not TELEBOT or not CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEBOT}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text}, timeout=5
        )
    except:
        pass

def sign_request(secret, ts, method, path, body=""):
    prehash = f"{ts}{method.upper()}{path}{body or ''}"
    return base64.b64encode(
        hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()
    ).decode()

def get_headers(method, path, body=""):
    ts  = str(int(time.time()*1000))
    sig = sign_request(BITGET_API_SECRET, ts, method, path, body)
    return {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": sig,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": BITGET_API_PASSPHRASE,
        "Content-Type": "application/json"
    }

def bitget_get(path):
    return requests.get("https://api.bitget.com"+path,
                        headers=get_headers("GET",path), timeout=8).json()

def get_account_equity() -> float:
    path = "/api/mix/v1/account/accounts?productType=umcbl"
    res  = bitget_get(path)
    data = res.get("data")
    if not isinstance(data, list) or not data:
        return 0.0
    return float(data[0].get("usdtEquity", 0) or 0)

def fetch_closes(symbol: str, granularity: str, limit: int) -> list:
    url = (
        "https://api.bitget.com"
        f"/api/v2/mix/market/candles"
        f"?symbol={symbol}&productType={PRODUCT}"
        f"&granularity={granularity}&limit={limit}"
    )
    try:
        j = requests.get(url, timeout=8).json()
        arr = j.get("data") or []
    except:
        return []
    closes = []
    for c in arr[::-1]:
        try:
            closes.append(float(c[4]))
        except:
            continue
    return closes

def compute_signal(sym: str, c1: list, c15: list, equity: float) -> dict:
    arr1, arr15 = np.array(c1), np.array(c15)
    price       = arr1[-1]
    atr1        = np.mean(np.abs(arr1[1:] - arr1[:-1])) + 1e-8

    # RSI14
    delta = np.diff(arr1)
    up    = np.where(delta>0, delta, 0)
    down  = np.where(delta<0, -delta, 0)
    rsi14 = 100 - 100/(1 + (up[-14:].mean()/(down[-14:].mean()+1e-8)))

    # MACD on 15m
    ema12 = pd.Series(arr15).ewm(span=12).mean().to_numpy()
    ema26 = pd.Series(arr15).ewm(span=26).mean().to_numpy()
    macd_line = ema12 - ema26
    sig_line  = pd.Series(macd_line).ewm(span=9).mean().to_numpy()
    hist      = macd_line - sig_line
    macd_hist = hist[-1]

    high15, low15 = arr15[-MA_LONG:].max(), arr15[-MA_LONG:].min()

    # 决策
    signal = "wait"
    if price>high15 and macd_hist>0 and rsi14<70:
        signal="long"
    elif price<low15 and macd_hist<0 and rsi14>30:
        signal="short"

    # 动态杠杆
    lev = int(max(5, min(50, (1/atr1)*2)))

    # 止盈止损
    tp = price + (2*atr1 if signal=="long" else -2*atr1)
    sl = price - (1*atr1 if signal=="long" else -1*atr1)

    # 头寸规模：风险1%权益 / 止损距离
    risk    = equity * RISK_PCT
    distance= abs(price-sl)
    qty     = round(risk/distance, 4)

    return {
        "signal":   signal,
        "price":    round(price,4),
        "leverage": lev,
        "entry":    round(price,4),
        "tp":       round(tp,4),
        "sl":       round(sl,4),
        "qty":      qty
    }

def trader_loop():
    notify("🤖【顶尖信号 V2】启动：含资金管理 · 10 币种 · 每 5 分钟")
    while True:
        equity = get_account_equity()
        if equity<=0:
            time.sleep(30)
            continue

        for sym in SYMBOLS:
            c1  = fetch_closes(sym, GRAN_1M,  LIMIT_1M)
            c15 = fetch_closes(sym, GRAN_15M, LIMIT_15M)
            if len(c1)<MA_LONG or len(c15)<MA_LONG:
                continue

            info = compute_signal(sym, c1, c15, equity)
            s    = info["signal"]
            if s=="long":
                txt = (
                    f"🚀 [{sym}] 开多\n"
                    f"现价 {info['price']}, 进场 {info['entry']}\n"
                    f"杠杆 x{info['leverage']}, 数量 {info['qty']} 张\n"
                    f"止盈 {info['tp']} 止损 {info['sl']}"
                )
            elif s=="short":
                txt = (
                    f"🛑 [{sym}] 开空\n"
                    f"现价 {info['price']}, 进场 {info['entry']}\n"
                    f"杠杆 x{info['leverage']}, 数量 {info['qty']} 张\n"
                    f"止盈 {info['tp']} 止损 {info['sl']}"
                )
            else:
                txt = f"⏸️ [{sym}] 观望 现价 {info['price']}"

            notify(txt)
            time.sleep(1)
        time.sleep(INTERVAL)

if __name__ == "__main__":
    # 并行启动内置HTTP健康检查 + 交易循环
    threading.Thread(target=start_health_server, daemon=True).start()
    trader_loop()
