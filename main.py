import time
import os
import requests

# Берем настройки из переменных окружения сервера
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "SUIUSDT"]
OI_THRESHOLD_PERCENT = 2.0  # Порог +2% за 5 минут
previous_oi = {}

def send_telegram_alert(symbol, oi_change, current_price):
    message = (
        f"🚀 <b>АНОМАЛЬНЫЙ РОСТ OI!</b>\n\n"
        f"🔹 <b>Монета:</b> #{symbol}\n"
        f"📈 <b>Изменение OI (5m):</b> <code>+{oi_change:.2f}%</code>\n"
        f"💵 <b>Текущая цена:</b> <code>${current_price:.2f}</code>\n"
        f"⏱ <b>Статус:</b> Заход денег / Набор позиции\n\n"
        f"💡 <i>Проверь 5M график на наличие 3 подтверждений!</i>"
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
        print(f"Ошибка получения данных {symbol}: {e}")
    return None, None

def main():
    print("🤖 Скринер запущен на удаленном сервере...")
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
        time.sleep(300) # Проверка каждые 5 минут

if __name__ == "__main__":
    main()
