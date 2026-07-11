# Amia-plugin-send

`Amia-plugin-send` 是 Mizuki Bot 的消息活动统计插件。它监听 OneBot V11 消息事件，将群聊和私聊活动写入 SQLite，并通过 `amia-core` 注册名为 `send` 的 `StatsProvider`，供 `group-insight`、`profile` 等插件读取。

它不是通用消息发送层，也不负责欢迎消息、公告或业务指令转发。

## 当前能力

- 记录每日和小时级消息活动。
- 记录消息数量、估算字节数、显示名和首次/最后出现时间。
- 按 `self_id + group_id` 隔离群聊排行和群活跃汇总。
- 提供今日、本月、今年的群内 Top 10。
- 提供超管活动概览。
- 通过 IdentityResolver 保存可选的 canonical user ID。
- 使用有界异步队列和批量写入降低 SQLite 压力。
- 数据库连续失败或队列溢出时写入 dead-letter JSONL。
- 检测到旧库时拒绝自动写入，不在启动阶段迁移生产数据。

## 统计作用域

每条记录包含：

```text
adapter_type
adapter_instance_id
bot_id
bot_app_id
context_type
context_id
gensokyo_user_id
canonical_user_id
date
```

主要口径：

- 群排行：当前 `self_id + group_id` 内统计。
- 群 DAU：指定群和日期内不同 `gensokyo_user_id`。
- 用户活动：当前 `self_id` 内统计，避免多个 Bot 的同 ID 数据混合。
- 实例活跃用户：只有显式配置 AppID 且确认跨上下文 ID 稳定时启用。
- merged DAU：使用历史 canonical 映射归并绑定前后记录；检测到冲突映射时返回不可用。

所有范围查询采用半开区间：

```text
start_date <= date < end_date
```

## 指令

群聊排行：

```text
今日发言 / 今日排行榜
本月发言 / 本月排行榜
今年发言 / 今年排行榜
```

超管活动概览：

```text
今日DAU / 全群统计 / bot数据
本月DAU / 本月统计
今年DAU / 年度统计
```

未配置可验证的实例身份时，群排行仍可用；跨群实例 DAU 会明确显示为未验证。

## 数据库

默认数据库：

```text
<插件目录>/data.db
```

主要表：

```text
activity_daily
activity_hourly
legacy_daily_metrics
schema_migrations
```

SQLite 配置：

- WAL 模式。
- busy timeout。
- 批量 upsert。
- 有界写入队列。

## 写入失败处理

数据库批次写入会有限重试。重试仍失败时写入：

```text
<data.db>.dead-letter.jsonl
```

队列溢出的记录也会尝试写入 dead-letter，而不是仅静默丢弃。

运行状态可从 `ActivityWriter` 读取：

```text
dropped_records
last_dropped_at
failed_batches
failed_records
last_failure_at
last_failure_error
```

## 配置

NoneBot 环境变量：

```env
AMIA_SEND_DB_PATH=
AMIA_SEND_ADAPTER_INSTANCE_ID=qqbot-local
AMIA_SEND_BOT_APP_ID=
AMIA_SEND_CROSS_CONTEXT_USER_ID_STABLE=false
AMIA_SEND_WRITER_QUEUE_SIZE=2000
AMIA_SEND_WRITER_BATCH_SIZE=100
AMIA_SEND_WRITER_FLUSH_SECONDS=0.5
AMIA_SEND_RESOLVER_TIMEOUT_SECONDS=0.2
AMIA_SEND_DEAD_LETTER_PATH=
AMIA_SEND_DEAD_LETTER_MAX_BYTES=5242880
AMIA_TIMEZONE=Asia/Shanghai
```

说明：

- `AMIA_SEND_BOT_APP_ID` 必须显式配置；插件不再猜测本地 `qqbot/config.yml` 路径。
- `AMIA_SEND_CROSS_CONTEXT_USER_ID_STABLE` 只有在确认 Gensokyo 跨群 ID 稳定时才可设为 `true`。
- 时区默认 `Asia/Shanghai`。
- dead-letter 默认与数据库同目录。

## Provider 接口

插件启动成功后注册：

```python
registry.register_stats_provider("send", activity_service, replace=True)
```

常用接口：

```text
get_user_activity
get_group_rank
get_group_dau
get_group_activity_summary
get_user_activity_summary
get_instance_active_users
get_merged_dau
get_admin_dashboard_data
```

调用方不应直接查询 Send 的 SQLite，应通过 `StatsProvider` 使用。

## 旧数据库迁移

插件启动不会自动迁移以下旧表：

```text
msg_stats
private_stats
hourly_stats
traffic_stats
```

检测到仅有旧结构时，插件会停止写入并保留原数据。

当前迁移代码仍需完成以下安全项后，才能用于生产库：

- 文件级备份。
- `PRAGMA integrity_check`。
- 部分迁移状态识别。
- 已存在 `*_legacy_bak` 时拒绝继续。
- 迁移前后消息总量校验。
- 失败注入和完整回滚测试。

在这些验收完成前，不要对生产 `data.db` 执行迁移。

## 测试

在项目根目录执行：

```powershell
$env:PYTHONPATH = '<project-root>'
python -m unittest discover -s src/plugins/Amia-plugin-send/tests -v
```

测试范围包括：

- SQLite 初始化和批量写入。
- 群统计作用域。
- `self_id` 用户隔离。
- day/month/year 半开区间。
- 绑定前后 merged DAU 归并。
- dead-letter 写入。
- 旧库检测和迁移预检。

## 运行边界

- 不直接修改 Gensokyo idmap。
- 不把昵称作为身份主键。
- 不自动迁移生产数据库。
- 不将实例 DAU 在未验证条件下伪装成准确数字。
- `data.db`、WAL、SHM 和 dead-letter 均属于运行数据，不应提交到 Git。