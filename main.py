import os
import time
import threading
import requests
from flask import Flask

app = Flask(__name__)

# Простой веб-адрес, чтобы Render считал сервис активным
@app.route('/')
def home():
    return "OI Scanner is running!"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "SUIUSDT"]
OI_THRESHOLD_PERCENT = 2.0
previous_oi = {}

def send_telegram_alert(symbol, oi_change, current_price):
    message = (
        f"🚀 <b>АНОМАЛЬНЫЙ РОСТ OI!</b>\n\n"
        f"🔹 <b>Монета:</b> #{symbol}\n"
        f"📈 <b>Изменение OI (5m):</b> <code>+{oi_change:.2f}%</code>\n"
        f"💵 <b>Текущая цена:</b> <code>${current_price:.2f}</code>\n"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Ошибка отправки: {e}")

def get_bybit_market_data(symbol):
    try:
        oi_url = f"https://api.bybit.com/v5/market/open-interest?category=linear&symbol={symbol}&intervalTime=5min&limit=1"
        ticker_url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={symbol}"
        oi_res = requests.get(oi_url).json()
        ticker_res = requests.get(ticker_url).json()
        if oi_res["retCode"] == 0 and ticker_res["retCode"] == 0:
            latest_oi = float(oi_res["result"]["list"][0]["openInterest"])
            last_price = float(ticker_res["result"]["list"][0]["lastPrice"])
            return latest_oi, last_price
    except Exception as e:
        print(f"Ошибка данных {symbol}: {e}")
    return None, None

def scanner_loop():
    print("🤖 Скринер запущен...")
    while True:
        for symbol in SYMBOLS:
            current_oi, current_price = get_bybit_market_data(symbol)
            if current_oi and current_price:
                if symbol in previous_oi:
                    old_oi = previous_oi[symbol]
                    oi_change_pct = ((current_oi - old_oi) / old_oi) * 100
                    if oi_change_pct >= OI_THRESHOLD_PERCENT:
                        send_telegram_alert(symbol, oi_change_pct, current_price)
                previous_oi[symbol] = current_oi
            time.sleep(1)
        time.sleep(300)

# Запускаем фоновый поток для скринера
threading.Thread(target=scanner_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
