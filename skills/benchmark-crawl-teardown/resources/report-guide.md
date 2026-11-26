# 写报告：单号拆解报告与跨账号汇总

数字全部来自 `bench.py facts / summarize` 生成的 facts.json。智能体只做三件事：**给作品分类、读口播和评论找差异、把结论写成 JSON**。需要表格时用数字块：`{"type": "fact", "key": "duration_table"}`。

## 一、给作品分类（labels.json）

- 读 `brief.md` 里的「全部作品」和「待分类」清单，按 `taxonomy.json` 的类别代码写 `<账号库>/accounts/<主页ID>/labels.json`，格式是 `{"完整视频id": "A", ...}`。
- 按「这条视频给观众的是什么」来分，不按标题关键词分：同样带「实测」两个字，6 款横评属于 B，单测一个新模型属于 D。
- 分类以后会被跨账号汇总复用，所以同一个号的分类写一次就会一直保留；第二次采集只需要补新作品。

## 二、单号报告（report.json）

位置：`<账号库>/accounts/<ID>/runs/<最新>/report.json`。写完运行 `bench.py render <账号>`。

### 结构

```json
{
 "headline": "一句话：这个号靠什么火、什么拍了没人看（带具体数字）",
 "sections": [
  {"title": "板块名", "conclusion": "这一块的结论，先说结论", "blocks": [ ... ]}
 ],
 "caveats": ["样本、口径、相关不等于因果……"]
}
```

`account`（粉丝、获赞、主页链接、爆款规则）和爆款清单由 facts.json 自动补上，不用写。

### 可用的块

| type | 用途 | 写法 |
|---|---|---|
| `fact` | 脚本算好的表或图 | `{"type":"fact","key":"category_table"}`。单号可用：category_table、duration_table、title_table、slot_table、month_chart、month_table、comment_table、compare_table（第二次采集后才有） |
| `kv` | 定位这类「项目：说明」 | `{"type":"kv","items":[["人设","…"],["给谁看","…"]]}` |
| `pairs` | 爆款 vs 同号对照 | `{"type":"pairs","items":[{"burst":{视频},"ctrl":{视频},"rows":[["开头 15 秒","爆款怎么说","对照怎么说"]],"why":"差异句"}]}`；视频 = `{"title","url","likes","date","duration_s"}`，从 brief.md 抄 |
| `quotes` | 高赞评论原文 | `{"type":"quotes","items":[{"text":"…","likes":5612,"tag":"哪条视频 · 最高赞"}]}` |
| `bullets` / `text` / `table` | 自由内容 | 自己写的 table 只放非计算类信息 |

### 必须覆盖的角度（顺序按这个号的情况调整，一个号没有的角度写一句「这个号没有××」）

1. **定位**：人设（凭什么讲）、给谁看、给观众什么、和同类号的区别、看得见的变现方式、账号名、置顶。
2. **人群画像**：comment_table + 评论里的身份线索。写明是从评论推断。
3. **作品分类**：category_table；结论说清哪类撑起这个号、哪类拖后腿。
4. **爆款拆解（同号对照）**：pairs.json 里每组一个 pairs 项；对比标题、开头 15 秒、讲什么、对谁有用、时长、评论。最后用 bullets 写「这个号的爆款规律」。
5. **内容设计**：title_table、duration_table + 开头、结构、类比、互动引导、系列。
6. **评论区**：quotes（3–5 条最有信息量的）+ 作者互动、竞品刷屏、还没被做的选题。
7. **题材风向与节奏**：month_chart + month_table + 更新频率、发布时间（slot_table）、涨粉（第一次写「待补」）。
8. **能学什么 / 别学什么**。
9. **第二次及以后**：加一节「和上次比」，放 compare_table，再写哪些规律仍成立、哪些变了、新出现了什么。

### 写法提醒

- 标题统计只看文案第一句；抖音的「标题」字段是整段文案，正文里的词会误伤。
- 数字核对、对比句、时机等规则见 SKILL.md「硬规则」5–7。

## 三、跨账号汇总（summary.json）

运行 `bench.py summarize <账号>... [--name-keyword AI]`，在新建的 `summaries/<时间>/` 里写 summary.json，再运行 `bench.py render-summary <目录>`。各号报告会被复制进 `reports/`，汇总页里用 links 块指过去：`{"type":"links","items":[{"href":"reports/知雪.html","text":"知雪 拆解报告"}]}`。

### 结构

```json
{"title": "N 个××对标号的爆款规律", "lede": "样本说明（几个号、几条、平均爆款率、哪些深拆）",
 "headline": "一句话总结", "sections": [...], "caveats": [...]}
```

### 板块

1. **样本**：`fact accounts_table` + 各号报告链接。
2. **大概率火 / 容易死 / 看情况**：用 rules 块，每条一项：
   `{"verdict":"火|死|看","stat":"60%","stat_note":"横评、帮你选\n5 条 3 爆","claim":"一句话规律","evidence":"具体视频和数字","holds":"成立：A、B ｜ 不成立：C ｜ 样本说明"}`
   - 「火 / 死」的入选规则见 SKILL.md「硬规则」8；集中提醒看 category_table。
   - 每条都要写左边的数字（爆款率或命中次数），全样本平均写在板块结论里。
3. **全部类别**：`fact category_table`。
4. **时长、标题写法、发布时间**：对应的 fact 表 + 一句结论。时长要提醒「更像账号风格」；发布时间如果各时段差别小，写「这个赛道看不出影响，换赛道要重测」。
5. **题材风向**：`fact month_chart` + `fact topic_table`；结论写清风往哪吹（后半段爆款率明显上升的题材）、哪些过气（前高后低）、哪些提得多但不爆。
6. **更新频率**：看 accounts_table 的「每周条数」「平时赞/粉丝」「爆款率」。
7. **账号名与涨粉**：`fact name_table`（用 --name-keyword 时）；涨粉要第二次采集后才有。
8. **第二次及以后**：`fact compare_table` + 规律变化（仍成立 / 变了 / 新出现）。
9. 不加选题推荐；不用横向条形图，只给百分比和结论。
