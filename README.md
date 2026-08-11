# Bilibili Technical Resource Discovery

从自然语言需求出发，联合普通网页索引、B 站证据和开源项目平台，寻找真正可复用的技术资源。项目优先返回源码、PCB 工程、设计资料和许可证证据；视频用于解释方案、验证价值以及发现简介、字幕和评论中的隐藏链接。

## 能做什么

- 搜索 GitHub、Gitee、立创开源平台及其他公开技术项目。
- 发现相关 B 站视频，并读取可获得的简介、字幕和有限评论。
- 从多种证据中提取仓库、硬件工程、文档、网盘和受限资源线索。
- 分别验证源码、原理图、PCB、BOM、Gerber、固件、文档和许可证范围。
- 对资源可用性和视频教学价值分别排序，不用视频热度代替工程价值。
- 接受 BV、`av...`、纯数字 aid 或 B 站视频链接。

## 作为 Agent Skill 安装

可分发 Skill 位于：

```text
skills/bilibili-tech-resource-discovery
```

把整个文件夹交给 Codex 或 OpenCode，并要求 AI 安装该 Skill。文件夹已经包含运行源码和跨客户端安装器，不依赖本仓库的其他目录。首次需要登录时，安装器会打开一个独立的 Edge 窗口；用户只需正常登录 B 站，不需要 Firefox、Cookie 插件或手工导出 Cookie。

安装器会验证实际运行的是 Skill 自带的命令：

```text
Runtime verified: bhka 0.3.0
```

之后用户可以直接描述需求，例如：

```text
帮我寻找适合零基础学习嘉立创 EDA 的视频，并优先返回带完整 PCB 工程的开源项目。
```

## 源码开发

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check .
```

常用 CLI：

```powershell
.\.venv\Scripts\bhka --version
.\.venv\Scripts\bhka login --project-root .
.\.venv\Scripts\bhka auth-status --json --project-root .
.\.venv\Scripts\bhka discover "自然语言技术需求" --project-root .
.\.venv\Scripts\bhka analyze BVxxxxxxxxxx --summary-json --project-root .
```

AI 分析器是可选能力。没有 OpenAI 或 DeepSeek API Key 时，搜索、资源提取、字幕和评论读取仍可工作；单视频评价会使用明确标记的启发式基线。

## 数据和安全边界

- `.env`、`.auth/`、Cookie、API Key、`data/` 和 `reports/` 不进入 Git。
- 登录状态只保存在安装目录本地，不复制进 Skill 分发包。
- 不批量抓取、不绕过验证码、不轮换账户或代理规避限制。
- HTTP 412 会触发运行级熔断和 5/15/30 分钟自适应客户端冷却；该时间不是 B 站官方规定。
- 不把“文件可下载”等同于“具有开源许可证”，也不把组件许可证扩大到完整项目。

所有自动化测试均使用离线假数据，不访问 B 站。
