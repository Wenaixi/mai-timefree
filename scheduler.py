"""mai-timefree 定时调度引擎。

管理定时任务的排期、存储、到期检查和触发。
完全与 plugin 层解耦，所有配置通过构造参数注入。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import uuid4

from .config import PlannerTimerConfig
from .constants import (
    ALL_BEHAVIORS,
    ALL_MODES,
    ALL_PRIORITIES,
    BEHAVIOR_NORMAL,
    BEHAVIOR_SILENT,
    BEHAVIOR_STRICT,
    MODE_ABSOLUTE,
    MODE_CHAIN,
    MODE_INTERVAL,
    MODE_RELATIVE,
    PRIORITY_HIGH,
    PRIORITY_LOW,
    PRIORITY_MEDIUM,
    TASK_CANCELLED,
    TASK_PENDING,
    TASK_POSTPONED,
    TASK_TRIGGERED,
)

# ─────────────────────────────────────────────────────────────────
# 数据类型
# ─────────────────────────────────────────────────────────────────


@dataclass
class ScheduledTask:
    """一次定时任务实例。"""

    task_id: str = field(default_factory=lambda: uuid4().hex[:12])
    mode: str = MODE_RELATIVE
    trigger_time: float = 0.0  # unix timestamp
    stream_id: str = ""
    note: str = ""
    priority: str = PRIORITY_MEDIUM
    behavior: str = BEHAVIOR_NORMAL

    # Interval/chain 特有
    interval_seconds: int = 0
    chain_count: int = 0  # 当前是第几次
    max_chain: int = 0  # 0 = 无限

    # 状态
    created_at: float = 0.0
    status: str = TASK_PENDING
    postpone_count: int = 0
    reason: str = ""


@dataclass
class TriggerResult:
    """一次触发的判定结果。"""

    action: Literal["trigger", "cancel", "postpone"] = "trigger"
    reason: str = ""
    cancel_msg_template: str = ""
    postpone_seconds: int = 0
    silent: bool = False  # True 时 _execute_cancel 跳过消息发送（drop_silent 场景）


# ─────────────────────────────────────────────────────────────────
# 消息渲染
# ─────────────────────────────────────────────────────────────────


class MessageRenderer:
    """消息模板渲染器。

    将 `{变量}` 模板替换为实际值。
    支持条件段：`{xxx|如果 xxx 为空则不输出此段}` — 暂不实现，未来扩展。
    """

    @staticmethod
    def render(template: str, **variables: Any) -> str:
        """渲染消息模板。

        Args:
            template: 包含 {变量} 的模板字符串。
            **variables: 变量名到值的映射。

        Returns:
            渲染后的字符串。未找到的变量保留原样。
        """
        result = template
        for key, value in variables.items():
            placeholder = "{" + key + "}"
            if placeholder in result:
                result = result.replace(placeholder, str(value))
        return result


# ─────────────────────────────────────────────────────────────────
# 调度引擎
# ─────────────────────────────────────────────────────────────────


class SchedulerEngine:
    """定时调度引擎核心。

    维护一个本地任务字典，后台 loop 每秒 tick 检查到期任务。
    到期后执行触发前判定链，根据结果：
    - trigger：通过 Maisaka 主动触发 API 非显式注入到 Planner 上下文
    - cancel：发送可见取消通知
    - postpone：更新触发时间 + 发送可见推迟通知
    """

    def __init__(
        self,
        logger: logging.Logger,
        ctx_send_text: Any,  # self.ctx.send.text — 取消/推迟通知（用户可见）
        ctx_maisaka_trigger: Any,  # self.ctx.maisaka.proactive.trigger — 非显式注入到 Planner 上下文
        ctx_message: Any,  # self.ctx.message 代理
        config_getter: Any,  # 返回 PlannerTimerConfig 的可调用对象
    ) -> None:
        """初始化调度引擎。

        Args:
            logger: 日志对象，通常为 self.ctx.logger。
            ctx_send_text: 发送可见通知消息的函数 (text, stream_id)，用于取消/推迟。
            ctx_maisaka_trigger: Maisaka 主动触发函数 (stream_id, intent, reason, metadata)，
                                 用于非显式地将定时器到期事件注入 Planner 上下文。
            ctx_message: 消息查询代理，用于活跃度检测。
            config_getter: 返回当前 PlannerTimerConfig 的可调用对象。
        """
        self._log = logger
        self._send_text = ctx_send_text
        self._maisaka_trigger = ctx_maisaka_trigger
        self._message = ctx_message
        self._get_config = config_getter

        # 任务存储
        self._tasks: Dict[str, ScheduledTask] = {}  # task_id → task
        self._tasks_by_stream: Dict[str, List[str]] = {}  # stream_id → [task_ids]

        # 运行时状态
        self._last_activity: Dict[str, float] = {}  # stream_id → last active timestamp
        self._trigger_count: Dict[str, int] = {}  # stream_id → triggered count (current window)
        self._trigger_count_start: Dict[str, float] = {}  # stream_id → window start

        # 后台循环
        self._loop_task: Optional[asyncio.Task[None]] = None
        self._running: bool = False

        # 统计（仅用于 debug dump）
        self._stats: Dict[str, int] = {
            "triggered": 0,
            "cancelled": 0,
            "postponed": 0,
            "rejected": 0,
        }
        self._last_dump_time: float = 0.0
        self._last_tick_time: float = 0.0

        self._log.debug("SchedulerEngine 初始化完成")

    # ── 生命周期 ──

    def start(self) -> None:
        """启动后台定时器循环。"""
        if self._running:
            self._log.debug("SchedulerEngine 已在运行，跳过启动")
            return
        if self._loop_task is not None and not self._loop_task.done():
            self._log.debug("SchedulerEngine 有未完成的任务，取消后重启")
            self._loop_task.cancel()

        self._running = True
        self._loop_task = asyncio.create_task(self._run_loop(), name="mai-timefree.scheduler")
        self._log.info("SchedulerEngine 后台循环已启动")

    async def stop(self) -> None:
        """停止后台定时器循环。"""
        self._running = False
        loop_task = self._loop_task
        if loop_task is not None and not loop_task.done():
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass
        self._loop_task = None
        self._log.info("SchedulerEngine 后台循环已停止")

    # ── 排期 ──

    def schedule(self, task: ScheduledTask) -> Optional[str]:
        """排期一个定时任务。

        Args:
            task: 待排期的任务（task_id 可为空，会自动生成）。

        Returns:
            成功时返回 task_id，被拒绝时返回 None。
        """
        cfg = self._get_config()

        # 生成 task_id
        if not task.task_id:
            task.task_id = uuid4().hex[:12]

        # 检查是否允许该模式
        if task.mode not in cfg.timer.allowed_modes:
            self._log.warning(
                "排期拒绝：模式 %s 未被允许。allowed=%s, stream=%s, note=%s",
                task.mode, cfg.timer.allowed_modes, task.stream_id, task.note,
            )
            return None

        # 检查 stream 上限
        stream_tasks = self._tasks_by_stream.get(task.stream_id, [])
        if len(stream_tasks) >= cfg.limits.max_active_per_stream:
            self._log.warning(
                "排期拒绝：stream %s 已达上限 %d。current=%d, note=%s",
                task.stream_id, cfg.limits.max_active_per_stream,
                len(stream_tasks), task.note,
            )
            self._stats["rejected"] += 1
            return None

        # 检查全局上限
        total_active = len(self._tasks)
        if total_active >= cfg.limits.max_active_total:
            self._log.warning(
                "排期拒绝：全局任务已达上限 %d。note=%s",
                cfg.limits.max_active_total, task.note,
            )
            self._stats["rejected"] += 1
            return None

        # 去重检查（同 note）
        if not cfg.limits.allow_duplicate_notes and task.note:
            for existing in self._tasks.values():
                if (existing.stream_id == task.stream_id
                        and existing.note == task.note
                        and existing.status == TASK_PENDING):
                    self._log.debug(
                        "排期拒绝：同 stream 同 note 已存在。task_id=%s, note=%s",
                        existing.task_id, task.note,
                    )
                    self._stats["rejected"] += 1
                    return None

        # 保存任务
        task.created_at = time.time()
        task.status = TASK_PENDING
        self._tasks[task.task_id] = task

        # 更新 stream 索引
        if task.stream_id not in self._tasks_by_stream:
            self._tasks_by_stream[task.stream_id] = []
        self._tasks_by_stream[task.stream_id].append(task.task_id)

        self._log.info(
            "定时任务已排期: id=%s mode=%s trigger=%s stream=%s note=%s priority=%s",
            task.task_id, task.mode,
            datetime.fromtimestamp(task.trigger_time).strftime("%m-%d %H:%M:%S"),
            task.stream_id[:32], task.note[:64], task.priority,
        )
        return task.task_id

    def cancel_task(self, task_id: str) -> Optional[ScheduledTask]:
        """取消一个指定的定时任务。

        Args:
            task_id: 任务 ID。

        Returns:
            成功时返回该任务对象，未找到时返回 None。
        """
        task = self._tasks.pop(task_id, None)
        if task is None:
            self._log.debug("取消任务未找到: id=%s", task_id)
            return None

        # 从 stream 索引移除
        stream_ids = self._tasks_by_stream.get(task.stream_id, [])
        if task_id in stream_ids:
            stream_ids.remove(task_id)
        # 最后一个任务被取消后，连空 list 也一起删，避免 _tasks_by_stream 无限增长
        if not stream_ids:
            self._tasks_by_stream.pop(task.stream_id, None)

        task.status = TASK_CANCELLED
        self._log.info("定时任务已取消: id=%s note=%s", task_id, task.note[:64])
        return task

    def cancel_by_stream(
        self,
        stream_id: str,
        note_filter: str = "",
    ) -> int:
        """取消指定 stream 的所有（或匹配 note 的）定时任务。

        Args:
            stream_id: 目标 stream ID。
            note_filter: 可选，仅取消 note 包含此字符串的任务。

        Returns:
            被取消的任务数量。
        """
        task_ids = list(self._tasks_by_stream.get(stream_id, []))
        cancelled = 0
        for task_id in task_ids:
            task = self._tasks.get(task_id)
            if task is None:
                continue
            if note_filter and note_filter not in task.note:
                continue
            self.cancel_task(task_id)
            cancelled += 1
        self._log.debug("按流取消: stream=%s note_filter=%s cancelled=%d", stream_id, note_filter, cancelled)
        return cancelled

    def clear_all(self) -> int:
        """清除所有待触发任务。

        Returns:
            被清除的任务数量。
        """
        count = len(self._tasks)
        self._tasks.clear()
        self._tasks_by_stream.clear()
        self._log.info("已清除所有定时任务: count=%d", count)
        return count

    # ── 活跃度更新 ──

    def touch_activity(self, stream_id: str) -> None:
        """标记某 stream 有活跃发生（planner 活动 / 消息到达）。"""
        now = time.time()
        self._last_activity[stream_id] = now
        self._log.debug("活跃更新: stream=%s time=%s", stream_id[:32], datetime.fromtimestamp(now).strftime("%H:%M:%S"))

    def get_last_activity(self, stream_id: str) -> float:
        """获取某 stream 最近一次活跃时间戳。

        Returns:
            unix timestamp，若无记录则返回 0。
        """
        return self._last_activity.get(stream_id, 0.0)

    def get_active_tasks(self, stream_id: str = "") -> List[ScheduledTask]:
        """获取待触发任务列表。

        Args:
            stream_id: 可选，仅返回该 stream 的任务。

        Returns:
            任务列表。
        """
        if stream_id:
            return [
                self._tasks[tid] for tid in self._tasks_by_stream.get(stream_id, [])
                if tid in self._tasks and self._tasks[tid].status == TASK_PENDING
            ]
        return [t for t in self._tasks.values() if t.status == TASK_PENDING]

    # ── 触发判定 ──

    async def _evaluate_trigger(self, task: ScheduledTask) -> TriggerResult:
        """对某任务执行触发前判定链。

        Args:
            task: 即将到期的任务。

        Returns:
            判定结果（trigger / cancel / postpone）。
        """
        cfg = self._get_config()

        # 高优先级穿越
        if task.priority == PRIORITY_HIGH and cfg.trigger_check.allow_high_priority_bypass:
            if cfg.debug.trace_all_decisions:
                self._log.debug(
                    "判定[高优穿越]: task=%s priority=high → 跳过所有检查",
                    task.task_id,
                )
            return TriggerResult(action="trigger")

        delta = 0.0
        last_act = self._last_activity.get(task.stream_id, 0.0)
        if last_act > 0:
            delta = time.time() - last_act

        # ── 检查 1：冷却 ──
        if cfg.trigger_check.enable_cooling_check and last_act > 0:
            cancel_th = cfg.trigger_check.cancel_threshold_seconds
            min_int = cfg.trigger_check.min_interval_seconds

            # 低优先级任务阈值翻倍
            effective_cancel_th = cancel_th * 2 if task.priority == PRIORITY_LOW else cancel_th
            effective_min_int = min_int * 2 if task.priority == PRIORITY_LOW else min_int

            if delta <= effective_cancel_th:
                self._log.info(
                    "判定[冷却→取消]: task=%s delta=%.1fs <= %ds → 取消",
                    task.task_id, delta, effective_cancel_th,
                )
                return TriggerResult(
                    action="cancel",
                    reason=f"距上次操作仅 {int(delta)} 秒",
                    cancel_msg_template=cfg.cancel.message_cooling,
                )

            if delta < effective_min_int:
                self._log.info(
                    "判定[冷却→推迟]: task=%s delta=%.1fs < %ds → 推迟",
                    task.task_id, delta, effective_min_int,
                )
                return TriggerResult(
                    action="postpone",
                    reason=f"距上次操作仅 {int(delta)} 秒",
                    postpone_seconds=cfg.postpone.postpone_delay_seconds,
                )

            if cfg.debug.trace_all_decisions:
                self._log.debug(
                    "判定[冷却→通过]: task=%s delta=%.1fs",
                    task.task_id, delta,
                )

        # ── 检查 2：活跃度 ──
        if cfg.trigger_check.enable_activity_check:
            try:
                if hasattr(self._message, "get_recent"):
                    if asyncio.iscoroutinefunction(self._message.get_recent):
                        recent = await self._message.get_recent(
                            task.stream_id, cfg.trigger_check.activity_max_messages,
                        )
                    else:
                        recent = self._message.get_recent(
                            task.stream_id, cfg.trigger_check.activity_max_messages,
                        )
                else:
                    recent = []
            except Exception:
                recent = []
                self._log.debug("判定[活跃度]: get_recent 异常", exc_info=True)

            if len(recent) >= cfg.trigger_check.activity_max_messages:
                action = cfg.trigger_check.activity_action
                if action == "cancel":
                    self._log.info(
                        "判定[活跃→取消]: task=%s msgs=%d >= %d → 取消",
                        task.task_id, len(recent), cfg.trigger_check.activity_max_messages,
                    )
                    return TriggerResult(action="cancel", cancel_msg_template=cfg.cancel.message_activity)
                if action == "postpone":
                    self._log.info(
                        "判定[活跃→推迟]: task=%s msgs=%d >= %d → 推迟",
                        task.task_id, len(recent), cfg.trigger_check.activity_max_messages,
                    )
                    return TriggerResult(action="postpone", postpone_seconds=cfg.postpone.postpone_delay_seconds)

        # ── 检查 3：频率限制 ──
        if cfg.trigger_check.enable_frequency_limit:
            now = time.time()
            last_window_start = self._trigger_count_start.get(task.stream_id, 0.0)
            if now - last_window_start > cfg.trigger_check.frequency_window_seconds:
                # 窗口已过期，重置
                self._trigger_count[task.stream_id] = 0
                self._trigger_count_start[task.stream_id] = now

            count = self._trigger_count.get(task.stream_id, 0)
            if count >= cfg.trigger_check.frequency_limit_count:
                action = cfg.trigger_check.frequency_action
                if action == "cancel":
                    self._log.info(
                        "判定[频率→取消]: task=%s count=%d >= %d → 取消",
                        task.task_id, count, cfg.trigger_check.frequency_limit_count,
                    )
                    return TriggerResult(action="cancel", cancel_msg_template=cfg.cancel.message_frequency)
                if action == "postpone":
                    return TriggerResult(action="postpone", postpone_seconds=cfg.postpone.postpone_delay_seconds)
                if action == "drop_silent":
                    return TriggerResult(action="cancel", reason="达到触发频率上限（静默丢弃）", silent=True)

        # ── 全部通过 → 触发 ──
        if cfg.debug.trace_all_decisions:
            self._log.debug(
                "判定[全部通过]: task=%s mode=%s note=%s → 触发",
                task.task_id, task.mode, task.note[:48],
            )
        return TriggerResult(action="trigger")

    # ── 执行 ──

    async def _execute_trigger(self, task: ScheduledTask) -> None:
        """执行任务的触发动作。"""
        cfg = self._get_config()
        now = time.time()
        mode = task.mode

        # 计数
        self._stats["triggered"] += 1
        self._trigger_count[task.stream_id] = self._trigger_count.get(task.stream_id, 0) + 1

        # 非显式注入：通过 Maisaka 主动触发写入 Planner 上下文，不发送可见消息
        if task.behavior != BEHAVIOR_SILENT:
            try:
                await self._maisaka_trigger(
                    stream_id=task.stream_id,
                    intent=f"定时提醒：{task.note}",
                    reason="mai_timefree",
                    metadata={
                        "task_id": task.task_id,
                        "mode": task.mode,
                        "note": task.note,
                        "priority": task.priority,
                    },
                )
                self._log.info(
                    "定时提醒已注入 Planner 上下文: stream=%s task=%s note=%s",
                    task.stream_id[:32], task.task_id, task.note[:48],
                )
            except Exception:
                self._log.error("定时提醒注入失败: task=%s", task.task_id, exc_info=True)

        # 标记任务已完成（用 pop 兜底，避免外部 cancel_task 已先删时的 KeyError）
        task.status = TASK_TRIGGERED
        self._tasks.pop(task.task_id, None)

        # 清理 stream 索引
        stream_ids = self._tasks_by_stream.get(task.stream_id, [])
        if task.task_id in stream_ids:
            stream_ids.remove(task.task_id)

        # 去重清理：同 stream 同 note 的待处理任务
        if cfg.limits.auto_cleanup_on_trigger:
            cleaned = self.cancel_by_stream(task.stream_id, note_filter=task.note)
            if cleaned:
                self._log.debug("触发后去重清理: stream=%s note=%s cleaned=%d", task.stream_id, task.note, cleaned)

        # Interval 模式：自动再排
        if mode == MODE_INTERVAL and task.interval_seconds > 0:
            if task.max_chain == 0 or task.chain_count < task.max_chain - 1:
                new_task = ScheduledTask(
                    mode=MODE_INTERVAL,
                    trigger_time=now + task.interval_seconds,
                    stream_id=task.stream_id,
                    note=task.note,
                    priority=task.priority,
                    behavior=task.behavior,
                    interval_seconds=task.interval_seconds,
                    chain_count=task.chain_count + 1,
                    max_chain=task.max_chain,
                )
                self.schedule(new_task)
                self._log.debug("Interval 再排: %s → +%ds (第%d次)", task.task_id, task.interval_seconds, new_task.chain_count)

        # Chain 模式：自动再排
        if mode == MODE_CHAIN and task.interval_seconds > 0:
            if task.max_chain == 0 or task.chain_count < task.max_chain - 1:
                new_task = ScheduledTask(
                    mode=MODE_CHAIN,
                    trigger_time=now + task.interval_seconds,
                    stream_id=task.stream_id,
                    note=task.note,
                    priority=task.priority,
                    behavior=task.behavior,
                    interval_seconds=task.interval_seconds,
                    chain_count=task.chain_count + 1,
                    max_chain=task.max_chain,
                )
                self.schedule(new_task)
                self._log.debug("Chain 再排: %s → +%ds (第%d次)", task.task_id, task.interval_seconds, new_task.chain_count)

    async def _execute_cancel(self, task: ScheduledTask, result: TriggerResult) -> None:
        """执行取消操作。"""
        cfg = self._get_config()
        self._stats["cancelled"] += 1

        # 删除任务
        task.status = TASK_CANCELLED
        del self._tasks[task.task_id]
        stream_ids = self._tasks_by_stream.get(task.stream_id, [])
        if task.task_id in stream_ids:
            stream_ids.remove(task.task_id)

        # 发送取消消息（silent=True 时即使 cfg.cancel.send_message 开启也跳过）
        if cfg.cancel.send_message and not result.silent:
            now = time.time()
            last_act = self._last_activity.get(task.stream_id, 0.0)
            delta = int(now - last_act) if last_act > 0 else 0
            msg = MessageRenderer.render(
                result.cancel_msg_template or cfg.cancel.message_generic,
                note=task.note,
                task_id=task.task_id,
                priority=task.priority,
                created_at=datetime.fromtimestamp(task.created_at).strftime("%m-%d %H:%M"),
                delta=delta,
                reason=result.reason,
            )
            try:
                await self._send_text(msg, task.stream_id)
            except Exception:
                self._log.error("取消消息发送失败: task=%s", task.task_id, exc_info=True)

        self._log.info(
            "定时任务已取消执行: id=%s note=%s reason=%s",
            task.task_id, task.note[:48], result.reason,
        )

    async def _execute_postpone(self, task: ScheduledTask, result: TriggerResult) -> None:
        """执行推迟操作。"""
        cfg = self._get_config()
        self._stats["postponed"] += 1

        # 检查重试次数：>= 表示达到上限即取消（max_retries=0 时第一次 postpone 就超 0）
        task.postpone_count += 1
        if task.postpone_count >= cfg.postpone.max_retries:
            self._log.info(
                "推迟超限: task=%s postpone=%d/%d → 转为取消",
                task.task_id, task.postpone_count, cfg.postpone.max_retries,
            )
            await self._execute_cancel(task, TriggerResult(
                action="cancel",
                reason="推迟次数已达上限",
                cancel_msg_template=cfg.cancel.message_generic,
            ))
            return

        # 更新触发时间
        postpone_sec = result.postpone_seconds or cfg.postpone.postpone_delay_seconds
        new_time = time.time() + postpone_sec
        old_time = task.trigger_time
        task.trigger_time = new_time

        self._log.info(
            "定时任务已推迟: id=%s old=%s new=%s (+%ds) (%d/%d)",
            task.task_id,
            datetime.fromtimestamp(old_time).strftime("%H:%M:%S"),
            datetime.fromtimestamp(new_time).strftime("%H:%M:%S"),
            postpone_sec, task.postpone_count, cfg.postpone.max_retries,
        )

        # 发送推迟消息
        if cfg.postpone.send_message:
            now = time.time()
            last_act = self._last_activity.get(task.stream_id, 0.0)
            delta = int(now - last_act) if last_act > 0 else 0
            # 选择模板：reason 必须非空才走专属模板，避免空串误命中
            if result.reason and "操作" in result.reason:
                tmpl = cfg.postpone.message_cooling
            elif result.reason and "活跃" in result.reason:
                tmpl = cfg.postpone.message_activity
            else:
                tmpl = cfg.postpone.message_generic

            msg = MessageRenderer.render(
                tmpl,
                note=task.note,
                task_id=task.task_id,
                postpone_seconds=postpone_sec,
                postpone_time=datetime.fromtimestamp(new_time).strftime("%H:%M:%S"),
                postpone_count=task.postpone_count,
                max_retries=cfg.postpone.max_retries,
                delta=delta,
                reason=result.reason,
            )
            try:
                await self._send_text(msg, task.stream_id)
            except Exception:
                self._log.error("推迟消息发送失败: task=%s", task.task_id, exc_info=True)

    # ── 后台循环 ──

    async def _run_loop(self) -> None:
        """后台主循环。

        每秒 tick 一次，检查所有待触发任务。
        """
        self._log.info("SchedulerEngine 后台循环进入运行状态")
        cfg = self._get_config()

        while self._running:
            tick_start = time.time()

            try:
                await self._tick()
            except asyncio.CancelledError:
                self._log.debug("SchedulerEngine 循环被取消")
                break
            except Exception:
                self._log.error("SchedulerEngine tick 异常", exc_info=True)

            tick_end = time.time()
            self._last_tick_time = tick_end - tick_start

            # 按配置间隔等待
            interval = getattr(cfg.timer, "check_interval_seconds", 1.0)
            await asyncio.sleep(interval)

        self._log.info("SchedulerEngine 后台循环已退出")

    async def _tick(self) -> None:
        """一次 tick：检查并处理所有到期任务。"""
        cfg = self._get_config()
        now = time.time()
        tasks_to_process: List[ScheduledTask] = []

        # 收集到期任务
        for task in list(self._tasks.values()):
            if task.status != TASK_PENDING:
                continue
            if task.trigger_time <= now:
                tasks_to_process.append(task)

        if not tasks_to_process:
            # 定时 dump（debug 模式）
            self._maybe_dump_queue(cfg)
            return

        # verbose 日志
        if cfg.debug.verbose_logging:
            self._log.debug("Tick: %d 个任务到期", len(tasks_to_process))

        for task in tasks_to_process:
            # 双重检查：在循环执行期间可能已被处理
            if task.task_id not in self._tasks:
                continue

            result = await self._evaluate_trigger(task)

            if result.action == "trigger":
                await self._execute_trigger(task)
            elif result.action == "cancel":
                await self._execute_cancel(task, result)
            elif result.action == "postpone":
                await self._execute_postpone(task, result)

        # 定期清理过期任务
        self._maybe_cleanup(cfg)

    def _maybe_dump_queue(self, cfg: Any) -> None:
        """按配置频率 dump 任务队列（debug 用）。"""
        if not cfg.debug.dump_task_queue or not cfg.debug.verbose_logging:
            return
        now = time.time()
        if now - self._last_dump_time < cfg.debug.dump_interval_seconds:
            return
        self._last_dump_time = now

        tasks = self.get_active_tasks()
        if not tasks:
            self._log.debug("任务队列: 空 | stats=%s", self._stats)
            return

        lines = []
        for t in sorted(tasks, key=lambda x: x.trigger_time)[:10]:  # 最多显示 10 个
            lines.append(
                f"  {t.task_id} {t.mode:10s} "
                f"{datetime.fromtimestamp(t.trigger_time).strftime('%H:%M:%S')} "
                f"stream={t.stream_id[:20]:20s} note={t.note[:30]:30s} pri={t.priority}"
            )

        self._log.debug(
            "任务队列 (%d 个):\n%s\nTick: %.1fms | stats=%s",
            len(tasks), "\n".join(lines),
            self._last_tick_time * 1000,
            self._stats,
        )

    def _maybe_cleanup(self, cfg: Any) -> None:
        """定期清理过期 / 僵死任务。"""
        now = time.time()
        stale = cfg.limits.stale_timeout_seconds
        cleaned = 0

        for task_id, task in list(self._tasks.items()):
            # 过期超时
            if stale > 0 and now - task.created_at > stale:
                # cancel_task 内部已从 self._tasks pop；用 continue 避免下方再次 del 同 key
                if self.cancel_task(task_id) is not None:
                    cleaned += 1
                    self._log.debug("清理过期任务: id=%s note=%s age=%ds", task_id, task.note[:32], int(now - task.created_at))
                continue

            # 已经触发/取消的残留
            if task.status in (TASK_TRIGGERED, TASK_CANCELLED):
                self._tasks.pop(task_id, None)
                cleaned += 1

        # stream 维度的活动/触发计数：无活跃 task 的 stream 清掉，防无限涨
        active_streams = set(self._tasks_by_stream.keys())
        for d in (self._last_activity, self._trigger_count, self._trigger_count_start):
            for sid in list(d.keys()):
                if sid not in active_streams:
                    # 超过 stale 窗口的才删，避免刚 touch 就丢
                    ts = self._last_activity.get(sid, 0.0)
                    if stale > 0 and now - ts > stale:
                        d.pop(sid, None)
                        cleaned += 1

        if cleaned:
            self._log.debug("过期任务清理: cleaned=%d", cleaned)
