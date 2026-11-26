#!/usr/bin/env python3
"""转写爆款与对照视频，提取开头钩子。

输入 CSV（至少两列）：video_id, media（本地文件路径，或 get_media_url.js 拿到的 http 地址）
用法：
  python3 transcribe.py media_list.csv --out transcripts/ [--model large-v3-turbo] [--hook-seconds 5]
输出：
  transcripts/<video_id>.txt      带时间戳全文
  transcripts/hooks.csv           video_id, hook_text（前 N 秒）, first_sentence, chars_per_min, duration_s
后端（自动选择，按顺序）：mlx_whisper（Apple 芯片）→ faster_whisper → whisper。都没有时报错并给出安装命令。
需要 ffmpeg 在 PATH（或 pip install imageio-ffmpeg 后本脚本会自动使用其自带 ffmpeg）。
国内网络：可设 HF_ENDPOINT=https://hf-mirror.com，pip 用 -i https://mirrors.aliyun.com/pypi/simple/
"""
import argparse, csv, os, shutil, sys, tempfile, urllib.request

PROMPT = "以下是普通话的简体中文转写。"


def ensure_ffmpeg():
    if shutil.which("ffmpeg"):
        return
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        d = tempfile.mkdtemp(prefix="ffbin")
        os.symlink(exe, os.path.join(d, "ffmpeg"))
        os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
    except ImportError:
        sys.exit("[transcribe] 找不到 ffmpeg：请安装 ffmpeg，或 pip install imageio-ffmpeg")


def pick_backend(model):
    try:
        import mlx_whisper
        repo = model if "/" in model else f"mlx-community/whisper-{model}"
        return "mlx", lambda p: mlx_whisper.transcribe(p, path_or_hf_repo=repo, language="zh", initial_prompt=PROMPT, verbose=None)["segments"]
    except ImportError:
        pass
    try:
        from faster_whisper import WhisperModel
        m = WhisperModel(model, compute_type="int8")
        def run(p):
            segs, _ = m.transcribe(p, language="zh", initial_prompt=PROMPT)
            return [{"start": s.start, "end": s.end, "text": s.text} for s in segs]
        return "faster", run
    except ImportError:
        pass
    try:
        import whisper
        m = whisper.load_model(model.replace("-turbo", ""))
        return "whisper", lambda p: m.transcribe(p, language="zh", initial_prompt=PROMPT)["segments"]
    except ImportError:
        sys.exit("[transcribe] 没有可用的转写后端。Apple 芯片：pip install mlx-whisper；其他：pip install faster-whisper")


def fetch(src, tmpdir, vid):
    if os.path.exists(src):
        return src
    path = os.path.join(tmpdir, f"{vid}.mp4")
    req = urllib.request.Request(src, headers={"Referer": "https://www.douyin.com/",
                                               "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/150.0 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f)
    if os.path.getsize(path) < 10000:
        raise RuntimeError("下载内容过小，地址可能已过期，请重新用 get_media_url.js 获取")
    return path


HALLUCINATIONS = ("明镜与点点", "请不吝点赞", "字幕由", "字幕提供", "Amara.org", "谢谢观看", "订阅我的频道", "感谢收看")


def is_noise(seg):
    """whisper 在纯音乐/无人声段会幻觉（2026-11 实测两种：单字循环“法法法…”、套话“请不吝点赞…明镜与点点”）。"""
    t = "".join(seg["text"].split())
    if not t:
        return True
    if len(t) >= 12 and len(set(t)) / len(t) < 0.15:
        return True
    if any(h in t for h in HALLUCINATIONS):
        return True
    span = seg["end"] - seg["start"]
    return span > 8 and len(t) / span < 1.2  # 正常中文口播约 4-5 字/秒


def clean(segs):
    out = []
    for s in segs:
        n = is_noise(s)
        out.append({**s, "text": "[无口播：音乐/画面]" if n else s["text"].strip(), "_noise": n})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("media_list")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--hook-seconds", type=float, default=5.0)
    a = ap.parse_args()
    ensure_ffmpeg()
    name, run = pick_backend(a.model)
    os.makedirs(a.out, exist_ok=True)
    rows = list(csv.DictReader(open(a.media_list, encoding="utf-8-sig")))
    hooks_path = os.path.join(a.out, "hooks.csv")
    done = {r["video_id"] for r in csv.DictReader(open(hooks_path, encoding="utf-8"))} if os.path.exists(hooks_path) else set()
    new = not os.path.exists(hooks_path)
    tmp = tempfile.mkdtemp(prefix="dyaudio")
    with open(hooks_path, "a", encoding="utf-8", newline="") as hf:
        w = csv.DictWriter(hf, fieldnames=["video_id", "hook_text", "first_sentence", "chars_per_min", "duration_s"])
        if new:
            w.writeheader()
        for r in rows:
            vid = r["video_id"]
            if vid in done:
                print(f"[transcribe] 跳过已转写 {vid}")
                continue
            try:
                segs = clean(run(fetch(r["media"], tmp, vid)))
            except Exception as e:
                print(f"[transcribe] ✗ {vid}: {e}")
                continue
            with open(os.path.join(a.out, f"{vid}.txt"), "w", encoding="utf-8") as f:
                for s in segs:
                    m, sec = divmod(int(s["start"]), 60)
                    f.write(f"[{m:02d}:{sec:02d}] {s['text'].strip()}\n")
            speech = [s for s in segs if not s["_noise"] and s["text"]]
            hook = "".join(s["text"] for s in speech if s["start"] < a.hook_seconds)
            if not hook:
                first_t = speech[0]["start"] if speech else None
                hook = f"[无口播开场，首句出现在 {first_t:.0f} 秒]" if first_t is not None else "[全片无口播]"
            dur = segs[-1]["end"] if segs else 0
            chars = sum(len(s["text"]) for s in speech)
            w.writerow({"video_id": vid, "hook_text": hook, "first_sentence": speech[0]["text"] if speech else "",
                        "chars_per_min": round(chars / dur * 60) if dur else "", "duration_s": round(dur, 1)})
            hf.flush()
            print(f"[transcribe] ✓ {vid}（{name}）钩子：{hook[:40]}")


if __name__ == "__main__":
    main()
