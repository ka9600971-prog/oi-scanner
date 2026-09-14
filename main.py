import os
import time
import threading
from pybit.unified_trading import HTTP
import requests
from flask import Flask

# Инициализация веб-сервера Flask для Render
app = Flask(__name__)

@app.route('/')
def home():
    return "OI Scanner for ALL Altcoins is running!"

# Переменные окружения Render
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Настройки скринера
OI_THRESHOLD_PERCENT = 0.1  # Порог роста OI (в %)
CHECK_INTERVAL_SECONDS = 300  # Интервал проверки (5 минут)

# Инициализация клиента Bybit
session = HTTP(testnet=False)
previous_oi = {}

def get_all_usdt_symbols():
    """Получает список ВСЕХ активных USDT-перпетуалов с Bybit"""
    try:
        response = session.get_instruments_info(category="linear")
        if response.get("retCode") == 0:
            list_data = response["result"]["list"]
            symbols = [
                item["symbol"] for item in list_data 
                if item["symbol"].endswith("USDT") and item["status"] == "Trading"
            ]
            print(f"📊 Загружено монет для мониторинга: {len(symbols)}")
            return symbols
    except Exception as e:
        print(f"❌ Ошибка запроса списка монет: {e}")
    return []

def send_telegram_alert(symbol, oi_change, current_price):
    """Отправка алертов в Telegram"""
    message = (
        f"🚀 <b>АНОМАЛЬНЫЙ РОСТ OI (АЛЬТКОИНЫ)!</b>\n\n"
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
    """Основной цикл сканирования всех альтов"""
    print("🤖 Скринер запущен и проверяет ВСЕ альткоины...")
    
    # 🧪 ТЕСТОВЫЙ СИГНАЛ ПРИ СТАРТЕ
    send_telegram_alert("TEST_BTCUSDT", 2.5, 65000.0)

    while True:
        # ... весь остальной код остается без изменений ...

        symbols = get_all_usdt_symbols()
        if not symbols:
            time.sleep(10)
            continue

        for symbol in symbols:
            try:
                oi_response = session.get_open_interest(
                    category="linear",
                    symbol=symbol,
                    intervalTime="5min",
                    limit=1
                )
                ticker_response = session.get_tickers(
                    category="linear",
                    symbol=symbol
                )

                if oi_response.get("retCode") == 0 and ticker_response.get("retCode") == 0:
                    oi_list = oi_response["result"]["list"]
                    ticker_list = ticker_response["result"]["list"]

                    if oi_list and ticker_list:
                        current_oi = float(oi_list[0]["openInterest"])
                        current_price = ticker_list[0]["lastPrice"]

                        if symbol in previous_oi:
                            prev_oi = previous_oi[symbol]
                            if prev_oi > 0:
                                oi_change = ((current_oi - prev_oi) / prev_oi) * 100

                                if oi_change >= OI_THRESHOLD_PERCENT:
                                    send_telegram_alert(symbol, oi_change, current_price)
                                    print(f"🔥 Сигнал по {symbol}: +{oi_change:.2f}%")

                        previous_oi[symbol] = current_oi

            except Exception:
                continue

            time.sleep(0.05) # Защита от банов по IP

        print(f"✅ Сканирование {len(symbols)} монет завершено. Ожидание 5 минут...")
        time.sleep(CHECK_INTERVAL_SECONDS)

# Запуск скринера в фоновом потоке
threading.Thread(target=scanner_loop, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
