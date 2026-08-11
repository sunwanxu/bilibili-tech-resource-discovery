# Phase 1 架构

```text
CLI (BVID / URL)
  -> YtDlpDataSource
       -> VideoMetadata + available subtitles/comments + extractor raw
  -> FileStorage.save_raw()
  -> Analyzer protocol
       -> OpenAIAnalyzer | HeuristicAnalyzer
  -> VideoAnalysisSchema
  -> processed JSON + Markdown report
```

边界很窄：`source.py` 是唯一接触 B 站数据提取工具的模块；`analyzers.py` 不发平台请求；`storage.py` 不关心数据来源或模型。数据源和模型都可以替换，而无需改 CLI 输出契约。

失败策略：元数据失败则命令返回非零；字幕、评论、收藏或投币缺失则保留空值与 warnings，继续生成报告。外部请求由 `yt-dlp` 的 timeout/retry 和 `sleep_interval_requests` 控制，值来自 `.env`。
