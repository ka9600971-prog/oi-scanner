import os
import time
import requests
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

OI_THRESHOLD_PERCENT = 0.5  # Тестовый порог
previous_oi = {}
last_status = "Инициализация..."

@app.route('/')
def home():
    return f"<h3>Binance OI Scanner</h3><b>Монет в памяти:</b> {len(previous_oi)}<br><b>Статус:</b> {last_status}"

def send_telegram_alert(symbol, oi_change, current_price):
    message = (
        f"🚀 <b>BINANCE: РОСТ OI!</b>\n\n"
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
    global previous_oi, last_status
    print("🔄 Сканирование Binance...")
    
    try:
        # Один общий запрос на все пары сразу (гораздо быстрее)
        ticker_res = requests.get("https://fapi.binance.com/fapi/v1/ticker/price", timeout=10).json()
        usdt_pairs = [item['symbol'] for item in ticker_res if item['symbol'].endswith('USDT')]

        alerts_count = 0
        success_count = 0

        # Сканируем с групповым сбором
        for symbol in usdt_pairs:
            try:
                oi_res = requests.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}", timeout=2).json()
                if "openInterest" in oi_res:
                    current_oi = float(oi_res["openInterest"])
                    
                    if symbol in previous_oi:
                        prev_oi = previous_oi[symbol]
                        if prev_oi > 0:
                            oi_change = ((current_oi - prev_oi) / prev_oi) * 100
                            if oi_change >= OI_THRESHOLD_PERCENT:
                                send_telegram_alert(symbol, oi_change, 0)
                                alerts_count += 1

                    previous_oi[symbol] = current_oi
                    success_count += 1
            except Exception:
                continue
            
            time.sleep(0.01)

        last_status = f"Успешно. База обновлена. Успешных пар: {success_count}. Алертов: {alerts_count}"
        print(f"✅ {last_status}")

    except Exception as e:
        last_status = f"Ошибка API: {e}"
        print(f"❌ {last_status}")

# Запуск планировщика
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(scan_binance_market, 'interval', minutes=5)
scheduler.start()

# Запускаем один раз прямо при загрузке модуля
scan_binance_market()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
