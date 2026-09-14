import os
import time
import threading
from pybit.unified_trading import HTTP
import requests
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "OI Scanner is active and running 24/7!"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

OI_THRESHOLD_PERCENT = 2.0
CHECK_INTERVAL_SECONDS = 300  # 5 минут

session = HTTP(testnet=False)
previous_oi = {}

def get_all_usdt_symbols():
    try:
        response = session.get_instruments_info(category="linear")
        if response.get("retCode") == 0:
            return [
                item["symbol"] for item in response["result"]["list"] 
                if item["symbol"].endswith("USDT") and item["status"] == "Trading"
            ]
    except Exception as e:
        print(f"❌ Ошибка получения списка монет: {e}")
    return []

def send_telegram_alert(symbol, oi_change, current_price):
    message = (
        f"🚀 <b>АНОМАЛЬНЫЙ РОСТ OI!</b>\n\n"
        f"🔹 <b>Монета:</b> #{symbol}\n"
        f"📈 <b>Изменение OI (5m):</b> <code>+{oi_change:.2f}%</code>\n"
        f"💵 <b>Текущая цена:</b> <code>${current_price}</code>\n\n"
        f"💡 <i>Проверь 5M график на наличие 3 подтверждений!</i>"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"❌ Ошибка отправки в Telegram: {e}")

def scanner_loop():
    print("🤖 Скринер успешно запущен в фоновом режиме...")
    
    while True:
        symbols = get_all_usdt_symbols()
        if not symbols:
            time.sleep(10)
            continue

        alerts_sent = 0
        for symbol in symbols:
            try:
                oi_res = session.get_open_interest(category="linear", symbol=symbol, intervalTime="5min", limit=1)
                ticker_res = session.get_tickers(category="linear", symbol=symbol)

                if oi_res.get("retCode") == 0 and ticker_res.get("retCode") == 0:
                    oi_data = oi_res["result"]["list"]
                    ticker_data = ticker_res["result"]["list"]

                    if oi_data and ticker_data:
                        current_oi = float(oi_data[0]["openInterest"])
                        current_price = ticker_data[0]["lastPrice"]

                        if symbol in previous_oi:
                            prev_oi = previous_oi[symbol]
                            if prev_oi > 0:
                                oi_change = ((current_oi - prev_oi) / prev_oi) * 100
                                if oi_change >= OI_THRESHOLD_PERCENT:
                                    send_telegram_alert(symbol, oi_change, current_price)
                                    alerts_sent += 1
                                    print(f"🔥 АЛЕРТ: {symbol} +{oi_change:.2f}%")

                        previous_oi[symbol] = current_oi
            except Exception:
                continue

            time.sleep(0.04)

        print(f"✅ Круг завершен. Монет в базе: {len(previous_oi)}. Отправлено алертов: {alerts_sent}. Пауза 5 минут...")
        time.sleep(CHECK_INTERVAL_SECONDS)

# Запуск фонового процесса
threading.Thread(target=scanner_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
