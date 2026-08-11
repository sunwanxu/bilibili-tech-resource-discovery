# Phase 1 决策记录

## D1：选择 `yt-dlp` 单适配器

选择方案 A：以 `YtDlpDataSource` 封装 `yt-dlp`，而不是采用已关停的 `bilibili-api-python` 或自己维护非公开协议。

理由：

- 2026-08 仍活跃，Bilibili 提取器有持续修复。
- 一次调用能取得 Phase 1 所需的大部分字段，并能尽力取得字幕/评论。
- Python API 可直接嵌入，同时通过 `VideoDataSource` 协议隔离，未来可以换成官方接口或用户导出的数据。
- 不下载视频、不引入 FFmpeg、浏览器、数据库或微服务。

代价：收藏和投币当前缺失；字幕常需 Cookie；搜索已实测 412。Schema 明确保留 `null` 和 evidence limitations，不伪造完整度。

## D2：原始 JSON + 文件存储

Phase 1 使用文件系统，不引入 SQLite。每次提取首先保存 `data/raw/<BVID>.json`，其中包含标准化字段、字幕/评论、warnings 和 `yt-dlp` 的 sanitized extractor info；分析结果另存到 `data/processed/`。这样评分变化后可离线重跑。

## D3：分析器可替换，结果必须标注方法

`DeepSeekAnalyzer` 使用 V4 Pro 的 OpenAI 兼容 Chat Completions JSON Output，`OpenAIAnalyzer` 使用 Responses API JSON Schema 输出；`HeuristicAnalyzer` 只作为链路验证基线。`auto` 优先选择已配置的 DeepSeek，其次 OpenAI，否则明确输出 `analysis_method=heuristic_baseline`。不把启发式结果包装成 AI 语义判断。

没有制定最终 Hidden Value 公式。`possible_hidden_value` 仍是独立实验维度，其理由中明确说明不是最终公式。

## D4：评论为显式可选项

`--comments` 默认关闭。原因是上游评论提取会分页，数量大时请求成本不可控。Phase 1 仅在小样本上验证能力；后续应先实现明确的页数/条数预算，再用于批量实验。

## D5：停止边界

本轮不实现搜索扩展、Whisper、RAG、知识图谱、Web UI 或 Agent 循环。搜索接口的 412 记录为 Phase 2 前置研究问题，而不是在本轮通过更激进方案绕过。
