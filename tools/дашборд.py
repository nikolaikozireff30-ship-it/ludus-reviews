#!/usr/bin/env python3
"""LUDUS reviews — HTML analytics dashboard generator (v2: фильтры).

Читает данные/снимки.json (дневные снимки оценок по точкам) и данные/отзывы.json
и пишет docs/index.html (Chart.js с CDN, стиль LUDUS, англ).

Вся агрегация — в браузере: страница получает плоский список отзывов и снимки,
а три фильтра (период MTD/YTD/месяц/всё время · точка · оценка) пересчитывают
карточки, графики, таблицу и список на лету. Даты — по Asia/Bangkok.
"""
import datetime
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
ДАННЫЕ = os.path.join(ROOT, "данные")
DOCS = os.path.join(ROOT, "docs")

START_MONTH = "2026-08"   # с этого месяца начинаем показывать (полноценный мониторинг)


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


PLACE_COLORS = {"google:complex": "#FF0005", "google:gym": "#3987e5", "google:massage": "#d95926",
                "google:shop": "#199e70", "tripadvisor:ta": "#c98500"}
FALLBACK_COLORS = ["#d55181", "#3987e5", "#199e70", "#c98500"]
UNASSIGNED = "none"   # отзывы, собранные до разбивки по точкам (до 11.08.2026): точка неизвестна


def build_data():
    """Плоские данные для дашборда: все отзывы + дневные снимки по точкам.

    Агрегация (MTD/YTD/месяц, фильтры по точке и оценке) делается в браузере —
    так один массив отзывов обслуживает любой срез без пересборки страницы.
    """
    снимки = load(os.path.join(ДАННЫЕ, "снимки.json"), {})
    склад = load(os.path.join(ДАННЫЕ, "отзывы.json"), {})
    reviews = [v for v in склад.values() if isinstance(v, dict)]
    места = места_карт()

    places = []
    for src in ("google", "tripadvisor"):
        for i, pl in enumerate(места[src]):
            pid = f"{src}:{pl['key']}"
            places.append({"id": pid, "src": src, "key": pl["key"], "label": pl["label"],
                           "color": PLACE_COLORS.get(pid, FALLBACK_COLORS[i % len(FALLBACK_COLORS)])})
    ta_ids = [p["id"] for p in places if p["src"] == "tripadvisor"]

    def place_id(r):
        src = r.get("source")
        if r.get("place"):
            return f"{src}:{r['place']}"
        # у TripAdvisor одна карточка — старые отзывы без метки относятся к ней однозначно
        if src == "tripadvisor" and len(ta_ids) == 1:
            return ta_ids[0]
        return UNASSIGNED

    now = сейчас_пхукет()
    today = now.strftime("%Y-%m-%d")
    current = now.strftime("%Y-%m")

    snaps = []
    for d in sorted(k for k in снимки if isinstance(k, str) and len(k) == 10):
        row = {}
        for p in places:
            r, c = из_снимка(снимки[d], p["src"], p["key"])
            if r is not None or c is not None:
                row[p["id"]] = {"r": r, "c": c}
        if row:
            snaps.append({"date": d, "p": row})

    flat = []
    for r in reviews:
        rating = r.get("rating") if isinstance(r.get("rating"), (int, float)) else None
        flat.append({
            "id": f"{r.get('source')}:{r.get('review_id')}",
            "src": r.get("source"), "place": place_id(r), "rating": rating,
            "date": r.get("date") or "", "author": r.get("author") or "—", "url": r.get("url") or "",
            "replied": bool(r.get("owner_replied")), "lang": r.get("lang") or "",
            "text": (r.get("text_en") or r.get("text") or "").strip()[:500],
        })
    flat.sort(key=lambda x: x["date"], reverse=True)

    # отзывы, оставленные ДО старта мониторинга: найдены при первой загрузке,
    # не относятся ни к одному отслеживаемому месяцу — в «All time» входят, в месяцы нет
    до_старта = [x for x in flat if x["date"] and x["date"][:7] < START_MONTH]
    оц_до = [x["rating"] for x in до_старта if x["rating"] is not None]
    pre_start = {"count": len(до_старта),
                 "avg": round(sum(оц_до) / len(оц_до), 2) if оц_до else None,
                 "from": min((x["date"] for x in до_старта), default=None),
                 "to": max((x["date"] for x in до_старта), default=None)}

    months = []
    cur = START_MONTH
    while cur <= current:
        months.append({"key": cur, "label": month_label(cur)})
        cur = month_add(cur, 1)

    return {"updated": now.strftime("%Y-%m-%d %H:%M"), "today": today, "current_month": current,
            "start_month": START_MONTH, "start_label": month_label(START_MONTH),
            "places": places, "unassigned": UNASSIGNED, "months": months,
            "snapshots": snaps, "reviews": flat, "pre_start": pre_start}


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
.sub{color:var(--silver);font-size:12px;margin-bottom:18px}
/* ---- фильтры ---- */
.filters{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 16px;margin-bottom:20px}
.frow{display:flex;align-items:center;flex-wrap:wrap;gap:6px;padding:6px 0}
.frow+.frow{border-top:1px solid var(--line)}
.frow .lab{font-family:var(--head);text-transform:uppercase;letter-spacing:1.5px;font-size:10px;color:var(--silver);width:72px;flex:none}
.chip{background:#0c0c0c;border:1px solid #2a2a2a;color:#bbb;border-radius:9px;padding:7px 12px;cursor:pointer;font-family:var(--head);letter-spacing:.8px;font-size:12px;text-transform:uppercase;display:inline-flex;align-items:center;gap:7px}
.chip:hover{border-color:#555;color:#fff}
.chip.on{background:var(--red);color:#fff;border-color:var(--red)}
.chip .dot{width:9px;height:9px;border-radius:50%;display:inline-block}
.chip.sw{background:#0c0c0c;color:#bbb;border-color:#2a2a2a}
.chip.sw.on{background:#1a1a1a;color:#fff;border-color:#666}
.chip.ghost{border-style:dashed;color:var(--silver)}
select.sel{background:#0c0c0c;border:1px solid #2a2a2a;color:#ddd;border-radius:9px;padding:7px 10px;font-family:var(--head);font-size:12px;letter-spacing:.8px;text-transform:uppercase}
.range{color:var(--silver);font-size:12px;margin-left:auto;font-family:var(--head);letter-spacing:.5px}
/* ---- карточки / KPI ---- */
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:14px;margin-bottom:8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;border-top:3px solid var(--line)}
.card .k{font-family:var(--head);text-transform:uppercase;letter-spacing:1.5px;font-size:11px;color:var(--silver)}
.card .v{font-family:var(--head);font-weight:700;font-size:30px;line-height:1;margin-top:6px}
.card .v .s{color:var(--silver);font-size:15px;font-weight:500;margin-left:6px}
.card .d{font-size:12px;color:var(--silver);margin-top:6px;font-family:var(--head)}
.g{color:#2ec16b}.y{color:#f4c000}.r{color:var(--red)}
h2{font-family:var(--head);text-transform:uppercase;letter-spacing:2px;font-size:15px;margin:26px 0 12px;padding-bottom:8px;border-bottom:2px solid var(--red);display:inline-block}
.h2row{display:flex;align-items:baseline;justify-content:space-between;gap:12px;flex-wrap:wrap}
.chartbox{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:22px;position:relative;height:320px}
.chartbox.slim{height:240px}
.chartbox canvas{width:100%!important;height:100%!important;display:block}
.empty{color:var(--silver);font-size:13px;text-align:center;padding:38px 10px;line-height:1.6}
.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:14px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.stat .k{font-family:var(--head);text-transform:uppercase;letter-spacing:1px;font-size:10px;color:var(--silver)}
.stat .v{font-family:var(--head);font-weight:700;font-size:26px;margin-top:4px}
.stat .d{font-size:11px;color:var(--silver);margin-top:4px;font-family:var(--head);letter-spacing:.3px}
.stat .d b{font-weight:600}
/* ---- распределение оценок (кликабельные полосы) ---- */
.dist{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:22px}
.drow{display:grid;grid-template-columns:44px 1fr 56px;align-items:center;gap:10px;padding:5px 4px;border-radius:8px;cursor:pointer}
.drow:hover{background:#181818}
.drow.on{background:#1d1d1d;outline:1px solid #444}
.drow.off{opacity:.38}
.drow .l{font-family:var(--head);font-size:13px}
.drow .bar{height:14px;background:#0c0c0c;border-radius:4px;overflow:hidden}
.drow .bar i{display:block;height:100%;border-radius:4px}
.drow .n{font-family:var(--head);font-size:13px;text-align:right}
.hint{color:var(--silver);font-size:11px;margin-top:8px}
/* ---- таблицы / список ---- */
.tscroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;margin-top:6px}
th{font-family:var(--head);text-transform:uppercase;letter-spacing:1px;font-size:10px;color:var(--silver);text-align:left;padding:8px 8px;border-bottom:1px solid var(--line)}
td{padding:9px 8px;border-bottom:1px solid var(--line);font-size:13px;vertical-align:top}
td.num{text-align:right;font-family:var(--head)}
tr.sel td{background:#181818}
.rev{border-bottom:1px solid var(--line);padding:11px 0}
.rev .h{font-family:var(--head);font-size:13px}
.rev .t{color:#cfcfcf;font-size:13px;margin-top:3px}
.rev a{color:var(--red);text-decoration:none;font-size:12px}
.nr{font-size:11px;color:#f4c000;font-family:var(--head);letter-spacing:.5px}
.nr.bad{color:var(--red)}
.mut{color:var(--silver);font-size:12px}
.asof{color:var(--silver);font-size:12px;margin:0 0 20px;line-height:1.5}
.toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.btn{background:#0c0c0c;border:1px solid #2a2a2a;color:#ddd;border-radius:9px;padding:7px 12px;cursor:pointer;font-family:var(--head);font-size:12px;letter-spacing:.8px;text-transform:uppercase}
.btn:hover{border-color:#666;color:#fff}
.btn.primary{background:var(--red);border-color:var(--red);color:#fff}
.note{background:#141414;border:1px solid #2a2a2a;border-left:3px solid #f4c000;border-radius:10px;padding:10px 14px;font-size:12px;color:#ddd;margin-bottom:16px;line-height:1.5}
@media(max-width:720px){
  .wrap{padding:18px 14px 50px}
  .logo{font-size:22px;letter-spacing:2px}
  .cards{grid-template-columns:1fr 1fr;gap:10px}
  .stats{grid-template-columns:1fr 1fr;gap:10px}
  .card .v{font-size:24px}
  .card .v .s{display:block;margin:4px 0 0}
  .stat .v{font-size:22px}
  .chartbox{height:250px;padding:12px}
  .frow .lab{width:100%;padding-top:2px}
  .range{margin-left:0;width:100%}
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

  <div class="filters">
    <div class="frow"><span class="lab">Period</span><span id="fPeriod"></span><span class="range" id="fRange"></span></div>
    <div class="frow"><span class="lab">Place</span><span id="fPlace"></span></div>
    <div class="frow"><span class="lab">Rating</span><span id="fRating"></span></div>
  </div>

  <div id="view"></div>
</div>
<script>
const DATA = __DATA__;

/* ============ состояние фильтров ============ */
const S = {period:"mtd", month:DATA.current_month, place:"all", ratings:new Set([1,2,3,4,5]), sort:"date_desc"};
const charts = {};

/* ============ утилиты ============ */
const clr = r => (typeof r!=="number") ? "" : (r<3?"r":(r<4?"y":"g"));
const fx = (r,d=1) => (typeof r==="number") ? r.toFixed(d) : "—";
const esc = s => (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
const pad = n => String(n).padStart(2,"0");
const isoAdd = (iso,days) => {const d=new Date(iso+"T12:00:00Z"); d.setUTCDate(d.getUTCDate()+days); return d.toISOString().slice(0,10);};
const lastDay = ym => {const [y,m]=ym.split("-").map(Number); return pad(new Date(Date.UTC(y,m,0)).getUTCDate());};
const monthLabel = ym => new Date(ym+"-01T12:00:00Z").toLocaleDateString("en-GB",{month:"short",year:"numeric",timeZone:"UTC"});
const dLabel = iso => new Date(iso+"T12:00:00Z").toLocaleDateString("en-GB",{day:"numeric",month:"short",timeZone:"UTC"});
const PL = Object.fromEntries(DATA.places.map(p=>[p.id,p]));
const placeName = id => id===DATA.unassigned ? "Unassigned" : (PL[id] ? (PL[id].src==="google"?"Google · "+PL[id].label:"TripAdvisor") : id);
const placeShort = id => id===DATA.unassigned ? "Unassigned" : (PL[id] ? PL[id].label : id);
const placeColor = id => PL[id] ? PL[id].color : "#8a8a8a";
const sign = v => (v>0?"+":"")+v;

/* ============ период ============ */
// Возвращает {from,to,label,cmp:{from,to,label}|null}. cmp — период для сравнения.
function periodRange(){
  const today = DATA.today, ym = today.slice(0,7), y = today.slice(0,4);
  if(S.period==="mtd"){
    const prevYm = (()=>{const [Y,M]=ym.split("-").map(Number); const d=new Date(Date.UTC(Y,M-2,1)); return d.toISOString().slice(0,7);})();
    const day = Math.min(+today.slice(8), +lastDay(prevYm));
    return {from:ym+"-01", to:today, label:"Month to date",
            cmp:{from:prevYm+"-01", to:prevYm+"-"+pad(day), label:"same days of "+monthLabel(prevYm)}};
  }
  if(S.period==="ytd"){
    const py = String(+y-1);
    const first = DATA.reviews.length ? DATA.reviews[DATA.reviews.length-1].date : today;
    const cmpFrom = py+"-01-01", cmpTo = py+today.slice(4);
    return {from:y+"-01-01", to:today, label:"Year to date",
            cmp: first<=cmpTo ? {from:cmpFrom,to:cmpTo,label:"same period of "+py} : null};
  }
  if(S.period==="all"){
    const first = DATA.reviews.length ? DATA.reviews[DATA.reviews.length-1].date : today;
    return {from:first, to:today, label:"All time", cmp:null};
  }
  // конкретный месяц
  const m = S.month, prev = (()=>{const [Y,M]=m.split("-").map(Number); return new Date(Date.UTC(Y,M-2,1)).toISOString().slice(0,7);})();
  const to = m===ym ? today : m+"-"+lastDay(m);
  return {from:m+"-01", to, label:monthLabel(m),
          cmp:{from:prev+"-01", to:prev+"-"+lastDay(prev), label:monthLabel(prev)}};
}

/* ============ выборки ============ */
const inRange = (d,R) => d && d>=R.from && d<=R.to;
const placeOk = r => S.place==="all" || r.place===S.place;
const ratingOk = r => r.rating==null ? S.ratings.size===5 : S.ratings.has(r.rating);
function pick(R, withRating=true){
  return DATA.reviews.filter(r=>inRange(r.date,R) && placeOk(r) && (!withRating || ratingOk(r)));
}
function stats(list){
  const rated=list.filter(r=>typeof r.rating==="number");
  const neg=rated.filter(r=>r.rating<3);
  return {n:list.length,
          avg: rated.length ? rated.reduce((s,r)=>s+r.rating,0)/rated.length : null,
          neg: neg.length,
          rep: list.length ? Math.round(100*list.filter(r=>r.replied).length/list.length) : null,
          unneg: neg.filter(r=>!r.replied).length,
          dist: [1,2,3,4,5].map(k=>rated.filter(r=>r.rating===k).length)};
}
// снимок на дату (последний ≤ date) — для «рейтинг на конец периода»
function snapAt(date){ let s=null; for(const x of DATA.snapshots){ if(x.date<=date) s=x; else break; } return s; }
function snapBefore(date){ let s=null; for(const x of DATA.snapshots){ if(x.date<date) s=x; else break; } return s; }
function snapsIn(R){ return DATA.snapshots.filter(x=>x.date>=R.from && x.date<=R.to); }
const scopePlaces = () => S.place==="all" ? DATA.places.map(p=>p.id) : (S.place===DATA.unassigned ? [] : [S.place]);

/* ============ фильтры (рендер) ============ */
function renderFilters(){
  const fp=document.getElementById("fPeriod");
  const opts=DATA.months.slice().reverse().map(m=>`<option value="${m.key}" ${S.period==="month"&&S.month===m.key?"selected":""}>${m.label}</option>`).join("");
  fp.innerHTML=`<button class="chip ${S.period==="mtd"?"on":""}" data-p="mtd">MTD</button>
    <button class="chip ${S.period==="ytd"?"on":""}" data-p="ytd">YTD</button>
    <button class="chip ${S.period==="all"?"on":""}" data-p="all">All time</button>
    <select class="sel" id="monthSel"><option value="" ${S.period!=="month"?"selected":""}>Month…</option>${opts}</select>`;
  fp.querySelectorAll("button").forEach(b=>b.onclick=()=>{S.period=b.dataset.p;render();});
  document.getElementById("monthSel").onchange=e=>{ if(e.target.value){S.period="month";S.month=e.target.value;render();} };

  const R=periodRange();
  document.getElementById("fRange").textContent = dLabel(R.from)+" – "+dLabel(R.to);

  const fpl=document.getElementById("fPlace");
  const chip=(id,label,col)=>`<button class="chip ${S.place===id?"on":""}" data-pl="${id}">${col?`<span class="dot" style="background:${col}"></span>`:""}${label}</button>`;
  fpl.innerHTML = chip("all","All") + DATA.places.map(p=>chip(p.id,p.label,p.color)).join("") + chip(DATA.unassigned,"Unassigned","#8a8a8a");
  fpl.querySelectorAll("button").forEach(b=>b.onclick=()=>{S.place=b.dataset.pl;render();});

  const fr=document.getElementById("fRating");
  const allOn=S.ratings.size===5;
  fr.innerHTML=[1,2,3,4,5].map(k=>`<button class="chip sw ${S.ratings.has(k)?"on":""}" data-r="${k}">${k}★</button>`).join("")
    +`<button class="chip ghost" data-pre="neg">Negative 1–2</button><button class="chip ghost" data-pre="neu">Neutral 3</button>`
    +(allOn?"":`<button class="chip ghost" data-pre="all">Reset</button>`);
  fr.querySelectorAll("[data-r]").forEach(b=>b.onclick=()=>{const k=+b.dataset.r; if(S.ratings.has(k)){ if(S.ratings.size>1)S.ratings.delete(k);} else S.ratings.add(k); render();});
  fr.querySelectorAll("[data-pre]").forEach(b=>b.onclick=()=>{const p=b.dataset.pre; S.ratings=new Set(p==="neg"?[1,2]:p==="neu"?[3]:[1,2,3,4,5]); render();});
}

/* ============ блоки ============ */
function cardsBlock(R){
  const end=snapAt(R.to), start=snapBefore(R.from) || snapsIn(R)[0] || null;
  const ids=scopePlaces();
  if(!ids.length) return `<div class="asof">Unassigned reviews were collected before the per-place split (11 Aug 2026); they have no live rating of their own.</div>`;
  const cards=ids.map(id=>{
    const e=end&&end.p[id], s=start&&start.p[id];
    if(!e) return "";
    const dr=(e&&s&&typeof e.r==="number"&&typeof s.r==="number")?+(e.r-s.r).toFixed(2):null;
    const dc=(e&&s&&typeof e.c==="number"&&typeof s.c==="number")?e.c-s.c:null;
    const d=[dr!=null?`<span class="${dr<0?"r":dr>0?"g":""}">${dr===0?"±0.0":sign(dr.toFixed(1))}★</span>`:"",
             dc!=null?`<span class="${dc<0?"r":""}">${dc===0?"±0":sign(dc)} reviews</span>`:""].filter(Boolean).join(" · ");
    return `<div class="card" style="border-top-color:${placeColor(id)}"><div class="k">${placeName(id)}</div>
      <div class="v ${clr(e.r)}">${fx(e.r,1)}★ <span class="s">${e.c??"—"} reviews</span></div>
      ${d?`<div class="d">${d} vs ${start.date===R.from?"period start":"before "+dLabel(R.from)}</div>`:""}</div>`;
  }).join("");
  const asof = end ? (end.date===DATA.today ? "Live totals — as of today" : "Totals as of "+dLabel(end.date)) : "No rating snapshots in this period";
  return `<div class="cards">${cards}</div><div class="asof">${asof}</div>`;
}

function cmpLine(cur, prev, R, fmt, better){
  if(!R.cmp) return `<div class="d">${S.period==="ytd"?"vs last year: n/a until 2027":"&nbsp;"}</div>`;
  if(prev==null||cur==null) return `<div class="d">vs ${R.cmp.label}: —</div>`;
  const d=cur-prev; const cls = d===0?"":((better==="up"?d>0:d<0)?"g":"r");
  return `<div class="d">vs ${R.cmp.label}: <b class="${cls}">${fmt(d)}</b> <span>(${fmt(prev,true)})</span></div>`;
}
function kpiBlock(R){
  const a=stats(pick(R)), b=R.cmp?stats(pick(R.cmp)):null;
  const n=(d,abs)=>abs?String(d):sign(d);
  const f2=(d,abs)=>abs?d.toFixed(2):sign(d.toFixed(2));
  const pc=(d,abs)=>abs?d+"%":sign(d)+" pp";
  const repCls=a.rep==null?"":(a.rep>=80?"g":(a.rep>=50?"y":"r"));
  return `<div class="stats">
    <div class="stat"><div class="k">New reviews</div><div class="v">${a.n}</div>${cmpLine(a.n,b&&b.n,R,n,"up")}</div>
    <div class="stat"><div class="k">Avg rating</div><div class="v ${clr(a.avg)}">${fx(a.avg,2)}</div>${cmpLine(a.avg,b&&b.avg,R,f2,"up")}</div>
    <div class="stat"><div class="k">Negative (&lt;3★)</div><div class="v ${a.neg?"r":"g"}">${a.neg}</div>${cmpLine(a.neg,b&&b.neg,R,n,"down")}</div>
    <div class="stat"><div class="k">Answered</div><div class="v ${repCls}">${a.rep==null?"—":a.rep+"%"}</div>${cmpLine(a.rep,b&&b.rep,R,pc,"up")}</div>
    <div class="stat"><div class="k">No-reply negative</div><div class="v ${a.unneg?"r":"g"}">${a.unneg}</div>${cmpLine(a.unneg,b&&b.unneg,R,n,"down")}</div>
  </div>`;
}

function distBlock(R){
  const all=stats(pick(R,false));      // распределение считаем БЕЗ фильтра по оценке — иначе нечего кликать
  const max=Math.max(1,...all.dist);
  const cols={1:"#FF0005",2:"#FF0005",3:"#f4c000",4:"#2ec16b",5:"#2ec16b"};
  const rows=[5,4,3,2,1].map(k=>{const v=all.dist[k-1]; const on=S.ratings.has(k)&&S.ratings.size<5; const off=!S.ratings.has(k);
    return `<div class="drow ${on?"on":""} ${off?"off":""}" data-k="${k}"><span class="l">${k}★</span><span class="bar"><i style="width:${Math.round(100*v/max)}%;background:${cols[k]}"></i></span><span class="n">${v}</span></div>`;}).join("");
  return `<div class="dist">${rows}<div class="hint">Click a row to filter by that rating · ${all.n} reviews in period${S.place!=="all"?" · "+placeShort(S.place):""}</div></div>`;
}

function volumeBlock(R, list){
  if(list.length<5) return `<div class="chartbox slim"><div class="empty">Only ${list.length} review${list.length===1?"":"s"} match — too few for a chart.<br>See the list below.</div></div>`;
  return `<div class="chartbox"><canvas id="chVol"></canvas></div>`;
}
function trendBlock(R){
  const ids=scopePlaces(); const sn=snapsIn(R);
  if(!ids.length) return "";
  if(sn.length<2) return `<h2>Rating trend</h2><div class="chartbox slim"><div class="empty">Daily rating snapshots are collected once a day.<br>${sn.length?"Only one snapshot in this period.":"No snapshots in this period (monitoring started "+DATA.start_label+")."}</div></div>`;
  return `<h2>Rating trend</h2><div class="chartbox slim"><canvas id="chTrend"></canvas></div>`;
}
function placesTable(R){
  const end=snapAt(R.to);
  const rows=DATA.places.map(p=>p.id).concat([DATA.unassigned]).map(id=>{
    const list=DATA.reviews.filter(r=>inRange(r.date,R)&&r.place===id&&ratingOk(r));
    const e=end&&end.p[id]; const st=stats(list);
    if(!e && !list.length) return "";
    return `<tr class="${S.place===id?"sel":""}"><td><span class="dot" style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${placeColor(id)};margin-right:7px"></span>${placeName(id)}</td>
      <td class="num ${e?clr(e.r):""}">${e?fx(e.r,1)+"★":"·"}</td><td class="num">${e?(e.c??"—"):"·"}</td>
      <td class="num">${st.n||"·"}</td><td class="num ${st.n?clr(st.avg):""}">${st.n?fx(st.avg,2):"·"}</td>
      <td class="num ${st.neg?"r":""}">${st.neg||"·"}</td><td class="num">${st.rep==null?"·":st.rep+"%"}</td></tr>`;}).join("");
  return `<h2>Places</h2><div class="tscroll"><table><tr><th>Place</th><th style="text-align:right">Rating</th><th style="text-align:right">Total</th>
    <th style="text-align:right">New</th><th style="text-align:right">Avg new</th><th style="text-align:right">Negative</th><th style="text-align:right">Answered</th></tr>${rows}</table></div>`;
}
function reviewsBlock(list){
  const sorted=list.slice().sort((a,b)=>{
    if(S.sort==="date_desc") return b.date.localeCompare(a.date);
    if(S.sort==="date_asc") return a.date.localeCompare(b.date);
    const ra=a.rating??9, rb=b.rating??9;
    return S.sort==="rating_asc" ? (ra-rb||b.date.localeCompare(a.date)) : (rb-ra||b.date.localeCompare(a.date));
  });
  const items=sorted.map(r=>`<div class="rev">
      <div class="h">${clr(r.rating)?('<span class="'+clr(r.rating)+'">●</span> '):''}★${r.rating??"—"} · ${placeName(r.place)} · ${esc(r.author)} · <span class="mut">${r.date}</span>${r.replied?"":` <span class="nr${(typeof r.rating==="number"&&r.rating<3)?" bad":""}">⚠ no reply</span>`}</div>
      ${r.text?`<div class="t">${esc(r.text)}</div>`:""}
      ${r.url?`<a href="${esc(r.url)}" target="_blank" rel="noopener">open review ↗</a>`:""}</div>`).join("")
    || '<div class="mut">No reviews match the current filters.</div>';
  const sel=`<select class="sel" id="sortSel">
    <option value="date_desc" ${S.sort==="date_desc"?"selected":""}>Newest first</option>
    <option value="date_asc" ${S.sort==="date_asc"?"selected":""}>Oldest first</option>
    <option value="rating_asc" ${S.sort==="rating_asc"?"selected":""}>Lowest rating first</option>
    <option value="rating_desc" ${S.sort==="rating_desc"?"selected":""}>Highest rating first</option></select>`;
  return `<div class="h2row"><h2>Reviews · ${list.length}</h2><div class="toolbar">${sel}<button class="btn" id="csvBtn">⬇ Download CSV</button></div></div>${items}`;
}

/* ============ CSV ============ */
function downloadCSV(list){
  const q=s=>'"'+String(s??"").replace(/"/g,'""')+'"';
  const head=["date","source","place","rating","author","replied","text","url"];
  const rows=list.map(r=>[r.date,r.src,placeShort(r.place),r.rating??"",r.author,r.replied?"yes":"no",r.text,r.url].map(q).join(","));
  const csv="﻿"+head.join(",")+"\n"+rows.join("\n");       // BOM — чтобы Excel понял UTF-8
  const R=periodRange();
  const name=`ludus-reviews_${R.from}_${R.to}${S.place!=="all"?"_"+placeShort(S.place).replace(/\W+/g,"-"):""}.csv`;
  const a=document.createElement("a"); a.href=URL.createObjectURL(new Blob([csv],{type:"text/csv;charset=utf-8"})); a.download=name; a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href),2000);
}

/* ============ графики ============ */
const GRID={color:"#1c1c1c"}, TICK={color:"#8f8f8f"};
const LEGEND={labels:{color:"#cfcfcf",font:{family:"Montserrat"},boxWidth:12}};
function drawVolume(R, list){
  const ctx=document.getElementById("chVol"); if(!ctx)return;
  if(charts.vol)charts.vol.destroy();
  const days=(new Date(R.to)-new Date(R.from))/864e5+1;
  const byDay=days<=62;
  const keys=[]; if(byDay){for(let d=R.from; d<=R.to; d=isoAdd(d,1))keys.push(d);} else {let m=R.from.slice(0,7); while(m<=R.to.slice(0,7)){keys.push(m); const [Y,M]=m.split("-").map(Number); m=new Date(Date.UTC(Y,M,1)).toISOString().slice(0,7);}}
  const idx=Object.fromEntries(keys.map((k,i)=>[k,i]));
  const g=keys.map(()=>0),ye=keys.map(()=>0),rr=keys.map(()=>0);
  list.forEach(r=>{ if(typeof r.rating!=="number")return; const k=byDay?r.date:r.date.slice(0,7); const i=idx[k]; if(i==null)return;
    if(r.rating<3)rr[i]++; else if(r.rating<4)ye[i]++; else g[i]++; });
  const bar=(label,data,col)=>({label,data,backgroundColor:col,borderColor:"#111",borderWidth:2,borderSkipped:false,borderRadius:3,maxBarThickness:byDay?26:56});
  const sets=[]; if(S.ratings.has(4)||S.ratings.has(5))sets.push(bar("4–5★",g,"#2ec16b")); if(S.ratings.has(3))sets.push(bar("3★",ye,"#f4c000")); if(S.ratings.has(1)||S.ratings.has(2))sets.push(bar("1–2★",rr,"#FF0005"));
  charts.vol=new Chart(ctx,{type:"bar",data:{labels:keys.map(k=>byDay?dLabel(k):monthLabel(k)),datasets:sets},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
      plugins:{legend:LEGEND,tooltip:{filter:c=>c.parsed.y>0}},
      scales:{x:{stacked:true,ticks:{...TICK,maxRotation:0,autoSkip:true},grid:{display:false}},
        y:{stacked:true,ticks:{...TICK,stepSize:1,precision:0},grid:GRID}}}});
}
function drawTrend(R){
  const ctx=document.getElementById("chTrend"); if(!ctx)return;
  if(charts.tr)charts.tr.destroy();
  const sn=snapsIn(R), ids=scopePlaces();
  const sets=ids.map(id=>({label:placeShort(id),data:sn.map(x=>x.p[id]?x.p[id].r:null),borderColor:placeColor(id),backgroundColor:placeColor(id)+"22",tension:.3,spanGaps:true,pointRadius:2,borderWidth:2}))
    .filter(s=>s.data.some(v=>v!=null));
  const vals=sets.flatMap(s=>s.data).filter(v=>typeof v==="number");
  const mn=vals.length?Math.max(0,Math.min(...vals)-0.2):0;
  charts.tr=new Chart(ctx,{type:"line",data:{labels:sn.map(x=>dLabel(x.date)),datasets:sets},
    options:{responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
      plugins:{legend:{...LEGEND,display:sets.length>1},tooltip:{callbacks:{label:c=>c.dataset.label+": "+(c.parsed.y==null?"—":c.parsed.y.toFixed(2)+"★")}}},
      scales:{y:{suggestedMin:mn,max:5,ticks:TICK,grid:GRID},x:{ticks:{...TICK,maxRotation:0,autoSkip:true},grid:{color:"#141414"}}}}});
}

/* ============ рендер страницы ============ */
function render(){
  renderFilters();
  const R=periodRange();
  const list=pick(R);
  const pre=DATA.pre_start||{count:0};
  const preNote = (S.period==="all"&&pre.count) ? `<div class="note">All time includes ${pre.count} reviews posted before monitoring started (${pre.from} – ${pre.to}, avg ${fx(pre.avg,2)}★). They were already on the pages on day one, so daily snapshots and reply tracking do not cover them.</div>` : "";
  const v=document.getElementById("view");
  v.innerHTML = cardsBlock(R) + preNote + kpiBlock(R)
    + `<h2>New reviews · ${R.label}</h2>` + volumeBlock(R,list)
    + `<h2>Rating distribution</h2>` + distBlock(R)
    + trendBlock(R) + placesTable(R) + reviewsBlock(list);
  drawVolume(R,list); drawTrend(R);
  v.querySelectorAll(".drow").forEach(el=>el.onclick=()=>{const k=+el.dataset.k;
    if(S.ratings.size===1&&S.ratings.has(k)) S.ratings=new Set([1,2,3,4,5]);   // второй клик по единственной — сброс
    else S.ratings=new Set([k]); render();});
  const ss=document.getElementById("sortSel"); if(ss) ss.onchange=e=>{S.sort=e.target.value;render();};
  const cb=document.getElementById("csvBtn"); if(cb) cb.onclick=()=>downloadCSV(list);
}
document.getElementById("updated").textContent="Updated: "+DATA.updated+" (Phuket) · refreshed daily";
render();
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
    print(f"dashboard: {len(data['reviews'])} reviews · {len(data['snapshots'])} snapshots · "
          f"months {data['months'][0]['label']}..{data['months'][-1]['label']} → docs/index.html")


if __name__ == "__main__":
    main()
