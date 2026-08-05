#!/usr/bin/env python3
"""Проба Apify — тянем последние отзывы LUDUS с Google Maps и TripAdvisor.

ЗАЧЕМ: убедиться, что через Apify реально достаём свежие отзывы, и увидеть,
       в каком формате они приходят (по этому формату построю парсер и дайджест).
ЧТО ДЕЛАЕТ: запускает два «актёра» Apify (Google-отзывы и TripAdvisor-отзывы)
       синхронно и печатает, что вернулось: кол-во, ключи первой записи, примеры.
Отзывы ПУБЛИЧНЫЕ — печатаем как есть, персональных данных тут нет.

Токен и URL — из apify.config.json. Только стандартная библиотека Python 3.
Запуск:  python3 tools/отзывы_проба.py   (может думать до минуты — идёт скрапинг)
"""
import json
import os
import sys
import urllib.request
import urllib.error

GOOGLE_ACTOR = "compass~google-maps-reviews-scraper"
TRIPADVISOR_ACTOR = "maxcopell~tripadvisor-reviews"

BASE = os.path.dirname(os.path.abspath(__file__))
КАНДИДАТЫ = [
    os.path.join(BASE, "apify.config.json"),
    os.path.join(BASE, "..", "apify.config.json"),
    os.path.join(os.getcwd(), "apify.config.json"),
]


def конфиг():
    for путь in КАНДИДАТЫ:
        if os.path.exists(путь):
            c = json.load(open(путь, encoding="utf-8"))
            tok = (c.get("apify_token") or "").strip()
            if not tok or tok.startswith("ВСТАВЬ"):
                sys.exit(f"❌ В {путь} не вписан apify_token.")
            return c
    sys.exit("❌ Не найден apify.config.json.")


def запуск(actor, вход, token):
    """Синхронный запуск актёра, сразу получаем элементы датасета."""
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
    req = urllib.request.Request(
        url, data=json.dumps(вход).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:400]
    except urllib.error.URLError as e:
        return None, str(e.reason)


def показать(имя, items):
    if not isinstance(items, list):
        print(f"  {имя}: ответ не список → {str(items)[:300]}")
        return
    print(f"  {имя}: записей = {len(items)}")
    if items:
        print(f"    ключи первой записи: {sorted(items[0].keys())}")
        for it in items[:2]:
            print("    · " + json.dumps(it, ensure_ascii=False)[:260])


def main():
    c = конфиг()
    token = c["apify_token"]

    g_url = (c.get("google_maps_url") or "").strip()
    if g_url and not g_url.startswith("ВСТАВЬ"):
        print("Google Maps — запрашиваю…")
        st, items = запуск(GOOGLE_ACTOR,
                           {"startUrls": [{"url": g_url}], "maxReviews": 10,
                            "reviewsSort": "newest", "language": "en"}, token)
        print(f"  HTTP {st}")
        показать("Google", items)
    else:
        print("Google Maps — URL не задан в конфиге, пропуск.")

    for i, u in enumerate(c.get("tripadvisor_urls", []), 1):
        u = (u or "").strip()
        if not u or u.startswith("ВСТАВЬ"):
            continue
        print(f"\nTripAdvisor листинг {i} — запрашиваю…")
        st, items = запуск(TRIPADVISOR_ACTOR,
                           {"startUrls": [{"url": u}], "maxReviewsPerUrl": 10}, token)
        print(f"  HTTP {st}")
        показать(f"TripAdvisor {i}", items)

    print("\nℹ️  По ключам/примерам выше построю парсер (оценка, автор, дата, текст, ссылка) и дайджест.")


if __name__ == "__main__":
    main()
