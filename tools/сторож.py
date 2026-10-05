#!/usr/bin/env python3
"""LUDUS reviews watchdog — замечает, что сбор замолчал, и кричит в Telegram.

Зачем: сбор запускается извне (cron-job.org → workflow_dispatch). Если внешний
пинок пропадает, всё выглядит нормально — просто данные тихо перестают
обновляться. Так мы потеряли месяц (02.09 → 05.10.2026).

Что делает: смотрит дату последнего снимка в данные/снимки.json и, если он
старше ПОРОГа, шлёт сообщение в Telegram. Apify НЕ трогает — ни одного цента.

Запуск: python3 tools/сторож.py [--порог 2] [--проба]
  --проба  ничего не отправлять, только напечатать, что было бы отправлено.
Секреты: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (env) или telegram.config.json.
"""
import datetime
import json
import os
import sys
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
ДАННЫЕ = os.path.join(ROOT, "данные")
СНИМКИ = os.path.join(ДАННЫЕ, "снимки.json")
ПОРОГ_ДНЕЙ = 2
REPO = "nikolaikozireff30-ship-it/ludus-reviews"
DASHBOARD_URL = "https://nikolaikozireff30-ship-it.github.io/ludus-reviews/"


def сейчас_пхукет():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("Asia/Bangkok"))
    except Exception:
        return datetime.datetime.utcnow() + datetime.timedelta(hours=7)


def конфиг_telegram():
    путь = os.path.join(ROOT, "telegram.config.json")
    if os.path.exists(путь):
        try:
            c = json.load(open(путь, encoding="utf-8"))
            tok = (c.get("bot_token") or "").strip()
            cid = str(c.get("chat_id") or "").strip()
            if tok and cid and not tok.startswith("ВСТАВЬ") and not cid.startswith("ВСТАВЬ"):
                return tok, cid
        except Exception as e:
            print("  ⚠ telegram.config.json:", e)
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    cid = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return (tok, cid) if tok and cid else None


def tg_send(text, tg):
    tok, cid = tg
    data = urllib.parse.urlencode({"chat_id": cid, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(
                urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendMessage", data=data),
                timeout=20) as r:
            return json.load(r).get("ok", False)
    except Exception as e:
        print("  ⚠ Telegram:", e)
        return False


def последний_снимок():
    """Дата самого свежего снимка, либо None, если файла/данных нет."""
    if not os.path.exists(СНИМКИ):
        return None
    try:
        снимки = json.load(open(СНИМКИ, encoding="utf-8"))
    except Exception as e:
        print("  ⚠ снимки.json не читается:", e)
        return None
    даты = sorted(k for k in снимки if isinstance(k, str) and len(k) == 10)
    return даты[-1] if даты else None


def дней_молчания(дата_строкой, сегодня):
    try:
        d = datetime.date.fromisoformat(дата_строкой)
    except Exception:
        return None
    return (сегодня - d).days


def текст(дней, последняя):
    слово = "day" if дней == 1 else "days"
    return (f"🚨 <b>Review monitor is silent.</b>\n\n"
            f"No data for <b>{дней} {слово}</b> — last snapshot: {последняя}.\n"
            f"The collector is not being triggered, so new reviews are not recorded "
            f"and the dashboard is frozen.\n\n"
            f"Check, in this order:\n"
            f"1. cron-job.org — is the daily job still enabled and firing?\n"
            f"2. GitHub → Actions → recent runs (red = the script failed)\n"
            f"3. Apify → Billing — monthly $5 allowance may be used up\n\n"
            f"<a href=\"https://github.com/{REPO}/actions\">Actions</a> · "
            f"<a href=\"{DASHBOARD_URL}\">Dashboard</a>")


def main():
    порог = ПОРОГ_ДНЕЙ
    проба = "--проба" in sys.argv or "--dry" in sys.argv
    if "--порог" in sys.argv:
        порог = int(sys.argv[sys.argv.index("--порог") + 1])

    сегодня = сейчас_пхукет().date()
    последняя = последний_снимок()

    if последняя is None:
        print("Снимков нет вообще — сторожить нечего (первый запуск?).")
        return 0

    дней = дней_молчания(последняя, сегодня)
    if дней is None:
        print(f"Непонятная дата снимка: {последняя}")
        return 0

    print(f"Последний снимок: {последняя} · сегодня: {сегодня} · молчание: {дней} дн · порог: {порог}")

    if дней < порог:
        print("✅ Сбор живой — тревожить не о чем.")
        return 0

    сообщение = текст(дней, последняя)
    if проба:
        print("--- БЫЛО БЫ ОТПРАВЛЕНО ---")
        print(сообщение)
        return 0

    tg = конфиг_telegram()
    if not tg:
        print("⚠ Telegram не настроен — алерт не отправлен.")
        return 1
    ok = tg_send(сообщение, tg)
    print("Telegram:", "отправлено." if ok else "НЕ отправлено.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
