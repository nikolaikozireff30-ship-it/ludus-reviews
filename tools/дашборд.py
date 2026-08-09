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


def build_data():
    снимки = load(os.path.join(ДАННЫЕ, "снимки.json"), {})
    склад = load(os.path.join(ДАННЫЕ, "отзывы.json"), {})
    reviews = [v for v in склад.values() if isinstance(v, dict)]

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
        end_snap = снимки[snap_dates[-1]] if snap_dates else None

        mrev = [r for r in reviews if (r.get("date") or "").startswith(m)]
        g_rev = [r for r in mrev if r["source"] == "google"]
        t_rev = [r for r in mrev if r["source"] == "tripadvisor"]
        dist = {}
        for r in mrev:
            if isinstance(r.get("rating"), (int, float)):
                k = int(r["rating"])
                dist[k] = dist.get(k, 0) + 1

        d_g = d_t = None
        if end_snap and prev_snap:
            if end_snap.get("g_rating") is not None and prev_snap.get("g_rating") is not None:
                d_g = round(end_snap["g_rating"] - prev_snap["g_rating"], 2)
            if end_snap.get("t_rating") is not None and prev_snap.get("t_rating") is not None:
                d_t = round(end_snap["t_rating"] - prev_snap["t_rating"], 2)

        out_months.append({
            "key": m, "label": month_label(m), "daily": daily,
            "new_total": len(mrev), "new_google": len(g_rev), "new_tripadvisor": len(t_rev),
            "avg_month": avg([r.get("rating") for r in mrev]),
            "avg_google": avg([r.get("rating") for r in g_rev]),
            "avg_tripadvisor": avg([r.get("rating") for r in t_rev]),
            "dist": dist,
            "end_g": (end_snap or {}).get("g_rating"), "end_gc": (end_snap or {}).get("g_count"),
            "end_t": (end_snap or {}).get("t_rating"), "end_tc": (end_snap or {}).get("t_count"),
            "d_g": d_g, "d_t": d_t,
            "reviews": sorted([{
                "source": r["source"], "rating": r.get("rating"), "date": r.get("date"),
                "author": r.get("author"), "url": r.get("url"),
                "text": (r.get("text_en") or r.get("text") or "").strip()[:280],
            } for r in mrev], key=lambda x: x["date"] or "", reverse=True),
        })
        if end_snap:
            prev_snap = end_snap

    last = снимки[sorted(снимки)[-1]] if снимки else {}
    overall = {"google": {"rating": last.get("g_rating"), "count": last.get("g_count")},
               "tripadvisor": {"rating": last.get("t_rating"), "count": last.get("t_count")}}

    return {"updated": now.strftime("%Y-%m-%d %H:%M"), "current_month": current,
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
.cards{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:22px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px}
.card .k{font-family:var(--head);text-transform:uppercase;letter-spacing:1.5px;font-size:11px;color:var(--silver)}
.card .v{font-family:var(--head);font-weight:700;font-size:40px;line-height:1;margin-top:6px}
.card .v .s{color:var(--silver);font-size:16px;font-weight:500;margin-left:6px}
.g{color:#2ec16b}.y{color:#f4c000}.r{color:var(--red)}
h2{font-family:var(--head);text-transform:uppercase;letter-spacing:2px;font-size:15px;margin:26px 0 12px;padding-bottom:8px;border-bottom:2px solid var(--red);display:inline-block}
.chartbox{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin-bottom:22px;position:relative}
.empty{color:var(--silver);font-size:13px;text-align:center;padding:38px 10px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.stat .k{font-family:var(--head);text-transform:uppercase;letter-spacing:1px;font-size:10px;color:var(--silver)}
.stat .v{font-family:var(--head);font-weight:700;font-size:26px;margin-top:4px}
.dist{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0 20px}
.dist span{background:#0c0c0c;border:1px solid #2a2a2a;border-radius:8px;padding:5px 10px;font-family:var(--head);font-size:13px}
table{width:100%;border-collapse:collapse;margin-top:6px}
th{font-family:var(--head);text-transform:uppercase;letter-spacing:1px;font-size:10px;color:var(--silver);text-align:left;padding:8px 8px;border-bottom:1px solid var(--line)}
td{padding:9px 8px;border-bottom:1px solid var(--line);font-size:13px;vertical-align:top}
td.r{text-align:right;font-family:var(--head)}
.rev{border-bottom:1px solid var(--line);padding:11px 0}
.rev .h{font-family:var(--head);font-size:13px}
.rev .t{color:#cfcfcf;font-size:13px;margin-top:3px}
.rev a{color:var(--red);text-decoration:none;font-size:12px}
.hide{display:none}.mut{color:var(--silver);font-size:12px}
@media(max-width:720px){.cards{grid-template-columns:1fr}.stats{grid-template-columns:1fr 1fr}}
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
  const c = s => {const r=o[s].rating,n=o[s].count; const name=s==="google"?"Google":"TripAdvisor";
    return `<div class="card"><div class="k">${name}</div>
      <div class="v ${clr(r)}">${fx(r,1)}★ <span class="s">${n??"—"} reviews</span></div></div>`;};
  return `<div class="cards">${c("google")}${c("tripadvisor")}</div>`;
}

function overviewView(){
  const dm = DATA.months.filter(hasData);
  let rows = dm.slice().reverse().map(m=>{
    const dg=(typeof m.d_g==="number")?(m.d_g>=0?"+":"")+m.d_g:"—";
    const dt=(typeof m.d_t==="number")?(m.d_t>=0?"+":"")+m.d_t:"—";
    return `<tr><td>${m.label}</td>
      <td class="r">${m.new_total}<div class="mut">${m.new_google} G · ${m.new_tripadvisor} T</div></td>
      <td class="r ${clr(m.avg_month)}">${fx(m.avg_month,2)}</td>
      <td class="r ${clr(m.end_g)}">${fx(m.end_g,1)}★<div class="mut">Δ ${dg}</div></td>
      <td class="r ${clr(m.end_t)}">${fx(m.end_t,1)}★<div class="mut">Δ ${dt}</div></td></tr>`;}).join("");
  return `${overallCards(DATA.overall)}
    <h2>Monthly overview</h2>
    <div class="chartbox">${dm.length?'<canvas id="ovChart" height="120"></canvas>':'<div class="empty">Collecting data — the chart appears as months are recorded.</div>'}</div>
    <table><tr><th>Month</th><th style="text-align:right">New reviews</th>
      <th style="text-align:right">Avg of month’s reviews</th>
      <th style="text-align:right">Google (end)</th><th style="text-align:right">TripAdvisor (end)</th></tr>
      ${rows || '<tr><td colspan="5" class="mut">No data yet.</td></tr>'}</table>`;
}

function monthView(m){
  const dist = Object.keys(m.dist).sort((a,b)=>b-a).map(k=>`<span>${k}★ × ${m.dist[k]}</span>`).join("");
  const revs = m.reviews.map(r=>`<div class="rev">
      <div class="h">${clr(r.rating)?('<span class="'+clr(r.rating)+'">●</span> '):''}★${r.rating} · ${r.source==="google"?"Google":"TripAdvisor"} · ${r.author||"—"} · <span class="mut">${r.date||""}</span></div>
      ${r.text?`<div class="t">${escapeHtml(r.text)}</div>`:""}
      ${r.url?`<a href="${r.url}" target="_blank">open review ↗</a>`:""}</div>`).join("")
    || '<div class="mut">No reviews recorded for this month yet.</div>';
  const chart = (m.daily && m.daily.length)
    ? `<canvas id="ch_${m.key}" height="120"></canvas>`
    : `<div class="empty">Daily rating data is collected once a day.<br>The trend line for ${m.label} appears as snapshots accumulate.</div>`;
  return `${overallCards(DATA.overall)}
    <h2>${m.label} · rating trend</h2>
    <div class="chartbox">${chart}</div>
    <div class="stats">
      <div class="stat"><div class="k">New reviews</div><div class="v">${m.new_total}</div></div>
      <div class="stat"><div class="k">Avg of month’s reviews</div><div class="v ${clr(m.avg_month)}">${fx(m.avg_month,2)}</div></div>
      <div class="stat"><div class="k">Google (month end)</div><div class="v ${clr(m.end_g)}">${fx(m.end_g,1)}★</div></div>
      <div class="stat"><div class="k">TripAdvisor (month end)</div><div class="v ${clr(m.end_t)}">${fx(m.end_t,1)}★</div></div>
    </div>
    <div class="dist">${dist||'<span class="mut">no distribution yet</span>'}</div>
    <h2>Reviews received</h2>${revs}`;
}

function escapeHtml(s){return (s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}

function chartOpts(vals){
  const nums=vals.filter(v=>typeof v==="number");
  const mn=nums.length?Math.max(0,Math.min(...nums)-0.3):0;
  return {responsive:true,maintainAspectRatio:false,interaction:{mode:"index",intersect:false},
    plugins:{legend:{labels:{color:"#cfcfcf",font:{family:"Montserrat"}}},
      tooltip:{callbacks:{label:c=>c.dataset.label+": "+(c.parsed.y==null?"—":c.parsed.y.toFixed(2)+"★")}}},
    scales:{y:{suggestedMin:mn,suggestedMax:5,ticks:{color:"#8f8f8f"},grid:{color:"#1c1c1c"}},
      x:{ticks:{color:"#8f8f8f",maxRotation:0,autoSkip:true},grid:{color:"#141414"}}}};
}
function drawMonthChart(m){
  const ctx=document.getElementById("ch_"+m.key); if(!ctx||charts[m.key])return;
  charts[m.key]=new Chart(ctx,{type:"line",
    data:{labels:m.daily.map(d=>d.date.slice(8)),datasets:[
      {label:"Google",data:m.daily.map(d=>d.g),borderColor:"#FF0005",backgroundColor:"#FF000522",tension:.3,spanGaps:true,pointRadius:2},
      {label:"TripAdvisor",data:m.daily.map(d=>d.t),borderColor:"#A5A5A5",backgroundColor:"#A5A5A522",tension:.3,spanGaps:true,pointRadius:2}]},
    options:chartOpts(m.daily.flatMap(d=>[d.g,d.t]))});
}
function drawOverview(){
  const ctx=document.getElementById("ovChart"); if(!ctx||charts.ov)return;
  const ms=DATA.months.filter(hasData);
  charts.ov=new Chart(ctx,{type:"line",
    data:{labels:ms.map(m=>m.label),datasets:[
      {label:"Google (month end)",data:ms.map(m=>m.end_g),borderColor:"#FF0005",tension:.3,spanGaps:true,pointRadius:3},
      {label:"Avg of month’s reviews",data:ms.map(m=>m.avg_month),borderColor:"#2ec16b",borderDash:[5,4],tension:.3,spanGaps:true,pointRadius:3}]},
    options:chartOpts(ms.flatMap(m=>[m.end_g,m.avg_month]))});
}

const tabs=[{key:"__ov__",label:"Overview",future:false}]
  .concat(DATA.months.map(m=>({key:m.key,label:m.label,future:m.key>DATA.current_month})));
function show(key){
  document.querySelectorAll("#tabs button").forEach(b=>b.classList.toggle("on",b.dataset.k===key));
  const v=document.getElementById("views");
  if(key==="__ov__"){v.innerHTML=overviewView();drawOverview();}
  else{const m=DATA.months.find(x=>x.key===key);v.innerHTML=monthView(m);if(m.daily&&m.daily.length)drawMonthChart(m);}
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
