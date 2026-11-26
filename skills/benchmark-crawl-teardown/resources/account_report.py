#!/usr/bin/env python3
"""单账号拆解调研报告：把智能体写好的 report.json 渲染成单文件 HTML。

  python3 account_report.py --report out/accounts/<账号>.json --out out/accounts/<账号>.html

report.json 结构（板块不固定，按这个号的实际情况增删、排序）：
{
  "account": {"name","url","followers","total_likes","total_works","ip","bio","crawled","span","median_likes","burst_rule"},
  "headline": "一句话：这个号靠什么火、什么拍了没人看",
  "bursts": [{"title","url","likes","date","duration_s","plays"}],
  "sections": [
    {"title": "板块名", "conclusion": "这一块的结论（先说结论）", "blocks": [
        {"type": "kv", "items": [["键", "值"], ...]},
        {"type": "table", "cols": [...], "rows": [[...]], "num_cols": [列序号], "note": "口径/样本说明"},
        {"type": "bullets", "items": ["..."]},
        {"type": "pairs", "items": [{"burst": {...视频}, "ctrl": {...视频}, "rows": [["看哪方面","爆款","对照"], ...], "why": "差异句"}]},
        {"type": "quotes", "items": [{"text","likes","tag"}]},
        {"type": "months", "series": [{"label":"2026-06","value":0.43,"text":"3/7"}], "unit": "%"},
        {"type": "text", "text": "..."}
    ]}
  ],
  "caveats": ["样本与口径说明"]
}
只用标准库。数字一律是这个号自己的数据；没有数据的块写明“缺什么”，不要编。
"""
import argparse, html, json

E = lambda s: html.escape(str(s if s is not None else ""), quote=True)


def fmt_n(x):
    if x in (None, ""):
        return "—"
    try:
        x = float(x)
    except (TypeError, ValueError):
        return E(x)
    return f"{x/10000:.1f}万" if x >= 10000 else f"{x:.0f}"


CSS = r"""
:root{--paper:#F1F3F6;--panel:#E6EAF0;--ink:#1B2232;--muted:#525D6E;--rule:#CBD2DC;--hot:#C03D0B;--hot-fill:#D9480F;--cold:#3553D6;--na:#8A94A3;
--serif:"Noto Serif SC","Source Han Serif SC","Songti SC",serif;--sans:"Noto Sans SC","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--paper:#121722;--panel:#1A2130;--ink:#E4E8EF;--muted:#9EA8B8;--rule:#2B3445;--hot:#FF8A57;--hot-fill:#FF7A45;--cold:#9AACFF;--na:#6E788B}}
:root[data-theme="dark"]{--paper:#121722;--panel:#1A2130;--ink:#E4E8EF;--muted:#9EA8B8;--rule:#2B3445;--hot:#FF8A57;--hot-fill:#FF7A45;--cold:#9AACFF;--na:#6E788B}
*{box-sizing:border-box}
html{background:var(--paper);color:var(--ink);font:15px/1.7 var(--sans);-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper)}
::selection{background:var(--hot-fill);color:#fff}
a{color:inherit;text-decoration-color:var(--rule);text-underline-offset:3px}
a:hover{text-decoration-color:var(--hot)}
:focus-visible{outline:2px solid var(--cold);outline-offset:2px;border-radius:2px}
main{max-width:960px;margin:0 auto;padding:40px 20px 80px}
h1,h2,h3{font-family:var(--serif);font-weight:700;line-height:1.3;text-wrap:balance;margin:0}
h1{font-size:2.1rem}
h1 a{text-decoration:none;border-bottom:1px solid var(--rule)}
h2{font-size:1.4rem;margin:60px 0 8px}
h3{font-size:1.05rem;margin:22px 0 6px}
p{margin:.45em 0;max-width:72ch}
.num{font-variant-numeric:tabular-nums}
.muted{color:var(--muted)}
.bio{color:var(--muted);margin-top:6px}
.facts{display:flex;flex-wrap:wrap;gap:4px 22px;margin-top:14px;font-size:.92rem;color:var(--muted)}
.facts b{color:var(--ink);font-weight:600}
.headline{font-family:var(--serif);font-size:1.22rem;line-height:1.55;margin:26px 0 0;max-width:40em}
.rule{font-size:.86rem;color:var(--muted);margin-top:22px}
.blist{list-style:none;margin:10px 0 0;padding:0}
.blist li{display:grid;grid-template-columns:5.2em 1fr auto;gap:12px;align-items:baseline;padding:6px 0;border-top:1px dashed var(--rule)}
.blist .lk{font-family:var(--serif);font-weight:700;color:var(--hot);text-align:right}
.blist .lk small{font-family:var(--sans);font-weight:400;font-size:.72rem;color:var(--muted);margin-left:2px}
.blist a{font-weight:500}
.blist time{font-size:.78rem;color:var(--muted);white-space:nowrap}
.concl{font-weight:600;margin:4px 0 14px;max-width:70ch}
.kv{display:grid;grid-template-columns:8em 1fr;gap:6px 16px;margin:8px 0}
.kv dt{color:var(--muted)}.kv dd{margin:0}
.scroll{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.9rem;margin:8px 0}
th{text-align:left;font-weight:500;color:var(--muted);font-size:.8rem;padding:6px 10px 6px 0;border-bottom:1px solid var(--rule);white-space:nowrap}
td{padding:7px 10px 7px 0;border-bottom:1px solid var(--rule);vertical-align:top}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.note{font-size:.8rem;color:var(--muted)}
table.nw td,table.nw th{white-space:nowrap}
ul.b{margin:6px 0;padding-left:1.2em}
ul.b li{margin:4px 0;max-width:72ch}
.pair{margin:18px 0 26px}
.pair .vs{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.vid{padding:10px 12px;background:var(--panel);border-radius:6px}
.vid .tag{font-size:.75rem;color:var(--muted)}
.vid.hotv .tag{color:var(--hot);font-weight:600}
.vid .tt{font-weight:600;margin:2px 0}
.vid .mm{font-size:.8rem;color:var(--muted)}
.pair table td:first-child{color:var(--muted);white-space:nowrap;width:6.5em}
.why{margin-top:8px;font-weight:600}
.why::before{content:"差异：";color:var(--hot)}
.quotes{list-style:none;padding:0;margin:8px 0}
.quotes li{padding:8px 0;border-top:1px dashed var(--rule)}
.quotes .q{max-width:68ch}
.quotes .m{font-size:.78rem;color:var(--muted)}
.months{display:flex;align-items:flex-end;gap:10px;height:150px;margin:16px 0 4px;padding-bottom:0;border-bottom:1px solid var(--rule)}
.months .c{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;min-width:0}
.months .v{font-size:.78rem;color:var(--ink);margin-bottom:3px}
.months .bar{width:100%;max-width:44px;background:var(--hot-fill);border-radius:2px 2px 0 0}
.months .bar.z{background:var(--rule);height:2px}
.mlabels{display:flex;gap:10px}
.mlabels span{flex:1;text-align:center;font-size:.75rem;color:var(--muted);min-width:0}
.mlabels small{display:block;font-size:.7rem}
.rules{list-style:none;margin:10px 0;padding:0}
.rule-i{display:grid;grid-template-columns:7.5em 1fr;gap:18px;padding:16px 0;border-top:1px solid var(--rule)}
.rs b{display:block;font-family:var(--serif);font-size:1.7rem;line-height:1.1}
.rs small{display:block;font-size:.74rem;color:var(--muted);margin-top:4px;line-height:1.4}
.rs.hot b{color:var(--hot)}.rs.cold b{color:var(--cold)}.rs.na b{color:var(--muted)}
.rt{font-weight:600;margin:0}
.re{font-size:.88rem;margin:4px 0 0}
.rh{font-size:.8rem;color:var(--muted);margin:4px 0 0}
.lede{color:var(--muted);margin-top:8px;max-width:70ch}
.caveats{margin-top:60px;font-size:.84rem;color:var(--muted)}
footer{margin-top:40px;color:var(--muted);font-size:.8rem}
@media (max-width:720px){
 main{padding:28px 16px 64px}
 h1{font-size:1.65rem}
 .pair .vs{grid-template-columns:1fr}
 .kv{grid-template-columns:1fr;gap:0}
 .kv dt{margin-top:8px}
 .blist li{grid-template-columns:4.6em 1fr;gap:0 10px}
 .blist time{grid-column:2}
 .months{gap:4px}.mlabels{gap:4px}
 .rule-i{grid-template-columns:1fr;gap:4px}
 .rs b{display:inline;font-size:1.4rem;margin-right:8px}.rs small{display:inline}
}
"""


def vid_card(v, label, hot):
    meta = "　".join(x for x in [f'{fmt_n(v.get("likes"))} 赞' if v.get("likes") is not None else "",
                                 f'{round(float(v["duration_s"]) / 60, 1)} 分钟' if v.get("duration_s") else "",
                                 E(v.get("date", ""))] if x)
    t = E(v.get("title", ""))
    t = f'<a href="{E(v["url"])}" target="_blank" rel="noopener">{t}</a>' if v.get("url") else t
    return f'<div class="vid {"hotv" if hot else ""}"><div class="tag">{label}</div><div class="tt">{t}</div><div class="mm num">{meta}</div></div>'


FACTS = {}


def block(b):
    t = b.get("type")
    if t == "fact":
        fb = FACTS.get("blocks", {}).get(b["key"])
        if not fb:
            return f'<p class="note">（缺数字块 {E(b["key"])}：先运行 bench.py facts / summarize）</p>'
        fb = dict(fb)
        if b.get("note"):
            fb["note"] = b["note"]
        return block(fb)
    if t == "kv":
        return '<dl class="kv">' + "".join(f"<dt>{E(k)}</dt><dd>{E(v)}</dd>" for k, v in b["items"]) + "</dl>"
    if t == "text":
        return f'<p>{E(b["text"])}</p>'
    if t == "bullets":
        return '<ul class="b">' + "".join(f"<li>{E(x)}</li>" for x in b["items"]) + "</ul>"
    if t == "table":
        nc = set(b.get("num_cols", []))
        head = "".join(f'<th class="{"n" if i in nc else ""}">{E(c)}</th>' for i, c in enumerate(b["cols"]))
        body = "".join("<tr>" + "".join(f'<td class="{"n" if i in nc else ""}">{E(c)}</td>' for i, c in enumerate(r)) + "</tr>" for r in b["rows"])
        note = f'<p class="note">{E(b["note"])}</p>' if b.get("note") else ""
        nw = ' class="nw"' if b.get("nowrap") else ""
        return f'<div class="scroll"><table{nw}><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>{note}'
    if t == "pairs":
        out = []
        for p in b["items"]:
            rows = "".join(f"<tr><td>{E(r[0])}</td><td>{E(r[1])}</td><td>{E(r[2])}</td></tr>" for r in p.get("rows", []))
            tbl = f'<div class="scroll"><table><thead><tr><th></th><th>爆款</th><th>对照</th></tr></thead><tbody>{rows}</tbody></table></div>' if rows else ""
            out.append(f'<div class="pair"><div class="vs">{vid_card(p["burst"], "爆款", True)}{vid_card(p["ctrl"], "同号对照", False)}</div>{tbl}'
                       f'<p class="why">{E(p.get("why", ""))}</p></div>')
        return "".join(out)
    if t == "quotes":
        return '<ul class="quotes">' + "".join(
            f'<li><div class="q">{E(q["text"])}</div><div class="m num">{E(q.get("tag", ""))}{("　" + fmt_n(q["likes"]) + " 赞") if q.get("likes") not in (None, "") else ""}</div></li>'
            for q in b["items"]) + "</ul>"
    if t == "rules":
        out = []
        for x in b["items"]:
            cls = {"火": "hot", "死": "cold"}.get(x.get("verdict"), "na")
            holds = f'<p class="rh">{E(x["holds"])}</p>' if x.get("holds") else ""
            ev = f'<p class="re">{E(x["evidence"])}</p>' if x.get("evidence") else ""
            out.append(f'<li class="rule-i"><div class="rs {cls}"><b class="num">{E(x.get("stat", ""))}</b><small>{E(x.get("stat_note", ""))}</small></div>'
                       f'<div class="rc"><p class="rt">{E(x["claim"])}</p>{ev}{holds}</div></li>')
        return f'<ul class="rules">{"".join(out)}</ul>'
    if t == "links":
        return '<ul class="b">' + "".join(f'<li><a href="{E(x["href"])}">{E(x["text"])}</a>{(" ｜ " + E(x["note"])) if x.get("note") else ""}</li>' for x in b["items"]) + "</ul>"
    if t == "months":
        s = b["series"]
        mx = max([x["value"] for x in s] + [1e-9])
        unit = b.get("unit", "")
        cols, labs = [], []
        for x in s:
            h = x["value"] / mx * 100 if mx else 0
            val = f'{x["value"] * 100:.0f}%' if unit == "%" else fmt_n(x["value"])
            bar = f'<div class="bar" style="height:{h:.1f}%"></div>' if x["value"] > 0 else '<div class="bar z"></div>'
            cols.append(f'<div class="c"><div class="v num">{val}</div>{bar}</div>')
            labs.append(f'<span>{E(x["label"])}<small class="num">{E(x.get("text", ""))}</small></span>')
        note = f'<p class="note">{E(b["note"])}</p>' if b.get("note") else ""
        return f'<div class="months" role="img" aria-label="{E(b.get("aria", "按月数据"))}">{"".join(cols)}</div><div class="mlabels">{"".join(labs)}</div>{note}'
    return ""


def render_summary(r, title):
    secs = []
    for s in r.get("sections", []):
        concl = f'<p class="concl">{E(s["conclusion"])}</p>' if s.get("conclusion") else ""
        secs.append(f'<h2>{E(s["title"])}</h2>{concl}' + "".join(block(b) for b in s.get("blocks", [])))
    cav = ('<div class="caveats"><h3>口径与局限</h3><ul class="b">' + "".join(f"<li>{E(c)}</li>" for c in r.get("caveats", [])) + "</ul></div>") if r.get("caveats") else ""
    body = f"""<main>
<h1>{E(r["title"])}</h1>
<p class="lede">{E(r.get("lede", ""))}</p>
<p class="headline">{E(r.get("headline", ""))}</p>
{"".join(secs)}
{cav}
<footer>对标账号规律汇总 · 生成于 {E(r.get("generated_at", ""))}</footer>
</main>"""
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title or r["title"])}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;600&family=Noto+Serif+SC:wght@700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>{body}</body></html>"""


def render(r, title):
    if "account" not in r:
        return render_summary(r, title)
    a = r["account"]
    name = E(a["name"])
    h1 = f'<a href="{E(a["url"])}" target="_blank" rel="noopener">{name}</a>' if a.get("url") else name
    facts = [("粉丝", fmt_n(a.get("followers"))), ("获赞", fmt_n(a.get("total_likes"))), ("作品", a.get("total_works")),
             ("本次抓取", f'{a.get("crawled")} 条'), ("覆盖", a.get("span")), ("平时一条约", f'{fmt_n(a.get("median_likes"))} 赞'),
             ("爆款", f'{len(r.get("bursts", []))} 条'), ("IP", a.get("ip"))]
    fx = "".join(f"<span>{E(k)} <b class=\"num\">{E(v)}</b></span>" for k, v in facts if v not in (None, "", "None 条"))
    bl = "".join(
        f'<li><span class="lk num">{fmt_n(b["likes"])}<small>赞</small></span>'
        f'<a href="{E(b.get("url"))}" target="_blank" rel="noopener">{E(b["title"])}</a><time class="num">{E(b.get("date", ""))}</time></li>'
        for b in r.get("bursts", []))
    secs = []
    for s in r.get("sections", []):
        concl = f'<p class="concl">{E(s["conclusion"])}</p>' if s.get("conclusion") else ""
        secs.append(f'<h2>{E(s["title"])}</h2>{concl}' + "".join(block(b) for b in s.get("blocks", [])))
    cav = ('<div class="caveats"><h3>口径与局限</h3><ul class="b">' + "".join(f"<li>{E(c)}</li>" for c in r.get("caveats", [])) + "</ul></div>") if r.get("caveats") else ""
    body = f"""<main>
<h1>{h1}</h1>
<p class="bio">{E(a.get("bio", ""))}</p>
<div class="facts">{fx}</div>
<p class="headline">{E(r.get("headline", ""))}</p>
<p class="rule">{E(a.get("burst_rule", ""))}</p>
<ol class="blist">{bl}</ol>
{"".join(secs)}
{cav}
<footer>对标账号拆解报告 · 生成于 {E(r.get("generated_at", ""))}</footer>
</main>"""
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title or a["name"] + " 拆解报告")}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;600&family=Noto+Serif+SC:wght@700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>{body}</body></html>"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title")
    ap.add_argument("--facts", help="bench.py 生成的 facts.json：提供账号信息、爆款清单和 {type:fact,key:...} 数字块")
    a = ap.parse_args()
    r = json.load(open(a.report, encoding="utf-8"))
    if a.facts:
        FACTS.update(json.load(open(a.facts, encoding="utf-8")))
        if "account" in FACTS and "title" not in r:
            r["account"] = {**FACTS["account"], **r.get("account", {})}
            r.setdefault("bursts", FACTS.get("bursts", []))
        r.setdefault("generated_at", __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"))
    open(a.out, "w", encoding="utf-8").write(render(r, a.title))
    print(f"[account_report] → {a.out}")


if __name__ == "__main__":
    main()
