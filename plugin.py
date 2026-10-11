"""mai-timefree 插件。

为 planner 提供定时能力（relative/absolute/interval/chain），
到期后经过触发前判定链进行提醒。
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

from maibot_sdk import MaiBotPlugin, Tool
from maibot_sdk.types import ToolParameterInfo, ToolParamType

from .config import PlannerTimerConfig, PluginSectionConfig, TimerCoreConfig
from .scheduler import MessageRenderer, SchedulerEngine, ScheduledTask


# ─────────────────────────────────────────────────────────────────
# 插件主类
# ─────────────────────────────────────────────────────────────────


class PlannerTimerPlugin(MaiBotPlugin):
    """为 planner 提供定时调度能力的插件。"""

    config_model = PlannerTimerConfig

    def __init__(self) -> None:
        super().__init__()
        self._engine: Optional[SchedulerEngine] = None
        self._initialized: bool = False

    # ── 生命周期 ──

    async def on_load(self) -> None:
        """插件加载时初始化调度引擎。"""
        self.ctx.logger.debug("PlannerTimerPlugin on_load 触发")

        cfg = self._config_or_fallback()

        # 初始化调度引擎
        self._engine = SchedulerEngine(
            logger=self.ctx.logger,
            ctx_send_text=self.ctx.send.text,
            ctx_maisaka_trigger=self.ctx.maisaka.proactive.trigger,
            ctx_message=self.ctx.message,
            config_getter=self._config_or_fallback,
        )

        # 如果插件已启用，启动后台循环
        if cfg.plugin.enabled:
            self._engine.start()
            self.ctx.logger.info("PlannerTimer 插件已加载，调度引擎已启动")
        else:
            self.ctx.logger.info("PlannerTimer 插件已加载，调度引擎待启用")

        self._initialized = True

    async def on_unload(self) -> None:
        """插件卸载时停止调度引擎。"""
        self.ctx.logger.debug("PlannerTimerPlugin on_unload 触发")

        if self._engine is not None:
            await self._engine.stop()
            self._engine = None

        self._initialized = False
        self.ctx.logger.info("PlannerTimer 插件已卸载")

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str) -> None:
        """配置热重载：只更新配置，不重建调度引擎，避免丢失已排期任务。

        engine 内部每次都会通过 config_getter 读最新配置，所以无需重启。
        若用户关闭插件（enabled: true → false），才需要 stop 引擎。
        """
        del version
        self.ctx.logger.debug("PlannerTimerPlugin on_config_update 触发: scope=%s", scope)

        if scope != "self":
            return

        self.set_plugin_config(config_data)
        cfg = self._config_or_fallback()

        # 仅在 enabled 由 true→false 时才停引擎；其它情况保持运行
        engine = self._engine
        if engine is not None and not cfg.plugin.enabled:
            await engine.stop()
            self.ctx.logger.info("PlannerTimer 配置已更新，引擎已停止")
        else:
            self.ctx.logger.info("PlannerTimer 配置已更新，引擎保持运行（任务不丢失）")

    # ── 工具：planner_schedule ──

    @Tool(
        "planner_schedule",
        description="排期一个定时任务。到期后系统会发送提醒消息到当前会话。支持多种定时模式。",
        parameters=[
            ToolParameterInfo(
                name="mode",
                param_type=ToolParamType.STRING,
                description="定时模式："
                            "relative=相对延迟（delay 秒后触发）、"
                            "absolute=绝对时间（指定具体时间）、"
                            "interval=等间隔重复（每 delay 秒触发一次）、"
                            "chain=触发后自动再排（delay 秒后触发，触发后再排）。",
                required=True,
                enum_values=["relative", "absolute", "interval", "chain"],
            ),
            ToolParameterInfo(
                name="delay_seconds",
                param_type=ToolParamType.INTEGER,
                description="相对模式/interval模式/chain模式的延迟秒数。默认 300 秒（5 分钟）。",
                required=False,
                default=300,
            ),
            ToolParameterInfo(
                name="specific_time",
                param_type=ToolParamType.STRING,
                description="绝对时间模式下使用。格式：YYYY-MM-DD HH:MM 或 HH:MM（今天的剩余时间）。",
                required=False,
                default="",
            ),
            ToolParameterInfo(
                name="note",
                param_type=ToolParamType.STRING,
                description="提醒内容说明。触发时会包含此说明。",
                required=True,
            ),
            ToolParameterInfo(
                name="priority",
                param_type=ToolParamType.STRING,
                description="优先级。high=跳过所有触发前检查直接触发、"
                            "medium=正常检查、low=检查阈值翻倍。",
                required=False,
                default="medium",
                enum_values=["high", "medium", "low"],
            ),
            ToolParameterInfo(
                name="behavior",
                param_type=ToolParamType.STRING,
                description="触发行为。normal=正常发送消息、"
                            "silent=静默触发不发消息（仅后台记录）、"
                            "strict=严格模式（所有检查必须通过）。",
                required=False,
                default="normal",
                enum_values=["normal", "silent", "strict"],
            ),
            ToolParameterInfo(
                name="max_chain",
                param_type=ToolParamType.INTEGER,
                description="chain/interval 模式下最多重复次数。0=无限重复。默认 0。",
                required=False,
                default=0,
            ),
        ],
    )
    async def handle_planner_schedule(
        self,
        mode: str = "relative",
        delay_seconds: int = 300,
        specific_time: str = "",
        note: str = "",
        priority: str = "medium",
        behavior: str = "normal",
        max_chain: int = 0,
        stream_id: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """处理 planner 的定时排期请求。"""

        if not self._engine:
            return {"name": "planner_schedule", "content": "❌ 插件尚未就绪，请稍后再试"}

        # 路由信息（通过 stream_id 定位，timers 触发时直接发送到该 stream）
        cfg = self._config_or_fallback()

        # ── 参数校验 ──
        if not note:
            return {"name": "planner_schedule", "content": "❌ note（提醒内容）不能为空"}
        if not stream_id:
            return {"name": "planner_schedule", "content": "❌ 缺少 stream_id，无法排期"}

        # 规范化 mode
        mode = mode.lower().strip()
        if mode not in ("relative", "absolute", "interval", "chain"):
            return {"name": "planner_schedule", "content": f"❌ 不支持的定时模式: {mode}。可选: relative, absolute, interval, chain"}

        if mode not in cfg.timer.allowed_modes:
            return {"name": "planner_schedule", "content": f"❌ 模式 '{mode}' 已被管理员限制。请联系管理员调整 timer.allowed_modes 配置。"}

        # 规范化 priority
        priority = priority.lower().strip()
        if priority not in ("high", "medium", "low"):
            priority = "medium"

        # 规范化 behavior
        behavior = behavior.lower().strip()
        if behavior not in ("normal", "silent", "strict"):
            behavior = "normal"

        # ── 计算触发时间 ──
        now = time.time()
        trigger_time = 0.0
        time_desc = ""

        if mode in ("relative", "interval", "chain"):
            delay_seconds = max(cfg.timer.min_delay_seconds, min(delay_seconds, cfg.timer.max_delay_seconds))
            trigger_time = now + delay_seconds
            time_desc = f"{delay_seconds} 秒后（约 {datetime.fromtimestamp(trigger_time).strftime('%H:%M')}）"

        elif mode == "absolute":
            if not specific_time:
                # 未指定时间，默认 300 秒
                trigger_time = now + 300
                time_desc = "未指定时间，默认 5 分钟后"
            else:
                parsed = self._parse_absolute_time(specific_time)
                if parsed is None:
                    return {"name": "planner_schedule", "content": f"❌ 时间格式无效: {specific_time}。请使用 YYYY-MM-DD HH:MM 或 HH:MM。"}
                trigger_time = parsed
                time_desc = datetime.fromtimestamp(trigger_time).strftime("%Y-%m-%d %H:%M")

        # ── 构造任务 ──
        task = ScheduledTask(
            mode=mode,
            trigger_time=trigger_time,
            stream_id=stream_id,
            note=note,
            priority=priority,
            behavior=behavior,
            interval_seconds=delay_seconds if mode in ("interval", "chain") else 0,
            max_chain=max_chain,
        )

        # ── 排期 ──
        task_id = self._engine.schedule(task)
        if task_id is None:
            # 排期被拒绝，查找原因
            msg = self._build_rejection_reason(task, cfg)
            return {"name": "planner_schedule", "content": msg}

        # ── 标记活跃度 ──
        self._engine.touch_activity(stream_id)

        # ── 成功返回 ──
        success_msg = MessageRenderer.render(
            cfg.messages.schedule_success,
            mode=mode,
            trigger_time_desc=time_desc,
            note=note,
            task_id=task_id,
            priority=priority,
            delay=str(delay_seconds),
        )

        self.ctx.logger.info(
            "Planner 排期成功: mode=%s delay=%s trigger=%s note=%s task_id=%s",
            mode, delay_seconds, time_desc, note[:48], task_id,
        )

        return {"name": "planner_schedule", "content": success_msg}

    # ── 工具：planner_schedule_clear ──

    @Tool(
        "planner_schedule_clear",
        description="取消所有（或指定 stream 的）排期中的定时任务。会发送系统消息说明已取消。",
        parameters=[
            ToolParameterInfo(
                name="scope",
                param_type=ToolParamType.STRING,
                description="清除范围：'all'=全局所有，'stream'=仅当前会话。",
                required=False,
                default="stream",
                enum_values=["all", "stream"],
            ),
            ToolParameterInfo(
                name="note_filter",
                param_type=ToolParamType.STRING,
                description="可选，仅取消 note 包含此文本的任务。留空则取消全部。",
                required=False,
                default="",
            ),
        ],
    )
    async def handle_planner_schedule_clear(
        self,
        scope: str = "stream",
        note_filter: str = "",
        stream_id: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """清除排期中的定时任务。"""
        del kwargs

        if not self._engine:
            return {"name": "planner_schedule_clear", "content": "❌ 插件尚未就绪"}

        cfg = self._config_or_fallback()

        if scope == "all":
            count = self._engine.clear_all()
            msg = MessageRenderer.render(cfg.messages.cleared_all, count=count)
        else:
            if not stream_id:
                return {"name": "planner_schedule_clear", "content": "❌ 缺少 stream_id"}
            count = self._engine.cancel_by_stream(stream_id, note_filter=note_filter)
            msg = MessageRenderer.render(cfg.messages.cleared_stream, count=count)

        # 发送通知
        if count > 0:
            try:
                await self.ctx.send.text(msg, stream_id)
            except Exception:
                self.ctx.logger.error("清除通知发送失败", exc_info=True)

        self.ctx.logger.info("Planner 清除定时: scope=%s note_filter=%s count=%d", scope, note_filter, count)
        return {"name": "planner_schedule_clear", "content": msg}

    # ── 辅助方法 ──

    def _config_or_fallback(self) -> PlannerTimerConfig:
        """获取当前配置，出错时返回默认配置。"""
        try:
            cfg = self.config
            if cfg is not None:
                return cfg
        except Exception as exc:
            self.ctx.logger.warning("获取配置失败，使用默认配置: %s", exc)
        return PlannerTimerConfig()

    @staticmethod
    def _parse_absolute_time(time_str: str) -> Optional[float]:
        """解析绝对时间字符串。

        支持格式：
        - HH:MM → 今天（若已过则明天）
        - YYYY-MM-DD HH:MM → 指定日期时间
        """
        time_str = time_str.strip()
        now = time.time()
        now_dt = datetime.fromtimestamp(now)
        today = now_dt.replace(hour=0, minute=0, second=0, microsecond=0)

        try:
            # 先尝试 HH:MM（今天剩余时间）
            parsed = datetime.strptime(time_str, "%H:%M")
            result = today.replace(hour=parsed.hour, minute=parsed.minute).timestamp()
            if result <= now:
                result += 86400  # 已过，推到明天
            return result
        except ValueError:
            pass

        try:
            # 再尝试 YYYY-MM-DD HH:MM
            parsed = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
            return parsed.timestamp()
        except ValueError:
            pass

        return None

    def _build_rejection_reason(self, task: ScheduledTask, cfg: Any) -> str:
        """构造排期被拒绝时返回给 planner 的说明。"""
        # 检查最常见的拒绝原因
        stream_tasks = self._engine.get_active_tasks(task.stream_id) if self._engine else []
        if len(stream_tasks) >= cfg.limits.max_active_per_stream:
            return f"❌ 排期失败：当前会话已有 {len(stream_tasks)} 个排期（上限 {cfg.limits.max_active_per_stream}）。请先取消一些再排期。"
        return "❌ 排期失败：未知原因。请检查配置限制或稍后重试。"


# ── 插件工厂 ──


def create_plugin() -> PlannerTimerPlugin:
    return PlannerTimerPlugin()
