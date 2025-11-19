# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Workflow & Roles

**🚨 强制规则：本项目采用双Agent协作模式，Claude Code禁止直接修改代码！**

### 角色分工

| 角色 | 职责 | 交付物 | 禁止事项 |
|------|------|--------|----------|
| **Claude Code** (你) | 产品规划、架构设计、**开发指令文档编写**、**测试执行**、进度监督、验收 | PRD、系统架构、开发prompt文档、测试报告、验收标准 | ❌ **绝对禁止直接修改代码**<br>❌ 禁止使用Edit/Write/MultiEdit工具修改.py文件<br>❌ 禁止修改src/目录下的任何代码 |
| **Codex** | 根据Claude Code提供的文档进行**具体编码实现** | 源代码、实现文档 | ❌ 禁止自行决策架构<br>❌ 禁止偏离开��指令文档 |

### Claude Code核心职责（详细说明）

#### 1️⃣ 需求分析与产品规划
- 深度理解用户需求（使用thinkdeep/debug等工具分析）
- 编写详细PRD文档（包含功能需求、技术约束、验收标准）
- 设计系统架构（数据模型、模块划分、接口设计）
- 评估技术可行性和风险

#### 2️⃣ 开发指令文档编写（最核心职责）
**这是Claude Code的核心价值所在！**

必须编写的文档类型：
- **PRD文档**：完整的产品需求文档
- **架构设计文档**：系统架构、数据流、模块划分
- **开发指令文档**：给Codex的详细实现指南，包含：
  - 问题诊断和根本原因分析
  - 解决方案设计（3层防御、Self-Healing机制等）
  - 逐步实施步骤（Step 1/2/3...）
  - 完整的代码示例（当前代码 vs 修复后代码）
  - 测试验证计划
  - 成功标准和检查清单

**文档质量标准**：
- ✅ 包含完整的"当前问题代码"和"修复后代码"对比
- ✅ 提供具体的文件路径和行号范围
- ✅ 说明修改原因和预期效果
- ✅ 附带测试验证方法
- ✅ 使用中文编写，清晰易懂
- ✅ 遵循Linus哲学（简单、实用、零破坏）

#### 3️⃣ 测试执行与验证
**Claude Code负责所有测试工作！**

测试类型：
- **单元测试**：使用Bash工具运行pytest
- **集成测试**：运行完整流程`.venv/bin/python -m src.main`
- **手动测试**：验证飞书表格、飞书通知、外部API交互
- **性能测试**：验证并发度、响应时间、错误率

测试报告要求：
- 记录测试命令和完整日志输出
- 附带截图（飞书表格数据、通知推送）
- 标注通过/失败的测试用例
- 分析失败原因并提出改进建议

#### 4️⃣ 进度监督与验收
- 使用TodoWrite工具跟踪任务进度
- 验收Codex提交的代码是否符合开发指令文档
- 检查代码质量（PEP8、类型注解、中文注释）
- 决策是否通过验收或打回修改

#### 5️⃣ 技术文档撰写
- 编写技术设计文档（如`docs/unified-llm-scorer-design.md`）
- 更新项目README和CLAUDE.md
- 编写测试报告和验收报告
- 记录关键技术决策（Why XXX instead of YYY?）

### Codex核心职责

#### 1️⃣ 代码实现（主力开发）
- 严格按照Claude Code提供的开发指令文档编写代码
- 实现所有功能需求和技术规范
- 遵循项目代码规范（PEP8、中文注释、Linus规则）
- 确保代码质量和可维护性

#### 2️⃣ 单元测试编写
- 为新功能编写单元测试
- 确保测试覆盖率≥80%
- 编写测试文档说明

#### 3️⃣ 实现文档
- 记录实现细节和技术选型理由
- 更新代码注释和docstring
- 提交清晰的commit message

### 工作流程（严格执行）

```
用户需求
    ↓
【Claude Code】深度分析需求
    ├─ 使用thinkdeep/debug工具诊断问题
    ├─ 编写PRD文档（产品需求）
    ├─ 设计系统架构
    └─ 编写详细开发指令文档（给Codex）
    ↓
【文档交接】Claude Code生成开发指令文档
    - 文档路径：.claude/specs/benchmark-intelligence-agent/CODEX-XXX.md
    - 包含：问题诊断 + 解决方案 + 实施步骤 + 代码示例 + 测试计划
    ↓
【Codex】阅读开发指令文档 → 编写代码 → 实现功能
    - 严格遵循文档中的设计方案
    - 实现所有Step（Step 1/2/3...）
    - 编写单元测试
    - 提交代码 + 实现文档
    ↓
【代码交接】Codex提交代码完成通知
    ↓
【Claude Code】执行测试验证
    ├─ 运行单元测试（pytest）
    ├─ 运行集成测试（完整流程）
    ├─ 手动验证（飞书表格、通知）
    └─ 生成测试报告（docs/test-report.md）
    ↓
【Claude Code】验收决策
    ├─ ✅ 通过：符合开发指令文档要求 → 交付用户
    └─ ❌ 打回：不符合要求 → 编写修复指令文档 → 返回Codex修复
```

### 开发指令文档位置与命名规范

**统一存放路径**：
```
.claude/specs/benchmark-intelligence-agent/
├── PHASE{N}-PROMPT.md              # 阶段总体指令（给Codex）
├── CODEX-{PHASE}-DETAILED.md       # 详细实现代码+测试用例
├── CODEX-URGENT-FIXES.md           # 紧急修复指令
├── CODEX-PHASE9-URGENT-FIX.md      # Phase 9紧急修复（推理长度问题）
└── docs/                           # 技术设计文档（Claude Code编写）
```

**文档命名规范**：
- `PHASE{N}-PROMPT.md` - 阶段总体开发指令
- `CODEX-{功能模块}-{类型}.md` - 具体功能模块指令
- `CODEX-URGENT-{问题描述}.md` - 紧急修复指令
- 所有文档必须包含：问题诊断 + 解决方案 + 实施步骤 + 代码示例 + 测试计划

### 协作示例

**❌ 错误做法（Claude Code直接改代码）**：
```
用户：LLM推理长度不足，评分失败
Claude Code：好的，我来修改src/scorer/llm_scorer.py...
[使用Edit工具直接修改代码] ← 这是错误的！
```

**✅ 正确做法（Claude Code编写指令文档）**：
```
用户：LLM推理长度不足，评分失败
Claude Code：
1. 我来诊断问题根因（使用thinkdeep分析日志）
2. 发现：LLM返回120字符，要求150字符，差距10-30字符
3. 设计解决方案：三层防御机制（增强Prompt + 增强System Message + Self-Healing）
4. 编写详细开发指令文档：CODEX-PHASE9-URGENT-FIX.md
5. 文档包含：
   - 问题诊断（数据统计、根本原因）
   - 解决方案（三层防御设计）
   - 实施步骤（Step 1/2/3，完整代码示例）
   - 测试计划（验证字符数、成功率）
6. 通知用户：请将文档交给Codex执行
7. Codex修复完成后，我执行测试验证
```

### Claude Code强制约束

**❌ 绝对禁止的操作**：
1. **禁止使用Edit/Write/MultiEdit工具修改.py文件**
2. **禁止直接修改src/目录下的任何代码**
3. **禁止修改config/、scripts/、tests/目录的代码**
4. **禁止在没有编写开发指令文档的情况下让Codex开发**

**✅ Claude Code应该做的**：
1. **深度分析问题**（使用Read/Grep/Bash查看代码和日志）
2. **编写开发指令文档**（详细的问题诊断+解决方��+实施步骤）
3. **执行测试验证**（运行Bash命令测试Codex的代码）
4. **编写技术文档**（PRD、架构设计、测试报告）
5. **验收和监督**（检查Codex的代码是否符合要求）

### 文档模板示例

参考已完成的优秀文档：
- `.claude/specs/benchmark-intelligence-agent/CODEX-PHASE9-URGENT-FIX.md` ← **最佳实践范例**
  - 包含：问题诊断（数据统计）
  - 包含：根本原因分析（4个层次）
  - 包含：解决方案（三层防御机制）
  - 包含：完���代码示例（当前代码 vs 修复后代码）
  - 包含：实施步骤（Step 1/2/3）
  - 包含：测试验证计划
  - 包含：成功标准和检查清单

---

## Project Overview

**BenchScope** = **Benchmark Intelligence Agent (BIA)**

一个自动化情报系统，每日采集AI/Agent领域的Benchmark资源，预筛选评分，推送到飞书，辅助研究团队高效筛选有价值的评测基准。

**服务于**: [MGX (https://mgx.dev)](https://mgx.dev) - 多智能体协作框架，专注Vibe Coding (AI原生编程)

### 核心目标

1. **系统性调研与评估**
   - 覆盖GUI/Web/Coding/DeepResearch/Agent协作等领域的新Benchmarks
   - 判断是否适合纳入现有Benchmark池以扩充覆盖面

2. **自动化情报流**
   - 建立"可定期更新"的自动化情报流
   - 降低人工维护成本，减少信息遗漏

3. **一键添加到候选池**
   - 提供完整Benchmark基础信息：论文地址、数据集地址、复现脚本、评估指标、开源时间等
   - 支持快速决策是否纳入Benchmark池

### 工作流（Workflow）

```
┌──────────────────────────────────────────────────────────────┐
│ 1. 自动发现（Auto Discovery）                                 │
│    - 论文库: arXiv, Semantic Scholar                          │
│    - 评测榜单: HELM                                           │
│    - 开源社区: GitHub, HuggingFace Hub                        │
└──────────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────────┐
│ 2. 预筛与评分（Pre-filter & Scoring）                        │
│    快速指标:                                                  │
│    - 活跃度 25%: GitHub stars/commits                         │
│    - 可复现性 30%: 代码/数据集开源状态                        │
│    - 许可合规 20%: MIT/Apache/BSD                             │
│    - 任务新颖性 15%: 与已有任务重叠度                         │
│    - MGX适配度 10%: LLM判断业务相关性                         │
│                                                               │
│    输出: 评分依据（说明为何作为候选Benchmark）                │
└──────────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────────┐
│ 3. 一键添加到Benchmark候选池（Feishu Bitable）               │
│    必需字段（支撑快速决策）:                                  │
│    ✅ 标题、来源、URL、摘要                                    │
│    ✅ 论文URL、数据集URL、复现脚本链接                        │
│    ✅ 评估指标摘要、开源时间、任务类型、License类型           │
│    ✅ GitHub Stars、作者信息                                  │
│    ✅ 5维评分 + 总分 + 优先级 + 评分依据                      │
└──────────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────────┐
│ 4. 飞书播报与人工审核（Human Review）                        │
│    - 每日自动推送Top候选项（交互式卡片）                       │
│    - 研究团队快速审核、标记状态（待评估/已采纳/已拒绝）        │
│    - 重要更新通知（GitHub Release、arXiv版本更新）            │
└──────────────────────────────────────────────────────────────┘
```

**当前项目状态**:
- 设计阶段: ✅ 完成 (PRD 93/100, 架构 94/100)
- 开发阶段: ✅ Phase 1-5 已完成, 🔄 Phase 6 进行中
- 关键决策: 存储层从Notion改为飞书多维表格(主) + SQLite(降级备份)
- 核心功能: arXiv/GitHub/HuggingFace/HELM/TechEmpower/DBEngines采集 + URL去重 + LLM评分(GPT-4o, 50并发) + 飞书存储/通知

**不做的事**：
- 不做SEO优化（纯内部系统）
- 不训练深度模型（规则+LLM抽取足够）
- 不追求100%自动化（关键决策保留人工）

## Architecture

### Core Modules

```
src/
├── collectors/              # 数据采集器
│   ├── arxiv_collector.py        # arXiv API (10s timeout, 3 retries)
│   ├── semantic_scholar_collector.py  # Semantic Scholar API (已禁用)
│   ├── helm_collector.py          # HELM Leaderboard scraper
│   ├── github_collector.py        # GitHub Search API (5s timeout)
│   ├── huggingface_collector.py   # HuggingFace Hub API
│   ├── techempower_collector.py   # TechEmpower Web框架性能基准
│   └── dbengines_collector.py     # DB-Engines数据库排名
│
├── prefilter/              # 规则预筛选
│   └── rule_filter.py          # URL去重 + 基础过滤 (过滤40-60%噪音)
│
├── scorer/                 # 评分引擎
│   ├── llm_scorer.py           # gpt-4o评分 (50并发) + Redis缓存 + 规则兜底
│   └── backend_scorer.py       # 后端Benchmark专项评分规则
│
├── storage/                # 存储层
│   ├── feishu_storage.py       # 飞书多维表格批量写入(20条/请求)
│   ├── sqlite_fallback.py      # SQLite降级备份(7天TTL, 自动回写)
│   └── storage_manager.py      # 主备切换管理器
│
├── notifier/               # 通知引擎
│   └── feishu_notifier.py      # 飞书Webhook推送 + 交互式卡片
│
├── api/                    # Web服务 (Phase 5, 可选)
│   └── feishu_callback.py      # Flask回调处理
│
├── common/
│   └── constants.py            # 魔法数字集中管理
│
├── models.py               # 数据模型定义 (RawCandidate, ScoredCandidate)
├── config.py               # 配置管理 (Settings, get_settings)
└── main.py                 # 流程编排器

config/
└── sources.yaml            # 数据源配置 (关键词、超时、时间窗口)

scripts/
├── analyze_logs.py         # 日志分析工具
├── create_feishu_fields.py     # 飞书表格字段初始化
├── deduplicate_feishu_table.py # 飞书表格去重
├── clear_feishu_table.py       # 飞书表格清空
└── test_layered_notification.py # 飞书通知测试
```

### Data Flow

```
GitHub Actions (每日UTC 2:00)
  ↓
main.py 编排器
  ↓
Step 1: 并发采集 (asyncio串行)
  ├─ ArxivCollector (10s timeout, 3 retries, 7天窗口)
  ├─ SemanticScholarCollector (15s timeout, 2年窗口)
  ├─ HelmCollector (20s timeout)
  ├─ GitHubCollector (5s timeout, 30天窗口)
  └─ HuggingFaceCollector (10s timeout, 14天窗口)
  ↓
Step 2: 规则预筛选 (prefilter_batch)
  - URL去重
  - GitHub: stars≥10, README≥500字, 90天内更新
  - HuggingFace: downloads≥100
  - 过滤率: 40-60%
  ↓
Step 3: LLM评分 (llm_scorer.py)
  - gpt-4o 5维评分 (activity/reproducibility/license/novelty/relevance)
  - 50并发异步评分 (asyncio.Semaphore控制)
  - Redis缓存(7天TTL), 命中率30%
  - 后端Benchmark自动识别与专项评分
  - 失败回退规则评分
  ↓
Step 4: 存储管理器 (storage_manager.py)
  ├─ Primary: 飞书多维表格 (批量写入20条/请求, 0.6s间隔)
  └─ Fallback: SQLite (降级备份, 7天自动同步)
  ↓
Step 5: 飞书通知 (feishu_notifier.py)
  - Webhook推送Top候选 (分层策略: High优先, Medium次之, Low补充)
  - 交互式卡片 + 按钮 (Phase 5)
```

## Technology Stack

| 模块 | 技术选型 | 关键依赖 |
|------|---------|---------|
| 数据采集 | Python + httpx | `arxiv`, `httpx`, `beautifulsoup4` |
| 智能评分 | OpenAI | `openai` (gpt-4o, 50并发) |
| 数据存储 | 飞书多维表格 + SQLite | `lark-oapi`, `sqlite3` |
| 缓存 | Redis | `redis` (7天TTL, 30%命中率) |
| 消息推送 | 飞书开放平台 | `lark-oapi` (Webhook) |
| 任务调度 | GitHub Actions | `.github/workflows/` |
| Web服务 | Flask (Phase 5, 可选) | 处理飞书回调 |

**为什么不用复杂方案**：
- 不用Airflow：任务依赖简单，GitHub Actions足够
- 不用向量数据库：候选池规模小（<1000条），Numpy计算相似度即可
- 不用PostgreSQL：飞书多维表格满足需求，还能让研究员直接操作
- 不用Notion：飞书生态统一，国内访问更稳定

## Development Commands

**重要规则：本项目强制使用uv虚拟环境**

所有Python命令必须使用uv虚拟环境执行：
- ✅ 虚拟环境路径: `/mnt/d/VibeCoding_pgm/BenchScope/.venv`
- ✅ 使用方式: `/mnt/d/VibeCoding_pgm/BenchScope/.venv/bin/python <script>`
- ❌ 不要使用: `python` 或 `python3` (可能使用错误的Python环境)

### Initial Setup

```bash
# 创建虚拟环境 (如果不存在)
python3.11 -m venv .venv

# 激活环境
source .venv/bin/activate

# 安装依赖
pip install --upgrade pip
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env.local
# 填写: OPENAI_API_KEY, FEISHU_APP_ID, FEISHU_APP_SECRET,
#      FEISHU_BITABLE_APP_TOKEN, FEISHU_BITABLE_TABLE_ID,
#      SEMANTIC_SCHOLAR_API_KEY, REDIS_URL (可选)
```

### Running the Main Pipeline

```bash
# 完整流程 (采集 → 预筛 → 评分 → 存储 → 通知)
# 注意: 必须从项目根目录运行，使用模块方式
.venv/bin/python -m src.main

# 或激活环境后运行
source .venv/bin/activate
python -m src.main
```

### Testing Individual Collectors

```bash
# 测试arXiv采集 (最近7天, 最多50条)
.venv/bin/python -c "
import asyncio
from src.collectors import ArxivCollector
async def test():
    collector = ArxivCollector()
    candidates = await collector.collect()
    print(f'采集到 {len(candidates)} 条')
asyncio.run(test())
"

# 测试GitHub采集 (最近30天, stars≥10)
.venv/bin/python -c "
import asyncio
from src.collectors import GitHubCollector
async def test():
    collector = GitHubCollector()
    candidates = await collector.collect()
    print(f'采集到 {len(candidates)} 条')
asyncio.run(test())
"
```

### Utility Scripts

```bash
# 分析日志 (采集/预筛/评分统计)
.venv/bin/python scripts/analyze_logs.py

# 创建飞书表格字段 (首次初始化)
.venv/bin/python scripts/create_feishu_fields.py

# 飞书表格去重
.venv/bin/python scripts/deduplicate_feishu_table.py

# 清空飞书表格 (危险操作!)
.venv/bin/python scripts/clear_feishu_table.py

# 测试飞书通知 (分层推送策略)
.venv/bin/python scripts/test_layered_notification.py
```

### Feishu Integration Testing

```bash
# 测试飞书存储写入
.venv/bin/python -c "
from src.storage import FeishuStorage
from src.models import ScoredCandidate
storage = FeishuStorage()
# 创建测试候选项并写入...
"

# 测试飞书通知推送
.venv/bin/python -c "
from src.notifier import FeishuNotifier
notifier = FeishuNotifier()
notifier.send_daily_digest([])  # 发送测试通知
"
```

### Manual Testing (强制执行)

**重要**: 飞书播报、飞书多维表格、外部API交互必须手动验证

1. 运行完整流程后检查飞书多维表格
2. 验证飞书通知是否正确推送
3. 检查日志文件 `logs/{YYYYMMDD}.log`
4. 将测试结果写入 `docs/test-report.md` 并附截图/日志

### Code Quality

```bash
# 代码格式化 (PEP8)
black .

# 代码检查
ruff check .

# 自动修复
ruff check --fix .
```

### Viewing Logs

```bash
# 查看最新日志
tail -f logs/$(ls -t logs/ | head -n1)

# 搜索错误
grep -i error logs/$(ls -t logs/ | head -n1)

# 分析日志统计
.venv/bin/python scripts/analyze_logs.py
```

## Configuration Files

### `config/sources.yaml` - 数据源配置

**关键配置**:

```yaml
arxiv:
  enabled: true
  max_results: 50
  lookback_hours: 168  # 7天窗口
  keywords: ["benchmark", "agent evaluation", "code generation"]
  categories: ["cs.AI", "cs.CL", "cs.SE"]

semantic_scholar:
  enabled: true
  lookback_years: 2
  max_results: 100
  venues: ["NeurIPS", "ICLR", "ICML", "ACL", "EMNLP", "NAACL"]

github:
  enabled: true
  lookback_days: 30  # 30天窗口
  min_stars: 10
  min_readme_length: 500
  max_days_since_update: 90

huggingface:
  enabled: true
  lookback_days: 14  # 14天窗口
  min_downloads: 100
  task_categories: ["text-generation", "question-answering"]

helm:
  enabled: true
  timeout_seconds: 20
```

**修改配置后无需重新部署，下次运行自动生效**

### `.env.local` - 环境变量

**必需**:
- `OPENAI_API_KEY` - OpenAI API密钥 (gpt-4o评分，建议Tier 2+账户支持50并发)
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET` - 飞书应用凭证
- `FEISHU_BITABLE_APP_TOKEN` - 飞书多维表格Token
- `FEISHU_BITABLE_TABLE_ID` - 飞书多维表格ID

**可选**:
- `REDIS_URL` - Redis连接URL (缓存LLM评分, 提升30%性能)
- `FEISHU_WEBHOOK_URL` - 飞书通知Webhook (用于推送)
- `GITHUB_TOKEN` - GitHub API Token (提升速率限制 5000→15000/h)

## Performance & Concurrency

### LLM评分并发配置

**核心配置** (`src/common/constants.py`):
```python
SCORE_CONCURRENCY: Final[int] = 50  # GPT-4o速率限制高，充分利用并发能力
LLM_MODEL: Final[str] = "gpt-4o"
LLM_TIMEOUT_SECONDS: Final[int] = 30
```

**并发控制实现** (`src/scorer/llm_scorer.py`):
```python
async def score_batch(self, candidates: List[RawCandidate]) -> List[ScoredCandidate]:
    semaphore = asyncio.Semaphore(constants.SCORE_CONCURRENCY)

    async def score_with_semaphore(candidate: RawCandidate) -> ScoredCandidate:
        async with semaphore:
            return await self.score(candidate)

    tasks = [score_with_semaphore(candidate) for candidate in candidates]
    results = await asyncio.gather(*tasks)
    return list(results)
```

**性能基准** (2025-11-17实测):
- **41条候选评分**: 12秒 (50并发)
- **加速比**: 11.7倍 vs 串行执行
- **完整流程**: 59秒 (采集38秒 + 评分12秒 + 其他9秒)
- **错误率**: 0% (无429速率限制错误)

**调优建议**:
- **Tier 1账户** (500 RPM): 保持30-35并发
- **Tier 2+账户** (5000 RPM): 可以使用50并发
- **调整方法**: 修改 `constants.py` 中的 `SCORE_CONCURRENCY`

## Code Quality Standards

### Python Style (PEP8强制)

- 4空格缩进，函数/变量 `snake_case`，类名 `PascalCase`
- 关键逻辑必须写**中文注释**
- 函数最大嵌套层级 ≤3（Linus规则）
- 魔法数字定义在 `src/common/constants.py`

**示例**:

```python
# src/common/constants.py
ACTIVITY_WEIGHT = 0.25
REPRODUCIBILITY_WEIGHT = 0.30
LICENSE_WEIGHT = 0.20
NOVELTY_WEIGHT = 0.15
RELEVANCE_WEIGHT = 0.10

SCORE_THRESHOLD = 6.0  # 低于6分直接过滤

# 飞书API限流
FEISHU_BATCH_SIZE = 20  # 每批次写入20条
FEISHU_RATE_LIMIT_DELAY = 0.6  # 请求间隔0.6秒

# 采集器超时
ARXIV_TIMEOUT = 10  # arXiv API超时10秒
GITHUB_TIMEOUT = 5  # GitHub API超时5秒
```

### Commit Convention

```bash
feat: add semantic scholar collector with venue filtering
fix(scorer): correct activity score calculation for repos with <100 stars
chore: update config/sources.yaml with new github topics
docs: add manual test report for feishu notification
refactor(storage): simplify feishu batch write logic
perf(scorer): add redis caching for llm scoring
```

**PR要求**:
- 问题背景
- 运行的命令
- 手动测试结果（截图/日志）
- 相关Issue/飞书讨论链接

## Key Design Decisions

### Why 飞书多维表格 Instead of Notion?

**技术决策时间**: 2025-11-13
**决策结果**: 飞书多维表格(主) + SQLite(降级备份)

**理由**:
1. **国内稳定性**: 飞书国内访问稳定,Notion常被墙
2. **API限额**: 飞书100请求/分钟 > Notion 3请求/秒(实际更严格)
3. **生态统一**: 团队已使用飞书,减少工具切换
4. **降级策略**: SQLite本地备份,7天自动同步,防数据丢失
5. **成本**: 飞书免费额度足够,Notion付费版才能API集成

### Why GitHub Actions Instead of Airflow?

- 任务依赖简单（串行采集+评分+入库）
- 免运维（不需要部署scheduler）
- 免费额度足够（每日5分钟任务 << 2000分钟/月）
- 迁移成本低（需要时改为Cron即可）

### Why gpt-4o with 50 Concurrency?

**技术决策时间**: 2025-11-17
**决策结果**: gpt-4o + 50并发异步评分

**理由**:
1. **性能提升**: gpt-4o质量优于gpt-4o-mini，评分更准确
2. **并发优化**: 50并发将LLM评分从140秒降至12秒（11.7倍加速）
3. **成本可控**: 规则预筛选50% + 后端专项评分 + Redis缓存30% → 月成本仍在预算内
4. **速率限制**: Tier 2+账户支持5000 RPM，50并发仅需750 RPM
5. **无错误**: 实测50并发无429错误，稳定性验证通过

**实测数据** (2025-11-17):
- 41条候选LLM评分耗时: 12秒
- 完整流程耗时: 59秒 (包含采集38秒)
- 并发控制: asyncio.Semaphore确保最多50个同时请求

## Implementation Phases

**当前状态**: Phase 1-5 已完成 ✅ → Phase 6 待开始 ⏭️

### Phase 0 (已完成) - 设计阶段 ✅
- [x] 仓库初始化与需求分析
- [x] PRD文档编写 (93/100质量分)
- [x] 系统架构设计 (94/100质量分)
- [x] 技术选型决策 (存储层: 飞书多维表格)
- [x] Codex开发指令文档准备

### Phase 1-2 (已完成) - MVP实施 ✅

**完成时间**: 2025-11-02 ~ 2025-11-08

- [x] 数据模型定义 (`src/models.py`)
- [x] 配置管理 (`src/config.py`)
- [x] 数据采集器 (5个采集器)
- [x] 规则预筛选 (`src/prefilter/rule_filter.py`)
- [x] LLM评分引擎 (`src/scorer/llm_scorer.py`)
- [x] 存储层 (飞书+SQLite+StorageManager)
- [x] 飞书通知 (`src/notifier/feishu_notifier.py`)
- [x] 主编排器 (`src/main.py`)
- [x] GitHub Actions工作流

**验收结果**:
- [x] GitHub Actions每日自动运行 ✅
- [x] 飞书多维表格自动写入 ✅
- [x] 飞书通知每日推送 ✅
- [x] 执行时间 < 20分钟 ✅ (实际~60秒，50并发优化后)
- [x] LLM月成本 < ¥50 ✅ (gpt-4o + 50并发，预计¥20/月)

### Phase 3-5 (已完成) - 优化与增强 ✅

**完成时间**: 2025-11-13

**Phase 3 - 核心优化**:
- [x] 移除Papers with Code采集器
- [x] 优化GitHub预筛选规则 (stars≥10, README≥500, 90天更新)
- [x] 实现时间窗口过滤 (GitHub 30天, HuggingFace 14天, arXiv 7天)
- [x] 创建日志分析工具 (`scripts/analyze_logs.py`)

**Phase 4 - 版本跟踪（已在2025-11-19下线）**:
- ❌ GitHub Release监控 (`src/tracker/github_tracker.py`) → 已移除
- ❌ arXiv版本更新提醒 (`src/tracker/arxiv_tracker.py`) → 已移除
- ❌ GitHub Actions定时任务 (`.github/workflows/track_releases.yml`) → 已删除
- ✅ 决策：版本监控偏离“发现新Benchmark”的核心目标

**Phase 5 - 增强功能**:
- [x] 飞书卡片消息 (交互式卡片 + 按钮)
- [x] 分层推送策略 (High/Medium/Low优先级)

**Phase 7 - 后端扩展与性能优化** ✅:
- [x] 新增TechEmpower Web框架性能基准采集器
- [x] 新增DBEngines数据库排名采集器
- [x] 后端Benchmark专项评分规则 (backend_scorer.py)
- [x] LLM并发优化: 从串行升级到50并发 (11.7倍加速)
- [x] 模型升级: gpt-4o-mini → gpt-4o (评分质量提升)

**总结**:
- 核心任务完成率: 100%
- 代码质量: ⭐⭐⭐⭐⭐ (10/10)
- 性能优化: LLM评分12秒完成41条 (50并发)
- 详细报告: `docs/codex-final-report.md`

### Phase 6 (待开始) - 信息源扩展与数据完善 ⏭️

**预计工期**: 2-3周
**详细PRD**: `.claude/specs/benchmark-intelligence-agent/PHASE6-EXPANSION-PRD.md`

**核心任务**:
- [ ] Task 6.1: 扩展会议论文采集 (Semantic Scholar ✅ 已完成, ACL Anthology)
- [ ] Task 6.2: 接入评测榜单 (HELM ✅ 已完成, Open LLM Leaderboard, EvalPlus)
- [ ] Task 6.3: 优化GitHub搜索策略 (排除awesome lists, 验证Benchmark特征)
- [ ] Task 6.4: 完善飞书表格字段 (新增9个字段)
- [ ] Task 6.5: 优化预筛选规则 (Benchmark特征检测)
- [ ] Task 6.6: 优化LLM评分Prompt (区分工具vs Benchmark)

**Phase 6 目标**:
- 信息源覆盖: 30% → 80% (+167%)
- 真实Benchmark占比: <20% → ≥60% (+200%)
- 预筛选过滤率: 0% → 30-50%
- 平均评分: 8.61 → 6.0-7.5
- 数据字段完整性: 13/22 → 22/22 (+69%)

## Critical Constraints

1. **手动测试强制执行**：
   - 飞书播报、飞书多维表格、外部API交互必须手动验证
   - 结果写入 `docs/test-report.md` 并附截图/日志

2. **评分逻辑变更流程**：
   - 修改 `src/scorer/llm_scorer.py` 前需提供最小可复现脚本
   - 提供样例输入和预期输出
   - PR附变更前后对比测试结果

3. **Linus哲学约束** (来自全局CLAUDE.md):
   - **Is this a real problem?** → 拒绝过度工程
   - **Is there a simpler way?** → 永远寻找最简单实现
   - **What will this break?** → MVP零破坏(纯新项目)
   - 最大嵌套层级 ≤ 3
   - 关键逻辑必须中文注释

## GitHub Actions Workflows

### Daily Collection (`.github/workflows/daily_collect.yml`)

**触发**: 每天 UTC 02:00 (北京时间 10:00)
**步骤**:
1. Checkout代码
2. 安装Python 3.11 + 依赖
3. 配置环境变量 (从GitHub Secrets)
4. 运行 `src/main.py`
5. 上传日志和SQLite备份到Artifacts (保留7天)

> ℹ️ 版本监控Workflow已在2025-11-19下线，所有CI/CD资源专注每日采集流水线。

## Common Pitfalls

1. **不要过度工程化**：
   - 不需要Airflow（GitHub Actions足够）
   - 不需要向量数据库（Numpy足够）
   - 不需要训练模型（规则+LLM足够）

2. **不要忽略人工环节**：
   - 关键决策（入库确认）保留人工
   - LLM抽取结果需要规则兜底
   - 评分权重需要定期复盘调整

3. **不要破坏向后兼容**：
   - 修改飞书字段前先迁移旧数据
   - 修改飞书卡片格式前测试回调兼容性
   - 修改评分算法前对比历史候选池评分

4. **不要忽视存储降级**：
   - 飞书API失败时SQLite自动兜底
   - 7天内自动同步,不要手动干预
   - 监控SQLite大小,超过阈值告警

## Reference Documents

### 核心设计文档 (BMAD产出)

- `.claude/specs/benchmark-intelligence-agent/00-repo-scan.md` - 仓库扫描报告
- `.claude/specs/benchmark-intelligence-agent/01-product-requirements.md` - PRD文档 (93/100)
- `.claude/specs/benchmark-intelligence-agent/02-system-architecture.md` - 系统架构 (94/100)
- `.claude/specs/benchmark-intelligence-agent/CODEX-COMPREHENSIVE-PLAN.md` - Phase 3-5开发方案 ✅
- `.claude/specs/benchmark-intelligence-agent/PHASE6-EXPANSION-PRD.md` - Phase 6开发PRD ⏭️

### 测试报告

- `docs/phase2-5-test-report.md` - Phase 2-5完整测试报告 (2025-11-13)
- `docs/codex-final-report.md` - Codex开发完成报告

### 项目规范

- `README.md` - 快速开始指南
- `AGENTS.md` - 仓库规范与约束
- `.claude/commands/arrange.md` - 文件整理规范
- `.claude/commands/deploy.md` - GitHub部署规范

## Monitoring & Debugging

### Key Metrics (记录在日志中)

- 每日采集成功率（目标 >95%）
- 预筛选通过率（目标 10-30%）
- 飞书消息送达率（目标 100%）
- 候选池增长速度（目标 2-5个/周）

### Logging

日志位置: `logs/{YYYYMMDD}.log`

格式:
```
2025-11-13 10:30:45 - BIA - INFO - [1/5] 数据采集...
2025-11-13 10:30:46 - BIA - INFO -   ✓ ArxivCollector: 12条
2025-11-13 10:30:47 - BIA - WARNING - GitHub API限流，等待60秒
2025-11-13 10:30:48 - BIA - ERROR - 飞书写入失败: rate limit exceeded
```

### 常用排查命令

```bash
# 查看最新日志
tail -100 logs/$(ls -t logs/ | head -n1)

# 搜索错误
grep -i error logs/$(ls -t logs/ | head -n1)

# 统计采集成功率
.venv/bin/python scripts/analyze_logs.py

# 检查SQLite降级备份
sqlite3 fallback.db "SELECT COUNT(*) FROM candidates;"

# 检查Redis缓存状态 (如果配置了Redis)
redis-cli ping
redis-cli dbsize
```

## Success Criteria

| 指标 | 现状 | 目标 | 验收标准 |
|------|------|------|---------|
| Benchmark发现速度 | 人工2-3个/月 | 系统10-20个/月 | 持续3个月达标 |
| 信息筛选效率 | 人工阅读200篇论文 | 预筛选后阅读20篇 | 噪音过滤率90%+ |
| 入库响应时间 | 发现后1-2周 | 发现后1-3天 | 自动播报延迟<24h |
| 候选池质量 | 无评分标准 | 入库后实际使用率>50% | 追踪3个月数据 |

3个月后，团队应该能够：
- 每周自动获取10-20个高质量候选Benchmark
- 信息噪音过滤率达到90%以上
- 从"被动搜索"变为"主动推送"
- Benchmark候选池规模扩大3-5倍
