# main.py
import os, time, requests, numpy as np

# —— 环境变量 —— 
TELEBOT = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# —— 策略参数 —— 
SYMBOLS     = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
PRODUCT     = "usdt-futures"
GRANULARITY = "1m"        # 1m, 5m, 15m, 1H, etc.
MA_SHORT    = 5
MA_LONG     = 20
INTERVAL    = 60 * 5      # 每 5 分钟扫描一次

def notify(text):
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

def get_closes(symbol, limit=MA_LONG*2):
    """V2 接口拉 K 线，倒序收盘价列表"""
    url = (
        "https://api.bitget.com"
        f"/api/v2/mix/market/candles"
        f"?symbol={symbol}"
        f"&productType={PRODUCT}"
        f"&granularity={GRANULARITY}"
        f"&limit={limit}"
    )
    try:
        j = requests.get(url, timeout=8).json()
    except Exception as e:
        notify(f"⚠️ {symbol} K线请求异常: {e}")
        return []
    data = j.get("data") or []
    closes = []
    for c in data[::-1]:
        # 每条 c = [ts, open, high, low, close, vol]
        if len(c) >= 5:
            try: closes.append(float(c[4]))
            except: pass
    if len(closes) < MA_LONG:
        notify(f"⚠️ {symbol} K线数据不足: {len(closes)} 条")
    return closes

def ai_signal(closes):
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
    notify("🤖【信号模式 V2】启动：每5分钟推送开多/开空/观望信号")
    while True:
        for sym in SYMBOLS:
            closes = get_closes(sym)
            if len(closes) < MA_LONG:
                continue
            sig   = ai_signal(closes)
            price = closes[-1]
            if sig == "open_long":
                txt = f"🔔 [{sym}] 建议 ➜ 开多 现价 {price:.2f}"
            elif sig == "open_short":
                txt = f"🔔 [{sym}] 建议 ➜ 开空 现价 {price:.2f}"
            else:
                txt = f"⏸️ [{sym}] 建议 ➜ 观望 现价 {price:.2f}"
            notify(txt)
            time.sleep(1)  # 防限速
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()

