#!/usr/bin/env python3
"""Сборщик отзывов LUDUS — Google Maps + TripAdvisor (Apify) + уведомления в Telegram.

ЛОГИКА:
  1. Тянет свежие отзывы с обоих источников.
  2. Единый формат, дедуп по source:review_id, копит в данные/отзывы.json.
  3. Первый запуск = база (без алертов). Дальше = дайджест каждый запуск + 🔴-аларм на <3★.

СЕКРЕТЫ: из apify.config.json / telegram.config.json (локально, в .gitignore)
  ЛИБО из переменных окружения (в GitHub Actions):
  APIFY_TOKEN, GOOGLE_MAPS_URL, TRIPADVISOR_URLS (через запятую),
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.

Отзывы публичные — ПД нет. Хранилище данные/отзывы.json — состояние дедупликации.
Запуск: python3 tools/сбор.py
"""
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import urllib.error

GOOGLE_ACTOR = "compass~google-maps-reviews-scraper"
TRIPADVISOR_ACTOR = "maxcopell~tripadvisor-reviews"

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
ДАННЫЕ = os.path.join(ROOT, "данные")
СКЛАД = os.path.join(ДАННЫЕ, "отзывы.json")


def _найти(имя):
    for путь in (os.path.join(BASE, имя), os.path.join(ROOT, имя), os.path.join(os.getcwd(), имя)):
        if os.path.exists(путь):
            return путь
    return None


def конфиг_apify():
    п = _найти("apify.config.json")
    if п:
        c = json.load(open(п, encoding="utf-8"))
        if (c.get("apify_token") or "").strip() and not c["apify_token"].startswith("ВСТАВЬ"):
            return c
    tok = os.environ.get("APIFY_TOKEN", "").strip()
    if tok:
        urls = [u.strip() for u in re.split(r"[,\n]", os.environ.get("TRIPADVISOR_URLS", "")) if u.strip()]
        return {"apify_token": tok, "google_maps_url": os.environ.get("GOOGLE_MAPS_URL", "").strip(),
                "tripadvisor_urls": urls}
    sys.exit("❌ Нет apify.config.json и нет переменной окружения APIFY_TOKEN.")


def конфиг_telegram():
    п = _найти("telegram.config.json")
    if п:
        c = json.load(open(п, encoding="utf-8"))
        tok = (c.get("bot_token") or "").strip()
        cid = str(c.get("chat_id") or "").strip()
        if tok and cid and not tok.startswith("ВСТАВЬ") and not cid.startswith("ВСТАВЬ"):
            return tok, cid
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    cid = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return (tok, cid) if tok and cid else None


# ---------- Apify ----------
def запуск(actor, вход, token):
    url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
    req = urllib.request.Request(url, data=json.dumps(вход).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")[:200]
    except urllib.error.URLError as e:
        return None, str(e.reason)


def норм_google(it):
    return {"source": "google", "review_id": str(it.get("reviewId") or ""),
            "rating": it.get("stars") if it.get("stars") is not None else it.get("rating"),
            "author": it.get("name") or "—", "date": (it.get("publishedAtDate") or "")[:10],
            "text": it.get("text") or "", "text_en": it.get("textTranslated") or "",
            "lang": it.get("originalLanguage") or "", "title": "",
            "url": it.get("reviewUrl") or "", "owner_replied": bool(it.get("responseFromOwnerText"))}


def норм_tripadvisor(it):
    u = it.get("user") or {}
    author = (u.get("name") or u.get("username")) if isinstance(u, dict) else "—"
    return {"source": "tripadvisor", "review_id": str(it.get("id") or ""),
            "rating": it.get("rating"), "author": author or "—",
            "date": (it.get("publishedDate") or "")[:10], "text": it.get("text") or "",
            "text_en": "", "lang": it.get("lang") or it.get("originalLanguage") or "",
            "title": it.get("title") or "", "url": it.get("url") or "",
            "owner_replied": bool(it.get("ownerResponse"))}


def собрать(c):
    """Возвращает (отзывы, статы_площадок). Статы — официальная оценка/кол-во с ресурса."""
    token = c["apify_token"]
    отзывы = []
    статы = {"google": {}, "tripadvisor": {}}
    g = (c.get("google_maps_url") or "").strip()
    if g and not g.startswith("ВСТАВЬ"):
        st, items = запуск(GOOGLE_ACTOR, {"startUrls": [{"url": g}], "maxReviews": 30,
                                          "reviewsSort": "newest", "language": "en"}, token)
        if st in (200, 201) and isinstance(items, list):
            отзывы += [норм_google(x) for x in items]
            if items:
                статы["google"] = {"rating": items[0].get("totalScore"),
                                    "count": items[0].get("reviewsCount")}
        else:
            print(f"  ⚠ Google: HTTP {st}: {str(items)[:150]}")
    for u in c.get("tripadvisor_urls", []):
        u = (u or "").strip()
        if not u or u.startswith("ВСТАВЬ"):
            continue
        st, items = запуск(TRIPADVISOR_ACTOR, {"startUrls": [{"url": u}], "maxReviewsPerUrl": 30}, token)
        if st in (200, 201) and isinstance(items, list):
            отзывы += [норм_tripadvisor(x) for x in items]
            if items:
                pi = items[0].get("placeInfo") or {}
                статы["tripadvisor"] = {"rating": pi.get("rating"),
                                        "count": pi.get("numberOfReviews") or pi.get("reviewsCount")}
        else:
            print(f"  ⚠ TripAdvisor: HTTP {st}: {str(items)[:150]}")
    return отзывы, статы


def ср_оценка(склад, src):
    vals = [x["rating"] for x in склад.values()
            if x["source"] == src and isinstance(x["rating"], (int, float))]
    return (round(sum(vals) / len(vals), 2) if vals else None), len(vals)


def итог_оценка(src, статы, склад):
    """Официальная оценка с ресурса, иначе — средняя по нашей базе."""
    s = статы.get(src) or {}
    ср, n = ср_оценка(склад, src)
    рейт = s.get("rating") if s.get("rating") is not None else ср
    кол = s.get("count") if s.get("count") is not None else n
    return рейт, кол


# ---------- форматирование ----------
def цвет(r):
    if not isinstance(r, (int, float)):
        return "⚪"
    return "🔴" if r < 3 else ("🟡" if r < 4 else "🟢")


def плюр(n):
    n = int(n or 0)
    if 11 <= n % 100 <= 14:
        return "отзывов"
    d = n % 10
    return "отзыв" if d == 1 else ("отзыва" if 2 <= d <= 4 else "отзывов")


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def имя_ист(src):
    return "Google" if src == "google" else "TripAdvisor"


def дайджест(новые, статы, склад):
    дата = datetime.datetime.now().strftime("%d.%m %H:%M")
    строки = [f"📊 <b>LUDUS · Отзывы</b> — {дата}", "", "<b>Итоговая оценка клуба:</b>"]
    for src in ("google", "tripadvisor"):
        рейт, кол = итог_оценка(src, статы, склад)
        рстр = f"{рейт}★" if рейт is not None else "—"
        строки.append(f"{цвет(рейт)} {имя_ист(src)} — {рстр} · {кол} {плюр(кол)}")

    if not новые:
        строки += ["", "Новых отзывов за период нет."]
        return "\n".join(строки)

    порядок = sorted(новые, key=lambda x: (x["rating"] if isinstance(x["rating"], (int, float)) else 9))
    строки += ["", f"🆕 <b>Новых за период: {len(новые)}</b>"]
    for r in порядок:
        строки.append(f"{цвет(r['rating'])} Новый отзыв на {имя_ист(r['source'])} — ★{r['rating']}")

    # Ссылки в конце, каждая — отдельным блоком, визуально разделены
    строки += ["", "━━━━━━━━━━━━━━━", "<b>🔗 Ссылки на отзывы:</b>"]
    for r in порядок:
        строки.append("")
        строки.append(f"{цвет(r['rating'])} {имя_ист(r['source'])} · ★{r['rating']}")
        if r["url"]:
            строки.append(f"<a href=\"{esc(r['url'])}\">открыть отзыв</a>")
    return "\n".join(строки)


def аларм(r):
    s = f"🔴 <b>НИЗКАЯ ОЦЕНКА ★{r['rating']}</b> — {имя_ист(r['source'])}\n{esc(r['author'])} · {r['date']}"
    if r["title"]:
        s += f"\n«{esc(r['title'])}»"
    txt = (r["text_en"] or r["text"] or "").strip()[:400]
    if txt:
        s += f"\n{esc(txt)}"
    if r["url"]:
        s += f"\n<a href=\"{esc(r['url'])}\">ответить на отзыв</a>"
    if not r["owner_replied"]:
        s += "\n⚠ Ответа владельца пока нет."
    return s


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


# ---------- main ----------
def main():
    os.makedirs(ДАННЫЕ, exist_ok=True)
    склад = json.load(open(СКЛАД, encoding="utf-8")) if os.path.exists(СКЛАД) else {}
    первый_запуск = (len(склад) == 0)

    c = конфиг_apify()
    tg = конфиг_telegram()
    print("Собираю отзывы (Google + TripAdvisor)…")
    все, статы = собрать(c)
    print(f"  получено записей: {len(все)}")

    now = datetime.datetime.now().isoformat(timespec="seconds")
    новые = []
    for r in все:
        if not r["review_id"]:
            continue
        ключ = r["source"] + ":" + r["review_id"]
        if ключ not in склад:
            r["first_seen"] = now
            склад[ключ] = r
            новые.append(r)
    json.dump(склад, open(СКЛАД, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"Telegram: {'подключён' if tg else 'не настроен'} · новых: {len(новые)}")

    if первый_запуск:
        print(f"Первый запуск — занёс {len(новые)} отзывов как базу, алертов нет.")
        if tg:
            g_r, g_n = итог_оценка("google", статы, склад)
            t_r, t_n = итог_оценка("tripadvisor", статы, склад)
            tg_send(f"✅ <b>Мониторинг отзывов LUDUS запущен.</b>\n\n"
                    f"{цвет(g_r)} Google — {g_r}★ · {g_n} {плюр(g_n)}\n"
                    f"{цвет(t_r)} TripAdvisor — {t_r}★ · {t_n} {плюр(t_n)}\n\n"
                    f"Дальше присылаю дайджест 5×/день и 🔴-аларм на отзывы ниже 3★.", tg)
        return

    if tg:
        tg_send(дайджест(новые, статы, склад), tg)
        for r in новые:
            if isinstance(r["rating"], (int, float)) and r["rating"] < 3:
                tg_send(аларм(r), tg)
        print("Telegram: отправлено.")


if __name__ == "__main__":
    main()
