#!/usr/bin/env python3
"""LUDUS reviews collector — Google Maps + TripAdvisor (Apify) + Telegram notifications.

Запускается внешним планировщиком cron-job.org 5 раз в день (09/12/15/18/20 по Пхукету),
который дёргает GitHub Actions (workflow_dispatch). GitHub-расписание НЕ используется —
так экономим Apify (5 прогонов в день вместо 48).

Каждый прогон: тянет свежие отзывы → дедуп по source:review_id (данные/отзывы.json) →
шлёт дайджест в Telegram (итоговая оценка + новые) и 🔴-аларм на <3★. Логика слотов
(данные/состояние.json) не даёт отправить один и тот же дайджест дважды.

Сообщения бота — на английском. Секреты: *.config.json (локально) или env-переменные (Actions):
APIFY_TOKEN, GOOGLE_MAPS_URL, TRIPADVISOR_URLS, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.
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
СЛОТЫ = [9, 12, 15, 18, 20]     # целевые времена дайджеста (по Пхукету)
СВЕЖИХ = 10                     # сколько последних отзывов тянуть за прогон

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
ДАННЫЕ = os.path.join(ROOT, "данные")
СКЛАД = os.path.join(ДАННЫЕ, "отзывы.json")
СОСТ = os.path.join(ДАННЫЕ, "состояние.json")


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
    token = c["apify_token"]
    отзывы = []
    статы = {"google": {}, "tripadvisor": {}}
    g = (c.get("google_maps_url") or "").strip()
    if g and not g.startswith("ВСТАВЬ"):
        st, items = запуск(GOOGLE_ACTOR, {"startUrls": [{"url": g}], "maxReviews": СВЕЖИХ,
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
        st, items = запуск(TRIPADVISOR_ACTOR, {"startUrls": [{"url": u}], "maxReviewsPerUrl": СВЕЖИХ}, token)
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
            if isinstance(x, dict) and x.get("source") == src and isinstance(x.get("rating"), (int, float))]
    return (round(sum(vals) / len(vals), 2) if vals else None), len(vals)


def итог_оценка(src, статы, склад):
    s = статы.get(src) or {}
    ср, n = ср_оценка(склад, src)
    рейт = s.get("rating") if s.get("rating") is not None else ср
    кол = s.get("count") if s.get("count") is not None else n
    return рейт, кол


# ---------- time / schedule ----------
def сейчас_пхукет():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("Asia/Bangkok"))
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=7)


def загрузить_состояние():
    if os.path.exists(СОСТ):
        try:
            return json.load(open(СОСТ, encoding="utf-8"))
        except Exception:
            pass
    return {"date": "", "posted": []}


def сохранить_состояние(s):
    json.dump(s, open(СОСТ, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


# ---------- formatting (English) ----------
def dot(r):
    if not isinstance(r, (int, float)):
        return "⚪"
    return "🔴" if r < 3 else ("🟡" if r < 4 else "🟢")


def plural(n):
    return "review" if int(n or 0) == 1 else "reviews"


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def src_name(src):
    return "Google" if src == "google" else "TripAdvisor"


def digest(new, статы, склад):
    ts = сейчас_пхукет().strftime("%d.%m %H:%M")
    lines = [f"📊 <b>LUDUS · Reviews</b> — {ts}", "", "<b>Overall rating:</b>"]
    for src in ("google", "tripadvisor"):
        rt, cnt = итог_оценка(src, статы, склад)
        rs = f"{rt}★" if rt is not None else "—"
        lines.append(f"{dot(rt)} {src_name(src)} — {rs} · {cnt} {plural(cnt)}")
    if not new:
        lines += ["", "No new reviews in this period."]
        return "\n".join(lines)
    order = sorted(new, key=lambda x: (x["rating"] if isinstance(x["rating"], (int, float)) else 9))
    lines += ["", f"🆕 <b>New this period: {len(new)}</b>"]
    for r in order:
        lines.append(f"{dot(r['rating'])} New review on {src_name(r['source'])} — ★{r['rating']}")
    lines += ["", "━━━━━━━━━━━━━━━", "<b>🔗 Review links:</b>"]
    for r in order:
        lines.append("")
        lines.append(f"{dot(r['rating'])} {src_name(r['source'])} · ★{r['rating']}")
        if r["url"]:
            lines.append(f"<a href=\"{esc(r['url'])}\">open review</a>")
    return "\n".join(lines)


def alarm(r):
    s = f"🔴 <b>LOW RATING ★{r['rating']}</b> — {src_name(r['source'])}\n{esc(r['author'])} · {r['date']}"
    if r["title"]:
        s += f"\n«{esc(r['title'])}»"
    txt = (r["text_en"] or r["text"] or "").strip()[:400]
    if txt:
        s += f"\n{esc(txt)}"
    if r["url"]:
        s += f"\n<a href=\"{esc(r['url'])}\">reply to review</a>"
    if not r["owner_replied"]:
        s += "\n⚠ No owner reply yet."
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
    now_ph = сейчас_пхукет()

    сост = загрузить_состояние()
    today = now_ph.strftime("%Y-%m-%d")
    if сост.get("date") != today:
        сост = {"date": today, "posted": []}
    из_за = [s for s in СЛОТЫ if now_ph.hour >= s and s not in сост["posted"]]
    время_дайджеста = len(из_за) > 0

    print("Collecting reviews (Google + TripAdvisor)…")
    все, статы = собрать(c)
    print(f"  fetched: {len(все)}")

    now_iso = now_ph.isoformat(timespec="seconds")
    новые = []
    for r in все:
        if not r["review_id"]:
            continue
        ключ = r["source"] + ":" + r["review_id"]
        if ключ not in склад:
            r["first_seen"] = now_iso
            склад[ключ] = r
            новые.append(r)
    json.dump(склад, open(СКЛАД, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"Telegram: {'on' if tg else 'off'} · new: {len(новые)} · digest-time: {'yes' if время_дайджеста else 'no'}")

    if первый_запуск:
        сост["posted"] = [s for s in СЛОТЫ if now_ph.hour >= s]
        сохранить_состояние(сост)
        if tg:
            g_r, g_n = итог_оценка("google", статы, склад)
            t_r, t_n = итог_оценка("tripadvisor", статы, склад)
            tg_send(f"✅ <b>LUDUS review monitor started.</b>\n\n"
                    f"{dot(g_r)} Google — {g_r}★ · {g_n} {plural(g_n)}\n"
                    f"{dot(t_r)} TripAdvisor — {t_r}★ · {t_n} {plural(t_n)}\n\n"
                    f"Digest at 09/12/15/18/20, 🔴 alarm on reviews below 3★.", tg)
        print("First run — baseline stored.")
        return

    надо_дайджест = время_дайджеста or bool(новые)
    if tg and надо_дайджест:
        tg_send(digest(новые, статы, склад), tg)
    if tg:
        for r in новые:
            if isinstance(r["rating"], (int, float)) and r["rating"] < 3:
                tg_send(alarm(r), tg)

    if время_дайджеста:
        сост["posted"] = sorted(set(сост["posted"]) | set(из_за))
    сохранить_состояние(сост)

    print("Telegram: sent." if (надо_дайджест and tg) else "Quiet (not digest-time, no new).")


if __name__ == "__main__":
    main()
