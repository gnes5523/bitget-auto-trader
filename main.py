# main.py
import os
import time
import requests
import hmac
import hashlib
import base64
import json
import uuid
import numpy as np

# —— 环境变量 —— 
BITGET_API_KEY       = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET    = os.getenv("BITGET_API_SECRET")
BITGET_API_PASSPHRASE= os.getenv("BITGET_API_PASSPHRASE")
TELEGRAM_BOT_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID     = os.getenv("TELEGRAM_CHAT_ID")

# —— 策略参数 —— 
SYMBOLS     = ["BTCUSDT_UMCBL", "ETHUSDT_UMCBL", "SOLUSDT_UMCBL", "BNBUSDT_UMCBL"]
GRANULARITY = 60      # K 线周期 1 分钟
WINDOW_MA1   = 5      # 短期均线
WINDOW_MA2   = 20     # 长期均线
SLEEP_LOOP   = 60*5   # 每 5 分钟扫描一次

def notify(msg: str):
    """发送 Telegram 消息"""
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        try:
            requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=5)
        except:
            pass

def get_ohlc(symbol: str, limit: int=WINDOW_MA2*2) -> list:
    """从 Bitget 拉取分钟 K 线收盘价"""
    path = f"/api/mix/v1/market/candles?symbol={symbol}&granularity={GRANULARITY}&limit={limit}"
    try:
        res = requests.get("https://api.bitget.com" + path, timeout=8).json().get("data", [])
        # data 格式 [[ts,open,high,low,close,vol],...]
        return [float(c[4]) for c in res[::-1]]
    except Exception as e:
        notify(f"⚠️ 获取 {symbol} K 线失败：{e}")
        return None

def ai_signal(closes: list) -> str:
    """多因子信号：短均突破长均 + ATR 动量"""
    arr = np.array(closes)
    ma1 = arr[-WINDOW_MA1:].mean()
    ma2 = arr[-WINDOW_MA2:].mean()
    price = arr[-1]
    atr = np.mean(np.abs(arr[1:] - arr[:-1]))
    if price > ma2 and ma1 > ma2 and (price - ma2) > 2*atr:
        return "open_long"
    if price < ma2 and ma1 < ma2 and (ma2 - price) > 2*atr:
        return "open_short"
    return "wait"

def main():
    notify("🤖【信号模式】AI 量化信号系统已启动，开始监控合约行情...")
    while True:
        for symbol in SYMBOLS:
            closes = get_ohlc(symbol)
            if not closes:
                continue
            signal = ai_signal(closes)
            price  = closes[-1]
            if signal == "open_long":
                notify(f"🔔 [{symbol}] 建议 ➜ 开多\n现价: {price:.2f}\n策略: 短期突破长均 + 动量")
            elif signal == "open_short":
                notify(f"🔔 [{symbol}] 建议 ➜ 开空\n现价: {price:.2f}\n策略: 短期下破长均 + 动量")
            else:
                # 观望可选是否推送，这里只推送一次开盘启动后的观望
                # notify(f"[{symbol}] 观望，现价 {price:.2f}")
                pass
            time.sleep(1)  # 矿 API 限频，短暂停
        time.sleep(SLEEP_LOOP)

if __name__ == "__main__":
    main()



