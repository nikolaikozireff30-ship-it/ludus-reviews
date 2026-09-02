#!/usr/bin/env python3
"""LUDUS reviews — HTML analytics dashboard generator.

Читает данные/снимки.json (дневные снимки оценок) и данные/отзывы.json,
считает помесячную аналитику и пишет docs/index.html (Chart.js с CDN, стиль LUDUS, англ).

Месяцы: от START_MONTH (старт мониторинга) до «текущий + 5» по Пхукету — будущие месяцы
идут как пустые вкладки и заполняются, когда наступают. Даты/месяц считаются по Asia/Bangkok.
"""
import datetime
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
ДАННЫЕ = os.path.join(ROOT, "данные")
DOCS = os.path.join(ROOT, "docs")

START_MONTH = "2026-08"   # с этого месяца начинаем показывать (полноценный мониторинг)
FUTURE = 5                # сколько месяцев вперёд добавлять заранее


def сейчас_пхукет():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("Asia/Bangkok"))
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=7)


def load(p, d):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return d


def month_add(m, k):
    idx = int(m[:4]) * 12 + (int(m[5:7]) - 1) + k
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def month_label(m):
    return datetime.date(int(m[:4]), int(m[5:7]), 1).strftime("%b %Y")


МЕСТА_ФАЙЛ = os.path.join(BASE, "точки.json")


def места_карт():
    """Отслеживаемые точки из tools/точки.json; фолбэк — главные карточки."""
    t = load(МЕСТА_ФАЙЛ, {})
    if t.get("google") or t.get("tripadvisor"):
        return {"google": t.get("google") or [], "tripadvisor": t.get("tripadvisor") or []}
    return {"google": [{"key": "complex", "label": "Sports Complex"}],
            "tripadvisor": [{"key": "ta", "label": "TripAdvisor"}]}


def из_снимка(сн, src, key):
    """Оценка/кол-во точки из снимка (новый формат places или легаси-поля)."""
    if not сн:
        return None, None
    p = ((сн.get("places") or {}).get(src) or {}).get(key)
    if p:
        return p.get("r"), p.get("c")
    if src == "google" and key == "complex":
        return сн.get("g_rating"), сн.get("g_count")
    if src == "tripadvisor" and key == "ta":
        return сн.get("t_rating"), сн.get("t_count")
    return None, None


def build_data():
    снимки = load(os.path.join(ДАННЫЕ, "снимки.json"), {})
    склад = load(os.path.join(ДАННЫЕ, "отзывы.json"), {})
    reviews = [v for v in склад.values() if isinstance(v, dict)]
    места = места_карт()
    метки = {(src, pl["key"]): pl["label"] for src in ("google", "tripadvisor") for pl in места[src]}

    def метка(r):
        key = r.get("place") or ("complex" if r.get("source") == "google" else "ta")
        return метки.get((r.get("source"), key), key)

    now = сейчас_пхукет()
    current = now.strftime("%Y-%m")
    horizon = month_add(max(current, START_MONTH), FUTURE)
    months_keys = []
    cur = START_MONTH
    while cur <= horizon:
        months_keys.append(cur)
        cur = month_add(cur, 1)

    def avg(vals):
        vals = [v for v in vals if isinstance(v, (int, float))]
        return round(sum(vals) / len(vals), 2) if vals else None

    out_months = []
    prev_snap = None
    for m in months_keys:
        snap_dates = sorted(k for k in снимки if k.startswith(m))
        daily = [{"date": d, "g": снимки[d].get("g_rating"), "t": снимки[d].get("t_rating")} for d in snap_dates]
        # серии по точкам: [{src,key,label,data:[{date,r}...]}]
        series = []
        for src in ("google", "tripadvisor"):
            for pl in места[src]:
                pts = []
                for d in snap_dates:
                    r, _ = из_снимка(снимки[d], src, pl["key"])
                    pts.append({"date": d, "r": r})
                if any(p["r"] is not None for p in pts):
                    series.append({"src": src, "key": pl["key"], "label": pl["label"], "data": pts})
        end_snap = снимки[snap_dates[-1]] if snap_dates else None

        mrev = [r for r in reviews if (r.get("date") or "").startswith(m)]
        g_rev = [r for r in mrev if r["source"] == "google"]
        t_rev = [r for r in mrev if r["source"] == "tripadvisor"]
        dist = {}
        for r in mrev:
            if isinstance(r.get("rating"), (int, float)):
                k = int(r["rating"])
                dist[k] = dist.get(k, 0) + 1

        def ключ_места(r):
            return r.get("place") or ("complex" if r.get("source") == "google" else "ta")

        нег = [r for r in mrev if isinstance(r.get("rating"), (int, float)) and r["rating"] < 3]
        отвечено = [r for r in mrev if r.get("owner_replied")]
        replied_pct = round(100 * len(отвечено) / len(mrev)) if mrev else None
        unneg = sum(1 for r in нег if not r.get("owner_replied"))

        # сравнительная таблица точек за месяц
        place_stats = []
        for src in ("google", "tripadvisor"):
            for pl in места[src]:
                конец = снимки[snap_dates[-1]] if snap_dates else None
                p_r, p_c = из_снимка(конец, src, pl["key"])
                pr = [r for r in mrev if r["source"] == src and ключ_места(r) == pl["key"]]
                pr_rated = [r["rating"] for r in pr if isinstance(r.get("rating"), (int, float))]
                p_avg = round(sum(pr_rated) / len(pr_rated), 2) if pr_rated else None
                p_neg = sum(1 for v in pr_rated if v < 3)
                p_rep = round(100 * sum(1 for r in pr if r.get("owner_replied")) / len(pr)) if pr else None
                place_stats.append({"src": src, "key": pl["key"], "label": pl["label"],
                                    "rating": p_r, "count": p_c, "new": len(pr), "avg": p_avg,
                                    "neg": p_neg, "replied_pct": p_rep})

        d_g = d_t = None
        if end_snap and prev_snap:
            if end_snap.get("g_rating") is not None and prev_snap.get("g_rating") is not None:
                d_g = round(end_snap["g_rating"] - prev_snap["g_rating"], 2)
            if end_snap.get("t_rating") is not None and prev_snap.get("t_rating") is not None:
                d_t = round(end_snap["t_rating"] - prev_snap["t_rating"], 2)

        out_months.append({
            "key": m, "label": month_label(m), "daily": daily, "series": series,
            "new_total": len(mrev), "new_google": len(g_rev), "new_tripadvisor": len(t_rev),
            "avg_month": avg([r.get("rating") for r in mrev]),
            "avg_google": avg([r.get("rating") for r in g_rev]),
            "avg_tripadvisor": avg([r.get("rating") for r in t_rev]),
            "dist": dist, "neg": len(нег), "replied_pct": replied_pct, "unneg": unneg,
            "place_stats": place_stats,
            "end_g": (end_snap or {}).get("g_rating"), "end_gc": (end_snap or {}).get("g_count"),
            "end_t": (end_snap or {}).get("t_rating"), "end_tc": (end_snap or {}).get("t_count"),
            "d_g": d_g, "d_t": d_t,
            "reviews": sorted([{
                "source": r["source"], "rating": r.get("rating"), "date": r.get("date"),
                "author": r.get("author"), "url": r.get("url"), "place": метка(r),
                "replied": bool(r.get("owner_replied")),
                "text": (r.get("text_en") or r.get("text") or "").strip()[:280],
            } for r in mrev], key=lambda x: x["date"] or "", reverse=True),
        })
        if end_snap:
            prev_snap = end_snap

    # отзывы, оставленные ДО старта мониторинга: они найдены при первой загрузке
    # и не относятся ни к одному отслеживаемому месяцу — показываем их отдельно,
    # чтобы Overview не выглядел так, будто это вся база
    до_старта = [r for r in reviews if (r.get("date") or "") and r["date"][:7] < START_MONTH]
    оц_до = [r["rating"] for r in до_старта if isinstance(r.get("rating"), (int, float))]
    pre_start = {
        "count": len(до_старта),
        "avg": round(sum(оц_до) / len(оц_до), 2) if оц_до else None,
        "from": min((r["date"] for r in до_старта), default=None),
        "to": max((r["date"] for r in до_старта), default=None),
    }

    last = снимки[sorted(снимки)[-1]] if снимки else {}
    overall = []
    for src in ("google", "tripadvisor"):
        for pl in места[src]:
            r, cnt = из_снимка(last, src, pl["key"])
            overall.append({"src": src, "key": pl["key"], "label": pl["label"], "rating": r, "count": cnt})

    return {"updated": now.strftime("%Y-%m-%d %H:%M"), "current_month": current,
            "start_month": START_MONTH, "start_label": month_label(START_MONTH),
            "pre_start": pre_start,
            "overall": overall, "months": out_months}


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>LUDUS · Reviews Analytics</title>
<link href="https://fonts.googleapis.com/css2?family=Tektur:wght@400;500;600;700&family=Montserrat:wght@400;500;600;700&display=swap" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
:root{--red:#FF0005;--silver:#A5A5A5;--bg:#000;--card:#111;--line:#232323;--head:'Tektur',sans-serif;--body:'Montserrat',Arial,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:#fff;font-family:var(--body)}
.wrap{max-width:1080px;margin:0 auto;padding:26px 20px 60px}
.top{display:flex;align-items:center;gap:12px;margin-bottom:4px}
.bolt{width:26px;height:26px}
.logo{font-family:var(--head);font-weight:700;letter-spacing:3px;font-size:26px}
.sub{color:var(--silver);font-size:12px;margin-bottom:22px}
.tabs{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:22px}
.tabs button{background:#0c0c0c;border:1px solid #2a2a2a;color:#bbb;border-radius:9px;padding:8px 14px;cursor:pointer;font-family:var(--head);letter-spacing:1px;font-size:13px;text-transform:uppercase}
.tabs button.on{background:var(--red);color:#fff;border-color:var(--red)}
.tabs button.future{opacity:.5}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:14px;margin-bottom:22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px}
.card .k{font-family:var(--head);text-transform:uppercase;letter-spacing:1.5px;font-size:11px;color:var(--silver)}
.card .v{font-family:var(--head);font-weight:700;font-size:32px;line-height:1;margin-top:6px}
.card .v .s{color:var(--silver);font-size:16px;font-weight:500;margin-left:6px}
.g{color:#2ec16b}.y{color:#f4c000}.r{color:var(--red)}
h2{font-family:var(--head);text-transform:uppercase;letter-spacing:2px;font-size:15px;margin:26px 0 12px;padding-bottom:8px;border-bottom:2px solid var(--red);display:inline-block}
.chartbox{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:22px;position:relative;height:320px}
.chartbox.slim{height:240px}
.nr{font-size:11px;color:#f4c000;font-family:var(--head);letter-spacing:.5px}
.nr.bad{color:var(--red)}
.chartbox canvas{width:100%!important;height:100%!important;display:block}
.empty{color:var(--silver);font-size:13px;text-align:center;padding:38px 10px}
.tscroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:14px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.stat .k{font-family:var(--head);text-transform:uppercase;letter-spacing:1px;font-size:10px;color:var(--silver)}
.stat .v{font-family:var(--head);font-weight:700;font-size:26px;margin-top:4px}
.dist{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0 20px}
.dist span{background:#0c0c0c;border:1px solid #2a2a2a;border-radius:8px;padding:5px 10px;font-family:var(--head);font-size:13px}
table{width:100%;border-collapse:collapse;margin-top:6px}
th{font-family:var(--head);text-transform:uppercase;letter-spacing:1px;font-size:10px;color:var(--silver);text-align:left;padding:8px 8px;border-bottom:1px solid var(--line)}
td{padding:9px 8px;border-bottom:1px solid var(--line);font-size:13px;vertical-align:top}
td.num{text-align:right;font-family:var(--head)}
.rev{border-bottom:1px solid var(--line);padding:11px 0}
.rev .h{font-family:var(--head);font-size:13px}
.rev .t{color:#cfcfcf;font-size:13px;margin-top:3px}
.rev a{color:var(--red);text-decoration:none;font-size:12px}
.hide{display:none}.mut{color:var(--silver);font-size:12px}
.asof{color:var(--silver);font-size:12px;margin:-14px 0 20px;line-height:1.5}
@media(max-width:720px){
  .wrap{padding:18px 14px 50px}
  .logo{font-size:22px;letter-spacing:2px}
  .cards{grid-template-columns:1fr 1fr;gap:10px}
  .stats{grid-template-columns:1fr 1fr;gap:10px}
  .card .v{font-size:26px}
  .stat .v{font-size:22px}
  .chartbox{height:250px;padding:12px}
  .tabs{gap:6px}
  .tabs button{padding:7px 11px;font-size:12px}
  table{min-width:520px}
  h2{font-size:14px}
}
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <svg class="bolt" viewBox="0 0 24 24"><polygon points="13,1 3,14 10,14 8,23 21,9 13,9" fill="#FF0005"/></svg>
    <div class="logo">LUDUS · REVIEWS</div>
  </div>
  <div class="sub" id="updated"></div>
  <div class="tabs" id="tabs"></div>
  <div id="views"></div>
</div>
<script>
const DATA = __DATA__;
const clr = r => (typeof r!=="number") ? "" : (r<3?"r":(r<4?"y":"g"));
const fx = (r,d=1) => (typeof r==="number") ? r.toFixed(d) : "—";
const hasData = m => m.new_total>0 || (m.daily && m.daily.length>0);
const charts = {};

function overallCards(o){
  return `<div class="cards">${o.map(c=>{
    const name=c.src==="google"?("Google · "+c.label):"TripAdvisor";
    return `<div class="card"><div class="k">${name}</div>
      <div class="v ${clr(c.rating)}">${fx(c.rating,1)}★ <span class="s">${c.count??"—"} reviews</span></div></div>`;
  }).join("")}</div>`;
}

// Карточки на вкладке месяца: рейтинг и число отзывов площадки НА КОНЕЦ ЭТОГО МЕСЯЦА,
// а не текущие. Иначе август и сентябрь показывали одни и те же цифры.
function monthCards(m){
  const it = (m.place_stats||[]).filter(c=>c.rating!=null||c.count!=null);
  if(!it.length) return overallCards(DATA.overall);
  const now = m.key===DATA.current_month;
  return `<div class="cards">${it.map(c=>{
    const name=c.src==="google"?("Google · "+c.label):"TripAdvisor";
    return `<div class="card"><div class="k">${name}</div>
      <div class="v ${clr(c.rating)}">${fx(c.rating,1)}★ <span class="s">${c.count??"—"} reviews</span></div></div>`;
  }).join("")}</div>
  <div class="asof">${now?"Live totals — as of today":("Totals as of the end of "+m.label)}</div>`;
}

function overviewView(){
  const dm = DATA.months.filter(hasData);
  const all = dm.flatMap(m=>m.reviews||[]);
  const rated = all.filter(r=>typeof r.rating==="number");
  const totNeg = rated.filter(r=>r.rating<3).length;
  const totAvg = rated.length?(rated.reduce((s,r)=>s+r.rating,0)/rated.length):null;
  const totRep = all.length?Math.round(100*all.filter(r=>r.replied).length/all.length):null;
  const totUnneg = rated.filter(r=>r.rating<3&&!r.replied).length;
  const repCls = totRep==null?"":(totRep>=80?"g":(totRep>=50?"y":"r"));
  let rows = dm.slice().reverse().map(m=>{
    const dg=(typeof m.d_g==="number")?(m.d_g>=0?"+":"")+m.d_g:"—";
    const dt=(typeof m.d_t==="number")?(m.d_t>=0?"+":"")+m.d_t:"—";
    return `<tr><td>${m.label}</td>
      <td class="num">${m.new_total}<div class="mut">${m.new_google} G · ${m.new_tripadvisor} T</div></td>
      <td class="num ${clr(m.avg_month)}">${fx(m.avg_month,2)}</td>
      <td class="num ${m.neg?"r":""}">${m.neg||"·"}</td>
      <td class="num">${m.replied_pct==null?"·":m.replied_pct+"%"}</td>
      <td class="num ${clr(m.end_g)}">${fx(m.end_g,1)}★<div class="mut">Δ ${dg}</div></td>
      <td class="num ${clr(m.end_t)}">${fx(m.end_t,1)}★<div class="mut">Δ ${dt}</div></td></tr>`;}).join("");
  const pre = DATA.pre_start||{count:0};
  const preNote = pre.count ? `<div class="asof">Plus ${pre.count} older reviews already on the pages
    when monitoring started (${pre.from} – ${pre.to}${pre.avg?`, avg ${pre.avg.toFixed(2)}★`:""}).
    They are not counted in the monthly figures above.</div>` : "";
  return `${overallCards(DATA.overall)}
    <div class="asof">Live totals — as of today</div>
    <h2>New reviews by month</h2>
    <div class="chartbox">${dm.length?'<canvas id="ovBars"></canvas>':'<div class="empty">Collecting data — the chart appears as months are recorded.</div>'}</div>
    <div class="stats">
      <div class="stat"><div class="k">New reviews since ${DATA.start_label||""}</div><div class="v">${all.length}</div></div>
      <div class="stat"><div class="k">Avg of new</div><div class="v ${clr(totAvg)}">${fx(totAvg,2)}</div></div>
      <div class="stat"><div class="k">Negative (&lt;3★)</div><div class="v ${totNeg?"r":"g"}">${totNeg}</div></div>
      <div class="stat"><div class="k">Answered</div><div class="v ${repCls}">${totRep==null?"—":totRep+"%"}</div></div>
      <div class="stat"><div class="k">No-reply negative</div><div class="v ${totUnneg?"r":"g"}">${totUnneg}</div></div>
    </div>
    ${preNote}
    <h2>Rating trend by month</h2>
    <div class="chartbox slim">${dm.length?'<canvas id="ovTrend"></canvas>':'<div class="empty">Appears as months are recorded.</div>'}</div>
    <h2>Months</h2>
    <div class="tscroll"><table><tr><th>Month</th><th style="text-align:right">New reviews</th>
      <th style="text-align:right">Avg new</th><th style="text-align:right">Negative</th>
      <th style="text-align:right">Answered</th>
      <th style="text-align:right">Google (end)</th><th style="text-align:right">TripAdvisor (end)</th></tr>
      ${rows || '<tr><td colspan="7" class="mut">No data yet.</td></tr>'}</table></div>`;
}

function monthView(m){
  const dist = Object.keys(m.dist).sort((a,b)=>b-a).map(k=>`<span>${k}★ × ${m.dist[k]}</span>`).join("");
  const revs = m.reviews.map(r=>`<div class="rev">
      <div class="h">${clr(r.rating)?('<span class="'+clr(r.rating)+'">●</span> '):''}★${r.rating} · ${r.source==="google"?("Google · "+(r.place||"")):"TripAdvisor"} · ${r.author||"—"} · <span class="mut">${r.date||""}</span>${r.replied?"":` <span class="nr${(typeof r.rating==="number"&&r.rating<3)?" bad":""}">⚠ no reply</span>`}</div>
      ${r.text?`<div class="t">${escapeHtml(r.text)}</div>`:""}
      ${r.url?`<a href="${r.url}" target="_blank">open review ↗</a>`:""}</div>`).join("")
    || '<div class="mut">No reviews recorded for this month yet.</div>';
  const kpiRep = m.replied_pct==null ? "—" : m.replied_pct+"%";
  const repCls = m.replied_pct==null ? "" : (m.replied_pct>=80?"g":(m.replied_pct>=50?"y":"r"));
  const table = (m.place_stats&&m.place_stats.length) ? `
    <h2>Places · ${m.label}</h2>
    <div class="tscroll"><table><tr><th>Place</th><th style="text-align:right">Rating</th>
      <th style="text-align:right">Total</th><th style="text-align:right">New</th>
      <th style="text-align:right">Avg new</th><th style="text-align:right">Negative</th>
      <th style="text-align:right">Answered</th></tr>
      ${m.place_stats.map(p=>`<tr>
        <td>${p.src==="google"?("Google · "+p.label):"TripAdvisor"}</td>
        <td class="num ${clr(p.rating)}">${fx(p.rating,1)}★</td>
        <td class="num">${p.count??"—"}</td><td class="num">${p.new||"·"}</td>
        <td class="num ${p.new?clr(p.avg):""}">${p.new?fx(p.avg,2):"·"}</td>
        <td class="num ${p.neg?"r":""}">${p.neg||"·"}</td>
        <td class="num">${p.replied_pct==null?"·":p.replied_pct+"%"}</td></tr>`).join("")}
    </table></div>` : "";
  return `${monthCards(m)}
    <h2>${m.label} · new reviews by day</h2>
    <div class="chartbox">${m.new_total?`<canvas id="bars_${m.key}"></canvas>`
      :`<div class="empty">No reviews received in ${m.label} yet.</div>`}</div>
    <div class="stats">
      <div class="stat"><div class="k">New reviews</div><div class="v">${m.new_total}</div></div>
      <div class="stat"><div class="k">Avg of new</div><div class="v ${clr(m.avg_month)}">${fx(m.avg_month,2)}</div></div>
      <div class="stat"><div class="k">Negative (&lt;3★)</div><div class="v ${m.neg?"r":"g"}">${m.neg}</div></div>
      <div class="stat"><div class="k">Answered</div><div class="v ${repCls}">${kpiRep}</div></div>
      <div class="stat"><div class="k">No-reply negative</div><div class="v ${m.unneg?"r":"g"}">${m.unneg}</div></div>
    </div>
    <div class="dist">${dist||'<span class="mut">no distribution yet</span>'}</div>
    <h2>${m.label} · rating trend</h2>
    <div class="chartbox slim">${(m.series&&m.series.length)?`<canvas id="ch_${m.key}"></canvas>`
      :`<div class="empty">Daily rating data is collected once a day.<br>The trend appears as snapshots accumulate.</div>`}</div>
    ${table}
    <h2>Reviews received</h2>${revs}`;
}

function escapeHtml(s){return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}

function chartOpts(vals){
  const nums=vals.filter(v=>typeof v==="number");
  const mn=nums.length?Math.max(0,Math.min(...nums)-0.2):0;
  return {responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
    plugins:{legend:{labels:{color:"#cfcfcf",font:{family:"Montserrat"}}},
      tooltip:{callbacks:{label:c=>c.dataset.label+": "+(c.parsed.y==null?"—":c.parsed.y.toFixed(2)+"★")}}},
    scales:{y:{suggestedMin:mn,max:5,ticks:{color:"#8f8f8f"},grid:{color:"#1c1c1c"}},
      x:{ticks:{color:"#8f8f8f",maxRotation:0,autoSkip:true},grid:{color:"#141414"}}}};
}
const PCOLOR={"google:complex":"#FF0005","google:gym":"#3987e5","google:massage":"#d95926",
  "google:shop":"#199e70","tripadvisor:ta":"#c98500"};
const PFALLBACK=["#d55181","#3987e5","#199e70","#c98500"];
function drawBars(m){
  const ctx=document.getElementById("bars_"+m.key); if(!ctx)return;
  if(charts["b"+m.key])charts["b"+m.key].destroy();
  const [yy,mo]=m.key.split("-").map(Number);
  const nDays=new Date(yy,mo,0).getDate();
  const days=Array.from({length:nDays},(_,i)=>String(i+1).padStart(2,"0"));
  const g=Array(nDays).fill(0),ye=Array(nDays).fill(0),rr=Array(nDays).fill(0);
  (m.reviews||[]).forEach(rv=>{
    if(typeof rv.rating!=="number"||!rv.date||!rv.date.startsWith(m.key))return;
    const d=parseInt(rv.date.slice(8),10)-1; if(d<0||d>=nDays)return;
    if(rv.rating<3)rr[d]++; else if(rv.rating<4)ye[d]++; else g[d]++;});
  const bar=(label,data,col)=>({label,data,backgroundColor:col,borderColor:"#111",
    borderWidth:2,borderSkipped:false,borderRadius:3,maxBarThickness:26});
  charts["b"+m.key]=new Chart(ctx,{type:"bar",
    data:{labels:days,datasets:[bar("4–5★",g,"#2ec16b"),bar("3★",ye,"#f4c000"),bar("1–2★",rr,"#FF0005")]},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
      plugins:{legend:{labels:{color:"#cfcfcf",font:{family:"Montserrat"}}},
        tooltip:{filter:c=>c.parsed.y>0}},
      scales:{x:{stacked:true,ticks:{color:"#8f8f8f",maxRotation:0,autoSkip:true},grid:{display:false}},
        y:{stacked:true,ticks:{color:"#8f8f8f",stepSize:1,precision:0},grid:{color:"#1c1c1c"}}}}});
}
function drawMonthChart(m){
  const ctx=document.getElementById("ch_"+m.key); if(!ctx)return;
  if(charts[m.key])charts[m.key].destroy();
  const series=m.series||[];
  const days=[...new Set(series.flatMap(s=>s.data.filter(p=>p.r!=null).map(p=>p.date.slice(8))))].sort();
  const lineSets=series.map((s,i)=>{
    const col=PCOLOR[s.src+":"+s.key]||PFALLBACK[i%PFALLBACK.length];
    const byDay=Object.fromEntries(s.data.map(p=>[p.date.slice(8),p.r]));
    return {label:s.label,data:days.map(d=>byDay[d]??null),borderColor:col,backgroundColor:col+"22",
      tension:.3,spanGaps:true,pointRadius:2,borderWidth:2};
  });
  charts[m.key]=new Chart(ctx,{type:"line",data:{labels:days,datasets:lineSets},
    options:chartOpts(series.flatMap(s=>s.data.map(p=>p.r)))});
}
function drawOverview(){
  const ms=DATA.months.filter(hasData);
  const b=document.getElementById("ovBars");
  if(b){
    if(charts.ovb)charts.ovb.destroy();
    const band=f=>ms.map(m=>Object.entries(m.dist||{}).reduce((s,[k,v])=>s+(f(+k)?v:0),0));
    const bar=(label,data,col)=>({label,data,backgroundColor:col,borderColor:"#111",
      borderWidth:2,borderSkipped:false,borderRadius:3,maxBarThickness:56});
    charts.ovb=new Chart(b,{type:"bar",
      data:{labels:ms.map(m=>m.label),datasets:[
        bar("4–5★",band(k=>k>=4),"#2ec16b"),bar("3★",band(k=>k===3),"#f4c000"),bar("1–2★",band(k=>k<3),"#FF0005")]},
      options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
        plugins:{legend:{labels:{color:"#cfcfcf",font:{family:"Montserrat"}}},tooltip:{filter:c=>c.parsed.y>0}},
        scales:{x:{stacked:true,ticks:{color:"#8f8f8f",maxRotation:0},grid:{display:false}},
          y:{stacked:true,ticks:{color:"#8f8f8f",stepSize:5,precision:0},grid:{color:"#1c1c1c"}}}}});
  }
  const t=document.getElementById("ovTrend");
  if(t){
    if(charts.ovt)charts.ovt.destroy();
    const keys=[...new Set(ms.flatMap(m=>(m.place_stats||[]).map(p=>p.src+":"+p.key)))];
    const sets=keys.map((k,i)=>{
      const col=PCOLOR[k]||PFALLBACK[i%PFALLBACK.length];
      const pts=ms.map(m=>{const p=(m.place_stats||[]).find(x=>x.src+":"+x.key===k);return p?p.rating:null;});
      const first=ms.flatMap(m=>m.place_stats||[]).find(x=>x.src+":"+x.key===k);
      return {label:first.src==="google"?first.label:"TripAdvisor",data:pts,borderColor:col,
        backgroundColor:col+"22",tension:.3,spanGaps:true,pointRadius:3,borderWidth:2};
    });
    charts.ovt=new Chart(t,{type:"line",data:{labels:ms.map(m=>m.label),datasets:sets},
      options:chartOpts(ms.flatMap(m=>(m.place_stats||[]).map(p=>p.rating)))});
  }
}

const tabs=[{key:"__ov__",label:"Overview",future:false}]
  .concat(DATA.months.map(m=>({key:m.key,label:m.label,future:m.key>DATA.current_month})));
function show(key){
  document.querySelectorAll("#tabs button").forEach(b=>b.classList.toggle("on",b.dataset.k===key));
  const v=document.getElementById("views");
  if(key==="__ov__"){v.innerHTML=overviewView();drawOverview();}
  else{const m=DATA.months.find(x=>x.key===key);v.innerHTML=monthView(m);
    if(m.new_total)drawBars(m);
    if(m.series&&m.series.length)drawMonthChart(m);}
}
document.getElementById("updated").textContent="Updated: "+DATA.updated+" (Phuket) · refreshed daily";
const tb=document.getElementById("tabs");
tabs.forEach(t=>{const b=document.createElement("button");b.textContent=t.label;b.dataset.k=t.key;
  if(t.future)b.classList.add("future");b.onclick=()=>show(t.key);tb.appendChild(b);});
show(DATA.months.some(m=>m.key===DATA.current_month)?DATA.current_month:"__ov__");
</script>
</body>
</html>
"""


def main():
    os.makedirs(DOCS, exist_ok=True)
    data = build_data()
    html = TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    with open(os.path.join(DOCS, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"dashboard: months {data['months'][0]['label']}..{data['months'][-1]['label']} "
          f"(current {data['current_month']}) → docs/index.html")


if __name__ == "__main__":
    main()
