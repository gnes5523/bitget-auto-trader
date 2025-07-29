# main.py
import os, time, requests, json, numpy as np

# —— 环境变量 —— 
BITGET_API_KEY        = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET     = os.getenv("BITGET_API_SECRET")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
TELEGRAM_BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID      = os.getenv("TELEGRAM_CHAT_ID")

# —— 策略参数 —— 
SYMBOLS      = ["BTCUSDT_UMCBL", "ETHUSDT_UMCBL", "SOLUSDT_UMCBL", "BNBUSDT_UMCBL"]
GRANULARITY  = 60   # K线周期：60秒
MA_SHORT     = 5
MA_LONG      = 20
LOOP_SECONDS = 60*5  # 每5分钟运行一次

def notify(msg):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
                timeout=5
            )
        except:
            pass

def get_ohlc(symbol, limit=MA_LONG*2):
    path = f"/api/mix/v1/market/candles?symbol={symbol}&granularity={GRANULARITY}&limit={limit}"
    try:
        data = requests.get("https://api.bitget.com"+path, timeout=8).json().get("data", [])
        return [float(c[4]) for c in data[::-1]]
    except Exception as e:
        notify(f"⚠️ 获取 {symbol} K线失败: {e}")
        return None

def ai_signal(closes):
    arr = np.array(closes)
    ma_s = arr[-MA_SHORT:].mean()
    ma_l = arr[-MA_LONG:].mean()
    price = arr[-1]
    atr = np.mean(np.abs(arr[1:] - arr[:-1]))
    if price > ma_l and ma_s > ma_l and (price-ma_l) > 2*atr:
        return "open_long"
    if price < ma_l and ma_s < ma_l and (ma_l-price) > 2*atr:
        return "open_short"
    return "wait"

def main():
    notify("🤖【信号模式】AI量化信号系统启动，开始每5分钟监控…")
    while True:
        for symbol in SYMBOLS:
            closes = get_ohlc(symbol)
            if not closes:
                continue
            sig = ai_signal(closes)
            price = closes[-1]
            if sig=="open_long":
                txt = f"🔔 [{symbol}] 信号→✅ 开多\n现价: {price:.2f}"
            elif sig=="open_short":
                txt = f"🔔 [{symbol}] 信号→✅ 开空\n现价: {price:.2f}"
            else:
                txt = f"⏸️ [{symbol}] 信号→观望\n现价: {price:.2f}"
            notify(txt)
            time.sleep(1)  # 防限流
        time.sleep(LOOP_SECONDS)

if __name__=="__main__":
    main()
