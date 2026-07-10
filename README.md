# Amia Plugin Send

`Amia-plugin-send` 是 Mizuki Bot 的群聊活动统计插件，不是通用消息输出层。它在 OneBot V11 消息事件中记录经过作用域隔离的群聊/私聊活动，并为其他插件提供 `StatsProvider`。

## 身份与统计口径

每条记录至少以以下键隔离：

```text
adapter_type + adapter_instance_id + bot_app_id + bot_id
context_type + context_id + gensokyo_user_id + date
```

- 本群 DAU：指定群、指定日期内的不同 `gensokyo_user_id`。
- 实例活跃用户数：只有 `amia_send_cross_context_user_id_stable=true` 且存在 AppID scope 时才启用。
- 绑定合并 DAU：优先使用 qbind 提供的 `canonical_user_id`；未绑定用户仍按完整下游 scope 计数。
- `self_id` 在当前 Gensokyo 配置中是 UIN，不能当作 AppID。插件默认只读 `H:\Amia-Develop\qqbot\config.yml` 提取 AppID；可用显式 NoneBot 配置覆盖。

## 存储与迁移安全

新库使用 SQLite WAL，并将写入汇入有界批处理队列。核心表为：

- `activity_daily`
- `activity_hourly`
- `legacy_daily_metrics`
- `schema_migrations`

旧 `msg_stats`、`private_stats`、`hourly_stats`、`traffic_stats` 不会在插件启动时自动迁移。检测到仅包含旧表的数据库时，插件拒绝写入并提示先执行迁移预检。`migrations.v0001_activity_v2.migrate()` 必须由显式维护操作调用；它在事务中创建新表，并将旧表重命名为 `*_legacy_bak` 保留。

## 配置

```env
AMIA_SEND_DB_PATH=
AMIA_SEND_ADAPTER_INSTANCE_ID=qqbot-local
AMIA_SEND_BOT_APP_ID=
AMIA_SEND_CROSS_CONTEXT_USER_ID_STABLE=false
AMIA_SEND_WRITER_QUEUE_SIZE=2000
AMIA_SEND_WRITER_BATCH_SIZE=100
AMIA_SEND_WRITER_FLUSH_SECONDS=0.5
AMIA_SEND_RESOLVER_TIMEOUT_SECONDS=0.2
```

未配置 AppID 时群内榜单仍可用，但实例与跨上下文汇总会明确标示为未验证。

## 指令

- `今日发言` / `本月发言` / `今年发言`：本群 Top 10。
- `今日DAU` / `本月DAU` / `今年DAU`：超管活动概览。

## 测试

在项目根目录的虚拟环境中运行：

```powershell
$env:PYTHONPATH = 'H:\Amia-Develop;H:\Amia-Develop\src\plugins'
Set-Location H:\Amia-Develop\src\plugins\Amia-plugin-send
H:\Amia-Develop\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试使用 `tests/plugin_loader.py` 将带连字符的插件目录加载为测试专用别名，不需要也不应创建第二个 `src/plugins/send` 插件目录。
