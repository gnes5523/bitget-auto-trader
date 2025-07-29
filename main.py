# main.py
import os
from telegram_notify import notify

def start_trading():
    api_key = os.getenv("BITGET_API_KEY")
    api_secret = os.getenv("BITGET_API_SECRET")
    passphrase = os.getenv("BITGET_PASSPHRASE")
    notify(f"📈 自動交易機器人啟動成功！\nAPI Key: {api_key[:4]}****")

if __name__ == "__main__":
    start_trading()
