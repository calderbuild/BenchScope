# BenchScope

**BenchScope** = **Benchmark Intelligence Agent (BIA)**

自动化Benchmark情报系统，每日采集AI/Agent领域的Benchmark资源，智能预筛选评分，推送到飞书多维表格，辅助研究团队高效筛选有价值的评测基准。

## 项目背景

服务于 **[MGX](https://mgx.dev)** - 多智能体协作框架，专注Vibe Coding（AI原生编程）

**MGX核心技术方向**:
- 多智能体协作与编排
- 代码生成与理解
- 工具调用与任务自动化
- 智能工作流设计

基于 [MetaGPT](https://github.com/FoundationAgents/MetaGPT) 框架构建

## 核心功能

### 数据采集
- **5个数据源并发采集**: arXiv、Semantic Scholar、HELM、GitHub、HuggingFace
- **时间窗口过滤**: GitHub 30天、HuggingFace 14天、arXiv 7天
- **异步并发**: asyncio优化的采集流程，平均耗时<2分钟

### 智能预筛选
- **URL去重**: 本地去重 + 飞书已存在URL去重
- **规则过滤**: 排除awesome-list、资源汇总、工具库
- **Benchmark特征检测**: 必须包含evaluation/test set/dataset/leaderboard等关键词
- **过滤率**: 40-60%噪音过滤

### LLM智能评分
- **模型**: GPT-4o-mini（成本优化，月费用<¥20）
- **5维评分**:
  - 活跃度 15%: GitHub stars与更新频率
  - 可复现性 30%: 代码/数据/文档开源状态
  - 许可合规 15%: MIT/Apache/BSD优先
  - 任务新颖性 15%: 创新性评估
  - MGX适配度 25%: 多智能体/代码生成/工具使用相关性
- **严格Benchmark识别**: 自动区分真Benchmark vs 工具/教程/资源汇总
- **Redis缓存**: 7天TTL，命中率~30%
- **规则兜底**: LLM失败时自动降级到规则评分

### 数据存储
- **主存储**: 飞书多维表格（批量写入20条/请求，0.6s间隔限流）
- **降级备份**: SQLite本地数据库（7天自动同步回写）
- **字段完整性**: 22个字段全覆盖（标题、URL、评分、任务类型、License等）

### 飞书通知
- **分层推送策略**: High优先级→Medium次之→Low补充
- **交互式卡片**: 支持按钮操作（Phase 5）
- **统一播报**: 单次推送最新高价值Benchmark（版本监控已下线）

## 性能指标

| 指标 | 优化前 | 优化后 | 改进 |
|------|--------|--------|------|
| 真Benchmark占比 | <20% | ≥60% | +200% |
| 平均MGX相关性 | 4.4/10 | 6.0-7.5/10 | +36-70% |
| 预筛选过滤率 | 0% | 40-60% | 新增 |
| 非Benchmark相关性 | 8.6/10 | ≤2/10 | -75% |
| GitHub Stars填充率 | 5.7% | 100%(GitHub源) | +1650% |

## 快速开始

### 1. 环境配置

```bash
# 创建虚拟环境
python3.11 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install --upgrade pip
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env.local
```

编辑 `.env.local` 填写：
- `OPENAI_API_KEY` - OpenAI API密钥（gpt-4o-mini评分）
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET` - 飞书应用凭证
- `FEISHU_BITABLE_APP_TOKEN` - 飞书多维表格Token
- `FEISHU_BITABLE_TABLE_ID` - 飞书表格ID
- `SEMANTIC_SCHOLAR_API_KEY` - Semantic Scholar API密钥
- `GITHUB_TOKEN` (可选) - 提升GitHub API速率限制
- `REDIS_URL` (可选) - Redis缓存，提升30%性能

### 系统依赖

**Poppler**（PDF渲染，Phase 9.5 新增）：
```bash
# Ubuntu / Debian
sudo apt-get install -y poppler-utils

# macOS
brew install poppler

# Windows
# 1) 下载: https://github.com/oschwartz10612/poppler-windows/releases/
# 2) 解压并把 bin 目录加入 PATH
# 3) 验证: pdftoppm -v
```

**GROBID**（PDF结构化解析，Phase 9 已集成自动启动）：
```bash
# 本地开发默认自动启动，GitHub Actions 已在流程中验证
```

### 2. 运行主流程

```bash
# 完整流程: 采集 → 预筛 → 评分 → 存储 → 通知
# 注意: 必须从项目根目录运行，使用模块方式
python -m src.main

# 或使用虚拟环境完整路径
.venv/bin/python -m src.main
```

### 3. (可选) 调整配置

编辑 `config/sources.yaml` 自定义：
- GitHub搜索关键词和topics
- HuggingFace任务分类
- 时间窗口和结果数量限制

## 实用工具脚本

```bash
# 分析采集日志（统计成功率、过滤率）
.venv/bin/python scripts/analyze_logs.py

# 分析飞书数据质量（字段完整性、评分分布）
.venv/bin/python scripts/analyze_feishu_data.py

# 查看飞书表格字段列表
.venv/bin/python scripts/list_feishu_fields.py

# 飞书表格去重
.venv/bin/python scripts/deduplicate_feishu_table.py

# 清空飞书表格（危险操作！）
.venv/bin/python scripts/clear_feishu_table.py

# SQLite数据同步到飞书
.venv/bin/python scripts/sync_sqlite_to_feishu.py

```

## 项目结构

```
src/
├── collectors/              # 数据采集器
│   ├── arxiv_collector.py        # arXiv API
│   ├── semantic_scholar_collector.py  # Semantic Scholar API
│   ├── helm_collector.py          # HELM Leaderboard
│   ├── github_collector.py        # GitHub Search API
│   └── huggingface_collector.py   # HuggingFace Hub API
├── prefilter/              # 规则预筛选
│   └── rule_filter.py          # URL去重 + Benchmark特征检测
├── scorer/                 # 评分引擎
│   └── llm_scorer.py           # gpt-4o-mini评分 + Redis缓存
├── storage/                # 存储层
│   ├── feishu_storage.py       # 飞书多维表格
│   ├── sqlite_fallback.py      # SQLite降级备份
│   └── storage_manager.py      # 主备切换管理
├── notifier/               # 通知引擎
│   └── feishu_notifier.py      # 飞书Webhook推送
├── common/
│   └── constants.py            # 配置常量
├── models.py               # 数据模型
├── config.py               # 配置管理
└── main.py                 # 流程编排器

config/
└── sources.yaml            # 数据源配置

scripts/
├── analyze_logs.py         # 日志分析
├── analyze_feishu_data.py  # 数据质量分析
├── list_feishu_fields.py   # 字段列表
├── list_feishu_tables.py   # 表格列表
├── sync_sqlite_to_feishu.py # 数据同步
├── deduplicate_feishu_table.py # 去重
├── clear_feishu_table.py   # 清空表格
├── create_feishu_fields.py # 初始化字段
└── test_layered_notification.py # 飞书通知测试
```

## GitHub Actions自动化

### 每日采集 (`.github/workflows/daily_collect.yml`)
- **触发**: 每天UTC 02:00 (北京时间10:00)
- **流程**: 采集 → 预筛 → 评分 → 存储 → 通知
- **制品**: 日志文件 + SQLite备份（保留7天）
- **说明**: 版本监控工作流已下线，所有CI资源集中在核心采集与评分流程

## 代码质量

```bash
# 格式化代码 (PEP8)
black .

# 代码检查
ruff check .

# 自动修复
ruff check --fix .
```

## 手动测试要求

飞书播报、飞书多维表格、外部API交互必须手动验证：
1. 运行完整流程后检查飞书多维表格
2. 验证飞书通知是否正确推送
3. 检查日志文件 `logs/{YYYYMMDD}.log`
4. 将测试结果记录到 `docs/test-report.md`

## 技术决策

### 为什么用飞书多维表格而不是Notion？
- 国内访问稳定（Notion常被墙）
- API限额更高（100请求/分钟 vs Notion 3请求/秒）
- 团队生态统一（减少工具切换）
- SQLite降级策略（数据不丢失）

### 为什么用gpt-4o-mini而不是gpt-4？
- 成本仅为gpt-4的1/10（月成本<¥20 << 预算¥50）
- 评分任务复杂度低，mini性能足够
- 规则预筛选50% + Redis缓存30% → 调用量优化

### 为什么用GitHub Actions而不是Airflow？
- 任务依赖简单（串行采集+评分+入库）
- 免运维（无需部署scheduler）
- 免费额度充足（每日5分钟 << 2000分钟/月）

## 项目状态

- **Phase 1-5**: ✅ 已完成（MVP + 核心优化 + 增强功能；版本跟踪已于2025-11-19下线）
- **Phase 6**: ✅ 已完成（信息源扩展 + 数据完善 + 智能预筛选）
- **当前版本**: v1.6.0
- **代码质量**: ⭐⭐⭐⭐⭐ (10/10)

## 后续规划

- [ ] 接入ACL Anthology会议论文数据源
- [ ] 接入Open LLM Leaderboard评测榜单
- [ ] 扩展更多任务类型识别（GUI、Deep Research等）
- [ ] 完善复现脚本URL和评估指标的自动提取
- [ ] 增加飞书告警机器人用于存储降级通知

## 参考文档

- [PRD文档](/.claude/specs/benchmark-intelligence-agent/01-product-requirements.md) (93/100)
- [系统架构](/.claude/specs/benchmark-intelligence-agent/02-system-architecture.md) (94/100)
- [Phase 2-5测试报告](/docs/phase2-5-test-report.md)
- [Codex开发报告](/docs/codex-final-report.md)
- [飞书表格配置指南](/docs/feishu-bitable-setup.md)
- [数据源配置指南](/docs/data-sources-configuration-guide.md)

## License

MIT License
