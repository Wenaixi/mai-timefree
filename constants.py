"""mai-timefree 插件共享常量和枚举。"""

from __future__ import annotations

from typing import Final

# ── 配置版本 ──
SUPPORTED_CONFIG_VERSION: Final[str] = "0.1.0"

# ── 定时模式 ──
MODE_RELATIVE: Final[str] = "relative"
MODE_ABSOLUTE: Final[str] = "absolute"
MODE_INTERVAL: Final[str] = "interval"
MODE_CHAIN: Final[str] = "chain"
ALL_MODES: Final[tuple[str, ...]] = (MODE_RELATIVE, MODE_ABSOLUTE, MODE_INTERVAL, MODE_CHAIN)

# ── 优先级 ──
PRIORITY_HIGH: Final[str] = "high"
PRIORITY_MEDIUM: Final[str] = "medium"
PRIORITY_LOW: Final[str] = "low"
ALL_PRIORITIES: Final[tuple[str, ...]] = (PRIORITY_HIGH, PRIORITY_MEDIUM, PRIORITY_LOW)

# ── 触发行为 ──
BEHAVIOR_NORMAL: Final[str] = "normal"
BEHAVIOR_SILENT: Final[str] = "silent"
BEHAVIOR_STRICT: Final[str] = "strict"
ALL_BEHAVIORS: Final[tuple[str, ...]] = (BEHAVIOR_NORMAL, BEHAVIOR_SILENT, BEHAVIOR_STRICT)

# ── 任务状态 ──
TASK_PENDING: Final[str] = "pending"
TASK_TRIGGERED: Final[str] = "triggered"
TASK_CANCELLED: Final[str] = "cancelled"
TASK_POSTPONED: Final[str] = "postponed"

# ── 日志等级 ──
ALL_LOG_LEVELS: Final[tuple[str, ...]] = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# ── 默认值 ──
DEFAULT_LOG_LEVEL: Final[str] = "INFO"
DEFAULT_CHECK_INTERVAL: Final[float] = 1.0
DEFAULT_DELAY_SECONDS: Final[int] = 300
DEFAULT_MIN_DELAY: Final[int] = 10
DEFAULT_MAX_DELAY: Final[int] = 86400  # 24 hours
DEFAULT_CANCEL_THRESHOLD: Final[int] = 30
DEFAULT_MIN_INTERVAL: Final[int] = 60
DEFAULT_POSTPONE_DELAY: Final[int] = 60
DEFAULT_MAX_POSTPONE_RETRIES: Final[int] = 3
DEFAULT_MAX_ACTIVE_PER_STREAM: Final[int] = 10
DEFAULT_MAX_ACTIVE_TOTAL: Final[int] = 50
DEFAULT_STALE_TIMEOUT: Final[int] = 7200
DEFAULT_CLEANUP_INTERVAL: Final[int] = 300
DEFAULT_FREQUENCY_LIMIT: Final[int] = 5
DEFAULT_FREQUENCY_WINDOW: Final[int] = 3600
