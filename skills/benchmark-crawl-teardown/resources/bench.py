#!/usr/bin/env python3
"""对标账号调研命令行（只用标准库，Python 3.9+）。数字全部由本脚本计算，智能体只负责分类和写分析。

账号库（默认 ~/对标账号库，可用 init --home 改）：
  accounts/<主页ID>/profile.json  labels.json  followers.csv
  accounts/<主页ID>/runs/<时间>/videos.json meta.json pairs.json comments.json transcripts/ facts.json report.json report.html
  summaries/<时间>/facts.json summary.json summary.html reports/<账号>.html

命令（典型顺序）：
  init      [--home DIR] [--mediacrawler DIR] [--whisper-python PY]   首次配置
  collect   链接或主页ID... --window 60|30|7|all                      抓作品（MediaCrawler 对标模式），每号建一次 run
  prepare   ID [--max-bursts 8]                                       找爆款、配同号对照 → pairs.json
  comments  ID                                                        抓爆款+对照的前 30 条评论，顺带刷新视频地址
  transcribe ID                                                       转写爆款+对照口播（在 comments 之后跑，地址不会过期）
  plays     ID                                                        （可选）补抓播放数，每条 3 秒
  brief     ID                                                        生成 brief.md：全部作品数据、待分类清单、对照组、评论摘要
  facts     ID                                                        按 labels.json 计算报告用的全部表格（含与上次的对比）→ facts.json
  render    ID                                                        report.json + facts.json → report.html
  summarize ID... [--name-keyword AI]                                 跨账号统计 → summaries/<时间>/facts.json
  render-summary 汇总目录                                             summary.json + facts.json → summary.html（附各号报告）
  list                                                                列出账号库
"""
import argparse, csv, datetime as dt, glob, json, os, re, shutil, statistics as st, subprocess, sys, urllib.request
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.expanduser("~/.config/benchmark-viral-research/config.json")
TAX = json.load(open(os.path.join(HERE, "taxonomy.json"), encoding="utf-8"))
SEC = re.compile(r"MS4wLjABAAAA[\w-]+")
NOW = lambda: dt.datetime.now().strftime("%Y%m%d-%H%M")
P = lambda x: f"{x:.0%}"


# ---------------- 配置与路径 ----------------
def cfg():
    if not os.path.exists(CFG_PATH):
        sys.exit("[bench] 还没配置：先运行 bench.py init --mediacrawler <MediaCrawler 目录>")
    return json.load(open(CFG_PATH, encoding="utf-8"))


def acc_dir(uid):
    return os.path.join(cfg()["home"], "accounts", uid)


def runs(uid):
    return sorted(glob.glob(os.path.join(acc_dir(uid), "runs", "*")))


def latest(uid, back=0):
    r = runs(uid)
    if len(r) <= back:
        sys.exit(f"[bench] {uid} 没有{'上一次' if back else ''}采集记录")
    return r[-1 - back]


def jload(p, default=None):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def jsave(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(obj, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def find_uid(x):
    """主页ID / 主页链接 / 账号名 → 主页ID"""
    m = SEC.search(x)
    if m:
        return m.group(0)
    for p in glob.glob(os.path.join(cfg()["home"], "accounts", "*", "profile.json")):
        if jload(p, {}).get("name") == x:
            return os.path.basename(os.path.dirname(p))
    sys.exit(f"[bench] 认不出账号：{x}（给主页链接、主页ID，或账号库里已有的账号名）")


def resolve(link):
    m = SEC.search(link)
    if m:
        return m.group(0)
    u = re.search(r"https?://v\.douyin\.com/[\w-]+/?", link)
    if not u:
        sys.exit(f"[bench] 不是抖音主页链接：{link[:60]}")
    req = urllib.request.Request(u.group(0), headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"})

    class NoRedir(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None
    try:
        urllib.request.build_opener(NoRedir()).open(req, timeout=15)
    except urllib.error.HTTPError as e:
        m = SEC.search(e.headers.get("Location", ""))
        if m:
            return m.group(0)
    sys.exit(f"[bench] 短链没解析出主页：{u.group(0)}（是不是视频链接？请给主页分享链接）")


def mc_env():
    e = dict(os.environ)
    for k in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        e.pop(k, None)
    return e


def mc_run(args, out_dir, extra_env=None):
    c = cfg()
    mc = c["mediacrawler"]
    py = os.path.join(mc, ".venv", "bin", "python")
    if not open(os.path.join(mc, "config", "dy_config.py"), encoding="utf-8").read().count("DY_BENCHMARK_MODE"):
        sys.exit(f"[bench] MediaCrawler 还没打对标补丁：在 {mc} 里 git apply {os.path.join(HERE, 'mediacrawler-benchmark.patch')}（先征得用户同意）")
    env = mc_env()
    env.update(extra_env or {})
    os.makedirs(out_dir, exist_ok=True)
    log = os.path.join(out_dir, "crawl.log")
    cmd = [py, "main.py", "--platform", "dy", "--lt", "qrcode"] + args + ["--save_data_option", "jsonl", "--save_data_path", out_dir]
    print(f"[bench] 运行 MediaCrawler（浏览器窗口出现二维码时请用户扫码；日志 {log}）", flush=True)
    with open(log, "w") as f:
        rc = subprocess.call(cmd, cwd=mc, env=env, stdout=f, stderr=subprocess.STDOUT)
    txt = open(log, encoding="utf-8", errors="replace").read()
    if "ConnectError" in txt or rc != 0:
        print(f"[bench] ⚠ MediaCrawler 有报错（退出码 {rc}）。常见原因是同时有大文件在下载，等其它任务结束后重跑这一步。", flush=True)
    return txt


# ---------------- 数据整理 ----------------
def headline(title):
    """抖音的「标题」字段是整段文案：只取第一句（去话题标签），用于标题写法统计"""
    x = re.split(r"#", title or "")[0].strip()
    t = re.split(r"\s+", x)
    out, i = t[0], 1
    while len(out) < 10 and i < len(t):
        out += " " + t[i]
        i += 1
    return out


def norm(d):
    ts = int(d["create_time"])
    return {"id": d["aweme_id"], "title": (d.get("title") or "").strip(), "headline": headline(d.get("title")),
            "ts": ts, "date": dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d"), "hour": dt.datetime.fromtimestamp(ts).hour,
            "likes": int(d.get("liked_count") or 0), "collects": int(d.get("collected_count") or 0),
            "comments": int(d.get("comment_count") or 0), "shares": int(d.get("share_count") or 0),
            "duration_s": round(int(d.get("duration") or 0) / 1000, 1), "is_top": int(d.get("is_top") or 0),
            "form": "图文" if str(d.get("aweme_type")) in ("2", "68", "150") else "视频",
            "url": d.get("aweme_url") or f"https://www.douyin.com/video/{d['aweme_id']}", "video_url": d.get("video_download_url", "")}


def load_run(run):
    vids = jload(os.path.join(run, "videos.json"), [])
    meta = jload(os.path.join(run, "meta.json"), {})
    return vids, meta


def judged(vids, min_posts=5, mult=3):
    """剔除早于连续采集范围的老置顶 → 中位数 → 爆款"""
    normal = [v for v in vids if not v["is_top"]]
    oldest = min((v["ts"] for v in normal), default=0)
    dropped = [v for v in vids if v["is_top"] and v["ts"] < oldest]
    rows = [dict(v) for v in vids if v not in dropped]
    med = st.median([v["likes"] for v in rows]) if rows else 0
    ok = len(rows) >= min_posts and med > 0
    for v in rows:
        v["mult"] = v["likes"] / med if med else 0
        v["burst"] = bool(ok and v["mult"] >= mult)
    return rows, med, dropped, ok


# ---------------- 命令 ----------------
def c_init(a):
    old = jload(CFG_PATH, {})
    c = {"home": os.path.expanduser(a.home or old.get("home") or "~/对标账号库"),
         "mediacrawler": os.path.expanduser(a.mediacrawler or old.get("mediacrawler") or ""),
         "whisper_python": a.whisper_python or old.get("whisper_python") or sys.executable}
    if not c["mediacrawler"] or not os.path.exists(os.path.join(c["mediacrawler"], "main.py")):
        sys.exit("[bench] 需要 --mediacrawler 指向 MediaCrawler 根目录")
    os.makedirs(os.path.join(c["home"], "accounts"), exist_ok=True)
    jsave(CFG_PATH, c)
    print(json.dumps(c, ensure_ascii=False, indent=1))


def c_collect(a):
    uids = [resolve(x) for x in a.links]
    since = "" if a.window == "all" else (dt.date.today() - dt.timedelta(days=int(a.window))).isoformat()
    tmp = os.path.join(cfg()["home"], "_crawl", NOW())
    mc_run(["--type", "creator", "--creator_id", ",".join(uids), "--get_comment", "no"], tmp,
           {"DY_BENCHMARK_MODE": "1", "DY_CREATOR_SINCE": since, "DY_CREATOR_MAX_POSTS": str(a.max_posts)})
    raw = defaultdict(dict)
    for f in glob.glob(os.path.join(tmp, "douyin", "jsonl", "creator_contents_*.jsonl")):
        for line in open(f, encoding="utf-8"):
            d = json.loads(line)
            raw[d.get("source_creator", "")][d["aweme_id"]] = d
    log = open(os.path.join(tmp, "crawl.log"), encoding="utf-8", errors="replace").read()
    ts = NOW()
    for uid in uids:
        ds = list(raw.get(uid, {}).values())
        st_m = re.search(rf"BENCHMARK sec_user_id:{re.escape(uid)} total=(\d+) status=(\w+)", log)
        if not ds:
            print(f"[bench] ⚠ {uid} 没抓到作品（{'状态 ' + st_m.group(2) if st_m else '日志里没有记录，可能中途报错'}）")
            continue
        d0 = ds[0]
        prof = jload(os.path.join(acc_dir(uid), "profile.json"), {})
        prof.update({"uid": uid, "url": f"https://www.douyin.com/user/{uid}",
                     "name": d0.get("source_nickname") or prof.get("name") or d0.get("nickname"),
                     "followers": d0.get("source_follower_count"), "total_likes": d0.get("source_total_favorited"),
                     "works": d0.get("source_aweme_count"), "bio": d0.get("source_signature") or prof.get("bio", ""),
                     "ip": d0.get("source_ip") or prof.get("ip", ""), "updated": ts})
        jsave(os.path.join(acc_dir(uid), "profile.json"), prof)
        fp = os.path.join(acc_dir(uid), "followers.csv")
        new = not os.path.exists(fp)
        with open(fp, "a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time", "followers"])
            w.writerow([ts, prof["followers"]])
        run = os.path.join(acc_dir(uid), "runs", ts)
        vids = sorted([norm(d) for d in ds], key=lambda v: -v["ts"])
        jsave(os.path.join(run, "videos.json"), vids)
        jsave(os.path.join(run, "meta.json"), {"window": a.window, "since": since, "crawled_at": ts, "n": len(vids),
                                               "status": st_m.group(2) if st_m else "unknown"})
        print(f"[bench] ✓ {prof['name']}（{uid[:16]}…）{len(vids)} 条 → {run}")
        if st_m and st_m.group(2) == "hit_max_posts":
            print(f"[bench]   ⚠ 触到上限 {a.max_posts} 条，没取全；需要更多就加 --max-posts")


def c_prepare(a):
    uid = find_uid(a.id)
    run = latest(uid)
    vids, meta = load_run(run)
    rows, med, dropped, ok = judged(vids)
    if not ok:
        sys.exit(f"[bench] 作品不足 5 条或中位数为 0，不判定爆款（{len(rows)} 条）")
    bursts = sorted([v for v in rows if v["burst"]], key=lambda v: -v["mult"])[:a.max_bursts]
    used, pairs = set(), []
    for b in bursts:
        cand = [v for v in rows if not v["burst"] and v["id"] not in used]
        cand.sort(key=lambda v: abs(v["ts"] - b["ts"]))
        c = cand[0] if cand else None
        if c:
            used.add(c["id"])
        pairs.append({"burst": b["id"], "control": c["id"] if c else None,
                      "note": "对照按时间最近自动选；如有同主题的普通视频更合适，可直接改 control"})
    jsave(os.path.join(run, "pairs.json"), pairs)
    print(f"[bench] 平时一条 {med:.0f} 赞，爆款 {sum(v['burst'] for v in rows)} 条（取前 {len(bursts)} 条配对照）→ {run}/pairs.json")
    for p in pairs:
        b = next(v for v in rows if v["id"] == p["burst"])
        c = next((v for v in rows if v["id"] == p["control"]), None)
        print(f"  爆款 {b['likes']:>7} 赞 {b['mult']:.1f}倍 {b['headline'][:24]}  ↔  对照 {c['likes'] if c else '-'} 赞 {c['headline'][:24] if c else ''}")


def pair_ids(run):
    ids = []
    for p in jload(os.path.join(run, "pairs.json"), []):
        ids += [x for x in (p["burst"], p["control"]) if x]
    if not ids:
        sys.exit("[bench] 先运行 prepare")
    return ids


def c_comments(a):
    uid = find_uid(a.id)
    run = latest(uid)
    ids = pair_ids(run)
    tmp = os.path.join(run, "_comments")
    mc_run(["--type", "detail", "--specified_id", ",".join(ids), "--get_comment", "yes", "--get_sub_comment", "no",
            "--max_comments_count_singlenotes", str(a.n)], tmp)
    cs = [json.loads(l) for f in glob.glob(os.path.join(tmp, "douyin", "jsonl", "*comments*.jsonl")) for l in open(f, encoding="utf-8")]
    fresh = {}
    for f in glob.glob(os.path.join(tmp, "douyin", "jsonl", "*contents*.jsonl")):
        for l in open(f, encoding="utf-8"):
            d = json.loads(l)
            fresh[d["aweme_id"]] = d
    cs = [{"video_id": c["aweme_id"], "text": c.get("content", ""), "likes": int(c.get("like_count") or 0),
           "author_hash": c.get("creator_hash"), "replies": int(c.get("sub_comment_count") or 0)} for c in cs]
    owner = {d.get("creator_hash") for d in fresh.values()}
    for c in cs:
        c["by_author"] = c["author_hash"] in owner
    jsave(os.path.join(run, "comments.json"), cs)
    vids, _ = load_run(run)
    for v in vids:
        if v["id"] in fresh:
            v["video_url"] = fresh[v["id"]].get("video_download_url") or v["video_url"]
            for k_src, k in (("liked_count", "likes"), ("collected_count", "collects"), ("comment_count", "comments"), ("share_count", "shares")):
                if fresh[v["id"]].get(k_src) not in (None, ""):
                    v[k] = int(fresh[v["id"]][k_src])
    jsave(os.path.join(run, "videos.json"), vids)
    got = Counter(c["video_id"] for c in cs)
    print(f"[bench] 评论 {len(cs)} 条，覆盖 {len(got)}/{len(ids)} 条视频；作者发言 {sum(c['by_author'] for c in cs)} 条 → {run}/comments.json")
    if len(got) < len(ids):
        print("[bench] ⚠ 有视频没抓到评论（评论关闭或网络出错），可重跑这一步")


def c_transcribe(a):
    uid = find_uid(a.id)
    run = latest(uid)
    ids = pair_ids(run)
    vids, _ = load_run(run)
    by = {v["id"]: v for v in vids}
    out = os.path.join(run, "transcripts")
    os.makedirs(out, exist_ok=True)
    ml = os.path.join(out, "media_list.csv")
    with open(ml, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["video_id", "media"])
        for i in ids:
            if not os.path.exists(os.path.join(out, f"{i}.txt")):
                w.writerow([i, by[i]["video_url"]])
    env = mc_env()
    env.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    rc = subprocess.call([cfg()["whisper_python"], os.path.join(HERE, "transcribe.py"), ml, "--out", out, "--hook-seconds", "15"], env=env)
    done = [i for i in ids if os.path.exists(os.path.join(out, f"{i}.txt"))]
    print(f"[bench] 转写完成 {len(done)}/{len(ids)} 条 → {out}")
    if len(done) < len(ids):
        print("[bench] ⚠ 有视频没转写成功：视频地址可能过期，先重跑 comments 刷新地址再转写")


def c_plays(a):
    """可选：逐条读抖音精选公开页的播放数（不登录，每条间隔 ≥3 秒，遇到验证码整批停止）"""
    sys.path.insert(0, HERE)
    import play_counts
    uid = find_uid(a.id)
    run = latest(uid)
    vids, _ = load_run(run)
    ok = 0
    for v in vids:
        if v.get("plays") or v["form"] == "图文":
            continue
        r = play_counts.fetch_play(v["id"])
        if r and r.get("play") is not None:
            v["plays"] = r["play"]
            ok += 1
        if play_counts._BLOCKED.is_set():
            print("[bench] ⚠ 抖音出现验证码或拦截，已停止；已取到的照常保存")
            break
    jsave(os.path.join(run, "videos.json"), vids)
    print(f"[bench] 播放数新取到 {ok} 条，共 {sum(1 for v in vids if v.get('plays'))}/{len(vids)} 条有播放数")


def c_brief(a):
    uid = find_uid(a.id)
    run = latest(uid)
    vids, meta = load_run(run)
    rows, med, dropped, ok = judged(vids)
    labels = jload(os.path.join(acc_dir(uid), "labels.json"), {})
    prof = jload(os.path.join(acc_dir(uid), "profile.json"), {})
    L = [f"# {prof.get('name')} 数据简报", "", f"- 采集：{meta.get('crawled_at')}，时间范围 {meta.get('window')}，{len(rows)} 条（剔除老置顶 {len(dropped)} 条）",
         f"- 平时一条 {med:.0f} 赞；爆款 {sum(v['burst'] for v in rows)} 条（≥3 倍）", f"- 主页：{prof.get('bio', '')}", "",
         "## 全部作品（id 后 6 位 | 日期 | 点赞 | 倍数 | 时长 | 分类 | 文案）"]
    for v in sorted(rows, key=lambda v: v["ts"]):
        L.append(f"- {v['id'][-6:]} | {v['date']} {v['hour']:02d}点 | {v['likes']}{('（播放 ' + str(v['plays']) + '）') if v.get('plays') else ''} | {v['mult']:.1f}{' 爆' if v['burst'] else ''} | {v['duration_s'] / 60:.1f}分 | {labels.get(v['id'], '待分类')} | {v['title'][:90].replace(chr(10), ' ')}")
    L += ["", "## 分类（写进 accounts/<ID>/labels.json，键是完整视频 id，值是下列代码之一）"] + [f"- {k}：{x['name']}——{x['desc']}" for k, x in TAX["categories"].items()]
    todo = [v["id"] for v in rows if v["id"] not in labels]
    L += ["", f"待分类 {len(todo)} 条：", json.dumps({i: "" for i in todo}, ensure_ascii=False)]
    cs = jload(os.path.join(run, "comments.json"), [])
    by_v = defaultdict(list)
    for c in cs:
        by_v[c["video_id"]].append(c)
    L += ["", "## 对照组（转写在 transcripts/<id>.txt）"]
    for p in jload(os.path.join(run, "pairs.json"), []):
        for role, i in (("爆款", p["burst"]), ("对照", p["control"])):
            if not i:
                continue
            v = next((x for x in rows if x["id"] == i), None)
            if not v:
                continue
            tp = os.path.join(run, "transcripts", f"{i}.txt")
            L.append(f"### {role} {v['headline']}（{v['likes']} 赞，{v['mult']:.1f} 倍，{v['duration_s'] / 60:.1f} 分钟，{v['date']}）")
            L.append(f"- 转写：{'有' if os.path.exists(tp) else '无'}；评论 {len(by_v.get(i, []))} 条，高赞：")
            for c in sorted(by_v.get(i, []), key=lambda c: -c["likes"])[:6]:
                L.append(f"  - {c['likes']} 赞{'（作者）' if c['by_author'] else ''}：{c['text'][:80].replace(chr(10), ' ')}")
    open(os.path.join(run, "brief.md"), "w", encoding="utf-8").write("\n".join(L))
    print(f"[bench] → {run}/brief.md（待分类 {len(todo)} 条）")


# ---------------- 统计表 ----------------
def grp(rows):
    b = sum(v["burst"] for v in rows)
    return {"n": len(rows), "b": b, "r": b / len(rows) if rows else 0, "med": st.median([v["likes"] for v in rows]) if rows else 0}


def bins_table(rows, edges, key, label="时长"):
    out = []
    for lo, hi, lab in edges:
        g = grp([v for v in rows if lo <= key(v) < hi])
        if g["n"]:
            out.append([lab, g["n"], g["b"], P(g["r"]), f"{g['med']:.0f}"])
    return {"type": "table", "cols": [label, "条数", "爆款", "爆款率", "平时点赞（中位）"], "num_cols": [1, 2, 3, 4], "rows": out}


DUR = [(0, 60, "1 分钟以内"), (60, 180, "1–3 分钟"), (180, 300, "3–5 分钟"), (300, 480, "5–8 分钟"), (480, 720, "8–12 分钟"), (720, 1200, "12–20 分钟"), (1200, 1e9, "20 分钟以上")]
SLOT = [(0, 7, "0–7 点"), (7, 12, "7–12 点"), (12, 17, "12–17 点"), (17, 20, "17–20 点"), (20, 24, "20–24 点")]


def cat_name(c):
    return TAX["categories"].get(c, {}).get("name", c or "未分类")


def account_facts(uid, run):
    vids, meta = load_run(run)
    rows, med, dropped, ok = judged(vids)
    labels = jload(os.path.join(acc_dir(uid), "labels.json"), {})
    for v in rows:
        v["cat"] = labels.get(v["id"], "")
    prof = jload(os.path.join(acc_dir(uid), "profile.json"), {})
    span_days = max((max(v["ts"] for v in rows) - min(v["ts"] for v in rows)) / 86400, 1) if rows else 1
    blocks = {}
    # 分类
    cats = defaultdict(list)
    for v in rows:
        cats[v["cat"]].append(v)
    crow = []
    for c, vs in sorted(cats.items(), key=lambda x: -grp(x[1])["r"]):
        g = grp(vs)
        crow.append([cat_name(c), g["n"], f"{g['b']} 条（{P(g['r'])}）" if g["b"] else "0", f"{g['med']:.0f}",
                     f"{sum(v['collects'] for v in vs) / max(sum(v['likes'] for v in vs), 1):.2f}", f"{st.median([v['duration_s'] for v in vs]) / 60:.1f} 分钟"])
    blocks["category_table"] = {"type": "table", "cols": ["类别", "条数", "爆款", "平时点赞（中位）", "收藏/赞", "时长（中位）"], "num_cols": [1, 3, 4], "rows": crow,
                                "note": "分类由智能体按标题和口播判断。" + (f"还有 {len(cats.get('', []))} 条没分类。" if cats.get("") else "")}
    blocks["duration_table"] = bins_table(rows, DUR, lambda v: v["duration_s"])
    blocks["slot_table"] = bins_table(rows, SLOT, lambda v: v["hour"], "发布时段")
    trows = []
    for k, p in TAX["title_patterns"]:
        vs = [v for v in rows if re.search(p, v["headline"].lower())]
        if vs:
            g = grp(vs)
            trows.append([k, g["n"], f"{g['b']} 条", f"{g['med']:.0f}"])
    blocks["title_table"] = {"type": "table", "cols": ["标题第一句里有", "条数", "爆款", "平时点赞（中位）"], "num_cols": [1, 2, 3], "rows": trows,
                             "note": "只看文案第一句（去掉话题标签和正文）。"}
    mon = defaultdict(list)
    for v in rows:
        mon[v["date"][:7]].append(v)
    ms = sorted(mon.items())
    blocks["month_chart"] = {"type": "months", "unit": "%", "aria": "每月爆款率",
                             "series": [{"label": f"{k[5:]}月", "value": grp(vs)["r"], "text": f"{grp(vs)['b']}/{len(vs)} 条"} for k, vs in ms],
                             "note": "每月爆款率 = 当月爆款 / 当月作品。单月条数少时波动大，看趋势不看单月。"}
    blocks["month_table"] = {"type": "table", "cols": ["月份", "作品", "爆款", "平时点赞（中位）", "主要类别"], "num_cols": [1, 2, 3],
                             "rows": [[f"{k[:4]}-{k[5:]}", len(vs), grp(vs)["b"], f"{grp(vs)['med']:.0f}", "、".join(cat_name(c) for c, _ in Counter(v["cat"] for v in vs if v["cat"]).most_common(2))] for k, vs in ms]}
    # 评论
    cs = jload(os.path.join(run, "comments.json"), [])
    if cs:
        crs = []
        for k, p in TAX["comment_themes"]:
            h = sum(1 for c in cs if re.search(p, c["text"]))
            crs.append([k, h, P(h / len(cs))])
        crs.sort(key=lambda r: -r[1])
        blocks["comment_table"] = {"type": "table", "cols": ["评论在说什么", "条数", "占比"], "num_cols": [1, 2], "rows": crs,
                                   "note": f"样本：{len(set(c['video_id'] for c in cs))} 条视频各取前若干条一级评论，共 {len(cs)} 条，按关键词归类，一条可属于多类。作者发言 {sum(c['by_author'] for c in cs)} 条。"}
    bursts = [{"title": v["headline"][:60], "url": v["url"], "likes": v["likes"], "date": v["date"], "duration_s": v["duration_s"], "plays": v.get("plays")}
              for v in sorted([v for v in rows if v["burst"]], key=lambda v: -v["likes"])]
    f = {"uid": uid, "run": os.path.basename(run), "window": meta.get("window"),
         "account": {"name": prof.get("name"), "url": prof.get("url"), "followers": prof.get("followers"), "total_likes": prof.get("total_likes"),
                     "total_works": prof.get("works"), "ip": prof.get("ip"), "bio": prof.get("bio"), "crawled": len(rows),
                     "span": f"{min(v['date'] for v in rows)} 至 {max(v['date'] for v in rows)}" if rows else "",
                     "median_likes": med,
                     "burst_rule": f"爆款判断：点赞达到这个号平时一条（{len(rows)} 条的中位数 {med:.0f} 赞）的 3 倍以上。{len(rows)} 条里有 {len(bursts)} 条。" + (f"已剔除 {len(dropped)} 条采集范围以外的老置顶。" if dropped else "")
                     if ok else "作品不足 5 条，不判定爆款。"},
         "bursts": bursts,
         "numbers": {"posts_per_week": round(len(rows) / (span_days / 7), 2), "collect_per_like": round(sum(v["collects"] for v in rows) / max(sum(v["likes"] for v in rows), 1), 2),
                     "share_per_like": round(sum(v["shares"] for v in rows) / max(sum(v["likes"] for v in rows), 1), 2),
                     "median_per_follower": round(med / prof["followers"], 4) if prof.get("followers") else None,
                     "unlabeled": len(cats.get("", []))},
         "blocks": blocks}
    return f, rows


def c_facts(a):
    uid = find_uid(a.id)
    run = latest(uid)
    f, rows = account_facts(uid, run)
    if len(runs(uid)) >= 2:
        prev = latest(uid, 1)
        pf, prows = account_facts(uid, prev)
        f["blocks"]["compare_table"] = compare_block(uid, f, pf, rows, prows)
        f["compare"] = {"previous_run": os.path.basename(prev)}
    jsave(os.path.join(run, "facts.json"), f)
    print(f"[bench] → {run}/facts.json；可用的数字块：{', '.join(f['blocks'])}；未分类 {f['numbers']['unlabeled']} 条")


def compare_block(uid, f, pf, rows, prows):
    fol = list(csv.DictReader(open(os.path.join(acc_dir(uid), "followers.csv"), encoding="utf-8")))
    r = []
    if len(fol) >= 2 and fol[-1]["followers"] and fol[-2]["followers"]:
        t1, t0 = dt.datetime.strptime(fol[-1]["time"], "%Y%m%d-%H%M"), dt.datetime.strptime(fol[-2]["time"], "%Y%m%d-%H%M")
        d = int(fol[-1]["followers"]) - int(fol[-2]["followers"])
        days = max((t1 - t0).total_seconds() / 86400, 0.01)
        per = f"{d / days:+.0f}/天，" if days >= 1 else f"间隔 {days * 24:.0f} 小时，"
        r.append(["粉丝", fol[-2]["followers"], fol[-1]["followers"], f"{d:+d}（{per}{d / int(fol[-2]['followers']):+.1%}）" + ("；间隔不足 7 天，涨粉结论先别用" if days < 7 else "")])
    old = {v["id"] for v in prows}
    new = [v for v in rows if v["id"] not in old]
    r.append(["新发作品", "—", len(new), f"其中爆款 {sum(v['burst'] for v in new)} 条" if new else "无"])
    r.append(["平时一条赞", f"{pf['account']['median_likes']:.0f}", f"{f['account']['median_likes']:.0f}", ""])
    g0, g1 = grp(prows), grp(rows)
    r.append(["爆款率", P(g0["r"]), P(g1["r"]), ""])
    c0, c1 = defaultdict(list), defaultdict(list)
    for v in prows:
        c0[v.get("cat", "")].append(v)
    for v in rows:
        c1[v.get("cat", "")].append(v)
    for c in sorted(set(c0) | set(c1)):
        if not c:
            continue
        a0, a1 = grp(c0.get(c, [])), grp(c1.get(c, []))
        r.append([f"「{cat_name(c)}」爆款率", f"{P(a0['r'])}（{a0['b']}/{a0['n']}）" if a0["n"] else "—", f"{P(a1['r'])}（{a1['b']}/{a1['n']}）" if a1["n"] else "—",
                  verdict(a0, a1)])
    return {"type": "table", "cols": ["", "上次", "这次", "变化"], "rows": r,
            "note": f"上次采集 {pf['run']}（{pf.get('window')}），这次 {f['run']}（{f.get('window')}）。两次时间范围不同时，比较要打折。"}


def verdict(a0, a1, base0=None, base1=None):
    if not a0["n"] and a1["n"]:
        return "新出现"
    if a0["n"] and not a1["n"]:
        return "这次没有"
    if a0["n"] < 3 or a1["n"] < 3:
        return "样本太少"
    d = a1["r"] - a0["r"]
    return "仍成立" if abs(d) < 0.15 else ("变好" if d > 0 else "变差")


def c_render(a):
    uid = find_uid(a.id)
    run = latest(uid)
    rep = os.path.join(run, "report.json")
    if not os.path.exists(rep):
        sys.exit(f"[bench] 先写 {rep}（报告正文），再渲染")
    subprocess.check_call([sys.executable, os.path.join(HERE, "account_report.py"), "--report", rep, "--facts", os.path.join(run, "facts.json"), "--out", os.path.join(run, "report.html")])
    print(f"[bench] 报告 → {os.path.join(run, 'report.html')}")


# ---------------- 汇总 ----------------
def c_summarize(a):
    uids = [find_uid(x) for x in a.ids]
    allrows, accs, prevrows = [], [], []
    for uid in uids:
        run = latest(uid)
        f, rows = account_facts(uid, run)
        prof = jload(os.path.join(acc_dir(uid), "profile.json"), {})
        for v in rows:
            v["acc"] = prof.get("name")
        allrows += rows
        has_rep = os.path.exists(os.path.join(run, "report.html"))
        g = grp(rows)
        accs.append([prof.get("name"), fmtn(prof.get("followers")), len(rows), f"{min(v['date'] for v in rows)[5:]}–{max(v['date'] for v in rows)[5:]}",
                     f"{f['numbers']['posts_per_week']:.1f}", f"{f['account']['median_likes']:.0f}",
                     f"{f['numbers']['median_per_follower']:.1%}" if f["numbers"]["median_per_follower"] else "—", g["b"], P(g["r"]), "深拆" if has_rep else "只看数据"])
        if len(runs(uid)) >= 2:
            pf, prows = account_facts(uid, latest(uid, 1))
            for v in prows:
                v["acc"] = prof.get("name")
            prevrows += prows
        if f["numbers"]["unlabeled"]:
            print(f"[bench] ⚠ {prof.get('name')} 还有 {f['numbers']['unlabeled']} 条未分类，先补 labels.json（brief 里有清单）")
    N, NB = len(allrows), sum(v["burst"] for v in allrows)
    base = NB / N if N else 0
    blocks = {"accounts_table": {"type": "table", "cols": ["账号", "粉丝", "作品", "覆盖", "每周条数", "平时一条赞", "平时赞/粉丝", "爆款", "爆款率", "拆解"],
                                 "num_cols": [2, 4, 5, 6, 7, 8], "rows": accs, "nowrap": True,
                                 "note": "各号的时间范围不同时，按月份、按风向的结论要打折。"}}

    def gtable(name, groups, first_col):
        out = []
        for k, vs in groups:
            if not vs:
                continue
            g = grp(vs)
            by = Counter(v["acc"] for v in vs if v["burst"])
            top = by.most_common(1)[0] if by else ("", 0)
            conc = f"{top[0]} 占 {top[1]}/{g['b']}" if g["b"] >= 3 and top[1] / g["b"] >= 0.5 else ""
            out.append([k, g["n"], g["b"], P(g["r"]), len({v["acc"] for v in vs}), len(by), conc])
            if conc:
                rest = grp([v for v in vs if v["acc"] != top[0]])
                if rest["n"]:
                    out.append([f"　└ 去掉{top[0]}", rest["n"], rest["b"], P(rest["r"]), len({v["acc"] for v in vs}) - 1, len(by) - 1, ""])
        return {"type": "table", "cols": [first_col, "条数", "爆款", "爆款率", "几个号", "几个号出过爆款", "集中提醒"], "num_cols": [1, 2, 3], "rows": out,
                "note": f"全样本 {N} 条、{NB} 条爆款，平均爆款率 {P(base)}。某类爆款一半以上来自同一个号时，下一行给出去掉它之后的数字。"}
    cats = defaultdict(list)
    for v in allrows:
        cats[v["cat"]].append(v)
    blocks["category_table"] = gtable("类别", sorted([(cat_name(c), vs) for c, vs in cats.items()], key=lambda x: -grp(x[1])["r"]), "类别")
    blocks["title_table"] = gtable("标题", [(k, [v for v in allrows if re.search(p, v["headline"].lower())]) for k, p in TAX["title_patterns"]], "标题第一句里有")
    blocks["duration_table"] = gtable("时长", [(lab, [v for v in allrows if lo <= v["duration_s"] < hi]) for lo, hi, lab in DUR], "时长")
    blocks["slot_table"] = gtable("时段", [(lab, [v for v in allrows if lo <= v["hour"] < hi]) for lo, hi, lab in SLOT], "发布时段")
    # 题材风向：前半段 vs 后半段 + 最近 5 个月
    mid = sorted(v["ts"] for v in allrows)[len(allrows) // 2] if allrows else 0
    months = sorted({v["date"][:7] for v in allrows})[-5:]
    trows = []
    topics = TAX["topics"] + [[k, re.escape(k.lower())] for k in (a.topic or [])]
    for k, p in topics:
        vs = [v for v in allrows if re.search(p, v["headline"].lower())]
        if len(vs) < 3:
            continue
        e, l = grp([v for v in vs if v["ts"] < mid]), grp([v for v in vs if v["ts"] >= mid])
        trows.append([k, len(vs), P(grp(vs)["r"]), f"{e['b']}/{e['n']}" + (f"（{P(e['r'])}）" if e["n"] else ""), f"{l['b']}/{l['n']}" + (f"（{P(l['r'])}）" if l["n"] else "")]
                     + [(lambda g: f"{g['b']}/{g['n']}" if g["n"] else "—")(grp([v for v in vs if v["date"][:7] == m])) for m in months])
    midd = dt.datetime.fromtimestamp(mid).strftime("%m-%d") if mid else ""
    blocks["topic_table"] = {"type": "table", "cols": ["题材（标题第一句）", "条数", "爆款率", f"{midd} 前", f"{midd} 后"] + [f"{m[5:]}月" for m in months],
                             "num_cols": [1, 2], "rows": sorted(trows, key=lambda r: -r[1]), "nowrap": True,
                             "note": f"以全部作品的中间日期 {midd} 分前后两段；格子是「爆款/条数」。出现少于 3 次的题材不列。"}
    mon = defaultdict(list)
    for v in allrows:
        mon[v["date"][:7]].append(v)
    blocks["month_chart"] = {"type": "months", "unit": "%", "aria": "每月整体爆款率",
                             "series": [{"label": f"{k[5:]}月", "value": grp(vs)["r"], "text": f"{grp(vs)['b']}/{len(vs)}"} for k, vs in sorted(mon.items())],
                             "note": "每月整体爆款率；各号覆盖时间不同，早期月份可能只有少数号。"}
    if a.name_keyword:
        kw = a.name_keyword.lower()
        blocks["name_table"] = gtable("名字", [(f"名字带「{a.name_keyword}」", [v for v in allrows if kw in (v["acc"] or "").lower()]),
                                             (f"名字不带「{a.name_keyword}」", [v for v in allrows if kw not in (v["acc"] or "").lower()])], "账号名")
    if prevrows:
        pc = defaultdict(list)
        for v in prevrows:
            pc[v["cat"]].append(v)
        crow = []
        for c in sorted(set(pc) | set(cats)):
            if not c:
                continue
            a0, a1 = grp(pc.get(c, [])), grp(cats.get(c, []))
            crow.append([cat_name(c), f"{P(a0['r'])}（{a0['b']}/{a0['n']}）" if a0["n"] else "—", f"{P(a1['r'])}（{a1['b']}/{a1['n']}）" if a1["n"] else "—", verdict(a0, a1)])
        blocks["compare_table"] = {"type": "table", "cols": ["类别", "上次", "这次", "规律变化"], "rows": crow,
                                   "note": "上次 = 每个号上一次采集；只对比两次都抓过的号。"}
    out = os.path.join(cfg()["home"], "summaries", NOW())
    f = {"accounts": [{"uid": u, "name": jload(os.path.join(acc_dir(u), "profile.json"), {}).get("name"), "run": os.path.basename(latest(u))} for u in uids],
         "numbers": {"videos": N, "bursts": NB, "base_rate": round(base, 3), "accounts": len(uids)}, "blocks": blocks}
    jsave(os.path.join(out, "facts.json"), f)
    print(f"[bench] 汇总数字 → {out}/facts.json（{N} 条，{NB} 爆款，平均 {P(base)}）；数字块：{', '.join(blocks)}")


def c_render_summary(a):
    d = os.path.abspath(a.dir)
    f = jload(os.path.join(d, "facts.json"))
    s = os.path.join(d, "summary.json")
    if not os.path.exists(s):
        sys.exit(f"[bench] 先写 {s}")
    os.makedirs(os.path.join(d, "reports"), exist_ok=True)
    for x in f["accounts"]:
        src = os.path.join(acc_dir(x["uid"]), "runs", x["run"], "report.html")
        if os.path.exists(src):
            shutil.copy(src, os.path.join(d, "reports", f"{x['name']}.html"))
    subprocess.check_call([sys.executable, os.path.join(HERE, "account_report.py"), "--report", s, "--facts", os.path.join(d, "facts.json"), "--out", os.path.join(d, "summary.html")])
    print(f"[bench] 汇总 → {d}/summary.html（各号报告在 reports/）")


def c_list(a):
    for p in sorted(glob.glob(os.path.join(cfg()["home"], "accounts", "*", "profile.json"))):
        uid = os.path.basename(os.path.dirname(p))
        pr = jload(p, {})
        rs = runs(uid)
        rep = bool(rs) and os.path.exists(os.path.join(rs[-1], "report.html"))
        print(f"{pr.get('name')}\t{uid}\t采集 {len(rs)} 次，最近 {os.path.basename(rs[-1]) if rs else '-'}\t{'有报告' if rep else '无报告'}")


def fmtn(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    return f"{x / 10000:.1f}万" if x >= 10000 else f"{x:.0f}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("init"); p.add_argument("--home"); p.add_argument("--mediacrawler"); p.add_argument("--whisper-python"); p.set_defaults(fn=c_init)
    p = sp.add_parser("collect"); p.add_argument("links", nargs="+"); p.add_argument("--window", choices=["7", "30", "60", "all"], default="60"); p.add_argument("--max-posts", type=int, default=500); p.set_defaults(fn=c_collect)
    p = sp.add_parser("prepare"); p.add_argument("id"); p.add_argument("--max-bursts", type=int, default=8); p.set_defaults(fn=c_prepare)
    p = sp.add_parser("comments"); p.add_argument("id"); p.add_argument("--n", type=int, default=30); p.set_defaults(fn=c_comments)
    p = sp.add_parser("transcribe"); p.add_argument("id"); p.set_defaults(fn=c_transcribe)
    p = sp.add_parser("plays"); p.add_argument("id"); p.set_defaults(fn=c_plays)
    p = sp.add_parser("brief"); p.add_argument("id"); p.set_defaults(fn=c_brief)
    p = sp.add_parser("facts"); p.add_argument("id"); p.set_defaults(fn=c_facts)
    p = sp.add_parser("render"); p.add_argument("id"); p.set_defaults(fn=c_render)
    p = sp.add_parser("summarize"); p.add_argument("ids", nargs="+"); p.add_argument("--name-keyword"); p.add_argument("--topic", action="append"); p.set_defaults(fn=c_summarize)
    p = sp.add_parser("render-summary"); p.add_argument("dir"); p.set_defaults(fn=c_render_summary)
    p = sp.add_parser("list"); p.set_defaults(fn=c_list)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
