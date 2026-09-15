import os
import time
import requests
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# Переменные окружения
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Порог входа (временно 0.5% для быстрого теста, затем верните 2.0%)
OI_THRESHOLD_PERCENT = 0.5  
previous_oi = {}

@app.route('/')
def home():
    return f"Binance OI Scanner Active. Tracked coins in memory: {len(previous_oi)}"

def send_telegram_alert(symbol, oi_change, current_price):
    message = (
        f"🚀 <b>BINANCE: АНОМАЛЬНЫЙ РОСТ OI!</b>\n\n"
        f"🔹 <b>Монета:</b> #{symbol}\n"
        f"📈 <b>Изменение OI (5m):</b> <code>+{oi_change:.2f}%</code>\n"
        f"💵 <b>Цена:</b> <code>${current_price}</code>\n"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=5)
    except Exception as e:
        print(f"❌ Telegram Error: {e}")

def scan_binance_market():
    """Сбор OI и цен со всех фьючерсных пар Binance (USDT-M)"""
    global previous_oi
    print("🔄 Запуск сканирования Binance Futures...")
    
    try:
        # 1. Получаем список всех активов и текущие цены
        ticker_url = "https://fapi.binance.com/fapi/v1/ticker/price"
        ticker_res = requests.get(ticker_url, timeout=10).json()
        
        # Фильтруем только торгуемые USDT-пары (исключаем индексы и дериваты)
        usdt_pairs = {
            item['symbol']: float(item['price']) 
            for item in ticker_res 
            if item['symbol'].endswith('USDT')
        }

        print(f"📊 Найдено пар Binance: {len(usdt_pairs)}. Сканируем OI...")
        alerts_count = 0

        # 2. Получаем Open Interest для каждой пары
        for symbol, current_price in usdt_pairs.items():
            try:
                oi_url = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}"
                oi_res = requests.get(oi_url, timeout=3).json()

                if "openInterest" in oi_res:
                    current_oi = float(oi_res["openInterest"])

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

            time.sleep(0.02) # Защита от лимитов

        print(f"✅ Сканирование Binance завершено. Монет в базе: {len(previous_oi)}. Алертов: {alerts_count}")

    except Exception as e:
        print(f"❌ Критическая ошибка Binance API: {e}")

# Настройка планировщика на 5 минут
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(scan_binance_market, 'interval', minutes=5)
scheduler.start()

# Первичный запуск при старте
scan_binance_market()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
