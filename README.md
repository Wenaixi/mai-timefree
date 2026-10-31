# wenaixi_mai_planner_timer_scheduler

[![Release](https://img.shields.io/github/v/release/Wenaixi/mai-planner-timer-scheduler?style=flat-square&color=blue&label=release)](https://github.com/Wenaixi/mai-planner-timer-scheduler/releases)
[![CI](https://img.shields.io/github/actions/workflow/status/Wenaixi/mai-planner-timer-scheduler/ci.yml?branch=main&style=flat-square&label=CI)](https://github.com/Wenaixi/mai-planner-timer-scheduler/actions)
[![License](https://img.shields.io/badge/license-AGPL--v3.0--or--later-green?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue?style=flat-square)](https://www.python.org/)
[![MaiBot](https://img.shields.io/badge/MaiBot-1.2%2B-orange?style=flat-square)](https://docs.mai-mai.org)

> 本插件由 [Wenaixi](https://github.com/Wenaixi) 维护，是专为生产环境深度调优的高可用分支。

## 简介与定位

为麦麦 Planner 规划器提供相对/绝对定时调度与定时提醒能力。

- **插件目录**：`wenaixi_mai_planner_timer_scheduler`
- **开源许可证**：`MIT`

---

## 核心特性与本地深度调优

- 优化定时器任务生命周期管理，防止进程重载时定时任务堆积

---

## 指令与工具速查

### 常用指令 (Command)
- `(无独立命令，供 Planner 内部调用)`

### 大模型工具 (Tool)
- `@Tool("planner_schedule") - 设定定时事件`
- `@Tool("planner_schedule_clear") - 清空定时事件`

---

## 快速配置

配置文件统一定位于插件根目录下的 `config.toml`。修改后重启或通过 WebUI 热重载即可生效。

---

## 上游项目与开源溯源

- **原作者 / 组织**：`Mai-with-u 社区`
- **官方原版开源仓库**：[https://github.com/Mai-with-u/wenaixi_mai_planner_timer_scheduler](https://github.com/Mai-with-u/wenaixi_mai_planner_timer_scheduler)
- **开源协议**：`MIT`
- **声明**：本项目遵循开源协议，特此致敬原作者的杰出贡献。本分支针对生产环境的高并发网络、个性化社交和抗风控需求进行了深度稳定性修复与定制化演进。