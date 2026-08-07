#!/usr/bin/env python3
"""LUDUS reviews collector — Google Maps + TripAdvisor (Apify) + Telegram notifications.

Запускается извне (cron-job.org → GitHub workflow_dispatch) 5×/день (09/12/15/18/20 Пхукет).
Каждый прогон: тянет свежие отзывы → дедуп (данные/отзывы.json) → дайджест в Telegram +
🔴-аларм на <3★. Плюс:
  • ежедневный снимок оценок площадок → данные/снимки.json (история для трендов);
  • месячный отчёт в начале нового месяца (оценка/динамика/новые отзывы/сравнение с прошлым).

Сообщения бота — на английском. Секреты: *.config.json (локально) или env (Actions):
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
СЛОТЫ = [8]          # ежедневный дайджест в 08:00 по Пхукету
СВЕЖИХ = 15          # глубина выборки за прогон (раз в сутки — с запасом)

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
ДАННЫЕ = os.path.join(ROOT, "данные")
СКЛАД = os.path.join(ДАННЫЕ, "отзывы.json")
СОСТ = os.path.join(ДАННЫЕ, "состояние.json")
СНИМКИ = os.path.join(ДАННЫЕ, "снимки.json")


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
    кандидаты = [x for x in (s.get("count"), n) if isinstance(x, int)]
    кол = max(кандидаты) if кандидаты else None
    return рейт, кол


# ---------- time / state / snapshots ----------
def сейчас_пхукет():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("Asia/Bangkok"))
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=7)


def _load(путь, default):
    if os.path.exists(путь):
        try:
            return json.load(open(путь, encoding="utf-8"))
        except Exception:
            pass
    return default


def _save(путь, d):
    json.dump(d, open(путь, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def пред_месяц(m):
    y, mo = int(m[:4]), int(m[5:7])
    mo -= 1
    if mo == 0:
        mo, y = 12, y - 1
    return f"{y:04d}-{mo:02d}"


def снимок_конца(снимки, месяц):
    ks = sorted(k for k in снимки if k.startswith(месяц))
    return снимки[ks[-1]] if ks else None


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


def monthly_report(месяц, склад, снимки):
    y, mo = int(месяц[:4]), int(месяц[5:7])
    имя_м = datetime.date(y, mo, 1).strftime("%B %Y")
    пред = пред_месяц(месяц)
    имя_пред = datetime.date(int(пред[:4]), int(пред[5:7]), 1).strftime("%b")
    сн_к = снимок_конца(снимки, месяц)
    сн_н = снимок_конца(снимки, пред)

    L = [f"📈 <b>LUDUS · Monthly report — {имя_м}</b>", "", "<b>Overall rating (month end):</b>"]
    for src, rk, ck in (("google", "g_rating", "g_count"), ("tripadvisor", "t_rating", "t_count")):
        r_now = (сн_к or {}).get(rk)
        c_now = (сн_к or {}).get(ck)
        доп = ""
        if сн_н and сн_н.get(rk) is not None and r_now is not None:
            dr = round(r_now - сн_н[rk], 2)
            dc = int((c_now or 0) - (сн_н.get(ck) or 0))
            доп = f"  (Δ vs {имя_пред}: {dr:+g}★, {dc:+d} reviews)"
        rs = f"{r_now}★" if r_now is not None else "—"
        cs = c_now if c_now is not None else "—"
        L.append(f"{dot(r_now)} {src_name(src)} — {rs} · {cs} reviews{доп}")

    def за(m):
        d = {"google": [], "tripadvisor": []}
        for x in склад.values():
            if isinstance(x, dict) and (x.get("date") or "").startswith(m) and x.get("source") in d:
                d[x["source"]].append(x)
        return d
    тек = за(месяц)
    всего = sum(len(v) for v in тек.values())
    L += ["", f"<b>New reviews in {datetime.date(y, mo, 1).strftime('%B')}: {всего}</b>"]
    for src in ("google", "tripadvisor"):
        arr = тек[src]
        if not arr:
            continue
        rr = [a["rating"] for a in arr if isinstance(a["rating"], (int, float))]
        avg = round(sum(rr) / len(rr), 2) if rr else None
        dist = {}
        for a in arr:
            if isinstance(a["rating"], (int, float)):
                k = int(a["rating"])
                dist[k] = dist.get(k, 0) + 1
        ds = " ".join(f"{k}★×{dist[k]}" for k in sorted(dist, reverse=True))
        avgs = f"{avg}★" if avg is not None else "—"
        L.append(f"{dot(avg)} {src_name(src)} — {len(arr)} (avg {avgs})" + (f": {ds}" if ds else ""))

    всего_пр = sum(len(v) for v in за(пред).values())
    d = int(всего - всего_пр)
    L += ["", f"<b>vs previous month:</b> {d:+d} new reviews (was {всего_пр})"]
    return "\n".join(L)


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
    склад = _load(СКЛАД, {})
    первый_запуск = (len(склад) == 0)

    c = конфиг_apify()
    tg = конфиг_telegram()
    now_ph = сейчас_пхукет()
    today = now_ph.strftime("%Y-%m-%d")

    сост = _load(СОСТ, {"date": "", "posted": []})
    if сост.get("date") != today:
        сост = {"date": today, "posted": [], "last_monthly": сост.get("last_monthly")}
    из_за = [s for s in СЛОТЫ if now_ph.hour >= s and s not in сост.get("posted", [])]
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
    _save(СКЛАД, склад)

    # ежедневный снимок оценок площадок (история для месячного отчёта)
    снимки = _load(СНИМКИ, {})
    g_r0, g_c0 = итог_оценка("google", статы, склад)
    t_r0, t_c0 = итог_оценка("tripadvisor", статы, склад)
    снимки[today] = {"g_rating": g_r0, "g_count": g_c0, "t_rating": t_r0, "t_count": t_c0}
    _save(СНИМКИ, снимки)

    print(f"Telegram: {'on' if tg else 'off'} · new: {len(новые)} · digest-time: {'yes' if время_дайджеста else 'no'}")

    if первый_запуск:
        сост["posted"] = [s for s in СЛОТЫ if now_ph.hour >= s]
        сост["last_monthly"] = пред_месяц(now_ph.strftime("%Y-%m"))
        _save(СОСТ, сост)
        if tg:
            tg_send(f"✅ <b>LUDUS review monitor started.</b>\n\n"
                    f"{dot(g_r0)} Google — {g_r0}★ · {g_c0} {plural(g_c0)}\n"
                    f"{dot(t_r0)} TripAdvisor — {t_r0}★ · {t_c0} {plural(t_c0)}\n\n"
                    f"Daily digest at 08:00, 🔴 alarm below 3★, monthly report on the 1st.", tg)
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
        сост["posted"] = sorted(set(сост.get("posted", [])) | set(из_за))

    # месячный отчёт — один раз в начале нового месяца за прошедший месяц
    отчётный = пред_месяц(now_ph.strftime("%Y-%m"))
    if "last_monthly" not in сост or сост.get("last_monthly") is None:
        сост["last_monthly"] = отчётный   # сид: не слать отчёт за уже прошедший месяц
    elif сост["last_monthly"] != отчётный:
        есть = снимок_конца(снимки, отчётный) or any(
            isinstance(x, dict) and (x.get("date") or "").startswith(отчётный) for x in склад.values())
        if tg and есть:
            tg_send(monthly_report(отчётный, склад, снимки), tg)
        сост["last_monthly"] = отчётный

    _save(СОСТ, сост)
    print("Telegram: sent." if (надо_дайджест and tg) else "Quiet (not digest-time, no new).")


if __name__ == "__main__":
    main()
