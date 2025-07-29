# main.py

import os
import time
import requests
import json
import hmac
import hashlib
import base64
import uuid
import numpy as np
import pandas as pd

# ———— 环境变量 ————
BITGET_API_KEY        = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET     = os.getenv("BITGET_API_SECRET")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
TELEBOT               = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID               = os.getenv("TELEGRAM_CHAT_ID")

# ———— 参数配置 ————
SYMBOLS      = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
                "ADAUSDT","MATICUSDT","DOGEUSDT","LINKUSDT","AVAXUSDT"]
PRODUCT      = "usdt-futures"
GRAN_1M      = "1m"
GRAN_15M     = "15m"
LIMIT_1M     = 50
LIMIT_15M    = 50
MA_SHORT     = 5
MA_LONG      = 20
RISK_PCT     = 0.01       # 每次交易风险占总权益比例（1%）
LOOP_SECONDS = 60 * 5     # 每 5 分钟运行一次

# ———— Telegram 推送 ————
def notify(text: str):
    if not TELEBOT or not CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEBOT}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text},
            timeout=5
        )
    except:
        pass

# ———— Bitget 签名 & 账户权益 ————
def sign_request(secret, ts, method, path, body=""):
    prehash = f"{ts}{method.upper()}{path}{body or ''}"
    return base64.b64encode(
        hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()
    ).decode()

def get_headers(method, path, body=""):
    ts = str(int(time.time() * 1000))
    sig= sign_request(BITGET_API_SECRET, ts, method, path, body)
    return {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": sig,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": BITGET_API_PASSPHRASE,
        "Content-Type": "application/json"
    }

def bitget_get(path):
    return requests.get("https://api.bitget.com"+path, headers=get_headers("GET",path), timeout=10).json()

def get_account_equity() -> float:
    """读取 U本位永续账户 USDT 权益"""
    path = "/api/mix/v1/account/accounts?productType=umcbl"
    res  = bitget_get(path)
    data = res.get("data") if isinstance(res, dict) else None
    if not data or not isinstance(data, list):
        return 0.0
    try:
        return float(data[0].get("usdtEquity", 0))
    except:
        return 0.0

# ———— 获取 K 线 ————
def fetch_closes(symbol: str, granularity: str, limit: int) -> list:
    url = (
        "https://api.bitget.com"
        f"/api/v2/mix/market/candles"
        f"?symbol={symbol}"
        f"&productType={PRODUCT}"
        f"&granularity={granularity}"
        f"&limit={limit}"
    )
    try:
        j = requests.get(url, timeout=8).json()
        data = j.get("data") or []
    except:
        return []
    closes = []
    for c in data[::-1]:
        try:
            closes.append(float(c[4]))
        except:
            pass
    return closes

# ———— 信号 & 风控计算 ————
def compute_signal(symbol: str, c1: list, c15: list, equity: float) -> dict:
    """
    生成交易信号与资金管理：
      - 多因子信号：1m vs 15m 突破 + MACD + RSI
      - ATR 风控
      - 动态杠杆
      - 头寸规模（基于 1% 风险 & 止损距离）
    返回：
      {
        signal: 'long'/'short'/'wait',
        price: float,
        leverage: int,
        entry: float,
        tp: float,
        sl: float,
        qty: float       # 建议下单合约张数
      }
    """
    arr1  = np.array(c1)
    arr15 = np.array(c15)
    price = arr1[-1]

    # ATR on 1m
    atr1 = np.mean(np.abs(arr1[1:] - arr1[:-1])) + 1e-8

    # RSI14
    delta = np.diff(arr1)
    up   = np.where(delta>0, delta, 0)
    down = np.where(delta<0, -delta, 0)
    rsi  = 100 - 100/(1 + (up[-14:].mean()/(down[-14:].mean()+1e-8)))

    # MACD15m
    ema12 = pd.Series(arr15).ewm(span=12).mean().to_numpy()
    ema26 = pd.Series(arr15).ewm(span=26).mean().to_numpy()
    macd_line = ema12 - ema26
    sig_line  = pd.Series(macd_line).ewm(span=9).mean().to_numpy()
    hist      = macd_line - sig_line
    macd_hist = hist[-1]

    # 突破
    high15 = arr15[-MA_LONG:].max()
    low15  = arr15[-MA_LONG:].min()

    # 判断信号
    signal = "wait"
    if price>high15 and macd_hist>0 and rsi<70:
        signal="long"
    elif price<low15 and macd_hist<0 and rsi>30:
        signal="short"

    # 动态杠杆（示例：波动小时可拉高杠杆）
    lev = int(max(5, min(50, (1/atr1)*2)))

    # 止盈止损
    tp = price + (2*atr1 if signal=="long" else -2*atr1)
    sl = price - (1*atr1 if signal=="long" else -1*atr1)

    # 头寸规模：风险1%权益 / 距离
    risk_amount = equity * RISK_PCT
    distance    = abs(price - sl)
    qty         = round(risk_amount / distance, 4)  # 合约张数，单位USDT合约

    return {
        "signal":   signal,
        "price":    round(price,4),
        "leverage": lev,
        "entry":    round(price,4),
        "tp":       round(tp,4),
        "sl":       round(sl,4),
        "qty":      qty
    }

# ———— 主循环 ————
def main():
    notify("🤖【顶尖信号 V2】启动：含资金管理 ∙ 10 币种 ∙ 每 5 分钟")
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
                msg = (
                    f"🚀 [{sym}] 建议做多\n"
                    f"现价 {info['price']}，进场 {info['entry']}\n"
                    f"杠杆 x{info['leverage']}，数量 {info['qty']} 张\n"
                    f"止盈 {info['tp']}，止损 {info['sl']}"
                )
            elif s=="short":
                msg = (
                    f"🛑 [{sym}] 建议做空\n"
                    f"现价 {info['price']}，进场 {info['entry']}\n"
                    f"杠杆 x{info['leverage']}，数量 {info['qty']} 张\n"
                    f"止盈 {info['tp']}，止损 {info['sl']}"
                )
            else:
                msg = f"⏸️ [{sym}] 建议观望 现价 {info['price']}"

            notify(msg)
            time.sleep(1)

        time.sleep(LOOP_SECONDS)

if __name__ == "__main__":
    main()
