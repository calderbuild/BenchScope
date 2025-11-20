# Codex优化指令：Phase 2性能与数据质量优化

**任务类型**：性能优化与配置调优
**优先级**：P1（提升数据采集质量）
**预计工时**：1小时
**创建时间**：2025-11-19
**基于测试**：完整流程执行日志分析

---

## 零、测试结果诊断

### 测试执行概况

**执行时间**：2025-11-19 10:00-10:02（约2分钟）
**执行命令**：`python -m src.main`
**中断原因**：在[5/6]存储阶段请求飞书字段列表时 httpx 抛出 `The operation was canceled`，未做重试直接终止

### 数据流分析

```
[1/6] 数据采集: 184条
  ├─ ArxivCollector: 0条 ❌ (3次超时，每次10秒)
  ├─ HelmCollector: 14条 ✅
  ├─ GitHubCollector: 31条 ⚠️ (预期150+)
  ├─ HuggingFaceCollector: 43条 ✅
  ├─ TechEmpowerCollector: 46条 ✅
  └─ DBEnginesCollector: 50条 ✅

[1.5/6] URL去重: 184 → 81条新发现
  ├─ 内部去重: 54条
  └─ 飞书去重: 49条

[2/6] 规则预筛选: 81 → 4条 ❌ (过滤率95.1%)
  ├─ 问题：TechEmpower/DBEngines大量被过滤
  └─ 原因：必需关键词规则太严

[3/6] PDF增强: 4条 ✅

[4/6] LLM评分: 4条全部成功 ✅
  └─ 自愈机制触发2次（推理长度不足）

[5/6] 存储入库: 飞书字段API请求被取消 → 流程中止 ❌
```

---

## 一、四大核心问题

### 🔴 问题1：arXiv采集器持续超时（高优先级）

**现象**：
```
10:00:51 - 第1次尝试开始
10:01:01 - 超时警告（10秒后）
10:01:02 - 第2次尝试开始
10:01:12 - 超时警告（10秒后）
10:01:14 - 第3次尝试开始
10:01:24 - 超时警告（10秒后）
10:01:27 - 返回空列表（连续失败）
```

**根本原因**：
1. **查询复杂度高**：22个关键词用OR连接，生成超长URL
2. **arXiv API响应慢**：白天高峰期，复杂查询处理时间>10秒
3. **超时配置过短**：当前10秒不足以处理复杂查询

**影响**：
- 损失arXiv论文候选（通常10-20条/天）
- 浪费~40秒（3次重试 × 10秒 + 等待时间）

**数据支持**：
```python
# 当前配置 (config/sources.yaml)
arxiv:
  timeout_seconds: 10     # ← 不足
  max_retries: 3          # ← 浪费时间
  keywords: [22个关键词]  # ← 查询复杂
```

---

### 🟡 问题2：预筛选过滤率过高（中优先级）

**现象**：
```
[2/6] 规则预筛选: 81条 → 4条 (过滤率95.1%)
```

**数据流追踪**：
```
来源分布 (81条新发现):
- TechEmpower: ~30条 (46条 - 重复)
- DBEngines: ~25条 (50条 - 重复)
- GitHub: ~20条 (31条 - 重复)
- HuggingFace: ~6条 (43条 - 重复)

预筛选结果:
- 保留: 4条
- 过滤: 77条 (95.1%)
  └─ 主要来源: TechEmpower/DBEngines
```

**根本原因**：

**规则层级**（`src/prefilter/rule_filter.py`）：
1. ✅ 基础过滤：标题长度、摘要长度、URL有效性
2. ✅ GitHub质量：stars≥50, 90天更新, README≥500字
3. ❌ **关键词过滤**（主要问题）：
   ```python
   # constants.py:286-308
   PREFILTER_REQUIRED_KEYWORDS = [
       "code", "coding", "program", "programming", "software",
       "web", "browser", "gui", "agent", "api", ...
   ]
   ```

   **问题**：TechEmpower/DBEngines候选项包含：
   - "FastAPI", "Gin", "Express" → ❌ 无code/programming关键词
   - "PostgreSQL", "MySQL", "Redis" → ❌ 无code/programming关键词
   - "framework", "database", "performance" → ❌ 不在必需关键词列表

4. ❌ **Benchmark特征检测**（次要问题）：
   ```python
   # rule_filter.py:114-129
   benchmark_features = [
       "benchmark", "evaluation", "test set",
       "dataset", "leaderboard", "baseline"
   ]
   ```

   **问题**：TechEmpower描述示例：
   - "FastAPI is a modern, fast web framework" → ❌ 无benchmark关键词
   - "Gin is a HTTP web framework" → ❌ 无benchmark关键词

**影响**：
- **数据损失严重**：77条候选被过滤（其中~55条是高质量后端Benchmark）
- **偏离核心目标**：TechEmpower/DBEngines是**后端性能Benchmark的权威来源**
- **ROI低下**：采集184条 → 只保留4条（2.2%利用率）

---

### 🟢 问题3：GitHub采集数量偏低（低优先级）

**现象**：
```
GitHubCollector: 31条 (预期150+)
```

**实际分析**（日志证据）：
```
30个topics并发搜索：
- 大部分topics返回0-2个仓库
- 只有少数topics返回5个仓库（最大per_page）
- 总计31条采集成功
```

**根本原因**：
1. **搜索条件严格**：
   ```
   pushed:>=2025-10-20 (30天内更新)
   stars排序 + per_page=5 (只取前5个)
   ```

2. **topics过于具体**：
   - "coding-challenge+benchmark" → 很少仓库同时包含
   - "selenium-testing+benchmark" → 小众组合
   - "graphql+benchmark" → 新兴技术，仓库少

3. **Benchmark项目特点**：
   - 更新频率低（大多数>30天才更新一次）
   - stars增长慢（很多优质项目<50 stars）

**影响评估**：
- ✅ **质量优于数量**：31条都是高质量仓库
- ✅ **未触发限流**：GITHUB_TOKEN生效，无403/429错误
- ⚠️ **覆盖面有限**：可能错过一些新兴Benchmark

### 🔴 问题4：飞书字段查询被取消（高优先级）

**现象**：
```
[5/6] 存储入库...
2025-11-19 10:02:11,192 [INFO] httpx: GET .../tables/***/fields?page_size=500
Error: The operation was canceled.
```

**根本原因**：
1. `src/storage/feishu_storage.py::_ensure_field_cache` 使用 `httpx.AsyncClient(timeout=10)` 直接调用 `client.get()`，没有任何 retry/backoff。
2. 飞书开放平台偶尔会把长时间请求直接断开（httpcore抛出 `ReadTimeout` / `Cancelled`），未捕获异常会冒泡到 `StorageManager.save()`，导致SQLite降级也无法执行。
3. `_field_names` 缓存是写入前的硬依赖，只要第一次请求失败整条流程就终止。

**影响**：
- 🛑 当天所有评分结果无法写入飞书，也不会进入SQLite备份。
- 🔁 下一次运行需要重新跑完采集/评分，浪费成本。
- ⚠️ 如果持续失败，GitHub Actions 会保持红灯。

---

## 二、优化方案设计

### 方案概览

| 问题 | 优先级 | 优化策略 | 预期效果 |
|------|--------|---------|---------|
| arXiv超时 | P0 | 增加timeout + 减少重试 | 采集成功率0% → 80% |
| 预筛选过严 | P1 | 放宽关键词 + 来源豁免 | 保留率2.2% → 30% |
| GitHub采集少 | P2 | 扩大时间窗口（可选） | 31条 → 50+条 |

---

### 优化1：arXiv超时问题解决

#### 策略A：增加超时时间（推荐）

**修改文件**：`config/sources.yaml`

**当前配置**：
```yaml
arxiv:
  timeout_seconds: 10
  max_retries: 3
```

**优化后配置**：
```yaml
arxiv:
  timeout_seconds: 20    # 增加到20秒（应对复杂查询）
  max_retries: 2         # 减少到2次（避免浪费时间）
```

**理由**：
- ✅ 20秒足够处理22个关键词的复杂查询
- ✅ 2次重试平衡成功率与耗时（10秒 + 20秒 + 20秒 = 50秒）
- ✅ 配置修改，零代码变更

**预期效果**：
- arXiv采集成功率：0% → 80%+
- 新增候选：10-20条/天
- 总耗时：40秒 → 50秒（可接受）

---

#### 策略B：简化查询复杂度（可选）

**修改文件**：`config/sources.yaml`

**当前配置**：
```yaml
arxiv:
  keywords: [22个关键词]  # 生成超长URL
```

**优化方案**：拆分为核心关键词（减少URL长度）
```yaml
arxiv:
  keywords:
    # P0 - 核心关键词（保留10个）
    - code generation benchmark
    - programming benchmark
    - software engineering benchmark
    - web agent benchmark
    - browser automation benchmark
    - GUI automation benchmark
    - multi-agent benchmark
    - agent collaboration evaluation
    - backend development benchmark
    - database query benchmark

    # P1 - 次要关键词（暂时注释）
    # - code evaluation
    # - code completion benchmark
    # - web navigation evaluation
    # - tool use benchmark
    # ...
```

**理由**：
- ✅ 减少URL长度，降低API处理时间
- ✅ 保留核心关键词，覆盖主要场景
- ⚠️ 可能遗漏部分长尾论文

**建议**：
- 先执行策略A（增加timeout）
- 如果仍然超时，再考虑策略B

---

### 优化2：预筛选过滤率问题解决

#### 核心思路

**不是放宽所有规则**，而是**针对不同来源采用差异化策略**：

```
来源分类:
├─ 学术来源 (arXiv, Semantic Scholar)
│   └─ 保持严格规则（必需关键词 + Benchmark特征）
│
├─ 开源社区 (GitHub, HuggingFace)
│   └─ 保持严格规则（必需关键词 + Benchmark特征）
│
└─ 权威性能数据源 (TechEmpower, DBEngines, HELM) ← 新增
    └─ 豁免关键词规则（信任官方筛选）
```

---

#### 实施步骤

**Step 1：扩展必需关键词列表**

**修改文件**：`src/common/constants.py`

**当前配置**：
```python
PREFILTER_REQUIRED_KEYWORDS: Final[list[str]] = [
    # P0 - 编程
    "code", "coding", "program", "programming", "software", "repository",
    # P0 - Web/GUI
    "web", "browser", "gui", "automation",
    # P0 - Agent
    "agent", "multi-agent", "llm",
    # P1 - API/后端
    "api", "backend", "microservice",
]
```

**优化后配置**：
```python
PREFILTER_REQUIRED_KEYWORDS: Final[list[str]] = [
    # P0 - 编程
    "code", "coding", "program", "programming", "software", "repository",

    # P0 - Web/GUI
    "web", "browser", "gui", "automation",

    # P0 - Agent
    "agent", "multi-agent", "llm",

    # P1 - API/后端
    "api", "backend", "microservice",

    # P1 - 性能与Benchmark（新增）
    "performance",
    "benchmark",
    "framework",
    "database",
    "latency",
    "throughput",
    "optimization",

    # P1 - 后端技术栈（新增）
    "http",
    "server",
    "service",
    "endpoint",
    "query",
    "storage",
]
```

**效果**：
- ✅ TechEmpower候选：FastAPI/Gin/Express → 包含"framework"/"http"/"performance"
- ✅ DBEngines候选：PostgreSQL/MySQL → 包含"database"/"query"/"performance"

---

**Step 2：为权威数据源添加豁免机制**

**修改文件**：`src/prefilter/rule_filter.py`

**当前代码**（line 134-147）：
```python
def _passes_keyword_rules(candidate: RawCandidate) -> bool:
    """基于Phase7白/黑名单的关键词过滤"""

    text = f"{candidate.title} {(candidate.abstract or '')}".lower()

    if any(excluded in text for excluded in constants.PREFILTER_EXCLUDED_KEYWORDS):
        logger.debug("过滤: 命中排除关键词 - %s", candidate.title)
        return False

    if not any(required in text for required in constants.PREFILTER_REQUIRED_KEYWORDS):
        logger.debug("过滤: 未命中必需关键词 - %s", candidate.title)
        return False

    return True
```

**优化后代码**：
```python
def _passes_keyword_rules(candidate: RawCandidate) -> bool:
    """基于Phase7白/黑名单的关键词过滤

    权威数据源豁免机制：
    - TechEmpower: Web框架性能权威Benchmark，信任其筛选
    - DBEngines: 数据库排名权威来源，信任其筛选
    - HELM: 斯坦福LLM评测权威Benchmark，信任其筛选
    """

    # 权威数据源豁免关键词规则（来源本身已经过筛选）
    TRUSTED_SOURCES = {"techempower", "dbengines", "helm"}
    if candidate.source in TRUSTED_SOURCES:
        logger.debug("权威来源豁免关键词检查: %s (%s)", candidate.title, candidate.source)
        return True

    text = f"{candidate.title} {(candidate.abstract or '')}".lower()

    if any(excluded in text for excluded in constants.PREFILTER_EXCLUDED_KEYWORDS):
        logger.debug("过滤: 命中排除关键词 - %s", candidate.title)
        return False

    if not any(required in text for required in constants.PREFILTER_REQUIRED_KEYWORDS):
        logger.debug("过滤: 未命中必需关键词 - %s", candidate.title)
        return False

    return True
```

**关键改动**：
- ✅ 新增`TRUSTED_SOURCES`常量
- ✅ 权威来源直接返回True，跳过关键词检查
- ✅ 保留其他来源的严格规则

---

### Step 3：飞书存储稳定性修复

飞书写入阶段一旦查询字段失败，整条流水线就会终止。因此需要在`src/common/constants.py`与`src/storage/feishu_storage.py`内加入超时/重试保护。

#### Step 3.1：新增飞书HTTP常量

**文件**：`src/common/constants.py`

```python
FEISHU_HTTP_TIMEOUT_SECONDS: Final[int] = 15
FEISHU_HTTP_MAX_RETRIES: Final[int] = 3
FEISHU_HTTP_RETRY_DELAY_SECONDS: Final[float] = 1.5
```

> 说明：15秒覆盖飞书偶发慢响应；1.5秒递增回退可以在最坏 1+1.5+3 ≈ 5 秒内完成三次重试。

#### Step 3.2：封装 `_request_with_retry`

**文件**：`src/storage/feishu_storage.py`

```python
import random

class FeishuStorage:
    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        timeout = kwargs.pop(
            "timeout",
            constants.FEISHU_HTTP_TIMEOUT_SECONDS,
        )

        backoff = constants.FEISHU_HTTP_RETRY_DELAY_SECONDS
        last_error: Exception | None = None

        for attempt in range(1, constants.FEISHU_HTTP_MAX_RETRIES + 1):
            try:
                return await client.request(
                    method,
                    url,
                    timeout=timeout,
                    **kwargs,
                )
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                last_error = exc
                logger.warning(
                    "飞书请求失败(%s %s) - 第%d次重试: %s",
                    method,
                    url,
                    attempt,
                    exc,
                )
                if attempt == constants.FEISHU_HTTP_MAX_RETRIES:
                    break
                await asyncio.sleep(backoff)
                backoff *= 1.8  # 轻量指数退避

        raise FeishuAPIError("飞书请求重试仍失败") from last_error
```

> 关键点：
> - 捕获所有`httpx.RequestError`（包含`ReadTimeout`/`Cancelled`）。
> - 失败日志包含HTTP方法与URL，便于溯源。
> - 最终抛出`FeishuAPIError`，上层`StorageManager`会自动降级到SQLite。

#### Step 3.3：接入所有飞书API调用

1. `_ensure_field_cache()`：将 `resp = await client.get(...)` 替换为 `resp = await self._request_with_retry(client, "GET", url, headers=headers, params=params)`；若仍失败，记录`logger.error`并抛`FeishuAPIError`。
2. `_batch_create_records()`：用 `_request_with_retry` 发送 `POST`，避免 `client.post` 直接抛异常。
3. `get_existing_urls()`：分页 `records/search` 也改为 `_request_with_retry`，确保查询去重数据时可自动重试。
4. `_ensure_access_token()`：刷新token使用 `_request_with_retry(..., method="POST")`，防止偶发 5xx 导致 token 缺失。

完成后，飞书阶段即使遇到短暂网络抖动也不会中止，最多退避后降级到SQLite。

---

### Step 4：放宽GitHub Benchmark特征检测

**修改文件**：`src/prefilter/rule_filter.py`

**当前代码**（line 114-131）：
```python
# Benchmark特征检测（至少满足一项）
benchmark_features = [
    "benchmark",
    "evaluation",
    "test set",
    "dataset",
    "leaderboard",
    "baseline",
]
has_benchmark_feature = any(
    feature in readme_lower for feature in benchmark_features
)

if not has_benchmark_feature:
    logger.debug("缺少Benchmark特征: %s", candidate.title)
    return False

return True
```

**优化后代码**：
```python
# Benchmark特征检测（至少满足一项）
# Phase 2优化: 扩展特征关键词，涵盖性能测试、对比分析等场景
benchmark_features = [
    "benchmark",
    "evaluation",
    "test set",
    "dataset",
    "leaderboard",
    "baseline",
    # 新增: 性能相关
    "performance",
    "comparison",
    "vs",
    "versus",
    # 新增: 测试相关
    "testing",
    "test suite",
    "test framework",
    # 新增: 排名相关
    "ranking",
    "rating",
    "score",
]
has_benchmark_feature = any(
    feature in readme_lower for feature in benchmark_features
)

if not has_benchmark_feature:
    logger.debug("缺少Benchmark特征: %s", candidate.title)
    return False

return True
```

**关键改动**：
- ✅ 新增"performance", "comparison", "vs" → 覆盖TechEmpower类Benchmark
- ✅ 新增"testing", "ranking" → 覆盖更多测试/对比场景
- ✅ 保持必须满足至少一项的底线

---

**Step 4：更新预筛选逻辑调用顺序**

**修改文件**：`src/prefilter/rule_filter.py`

**当前代码**（line 15-50）：
```python
def prefilter(candidate: RawCandidate) -> bool:
    """Phase 3 基线预筛选规则"""

    # 基础过滤
    if not candidate.title or len(candidate.title.strip()) < ...:
        return False

    # ...省略其他基础检查...

    # 关键词过滤
    if not _passes_keyword_rules(candidate):
        return False

    # GitHub质量过滤
    if candidate.source == "github" and not _is_quality_github_repo(candidate):
        return False

    return True
```

**优化后代码**（调整顺序 + 添加日志）：
```python
def prefilter(candidate: RawCandidate) -> bool:
    """Phase 2优化版预筛选规则

    优化点:
    1. 权威数据源优先豁免（减少不必要的检查）
    2. 调整过滤顺序（先快速检查，后复杂检查）
    3. 增加调试日志（便于分析过滤路径）
    """

    # 基础过滤（必须通过）
    if not candidate.title or len(candidate.title.strip()) < constants.PREFILTER_MIN_TITLE_LENGTH:
        logger.debug("过滤: 标题过短 - %s", candidate.title)
        return False

    # 摘要长度要求：HuggingFace/HELM/Semantic Scholar来源豁免
    if candidate.source not in {"helm", "semantic_scholar", "huggingface"}:
        if not candidate.abstract or len(candidate.abstract.strip()) < constants.PREFILTER_MIN_ABSTRACT_LENGTH:
            logger.debug("过滤: 摘要过短 - %s", candidate.title)
            return False

    if not candidate.url or not candidate.url.startswith(("http://", "https://")):
        logger.debug("过滤: URL无效 - %s", candidate.url)
        return False

    # 来源白名单（新增: techempower, dbengines）
    valid_sources = {
        "arxiv", "github", "huggingface", "helm",
        "semantic_scholar", "techempower", "dbengines"
    }
    if candidate.source not in valid_sources:
        logger.debug("过滤: 来源不在白名单 - %s", candidate.source)
        return False

    # 关键词过滤（权威来源豁免）
    if not _passes_keyword_rules(candidate):
        return False

    # GitHub特定质量过滤
    if candidate.source == "github" and not _is_quality_github_repo(candidate):
        return False

    logger.debug("✅ 通过预筛选: %s (%s)",
                 candidate.title[:50], candidate.source)
    return True
```

**关键改动**：
- ✅ `valid_sources`新增"techempower", "dbengines"
- ✅ 增加通过日志（便于验证豁免机制）
- ✅ 调整注释，说明优化逻辑

---

#### 预期效果

**优化前**：
```
81条新发现
  ├─ TechEmpower: ~30条 → 过滤29条 → 保留1条
  ├─ DBEngines: ~25条 → 过滤25条 → 保留0条
  ├─ GitHub: ~20条 → 过滤18条 → 保留2条
  └─ HuggingFace: ~6条 → 过滤5条 → 保留1条
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
总计: 过滤77条 (95.1%) → 保留4条 (4.9%)
```

**优化后**：
```
81条新发现
  ├─ TechEmpower: ~30条 → 豁免 → 保留30条 ✅
  ├─ DBEngines: ~25条 → 豁免 → 保留25条 ✅
  ├─ GitHub: ~20条 → 过滤13条 → 保留7条 ⬆️
  └─ HuggingFace: ~6条 → 过滤3条 → 保留3条 ⬆️
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
总计: 过滤16条 (19.8%) → 保留65条 (80.2%)
```

**关键指标改善**：
- 保留率：4.9% → 80.2%（**16倍提升**）
- 保留数量：4条 → 65条（**16倍提升**）
- TechEmpower利用率：3.3% → 100%（**30倍提升**）
- DBEngines利用率：0% → 100%（**无穷倍提升**）

---

### 优化3：GitHub采集数量提升（可选）

#### 策略：扩大时间窗口

**修改文件**：`config/sources.yaml`

**当前配置**：
```yaml
github:
  lookback_days: 30  # 30天窗口
```

**优化后配置**（可选）：
```yaml
github:
  lookback_days: 90  # 扩大到90天
```

**理由**：
- Benchmark项目更新频率低
- 很多优质项目3个月才更新一次
- 扩大窗口可以捕获更多候选

**预期效果**：
- GitHub采集：31条 → 50-80条
- 但可能增加旧项目比例

**建议**：
- **保持30天窗口**（优先新鲜度）
- 如果确实需要更多候选，再调整到90天

---

## 三、实施计划

### 执行顺序

```
Step 1: arXiv超时修复（最高优先级）
  ├─ 修改 config/sources.yaml
  └─ 测试验证

Step 2: 预筛选规则优化（高优先级）
  ├─ 修改 src/common/constants.py（扩展关键词）
  ├─ 修改 src/prefilter/rule_filter.py（豁免机制）
  └─ 测试验证

Step 3: 飞书存储稳定性修复（高优先级）
  ├─ 新增飞书HTTP常量
  ├─ 封装重试助手并接入所有飞书API调用
  └─ 重新跑一次主流程验证写入成功

Step 4: GitHub时间窗口调整（可选）
  ├─ 修改 config/sources.yaml
  └─ 测试验证
```

---

### Step 1：arXiv超时修复

**修改文件**：`config/sources.yaml`

**完整修改**：
```yaml
arxiv:
  enabled: true
  max_results: 50
  lookback_hours: 168  # 7天窗口
  timeout_seconds: 20  # 从10秒增加到20秒
  max_retries: 2       # 从3次减少到2次

  # Phase 7: 聚焦MGX核心场景关键词
  keywords:
    # ... 保持不变 ...
```

**测试验证**：
```bash
# 单独测试arXiv采集
cd /mnt/d/VibeCoding_pgm/BenchScope
.venv/bin/python -c "
import asyncio
from src.collectors import ArxivCollector

async def test():
    collector = ArxivCollector()
    candidates = await collector.collect()
    print(f'✅ 采集成功: {len(candidates)}条')

asyncio.run(test())
"
```

**成功标准**：
- ✅ 采集数量≥10条
- ✅ 无超时错误
- ✅ 耗时<60秒

---

### Step 2.1：扩展必需关键词

**修改文件**：`src/common/constants.py`

**定位行号**：约line 286-308

**修改内容**：
```python
PREFILTER_REQUIRED_KEYWORDS: Final[list[str]] = [
    # P0 - 编程
    "code",
    "coding",
    "program",
    "programming",
    "software",
    "repository",

    # P0 - Web/GUI
    "web",
    "browser",
    "gui",
    "automation",

    # P0 - Agent
    "agent",
    "multi-agent",
    "llm",

    # P1 - API/后端
    "api",
    "backend",
    "microservice",

    # Phase 2新增: 性能与Benchmark
    "performance",
    "benchmark",
    "framework",
    "database",
    "latency",
    "throughput",
    "optimization",

    # Phase 2新增: 后端技术栈
    "http",
    "server",
    "service",
    "endpoint",
    "query",
    "storage",
]
```

---

### Step 2.2：添加权威来源豁免

**修改文件**：`src/prefilter/rule_filter.py`

**定位函数**：`_passes_keyword_rules` (约line 134)

**完整新代码**：
```python
def _passes_keyword_rules(candidate: RawCandidate) -> bool:
    """基于Phase7白/黑名单的关键词过滤

    Phase 2优化: 权威数据源豁免机制
    - TechEmpower: Web框架性能权威Benchmark，信任其官方筛选
    - DBEngines: 数据库排名权威来源，信任其官方筛选
    - HELM: 斯坦福LLM评测权威Benchmark，信任其官方筛选

    理由: 这些来源本身就是高质量Benchmark的集合，无需重复过滤
    """

    # 权威数据源豁免关键词规则
    TRUSTED_SOURCES = {"techempower", "dbengines", "helm"}
    if candidate.source in TRUSTED_SOURCES:
        logger.debug("✅ 权威来源豁免关键词检查: %s (%s)",
                     candidate.title[:50], candidate.source)
        return True

    # 非权威来源：执行严格关键词检查
    text = f"{candidate.title} {(candidate.abstract or '')}".lower()

    # 排除关键词检查
    if any(excluded in text for excluded in constants.PREFILTER_EXCLUDED_KEYWORDS):
        logger.debug("❌ 过滤: 命中排除关键词 - %s", candidate.title[:50])
        return False

    # 必需关键词检查
    if not any(required in text for required in constants.PREFILTER_REQUIRED_KEYWORDS):
        logger.debug("❌ 过滤: 未命中必需关键词 - %s", candidate.title[:50])
        return False

    return True
```

---

### Step 2.3：扩展Benchmark特征关键词

**修改文件**：`src/prefilter/rule_filter.py`

**定位代码**：`_is_quality_github_repo` 函数中的 `benchmark_features` (约line 114)

**修改内容**：
```python
# Benchmark特征检测（至少满足一项）
# Phase 2优化: 扩展特征关键词，涵盖性能测试、对比分析等场景
benchmark_features = [
    # 原有关键词
    "benchmark",
    "evaluation",
    "test set",
    "dataset",
    "leaderboard",
    "baseline",

    # Phase 2新增: 性能相关
    "performance",
    "comparison",
    "vs",
    "versus",

    # Phase 2新增: 测试相关
    "testing",
    "test suite",
    "test framework",

    # Phase 2新增: 排名相关
    "ranking",
    "rating",
    "score",
]
```

---

### Step 2.4：更新来源白名单

**修改文件**：`src/prefilter/rule_filter.py`

**定位代码**：`prefilter` 函数中的 `valid_sources` (约line 38)

**修改内容**：
```python
# 来源白名单（Phase 2新增: techempower, dbengines）
valid_sources = {
    "arxiv",
    "github",
    "huggingface",
    "helm",
    "semantic_scholar",
    "techempower",  # Phase 2新增
    "dbengines",    # Phase 2新增
}
```

---

### Step 2.5：增强调试日志

**修改文件**：`src/prefilter/rule_filter.py`

**定位代码**：`prefilter` 函数的返回语句 (约line 49)

**修改内容**：
```python
# 修改前
logger.debug("通过: %s", candidate.title[: constants.TITLE_TRUNCATE_SHORT])

# 修改后（更详细的日志）
logger.debug("✅ 通过预筛选: %s (%s来源, stars=%s)",
             candidate.title[:50],
             candidate.source,
             candidate.github_stars or "N/A")
```

---

### Step 4：GitHub时间窗口调整（可选）

**修改文件**：`config/sources.yaml`

**当前配置**：
```yaml
github:
  lookback_days: 30
```

**可选修改**：
```yaml
github:
  lookback_days: 90  # 扩大到90天（可选）
```

**建议**：
- **先不修改**，执行Step 1-2后测试效果
- 如果采集数量仍不足，再考虑扩大窗口

---

## 四、测试验证

### 测试1：arXiv采集验证

```bash
cd /mnt/d/VibeCoding_pgm/BenchScope

# 单独测试arXiv（验证超时修复）
.venv/bin/python -c "
import asyncio
from src.collectors import ArxivCollector

async def test():
    print('测试arXiv采集（timeout=20s, retries=2）...')
    collector = ArxivCollector()
    candidates = await collector.collect()
    print(f'✅ 采集成功: {len(candidates)}条')
    if candidates:
        print(f'示例: {candidates[0].title}')

asyncio.run(test())
"
```

**成功标准**：
- ✅ 采集数量≥10条
- ✅ 无连续超时错误
- ✅ 耗时<60秒

---

### 测试2：预筛选规则验证

```bash
cd /mnt/d/VibeCoding_pgm/BenchScope

# 完整流程测试（验证预筛选改善）
.venv/bin/python -m src.main
```

**关键指标对比**：

| 指标 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 采集总数 | 184条 | ~200条 | +8.7% |
| arXiv成功率 | 0% | 80%+ | +80%pt |
| 预筛选保留 | 4条 (4.9%) | 65条 (80%) | +16倍 |
| TechEmpower利用 | 1条 (3%) | 30条 (100%) | +30倍 |
| DBEngines利用 | 0条 (0%) | 25条 (100%) | +∞ |

**成功标准**：
- ✅ arXiv采集≥10条
- ✅ 预筛选保留率≥60%
- ✅ TechEmpower/DBEngines基本全部保留
- ✅ LLM评分成功率100%

---

### 测试3：飞书写入重试验证

```bash
cd /mnt/d/VibeCoding_pgm/BenchScope

# 运行主流程，重点观察[5/6]日志
.venv/bin/python -m src.main
```

**检查要点**：
- 日志中应出现 `飞书字段分页...` → 若出现短暂失败，也应该看到 `第X次重试`，最终继续执行。
- 若飞书API仍然不可用，`StorageManager` 会记录 `FeishuAPIError` 并自动进入SQLite降级；不可再出现 `The operation was canceled` 后直接退出的情况。

---

### 测试4：日志分析

```bash
# 查看最新日志
cd /mnt/d/VibeCoding_pgm/BenchScope
tail -100 logs/$(ls -t logs/ | head -n1)

# 搜索关键日志
grep "权威来源豁免" logs/$(ls -t logs/ | head -n1)
grep "预筛选完成" logs/$(ls -t logs/ | head -n1)
grep "✅ 通过预筛选" logs/$(ls -t logs/ | head -n1)
```

**验证点**：
- ✅ 看到"权威来源豁免"日志（TechEmpower/DBEngines）
- ✅ 预筛选保留率显著提升
- ✅ 无异常ERROR日志

---

## 五、成功标准

### 5.1 功能完整性

- [ ] ✅ arXiv采集成功（≥10条）
- [ ] ✅ 所有collectors正常工作
- [ ] ✅ 预筛选保留率≥60%
- [ ] ✅ TechEmpower/DBEngines全部保留
- [ ] ✅ LLM评分成功率100%
- [ ] ✅ 飞书存储正常写入

### 5.2 性能指标

- [ ] ✅ arXiv采集耗时<60秒（vs 原40秒空跑）
- [ ] ✅ 完整流程耗时<120秒
- [ ] ✅ 预筛选保留数量：4条 → 65条（+16倍）
- [ ] ✅ 数据利用率：2.2% → 80%+（+36倍）

### 5.3 代码质量

- [ ] ✅ PEP8规范通过（ruff check）
- [ ] ✅ 关键逻辑有中文注释
- [ ] ✅ 函数嵌套≤3层
- [ ] ✅ 日志清晰易读

---

## 六、风险管理

### 6.1 风险识别

**风险1：arXiv超时仍未解决**
- **概率**：低（20秒应该足够）
- **影响**：中（仍然损失arXiv候选）
- **缓解措施**：如果仍超时，执行策略B（简化查询）

**风险2：预筛选保留过多低质量候选**
- **概率**：低（权威来源质量有保证）
- **影响**：中（LLM评分成本增加）
- **缓解措施**：观察1周数据，如有问题调整豁免规则

**风险3：GitHub时间窗口扩大后旧项目过多**
- **概率**：中（如果执行Step 4）
- **影响**：低（旧项目可能仍有价值）
- **缓解措施**：LLM评分会自然过滤低质量候选

### 6.2 回滚计划

**如果优化后出现严重问题**：

```bash
# 方案A: Git revert
cd /mnt/d/VibeCoding_pgm/BenchScope
git revert <commit-hash>
git push origin main

# 方案B: 手动回滚配置
# 1. config/sources.yaml
#    arxiv.timeout_seconds: 20 → 10
#    arxiv.max_retries: 2 → 3
#
# 2. src/common/constants.py
#    删除新增的关键词
#
# 3. src/prefilter/rule_filter.py
#    删除权威来源豁免逻辑
```

**回滚标准**：
- 预筛选保留率>95%（过度放宽）
- LLM评分失败率>10%
- 飞书存储失败率>5%

---

## 七、后续优化方向

### 7.1 短期优化（1-2周）

**优化1：arXiv关键词智能分组**
- 当前：22个关键词串行查询
- 优化：拆分为3-4组并发查询，避免超长URL
- 预期：查询时间从20秒降到10秒

**优化2：预筛选规则动态调整**
- 当前：固定规则
- 优化：基于历史数据（保留率、LLM评分分布）动态调整阈值
- 预期：保留率稳定在70-80%

**优化3：LLM评分成本优化**
- 当前：全量评分
- 优化：规则预评分（基础指标快速打分） + LLM精评（仅评分>5分的候选）
- 预期：LLM调用减少50%，成本降低50%

### 7.2 中期优化（1-2月）

**优化1：新增采集器**
- Kaggle Datasets（数据集Benchmark）
- BenchmarkML（ML Benchmark集合）
- OpenBenchmark（开源Benchmark社区）

**优化2：智能去重优化**
- 当前：基于URL精确匹配
- 优化：基于标题/摘要相似度去重（处理同一Benchmark的不同来源）
- 预期：去重准确率提升20%

**优化3：飞书通知增强**
- 当前：分层推送（High/Medium/Low）
- 优化：添加交互按钮（✅采纳 / ❌拒绝 / 🔖待评估）
- 预期：减少人工操作飞书表格

---

## 八、附录

### A. 文件清单

**修改文件**：
- `config/sources.yaml` (arXiv超时配置)
- `src/common/constants.py` (扩展必需关键词)
- `src/prefilter/rule_filter.py` (权威来源豁免 + Benchmark特征扩展)
- `src/storage/feishu_storage.py` (飞书HTTP重试 + 超时保护)

**新建文件**：
- 无

**测试文件**：
- 运行 `python -m src.main` 验证完整流程

### B. 配置对比

**config/sources.yaml**:
```diff
arxiv:
- timeout_seconds: 10
+ timeout_seconds: 20
- max_retries: 3
+ max_retries: 2
```

**src/common/constants.py**:
```diff
+FEISHU_HTTP_TIMEOUT_SECONDS: Final[int] = 15
+FEISHU_HTTP_MAX_RETRIES: Final[int] = 3
+FEISHU_HTTP_RETRY_DELAY_SECONDS: Final[float] = 1.5

PREFILTER_REQUIRED_KEYWORDS = [
  "code", "coding", "program", ...,
+ "performance", "benchmark", "framework",
+ "database", "latency", "throughput",
+ "http", "server", "service", "query",
]
```

**src/prefilter/rule_filter.py**:
```diff
def _passes_keyword_rules(candidate: RawCandidate) -> bool:
+   TRUSTED_SOURCES = {"techempower", "dbengines", "helm"}
+   if candidate.source in TRUSTED_SOURCES:
+       return True

    text = f"{candidate.title} ...".lower()
    # ... 原有逻辑 ...
```

**src/storage/feishu_storage.py**:
```diff
+    async def _request_with_retry(...):
+        for attempt in range(1, constants.FEISHU_HTTP_MAX_RETRIES + 1):
+            try:
+                return await client.request(...)
+            except (httpx.RequestError, httpx.TimeoutException) as exc:
+                logger.warning(...)
+                await asyncio.sleep(backoff)
+        raise FeishuAPIError("飞书请求重试仍失败")

-        resp = await client.get(url, headers=headers, params=params)
+        resp = await self._request_with_retry(
+            client,
+            "GET",
+            url,
+            headers=headers,
+            params=params,
+        )

-                resp = await client.post(url, headers=self._auth_header(), json=payload)
+                resp = await self._request_with_retry(
+                    client,
+                    "POST",
+                    url,
+                    headers=self._auth_header(),
+                    json=payload,
+                )
```

### C. 预期数据流

**优化后完整流程**：
```
[1/6] 数据采集: ~200条
  ├─ ArxivCollector: 15条 ✅ (超时修复)
  ├─ HelmCollector: 14条 ✅
  ├─ GitHubCollector: 31条 ✅
  ├─ HuggingFaceCollector: 43条 ✅
  ├─ TechEmpowerCollector: 46条 ✅
  └─ DBEnginesCollector: 50条 ✅

[1.5/6] URL去重: 200 → 85条新发现

[2/6] 规则预筛选: 85 → 65条 ✅ (保留率76%)
  ├─ TechEmpower: 30条 → 30条 (100%保留)
  ├─ DBEngines: 25条 → 25条 (100%保留)
  ├─ GitHub: 20条 → 7条 (35%保留)
  └─ 其他: 10条 → 3条 (30%保留)

[3/6] PDF增强: 65条 (arXiv ~10条)

[4/6] LLM评分: 65条 (预计45秒)

[5/6] 存储入库: 65条

[6/6] 飞书通知: High/Medium/Low分层推送
```

---

## 九、Codex执行建议

1. **按顺序执行**：Step 1 → Step 2.1-2.5 → Step 3 → Step 4（可选）
2. **每步验证**：修改后运行对应测试，确认无ERROR
3. **日志分析**：关注"权威来源豁免"、"通过预筛选"日志
4. **完整测试**：所有修改完成后，运行`python -m src.main`

**预计完成时间**：1小时

**交付标准**：
- ✅ 所有测试通过
- ✅ 预筛选保留率≥60%
- ✅ arXiv采集成功率≥80%
- ✅ Git commit遵循conventional格式

---

**Claude Code验收任务**：

Codex完成后，我将执行：
1. 运行完整流程测试
2. 分析日志对比优化前后指标
3. 验证飞书存储数据质量
4. 编写优化验收报告
