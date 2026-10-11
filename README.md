# mai-timefree

为 MaiBot Planner 提供定时调度能力。Planner 通过工具调用排期定时任务，到期后通过 Maisaka 主动触发 API 非显式注入到 Planner 上下文，让 Maisaka 自行决定是否回复及如何表达。

maimaimaimaimaimaimaimaimaimaimaimaimaimaimaimai
无限循环的麦麦
麦麦终将踏上新一轮的循环

## 安装

将 `mai-timefree` 目录复制到 MaiBot 的 `plugins/` 目录下，重启即可。

## 配置

编辑 `plugins/mai-timefree/config.toml`：

```toml
[plugin]
enabled = true
# log_level: DEBUG / INFO / WARNING / ERROR / CRITICAL
log_level = "INFO"

# 计时核心
[timer]
default_delay_seconds = 300   # 默认延迟（秒）
min_delay_seconds = 10        # 最小延迟下限
max_delay_seconds = 86400     # 最大延迟上限（24h）
check_interval_seconds = 1.0  # 后台 tick 间隔
allowed_modes = ["relative", "absolute", "interval", "chain"]

# 触发前判定
[trigger_check]
enable_cooling_check = true       # 冷却检查：planner 刚活跃过时取消/推迟
cancel_threshold_seconds = 30     # 距上次活跃 ≤ 此值 → 取消
min_interval_seconds = 60         # 距上次活跃 < 此值 → 推迟
enable_activity_check = false     # 活跃度检查
activity_max_messages = 10
activity_action = "postpone"      # cancel / postpone / ignore
enable_frequency_limit = false    # 频率限制
frequency_limit_count = 5
frequency_window_seconds = 3600
frequency_action = "drop_silent"  # cancel / postpone / drop_silent
allow_high_priority_bypass = true # 高优跳过所有检查

# 取消行为
[cancel]
send_message = true
message_cooling = "❌ [计划取消] 定时任务已取消：您刚刚进行过操作（距上次操作仅 {delta} 秒），本次计划「{note}」不再执行。"
message_activity = "❌ [计划取消] 定时任务已取消：当前会话活跃，本次计划「{note}」不再执行。"
message_frequency = "❌ [计划取消] 定时任务已取消：达到触发频率上限，本次计划「{note}」不再执行。"
message_generic = "❌ [计划取消] 定时任务已取消（{reason}），计划：「{note}」。"

# 推迟行为
[postpone]
send_message = true
postpone_delay_seconds = 60
max_retries = 3
message_cooling = "⏳ [计划推迟] 定时任务已推迟：您刚刚操作过（{delta} 秒前），将在 {postpone_seconds} 秒后重试。计划：「{note}」（推迟 {postpone_count}/{max_retries} 次）"
message_activity = "⏳ [计划推迟] 定时任务已推迟：当前会话活跃，将在 {postpone_seconds} 秒后重试。计划：「{note}」"
message_generic = "⏳ [计划推迟] 定时任务已推迟（{reason}），将在 {postpone_seconds} 秒后重试。计划：「{note}」"

# 资源限制
[limits]
max_active_per_stream = 10
max_active_total = 50
stale_timeout_seconds = 7200
allow_duplicate_notes = false
auto_cleanup_on_trigger = true

# 消息模板
[messages]
triggered = "⏰ [计划任务] 提醒：{note}"
triggered_high_priority = "⚡ [计划任务 高优] 提醒：{note}"
triggered_interval = "⏰ [周期任务 第{n}次] 提醒：{note}"
cleared_all = "🗑️ [计划清除] 已取消所有定时任务（共 {count} 个）。"
cleared_stream = "🗑️ [计划清除] 已取消本会话的定时任务（共 {count} 个）。"
schedule_success = "✅ [计划已排期] {mode}模式，{trigger_time_desc}。计划：「{note}」"
schedule_rejected = "❌ [排期失败] {reason}"

# 调试
[debug]
verbose_logging = false
dump_task_queue = false
dump_interval_seconds = 60
trace_all_decisions = false
```

## 使用

Planner 通过调用以下两个工具来使用：

### `planner_schedule` — 排期定时任务

| 参数 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `mode` | string | ✅ | — | `relative` 相对延迟 / `absolute` 绝对时间 / `interval` 等间隔重复 / `chain` 触发后自动再排 |
| `note` | string | ✅ | — | 提醒内容 |
| `delay_seconds` | int |    | 300 | 相对/interval/chain 模式的延迟秒数 |
| `specific_time` | string |    | — | 绝对时间：`HH:MM` 或 `YYYY-MM-DD HH:MM` |
| `priority` | string |    | medium | `high` / `medium` / `low` |
| `behavior` | string |    | normal | `normal` / `silent` / `strict` |
| `max_chain` | int |    | 0 | interval/chain 最大重复次数，0=无限 |

### `planner_schedule_clear` — 取消定时任务

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `scope` | string | stream | `all` 全局 / `stream` 仅当前会话 |
| `note_filter` | string | — | 可选，仅取消 note 包含此文本的任务 |

### 触发流程

```
到期 → 高优穿越？
  ├─ yes → 直接触发 → maisaka.proactive.trigger() 非显式注入
  └─ no  → 冷却检查 → 活跃度检查 → 频率限制 → 触发
```

触发时通过 `maisaka.proactive.trigger()` 非显式注入到 Maisaka Planner 上下文：
- 不发固定文本到聊天
- 不伪装用户消息
- Maisaka 自行决定是否回复、如何表达

# ⚠️ 史诗级免责声明

## 一、插件内容过大

本插件包含 7 个配置模块、30+ 配置项、8 个子功能模块、4 种定时模式、3 级触发前判定。虽然核心逻辑只有几百行，但配置模型的代码行数是引擎代码的两倍。你可能只需要其中 10% 的功能，但剩下 90% 就放在那里——不吃内存，不耗 CPU，只是看着有点多。

## 二、与其他插件/功能不兼容

- 其他也向 planner 暴露工具的插件（同名冲突）
- 修改 Maisaka 主动触发行为的插件
- 操作 stream 会话生命周期的插件
- 你的第三行代码

## 三、功能性免责

- 所有任务在内存中，进程重启、插件卸载、崩溃都会丢光。没有持久化。
- 冷却检查只追踪通过本插件 tool 排期时的活跃。其他 plugin 不更新冷却状态。
- 高优先级穿越跳过所有检查——你选的。
- Maisaka 收到主动触发后是否回复、回复什么，取决于它当时的上下文和人格。不保证一定有可见回复。
- 系统内置 cron 与本插件无关。两者同时用可能出现"时间到了"×2。

## 四、宇宙级免责

本插件按「AS IS」提供。作者不对以下后果负责，包括但不限于：
- 错过了定时提醒
- 在错误的时间收到了提醒
- 提醒内容被 Maisaka 自由发挥到面目全非
- 服务器过热
- 猫踩键盘排期了一万个定时
- 你女朋友因为你没回消息生气了

使用即接受。不接受就 `rm -rf plugins/mai-timefree/`。

## 许可证

AGPL v3.0
