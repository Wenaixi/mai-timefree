"""mai-timefree 插件的完整配置模型。

每个配置模块对应一个 `[section]`，按功能分组。
所有字段均有详细的 description 和 hint 说明。
"""

from __future__ import annotations

from typing import Any, ClassVar, Dict, Literal

from maibot_sdk import Field, PluginConfigBase

from .constants import (
    ALL_MODES,
    DEFAULT_CANCEL_THRESHOLD,
    DEFAULT_CHECK_INTERVAL,
    DEFAULT_CLEANUP_INTERVAL,
    DEFAULT_DELAY_SECONDS,
    DEFAULT_FREQUENCY_LIMIT,
    DEFAULT_FREQUENCY_WINDOW,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_ACTIVE_PER_STREAM,
    DEFAULT_MAX_ACTIVE_TOTAL,
    DEFAULT_MAX_DELAY,
    DEFAULT_MAX_POSTPONE_RETRIES,
    DEFAULT_MIN_DELAY,
    DEFAULT_MIN_INTERVAL,
    DEFAULT_POSTPONE_DELAY,
    DEFAULT_STALE_TIMEOUT,
    SUPPORTED_CONFIG_VERSION,
)


# ── 工具函数：生成配置项的 i18n / hint ──


def _field_opts(
    *,
    label: str,
    hint: str,
    order: int = 0,
    placeholder: str = "",
    input_type: str = "",
    step: Any = None,
    disabled: bool = False,
    hidden: bool = False,
) -> Dict[str, Any]:
    """构造 Field 的 json_schema_extra 参数。

    Args:
        label: WebUI 上显示的标签。
        hint: 鼠标悬浮时的说明文字（详细的使用解释）。
        order: 排序权重，越小越靠前。
        placeholder: 输入框的占位文本（可选）。
        input_type: 输入框类型，如 "password"（可选）。
        step: 步进值，用于 number 类型输入（可选）。
        disabled: 是否禁用编辑（可选）。
        hidden: 是否在 WebUI 中隐藏（可选）。
    """
    extra: Dict[str, Any] = {
        "label": label,
        "hint": hint,
        "order": order,
    }
    if placeholder:
        extra["placeholder"] = placeholder
    if input_type:
        extra["input_type"] = input_type
    if step is not None:
        extra["step"] = step
    if disabled:
        extra["disabled"] = True
    if hidden:
        extra["hidden"] = True
    return extra


# ═══════════════════════════════════════════════════════════════
# 模块 1: 插件基础设置
# ═══════════════════════════════════════════════════════════════


class PluginSectionConfig(PluginConfigBase):
    """插件基础设置。

    控制插件的启用/停用、配置版本号和日志输出级别。
    """

    __ui_label__: ClassVar[str] = "插件设置"
    __ui_icon__: ClassVar[str] = "package"
    __ui_order__: ClassVar[int] = 0

    enabled: bool = Field(
        default=False,
        description="是否启用 Planner Timer 插件。关闭后所有定时任务不会触发，但已排期的任务保留。",
        json_schema_extra=_field_opts(
            label="启用插件",
            hint="关闭后后台定时器循环停止，已排期的定时任务不会触发，但任务数据保留。重新开启后任务继续生效。",
            order=0,
        ),
    )
    config_version: str = Field(
        default=SUPPORTED_CONFIG_VERSION,
        description="当前配置结构版本号，用于版本迁移。",
        json_schema_extra=_field_opts(
            label="配置版本",
            hint="当前配置的结构版本。如果配置结构有足够大的变动，这里会递增以触发迁移逻辑。",
            order=99,
            disabled=True,
            hidden=True,
        ),
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default=DEFAULT_LOG_LEVEL,
        description="插件日志输出级别。DEBUG 会输出每 tick 的定时器检查结果、每个分支判定日志。",
        json_schema_extra=_field_opts(
            label="日志级别",
            hint="控制插件自身的日志输出详细程度。DEBUG 会输出每 tick 的判定分支日志、任务入队/出队详情，"
                 "用于排查定时器行为。INFO 仅输出关键事件（排期/触发/取消/推迟）。"
                 "WARNING/ERROR 仅在出现异常或预期外情况时输出。",
            order=1,
        ),
    )


# ═══════════════════════════════════════════════════════════════
# 模块 2: 计时核心配置
# ═══════════════════════════════════════════════════════════════


class TimerCoreConfig(PluginConfigBase):
    """计时核心配置。

    控制定时器的主循环行为、默认延迟、时间范围等。
    """

    __ui_label__: ClassVar[str] = "计时核心"
    __ui_icon__: ClassVar[str] = "clock"
    __ui_order__: ClassVar[int] = 1

    default_delay_seconds: int = Field(
        default=DEFAULT_DELAY_SECONDS,
        description="相对模式下的默认延迟秒数。planner 未指定 delay 时使用此值。",
        json_schema_extra=_field_opts(
            label="默认延迟（秒）",
            hint="Planner 调用定时工具时如果未指定 delay 参数，使用此值作为默认延迟。"
                 "建议 60-600 秒。太短（<30 秒）可能导致 planner 循环太快，太长则可能遗忘。",
            order=0,
            step=10,
        ),
    )
    min_delay_seconds: int = Field(
        default=DEFAULT_MIN_DELAY,
        description="相对模式允许的最小延迟秒数。短于此值的 delay 会被截断至此值。",
        json_schema_extra=_field_opts(
            label="最小延迟（秒）",
            hint="任何定时请求的延迟不会低于此值。防止 planner 设置 1 秒这种无意义的快速触发器。"
                 "建议 10-30 秒。",
            order=1,
            step=5,
        ),
    )
    max_delay_seconds: int = Field(
        default=DEFAULT_MAX_DELAY,
        description="相对模式允许的最大延迟秒数。长于此值的 delay 会被截断至此值。",
        json_schema_extra=_field_opts(
            label="最大延迟（秒）",
            hint="定时延迟的上限，防止 planner 设置长达数天的定时任务——长时间无人值守可能造成意外。"
                 "建议 3600-86400 秒（1 小时到 24 小时）。",
            order=2,
            step=60,
        ),
    )
    check_interval_seconds: float = Field(
        default=DEFAULT_CHECK_INTERVAL,
        ge=0.05,
        description="后台定时器 tick 间隔（秒）。每 tick 检查一次是否有到期的任务。",
        json_schema_extra=_field_opts(
            label="检查间隔（秒）",
            hint="后台循环每 tick 扫描待触发列表的间隔。1 秒基本够用。"
                 "如果定时任务数量巨大（>10000），可以适当增大以减少 CPU 消耗。"
                 "最小 0.05 秒，避免 sleep(0) 死循环。",
            order=3,
            step=0.5,
        ),
    )
    allowed_modes: list[str] = Field(
        default_factory=lambda: list(ALL_MODES),
        description="允许 planner 使用的定时模式列表。可勾选部分模式来限制功能。",
        json_schema_extra=_field_opts(
            label="允许的定时模式",
            hint="可在此限制 planner 能使用的定时模式。例如移除 chain 模式来禁止连续定时。"
                 "选项：relative（相对秒数）、absolute（绝对时间）、"
                 "interval（等间隔重复）、chain（触发后自动再排）。",
            order=4,
        ),
    )


# ═══════════════════════════════════════════════════════════════
# 模块 3: 触发前判定（冷却 / 活跃 / 频控 / 人类在场）
# ═══════════════════════════════════════════════════════════════


class TriggerCheckConfig(PluginConfigBase):
    """触发前判定配置。

    定时任务到期后，在真正触发之前执行的各项前置判定。
    每一项都可独立开关，通过 enable_xxx 控制是否启用。
    """

    __ui_label__: ClassVar[str] = "触发前判定"
    __ui_icon__: ClassVar[str] = "shield"
    __ui_order__: ClassVar[int] = 2

    # ── 冷却检查 ──
    enable_cooling_check: bool = Field(
        default=True,
        description="启用冷却检查。检查 planner 最近一次活动距今是否小于取消阈值。",
        json_schema_extra=_field_opts(
            label="启用冷却检查",
            hint="Planner 刚刚活动过（发了消息/执行了规划）时，如果定时正好到了，走取消/推迟逻辑以避免重复唤醒。"
                 "关闭此开关后定时到点直接触发，不关心 planner 是否刚活跃过。",
            order=0,
        ),
    )
    cancel_threshold_seconds: int = Field(
        default=DEFAULT_CANCEL_THRESHOLD,
        description="取消阈值（秒）。Planner 最近活动距今 ≤ 此值 → 直接取消本次定时。",
        json_schema_extra=_field_opts(
            label="取消阈值（秒）",
            hint="如果 planner 最近一次活跃距今 ≤ 此值，说明 planner 刚工作完，"
                 "此时再触发定时会打断节奏。系统会直接取消本次定时并通过消息告知原因。"
                 "范围建议 15-60 秒。",
            order=1,
            step=5,
        ),
    )
    min_interval_seconds: int = Field(
        default=DEFAULT_MIN_INTERVAL,
        description="最小触发间隔（秒）。Planner 最近活动距今 ≥ 此值才允许触发。",
        json_schema_extra=_field_opts(
            label="最小触发间隔（秒）",
            hint="Planner 最近一次活跃距今 ≥ 此值才允许触发定时。"
                 "介于 cancel_threshold（取消）和此值之间时 → 走推迟逻辑。"
                 "此值必须 ≥ cancel_threshold，否则冷却检查无意义。"
                 "建议 60-300 秒。",
            order=2,
            step=10,
        ),
    )

    # ── 活跃度检查 ──
    enable_activity_check: bool = Field(
        default=False,
        description="启用会话活跃度检查。若当前 stream 消息量超过阈值则推迟/取消定时。",
        json_schema_extra=_field_opts(
            label="启用活跃度检查",
            hint="检查当前 stream 最近一段时间内的消息频率是否过高。"
                 "如果 stream 正在热烈讨论，定时提醒可能不合时宜。"
                 "关闭则不检查此维度。",
            order=3,
        ),
    )
    activity_max_messages: int = Field(
        default=10,
        description="活跃度阈值。get_recent 返回的消息数超过此值判定为「活跃」。",
        json_schema_extra=_field_opts(
            label="活跃消息数量阈值",
            hint="get_recent 返回的消息数达到此值，就判定当前 chat 处于活跃状态。"
                 "活跃状态下定时可以选择推迟或取消（取决于 activity_action）。建议 5-20 条。",
            order=4,
        ),
    )
    activity_action: Literal["cancel", "postpone", "ignore"] = Field(
        default="postpone",
        description="活跃度超标时的处理动作：cancel 取消、postpone 推迟、ignore 不处理。",
        json_schema_extra=_field_opts(
            label="活跃度超标处理",
            hint="检测到当前 stream 过于活跃时，选择取消本次定时（cancel）、"
                 "推迟一段时间（postpone）、或忽略活跃度继续触发（ignore）。",
            order=5,
        ),
    )

    # ── 频率限制 ──
    enable_frequency_limit: bool = Field(
        default=False,
        description="启用频率限制。单位时间内每个 stream 最多触发 N 次定时。",
        json_schema_extra=_field_opts(
            label="启用频率限制",
            hint="限制同一个 stream 在单位时间内最多触发的定时次数。"
                 "防止 planner 或者外部因素短时间内反复排期触发。"
                 "关闭则不检查此维度。",
            order=7,
        ),
    )
    frequency_limit_count: int = Field(
        default=DEFAULT_FREQUENCY_LIMIT,
        description="频率上限。窗口期内最多触发的定时次数。",
        json_schema_extra=_field_opts(
            label="频率上限（次数）",
            hint="单位时间窗口内最多允许触发的定时任务数，超出后走 frequency_action。"
                 "建议 3-10 次。",
            order=8,
        ),
    )
    frequency_window_seconds: int = Field(
        default=DEFAULT_FREQUENCY_WINDOW,
        description="频率统计窗口（秒）。",
        json_schema_extra=_field_opts(
            label="频率窗口（秒）",
            hint="在此时间窗口内统计定时触发次数。"
                 "窗口越长行为越平滑，窗口越短越灵敏。建议 1800-3600 秒。",
            order=9,
            step=60,
        ),
    )
    frequency_action: Literal["cancel", "postpone", "drop_silent"] = Field(
        default="drop_silent",
        description="频率超标时的处理动作：cancel 取消并通知、postpone 推迟、drop_silent 静默丢弃。",
        json_schema_extra=_field_opts(
            label="频率超标处理",
            hint="达到频率上限时的处理方式。cancel 会发送取消消息，"
                 "postpone 推迟到窗口期后，drop_silent 静默丢弃不通知。",
            order=10,
        ),
    )

    # ── 优先级穿越 ──
    allow_high_priority_bypass: bool = Field(
        default=True,
        description="高优先级定时任务是否跳过冷却/活跃/频控/人类检查。",
        json_schema_extra=_field_opts(
            label="高优穿越",
            hint="高优先级（high）定时任务可以跳过所有触发前判定直接触发。"
                 "适用于 planner 标记为「紧急」的重要任务。"
                 "低优先级（low）任务的冷却阈值会翻倍。",
            order=14,
        ),
    )


# ═══════════════════════════════════════════════════════════════
# 模块 4: 取消行为
# ═══════════════════════════════════════════════════════════════


class CancelBehaviorConfig(PluginConfigBase):
    """取消行为配置。

    当触发前判定决定取消本次定时时，控制是否发送通知以及通知的格式。
    """

    __ui_label__: ClassVar[str] = "取消行为"
    __ui_icon__: ClassVar[str] = "x-circle"
    __ui_order__: ClassVar[int] = 3

    send_message: bool = Field(
        default=True,
        description="取消定时时是否向 stream 发送系统消息说明原因。",
        json_schema_extra=_field_opts(
            label="发送取消通知",
            hint="取消定时任务时是否发送一条系统消息给对应的 chat stream，"
                 "说明被取消的原因和原计划内容。关闭后静默取消不通知。",
            order=0,
        ),
    )
    message_cooling: str = Field(
        default="❌ [计划取消] 定时任务已取消：您刚刚进行过操作（距上次操作仅 {delta} 秒），本次计划「{note}」不再执行。",
        description="冷却检查导致取消时的消息模板。可用变量：{note}{delta}{task_id}{priority}{created_at}",
        json_schema_extra=_field_opts(
            label="冷却取消消息",
            hint="冷却检查不通过导致取消时发送的消息模板。"
                 "可用变量：{note}=原计划内容、{delta}=距上次活跃秒数、"
                 "{task_id}=任务 ID、{priority}=优先级、{created_at}=排期时间。",
            order=1,
            placeholder="示例：❌ [计划取消] {note}（距上次操作 {delta} 秒，已取消）",
        ),
    )
    message_activity: str = Field(
        default="❌ [计划取消] 定时任务已取消：当前会话活跃，本次计划「{note}」不再执行。",
        description="活跃度检查导致取消时的消息模板。",
        json_schema_extra=_field_opts(
            label="活跃取消消息",
            hint="会话活跃度过高导致取消时发送的消息。",
            order=2,
        ),
    )
    message_frequency: str = Field(
        default="❌ [计划取消] 定时任务已取消：达到触发频率上限，本次计划「{note}」不再执行。",
        description="频率限制导致取消时的消息模板。",
        json_schema_extra=_field_opts(
            label="频率取消消息",
            hint="频率限制导致取消时发送的消息。",
            order=3,
        ),
    )
    message_generic: str = Field(
        default="❌ [计划取消] 定时任务已取消（{reason}），计划：「{note}」。",
        description="通用取消消息模板（未匹配到具体原因时的兜底）。",
        json_schema_extra=_field_opts(
            label="通用取消消息",
            hint="未匹配到具体取消原因时的兜底消息。{reason} 会包含具体的原因文本。",
            order=4,
        ),
    )


# ═══════════════════════════════════════════════════════════════
# 模块 5: 推迟行为
# ═══════════════════════════════════════════════════════════════


class PostponeBehaviorConfig(PluginConfigBase):
    """推迟行为配置。

    当触发前判定建议推迟而非取消时，控制推迟多久、重试次数上限、通知格式。
    """

    __ui_label__: ClassVar[str] = "推迟行为"
    __ui_icon__: ClassVar[str] = "clock-rewind"
    __ui_order__: ClassVar[int] = 4

    send_message: bool = Field(
        default=True,
        description="推迟时是否向 stream 发送系统消息说明原因和新的触发时间。",
        json_schema_extra=_field_opts(
            label="发送推迟通知",
            hint="推迟定时任务时是否发送一条系统消息说明推迟原因和新的触发时间。",
            order=0,
        ),
    )
    postpone_delay_seconds: int = Field(
        default=DEFAULT_POSTPONE_DELAY,
        description="默认推迟延迟（秒）。每次推迟后，新的触发时间 = now + 此值。",
        json_schema_extra=_field_opts(
            label="推迟延迟（秒）",
            hint="触发被推迟时，将从当前时间向后推迟此秒数。"
                 "太短可能再次碰触冷却区，太长则失去定时意义。建议 30-180 秒。",
            order=1,
            step=10,
        ),
    )
    max_retries: int = Field(
        default=DEFAULT_MAX_POSTPONE_RETRIES,
        description="最大推迟重试次数。超过此值后任务被完全取消。",
        json_schema_extra=_field_opts(
            label="最大重试次数",
            hint="一个定时任务最多能被推迟（自动重试）几次。"
                 "超过后直接取消并发送取消通知。0 表示第一次触发失败就直接取消。"
                 "建议 1-5 次。",
            order=2,
        ),
    )
    message_cooling: str = Field(
        default="⏳ [计划推迟] 定时任务已推迟：您刚刚操作过（{delta} 秒前），将在 {postpone_seconds} 秒后重试。计划：「{note}」（推迟 {postpone_count}/{max_retries} 次）",
        description="冷却不通过时推迟的消息模板。",
        json_schema_extra=_field_opts(
            label="冷却推迟消息",
            hint="冷却检查不通过导致推迟时发送的消息。"
                 "额外可用变量：{postpone_seconds}=推迟秒数、"
                 "{postpone_time}=新的触发时间格式化、{postpone_count}=已推迟次数、"
                 "{max_retries}=最大重试次数。",
            order=3,
        ),
    )
    message_activity: str = Field(
        default="⏳ [计划推迟] 定时任务已推迟：当前会话活跃，将在 {postpone_seconds} 秒后重试。计划：「{note}」",
        description="活跃度过高时推迟的消息模板。",
        json_schema_extra=_field_opts(
            label="活跃推迟消息",
            hint="活跃度过高导致推迟时发送的消息。",
            order=4,
        ),
    )
    message_generic: str = Field(
        default="⏳ [计划推迟] 定时任务已推迟（{reason}），将在 {postpone_seconds} 秒后重试。计划：「{note}」",
        description="通用推迟消息模板（兜底）。",
        json_schema_extra=_field_opts(
            label="通用推迟消息",
            hint="未匹配到具体原因的兜底推迟消息。",
            order=5,
        ),
    )


# ═══════════════════════════════════════════════════════════════
# 模块 6: 资源限制
# ═══════════════════════════════════════════════════════════════


class LimitConfig(PluginConfigBase):
    """资源限制配置。

    控制同时活跃的定时任务数量上限、过期清理、去重策略等。
    """

    __ui_label__: ClassVar[str] = "资源限制"
    __ui_icon__: ClassVar[str] = "server"
    __ui_order__: ClassVar[int] = 5

    max_active_per_stream: int = Field(
        default=DEFAULT_MAX_ACTIVE_PER_STREAM,
        description="每个 stream 的最大活跃定时任务数。超过后新排期会被拒绝并告知 planner。",
        json_schema_extra=_field_opts(
            label="每流最大任务数",
            hint="每个 chat stream 中最多同时存在的待触发定时任务数。"
                 "超过后 planner 再排期会收到失败响应。防止单个 stream 排期过多。"
                 "建议 5-20。",
            order=0,
        ),
    )
    max_active_total: int = Field(
        default=DEFAULT_MAX_ACTIVE_TOTAL,
        description="全局最大活跃定时任务数。防止插件整体资源超限。",
        json_schema_extra=_field_opts(
            label="全局最大任务数",
            hint="所有 stream 汇总的待触发定时任务总数上限。超过后新排期会被拒绝。"
                 "建议 20-100。",
            order=1,
        ),
    )
    stale_timeout_seconds: int = Field(
        default=DEFAULT_STALE_TIMEOUT,
        description="定时任务过期超时（秒）。超过此值未触发的任务会被自动清理。",
        json_schema_extra=_field_opts(
            label="过期超时（秒）",
            hint="一个定时任务从创建到当前时间超过此值仍未触发，将被自动清理。"
                 "防止因异常情况（如 stream 消失）导致任务永远挂起。"
                 "建议 3600-86400 秒（1-24 小时）。",
            order=2,
            step=60,
        ),
    )
    cleanup_interval_seconds: int = Field(
        default=DEFAULT_CLEANUP_INTERVAL,
        description="自动清理检查间隔（秒）。周期性扫描并清理过期/完成的任务。",
        json_schema_extra=_field_opts(
            label="清理间隔（秒）",
            hint="清扫线程多久执行一次。过期的、已触发的、被取消的旧任务会被清理。"
                 "建议 60-600 秒。",
            order=3,
            step=10,
        ),
    )
    allow_duplicate_notes: bool = Field(
        default=False,
        description="是否允许同一条 note 文本的定时任务排期多次。",
        json_schema_extra=_field_opts(
            label="允许重复排期（同内容）",
            hint="默认关闭，即同一个 note 文本只能有一个待触发的定时。"
                 "如果 planner 不小心排了同一个任务两次，后一次会被拒绝。",
            order=4,
        ),
    )
    auto_cleanup_on_trigger: bool = Field(
        default=True,
        description="定时触发后是否自动清理该 stream 内同 note 的待处理任务，避免积累重复。",
        json_schema_extra=_field_opts(
            label="触发后去重清理",
            hint="一个定时任务触发后，自动清理同 stream 内 same note 的待触发任务。"
                 "适用于 interval/chain 模式防止重复积累。",
            order=5,
        ),
    )


# ═══════════════════════════════════════════════════════════════
# 模块 7: 消息模板
# ═══════════════════════════════════════════════════════════════


class MessageTemplateConfig(PluginConfigBase):
    """触发消息模板配置。

    定时任务正常触发时的消息内容和格式。
    注意：取消和推迟的模板在对应的取消/推迟行为模块中。
    """

    __ui_label__: ClassVar[str] = "消息模板"
    __ui_icon__: ClassVar[str] = "message-square"
    __ui_order__: ClassVar[int] = 6

    triggered: str = Field(
        default="⏰ [计划任务] 提醒：{note}",
        description="定时正常触发时发送的消息。",
        json_schema_extra=_field_opts(
            label="触发消息",
            hint="定时任务正常触发时向 stream 发送的消息。"
                 "可用变量：{note}=计划说明、{task_id}=任务 ID、"
                 "{priority}=优先级、{mode}=定时模式、{delay}=原始延迟。",
            order=0,
            placeholder="示例：⏰ [计划任务] 提醒：{note}",
        ),
    )
    triggered_high_priority: str = Field(
        default="⚡ [计划任务 高优] 提醒：{note}",
        description="高优先级定时任务触发时的特殊消息。",
        json_schema_extra=_field_opts(
            label="高优触发消息",
            hint="高优先级定时任务触发时使用不同的消息格式以示区分。",
            order=1,
        ),
    )
    triggered_interval: str = Field(
        default="⏰ [周期任务 第{n}次] 提醒：{note}",
        description="interval（间隔重复）模式触发时的消息。",
        json_schema_extra=_field_opts(
            label="周期触发消息",
            hint="interval 模式的触发消息。额外可用变量："
                 "{n}=当前是第几次触发、{total}=总次数（0 为无限）。",
            order=2,
        ),
    )
    cleared_all: str = Field(
        default="🗑️ [计划清除] 已取消所有定时任务（共 {count} 个）。",
        description="清除所有定时任务时发送的消息。",
        json_schema_extra=_field_opts(
            label="全部清除消息",
            hint="调用清除工具清空所有定时时发送的消息。{count}=被取消的任务数。",
            order=3,
        ),
    )
    cleared_stream: str = Field(
        default="🗑️ [计划清除] 已取消本会话的定时任务（共 {count} 个）。",
        description="清除当前 stream 的定时任务时发送的消息。",
        json_schema_extra=_field_opts(
            label="按流清除消息",
            hint="按 stream 清除定时时发送的消息。",
            order=4,
        ),
    )
    schedule_success: str = Field(
        default="✅ [计划已排期] {mode}模式，{trigger_time_desc}。计划：「{note}」",
        description="定时任务排期成功后返回给 planner 的消息。",
        json_schema_extra=_field_opts(
            label="排期成功消息",
            hint="定时任务成功排期后通过 Tool 返回值告知 planner 的消息。"
                 "额外变量：{trigger_time_desc}=触发时间的友好描述。",
            order=5,
        ),
    )
    schedule_rejected: str = Field(
        default="❌ [排期失败] {reason}",
        description="定时任务排期被拒绝时返回给 planner 的消息。",
        json_schema_extra=_field_opts(
            label="排期失败消息",
            hint="定时任务排期被拒绝时的返回消息。{reason}=拒绝原因。",
            order=6,
        ),
    )


# ═══════════════════════════════════════════════════════════════
# 模块 8: 调试配置
# ═══════════════════════════════════════════════════════════════


class DebugConfig(PluginConfigBase):
    """调试配置。

    当需要排查插件行为时启用，输出更详细的运行状态。
    """

    __ui_label__: ClassVar[str] = "调试"
    __ui_icon__: ClassVar[str] = "bug"
    __ui_order__: ClassVar[int] = 7

    verbose_logging: bool = Field(
        default=False,
        description="启用详细日志。每 tick 输出定时器检查详情、任务队列快照。",
        json_schema_extra=_field_opts(
            label="详细日志",
            hint="启用后每个 tick 都会输出当前待触发任务数、最近 t ick 耗时、"
                 "每项判定结果等。建议仅排查问题时开启，正常运行时关闭以减少日志噪音。",
            order=0,
        ),
    )
    dump_task_queue: bool = Field(
        default=False,
        description="定时 dump 任务队列内容到日志。",
        json_schema_extra=_field_opts(
            label="Dump 任务队列",
            hint="每隔 dump_interval_seconds 秒将当前所有待触发任务的信息输出到 debug 日志。"
                 "包含每个任务的 ID、模式、stream、触发时间、note 等。仅 verbose_logging 开启时生效。",
            order=1,
        ),
    )
    dump_interval_seconds: int = Field(
        default=60,
        description="任务队列 dump 间隔（秒）。",
        json_schema_extra=_field_opts(
            label="Dump 间隔（秒）",
            hint="每隔此秒数输出一次任务队列快照。仅 verbose_logging + dump_task_queue 同时启用时生效。",
            order=2,
            step=10,
        ),
    )
    trace_all_decisions: bool = Field(
        default=False,
        description="追踪所有触发前判定的决策路径（冷却→活跃→频控→人类）。即使最终允许触发也输出日志。",
        json_schema_extra=_field_opts(
            label="追踪全部分支",
            hint="启用后，即使某个判定通过了（允许触发），也输出详细的判定日志。"
                 "关闭时仅输出「阻止了触发」的判定日志。"
                 "建议仅排查问题时启用。",
            order=3,
        ),
    )


# ═══════════════════════════════════════════════════════════════
# 顶层配置聚合
# ═══════════════════════════════════════════════════════════════


class PlannerTimerConfig(PluginConfigBase):
    """Planner Timer 插件完整配置。

    聚合所有子配置模块。每个子配置对应 `config.toml` 中的一个 `[section]`。
    """

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    timer: TimerCoreConfig = Field(default_factory=TimerCoreConfig)
    trigger_check: TriggerCheckConfig = Field(default_factory=TriggerCheckConfig)
    cancel: CancelBehaviorConfig = Field(default_factory=CancelBehaviorConfig)
    postpone: PostponeBehaviorConfig = Field(default_factory=PostponeBehaviorConfig)
    limits: LimitConfig = Field(default_factory=LimitConfig)
    messages: MessageTemplateConfig = Field(default_factory=MessageTemplateConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)

    @classmethod
    def from_mapping(cls, raw_config: Any, logger: Any) -> "PlannerTimerConfig":
        """从 Runner 注入的原始配置字典解析配置。"""
        return cls.model_validate(dict(raw_config) if isinstance(raw_config, dict) else {})

    def get_log_level(self) -> int:
        """将日志级别字符串转换为 logging 级别常量。"""
        import logging
        return getattr(logging, self.plugin.log_level, logging.INFO)

    def should_connect(self) -> bool:
        """判断插件是否应启动后台定时循环。"""
        return self.plugin.enabled
