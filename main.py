import os
import time
import html
import threading
from collections import deque, defaultdict
from datetime import datetime

import requests
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

BASE = "https://fapi.binance.com"
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# ---------- настройки (можно менять через переменные окружения) ----------
SCAN_MINUTES = int(os.environ.get("SCAN_MINUTES", 5))
OI_PCT_5M = float(os.environ.get("OI_PCT_5M", 3.0))      # порог роста ОИ за скан (5 мин)
OI_PCT_30M = float(os.environ.get("OI_PCT_30M", 5.0))    # порог роста ОИ за 30 мин
MIN_OI_DELTA_USD = float(os.environ.get("MIN_OI_DELTA_USD", 300_000))  # минимум прироста в $
MIN_VOLUME_24H_USD = float(os.environ.get("MIN_VOLUME_24H_USD", 2_000_000))
COOLDOWN_MIN = int(os.environ.get("COOLDOWN_MIN", 30))  # пауза на монету между алертами
WINDOW_SCANS = 30 // SCAN_MINUTES                       # сколько сканов в окне 30 минут

session = requests.Session()
history = defaultdict(lambda: deque(maxlen=WINDOW_SCANS + 1))  # symbol -> [(ts, oi_coins)]
last_alert = {}
last_status = "Инициализация..."
scan_lock = threading.Lock()


# ---------- запросы к Binance ----------
def api_get(path, params=None, timeout=8):
    try:
        r = session.get(BASE + path, params=params, timeout=timeout)
        if r.status_code in (418, 429):
            wait = int(r.headers.get("Retry-After", 30))
            print(f"⚠️ Лимит Binance, жду {wait} c")
            time.sleep(min(wait, 60))
            return None
        if r.status_code == 451:
            print("⛔ 451: Binance недоступен из региона сервера")
            return None
        if r.status_code != 200:
            print(f"⚠️ {path} {r.status_code}: {r.text[:120]}")
            return None
        return r.json()
    except Exception as e:
        print(f"❌ {path}: {e}")
        return None


def pct(a, b):
    return (a - b) / b * 100 if b else 0.0


# ---------- обогащение сигнала ----------
def enrich(symbol, mark_price, funding_rate):
    info = {"funding": funding_rate * 100}

    # свечи 5м: цена и объём
    kl = api_get("/fapi/v1/klines", {"symbol": symbol, "interval": "5m", "limit": 60})
    if kl and len(kl) >= 50:
        closes = [float(k[4]) for k in kl]
        qvol = [float(k[7]) for k in kl]  # объём в USDT
        last = closes[-1]
        info["p5"] = pct(last, closes[-2])
        info["p30"] = pct(last, closes[-7])
        info["p1h"] = pct(last, closes[-13])
        info["p4h"] = pct(last, closes[-49])
        vol30 = sum(qvol[-6:])
        base = sum(qvol[:-6]) / max(len(qvol[:-6]) / 6, 1)
        info["vol30"] = vol30
        info["vol_ratio"] = vol30 / base if base else 0

    # давление покупателей/продавцов (taker buy/sell) за ~30 мин
    tk = api_get("/futures/data/takerlongshortRatio", {"symbol": symbol, "period": "5m", "limit": 6})
    if tk:
        info["taker"] = sum(float(x["buySellRatio"]) for x in tk) / len(tk)

    # лонги/шорты топ-трейдеров (по позициям) и всех аккаунтов
    top = api_get("/futures/data/topLongShortPositionRatio", {"symbol": symbol, "period": "5m", "limit": 1})
    if top:
        info["top_ls"] = float(top[-1]["longShortRatio"])
    glob = api_get("/futures/data/globalLongShortAccountRatio", {"symbol": symbol, "period": "5m", "limit": 1})
    if glob:
        info["all_ls"] = float(glob[-1]["longShortRatio"])
    return info


def btc_context():
    kl = api_get("/fapi/v1/klines", {"symbol": "BTCUSDT", "interval": "5m", "limit": 14})
    if kl and len(kl) >= 13:
        closes = [float(k[4]) for k in kl]
        return pct(closes[-1], closes[-7]), pct(closes[-1], closes[-13])
    return None, None


def verdict(oi5, oi30, info):
    """Простая оценка направления: набор очков за лонг (+) или за шорт (-)."""
    score = 0
    notes = []
    p30 = info.get("p30")
    if p30 is not None:
        if p30 >= 0.3:
            score += 1
        elif p30 <= -0.3:
            score -= 1
    taker = info.get("taker")
    if taker is not None:
        if taker >= 1.1:
            score += 1
        elif taker <= 0.9:
            score -= 1
    p4h = info.get("p4h")
    if p4h is not None and p30 is not None:
        if p4h > 1 and p30 > 0:
            score += 1
        elif p4h < -1 and p30 < 0:
            score -= 1
    f = info["funding"]
    if f >= 0.05:
        notes.append("⚠️ фандинг высокий: лонги перегреты")
    elif f <= -0.05:
        notes.append("⚠️ фандинг сильно отрицательный: шорты перегреты")
    vr = info.get("vol_ratio")
    if vr is not None and vr < 0.8:
        notes.append("⚠️ объём ниже обычного")

    if score >= 2:
        label = "🟢 ЛОНГИ набирают"
    elif score <= -2:
        label = "🔴 ШОРТЫ набирают"
    else:
        label = "⚪ направление неясно"
    strength = min(5, abs(score) + (1 if vr and vr >= 1.5 else 0) + (1 if oi30 and oi30 >= 2 * OI_PCT_30M else 0))
    return label, strength, notes


# ---------- Telegram ----------
def fmt(v, suffix="%", digits=2, sign=True):
    if v is None:
        return "н/д"
    return f"{v:+.{digits}f}{suffix}" if sign else f"{v:.{digits}f}{suffix}"


def send_telegram_alert(symbol, oi5, oi30, oi_usd, delta_usd, price, info, btc):
    label, strength, notes = verdict(oi5, oi30, info)
    sym = html.escape(symbol)
    btc30, btc1h = btc
    lines = [
        f"🪙 <b>Binance</b> — <a href='https://www.binance.com/ru/futures/{sym}'>{sym}</a>",
        f"{label}  (сила {strength}/5)",
        "",
        f"📈 <b>ОИ:</b> 5м <code>{fmt(oi5)}</code> | 30м <code>{fmt(oi30)}</code>",
        f"💰 ОИ сейчас <code>{oi_usd/1e6:.2f} млн $</code> (прирост <code>{delta_usd/1e6:.2f} млн $</code>)",
        f"💲 <b>Цена:</b> <code>{price}</code>",
        f"   5м {fmt(info.get('p5'))} | 30м {fmt(info.get('p30'))} | 1ч {fmt(info.get('p1h'))} | 4ч {fmt(info.get('p4h'))}",
        f"📊 <b>Объём 30м:</b> <code>{(info.get('vol30') or 0)/1e6:.2f} млн $</code>"
        f" (×{(info.get('vol_ratio') or 0):.1f} к обычному)",
        f"💸 <b>Фандинг:</b> <code>{info['funding']:+.4f}%</code>",
        f"⚖️ <b>Покупатели/продавцы (taker):</b> <code>{fmt(info.get('taker'), '', 2, False)}</code>",
        f"👥 <b>Лонг/шорт топ-трейдеров:</b> <code>{fmt(info.get('top_ls'), '', 2, False)}</code>"
        f" | всех: <code>{fmt(info.get('all_ls'), '', 2, False)}</code>",
        f"🌐 <b>BTC:</b> 30м {fmt(btc30)} | 1ч {fmt(btc1h)}",
    ]
    if notes:
        lines.append("")
        lines.extend(notes)
    message = "\n".join(lines)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML",
                                 "disable_web_page_preview": True}, timeout=8)
    except Exception as e:
        print(f"❌ Telegram: {e}")


# ---------- основной скан ----------
def scan_binance_market():
    global last_status
    if not scan_lock.acquire(blocking=False):
        return  # предыдущий скан ещё идёт
    try:
        started = time.time()
        info_res = api_get("/fapi/v1/exchangeInfo", timeout=15)
        if not info_res or "symbols" not in info_res:
            last_status = "Нет ответа exchangeInfo (лимит, 451 или сеть)"
            return

        symbols = [s["symbol"] for s in info_res["symbols"]
                   if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"
                   and s.get("contractType") == "PERPETUAL"]

        tickers = {t["symbol"]: t for t in (api_get("/fapi/v1/ticker/24hr", timeout=15) or [])}
        premium = {p["symbol"]: p for p in (api_get("/fapi/v1/premiumIndex", timeout=15) or [])}
        if not tickers or not premium:
            last_status = "Нет данных ticker/premiumIndex"
            return

        now = time.time()
        candidates = []
        ok = 0
        for symbol in symbols:
            if symbol not in premium or symbol not in tickers:
                continue
            oi_res = api_get("/fapi/v1/openInterest", {"symbol": symbol}, timeout=4)
            time.sleep(0.03)
            if not isinstance(oi_res, dict) or "openInterest" not in oi_res:
                continue
            ok += 1
            oi = float(oi_res["openInterest"])
            mark = float(premium[symbol]["markPrice"])
            oi_usd = oi * mark
            hist = history[symbol]

            if hist:
                prev_oi = hist[0 if len(hist) == hist.maxlen else 0][1]
                oi5 = pct(oi, hist[-1][1])
                # окно 30м: сравниваем с самой старой записью, если ей >= 25 минут
                old_ts, old_oi = hist[0]
                oi30 = pct(oi, old_oi) if now - old_ts >= 25 * 60 else None
                delta_usd = (oi - hist[-1][1]) * mark
                if oi30 is not None and (oi - old_oi) * mark > delta_usd:
                    delta_usd = (oi - old_oi) * mark
                vol24 = float(tickers[symbol]["quoteVolume"])
                trigger = (oi5 >= OI_PCT_5M) or (oi30 is not None and oi30 >= OI_PCT_30M)
                if (trigger and delta_usd >= MIN_OI_DELTA_USD and vol24 >= MIN_VOLUME_24H_USD
                        and now - last_alert.get(symbol, 0) >= COOLDOWN_MIN * 60):
                    candidates.append((symbol, oi5, oi30, oi_usd, delta_usd, mark,
                                       float(premium[symbol]["lastFundingRate"])))
            hist.append((now, oi))

        alerts = 0
        if candidates:
            btc = btc_context()
            # самые крупные по приросту в $ — первыми
            for symbol, oi5, oi30, oi_usd, delta_usd, mark, fr in sorted(candidates, key=lambda c: -c[4]):
                info = enrich(symbol, mark, fr)
                send_telegram_alert(symbol, oi5, oi30, oi_usd, delta_usd, mark, info, btc)
                last_alert[symbol] = now
                alerts += 1
                time.sleep(0.5)

        last_status = (f"Скан {datetime.now():%H:%M:%S}: монет {ok}/{len(symbols)}, алертов {alerts}, "
                       f"{time.time() - started:.0f} c")
        print(f"✅ {last_status}")
    except Exception as e:
        last_status = f"Ошибка: {e}"
        print(f"❌ {last_status}")
    finally:
        scan_lock.release()


@app.route("/")
def home():
    return (f"<h3>Binance OI Scanner</h3><b>Монет в памяти:</b> {len(history)}<br>"
            f"<b>Статус:</b> {html.escape(last_status)}")


scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(scan_binance_market, "interval", minutes=SCAN_MINUTES,
                  max_instances=1, coalesce=True, next_run_time=datetime.now())
scheduler.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
