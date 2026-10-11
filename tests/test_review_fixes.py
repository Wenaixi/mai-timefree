"""TDD 修复测试：mai-timefree review 找出的 HIGH/MEDIUM 问题。

每个测试都对应任务描述里的一条 fix；先 RED（FAIL）→ GREEN（PASS）。
"""

from __future__ import annotations

import asyncio
import time

import pytest

from _mai_timefree_pkg.constants import (
    BEHAVIOR_NORMAL,
    MODE_RELATIVE,
    TASK_CANCELLED,
    TASK_PENDING,
    TASK_TRIGGERED,
)
from _mai_timefree_pkg.scheduler import SchedulerEngine


# ─────────────────────────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────────────────────────


def _make_task(stream_id="stream-A", note="hello", **kw):
    from _mai_timefree_pkg.scheduler import ScheduledTask

    defaults = dict(
        mode=MODE_RELATIVE,
        trigger_time=time.time(),
        stream_id=stream_id,
        note=note,
        priority="medium",
        behavior=BEHAVIOR_NORMAL,
    )
    defaults.update(kw)
    return ScheduledTask(**defaults)


# ─────────────────────────────────────────────────────────────────
# HIGH 1：_maybe_cleanup stale 分支 cancel_task 后又 del → KeyError
# ─────────────────────────────────────────────────────────────────


def test_high1_cleanup_stale_after_cancel_does_not_keyerror(
    PlannerTimerConfig, SchedulerEngine
):
    cfg = PlannerTimerConfig()
    cfg.limits.stale_timeout_seconds = 60

    engine = SchedulerEngine(
        logger=_NoopLogger(),
        ctx_send_text=_AsyncNoop(),
        ctx_maisaka_trigger=_AsyncNoop(),
        ctx_message=_MessageProxy(),
        config_getter=lambda: cfg,
    )

    task = _make_task(stream_id="s1")
    # 触发"过期"判定：created_at 很久以前
    task.created_at = time.time() - 10000
    task.status = TASK_PENDING
    engine._tasks[task.task_id] = task
    engine._tasks_by_stream.setdefault("s1", []).append(task.task_id)

    # 不应抛 KeyError
    engine._maybe_cleanup(cfg)

    # 任务确实被取消
    assert task.task_id not in engine._tasks


# ─────────────────────────────────────────────────────────────────
# HIGH 2：_execute_trigger await 期间 race → del KeyError
# ─────────────────────────────────────────────────────────────────


def test_high2_execute_trigger_pop_after_external_cancel(
    PlannerTimerConfig, SchedulerEngine
):
    """在 _maisaka_trigger await 期间外部 cancel_task，再 del 同一个 key 不应抛 KeyError。"""
    cfg = PlannerTimerConfig()

    cancel_during_await = {"done": False}

    async def racing_trigger(*a, **kw):
        # 模拟"外部调用 cancel_task"
        engine.cancel_task(task.task_id)
        cancel_during_await["done"] = True

    engine = SchedulerEngine(
        logger=_NoopLogger(),
        ctx_send_text=_AsyncNoop(),
        ctx_maisaka_trigger=racing_trigger,
        ctx_message=_MessageProxy(),
        config_getter=lambda: cfg,
    )

    task = _make_task(stream_id="s2", behavior=BEHAVIOR_NORMAL)
    engine._tasks[task.task_id] = task
    engine._tasks_by_stream.setdefault("s2", []).append(task.task_id)

    asyncio.run(engine._execute_trigger(task))

    assert cancel_during_await["done"], "mock trigger was not invoked"
    # 第二次 del 应已用 pop(..., None) 兜底


# ─────────────────────────────────────────────────────────────────
# HIGH 3：_tasks_by_stream 永不删 key → 内存泄漏
# ─────────────────────────────────────────────────────────────────


def test_high3_tasks_by_stream_key_pruned_after_last_cancel(
    PlannerTimerConfig, SchedulerEngine
):
    cfg = PlannerTimerConfig()

    engine = SchedulerEngine(
        logger=_NoopLogger(),
        ctx_send_text=_AsyncNoop(),
        ctx_maisaka_trigger=_AsyncNoop(),
        ctx_message=_MessageProxy(),
        config_getter=lambda: cfg,
    )

    task = _make_task(stream_id="stream-X")
    engine._tasks[task.task_id] = task
    engine._tasks_by_stream.setdefault("stream-X", []).append(task.task_id)

    assert engine.cancel_task(task.task_id) is task
    # 唯一任务被取消后，stream key 也应消失
    assert "stream-X" not in engine._tasks_by_stream, (
        f"_tasks_by_stream leaked stream key: {list(engine._tasks_by_stream.keys())}"
    )


# ─────────────────────────────────────────────────────────────────
# HIGH 4：on_config_update 重建 engine → 排期全丢
# ─────────────────────────────────────────────────────────────────


def test_high4_on_config_update_preserves_engine_and_tasks(
    PlannerTimerConfig, plugin_module
):
    """on_config_update 后 self._engine 应保持同一个对象，任务不被清空。"""

    plugin = plugin_module.PlannerTimerPlugin()

    # 模拟 ctx：logger 必备
    class _NoopLogger2:
        def debug(self, *a, **kw):
            pass

        def info(self, *a, **kw):
            pass

        def warning(self, *a, **kw):
            pass

        def error(self, *a, **kw):
            pass

    class _Ctx:
        logger = _NoopLogger2()

        class _Send:
            async def text(self, *a, **kw):
                return None

        send = _Send()

        class _Maisaka:
            class _Proactive:
                async def trigger(self, *a, **kw):
                    return None

            proactive = _Proactive()

        maisaka = _Maisaka()

        class _Message:
            def get_recent(self, *a, **kw):
                return []

        message = _Message()

    plugin.ctx = _Ctx()

    # 绕开 SDK 的 set_plugin_config / config，自己填好内部状态
    cfg = PlannerTimerConfig()
    cfg.plugin.enabled = True

    # 手动构造一个 engine 并挂在 plugin 上（避免启动后台 loop）
    engine = SchedulerEngine(
        logger=_NoopLogger2(),
        ctx_send_text=plugin.ctx.send.text,
        ctx_maisaka_trigger=plugin.ctx.maisaka.proactive.trigger,
        ctx_message=plugin.ctx.message,
        config_getter=lambda: cfg,
    )
    plugin._engine = engine
    plugin._initialized = True

    # 让 plugin.config 直接返回 cfg（替代 set_plugin_config 副作用）
    type(plugin).config = property(lambda self: cfg)
    plugin.set_plugin_config = lambda data: None

    # 排一个任务
    task = _make_task(stream_id="s-config", note="keep-me")
    scheduled_id = engine.schedule(task)
    assert scheduled_id is not None
    assert scheduled_id in engine._tasks

    # 触发 on_config_update
    asyncio.run(plugin.on_config_update("self", {}, ""))

    # 引擎实例不变、任务仍在
    assert plugin._engine is engine, "on_config_update 重建了 engine，丢失了所有排期"
    assert scheduled_id in engine._tasks, "排期任务在 on_config_update 后丢失"


# ─────────────────────────────────────────────────────────────────
# HIGH 5：drop_silent 实际走 cancel 发通知
# ─────────────────────────────────────────────────────────────────


def test_high5_drop_silent_does_not_send_notification(
    PlannerTimerConfig, SchedulerEngine
):
    cfg = PlannerTimerConfig()
    cfg.trigger_check.enable_frequency_limit = True
    cfg.trigger_check.frequency_limit_count = 1
    cfg.trigger_check.frequency_window_seconds = 3600
    cfg.trigger_check.frequency_action = "drop_silent"
    cfg.cancel.send_message = True  # 即便开启，也应该 drop_silent 时静默

    sent: list = []

    async def recording_send(msg, sid):
        sent.append((msg, sid))

    engine = SchedulerEngine(
        logger=_NoopLogger(),
        ctx_send_text=recording_send,
        ctx_maisaka_trigger=_AsyncNoop(),
        ctx_message=_MessageProxy(),
        config_getter=lambda: cfg,
    )

    # 先把频率窗口推到上限
    engine._trigger_count_start["s-ds"] = time.time()
    engine._trigger_count["s-ds"] = cfg.trigger_check.frequency_limit_count

    task = _make_task(stream_id="s-ds", note="drop-me")
    engine._tasks[task.task_id] = task
    engine._tasks_by_stream.setdefault("s-ds", []).append(task.task_id)

    result = asyncio.run(engine._evaluate_trigger(task))
    assert result.action == "cancel"
    # drop_silent 应该走静默路径，TriggerResult.silent 应为 True
    assert getattr(result, "silent", False) is True, (
        f"drop_silent should mark result.silent=True, got {result!r}"
    )

    asyncio.run(engine._execute_cancel(task, result))
    # 静默丢消息时，不应发送取消通知
    assert sent == [], f"drop_silent still sent: {sent!r}"


# ─────────────────────────────────────────────────────────────────
# HIGH 6：max_retries=0 语义错
# ─────────────────────────────────────────────────────────────────


def test_high6_max_retries_zero_cancels_on_first_postpone(
    PlannerTimerConfig, SchedulerEngine
):
    cfg = PlannerTimerConfig()
    cfg.postpone.max_retries = 0

    sent: list = []

    async def recording_send(msg, sid):
        sent.append((msg, sid))

    engine = SchedulerEngine(
        logger=_NoopLogger(),
        ctx_send_text=recording_send,
        ctx_maisaka_trigger=_AsyncNoop(),
        ctx_message=_MessageProxy(),
        config_getter=lambda: cfg,
    )

    task = _make_task(stream_id="s-r0", note="zero-retries")
    engine._tasks[task.task_id] = task
    engine._tasks_by_stream.setdefault("s-r0", []).append(task.task_id)

    # 触发 postpone（reason 空也无所谓）
    from _mai_timefree_pkg.scheduler import TriggerResult

    result = TriggerResult(action="postpone", reason="冷却", postpone_seconds=60)
    asyncio.run(engine._execute_postpone(task, result))

    # max_retries=0 时第一次 postpone_count=1 ≥ 0 → 立即取消
    assert task.status == TASK_CANCELLED
    assert task.task_id not in engine._tasks, (
        f"max_retries=0 should drop task, but still in _tasks: {list(engine._tasks.keys())}"
    )


# ─────────────────────────────────────────────────────────────────
# MEDIUM：check_interval_seconds 无下限保护（ge=0.05）
# ─────────────────────────────────────────────────────────────────


def test_medium_check_interval_has_lower_bound(PlannerTimerConfig):
    import pydantic

    cfg = PlannerTimerConfig()
    timer = cfg.timer

    # 极小值应该被拒绝（Pydantic ge=0.05）
    with pytest.raises(pydantic.ValidationError):
        PlannerTimerConfig.model_validate(
            {
                "plugin": {"enabled": True},
                "timer": {"check_interval_seconds": 0.0},
            }
        )


# ─────────────────────────────────────────────────────────────────
# MEDIUM：_execute_postpone 模板选择第二个 elif 无 result.reason guard
# ─────────────────────────────────────────────────────────────────


def test_medium_postpone_template_no_reason_does_not_crash(
    PlannerTimerConfig, SchedulerEngine
):
    """result.reason 为空字符串时，模板选择不应在 "活跃" in "" 时误命中。"""
    cfg = PlannerTimerConfig()

    engine = SchedulerEngine(
        logger=_NoopLogger(),
        ctx_send_text=_AsyncNoop(),
        ctx_maisaka_trigger=_AsyncNoop(),
        ctx_message=_MessageProxy(),
        config_getter=lambda: cfg,
    )

    task = _make_task(stream_id="s-r3", note="no-reason")
    engine._tasks[task.task_id] = task
    engine._tasks_by_stream.setdefault("s-r3", []).append(task.task_id)

    from _mai_timefree_pkg.scheduler import TriggerResult

    # reason 为空字符串——第二个 elif `"活跃" in ""` 在 Python 里是 False，所以目前看似 OK，
    # 但若 reason 为 None 或意图改成"包含reason时才走专门模板"，这里会出错。
    # 本测试锁死：reason 为空字符串时，必须走 generic，不抛异常。
    result = TriggerResult(action="postpone", reason="", postpone_seconds=60)
    asyncio.run(engine._execute_postpone(task, result))

    # 任务应仍在（postpone 不取消）
    assert task.task_id in engine._tasks


# ─────────────────────────────────────────────────────────────────
# MEDIUM：_maybe_dump_queue 注释与代码不一致
# ─────────────────────────────────────────────────────────────────


def test_medium_dump_queue_uses_consistent_limit(
    PlannerTimerConfig, SchedulerEngine
):
    """注释应与代码一致：最多显示 10 条（与 lines 对齐）。"""
    import inspect
    import re

    src = inspect.getsource(SchedulerEngine._maybe_dump_queue)
    # 任务截断：trigger_time)[:N] 应该是 10；不能再有 [:20] 的任务截断
    m = re.search(r"trigger_time\)\[:(\d+)\]", src)
    assert m is not None, "找不到 trigger_time 截断"
    assert m.group(1) == "10", f"任务截断应为 10，实际为 {m.group(1)}"
    # 日志 join 应直接用 lines，不要再二次切片
    assert "join(lines[:10])" not in src, "二次切片 join(lines[:10]) 与 [:10] 重复"


# ─────────────────────────────────────────────────────────────────
# 共享的 no-op 替身
# ─────────────────────────────────────────────────────────────────


class _AsyncNoop:
    async def __call__(self, *a, **kw):
        return None


class _NoopLogger:
    def debug(self, *a, **kw):
        pass

    def info(self, *a, **kw):
        pass

    def warning(self, *a, **kw):
        pass

    def error(self, *a, **kw):
        pass

    def exception(self, *a, **kw):
        pass


class _MessageProxy:
    def get_recent(self, *a, **kw):
        return []
