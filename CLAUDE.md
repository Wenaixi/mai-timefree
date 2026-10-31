# CLAUDE.md - mai-timefree (mai-timefree)

## 1. 模块定位与系统职责
- **插件标识符**：`mai-timefree`
- **当前生效版本**：`v0.1.0`
- **托管仓库**：[`Wenaixi/mai-timefree`](https://github.com/Wenaixi/mai-timefree)
- **核心定位**：为麦麦 Planner 规划器提供相对/绝对定时调度与定时提醒能力。

## 2. 关键工程规范与配置说明
- **配置路径**：`config.toml`（所有业务调优与鉴权参数收敛于此）；
- **数据持久化**：优先遵循 MaiBot SDK 标准持久化规范，不直接向源码目录写入易失数据；
- **编码与日志规范**：严格遵循 PEP 8 风格，文档与代码注释杜绝 emoji，避免虚假套话。

## 3. 本地深度定制与稳定性修复
优化定时器任务生命周期管理，防止进程重载时定时任务堆积。

---

## 上游项目与开源溯源
- **原作者 / 组织**：`Mai-with-u 社区`
- **官方上游仓库**：[https://github.com/Mai-with-u/mai-timefree](https://github.com/Mai-with-u/mai-timefree)
- **开源许可证**：`MIT`
- **分支演进模式**：本仓库作为主人的深度定制与生产维护分支（`Wenaixi/mai-timefree`）。在保持与官方上游架构演进对齐的同时，锁死并持续维护针对本服务器生产环境的稳定性补丁与核心特性。
