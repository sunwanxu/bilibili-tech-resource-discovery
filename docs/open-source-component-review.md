# v1 开源组件评估

评估日期：2026-08-15。结论同时考虑功能、维护状态、许可证、Windows 安装成本、隐私和上游风险。

## 1. 决策摘要

| 能力 | 结论 | 采用方式 |
|---|---|---|
| Windows 运行时 | 采用 `uv` | 固定版本的隔离安装和升级，不使用 editable install |
| 独立登录会话 | 采用 Playwright 思路 | 可见 Edge/Chromium + 项目专属会话，不读取日常浏览器 Cookie 数据库 |
| B 站候选发现 | 自建薄适配器 | 读取官方搜索页面；借鉴 OpenCLI 的浏览器桥接思想，但不强制扩展/Node |
| 视频深读 | 采用 `yt-dlp` Python wheel | 读取选定视频的标准化元数据和字幕；不下载视频 |
| 字幕降级 | 借鉴 BiliNote | 字幕优先、缓存命中优先；不复制其完整 Web/RAG 系统 |
| 排名与缓存 | Python + SQLite FTS5 | BM25、本地去重、断点和事件日志，避免引入服务端数据库 |
| 仓库验证 | GitHub REST +普通 HTTP | 读取仓库状态、默认分支、许可证和必要文件；密钥可选 |
| 报告协议 | Pydantic JSON envelope | 借鉴 bilibili-cli 的稳定 envelope，但自行实现、版本化 |

## 2. 采用或借鉴

### `yt-dlp/yt-dlp`

- 地址：https://github.com/yt-dlp/yt-dlp
- 状态：活跃维护，Bilibili extractor 持续更新。
- 许可证：源码和 PyPI wheel 为 Unlicense；官方 PyInstaller 可执行文件包含其他组件时为 GPLv3+。
- 采用：依赖 PyPI wheel，封装为选定视频的深读适配器；不把整个 raw extractor response 持久化。
- 不采用：用它连续执行大量 B 站搜索，或默认抓取无限评论。

### `microsoft/playwright-python`

- 地址：https://github.com/microsoft/playwright-python
- 状态：活跃维护，Windows/Chromium 支持成熟。
- 许可证：Apache-2.0。
- 采用：独立可见登录窗口、项目专属 storage state、B 站搜索页面读取和最小化证据读取。
- 边界：登录文件视为敏感数据；不得提交、上传或打印。

### `astral-sh/uv`

- 地址：https://github.com/astral-sh/uv
- 状态：稳定、活跃，支持 Windows，独立二进制不要求预装 Python。
- 许可证：MIT 或 Apache-2.0。
- 采用：发布时固定版本，安装锁定 wheel 与托管 Python，运行环境按版本目录原子切换。

### `JefferyHcool/BiliNote`

- 地址：https://github.com/JefferyHcool/BiliNote
- 状态：活跃，MIT，2026 年仍发布版本。
- 借鉴：字幕优先于音频转写、浏览器侧预取、缓存命中复用、无字幕才降级。
- 不直接采用：完整后端、RAG、插件和模型配置远超本项目核心需求。

### `public-clis/bilibili-cli`

- 地址：https://github.com/public-clis/bilibili-cli
- 许可证：Apache-2.0。
- 借鉴：二维码登录体验、`ok/schema_version/data/error` envelope、规范化 payload 和错误代码。
- 不作为核心依赖：它直接依赖 `bilibili-api-python>=16.0`，而该上游已经归档；其 Edge/Chrome
  Cookie 自动提取也有公开故障报告。

### `jackwener/OpenCLI`

- 地址：https://github.com/jackwener/OpenCLI
- 状态：活跃，Apache-2.0，Bilibili 适配覆盖搜索、字幕、视频、UP 投稿等。
- 借鉴：在用户已登录浏览器环境中执行确定性适配器、统一结构化输出、适配器可验证。
- 可选集成：用户已经安装 OpenCLI 时可作为额外发现源。
- 不作为默认依赖：需要 Node.js、浏览器扩展和本地桥接，违背首次安装零摩擦目标。

### `tamnd/bilibili-cli`

- 地址：https://github.com/tamnd/bilibili-cli
- 状态：Apache-2.0、单 Go 二进制、接口和缓存设计清晰，但项目很新、提交和用户验证很少。
- 借鉴：ID 统一、JSONL 管道、缓存、dry-run、请求预算和明确退出码。
- 暂不采用为核心：直接维护 WBI/匿名会话和未公开端点会把高维护风险重新带回项目；其默认对
  `-412` 重试也不符合我们的全局熔断规则。

## 3. 明确排除

### `Nemo2011/bilibili-api`

- 地址：https://github.com/Nemo2011/bilibili-api
- 2026-07 已因收到 B 站法律通知归档并永久停止。
- 结论：不依赖、不复制实现，只保留风险记录。

### `NanmiCoder/MediaCrawler`

- 地址：https://github.com/NanmiCoder/MediaCrawler
- 优点：Playwright 登录态、搜索、评论和多种存储方案成熟。
- 许可证：`NON-COMMERCIAL LEARNING LICENSE 1.1`，不是通用开源许可证，限制商业使用和用途。
- 结论：只能学习高层架构思想，不能合并代码或作为可再分发依赖。

### `nilaoda/BBDown`

- 地址：https://github.com/nilaoda/BBDown
- 2026-05 已归档。
- 结论：不新增为 v1 核心依赖，避免再次依赖停止维护的 B 站适配器。

### 搜索引擎 HTML 抓取

- 结论：不作为核心内置方案。页面结构和使用条款不稳定，也无法保证结果真来自 B 站内部搜索。
- Firecrawl 或宿主提供的网页搜索可作为明确标注的补充源，缺少密钥时不能让核心链路失效。

## 4. 按阶段的最终组合

| 阶段 | v1 默认实现 | 可选适配器 |
|---|---|---|
| 安装 | 固定版本 uv + 锁定 wheel + 原子切换 | 预构建安装包 |
| 登录 | Playwright 独立可见会话 | 公开模式 |
| 候选发现 | B 站搜索页面适配器 | OpenCLI、Firecrawl、宿主网页索引、手工 URL |
| 扩展 | B 站页面中的相关视频/UP/合集 | 缓存导入 |
| 深读 | yt-dlp + 页面最小证据读取 | 用户提供字幕/文档 |
| 排名 | SQLite FTS5/BM25 + 确定性特征 | 宿主 AI 重排 |
| 链接挖掘 | URL 规范化、来源合并、证据片段 | 平台专项解析器 |
| 资源验证 | GitHub REST、普通 HTTP、结构文件探测 | Gitee/立创专项适配器 |
| 输出 | 版本化 Pydantic JSON + 派生 Markdown | 网站 UI/Skill 展示层 |

## 5. 许可证与分发约束

- 发布包必须生成第三方组件清单并保留许可证文本。
- 若分发 yt-dlp 的 PyInstaller 版可执行文件，组合许可证可能变成 GPLv3+；v1 默认使用 PyPI wheel，
  避免无意改变本项目分发条件。
- 任何从 Apache-2.0 项目改写的具体代码都需要保留要求的版权和 NOTICE；仅借鉴接口思想时仍应在
  设计记录中注明来源。
- “能访问”不代表“允许重新分发”。外部项目的许可证结论必须限定到对应仓库或文件。

