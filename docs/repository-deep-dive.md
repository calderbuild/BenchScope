# BenchScope 仓库深度解析

## 项目定位

BenchScope是一个自动化Benchmark情报系统，专为MGX多智能体协作框架服务。每天自动采集AI/Agent领域的评测基准，通过规则预筛选+LLM智能评分，过滤掉80-90%的噪音数据，将高质量候选推送到飞书多维表格，辅助研究团队快速决策是否纳入Benchmark池。

**核心价值**：把研究员从"每月人工阅读200篇论文、筛选2-3个Benchmark"的低效模式，转变为"每月系统推荐40-60个候选、团队审核后采纳10-20个"的高效模式。3个月内Benchmark候选池规模预期扩大3-5倍。

**服务对象**：[MGX (https://mgx.dev)](https://mgx.dev) - AI原生多智能体协作框架，专注Vibe Coding（编程、Web开发、后端优化、GUI自动化等场景）

## 技术架构

### 数据流全景（6步流水线）

```
GitHub Actions (每日UTC 2:00触发)
    ↓
【Step 1】并发采集 (7个采集器)
    ├─ ArxivCollector: 学术论文 (7天窗口, 10s超时)
    ├─ GitHubCollector: 开源项目 (30天窗口, 5s超时, stars≥50)
    ├─ HelmCollector: HELM榜单 (场景过滤, 15s超时)
    ├─ HuggingFaceCollector: 数据集 (14天窗口, min_downloads≥100)
    ├─ TechEmpowerCollector: Web框架性能基准
    ├─ DBEnginesCollector: 数据库排名
    └─ TwitterCollector: 社交媒体 (默认禁用, 需付费API)
    ↓ 输出: RawCandidate列表 (40-80条)

【Step 1.5】URL去重
    - 本次采集内部去重 (保留第一次出现)
    - 与飞书已存URL去重 (避免重复推送)
    ↓ 输出: 去重后候选 (30-60条)

【Step 2】规则预筛选 (rule_filter.py)
    - GitHub: stars≥50, README≥500字, 90天内更新, 必须有Benchmark特征
    - 关键词白名单: code/benchmark/performance/agent/web/backend等24个
    - 关键词黑名单: awesome-list/tutorial/wrapper等
    - 权威来源豁免: HELM/TechEmpower/DBEngines直接通过
    ↓ 输出: 预筛选后候选 (15-40条, 过滤率40-60%)

【Step 3】PDF内容增强 (pdf_enhancer.py)
    - 仅处理arXiv论文: 下载PDF → GROBID解析 → 提取Evaluation/Dataset/Baselines章节
    - 云端GROBID服务 (kermitt2-grobid.hf.space, 3并发)
    - 失败降级: 本地GROBID (localhost:8070) → 跳过
    ↓ 输出: 增强后候选 (raw_metadata包含PDF摘要, 2000+字符)

【Step 4】LLM智能评分 (llm_scorer.py)
    - 模型: gpt-4o (质量优先, 月成本<$20)
    - 并发: 50并发异步评分 (asyncio.Semaphore控制)
    - 缓存: Redis (7天TTL, 命中率30%)
    - 评分维度: 5维基础评分 + 2维后端专项评分
    - 推理要求: 每个维度≥150字符, 后端专项≥200字符, 总推理≥1200字符
    - Self-Healing: 字符不足时自动重试补充 (最多2次)
    ↓ 输出: ScoredCandidate列表 (26个字段, 总分0-10)

【Step 5】存储入库 (storage_manager.py)
    - 主存储: 飞书多维表格 (批量写入20条/请求, 0.6s间隔)
    - 降级备份: SQLite (本地fallback.db, 7天TTL, 自动回写)
    - 主备切换: 飞书失败自动降级SQLite, 下次运行自动同步
    ↓ 输出: 飞书表格新增记录 (22个字段)

【Step 6】飞书通知 (feishu_notifier.py)
    - 分层推送: High优先 (总分≥8.0) → Medium次之 (≥6.0) → Low补充
    - 交互式卡片: 标题/来源/评分/推理/快速操作按钮
    - Webhook推送: 研究群即时收到通知
    ↓ 输出: 飞书消息 (TopK=5条High + 5条Medium)
```

**性能数据** (2025-11-17实测):
- 采集耗时: 38秒 (7个采集器串行执行)
- 评分耗时: 12秒 (41条候选, 50并发, 11.7倍加速)
- 完整流程: 59秒 (采集+去重+预筛选+评分+存储+通知)

### 核心模块职责

| 模块 | 文件路径 | 核心职责 | 关键技术 |
|------|---------|---------|---------|
| **流程编排器** | `src/main.py` | 串行编排6步流水线, 异常容错, 日志聚合 | asyncio, logging |
| **数据模型** | `src/models.py` | RawCandidate (13字段) → ScoredCandidate (37字段) | dataclass, slots=True |
| **配置系统** | `src/config.py` | 环境变量 + YAML配置 + 数据源设置 | pydantic, dotenv |
| **采集器基础** | `src/collectors/*.py` | 7个采集器, 统一接口collect() → List[RawCandidate] | httpx, asyncio |
| **规则预筛选** | `src/prefilter/rule_filter.py` | 关键词白/黑名单, GitHub质量检查, Benchmark特征检测 | regex, datetime |
| **LLM评分引擎** | `src/scorer/llm_scorer.py` | 全LLM统一评分 (4000+ token prompt), 50并发, Redis缓存 | openai, redis, pydantic |
| **后端专项评分** | `src/scorer/backend_scorer.py` | 后端Benchmark专项评分规则 (已被LLM统一评分取代) | 规则引擎 |
| **存储管理器** | `src/storage/storage_manager.py` | 主备切换 (飞书→SQLite), 自动回写, 去重查询 | asyncio |
| **飞书存储** | `src/storage/feishu_storage.py` | 飞书多维表格批量写入, 字段映射, 限流控制 | lark-oapi, httpx |
| **SQLite降级** | `src/storage/sqlite_fallback.py` | 本地备份, 7天TTL, 未同步记录跟踪 | sqlite3, aiosqlite |
| **飞书通知** | `src/notifier/feishu_notifier.py` | Webhook推送, 分层策略, 交互式卡片 | lark-oapi, jinja2 |
| **PDF增强器** | `src/enhancer/pdf_enhancer.py` | GROBID解析, 章节提取, 3并发控制 | httpx, asyncio |
| **常量管理** | `src/common/constants.py` | 455行常量定义 (魔法数字集中管理) | Final类型注解 |

## 核心代码深度解析

### 1. 流程编排器 (src/main.py)

**设计哲学**: 简单直接的串行编排，而非复杂的DAG调度器（不需要Airflow）。

**关键逻辑**:
```python
async def main() -> None:
    # Step 1: 数据采集 (串行执行7个采集器, 容错设计)
    collectors = [ArxivCollector(), GitHubCollector(), ...]
    for collector in collectors:
        try:
            candidates = await collector.collect()
            all_candidates.extend(candidates)
        except Exception:
            logger.error("采集器失败,继续执行")  # 单个失败不影响整体

    # Step 1.5: URL去重 (本次内部去重 + 与飞书已存URL去重)
    existing_urls = await storage.get_existing_urls()
    deduplicated = [c for c in all_candidates if c.url not in existing_urls]

    # Step 2: 规则预筛选 (过滤40-60%噪音)
    filtered = prefilter_batch(deduplicated)

    # Step 3: PDF增强 (仅arXiv论文)
    enhanced_candidates = await pdf_enhancer.enhance_batch(filtered)

    # Step 4: LLM评分 (50并发)
    async with LLMScorer() as scorer:
        scored = await scorer.score_batch(enhanced_candidates)

    # Step 5: 存储入库 (主备切换)
    await storage.save(scored)
    await storage.sync_from_sqlite()  # 自动回写未同步记录

    # Step 6: 飞书通知
    await notifier.notify(scored)
```

**为什么串行执行采集器**？
- 原因1: 避免并发请求触发API限流 (GitHub 5000 RPM, arXiv无官方限流但不建议高并发)
- 原因2: 单个采集器失败不影响其他采集器 (容错设计)
- 原因3: 采集耗时占比60% (38秒/59秒), 但优化收益有限 (并发改造复杂度高, 收益仅节省10-15秒)

**为什么不用Airflow**？
- 任务依赖简单 (串行编排, 无分支/循环)
- 每日仅运行1次 (GitHub Actions足够, 无需常驻scheduler)
- 运维成本: Airflow需要独立部署+数据库+监控, BenchScope只需GitHub Actions (免费2000分钟/月)

### 2. 数据模型 (src/models.py)

**设计原则**: 扁平化数据结构，减少嵌套解析（Linus哲学: 简化数据结构优于复杂逻辑）

**RawCandidate** (采集器输出):
```python
@dataclass(slots=True)  # slots减少内存占用40%
class RawCandidate:
    # 基础字段 (13个)
    title: str
    url: str
    source: SourceType  # Literal联合类型约束
    abstract: Optional[str] = None
    github_stars: Optional[int] = None

    # Phase 6新增: 采集器直接提取 (6个)
    paper_url: Optional[str] = None
    task_type: Optional[str] = None
    license_type: Optional[str] = None
    evaluation_metrics: Optional[List[str]] = None

    # Phase 8新增: PDF粗提取元数据 (5个)
    raw_metrics: Optional[List[str]] = None  # ["Pass@1", "BLEU-4"]
    raw_baselines: Optional[List[str]] = None  # ["GPT-4", "Claude-3.5"]
    raw_authors: Optional[str] = None
    raw_institutions: Optional[str] = None
    raw_dataset_size: Optional[str] = None

    raw_metadata: Dict[str, str] = field(default_factory=dict)  # PDF深度内容
```

**ScoredCandidate** (评分后输出):
```python
@dataclass(slots=True)
class ScoredCandidate:
    # 继承RawCandidate全部字段 (24个)
    # ...

    # 5维基础评分 (10个字段)
    activity_score: float = 0.0  # 活跃度 (权重15%)
    reproducibility_score: float = 0.0  # 可复现性 (权重30%)
    license_score: float = 0.0  # 许可合规 (权重15%)
    novelty_score: float = 0.0  # 新颖性 (权重15%)
    relevance_score: float = 0.0  # MGX适配度 (权重25%)

    # 每个维度详细推理 (≥150字符)
    activity_reasoning: str = ""
    reproducibility_reasoning: str = ""
    license_reasoning: str = ""
    novelty_reasoning: str = ""
    relevance_reasoning: str = ""

    # 后端专项评分 (4个字段, 仅后端Benchmark)
    backend_mgx_relevance: float = 0.0  # MGX相关性 (0-10)
    backend_mgx_reasoning: str = ""  # ≥200字符
    backend_engineering_value: float = 0.0  # 工程价值 (0-10)
    backend_engineering_reasoning: str = ""  # ≥200字符

    # Phase 8新增: LLM抽取字段 (6个)
    task_domain: Optional[str] = None  # 任务领域 (Coding/WebDev/Backend等)
    metrics: Optional[List[str]] = None  # 规范化指标名
    baselines: Optional[List[str]] = None  # 规范化模型名
    institution: Optional[str] = None  # 主要机构
    dataset_size: Optional[int] = None  # 数据集规模 (整数)
    dataset_size_description: Optional[str] = None  # 原始描述

    @property
    def total_score(self) -> float:
        """加权总分 = sum(score_i * weight_i)"""
        if self.custom_total_score is not None:
            return self.custom_total_score  # 后端专项可覆盖
        weights = constants.SCORE_WEIGHTS
        return (
            self.activity_score * weights["activity"] +
            self.reproducibility_score * weights["reproducibility"] +
            # ... 5维加权求和
        )

    @property
    def priority(self) -> str:
        """自动分级: ≥8.0=high, ≥6.0=medium, <6.0=low"""
        if self.total_score >= 8.0: return "high"
        if self.total_score >= 6.0: return "medium"
        return "low"
```

**为什么用dataclass而非Pydantic**？
- 性能: dataclass实例化速度比Pydantic快3-5倍 (无运行时类型校验)
- 内存: slots=True减少内存占用40% (无__dict__开销)
- 简洁: 37个字段的模型，dataclass代码量比Pydantic少30%
- 权衡: 牺牲了序列化便利性 (需手动处理JSON), 但BenchScope的模型转换在LLMScorer中集中处理，影响可控

### 3. LLM评分引擎 (src/scorer/llm_scorer.py)

**架构演进**: Phase 1-7使用规则评分 → Phase 8全面改为LLM统一评分 → Phase 9增强推理长度校验

**核心特性**:
1. **单次调用返回26个字段** (5维评分+5维推理+2维后端专项+8个结构化字段)
2. **4000+ token超详细prompt** (包含MGX场景定义、评分标准、推理要求、JSON Schema)
3. **强制字段完成** (不允许null, 不允许N/A, 字符数不足自动重试)
4. **50并发异步评分** (asyncio.Semaphore控制并发上限)
5. **Redis缓存** (7天TTL, 基于标题+URL的MD5, 命中率30%)
6. **Self-Healing机制** (推理字符不足时自动补充, 最多2次重试)

**Prompt设计** (总长度4000+ tokens):
```python
UNIFIED_SCORING_PROMPT_TEMPLATE = """
你是BenchScope的Benchmark情报分析专家...

=== 第1部分: 候选基础信息 ===
标题: {title}
摘要/README: {abstract}  # 截断到2000字符
GitHub Stars: {github_stars}
PDF深度内容: {evaluation_summary}, {dataset_summary}, {baselines_summary}
原始提取数据: {raw_metrics}, {raw_baselines}, {raw_authors}, ...

=== 第2部分: MGX场景定义 ===
P0优先级 - 核心场景 (relevance_score建议8-10分):
1. Coding: 代码生成、补全、调试、重构...
2. WebDev: Web开发、前端组件、后端API...
3. Backend: 后端性能、数据库设计、分布式系统...
...

=== 第3部分: 5维评分任务 ===
【维度1: 活跃度 activity_score】
评分标准: 10分=GitHub>5000stars, 8-9分=1000-5000stars, ...
推理要求 (≥150字符, 建议≥180字符):
- 明确说明GitHub stars、最后commit时间、contributor活跃度
- 分析PR/Issue数量、讨论质量、社区治理模式
- 解释对MGX稳定维护的影响
- 字符计数示例: "该候选项来自GitHub,拥有1200+stars...（≈180字符）"
...

=== 第4部分: 后端专项评分 ===
如果候选属于Backend场景, 必须提供:
【后端维度1: MGX相关性 backend_mgx_relevance】
推理要求 (≥200字符): 详细描述Benchmark聚焦的后端维度...
...

=== 第5部分: 结构化字段抽取 ===
task_domain: 从[Coding, WebDev, Backend, GUI, ToolUse, ...]中选择
metrics: ["Pass@1", "BLEU-4", "Accuracy", ...]
baselines: ["GPT-4", "Claude-3.5-Sonnet", ...]
...

=== 第6部分: 综合评分与推荐逻辑 ===
overall_reasoning (≥50字符): 基于5维评分给出总体推荐意见

=== 第7部分: JSON输出格式 ===
严格按照JSON Schema输出, 26个字段, 不能新增/删除/返回null

=== 第8部分: 特殊情况处理 ===
【情况1: 摘要字段被污染】处理HTML标签、Markdown语法...
【情况2: 缺少GitHub stars】说明"可能是新项目或私有仓库"...
【情况3: 非Benchmark候选】明确说明"该候选不是Benchmark"...
【情况4: 后端Benchmark识别】包含"database", "HTTP benchmark"等关键词

=== 第9部分: 质量检查清单 ===
- [ ] 所有score字段在0-10范围
- [ ] 每个reasoning字段≥150字符 (后端专项≥200字符)
- [ ] task_domain不是null, 从预定义列表选择
- [ ] JSON严格符合Schema, 可被标准解析器解析
"""
```

**并发控制实现**:
```python
async def score_batch(self, candidates: List[RawCandidate]) -> List[ScoredCandidate]:
    semaphore = asyncio.Semaphore(constants.SCORE_CONCURRENCY)  # 50并发

    async def score_with_semaphore(candidate: RawCandidate) -> ScoredCandidate:
        async with semaphore:
            return await self.score(candidate)  # 单个评分 (缓存+LLM+Self-Healing)

    tasks = [score_with_semaphore(c) for c in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if not isinstance(r, Exception)]
```

**Self-Healing机制** (Phase 9新增):
```python
async def _call_llm(self, candidate: RawCandidate) -> UnifiedBenchmarkExtraction:
    messages = [system_prompt, user_prompt]
    repair_attempt = 0

    while True:
        response = await self.client.chat.completions.create(...)
        try:
            extraction = UnifiedBenchmarkExtraction.parse_obj(payload)
            return extraction  # 校验通过, 返回结果
        except ValidationError as exc:
            violations = self._extract_length_violations(exc, payload)
            if violations and repair_attempt < 2:  # 最多重试2次
                repair_attempt += 1
                fix_prompt = self._build_length_fix_prompt(violations)
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": fix_prompt})
                logger.warning("LLM推理长度不足, 触发第%d次纠偏", repair_attempt)
                continue  # 继续循环, 重新调用LLM
            raise  # 重试耗尽或不可修复的错误
```

**为什么用gpt-4o而非gpt-4o-mini**？
- 质量: gpt-4o评分准确率比mini高15-20% (对比测试: 手工标注100条样本)
- 推理: gpt-4o生成的推理文本更详细、更有深度 (平均长度1500字符 vs 800字符)
- 成本: 规则预筛选50% + Redis缓存30% + 后端专项评分 → 实际LLM调用量降低70%, 月成本仍在¥20预算内
- 性能: 50并发优化后12秒完成41条评分, 延迟可接受

**为什么50并发**？
- Tier 2账户支持5000 RPM (Requests Per Minute), 50并发仅需750 RPM, 留有6.7倍安全余量
- 实测50并发无429限流错误, 稳定性验证通过
- 加速比: 50并发 vs 串行执行 = 12秒 vs 140秒 = 11.7倍加速

### 4. 规则预筛选 (src/prefilter/rule_filter.py)

**设计目标**: 在LLM评分前过滤掉40-60%的噪音数据, 降低LLM成本并提升候选池质量。

**预筛选规则** (4层防御):
```python
def prefilter(candidate: RawCandidate) -> bool:
    # 第1层: 基础质量检查
    if len(candidate.title) < 10 or len(candidate.abstract) < 20:
        return False  # 标题/摘要过短
    if not candidate.url.startswith(("http://", "https://")):
        return False  # URL无效

    # 第2层: 来源白名单
    valid_sources = {"arxiv", "github", "huggingface", "helm",
                     "semantic_scholar", "techempower", "dbengines"}
    if candidate.source not in valid_sources:
        return False

    # 第3层: 关键词白/黑名单
    if not _passes_keyword_rules(candidate):
        return False  # 未命中必需关键词 或 命中排除关键词

    # 第4层: GitHub专项质量检查
    if candidate.source == "github" and not _is_quality_github_repo(candidate):
        return False  # stars<50 或 README<500字 或 90天无更新

    return True
```

**GitHub专项检查** (Phase 6优化):
```python
def _is_quality_github_repo(candidate: RawCandidate) -> bool:
    # 1. Stars门槛: ≥50 (Phase 7从10提高到50, 过滤低质量项目)
    if candidate.github_stars < 50:
        return False

    # 2. 活跃度: 90天内有更新
    if (datetime.now() - candidate.publish_date).days > 90:
        return False

    # 3. README长度: ≥500字符 (说明文档完整性)
    if len(candidate.abstract) < 500:
        return False

    # 4. 排除awesome-list (Phase 6新增)
    if "awesome-" in candidate.title.lower():
        return False

    # 5. 排除资源汇总类项目
    curated_patterns = ["curated list", "collection of", "list of tools", ...]
    if any(pattern in candidate.abstract.lower() for pattern in curated_patterns):
        return False

    # 6. Benchmark特征检测 (Phase 6新增, 至少满足一项)
    benchmark_features = ["benchmark", "evaluation", "test set", "dataset",
                          "leaderboard", "baseline", "performance", "comparison", ...]
    if not any(feature in candidate.abstract.lower() for feature in benchmark_features):
        return False

    return True
```

**关键词规则** (Phase 7优化):
```python
# 权威来源豁免 (HELM/TechEmpower/DBEngines直接通过, 无需关键词检查)
TRUSTED_SOURCES = {"techempower", "dbengines", "helm"}

# 白名单 (24个关键词, 至少命中1个)
PREFILTER_REQUIRED_KEYWORDS = [
    "code", "coding", "program", "programming", "software",  # P0-编程
    "web", "browser", "gui", "ui", "automation",  # P0-Web/GUI
    "agent", "multi-agent", "tool", "api", "workflow",  # P1-Agent
    "performance", "benchmark", "framework", "database",  # Phase 7-后端
    "latency", "throughput", "optimization", "http", "server", ...
]

# 黑名单 (排除教程、资源汇总、工具包装)
PREFILTER_EXCLUDED_KEYWORDS = [
    "translation", "summarization", "sentiment analysis",  # 纯NLP
    "image classification", "computer vision", "video processing",  # 多模态
    "awesome list", "curated list", "collection of resources",  # 资源汇总
    "tutorial series", "online course", "learning guide",  # 教程
    "sdk wrapper", "api wrapper library",  # 工具包装
]
```

**为什么不用向量相似度而是关键词匹配**？
- 性能: 关键词匹配<1ms, 向量相似度需要10-50ms (Sentence-BERT编码) + 候选池规模小 (<1000条), 向量数据库ROI低
- 准确率: 关键词匹配准确率85-90% (测试100条样本), 向量相似度准确率88-92%, 提升有限
- 运维: 关键词规则可人工快速调整 (修改YAML配置), 向量模型需要重新训练+部署
- 决策: 简单方案先跑起来, 如果准确率不足再升级 (Linus哲学: 先实用后优化)

### 5. 存储管理器 (src/storage/storage_manager.py)

**设计模式**: 主备存储 + 自动降级 + 定时回写

**主备切换逻辑**:
```python
async def save(self, candidates: List[ScoredCandidate]) -> None:
    try:
        await self.feishu.save(candidates)  # 主存储: 飞书多维表格
        logger.info("✅ 飞书存储成功: %d条", len(candidates))
    except Exception as exc:
        logger.warning("⚠️ 飞书存储失败, 降级到SQLite: %s", exc)
        await self.sqlite.save(candidates)  # 降级备份: SQLite
        logger.info("✅ SQLite备份成功: %d条", len(candidates))

async def sync_from_sqlite(self) -> None:
    """将SQLite未同步记录回写到飞书 (每次运行自动执行)"""
    pending = await self.sqlite.get_unsynced()
    if pending:
        await self.feishu.save(pending)
        await self.sqlite.mark_synced([item.url for item in pending])
        logger.info("✅ 同步完成: %d条", len(pending))
```

**飞书存储** (src/storage/feishu_storage.py):
- 批量写入: 20条/请求 (飞书API限制)
- 限流控制: 0.6秒间隔 (100请求/分钟)
- 字段映射: ScoredCandidate (37字段) → 飞书表格 (22字段, 部分合并/截断)
- 去重查询: 每次运行前查询飞书已存URL集合, 避免重复推送

**SQLite降级** (src/storage/sqlite_fallback.py):
- 表结构: candidates表 (22字段 + synced_to_feishu + created_at)
- TTL清理: 7天前的已同步记录自动删除
- 未同步跟踪: synced_to_feishu=0的记录保留, 等待下次同步

**为什么飞书而非Notion**？
| 对比维度 | 飞书多维表格 | Notion Database | 决策理由 |
|---------|------------|----------------|---------|
| 国内访问 | 稳定 (国内CDN) | 不稳定 (常被墙) | 飞书胜 |
| API限额 | 100请求/分钟 | 3请求/秒 (实际更严格) | 飞书胜 |
| 批量写入 | 20条/请求 | 1条/请求 | 飞书胜 |
| 团队生态 | 统一 (MGX已用飞书) | 需切换工具 | 飞书胜 |
| 成本 | 免费版足够 | 付费版才能API集成 | 飞书胜 |

**为什么SQLite而非PostgreSQL**？
- 飞书多维表格已满足查询需求 (研究员直接操作表格)
- SQLite仅作降级备份, 不需要高并发/分布式能力
- 运维成本: SQLite零配置, PostgreSQL需要独立部署+备份+监控

### 6. 飞书通知 (src/notifier/feishu_notifier.py)

**分层推送策略**:
```python
async def notify(self, candidates: List[ScoredCandidate]) -> None:
    high = [c for c in candidates if c.priority == "high"]  # ≥8.0分
    medium = [c for c in candidates if c.priority == "medium"]  # 6.0-7.9分
    low = [c for c in candidates if c.priority == "low"]  # <6.0分

    # 推送逻辑: High全推 → Medium取Top5 → Low不推送 (避免噪音)
    to_notify = high + medium[:5]

    for candidate in to_notify:
        card = self._build_interactive_card(candidate)
        await self._send_webhook(card)
```

**交互式卡片** (Feishu Card JSON):
```json
{
  "header": {"title": "🎯 新发现Benchmark候选"},
  "elements": [
    {"tag": "div", "text": "【标题】{title}\n【来源】{source}\n【评分】{total_score}/10 ⭐️"},
    {"tag": "div", "text": "【活跃度】{activity_score}/10 - {activity_reasoning[:150]}..."},
    {"tag": "hr"},
    {"tag": "action", "actions": [
      {"tag": "button", "text": "查看详情", "url": "{url}"},
      {"tag": "button", "text": "飞书表格", "url": "飞书表格链接"}
    ]}
  ]
}
```

**为什么Webhook而非飞书机器人**？
- Webhook: 无需审批, 配置URL即可推送, 支持交互式卡片
- 机器人: 需要企业认证+应用审批, 配置复杂, 但支持双向交互
- 决策: MVP阶段Webhook足够, 未来如需"标记采纳/拒绝"功能再升级机器人

## 配置系统

### 1. 数据源配置 (config/sources.yaml)

**分层结构**:
```yaml
# ============ 论文库 ============
arxiv:
  enabled: true
  max_results: 50
  lookback_hours: 168  # 7天窗口
  keywords:  # 35个关键词 (P0-编程/Web + P1-Agent + Phase 6.5-后端)
    - code generation benchmark
    - web agent benchmark
    - backend development benchmark
    ...
  categories: [cs.SE, cs.AI, cs.CL, cs.DC, cs.DB, cs.NI]

# ============ 评测榜单 ============
helm:
  enabled: true
  allowed_scenarios: [code, coding, program, reasoning, ...]
  excluded_scenarios: [qa, question, answer, dialogue, ...]

# ============ 开源社区 ============
github:
  enabled: true
  topics: [code-generation, web-automation, backend-benchmark, ...]
  min_stars: 50
  lookback_days: 30

# ============ 后端专项数据源 ============
techempower:
  enabled: true
  base_url: "https://tfb-status.techempower.com"
  min_composite_score: 50.0

dbengines:
  enabled: true
  max_results: 50

# ============ 社交媒体 ============
twitter:
  enabled: false  # 默认禁用 (免费API仅100次/月, 需Basic套餐$100/月)
```

**修改生效**: 无需重新部署, 下次GitHub Actions运行自动生效。

### 2. 环境变量 (.env.local)

**必需变量**:
```bash
# OpenAI (LLM评分)
OPENAI_API_KEY=sk-xxx
OPENAI_MODEL=gpt-4o  # 可选, 默认gpt-4o

# 飞书 (存储+通知)
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_BITABLE_APP_TOKEN=xxx  # 多维表格Token
FEISHU_BITABLE_TABLE_ID=xxx  # 表格ID
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx

# 可选变量
REDIS_URL=redis://localhost:6379/0  # 缓存 (建议配置, 提升30%性能)
GITHUB_TOKEN=ghp_xxx  # GitHub API限流 (5000→15000/h)
```

## 部署与运维

### 1. GitHub Actions工作流

**daily_collect.yml**:
```yaml
name: Daily Benchmark Collection
on:
  schedule:
    - cron: '0 2 * * *'  # 每天UTC 2:00 (北京时间10:00)
  workflow_dispatch:  # 支持手动触发

jobs:
  collect:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python -m src.main
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          FEISHU_APP_ID: ${{ secrets.FEISHU_APP_ID }}
          # ... 其他环境变量
      - uses: actions/upload-artifact@v4
        with:
          name: logs
          path: logs/*.log
          retention-days: 7
```

**免费额度**: GitHub Actions提供2000分钟/月, BenchScope每次运行<2分钟, 每月约60次, 消耗<120分钟, 远低于额度。

### 2. 日志与监控

**日志文件**: `logs/{YYYYMMDD}.log`

**日志级别**:
- INFO: 流程关键节点 (采集完成、评分完成、存储完成)
- WARNING: 非致命错误 (单个采集器失败、Redis缓存失败、飞书限流)
- ERROR: 致命错误 (LLM评分失败、存储完全失败、JSON解析失败)

**监控指标** (记录在日志中):
```
2025-11-19 10:30:45 [INFO] 采集完成: 共68条候选
2025-11-19 10:30:46 [INFO] 去重完成: 过滤12条重复, 保留56条新发现
2025-11-19 10:30:47 [INFO] 预筛选完成: 保留32条 (过滤率42.9%)
2025-11-19 10:30:59 [INFO] 批量评分完成: 成功32条/共32条 (并发上限=50)
2025-11-19 10:31:00 [INFO] ✅ 飞书存储成功: 32条
2025-11-19 10:31:02 [INFO] 通知完成: 推送8条候选 (high=3, medium=5)
```

**日志分析工具**: `scripts/analyze_logs.py`
```bash
$ .venv/bin/python scripts/analyze_logs.py
=== 日志分析报告 ===
采集成功率: 95.2% (20/21次)
预筛选通过率: 45.3% (432/953条)
飞书消息送达率: 100% (120/120条)
候选池增长: +32条/周
```

### 3. 故障恢复

**场景1: 飞书API限流**
- 症状: 日志显示"飞书存储失败: rate limit exceeded"
- 自动降级: SQLite备份成功
- 恢复: 下次运行自动同步SQLite → 飞书

**场景2: LLM评分超时**
- 症状: 日志显示"LLM评分失败: Timeout"
- 重试机制: tenacity自动重试3次 (指数退避)
- 失败处理: 该候选跳过, 不影响其他候选

**场景3: GitHub Actions执行失败**
- 症状: Actions日志显示"Exit code 1"
- 排查: 下载Artifacts中的logs/*.log查看详细错误
- 手动补偿: 本地运行`python -m src.main`手动执行流程

## 性能优化历程

### Phase 1-6: 串行执行 (140秒瓶颈)

**问题**: LLM评分串行执行, 41条候选耗时140秒, 成为流程瓶颈。

**优化前代码**:
```python
async def score_batch(self, candidates: List[RawCandidate]) -> List[ScoredCandidate]:
    results = []
    for candidate in candidates:
        scored = await self.score(candidate)  # 串行执行, 每次3-4秒
        results.append(scored)
    return results
```

### Phase 7: 50并发优化 (12秒, 11.7倍加速)

**优化策略**:
1. **并发控制**: asyncio.Semaphore限制最大50个并发请求
2. **模型升级**: gpt-4o-mini → gpt-4o (质量优先, 成本可控)
3. **Redis缓存**: 7天TTL, 命中率30%, 减少LLM调用
4. **异常容错**: gather(..., return_exceptions=True) 确保单个失败不影响整体

**优化后代码**:
```python
async def score_batch(self, candidates: List[RawCandidate]) -> List[ScoredCandidate]:
    semaphore = asyncio.Semaphore(50)  # 50并发

    async def score_with_semaphore(candidate: RawCandidate) -> ScoredCandidate:
        async with semaphore:
            return await self.score(candidate)

    tasks = [score_with_semaphore(c) for c in candidates]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if not isinstance(r, Exception)]
```

**实测数据**:
- 41条候选: 串行140秒 → 并发12秒 (11.7倍加速)
- 完整流程: 串行184秒 → 并发59秒 (3.1倍加速)
- 错误率: 0% (无429限流错误)

### Phase 9: Self-Healing机制 (推理长度保障)

**问题**: LLM有时返回字符数不足的推理 (120字符 < 150字符要求), 导致Pydantic校验失败。

**解决方案**: 检测到字符不足时, 自动发送补充prompt要求LLM扩写, 最多重试2次。

**实测效果**:
- 触发率: 5-10% (每20条候选触发1-2次)
- 成功率: 95% (重试1次成功)
- 延迟: 第1次重试+10秒, 第2次重试+10秒
- 总体影响: 平均延迟增加0.5秒/条 (5%触发率 × 10秒延迟)

## 设计决策与权衡

### 1. 为什么不用向量数据库？

**场景**: 候选池URL去重、相似标题检测

**方案对比**:
| 方案 | 优点 | 缺点 | 决策 |
|------|-----|------|------|
| **精确匹配** (当前方案) | 实现简单, 性能极高 (<1ms) | 无法检测相似标题 | ✅ 采用 |
| **TF-IDF + 余弦相似度** | 轻量级, 无外部依赖 | 准确率一般 (75-80%) | ❌ 不采用 |
| **Sentence-BERT + FAISS** | 准确率高 (90-95%) | 需要GPU, 模型500MB, 运维复杂 | ❌ 不采用 |

**决策理由**:
- 候选池规模小 (<1000条), 精确匹配已能去重90%+
- 相似标题问题不严重 (实测: 仅2-3%的候选存在标题变体)
- 引入向量数据库的ROI低 (复杂度+10倍, 收益<5%)

### 2. 为什么不训练自定义评分模型？

**场景**: Benchmark质量评分

**方案对比**:
| 方案 | 优点 | 缺点 | 决策 |
|------|-----|------|------|
| **规则评分** (Phase 1-7) | 简单, 可解释性强 | 准确率低 (70-75%) | ❌ 已淘汰 |
| **LLM评分** (Phase 8-9, 当前方案) | 准确率高 (85-90%), 推理详细 | 成本¥20/月, 延迟12秒 | ✅ 采用 |
| **Fine-tuned模型** | 成本低 (¥2/月), 延迟快 (2秒) | 需标注1000+样本, 泛化性差 | ❌ 不采用 |

**决策理由**:
- 标注成本高 (人工标注1000条需要40小时)
- 泛化性差 (新场景/新指标需要重新标注+训练)
- LLM评分质量已满足需求 (85-90%准确率), 成本可控

### 3. 为什么GitHub Actions而非Cron/Airflow？

**场景**: 每日定时任务调度

**方案对比**:
| 方案 | 优点 | 缺点 | 决策 |
|------|-----|------|------|
| **GitHub Actions** (当前方案) | 免运维, 免费2000分钟/月 | 日志保留7天, 调试不便 | ✅ 采用 |
| **Cron + VPS** | 灵活, 日志永久保留 | 需要独立服务器, 月成本$5-10 | ❌ 不采用 |
| **Airflow** | 强大DAG调度, 监控完善 | 运维复杂, 需要数据库+Scheduler | ❌ 不采用 |

**决策理由**:
- BenchScope任务依赖简单 (串行编排, 无分支/循环)
- 每日仅运行1次, 不需要常驻scheduler
- GitHub Actions免费额度足够 (每次运行<2分钟, 月消耗<120分钟)

## 未来优化方向

### Phase 10: 性能进一步优化

**采集器并发化**:
- 当前: 7个采集器串行执行 (38秒)
- 优化: asyncio.gather并发执行 (预计15秒, 2.5倍加速)
- 风险: API限流风险增加, 需要限流控制

**LLM评分缓存预热**:
- 当前: Redis缓存命中率30%
- 优化: 定期全量评分历史候选池 (1000条), 缓存命中率提升至70%
- 收益: LLM成本降低50%, 延迟降低至5秒

### Phase 11: 数据质量提升

**多模态信息增强**:
- 当前: 仅文本数据 (标题/摘要/README)
- 优化: 增加GitHub仓库结构分析 (目录树/文件类型/代码语言分布)
- 收益: Benchmark特征检测准确率从85%提升至92%

**主动学习反馈循环**:
- 当前: 人工审核后无反馈
- 优化: 研究员标记"采纳/拒绝"后, 将标注数据回流训练规则/模型
- 收益: 评分准确率持续提升, 6个月后达到95%+

### Phase 12: 功能扩展

**交互式审核界面**:
- 当前: 飞书Webhook推送 (单向)
- 优化: 飞书机器人双向交互 (标记采纳/拒绝/待定, 添加备注)
- 收益: 审核效率提升50%, 数据质量反馈闭环

**自动化复现验证**:
- 当前: 人工验证Benchmark可复现性
- 优化: Docker + GitHub Actions自动拉取代码/数据集, 运行评估脚本
- 收益: 可复现性评分从主观判断改为客观验证

## 总结

BenchScope通过6步流水线 (采集→去重→预筛选→PDF增强→LLM评分→存储→通知), 将Benchmark发现效率提升10倍 (从人工2-3个/月 → 系统10-20个/月)。核心技术亮点:

1. **全LLM统一评分**: 单次调用返回26个字段, 推理≥1200字符, 准确率85-90%
2. **50并发优化**: LLM评分从140秒降至12秒 (11.7倍加速), 稳定运行无限流
3. **主备存储**: 飞书多维表格 + SQLite降级, 7天自动回写, 数据零丢失
4. **Self-Healing机制**: 推理长度不足自动纠偏, 成功率95%

**Linus哲学实践**:
- 简化数据结构: dataclass扁平化设计, 避免过度嵌套
- 实用主义: GitHub Actions而非Airflow, 精确匹配而非向量数据库
- 零破坏: 主备存储保障数据安全, 单个采集器失败不影响整体

**3个月目标**:
- Benchmark发现速度: 2-3个/月 → 10-20个/月 (5-10倍)
- 信息筛选效率: 阅读200篇 → 阅读20篇 (噪音过滤90%+)
- 候选池规模: 50条 → 200条 (4倍扩大)
