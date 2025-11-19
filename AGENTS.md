# Repository Guidelines

本文件为 BenchScope 仓库贡献者与智能代理（AI 助手）的统一协作规范，请在提交代码前快速浏览一遍。

## Project Structure & Module Organization

- 业务代码在 `src/`：如 `collectors/`（数据采集）、`prefilter/`（规则预筛）、`scorer/`（LLM 评分）、`storage/`（飞书与 SQLite 存储）、`notifier/`（飞书通知）、`api/`（API/Callback 服务）。
- 配置在 `config/`（如 `config/sources.yaml`），公共常量在 `src/common/constants.py`。
- 实用脚本在 `scripts/`（日志分析、飞书表同步等），文档在 `docs/`，运行日志在 `logs/`。

## Build, Test, and Development Commands

- 创建并激活虚拟环境：`python3.11 -m venv .venv && source .venv/bin/activate`
- 安装依赖：`pip install -r requirements.txt`
- 本地跑完整流水线：`python -m src.main`（必须在仓库根目录执行）。
- 快速检查关键约束：`bash scripts/quick_validation.sh`
- 代码格式化与检查：`black .`、`ruff check .`

## Coding Style & Naming Conventions

- 统一使用 Python 3.11，遵循 PEP8，缩进 4 空格；函数/变量使用 `snake_case`，类使用 `PascalCase`。
- 推荐使用 `black` + `ruff` 保持风格一致，不引入与现有风格冲突的工具。
- 函数保持单一职责，避免超过 3 层嵌套；关键业务逻辑必须加中文注释。
- 避免魔法数字，统一放在 `src/common/constants.py` 或配置文件中。

## Testing Guidelines

- 当前以手动与脚本验证为主：修改前后至少运行 `bash scripts/quick_validation.sh` 与 `python -m src.main` 做冒烟测试。
- 如新增 `tests/` 目录，单元测试约定使用 `pytest`，命名示例：`tests/unit/test_github_collector.py`，运行：`pytest tests/unit -v`。
- 提交前请在 PR 描述中简要说明「测试方式与结果」。

## Commit & Pull Request Guidelines

- 提交信息建议采用 `type(scope): summary` 样式，例如：`feat(collector): 支持新的HF任务类型`、`fix(storage): 修复SQLite同步异常`。
- 常用 `type`：`feat`、`fix`、`refactor`、`docs`、`chore`、`revert`；摘要建议使用简洁中文。
- PR 需包含：变更背景、主要修改点、测试方式（含关键命令）、潜在风险与回滚思路；涉及飞书或外部服务时可附上日志或截图。

## Agent-Specific Instructions

- 默认用简体中文回复用户，代码中的关键注释也使用中文。
- 优先复用现有结构与工具，不破坏现有 API 兼容性；修改前先执行上述手动验证命令。
