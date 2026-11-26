# 采集与准备（bench.py）

## 一次性配置

1. 用户本机要有 [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)（非商业学习许可）。检查是否打过对标补丁：`grep DY_BENCHMARK_MODE <MediaCrawler>/config/dy_config.py`。没打过就先征得用户同意，再在 MediaCrawler 根目录执行 `git apply <本目录>/mediacrawler-benchmark.patch`。打不上（上游改版）时，按补丁内容手动改 4 个文件：`config/dy_config.py`、`media_platform/douyin/client.py`、`media_platform/douyin/core.py`、`store/douyin/__init__.py`。补丁全部挂在 `DY_BENCHMARK_MODE=1` 开关后面，不影响原有用法。
2. 转写环境：一个装了 `mlx-whisper`（Apple 芯片）或 `faster-whisper` 和 `imageio-ffmpeg` 的 Python。国内装包用 `-i https://mirrors.aliyun.com/pypi/simple/`，下模型设 `HF_ENDPOINT=https://hf-mirror.com`。
3. `python3 bench.py init --mediacrawler <目录> --whisper-python <转写用的 python> [--home ~/对标账号库]`，写入 `~/.config/benchmark-viral-research/config.json`。已配置过就跳过（直接 `bench.py list` 能跑就说明配好了）。

## 每次采集

```bash
python3 bench.py collect <主页链接或分享口令>... --window 60      # 7 / 30 / 60 / all
python3 bench.py prepare <账号名或主页ID>                          # 找爆款、配对照（默认最多 8 组）
python3 bench.py comments <账号>                                  # 爆款+对照的前 30 条评论，顺带刷新视频地址
python3 bench.py transcribe <账号>                                # 转写爆款+对照（必须在 comments 之后）
python3 bench.py plays <账号>                                     # 可选：播放数，每条 3 秒
python3 bench.py brief <账号>                                     # 生成 brief.md 给智能体读
```

- `collect` 能一次给多个链接，按顺序抓。分享口令里的 `v.douyin.com` 短链会自动解析成主页。**给的是视频链接不是主页**时会报错，请用户给主页分享链接。
- `--window all` 抓全部作品（上限 `--max-posts 500`，日志出现「触到上限」就调大）。时间范围按发布日期截取，早于范围的置顶作品不收。
- 只做汇总、不深拆的号：只跑 `collect`，再给它的作品分类（见 report-guide），不跑 prepare / comments / transcribe。

## 耗时与记录

- **耗时预估**（告诉用户）：抓作品每号约 1 分钟；评论 10–20 条视频约 5–10 分钟；转写每条 1.5–2 分钟（下载 + 识别）。一个号深拆大约 20–30 分钟。
- **粉丝快照**：每次 `collect` 自动往 `followers.csv` 记一笔。同一个号第二次 `collect` 之后，`facts` 自动生成和上次的对比（粉丝变化、新作品、爆款率、各类别变化）。
- 扫码、验证码、不并行、限速等规则见 SKILL.md「硬规则」。
