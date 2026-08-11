# B 站数据工具可行性调研（2026-08-10）

## 结论先行

2026 年的生态与项目设想时已经不同：两个最常被引用的 API 项目均因法律风险永久关停，BBDown 也已归档。Phase 1 不应继续押注非公开 API 的自维护实现。当前最小可行路径是把仍活跃的 `yt-dlp` 当作可替换适配器，严格限制为用户指定视频和小规模测试；字幕、评论是可降级证据，不是成功条件。

维护状态来自 2026-08-10 的 GitHub 仓库状态与最近 push 时间。功能判断仅基于项目文档/源码中能确认的能力。

| Project | 定位/可确认能力 | 状态（最近 push） | 字幕 | 评论 | 搜索 | 登录 | License | 决策 |
|---|---|---:|---|---|---|---|---|---|
| [Nemo2011/bilibili-api](https://github.com/Nemo2011/bilibili-api) | 曾是 Python 综合 SDK | **归档/永久关停**（2026-07-06） | 曾支持 | 曾支持 | 曾支持 | 部分能力需要 | 已移除 | 不采用；维护与法律风险不可接受 |
| [SocialSisterYi/bilibili-API-collect](https://github.com/SocialSisterYi/bilibili-API-collect) | 曾是非官方 API 文档集 | **归档/删除内容**（2026-01-30） | 曾记录 | 曾记录 | 曾记录 | 视端点 | 已移除 | 仅作为历史背景，不依赖 |
| [nilaoda/BBDown](https://github.com/nilaoda/BBDown) | C# CLI 下载器、字幕下载 | **归档**（2026-05-14） | 是 | 否 | 否 | 受限内容需要 | MIT | 不作为新原型核心；可作为历史备选 |
| [yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp) | Python/CLI；Bilibili 元数据、字幕、评论后处理、搜索提取器 | 活跃（2026-08-04） | 是 | 是 | 有，但实测 412 | 元数据通常不需要；字幕常需要 | Unlicense | **采用**；能力集中、可嵌入、可替换 |
| [yutto-dev/yutto](https://github.com/yutto-dev/yutto) | Python B 站专用下载器，单视频/批量、弹幕 | 活跃（2026-08-10） | 文档未确认 | 否 | 否 | 高画质/受限内容需要 | GPL-3.0 | 下载阶段候选；当前只取元数据时偏重 |
| [amtoaer/bili-sync](https://github.com/amtoaer/bili-sync) | Rust/Tokio 媒体库同步工具 | 活跃（2026-07-13） | 文档未确认 | 否 | 以账号资源同步为主 | 是 | MIT | 不采用；目标是 NAS 同步而非分析 |
| [biliup/biliup](https://github.com/biliup/biliup) | Rust/Python；直播录制、投稿、下载、查看评论 | 活跃（2026-08-07） | 非核心 | 是 | 否 | 多数工作流需要 | MIT | 能力过宽、依赖较重，不适合最小原型 |
| [nICEnnnnnnnLee/BilibiliDown](https://github.com/nICEnnnnnnnLee/BilibiliDown) | Java GUI 下载器 | 活跃（2026-07-10） | 文档未确认 | 否 | GUI 内检索非稳定 API 契约 | 常需 Cookie | Apache-2.0（仓库说明） | 不采用；GUI/Java 集成成本高 |
| [leiurayer/downkyi](https://github.com/leiurayer/downkyi) | Windows GUI 下载器 | 活跃（2026-07-06） | 文档未确认 | 否 | GUI 能力 | 受限内容需要 | GPL-3.0 | 不采用；难作为轻量 Python 数据适配器 |

`yt-dlp` 的 Bilibili 提取器源码明确暴露 `view_count`、`like_count`、`comment_count`、标签、字幕与评论提取；但未输出收藏和投币。其字幕路径在无登录时会返回 `need_login_subtitle`，本轮 5 个样本中有 4 个明确触发该提示。

## 三种数据方案

| 方案 | 稳定性 | 开发成本 | 登录要求 | 数据完整度 | 维护性 | 风险 |
|---|---|---|---|---|---|---|
| A. `yt-dlp` 单适配器 | 中 | 低 | 元数据低；字幕/部分内容高 | 标题、简介、作者、时间、播放、点赞、评论数、标签；收藏/投币缺失 | 高：活跃上游，隔离在 adapter | 搜索 412；上游接口变化；平台条款风险 |
| B. 官方开放平台 + 下载器 | 高（授权范围内） | 中 | OAuth/开发者资质 | 自有/授权稿件强；任意公开视频发现不足 | 高 | 覆盖面无法满足产品目标 |
| C. 浏览器自动化/页面解析 | 低到中 | 高 | 可能需要 | 可接近页面展示字段 | 低：DOM/风控变化频繁 | 412/验证码、维护成本、合规边界更复杂 |

## 实验结论

- 单 BVID 元数据：5/5 成功。
- B 站搜索提取器：实测 HTTP 412，不能作为当前可靠入口。
- 字幕：0/5；不能作为无登录 MVP 的硬依赖。
- 评论：对低播放样本开启一次，5/5 条成功取得；默认关闭以控制请求量。
- 收藏、投币：`yt-dlp` 当前数据模型不提供，保持 `null`，没有用错误字段替代。
- 官方开放平台文档显示的重点是已授权稿件发布、删除、查询，并非任意公开视频研究数据接口。

## 边界

本调研不是对非公开接口的重新整理或逆向说明。原型不绕过认证、不规避风控、不下载媒体、不批量抓取，只对用户提供的 BVID 做低频分析。
