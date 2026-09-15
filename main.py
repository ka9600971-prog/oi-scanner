import os
import time
import requests
from flask import Flask
from pybit.unified_trading import HTTP
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# Переменные окружения
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Временно 0.5% для гарантированного теста отправки
OI_THRESHOLD_PERCENT = 0.5  
session = HTTP(testnet=False)
previous_oi = {}

@app.route('/')
def home():
    return f"OI Scanner Active. Tracked coins in memory: {len(previous_oi)}"

def send_telegram_alert(symbol, oi_change, current_price):
    message = (
        f"🚀 <b>АНОМАЛЬНЫЙ РОСТ OI!</b>\n\n"
        f"🔹 <b>Монета:</b> #{symbol}\n"
        f"📈 <b>Изменение OI (5m):</b> <code>+{oi_change:.2f}%</code>\n"
        f"💵 <b>Цена:</b> <code>${current_price}</code>\n"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=5)
    except Exception as e:
        print(f"❌ Telegram Error: {e}")

def scan_market():
    """Сканирование рынка каждые 5 минут"""
    global previous_oi
    print("🔄 Запуск сканирования Bybit...")
    
    try:
        response = session.get_instruments_info(category="linear")
        if response.get("retCode") != 0:
            print(f"❌ Ошибка Bybit API: {response.get('retMsg')}")
            return
        
        symbols = [
            item["symbol"] for item in response["result"]["list"] 
            if item["symbol"].endswith("USDT") and item["status"] == "Trading"
        ]

        print(f"📊 Найдено пар: {len(symbols)}. Начинаем сбор OI...")
        alerts_count = 0
        
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
                                    alerts_count += 1
                                    print(f"🔥 АЛЕРТ: {symbol} +{oi_change:.2f}%")

                        previous_oi[symbol] = current_oi
            except Exception:
                continue

            time.sleep(0.02)

        print(f"✅ Сканирование завершено. Сохранено монет: {len(previous_oi)}. Алертов: {alerts_count}")

    except Exception as e:
        print(f"❌ Критическая ошибка цикла: {e}")

# Запуск фонового планировщика
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(scan_market, 'interval', minutes=5)
scheduler.start()

# Первичная загрузка базы при старте
scan_market()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
