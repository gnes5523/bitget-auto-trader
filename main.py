# main.py
import os
import time
import requests
import hmac
import hashlib
import base64
import uuid
import json
import numpy as np

# ====== 环境变量读取 ======
BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET = os.getenv("BITGET_API_SECRET")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ====== 操盘参数 ======
SYMBOLS = ["BTCUSDT_UMCBL", "ETHUSDT_UMCBL", "SOLUSDT_UMCBL", "BNBUSDT_UMCBL", "XRPUSDT_UMCBL"]
LEVERAGE = 15
MAX_POS_PCT = 0.20
ORDER_GRID = 3
TAKE_PROFIT = 0.012
STOP_LOSS = 0.007

def notify(msg: str):
    """发送 Telegram 通知"""
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
                timeout=5
            )
        except:
            pass

# ====== Bitget 签名与请求 ======
def sign_request(secret, ts, method, path, body=''):
    prehash = f"{ts}{method.upper()}{path}{body or ''}"
    return base64.b64encode(hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()).decode()

def get_headers(method, path, body=''):
    ts = str(int(time.time() * 1000))
    sig = sign_request(BITGET_API_SECRET, ts, method, path, body)
    return {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": sig,
        "ACCESS-TIMESTAMP": ts,
        "ACCESS-PASSPHRASE": BITGET_API_PASSPHRASE,
        "Content-Type": "application/json"
    }

def bitget_get(path):
    return requests.get("https://api.bitget.com" + path, headers=get_headers("GET", path), timeout=10).json()

def bitget_post(path, payload):
    body = json.dumps(payload)
    return requests.post("https://api.bitget.com" + path, headers=get_headers("POST", path, body), data=body, timeout=10).json()

# ====== 数据获取函数（已修复空值判断） ======
def get_account_equity() -> float:
    """获取账户 USDT 权益，支持空值保护"""
    path = "/api/mix/v1/account/accounts?productType=umcbl"
    res = bitget_get(path)
    data = res.get("data") if isinstance(res, dict) else None
    if not data or not isinstance(data, list):
        notify(f"⚠️ 获取账户权益接口返回异常: {res}")
        return 0.0
    try:
        return float(data[0].get("usdtEquity", 0))
    except Exception as e:
        notify(f"⚠️ 解析账户权益失败: {e}")
        return 0.0

def get_last_price(symbol: str) -> float:
    path = f"/api/mix/v1/market/ticker?symbol={symbol}&productType=umcbl"
    try:
        return float(requests.get("https://api.bitget.com" + path, timeout=8).json()['data']['last'])
    except Exception as e:
        notify(f"⚠️ 获取{symbol}最新价失败: {e}")
        return None

def get_ohlc(symbol: str, limit: int = 60) -> list:
    path = f"/api/mix/v1/market/candles?symbol={symbol}&granularity=60&limit={limit}"
    try:
        arr = requests.get("https://api.bitget.com" + path, timeout=8).json().get('data', [])
        return [float(c[4]) for c in arr[::-1]]
    except Exception as e:
        notify(f"⚠️ 获取{symbol}K线失败: {e}")
        return None

def get_position(symbol: str) -> dict:
    path = f"/api/mix/v1/position/singlePosition?symbol={symbol}&marginCoin=USDT"
    try:
        return bitget_get(path).get('data', {})
    except Exception as e:
        notify(f"⚠️ 查询{symbol}持仓失败: {e}")
        return {}

# ====== 下单与平仓 ======
def place_order(symbol: str, side: str, size: float, leverage: int):
    path = "/api/mix/v1/order/placeOrder"
    payload = {
        "symbol": symbol,
        "marginCoin": "USDT",
        "size": str(size),
        "side": side,
        "orderType": "market",
        "force": "gtc",
        "leverage": str(leverage),
        "clientOid": str(uuid.uuid4())
    }
    try:
        res = bitget_post(path, payload)
        notify(f"🚀 {symbol} {side} x{leverage} 数量{size} 下单回报: {res}")
    except Exception as e:
        notify(f"❌ 下单失败 {symbol} {side}: {e}")

def close_all_positions(symbol: str):
    pos = get_position(symbol)
    total = float(pos.get('total', 0))
    if total:
        side = "close_long" if pos.get('holdSide')=="long" else "close_short"
        place_order(symbol, side, abs(total), LEVERAGE)

# ====== AI 策略判断 ======
def ai_signal(symbol: str, closes: list) -> str:
    arr = np.array(closes)
    ma20 = arr[-20:].mean()
    ma5  = arr[-5:].mean()
    price = arr[-1]
    atr = np.mean(np.abs(arr[1:] - arr[:-1]))
    if price > ma20 and ma5 > ma20 and (price - ma20) > 2*atr:
        return "open_long"
    if price < ma20 and ma5 < ma20 and (ma20 - price) > 2*atr:
        return "open_short"
    return "wait"

# ====== 主循环 ======
def ai_trader():
    notify("🤖【AI量化控盘系统】启动：Bitget合约全天候监控")
    while True:
        equity = get_account_equity()
        if equity <= 0:
            time.sleep(30)
            continue
        unit = round((equity * MAX_POS_PCT) / ORDER_GRID, 4)
        for symbol in SYMBOLS:
            price = get_last_price(symbol)
            if not price:
                continue
            closes = get_ohlc(symbol, 60)
            if not closes:
                continue
            signal = ai_signal(symbol, closes)
            pos = get_position(symbol)
            has_pos = float(pos.get('total', 0)) != 0
            msg = f"{symbol} 现价:{price:.2f} 信号:{signal} 权益:{equity:.2f} 单笔:{unit}"
            if signal in ["open_long","open_short"] and not has_pos:
                notify(f"🟢 开仓信号→ {msg}")
                for _ in range(ORDER_GRID):
                    place_order(symbol, signal, unit, LEVERAGE)
                    time.sleep(1)
            elif has_pos:
                entry = float(pos.get('openPriceAvg', price))
                side  = pos.get('holdSide')
                if side=="long":
                    if price >= entry*(1+TAKE_PROFIT):
                        notify(f"🏁 止盈→ {msg}")
                        close_all_positions(symbol)
                    elif price <= entry*(1-STOP_LOSS):
                        notify(f"⚡ 止损→ {msg}")
                        close_all_positions(symbol)
                else:
                    if price <= entry*(1-TAKE_PROFIT):
                        notify(f"🏁 止盈空→ {msg}")
                        close_all_positions(symbol)
                    elif price >= entry*(1+STOP_LOSS):
                        notify(f"⚡ 止损空→ {msg}")
                        close_all_positions(symbol)
            else:
                notify(f"⏸️ 观望→ {msg}")
            time.sleep(2)
        time.sleep(60)

if __name__ == "__main__":
    ai_trader()



