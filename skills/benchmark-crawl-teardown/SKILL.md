---
name: benchmark-crawl-teardown
description: 【自制skill】抓取拆解视频：给一个或多个抖音对标账号主页链接，选时间范围（近 7/30/60 天或全部），用 MediaCrawler 抓作品，按「点赞 ≥ 本号中位数 3 倍」找爆款，转写爆款和同号对照、抓评论，写单号拆解报告（定位、人群、分类、爆款对照、内容设计、评论区、风向节奏）；多个号时再出跨账号规律汇总（火 / 死 / 看情况，附各号报告）；也能只用已拆解的账号出汇总；同一号再抓时自动对比规律变化。触发：「拆解这个对标账号」「批量拆这几个号」「给这几个号出个规律汇总」「再抓一次看看规律变没变」。不用于：只起标题（用 benchmark-teardown-playbook）、分析自己后台完播率。Use when asked to analyze benchmark/competitor Douyin creators, produce per-account teardown reports or a cross-account viral-pattern summary.
---

# 抓取拆解视频：对标账号拆解报告与跨账号规律汇总

## 方法（五个动作）

1. **相对口径**：每个号只和自己平时比，点赞 ≥ 本号中位数 3 倍才算爆款，大号小号可以放在一起看。
2. **同号对照找原因**：同一个号的爆款和发布时间最近的普通视频放在一起比，找看得见的差异。
3. **多角度切片**：内容方向、标题写法、时长、题材、更新频率、发布时间、账号名，各算爆款率，和平均比。
4. **自检**：样本少的、靠单个号撑起来的结论主动打折。
5. **复盘**：隔一段时间重抓，看规律还成不成立。

规律只从这批对标号的数据里归纳，不套用任何现成经验（包括 benchmark-teardown-playbook 里的规律）。实测中，「做出东西才会火」在一个号上成立，在另一个号上是反的：讲原理的视频比带着做的高 14 倍。

## 何时用

- 拆一个号：「拆解这个对标账号」「帮我分析一下这个博主」，附主页链接或分享口令。
- 批量：「这几个对标号都拆一下」「批量拆解出个汇总」。
- 只汇总：「用这几个已经拆过的号，出个规律汇总」。
- 再抓对比：「再抓一下这个号，看看有什么变化」「重新跑一遍，规律变没变」。

**运行环境**：采集和转写要在装了 MediaCrawler 和转写环境的电脑上跑；只能读文件、不能跑脚本时，只用已采集好的数据写报告和汇总，并告诉用户。

## 流程

先读 `resources/collect-guide.md`（采集）和 `resources/report-guide.md`（写报告）。命令都是 `python3 <本 Skill 目录>/resources/bench.py ...`，下文简写为 `bench.py`。

**0. 确认输入**（缺了就问，不要猜）

| 字段 | 默认 | 说明 |
|---|---|---|
| 账号 | — | 主页链接或分享口令；也可以是账号库里已有的账号名 |
| 时间范围 | 近 60 天 | 7 / 30 / 60 / 全部 |
| 深拆哪些号 | 全部 | 没勾选的号只看数据：参与汇总，不出单号报告 |
| 模式 | 按账号数 | 1 个号 → 单号报告；多个号 → 单号报告 + 汇总；「用已拆解的号汇总」→ 只汇总 |

首次使用：`bench.py list` 能跑说明已配好；不能跑就按 collect-guide「一次性配置」做。

**1. 采集**：`collect <链接…> --window <范围>`。每个号显示「✓ N 条」算完成；N 为 0 或出现「触到上限」要告诉用户。

**2. 深拆**（逐个号）：`prepare` → `comments` → `transcribe` →（可选 `plays`）→ `brief`。开始前告诉用户每号约 20–30 分钟。

**3. 分类**：读每个号的 brief.md，按 taxonomy.json 写 labels.json。只看数据的号也要分类，汇总靠它。

**4. 单号报告**：`facts` → 读 brief.md、转写、facts.json → 写 report.json → `render`。

**5. 汇总**（多个号，或用户点名要）：`summarize <账号…> [--name-keyword AI]` → 写 summary.json → `render-summary <目录>`。

**6. 再抓对比**：同样跑 1–4，`facts` 自动生成 compare_table；报告加「和上次比」，汇总写哪些规律仍成立、变了、新出现。不做自动定时复盘。

**7. 交付**：发 report.html / summary.html 的路径，再用 5–8 句话说清：最大的几个爆款规律、最该避开的、和上次比的变化（如有）、哪些结论样本不足。

**输出位置**：单号 `<账号库>/accounts/<ID>/runs/<时间>/report.html`；汇总 `<账号库>/summaries/<时间>/summary.html`，各号报告在同目录 `reports/`；原始数据、转写、评论留在 run 目录。

## 硬规则

**采集**
1. **凭据交给用户**：MediaCrawler 会打开 Chrome，登录过期时出现二维码，请用户扫码；出现验证码立即停下交给用户。不代登录、不绕过验证码、不采集私密内容。
2. **一步一步来**：一个号跑完再跑下一个；评论和转写不能同时跑（会报 `ConnectError`），报错就重跑那一步。
3. **不调低限速**：翻页 15 秒、播放数每条 3 秒。
4. **MediaCrawler 补丁**：打补丁前先征得用户同意；上游改版可能让补丁失效，先检查。

**写报告**
5. **数字只用脚本算的**：表格和百分比来自 facts.json，不心算；写完把报告里每个数字（点赞、倍数、日期、时长、条数）回到 brief.md / facts.json 核对一遍（实测第一稿平均错 3–4 处）。
6. **「为什么爆」必须是对比句**：指出爆款和对照之间看得见的差异；找不到就写「未找到明确的可见差异」，再列可能原因，不编。
7. **时机要说出来**：爆款发在某个工具或话题最热的时候，写明时机也有贡献。
8. **汇总里「火 / 死」只放至少 2 个号成立的规律**；一类爆款一半以上来自同一个号（集中提醒）时，用去掉它之后的数字。只在一个号成立或各号相反的放「看情况」。

## 解读边界

- **相关不等于因果**：规律只是「这批号里什么和高数据一起出现」。
- **选样偏差**：对标号是用户挑的，结论只代表这批号所在的赛道。
- **相对口径的副作用**：平时点赞很低的小号更容易「过 3 倍」，要看集中提醒。
- **小样本**：单号几十条、单类几条的结论只当线索。
- **覆盖不一致**：各号更新频率不同，同样时间范围条数可能差很多，按月份的结论要打折。
- **涨粉**：第一次采集只记粉丝数，第二次采集后才能算涨粉。
- 不把恐吓、引战类的高互动当成推荐方向。

## 配套资源

脚本运行前先检查运行条件，不因附带而自动执行。

- [resources/collect-guide.md](resources/collect-guide.md)：一次性配置、采集命令、耗时
- [resources/report-guide.md](resources/report-guide.md)：分类、报告和汇总的 JSON 写法
- [resources/bench.py](resources/bench.py)、[resources/account_report.py](resources/account_report.py)、[resources/transcribe.py](resources/transcribe.py)、[resources/play_counts.py](resources/play_counts.py)
- [resources/taxonomy.json](resources/taxonomy.json)：统一分类与关键词表
- [resources/mediacrawler-benchmark.patch](resources/mediacrawler-benchmark.patch)
