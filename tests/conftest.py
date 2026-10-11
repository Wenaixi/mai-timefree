"""测试基础设施：让 mai-timefree 的相对导入在没有 maibot_sdk 的环境下也能跑。"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest
from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────
# Mock maibot_sdk 与 maibot_sdk.types
# ─────────────────────────────────────────────────────────────────

sdk = types.ModuleType("maibot_sdk")
sdk.Field = Field
sdk.PluginConfigBase = BaseModel


class _MaiBotPlugin:
    """极简 MaiBotPlugin 占位，足够让 plugin.py 完成 import 与属性赋值。"""

    def __init__(self):
        self.ctx = None

    def set_plugin_config(self, data):
        return None


class _Tool:
    """极简 Tool 装饰器占位，调用时返回原函数。"""

    def __init__(self, name=None, description=None, parameters=None):
        self.name = name
        self.description = description
        self.parameters = parameters

    def __call__(self, fn):
        return fn


sdk.MaiBotPlugin = _MaiBotPlugin
sdk.Tool = _Tool
sys.modules.setdefault("maibot_sdk", sdk)


_types_pkg = types.ModuleType("maibot_sdk.types")


class _ToolParameterInfo:
    def __init__(self, **kw):
        self.kw = kw


class _ToolParamType:
    STRING = "string"
    INTEGER = "integer"


_ToolParameterInfo.__init__.__defaults__ = ()
_ToolParamType.__name__ = "ToolParamType"
_types_pkg.ToolParameterInfo = _ToolParameterInfo
_types_pkg.ToolParamType = _ToolParamType
sys.modules.setdefault("maibot_sdk.types", _types_pkg)


# ─────────────────────────────────────────────────────────────────
# 把 mai-timefree 当作一个虚拟包加载，使相对导入（from .config）生效
# ─────────────────────────────────────────────────────────────────

PLUGIN_DIR = Path(__file__).resolve().parent.parent
PKG_NAME = "_mai_timefree_pkg"

_pkg = types.ModuleType(PKG_NAME)
_pkg.__path__ = [str(PLUGIN_DIR)]
sys.modules.setdefault(PKG_NAME, _pkg)


def _load_submodule(name: str):
    spec = importlib.util.spec_from_file_location(
        f"{PKG_NAME}.{name}", PLUGIN_DIR / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"{PKG_NAME}.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


_constants = _load_submodule("constants")
_config = _load_submodule("config")
_scheduler = _load_submodule("scheduler")
_plugin = _load_submodule("plugin")


# ─────────────────────────────────────────────────────────────────
# 公共 fixture：暴露被测模块的符号
# ─────────────────────────────────────────────────────────────────


@pytest.fixture
def cfg_module():
    return _config


@pytest.fixture
def scheduler_module():
    return _scheduler


@pytest.fixture
def plugin_module():
    return _plugin


@pytest.fixture
def PlannerTimerConfig():
    return _config.PlannerTimerConfig


@pytest.fixture
def SchedulerEngine():
    return _scheduler.SchedulerEngine


@pytest.fixture
def ScheduledTask():
    return _scheduler.ScheduledTask


@pytest.fixture
def constants():
    return _constants


def make_engine(PlannerTimerConfig, SchedulerEngine, cfg=None):
    """构造一个最小的 SchedulerEngine，ctx 全部用 no-op 替身。"""

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

    if cfg is None:
        cfg = PlannerTimerConfig()

    engine = SchedulerEngine(
        logger=_NoopLogger(),
        ctx_send_text=_AsyncNoop(),
        ctx_maisaka_trigger=_AsyncNoop(),
        ctx_message=_MessageProxy(),
        config_getter=lambda: cfg,
    )
    return engine
