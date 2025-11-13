# BenchScope Phase 2 开发指令

## 开发背景

**当前状态**: Phase 1 MVP已完成,核心采集功能验证通过
- ✅ 4个数据源采集器已实现 (arXiv, GitHub, PwC, HuggingFace)
- ✅ 时区处理、错误重试、并发采集已验证
- ✅ 单元测试 5/5 通过
- ✅ 集成测试系统正常运行
- ✅ 性能达标 (<5秒 vs 目标<20分钟)
- ✅ HuggingFace采集器集成完成
- ✅ 已修复3个关键Bug (语法错误、API兼容性、时区处理)

**待开发功能**: Phase 2 核心评分与存储系统

## 技术约束

### 环境要求
- Python 3.11.14 (uv管理)
- Redis 7.0.15 (本地或容器)
- 飞书开放平台账号 + API凭证
- OpenAI API (gpt-4o-mini推荐)

### 代码规范 (强制执行)
- PEP8合规,使用`black`和`ruff`自动格式化
- 关键逻辑必须写中文注释
- 最大嵌套层级 ≤ 3 (Linus规则)
- 魔法数字定义在`src/common/constants.py`
- 测试覆盖率 ≥ 60%

### 文档规范 (强制执行)
- 禁止使用emoji (代码、文档、日志、commit message)
- 禁止"让我们..."、"首先..."等机器化过渡词
- 必须基于真实数据,严禁虚构示例
- 必须具体量化,不用"大幅"、"显著"等模糊词
- 中文技术文档,说人话不说官话

### 禁止事项
- 不使用emoji (文档、日志、代码注释、commit message)
- 不引入深度学习框架 (TensorFlow/PyTorch)
- 不使用Airflow/Celery等重型调度器
- 不破坏现有采集器接口
- 不添加"Generated with Claude Code"或Co-Authored-By

## Phase 2 开发任务清单

### Task 1: 规则预筛选引擎 (优先级: P0)

**目标**: 过滤掉50%低质量候选,减少LLM调用成本

**实现位置**: `src/prefilter/rule_filter.py`

**核心逻辑**:
```python
def prefilter(candidate: RawCandidate) -> bool:
    """
    预筛选规则:
    1. 标题长度 >= 10字符
    2. 摘要非空
    3. URL有效且可访问
    4. 来源在白名单内 (arxiv/github/pwc/huggingface)
    5. 关键词匹配 (至少1个benchmark相关词)

    返回: True=保留, False=过滤
    """
```

**关键词白名单** (定义在`src/common/constants.py`):
```python
BENCHMARK_KEYWORDS = [
    "benchmark", "evaluation", "leaderboard", "dataset",
    "agent", "coding", "reasoning", "tool use", "multi-agent"
]
```

**测试要求**:
- 单元测试覆盖所有规则分支
- 提供10个正样本和10个负样本
- 验证过滤率在40-60%区间

---

### Task 2: LLM评分引擎 (优先级: P0)

**目标**: 使用gpt-4o-mini对候选进行5维度评分

**实现位置**: `src/scorer/llm_scorer.py`

**评分维度** (权重见`config/weights.yaml`):
1. **活跃度** (25%): GitHub stars/commits/issues
2. **可复现性** (30%): 代码/数据/文档开源状态
3. **许可合规** (20%): MIT/Apache/BSD优先
4. **任务新颖性** (15%): 与已有benchmark相似度
5. **MGX适配度** (10%): 与业务需求相关性

**Prompt设计** (关键):
```python
SCORING_PROMPT = """
你是AI Benchmark评估专家。请对以下候选进行评分(0-10分):

候选信息:
- 标题: {title}
- 来源: {source}
- 摘要: {abstract}
- GitHub信息: {github_stats}

评分维度:
1. 活跃度 (GitHub stars/更新频率)
2. 可复现性 (代码/数据开源状态)
3. 许可合规 (MIT/Apache/BSD优先)
4. 任务新颖性 (是否有独特价值)
5. MGX适配度 (与多智能体/代码生成的相关性)

输出JSON格式:
{{
  "activity_score": 7.5,
  "reproducibility_score": 9.0,
  "license_score": 10.0,
  "novelty_score": 6.0,
  "relevance_score": 8.5,
  "reasoning": "简要说明评分依据"
}}
"""
```

**Redis缓存策略**:
- Key格式: `llm_score:{md5(title+url)}`
- TTL: 7天
- 命中率目标: 30%+

**错误处理**:
- LLM调用失败 → 使用规则评分兜底
- 响应格式错误 → 记录日志并降级
- API限流 → 指数退避重试 (tenacity)

**测试要求**:
- Mock OpenAI API调用
- 验证JSON解析鲁棒性
- 验证缓存命中/未命中场景

---

### Task 3: 飞书多维表格存储 (优先级: P0)

**目标**: 将评分后的候选写入飞书多维表格

**实现位置**: `src/storage/feishu_storage.py`

**表格字段设计**:
| 字段名 | 类型 | 说明 |
|--------|------|------|
| title | 文本 | 候选标题 |
| source | 单选 | arxiv/github/pwc/huggingface |
| url | URL | 原始链接 |
| abstract | 多行文本 | 摘要 |
| activity_score | 数字 | 活跃度评分 (0-10) |
| reproducibility_score | 数字 | 可复现性评分 (0-10) |
| license_score | 数字 | 许可合规评分 (0-10) |
| novelty_score | 数字 | 任务新颖性评分 (0-10) |
| relevance_score | 数字 | MGX适配度评分 (0-10) |
| total_score | 数字 | 加权总分 (0-10) |
| priority | 单选 | 高/中/低 (根据总分自动设置) |
| status | 单选 | 待审核/已采纳/已拒绝 |
| github_stars | 数字 | GitHub星数 (如有) |
| github_url | URL | GitHub仓库地址 (如有) |
| created_at | 日期 | 采集时间 |

**批量写入策略**:
- 每批20条记录 (飞书API限制)
- 批次间隔0.6秒 (避免限流)
- 使用`lark-oapi` SDK

**API调用示例**:
```python
from lark_oapi import Client
from lark_oapi.api.bitable.v1 import CreateAppTableRecordRequest

client = Client.builder() \
    .app_id(settings.feishu.app_id) \
    .app_secret(settings.feishu.app_secret) \
    .build()

records = [
    {
        "fields": {
            "title": candidate.title,
            "source": candidate.source,
            "total_score": candidate.total_score,
            # ... 其他字段
        }
    }
]

request = CreateAppTableRecordRequest.builder() \
    .app_token(settings.feishu.bitable_app_token) \
    .table_id(settings.feishu.bitable_table_id) \
    .body(records) \
    .build()

response = client.bitable.v1.app_table_record.create(request)
```

**错误处理**:
- API失败 → 降级到SQLite备份
- 限流 (429) → 等待后重试
- 网络超时 → 3次重试后放弃

**测试要求**:
- Mock飞书API调用
- 验证批量写入逻辑
- 验证字段映射正确性

---

### Task 4: SQLite降级备份 (优先级: P1)

**目标**: 飞书API失败时自动降级到本地SQLite

**实现位置**: `src/storage/sqlite_fallback.py`

**表结构**:
```sql
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    abstract TEXT,
    activity_score REAL,
    reproducibility_score REAL,
    license_score REAL,
    novelty_score REAL,
    relevance_score REAL,
    total_score REAL,
    priority TEXT,
    status TEXT DEFAULT 'pending',
    github_stars INTEGER,
    github_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    synced_to_feishu BOOLEAN DEFAULT 0
);

CREATE INDEX idx_synced ON candidates(synced_to_feishu);
CREATE INDEX idx_created_at ON candidates(created_at);
```

**自动同步逻辑**:
- 每次运行开始时检查未同步记录
- 尝试同步到飞书
- 同步成功后标记`synced_to_feishu=1`
- 7天后自动清理已同步记录

**测试要求**:
- 验证表结构创建
- 验证自动同步逻辑
- 验证7天TTL清理

---

### Task 5: 存储管理器 (优先级: P0)

**目标**: 封装飞书(主)+SQLite(备)双存储策略

**实现位置**: `src/storage/storage_manager.py`

**核心逻辑**:
```python
class StorageManager:
    def __init__(self):
        self.primary = FeishuStorage()
        self.fallback = SQLiteFallback()

    async def save_candidates(self, candidates: List[ScoredCandidate]):
        """
        存储策略:
        1. 尝试写入飞书多维表格
        2. 失败 → 降级到SQLite
        3. 记录降级事件到日志
        """
        try:
            await self.primary.save(candidates)
            logger.info(f"飞书写入成功: {len(candidates)}条")
        except Exception as e:
            logger.error(f"飞书写入失败,降级到SQLite: {e}")
            await self.fallback.save(candidates)

    async def sync_pending_records(self):
        """
        同步SQLite中未同步的记录到飞书
        """
        pending = await self.fallback.get_pending()
        if not pending:
            return

        try:
            await self.primary.save(pending)
            await self.fallback.mark_synced(pending)
            logger.info(f"同步成功: {len(pending)}条")
        except Exception as e:
            logger.warning(f"同步失败,下次重试: {e}")
```

**测试要求**:
- 验证主存储成功场景
- 验证降级到备份场景
- 验证自动同步逻辑

---

### Task 6: 飞书通知推送 (优先级: P1)

**目标**: 每日推送Top 5候选到飞书群聊

**实现位置**: `src/notifier/feishu_notifier.py`

**消息格式** (Markdown富文本):
```python
message_text = f"""今日发现 {len(top5)} 个高质量Benchmark

{format_benchmark_list(top5)}

详情: {feishu_table_url}
"""
```

**格式化函数**:
```python
def format_benchmark_list(candidates):
    lines = []
    for i, c in enumerate(candidates, 1):
        lines.append(f"{i}. {c.title} (评分: {c.total_score:.1f}/10)")
        lines.append(f"   来源: {c.source} | {c.url}")
        lines.append(f"   摘要: {c.abstract[:100]}...")
    return "\n".join(lines)
```

**推送策略**:
- 按总分排序取Top 5
- 每日UTC 2:30推送 (采集后30分钟)
- 使用简洁文本格式 (禁止emoji)

**错误处理**:
- Webhook调用失败 → 记录日志但不中断流程
- 限流 → 等待后重试1次

**测试要求**:
- Mock Webhook调用
- 验证消息格式正确性
- 验证Top 5排序逻辑

---

### Task 7: 主流程编排器 (优先级: P0)

**目标**: 串联采集→预筛选→评分→存储→通知全流程

**实现位置**: `src/main.py`

**流程图**:
```
开始
 ↓
并发采集 (4个数据源)
 ↓
规则预筛选 (过滤50%)
 ↓
LLM评分 (gpt-4o-mini + Redis缓存)
 ↓
加权计算总分 + 优先级判定
 ↓
存储管理器 (飞书主+SQLite备)
 ↓
飞书通知 (Top 5推送)
 ↓
结束
```

**核心代码**:
```python
async def main():
    # 1. 同步SQLite待同步记录
    storage_mgr = StorageManager()
    await storage_mgr.sync_pending_records()

    # 2. 并发采集
    collectors = [
        ArxivCollector(),
        GitHubCollector(),
        PwCCollector(),
        HuggingFaceCollector()
    ]

    raw_candidates = []
    tasks = [collector.collect() for collector in collectors]
    results = await asyncio.gather(*tasks)
    for result in results:
        raw_candidates.extend(result)

    logger.info(f"采集完成: 共{len(raw_candidates)}个候选")

    # 3. 规则预筛选
    filtered = [c for c in raw_candidates if prefilter(c)]
    filter_rate = 100 * (1 - len(filtered) / len(raw_candidates)) if raw_candidates else 0
    logger.info(f"预筛选后: {len(filtered)}个候选 (过滤率{filter_rate:.1f}%)")

    # 4. LLM评分
    scorer = LLMScorer()
    scored = await scorer.score_batch(filtered)
    logger.info(f"评分完成: {len(scored)}个候选")

    # 5. 计算总分和优先级
    for candidate in scored:
        candidate.total_score = calculate_weighted_score(candidate)
        candidate.priority = assign_priority(candidate.total_score)

    # 6. 存储
    await storage_mgr.save_candidates(scored)

    # 7. 飞书通知
    notifier = FeishuNotifier()
    top5 = sorted(scored, key=lambda x: x.total_score, reverse=True)[:5]
    await notifier.send_daily_report(top5)

    logger.info("流程执行完成")
```

**性能目标**:
- 总执行时间 < 20分钟 (GitHub Actions限制)
- LLM调用 < 100次/天 (成本控制)
- 内存占用 < 500MB

**测试要求**:
- 端到端集成测试
- Mock所有外部API
- 验证错误恢复机制

---

## 配置文件更新

### `config/weights.yaml`
```yaml
scoring:
  activity:
    weight: 0.25
    thresholds:
      stars: [100, 500, 1000]  # 分档: 低/中/高
      update_days: [7, 30, 90]

  reproducibility:
    weight: 0.30
    has_code: 6      # 有代码仓库得6分
    has_dataset: 3   # 有数据集得3分
    has_doc: 1       # 有文档得1分

  license:
    weight: 0.20
    approved: ["MIT", "Apache-2.0", "BSD-3-Clause"]

  novelty:
    weight: 0.15
    similarity_threshold: 0.8  # 相似度>0.8视为重复

  relevance:
    weight: 0.10
    mgx_keywords: ["multi-agent", "code generation", "tool use"]

priority_thresholds:
  high: 8.0   # 总分 >= 8.0
  medium: 6.0 # 总分 >= 6.0
  low: 0.0    # 总分 < 6.0
```

### `src/common/constants.py`
```python
# 预筛选关键词
BENCHMARK_KEYWORDS = [
    "benchmark", "evaluation", "leaderboard", "dataset",
    "agent", "coding", "reasoning", "tool use", "multi-agent"
]

# LLM配置
LLM_MODEL = "gpt-4o-mini"
LLM_MAX_RETRIES = 3
LLM_TIMEOUT_SECONDS = 30

# Redis缓存
REDIS_TTL_DAYS = 7
REDIS_KEY_PREFIX = "benchscope:"

# 飞书API
FEISHU_BATCH_SIZE = 20
FEISHU_RATE_LIMIT_DELAY = 0.6  # 秒

# 评分阈值
MIN_TOTAL_SCORE = 6.0  # 低于6分不入库
```

---

## 验收标准

### 功能验收
- [ ] 规则预筛选过滤率在40-60%
- [ ] LLM评分返回5维度分数
- [ ] 飞书多维表格自动写入
- [ ] SQLite降级备份生效
- [ ] 飞书通知每日推送Top 5
- [ ] 完整流程执行时间 < 20分钟

### 质量验收
- [ ] 单元测试覆盖率 ≥ 60%
- [ ] 所有测试通过 (pytest)
- [ ] 代码PEP8合规 (black + ruff)
- [ ] 手动测试通过 (docs/test-report.md更新)

### 成本验收
- [ ] LLM月成本 < ¥50
- [ ] Redis缓存命中率 ≥ 30%
- [ ] 飞书API调用 < 100次/天

---

## 开发流程建议

### 开发顺序
1. **Day 1-2**: Task 1 (规则预筛选) + Task 6 (飞书通知)
   - 先实现简单模块,验证集成路径
2. **Day 3-5**: Task 2 (LLM评分)
   - 核心复杂度,需充分测试
3. **Day 6-7**: Task 3 (飞书存储) + Task 4 (SQLite备份)
   - 存储层双写逻辑
4. **Day 8**: Task 5 (存储管理器)
   - 封装主备切换
5. **Day 9-10**: Task 7 (主流程编排) + 集成测试
   - 端到端验证

### 测试策略
- 单元测试: 每个模块独立测试
- 集成测试: Mock外部API,验证流程
- 手动测试: 真实API调用,记录到test-report.md

### Git提交规范
```bash
feat(scorer): implement LLM scoring with Redis cache
fix(storage): handle Feishu API rate limiting
test(prefilter): add unit tests for keyword matching
docs(test-report): add Phase 2 manual test results
```

**严格禁止**:
- 不添加emoji到commit message
- 不添加"Generated with Claude Code"footer
- 不添加"Co-Authored-By: Claude"

---

## 参考文档

- [飞书开放平台文档](https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/create)
- [OpenAI API文档](https://platform.openai.com/docs/api-reference)
- [lark-oapi Python SDK](https://github.com/larksuite/oapi-sdk-python)
- [BenchScope PRD](.claude/specs/benchmark-intelligence-agent/01-product-requirements.md)
- [BenchScope架构设计](.claude/specs/benchmark-intelligence-agent/02-system-architecture.md)

---

## 常见问题

**Q: LLM评分太慢怎么办?**
A:
1. 开启Redis缓存 (7天TTL)
2. 规则预筛选过滤更多噪音
3. 批量评分而非逐条调用

**Q: 飞书API限流怎么处理?**
A:
1. 批量写入 (20条/批)
2. 批次间隔0.6秒
3. 429错误时指数退避重试

**Q: SQLite同步失败怎么办?**
A:
1. 下次运行时自动重试
2. 7天内多次尝试同步
3. 超过7天的记录不再同步

**Q: 如何降低LLM成本?**
A:
1. 使用gpt-4o-mini (成本1/10)
2. 规则预筛选50% (减少调用量)
3. Redis缓存30% (避免重复评分)

---

**Codex开发提示**:
- 严格遵循Linus哲学: 简单优先,拒绝过度工程
- 所有外部API调用必须Mock测试
- 手动测试结果记录到`docs/test-report.md`
- 禁止使用emoji (代码、文档、日志、commit message)
- 关键决策点需要询问用户确认
- 禁止添加"Generated with Claude Code"或Co-Authored-By

---

**当前进度总结**:
- Phase 1 MVP: 采集器全部完成,测试通过
- 待开发: Phase 2评分+存储系统 (7个任务)
- GitHub Actions: 已配置自动化workflow
- 环境: uv+Redis+飞书全部就绪
