"""匿名读取抖音精选公开页的计数，不下载媒体、不运行网页脚本。

方法参考 ShareXtract (Apache-2.0) 的 douyin 适配器，独立实现为标准库模块。
https://github.com/wuaishare/sharextract/blob/9934bdd16f2804c3ee956569138f81313d01c8a5/sharextract/extractors/douyin.py
源自用户「导眼」项目的 play_counts.py（严格匹配 WatchAction、所有跳转逐次限速、异常返回 None），
去掉了导眼专用的夜间节流/停抓通知依赖，加了批量命令行（benchmark-crawl-teardown 用）。

批量用法（在 normalize.py 之后、analyze.py 之前）：
  python3 play_counts.py data/videos.csv [--cache data/plays.csv] [--limit N]
  - 逐条读取抖音精选公开页的播放数，串行、每次请求间隔 ≥3 秒、不登录、不带 Cookie、失败不重试；
  - 结果缓存到 data/plays.csv（video_id,plays,play_fetched_at），重跑只补没取到的；
  - 把 plays 列写回 videos.csv；遇到验证码 / 403 / 429 立即整批停止，已取到的照常写回。
  800 条约需 40 分钟。
"""
import contextlib
import datetime
from html.parser import HTMLParser
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import contextlib as _ctx


def verification_page(text):
    # 不因正文提到“验证码”或空响应就推断风控。
    title = re.search(r'<title[^>]*>(.*?)</title>', text, re.I | re.S)
    if title and re.match(r'\s*(?:验证码(?:中间页)?|安全验证|访问验证|captcha|security verification)(?=\s|[-_·|]|$)', title.group(1), re.I):
        return True
    return bool(re.search(r'<[^>]+(?:id|class)=["\'][^"\']*(?:captcha-verify-image|captcha_container|secsdk-captcha-drag-icon|verify-bar-code)', text, re.I))


BLOCK_REASON = []


def stop_douyin(reason):
    BLOCK_REASON.append(reason)

SOURCE = "抖音精选网页"
_INTERVAL = 3.0
_TIMEOUT = 15
_MAX_BYTES = 8 * 1024 * 1024
_NETWORK_LOCK = threading.Lock()
_last_finished = None
_BLOCKED = threading.Event()
REQUEST_EVENTS = []
_LAST_PAGE = threading.local()
REQUEST_GUARD = None

def network_slot(url):
    if REQUEST_GUARD is not None:
        return REQUEST_GUARD.slot(url)
    return contextlib.nullcontext()

_ID = re.compile(r"[0-9]{10,32}\Z")
_HOSTS = frozenset({"douyin.com", "www.douyin.com", "m.douyin.com",
                    "v.douyin.com", "jingxuan.douyin.com",
                    "iesdouyin.com", "www.iesdouyin.com"})
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                  "AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "identity",
}


def _checked_url(url):
    value = urllib.parse.urlsplit(url)
    if value.scheme not in {"http", "https"} or value.hostname not in _HOSTS:
        raise ValueError("只接受抖音公开链接")
    if value.username or value.password or value.port not in (None, 80, 443):
        raise ValueError("链接格式不正确")
    return urllib.parse.urlunsplit(("https", value.hostname, value.path or "/", value.query, ""))


def _url_id(url):
    value = urllib.parse.urlsplit(_checked_url(url))
    parts = [urllib.parse.unquote(x) for x in value.path.split("/") if x]
    candidate = None
    if value.hostname in {"www.douyin.com", "douyin.com"} and len(parts) == 2 and parts[0] == "video":
        candidate = parts[1]
    elif value.hostname == "jingxuan.douyin.com" and len(parts) == 3 and parts[:2] == ["m", "video"]:
        candidate = parts[2]
    elif value.hostname in _HOSTS - {"v.douyin.com", "jingxuan.douyin.com"} and len(parts) == 3 and parts[:2] == ["share", "video"]:
        candidate = parts[2]
    return candidate if candidate and _ID.fullmatch(candidate) else None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _get_once(url):
    """一次请求；不收发 Cookie。跳转交给上层，同样经过间隔限制。"""
    global _last_finished
    url = _checked_url(url)
    if _BLOCKED.is_set():
        raise ValueError("抖音请求已因验证码或拦截停止")
    with _NETWORK_LOCK, network_slot(url):
        if _BLOCKED.is_set():
            raise ValueError("抖音请求已因验证码或拦截停止")
        if _last_finished is not None:
            pause = _INTERVAL - (time.monotonic() - _last_finished)
            if pause > 0:
                time.sleep(pause)
        started = time.monotonic()
        try:
            request = urllib.request.Request(url, headers=_HEADERS)
            opener = urllib.request.build_opener(_NoRedirect())
            try:
                with opener.open(request, timeout=_TIMEOUT) as response:
                    if response.status != 200:
                        raise ValueError("网页请求失败")
                    if response.headers.get("Content-Encoding", "identity").lower() not in {"identity", ""}:
                        raise ValueError("网页编码不支持")
                    data = response.read(_MAX_BYTES + 1)
                    if len(data) > _MAX_BYTES:
                        raise ValueError("网页超过读取上限")
                    encoding = response.headers.get_content_charset() or "utf-8"
                    page = data.decode(encoding, errors="replace")
                    if verification_page(page):
                        _BLOCKED.set()
                        stop_douyin('抖音出现验证码，本批停止全部抖音请求')
                        raise ValueError("抖音出现验证码或拦截，已停止")
                    return page, None
            except urllib.error.HTTPError as error:
                try:
                    if error.code in {301, 302, 303, 307, 308} and error.headers.get("Location"):
                        return "", _checked_url(urllib.parse.urljoin(url, error.headers["Location"]))
                    if error.code in {403, 429}:
                        _BLOCKED.set()
                        stop_douyin('抖音返回HTTP %s，本批停止全部抖音请求'%error.code)
                    elif error.code not in {301,302,303,307,308}:
                        if verification_page(error.read(_MAX_BYTES).decode('utf-8',errors='replace')):
                            _BLOCKED.set()
                            stop_douyin('抖音出现验证码，本批停止全部抖音请求')
                    raise
                finally:
                    error.close()
        finally:
            _last_finished = time.monotonic()
            REQUEST_EVENTS.append({"host": urllib.parse.urlsplit(url).hostname, "path": urllib.parse.urlsplit(url).path,
                                   "started": started, "finished": _last_finished})
            if len(REQUEST_EVENTS) > 1000:
                del REQUEST_EVENTS[:-1000]


def _follow(url, stop_on_id=False):
    seen = set()
    for _ in range(6):
        if url in seen:
            raise ValueError("网页循环跳转")
        seen.add(url)
        if stop_on_id:
            video_id = _url_id(url)
            if video_id:
                return video_id
        page, target = _get_once(url)
        if target is None:
            return None if stop_on_id else page
        url = target
    raise ValueError("网页跳转过多")


def _count(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        return int(value.strip())
    return None


def _ssr_result(page, video_id):
    marker = re.search(r"\bwindow\s*\.\s*_SSR_DATA\s*=\s*", page)
    if not marker:
        return None
    try:
        payload, _ = json.JSONDecoder().raw_decode(page[marker.end():])
        for key in ("data", "storeState", "detail", "videoData", "result"):
            payload = payload[key]
        if not isinstance(payload, dict):
            return None
        for key in ("gid", "aweme_id"):
            if payload.get(key) is not None and str(payload[key]) != video_id:
                return None
        return payload
    except (ValueError, KeyError, TypeError):
        return None


class _JsonLd(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.capture = False
        self.parts = []
        self.values = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            attrs = dict(attrs)
            self.capture = str(attrs.get("type", "")).lower() == "application/ld+json"
            self.parts = []

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "script" and self.capture:
            self.capture = False
            try:
                self.values.append(json.loads("".join(self.parts)))
            except ValueError:
                pass


def _schema_type(value, name):
    if isinstance(value, dict):
        value = value.get("@type") or value.get("@id")
    if isinstance(value, list):
        return any(_schema_type(item, name) for item in value)
    return isinstance(value, str) and value.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1].rsplit(":", 1)[-1] == name


def _video_nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from _video_nodes(item)
    elif isinstance(value, dict):
        if _schema_type(value.get("@type"), "VideoObject"):
            yield value
        if "@graph" in value:
            yield from _video_nodes(value["@graph"])


def _jsonld_counts(page, video_id):
    parser = _JsonLd()
    parser.feed(page)
    parser.close()
    for node in _video_nodes(parser.values):
        identity = node.get("url") or node.get("@id")
        if isinstance(identity, str):
            try:
                claimed_id = _url_id(identity)
            except ValueError:
                claimed_id = None
            if claimed_id and claimed_id != video_id:
                continue
        counters = node.get("interactionStatistic", [])
        if isinstance(counters, dict):
            counters = [counters]
        if not isinstance(counters, list):
            continue
        play, digg = None, None
        for counter in counters:
            if not isinstance(counter, dict):
                continue
            if _schema_type(counter.get("interactionType"), "WatchAction"):
                play = _count(counter.get("userInteractionCount"))
            if _schema_type(counter.get("interactionType"), "LikeAction"):
                digg = _count(counter.get("userInteractionCount"))
        if play is not None:
            return {"play": play, "digg": digg}
    return None


def extract_counts(page, video_id):
    """只提取当前视频计数；不对网页脚本做 eval/exec。"""
    result = _ssr_result(page, video_id)
    if result is not None:
        play, digg = _count(result.get("play_count")), _count(result.get("digg_count"))
        if play is not None:
            return {"play": play, "digg": digg}
    fallback = _jsonld_counts(page, video_id)
    if fallback is not None and fallback["digg"] is None and result is not None:
        fallback["digg"] = _count(result.get("digg_count"))
    return fallback


def resolve_video_id(video_id_or_url):
    """复用相同的链接校验、短链跳转与全局限速；无重试。"""
    if not isinstance(video_id_or_url, (str, int)) or isinstance(video_id_or_url, bool):
        return None
    value = str(video_id_or_url).strip()
    if not value or len(value) > 4096:
        return None
    if _ID.fullmatch(value):
        video_id = value
    else:
        match = re.search(r"https?://[^\s<>\"，。！？]+", value)
        if not match:
            return None
        url = _checked_url(match.group(0).rstrip("）)]}>;；"))
        video_id = _url_id(url)
        if video_id is None and urllib.parse.urlsplit(url).hostname == "v.douyin.com":
            video_id = _follow(url, stop_on_id=True)
        if not video_id:
            return None
    return video_id


def fetch_play(video_id_or_url):
    """返回 {play,digg,fetched_at,source}；无公开播放数、错误或挑战页返回 None。

    所有网络请求（包括短链和精选页跳转）在本进程内串行，距上次请求结束
    至少3秒。每一步只请求一次，不重试失败请求，不登录、不带Cookie。
    """
    try:
        video_id = resolve_video_id(video_id_or_url)
        if not video_id:
            return None
        _LAST_PAGE.value = None
        page = _follow("https://jingxuan.douyin.com/m/video/" + video_id)
        _LAST_PAGE.value = (video_id, page)
        counts = extract_counts(page, video_id)
        if counts is None:
            return None
        fetched_at = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec="seconds")
        return {**counts, "fetched_at": fetched_at, "source": SOURCE}
    except (OSError, ValueError, TypeError, LookupError, RecursionError, urllib.error.URLError):
        return None


def last_public_page(video_id):
    """只复用同线程刚才fetch_play读到的精选HTML，避免重复网络请求。"""
    value = getattr(_LAST_PAGE, 'value', None)
    return value[1] if value and value[0] == video_id else ''


def last_video_id():
    value = getattr(_LAST_PAGE, 'value', None)
    return value[0] if value else None


# ---------------- 批量命令行（benchmark-crawl-teardown） ----------------
def _batch():
    import argparse, csv, os
    ap = argparse.ArgumentParser(description="批量补抓 videos.csv 的播放数（抖音精选公开页）")
    ap.add_argument("videos")
    ap.add_argument("--cache", help="缓存文件，默认与 videos.csv 同目录的 plays.csv")
    ap.add_argument("--limit", type=int, default=0, help="本次最多请求几条（0=全部）")
    a = ap.parse_args()
    cache_p = a.cache or os.path.join(os.path.dirname(os.path.abspath(a.videos)), "plays.csv")
    cache = {}
    if os.path.exists(cache_p):
        with open(cache_p, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if r.get("plays") not in (None, ""):
                    cache[r["video_id"]] = r
    with open(a.videos, encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        fields = list(rd.fieldnames or [])
        rows = list(rd)
    todo = [r for r in rows if r["video_id"] not in cache and str(r.get("form", "")) != "图文"]
    if a.limit:
        todo = todo[:a.limit]
    print(f"[plays] 共 {len(rows)} 条，缓存已有 {len(cache)} 条，本次请求 {len(todo)} 条（约 {len(todo) * 3 // 60 + 1} 分钟）", flush=True)
    new = not os.path.exists(cache_p)
    ok = fail = 0
    with open(cache_p, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["video_id", "plays", "play_fetched_at"])
        if new:
            w.writeheader()
        for i, r in enumerate(todo, 1):
            res = fetch_play(r["video_id"])
            if res and res.get("play") is not None:
                rec = {"video_id": r["video_id"], "plays": res["play"], "play_fetched_at": res["fetched_at"]}
                w.writerow(rec); f.flush()
                cache[r["video_id"]] = rec; ok += 1
            else:
                fail += 1
            if _BLOCKED.is_set():
                print(f"[plays] ⚠ {BLOCK_REASON[-1] if BLOCK_REASON else '被拦截'}；已停止，稍后再跑会从断点继续", flush=True)
                break
            if i % 20 == 0:
                print(f"[plays] {i}/{len(todo)}  成功 {ok}  失败 {fail}", flush=True)
    for c in ("plays", "play_fetched_at"):
        if c not in fields:
            fields.append(c)
    for r in rows:
        hit = cache.get(r["video_id"])
        r["plays"] = hit["plays"] if hit else r.get("plays", "")
        r["play_fetched_at"] = hit["play_fetched_at"] if hit else r.get("play_fetched_at", "")
    with open(a.videos, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    have = sum(1 for r in rows if r.get("plays") not in (None, ""))
    print(f"[plays] 本次成功 {ok}、失败 {fail}；videos.csv 播放数覆盖 {have}/{len(rows)}（图文没有播放数）", flush=True)


if __name__ == "__main__":
    _batch()
