# BenchScope

BenchScope 是一个用于自动化收集 AI/Agent Benchmark 情报的异步流水线,负责完成“采集 → 预筛 → 评分 → 存储 → 通知”的闭环。

## 功能特性
- 并发采集 arXiv/GitHub/HuggingFace 数据
- 规则预筛去重,过滤 40-60% 噪音
- 集成 OpenAI gpt-4o-mini + Redis 缓存的 LLM 评分,失败回落规则评分
- 飞书多维表格批量写入,SQLite 降级备份与回写
- 飞书 Webhook 推送每日 Top 候选
- 提供 `scripts/analyze_logs.py` 辅助分析采集/预筛/评分日志
- `scripts/track_github_releases.py`/`scripts/track_arxiv_versions.py` 跟踪版本更新并自动推送
- GitHub Actions 定时调度,附日志与备份制品

## 快速开始
1. 准备 `.env` (参考 `.env.example`),配置 OpenAI/飞书/Redis 等凭证。
2. 安装依赖:
   ```bash
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```
3. (可选) 调整 `config/sources.yaml` 中的 HuggingFace 抓取关键词、任务分类与下载量阈值。

4. 启动 Redis(本地或云服务)并运行主流程:
   ```bash
   python src/main.py
   ```

## 手动测试
- 飞书写入、飞书通知与外部 API 需手动验证,请将记录更新到 `docs/test-report.md` 并附日志/截图。
- 修改核心逻辑前,先执行 `poetry run python scripts/manual_review.py` (若存在)或等效手动验证。

## 目录结构
```
src/
  collectors/         # arXiv/GitHub/HuggingFace 采集器
  prefilter/          # 规则去重与过滤
  scorer/             # LLM评分 + 规则兜底
  storage/            # 飞书存储 + SQLite 降级
  notifier/           # 飞书 Webhook 通知
  common/constants.py # 魔法数字集中管理
  models.py           # 数据模型
  main.py             # 流程编排
config/
  sources.yaml        # 数据源自定义配置
scripts/
  analyze_logs.py     # 日志快速分析
  track_github_releases.py    # GitHub Release 跟踪
  track_arxiv_versions.py    # arXiv 版本跟踪
```

## 测试
- 单元测试:
  ```bash
  pytest tests/unit -m "not slow"
  ```
- 代码质量: 请在提交前运行 `ruff check` 与 `black .`。

## 调度
- `.github/workflows/daily_collect.yml` 每天 UTC 02:00 自动运行采集/评分流水线,并上传日志与 SQLite 备份。
- `.github/workflows/track_releases.yml` 每天 UTC 10:00 运行 GitHub Release 与 arXiv 版本跟踪任务。

## 后续规划
- 引入特征权重配置(`config/weights.yaml`)
- 增加 Feishu 告警机器人用于存储降级通知
- 扩展更多数据源(如 HuggingFace Datasets)
