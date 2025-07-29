import requests, time, hmac, hashlib, base64, os, uuid, json
import numpy as np

# ===== Bitget API密鑰設置 =====
BITGET_API_KEY = os.getenv("BITGET_API_KEY")
BITGET_API_SECRET = os.getenv("BITGET_API_SECRET")
BITGET_API_PASSPHRASE = os.getenv("BITGET_API_PASSPHRASE")

# ===== Telegram設置 =====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ===== 操盤參數 =====
SYMBOLS = ["BTCUSDT_UMCBL", "ETHUSDT_UMCBL", "SOLUSDT_UMCBL", "BNBUSDT_UMCBL", "XRPUSDT_UMCBL"]
LEVERAGE = 15                # 槓桿倍數
MAX_POS_PCT = 0.20           # 單幣最大資金配比(20%)
ORDER_GRID = 3               # 分批建倉數
TAKE_PROFIT = 0.012          # 止盈比例 1.2%
STOP_LOSS = 0.007            # 止損比例 0.7%

def notify(msg):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})

def sign_request(api_secret, timestamp, method, request_path, body=''):
    body = body if body else ''
    prehash = f"{timestamp}{method.upper()}{request_path}{body}"
    signature = base64.b64encode(hmac.new(api_secret.encode(), prehash.encode(), hashlib.sha256).digest()).decode()
    return signature

def get_headers(method, request_path, body=''):
    timestamp = str(int(time.time() * 1000))
    signature = sign_request(BITGET_API_SECRET, timestamp, method, request_path, body)
    return {
        "ACCESS-KEY": BITGET_API_KEY,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": BITGET_API_PASSPHRASE,
        "Content-Type": "application/json"
    }

def bitget_get(path):
    url = f"https://api.bitget.com{path}"
    headers = get_headers("GET", path)
    res = requests.get(url, headers=headers, timeout=10)
    return res.json()

def bitget_post(path, payload):
    url = f"https://api.bitget.com{path}"
    body = json.dumps(payload) if payload else ''
    headers = get_headers("POST", path, body)
    res = requests.post(url, headers=headers, data=body, timeout=10)
    return res.json()

def get_account_equity():
    path = "/api/mix/v1/account/account?productType=umcbl"
    try:
        data = bitget_get(path)
        eq = float(data['data'][0]['usdtEquity'])
        return eq
    except:
        notify("⚠️ 無法獲取帳戶權益")
        return 100

def get_last_price(symbol):
    path = f"/api/mix/v1/market/ticker?symbol={symbol}&productType=umcbl"
    try:
        res = requests.get("https://api.bitget.com" + path, timeout=8)
        return float(res.json()['data']['last'])
    except Exception as e:
        notify(f"⚠️ 取得 {symbol} 報價失敗: {e}")
        return None

def get_ohlc(symbol, limit=60):
    path = f"/api/mix/v1/market/candles?symbol={symbol}&granularity=1m&limit={limit}"
    try:
        res = requests.get("https://api.bitget.com" + path, timeout=8)
        candles = res.json()['data']
        closes = [float(c[4]) for c in candles[::-1]]
        return closes
    except:
        notify(f"⚠️ 取得 {symbol} K線失敗")
        return None

def get_position(symbol):
    path = f"/api/mix/v1/position/singlePosition?symbol={symbol}&marginCoin=USDT"
    try:
        data = bitget_get(path)
        return data['data']
    except Exception as e:
        notify(f"⚠️ 查持倉失敗: {e}")
        return None

def place_order(symbol, side, size, leverage):
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
        notify(f"🚀 下單: {side} {symbol} {size} x{leverage} 回傳:{res}")
    except Exception as e:
        notify(f"❌ 下單失敗: {e}")

def close_all_positions(symbol):
    pos = get_position(symbol)
    if pos and float(pos['total']):  # 若有持倉
        side = "close_long" if float(pos['holdSide']) > 0 else "close_short"
        place_order(symbol, side, abs(float(pos['total'])), LEVERAGE)

# ======= AI多因子進出場判斷 =======
def ai_signal(symbol):
    closes = get_ohlc(symbol, 40)
    if not closes: return "wait"
    arr = np.array(closes)
    ma20 = np.mean(arr[-20:])
    ma5 = np.mean(arr[-5:])
    price = arr[-1]
    atr = np.mean(np.abs(arr[1:] - arr[:-1]))
    # 例: 短線突破+動量+波動因子
    if price > ma20 and ma5 > ma20 and (price - ma20) > atr*2:
        return "open_long"
    if price < ma20 and ma5 < ma20 and (ma20 - price) > atr*2:
        return "open_short"
    return "wait"

# ======= 主程式 =======
def ai_trader():
    notify("🤖【AI量化控盤系統啟動】主流幣合約全天候巡邏！")
    while True:
        equity = get_account_equity()
        unit = round((equity * MAX_POS_PCT) / ORDER_GRID, 2)
        for symbol in SYMBOLS:
            price = get_last_price(symbol)
            if not price: continue
            signal = ai_signal(symbol)
            pos = get_position(symbol)
            msg = f"幣:{symbol} 現價:{price}\n判斷:{signal} 資金:{equity} 單筆:{unit}槓桿:{LEVERAGE}\n"
            if signal == "open_long" and (not pos or float(pos['total']) == 0):
                notify("🟢 [進場做多]\n"+msg)
                for _ in range(ORDER_GRID):
                    place_order(symbol, "open_long", unit, LEVERAGE)
                    time.sleep(1)
            elif signal == "open_short" and (not pos or float(pos['total']) == 0):
                notify("🔴 [進場做空]\n"+msg)
                for _ in range(ORDER_GRID):
                    place_order(symbol, "open_short", unit, LEVERAGE)
                    time.sleep(1)
            elif pos and float(pos['total']):
                cost = float(pos['openPriceAvg'])
                if (pos['holdSide'] == 'long' and price >= cost*(1+TAKE_PROFIT)) or (pos['holdSide'] == 'short' and price <= cost*(1-TAKE_PROFIT)):
                    notify("🏁 [止盈平倉]\n"+msg)
                    close_all_positions(symbol)
                elif (pos['holdSide'] == 'long' and price <= cost*(1-STOP_LOSS)) or (pos['holdSide'] == 'short' and price >= cost*(1+STOP_LOSS)):
                    notify("⚡ [止損平倉]\n"+msg)
                    close_all_positions(symbol)
            else:
                notify(f"⏸️ [{symbol}] 觀望中… 現價:{price}")
            time.sleep(3)
        time.sleep(60)

if __name__ == "__main__":
    ai_trader()

