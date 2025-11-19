# 设计决策：下线版本监控功能

- **日期**：2025-11-19
- **决策人**：BenchScope Codex Agent（参考 CODEX-FINAL-OPTIMIZATION 指令）
- **状态**：已执行

## 背景

Phase 4 曾引入 GitHub Release 与 arXiv 版本监控，依赖以下组件：
- `.github/workflows/track_releases.yml`
- `scripts/track_github_releases.py`
- `scripts/track_arxiv_versions.py`
- `src/tracker/github_tracker.py`
- `src/tracker/arxiv_tracker.py`

运行一段时间后，团队确认版本监控无法直接提升「发现新的高价值 Benchmark」这一核心目标，且造成 GitHub Actions 配额与维护成本翻倍。

## 决策

1. 删除所有版本监控代码与脚本，集中精力在每日采集主流程。
2. 保留 `daily_collect.yml` 作为唯一 GitHub Actions workflow。
3. 更新文档与快速验证脚本，确保后续贡献者不会重新引入已废弃模块。
4. 通过 README 与 CLAUDE.md 说明：版本监控已于 2025-11-19 下线。

## 影响

| 项目 | 变更前 | 变更后 |
|------|--------|--------|
| GitHub Actions 工作流 | daily_collect + track_releases | 仅 daily_collect |
| 相关代码行数 | ~740 行 | 0 行 |
| 每日 CI 运行次数 | 2 次 | 1 次 |
| 飞书通知次数 | 2 次 | 1 次 |

## 替代方案

- GitHub 仓库可使用官方 Watch → Releases 功能接收更新。
- arXiv 支持 RSS 订阅，评估阶段可按需关注。
- 若未来再次需要版本监控，可从 Git 历史中恢复上述文件。

## 验证

- `bash scripts/quick_validation.sh` 新增检查，确保版本监控代码已被移除。
- `python -m src.main` 成功运行并推送飞书通知。
- GitHub Actions 仅保留 `daily_collect.yml` 并执行成功。
