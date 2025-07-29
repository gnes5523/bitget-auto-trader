# main.py
import os
import time
import requests
import json
import numpy as np

# ———— 环境变量 ———— 
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

# ———— 策略参数 ———— 
SYMBOLS      = ["BTCUSDT_UMCBL", "ETHUSDT_UMCBL", "SOLUSDT_UMCBL", "BNBUSDT_UMCBL"]
GRANULARITY  = 60       # 60秒K线
MA_SHORT     = 5
MA_LONG      = 20
LOOP_SECONDS = 60 * 5   # 每5分钟运行一次

def notify(msg: str):
    """发送 Telegram 消息"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
            timeout=5
        )
    except:
        pass

def get_ohlc(symbol: str, limit: int = MA_LONG*3) -> list:
    """
    获取Bitget永续合约K线，
    返回倒序收盘价列表(旧->新)，失败时返回空列表
    """
    path = (
        f"/api/mix/v1/market/candles"
        f"?symbol={symbol}&granularity={GRANULARITY}&limit={limit}"
    )
    try:
        res = requests.get("https://api.bitget.com" + path, timeout=8)
        j = res.json()
    except Exception as e:
        notify(f"⚠️ {symbol} K线接口请求异常: {e}")
        return []

    # 格式检查
    data = j.get("data")
    if not isinstance(data, list):
        notify(f"⚠️ {symbol} K线接口返回格式异常: {j}")
        return []

    closes = []
    for candle in data[::-1]:
        # candle 格式 [ts, open, high, low, close, vol]
        if len(candle) >= 5:
            try:
                closes.append(float(candle[4]))
            except:
                pass

    if len(closes) < MA_LONG:
        notify(f"⚠️ {symbol} K线数据不足 (拿到 {len(closes)} 条，需要至少 {MA_LONG})")
    return closes

def ai_signal(closes: list) -> str:
    """
    多因子信号：短均突破长均 + ATR 动量
    price > MA_LONG 且 MA_SHORT > MA_LONG 且 (price - MA_LONG) > 2*ATR → open_long
    price < MA_LONG 且 MA_SHORT < MA_LONG 且 (MA_LONG - price) > 2*ATR → open_short
    其余 → wait
    """
    arr = np.array(closes)
    ma_s = arr[-MA_SHORT:].mean()
    ma_l = arr[-MA_LONG:].mean()
    price = arr[-1]
    atr   = np.mean(np.abs(arr[1:] - arr[:-1]))

    if price > ma_l and ma_s > ma_l and (price - ma_l) > 2*atr:
        return "open_long"
    if price < ma_l and ma_s < ma_l and (ma_l - price) > 2*atr:
        return "open_short"
    return "wait"

def main():
    notify("🤖【信号模式】AI量化信号系统启动，开始每5分钟监控…")
    while True:
        for symbol in SYMBOLS:
            closes = get_ohlc(symbol)
            if len(closes) < MA_LONG:
                # 数据不够就跳过，下次再试
                continue

            sig   = ai_signal(closes)
            price = closes[-1]

            if sig == "open_long":
                text = f"🔔 [{symbol}] 信号→✅ 建议开多\n现价: {price:.2f}"
            elif sig == "open_short":
                text = f"🔔 [{symbol}] 信号→✅ 建议开空\n现价: {price:.2f}"
            else:
                text = f"⏸️ [{symbol}] 信号→观望\n现价: {price:.2f}"

            notify(text)
            time.sleep(1)  # 防止短时间内API限流

        time.sleep(LOOP_SECONDS)

if __name__ == "__main__":
    main()
