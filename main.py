# main.py
import os
import time
from telegram_notify import notify

def start_trading():
    api_key = os.getenv("BITGET_API_KEY")
    api_secret = os.getenv("BITGET_API_SECRET")
    passphrase = os.getenv("BITGET_PASSPHRASE")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    print("📦 環境變數檢查：")
    print("BITGET_API_KEY:", api_key)
    print("BITGET_API_SECRET:", api_secret)
    print("BITGET_PASSPHRASE:", passphrase)
    print("TELEGRAM_BOT_TOKEN:", bot_token)
    print("TELEGRAM_CHAT_ID:", chat_id)

    if not all([api_key, api_secret, passphrase, bot_token, chat_id]):
        print("❌ 有變數為空，請檢查 Render 的 Environment 設定")
        return

    notify(f"✅ 機器人啟動成功！BITGET_KEY: {api_key[:4]}****")
    while True:
        time.sleep(60)  # 保持程式持續運行

if __name__ == "__main__":
    start_trading()
import time
while True:
    time.sleep(60)

