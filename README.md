# 对标账号拆解技能（Benchmark Account Teardown Skills）

阿伟自制的两个 AI 技能（Skill），用来拆解抖音对标账号、总结短视频爆款规律。适用于 Claude Code、Codex 等支持 Skill 的 AI 助手。

| 技能 | 作用 |
|---|---|
| [benchmark-teardown-playbook](skills/benchmark-teardown-playbook)（对标拆解方法论） | AI 赛道短视频怎么拍的规律合集：起标题与避雷、新模型发布拍什么、互动目标与系列化、更新节奏与商单拍法 |
| [benchmark-crawl-teardown](skills/benchmark-crawl-teardown)（抓取拆解视频） | 给抖音对标账号主页链接，抓取作品、按「点赞 ≥ 本号中位数 3 倍」找爆款，转写对照、抓评论，出单号拆解报告和跨账号规律汇总 |

## 安装

把 `skills/` 里的两个文件夹复制到：

- Claude Code：`~/.claude/skills/`
- Codex：`~/.codex/skills/`

然后直接对 AI 说「帮我起几个标题」或「拆解这个对标账号 <主页链接>」即可。

## 运行要求（抓取拆解视频）

- [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)，配合本仓库的 `mediacrawler-benchmark.patch`。MediaCrawler 有自己的非商业学习许可，使用时请遵守。
- 一个装了 `mlx-whisper`（Apple 芯片）或 `faster-whisper` 的 Python，用于转写。
- 详见 [collect-guide.md](skills/benchmark-crawl-teardown/resources/collect-guide.md)。

## 使用须知

- 只采集公开内容；登录、扫码、验证码都由使用者本人完成，不绕过平台限制，保持默认限速。
- 规律来自样本数据，相关不等于因果，换赛道或隔几个月请重新测。

## 许可

本仓库自有内容采用 [MIT License](LICENSE)。`mediacrawler-benchmark.patch` 是对 MediaCrawler 的修改，适用 MediaCrawler 的原许可。
