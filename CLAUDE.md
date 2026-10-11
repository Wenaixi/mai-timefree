# mai-timefree

## 官方上游与版本溯源
- 官方仓库（Upstream Repository）：https://github.com/clfr41/mai-timefree
- 官方作者（Author / Maintainer）：clfr41
- 功能定位：基于时间的自由调度与定时引擎
- 本地演进定位：基于官方上游最新版本，融入本地生产环境兼容性定制与稳定性加固。
- 本地专属定制：本地修复 stream 计数字典无界增长与内存泄漏隐患。


源: 社区插件（具体仓库未公开记录）

## 主人改过的关键文件

- `_manifest.json`：`max_version` 改成 `1.99.99`（让 Host 1.1.0 能加载）。
- `config.toml`：`enabled = true`。

## 配置要点

- 之前**没有 .gitignore**；本仓库新建了完整 Python plugin 模板 + 主人段。

## 接入 & 依赖

- 无外部服务。

## 关键日志

- `mai-timefree 已加载`

## 历史脚注

- 2026-07-28: 从服务器同步到本地仓库（baseline head=`e88e74b`）；新建 `.gitignore` 与本 CLAUDE.md。
