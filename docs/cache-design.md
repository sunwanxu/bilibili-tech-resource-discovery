# v1 缓存读取设计

决策日期：2026-08-15。

## 目标

让重复或相近需求复用已经完成的视频深读与外部资源验证，减少 B 站请求、链接验证时间和
HTTP 412 风险，同时避免把不完整或过期的数据伪装成最新验证。

## 开源优先评估

| 方案 | 决策 | 原因 |
|---|---|---|
| Python `sqlite3` + SQLite UPSERT | 采用 | 项目已经使用 SQLite；Windows/Python 自带，无新安装成本，事务和唯一键足够支持原子 checkpoint |
| DiskCache | 参考 | Apache-2.0、Windows 支持良好，过期键和原子操作成熟；但通用键值模型不能直接表达评论覆盖、证据保留级别和许可证验证范围 |
| requests-cache | 参考 | 其分层过期与稳定请求键设计值得借鉴；但它面向 HTTP 请求/响应，而项目缓存的是经过最小化的领域证据，直接采用会保存更多第三方原始响应 |
| 新增 Redis 或服务端数据库 | 拒绝 | 单用户 Windows Skill 不需要后台服务，会显著提高安装和运维门槛 |

参考资料：

- SQLite UPSERT：https://www.sqlite.org/lang_upsert.html
- SQLite transactions：https://www.sqlite.org/lang_transaction.html
- Python sqlite3：https://docs.python.org/3/library/sqlite3.html
- DiskCache：https://grantjenks.com/docs/diskcache/
- requests-cache expiration：https://requests-cache.readthedocs.io/en/stable/user_guide/expiration.html

## 采用的语义

- 候选列表继续按规范化用户意图复用。
- 视频证据按视频 ID 保存一个完整性快照，记录是否包含评论以及 minimal/full 保留级别。
- 资源验证按规范化 locator 保存，并记录 none/core/all 验证范围。
- 视频证据和资源验证默认有效七天；过期数据保留在本地，但不会作为 cache hit 返回。
- 高完整性缓存可以满足低完整性请求，反方向不允许。
- 读取缓存发生在请求预算判断之前，因此离线模式或运行级 412 熔断后仍能使用已经完成的工作。
- 缓存命中不刷新过期时间，避免旧结果因反复读取而永久保持“新鲜”。
- 缓存读取返回 `cached: true`，运行事件记录 `cache_hit`，让报告明确区分本地复用与实时检查。

## 迁移与隐私

- 启动时为旧 `resource` 表增量增加 `verification_scope`，不删除已有行。
- 旧资源记录默认视为 `none`，不会错误满足 core/all 验证。
- 旧 evidence 行没有完整性快照，因此不会直接命中；完成一次新的深读后自动建立快照。
- 敏感属性过滤规则保持不变。minimal 证据已经在读取适配器中限长，缓存不再做第二次截断；
  full evidence 只有显式启用完整文本保留时才可作为 full cache hit。
