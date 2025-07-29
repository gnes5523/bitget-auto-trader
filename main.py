import time
import requests
import os

# ========== Bitget API Key 設定 ==========
API_KEY = os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("BITGET_API_SECRET")
API_PASSPHRASE = os.getenv("BITGET_PASSPHRASE")

# ========== Telegram 設定 ==========
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def notify(msg):
    """發送Telegram訊息"""
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})

def get_price(symbol):
    """模擬從Bitget獲取幣價，實際可串API（這裡僅為範例）"""
    # 真實情境可參考Bitget官方API文檔
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT"
    try:
        res = requests.get(url, timeout=5)
        return float(res.json()['price'])
    except Exception as e:
        notify(f"⚠️ 無法獲取 {symbol} 幣價: {e}")
        return None

def ai_strategy(symbols):
    """多幣自動盯盤＋智能進出策略（模擬）"""
    notify(f"🤖 頂尖AI操盤手啟動！追蹤幣種：{', '.join(symbols)}")

    while True:
        for symbol in symbols:
            price = get_price(symbol)
            if price:
                notify(f"🔎 {symbol}/USDT 現價: {price}")
                # ------ 這裡可以放智能判斷/策略邏輯 ------
                if price < 10:
                    notify(f"💰 {symbol}/USDT 跌破 10，自動下單！（模擬）")
                # ----------------------------------------
            time.sleep(2)  # 每個幣查詢間隔2秒（防API限流）
        time.sleep(60 * 5)  # 每輪盯盤間隔5分鐘

if __name__ == "__main__":
    # 支持多幣自動盯盤
    symbols = ["BTC", "ETH", "SOL", "ASR", "BNB", "DOGE", "ADA", "MATIC", "XRP", "LINK", "TON", "OP", "LTC", "AVAX", "PEPE"]
    ai_strategy(symbols)
