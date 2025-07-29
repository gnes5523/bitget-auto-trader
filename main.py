import time
import requests
import os

# ----- Bitget API Key 設定 -----
API_KEY = os.getenv("BITGET_API_KEY")
API_SECRET = os.getenv("BITGET_API_SECRET")
API_PASSPHRASE = os.getenv("BITGET_PASSPHRASE")

# ----- Telegram 設定 -----
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def notify(msg):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
        print(r.text)  # 印出 response 看有沒有報錯
    else:
        print("沒有找到 BOT_TOKEN 或 CHAT_ID")

if __name__ == "__main__":
    notify("測試訊息 from Render！")
