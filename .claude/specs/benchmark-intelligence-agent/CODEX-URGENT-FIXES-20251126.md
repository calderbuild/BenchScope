# CODEX紧急修复指令 - 2025-11-26 三项关键Bug修复

## 概述

本次修复解决3个关键问题：
1. **P0紧急**: 飞书存储100%失败，223条数据滞留SQLite
2. **P1重要**: MCP工具被误判为Benchmark（噪音率10-20%）
3. **P2优化**: 清理未使用的trending_url配置

**影响范围**:
- 用户无法在飞书表格看到最新采集结果
- 飞书推送的候选中混入MCP工具（非Benchmark）
- 配置冗余可能误导开发者

---

## 问题1: 飞书存储100%失败（P0紧急）

### 问题诊断

**症状**（2025-11-26 02:55日志）：
```
02:55:41,104 [INFO] src.storage.feishu_storage: 飞书access_token刷新成功
02:55:41,127 [WARNING] src.storage.storage_manager: ⚠️  飞书存储失败,降级到SQLite: access_token不存在
02:55:41,165 [INFO] src.storage.storage_manager: ✅ SQLite备份成功: 223条
02:55:41,729 [INFO] src.storage.feishu_storage: 飞书access_token刷新成功
02:55:41,751 [ERROR] src.storage.storage_manager: ❌ 同步失败: access_token不存在
```

**根本原因分析**：

**Bug位置**: `src/storage/feishu_storage.py:273-282`

```python
async def _ensure_field_cache(self, client: httpx.AsyncClient) -> None:
    if self._field_names is not None:
        return

    url = (
        f"{self.base_url}/bitable/v1/apps/{self.settings.feishu.bitable_app_token}/"
        f"tables/{self.settings.feishu.bitable_table_id}/fields"
    )
    params: Dict[str, Any] = {"page_size": 500}
    headers = self._auth_header()  # ❌ Bug在这里！调用时没有先确保token存在
    # ...
```

**问题调用链**：
```
1. save() → await self._ensure_access_token() ✅ token刷新成功
2. save() → await self.get_existing_urls()
3. get_existing_urls() → await self._ensure_field_cache(client)
4. _ensure_field_cache() → headers = self._auth_header() ❌ 直接调用，未确保token存在
5. _auth_header() → if not self.access_token: raise FeishuAPIError("access_token不存在")
```

**为什么会失败**：
- `_ensure_field_cache()` **假设调用者已经刷新了token**
- 但在异步并发场景下，某些路径可能跳过token刷新
- `_auth_header()` 是防御性检查，检测到token不存在立即报错
- 缺少防御性编程：应该在使用token前再次确保其存在

**影响**：
- **223条数据全部写入SQLite，飞书表格未更新**
- 后续同步失败（同样的bug）
- 用户无法在飞书表格看到11月26日采集的所有Benchmark

---

### 解决方案 - 问题1

#### 方案设计原则
1. **防御性编程**：任何使用token的方法都应该先确保token存在
2. **零破坏**：不改变现有API，只增加防御检查
3. **统一修复**：所有调用`_auth_header()`的地方都需要先`await self._ensure_access_token()`

#### 修复步骤

**Step 1: 修复`_ensure_field_cache()`方法**

**文件**: `src/storage/feishu_storage.py`

**当前问题代码** (第273-282行):
```python
async def _ensure_field_cache(self, client: httpx.AsyncClient) -> None:
    if self._field_names is not None:
        return

    url = (
        f"{self.base_url}/bitable/v1/apps/{self.settings.feishu.bitable_app_token}/"
        f"tables/{self.settings.feishu.bitable_table_id}/fields"
    )
    params: Dict[str, Any] = {"page_size": 500}
    headers = self._auth_header()  # ❌ Bug: 没有先确保token存在
    field_names: set[str] = set()
```

**修复后代码**:
```python
async def _ensure_field_cache(self, client: httpx.AsyncClient) -> None:
    if self._field_names is not None:
        return

    # ✅ 修复: 使用token前先确保其存在
    await self._ensure_access_token()

    url = (
        f"{self.base_url}/bitable/v1/apps/{self.settings.feishu.bitable_app_token}/"
        f"tables/{self.settings.feishu.bitable_table_id}/fields"
    )
    params: Dict[str, Any] = {"page_size": 500}
    headers = self._auth_header()  # ✅ 安全: token已确保存在
    field_names: set[str] = set()
```

**修改位置**: 在第275行后添加 `await self._ensure_access_token()`

---

**Step 2: 检查其他调用`_auth_header()`的地方**

使用以下命令检查所有调用点：
```bash
grep -n "_auth_header()" src/storage/feishu_storage.py
```

**需要检查的方法**：
1. `save()` → 已有 `await self._ensure_access_token()` ✅
2. `get_existing_urls()` → 已有 `await self._ensure_access_token()` ✅
3. `read_existing_records()` → 需要检查
4. `_ensure_field_cache()` → **已在Step 1修复** ✅

**Step 2.1: 检查`read_existing_records()`**

**文件**: `src/storage/feishu_storage.py`

查找 `async def read_existing_records` 方法，确认是否有 `await self._ensure_access_token()`。

如果**没有**，在方法开头添加：
```python
async def read_existing_records(self):
    """读取已存在记录（含URL/发布日期/来源），用于时间窗去重"""
    await self._ensure_access_token()  # ✅ 确保token存在

    # ... 原有代码 ...
```

---

**Step 3: 验证修复**

运行完整流程：
```bash
.venv/bin/python -m src.main
```

**预期结果**：
1. ✅ 日志显示 `✅ 飞书存储成功: XXX条`（不再是SQLite备份）
2. ✅ 日志显示 `✅ 同步完成: 0条`（无未同步记录）
3. ✅ 飞书表格实时更新，能看到最新采集结果

**失败回滚**：
如果修复后仍然失败，检查：
1. 环境变量 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET` 是否正确
2. 飞书应用是否有权限访问多维表格
3. 查看完整错误堆栈，确认是否有其他异常

---

## 问题2: MCP工具被误判为Benchmark（P1重要）

### 问题诊断

**误判案例**：

1. **CAPHTECH/kiri** (综合评分 8.4/10)
   - **实际**: MCP工具，用于代码上下文提取（Tool）
   - **被判定为**: Code Generation Benchmark
   - **特征**: README包含"benchmark"、"code retrieval"等关键词

2. **universal-tool-calling-protocol/code-mode** (综合评分 9.3/10)
   - **实际**: MCP协议工具，用于工具调用（Protocol/SDK）
   - **被判定为**: Tool Calling Benchmark
   - **特征**: Stars多（1031），README提到"benchmark"（指性能测试，非评测基准）

**根本原因**：

LLM评分Prompt缺少对**工具(Tool/Framework/SDK)** vs **评测基准(Benchmark/Evaluation Dataset)**的明确区分。

**工具 vs Benchmark 的核心区别**：

| 维度 | 工具(Tool/Framework) | 评测基准(Benchmark) |
|------|---------------------|-------------------|
| **目的** | 提供功能接口、帮助开发者构建应用 | 提供测试数据集、评估模型能力 |
| **产出** | 可运行的代码、SDK、API | 测试集、排行榜、评估指标 |
| **使用方式** | import/调用 → 实现功能 | 运行测试 → 获得分数 |
| **示例** | MCP、LangChain、FastAPI | HumanEval、MBPP、SWE-bench |

**为什么LLM会误判**：
1. MCP工具的README常包含"evaluation"、"benchmark"等关键词
2. 当前Prompt没有明确负面过滤规则（如"is this a tool/SDK?"）
3. 活跃度高（stars多）→ 高分
4. README提到"benchmark"（但实际是性能测试benchmark，不是评测benchmark）

---

### 解决方案 - 问题2

#### 方案设计原则
1. **明确定义**：在Prompt中清晰定义什么是Benchmark，什么不是
2. **负面筛选**：增加专门的"工具判定"检查项
3. **示例引导**：提供正反例，帮助LLM理解边界

#### 修复步骤

**Step 1: 更新LLM评分Prompt - 添加工具过滤说明**

**文件**: `src/scorer/llm_scorer.py`

**当前问题代码** (第95-107行附近):
```python
UNIFIED_SCORING_PROMPT_TEMPLATE = """
你是MGX BenchScope的专家评估员，专门为AI/Agent领域的Benchmark候选打分。

MGX是一个多智能体协作框架（https://mgx.dev），专注Vibe Coding（AI原生编程）。
我们需要寻找高质量的Benchmark来评估MGX的能力。

候选信息：
- 标题: {title}
- 来源: {source}
- 摘要: {summary}
- URL: {url}
{extra_fields}

你的任务：评估该候选是否适合纳入MGX的Benchmark池。
```

**修复后代码**:
```python
UNIFIED_SCORING_PROMPT_TEMPLATE = """
你是MGX BenchScope的专家评估员，专门为AI/Agent领域的Benchmark候选打分。

MGX是一个多智能体协作框架（https://mgx.dev），专注Vibe Coding（AI原生编程）。
我们需要寻找高质量的Benchmark来评估MGX的能力。

【重要】什么是Benchmark？什么不是？
✅ **Benchmark（评测基准）**:
- 提供测试数据集、评估任务、排行榜
- 目的是评估模型/系统的能力（准确率、性能、成功率）
- 示例: HumanEval（代码生成测试集）、SWE-bench（软件工程任务）、MMLU（知识问答）
- 关键特征: 有测试样本、有评估指标、有baseline结果

❌ **不是Benchmark（工具/框架）**:
- 提供功能接口、SDK、协议、框架
- 目的是帮助开发者构建应用
- 示例: MCP（Model Context Protocol）、LangChain（框架）、FastAPI（Web框架）
- 关键特征: import后可调用、提供API文档、有使用示例

⚠️ **常见误判场景**:
- README提到"benchmark"但实际是性能测试 → 不是评测基准
- 包含"evaluation"但实际是工具的评估模块 → 不是评测基准
- 有"test"但实际是单元测试 → 不是评测基准

候选信息：
- 标题: {title}
- 来源: {source}
- 摘要: {summary}
- URL: {url}
{extra_fields}

你的任务：
1. **首先判断**：这是Benchmark（评测基准）还是Tool/Framework（工具/框架）？
2. **如果是工具**：所有维度评分降低3-5分，overall_reasoning说明"这是工具/框架，不是评测基准"
3. **如果是Benchmark**：正常按照以下标准评分
```

---

**Step 2: 更新评分JSON Schema - 添加is_tool字段**

**文件**: `src/scorer/llm_scorer.py`

在 `BenchmarkScore` Pydantic模型中添加工具判定字段：

**当前问题代码** (第60-95行附近):
```python
class BenchmarkScore(BaseModel):
    """统一的Benchmark评分模型"""

    activity: float = Field(
        ge=0.0, le=10.0, description="活跃度评分（0-10分）"
    )
    activity_reasoning: str = Field(
        min_length=150,
        description="活跃度推理（≥150字符）",
    )
    # ... 其他字段 ...
```

**修复后代码**:
```python
class BenchmarkScore(BaseModel):
    """统一的Benchmark评分模型"""

    # ✅ 新增: 工具判定字段
    is_tool_not_benchmark: bool = Field(
        description="判断：这是工具/框架/SDK（True）还是评测基准（False）？"
    )
    tool_reasoning: str = Field(
        min_length=100,
        description="工具判定推理（≥100字符）：说明为什么判定为工具或Benchmark，提供关键证据",
    )

    activity: float = Field(
        ge=0.0, le=10.0, description="活跃度评分（0-10分）"
    )
    activity_reasoning: str = Field(
        min_length=150,
        description="活跃度推理（≥150字符）",
    )
    # ... 其他字段保持不变 ...
```

---

**Step 3: 更新评分逻辑 - 工具惩罚机制**

**文件**: `src/scorer/llm_scorer.py`

在 `score()` 方法中，接收LLM返回的 `is_tool_not_benchmark` 字段，如果为True，降低综合评分。

**当前问题代码** (第600-650行附近，`score()`方法):
```python
async def score(self, candidate: RawCandidate) -> ScoredCandidate:
    # ... 现有评分逻辑 ...

    # 计算综合得分
    total_score = (
        score_data.activity * constants.ACTIVITY_WEIGHT
        + score_data.reproducibility * constants.REPRODUCIBILITY_WEIGHT
        + score_data.license * constants.LICENSE_WEIGHT
        + score_data.novelty * constants.NOVELTY_WEIGHT
        + score_data.relevance * constants.RELEVANCE_WEIGHT
    )

    return ScoredCandidate(
        **candidate.model_dump(),
        activity_score=score_data.activity,
        # ... 其他字段 ...
        total_score=total_score,
    )
```

**修复后代码**:
```python
async def score(self, candidate: RawCandidate) -> ScoredCandidate:
    # ... 现有评分逻辑 ...

    # 计算综合得分
    total_score = (
        score_data.activity * constants.ACTIVITY_WEIGHT
        + score_data.reproducibility * constants.REPRODUCIBILITY_WEIGHT
        + score_data.license * constants.LICENSE_WEIGHT
        + score_data.novelty * constants.NOVELTY_WEIGHT
        + score_data.relevance * constants.RELEVANCE_WEIGHT
    )

    # ✅ 新增: 工具惩罚机制
    if score_data.is_tool_not_benchmark:
        logger.warning(
            "工具误判检测: %s (原始分%.1f → 惩罚后%.1f), 理由: %s",
            candidate.title,
            total_score,
            max(total_score - 3.0, 0.0),
            score_data.tool_reasoning[:100],
        )
        total_score = max(total_score - 3.0, 0.0)  # 扣除3分，最低0分

    return ScoredCandidate(
        **candidate.model_dump(),
        activity_score=score_data.activity,
        # ... 其他字段 ...
        total_score=total_score,
        # ✅ 新增: 存储工具判定结果
        is_tool_not_benchmark=score_data.is_tool_not_benchmark,
        tool_reasoning=score_data.tool_reasoning,
    )
```

---

**Step 4: 更新ScoredCandidate模型**

**文件**: `src/models.py`

在 `ScoredCandidate` 类中添加工具判定字段：

**当前问题代码** (ScoredCandidate类):
```python
@dataclass
class ScoredCandidate(RawCandidate):
    """评分后的候选Benchmark"""

    activity_score: float = 0.0
    activity_reasoning: str = ""
    # ... 其他评分字段 ...
    total_score: float = 0.0
    overall_reasoning: str = ""
```

**修复后代码**:
```python
@dataclass
class ScoredCandidate(RawCandidate):
    """评分后的候选Benchmark"""

    # ✅ 新增: 工具判定字段
    is_tool_not_benchmark: bool = False
    tool_reasoning: str = ""

    activity_score: float = 0.0
    activity_reasoning: str = ""
    # ... 其他评分字段保持不变 ...
    total_score: float = 0.0
    overall_reasoning: str = ""
```

---

**Step 5: 更新飞书字段映射（可选）**

如果需要在飞书表格中显示工具判定结果，更新字段映射：

**文件**: `src/storage/feishu_storage.py`

**当前问题代码** (FIELD_MAPPING):
```python
FIELD_MAPPING = {
    "url": "URL",
    "title": "标题",
    # ... 其他字段 ...
    "overall_reasoning": "评分依据",
}
```

**修复后代码**:
```python
FIELD_MAPPING = {
    "url": "URL",
    "title": "标题",
    # ... 其他字段 ...
    "overall_reasoning": "评分依据",
    # ✅ 新增: 工具判定字段（可选）
    "is_tool_not_benchmark": "是否为工具",
    "tool_reasoning": "工具判定理由",
}
```

**注意**: 这一步是可选的，需要先在飞书表格中手动创建这两个字段。

---

**Step 6: 验证修复**

运行完整流程：
```bash
.venv/bin/python -m src.main
```

**预期结果**：
1. ✅ 日志显示 `工具误判检测: CAPHTECH/kiri (原始分8.4 → 惩罚后5.4)`
2. ✅ 日志显示 `工具误判检测: universal-tool-calling-protocol/code-mode (原始分9.3 → 惩罚后6.3)`
3. ✅ MCP工具的总分降低3分，优先级降低
4. ✅ 真正的Benchmark（如arXiv论文）不受影响

**测试案例**：
- ✅ 真Benchmark: `HumanEval` → `is_tool_not_benchmark=False` → 评分不变
- ✅ 工具: `CAPHTECH/kiri` → `is_tool_not_benchmark=True` → 扣3分
- ✅ 边界case: `LangChain` → `is_tool_not_benchmark=True` → 扣3分

---

## 问题3: 清理未使用的trending_url配置（P2优化）

### 问题诊断

**现象**：
- `config/sources.yaml` 中有 `trending_url: "https://github.com/trending"`
- `src/config.py` 中定义了 `trending_url` 字段
- 但 `src/collectors/github_collector.py` **从未使用** trending_url

**证据**：
```bash
$ grep "trending_url" src/collectors/github_collector.py
# 无输出 - 未被引用

$ grep "self.trending_url" src/collectors/github_collector.py
# 无输出 - 未被使用
```

**实际数据源**：
- 使用 **GitHub Search API** (`https://api.github.com/search/repositories`)
- 查询条件: `created:>=YYYY-MM-DD` (最近30天)
- 不依赖GitHub Trending页面

**影响**：
- 配置冗余，可能误导开发者
- 浪费配置文件空间
- 如果未来接入Trending，会产生命名冲突

---

### 解决方案 - 问题3

#### 修复步骤

**Step 1: 删除config/sources.yaml中的trending_url**

**文件**: `config/sources.yaml`

**当前问题代码** (github部分):
```yaml
github:
  enabled: true
  lookback_days: 30
  min_stars: 10
  search_api: "https://api.github.com/search/repositories"
  trending_url: "https://github.com/trending"  # ❌ 未使用
  timeout_seconds: 5
  # ... 其他配置 ...
```

**修复后代码**:
```yaml
github:
  enabled: true
  lookback_days: 30
  min_stars: 10
  search_api: "https://api.github.com/search/repositories"
  # trending_url 已删除（未使用）
  timeout_seconds: 5
  # ... 其他配置保持不变 ...
```

---

**Step 2: 删除src/config.py中的trending_url字段**

**文件**: `src/config.py`

**当前问题代码** (GitHubSourceConfig类):
```python
@dataclass
class GitHubSourceConfig:
    enabled: bool
    lookback_days: int
    min_stars: int
    search_api: str
    trending_url: str  # ❌ 未使用
    timeout_seconds: int
    # ... 其他字段 ...
```

**修复后代码**:
```python
@dataclass
class GitHubSourceConfig:
    enabled: bool
    lookback_days: int
    min_stars: int
    search_api: str
    # trending_url 已删除（未使用）
    timeout_seconds: int
    # ... 其他字段保持不变 ...
```

---

**Step 3: 删除src/common/constants.py中的GITHUB_TRENDING_URL**

**文件**: `src/common/constants.py`

使用以下命令检查是否存在：
```bash
grep -n "GITHUB_TRENDING_URL" src/common/constants.py
```

如果存在，删除该常量定义：

**当前问题代码**:
```python
GITHUB_TRENDING_URL: Final[str] = "https://github.com/trending"  # ❌ 未使用
```

**修复后代码**:
```python
# GITHUB_TRENDING_URL 已删除（未使用）
```

---

**Step 4: 更新配置解析逻辑**

**文件**: `src/config.py`

查找 `GitHubSourceConfig` 的初始化代码，删除 `trending_url` 的默认值：

**当前问题代码** (第280行附近):
```python
github_cfg = sources_cfg.get("github", {})
github = GitHubSourceConfig(
    enabled=github_cfg.get("enabled", True),
    # ... 其他字段 ...
    trending_url=github_cfg.get("trending_url", constants.GITHUB_TRENDING_URL),  # ❌ 删除
)
```

**修复后代码**:
```python
github_cfg = sources_cfg.get("github", {})
github = GitHubSourceConfig(
    enabled=github_cfg.get("enabled", True),
    # ... 其他字段保持不变 ...
    # trending_url 已删除
)
```

---

**Step 5: 验证修复**

运行完整流程：
```bash
.venv/bin/python -m src.main
```

**预期结果**：
1. ✅ GitHub采集器正常工作（使用Search API）
2. ✅ 没有关于trending_url的错误或警告
3. ✅ 配置加载成功，没有缺失字段报错

**测试命令**：
```bash
# 检查trending_url是否完全删除
grep -r "trending_url" src/ config/
# 预期输出: 无结果

# 检查GITHUB_TRENDING_URL是否完全删除
grep -r "GITHUB_TRENDING_URL" src/
# 预期输出: 无结果
```

---

## 测试验证计划

### 测试环境
- Python 3.11
- uv虚拟环境: `.venv/bin/python`
- 飞书开发环境（真实API）

### 测试用例

#### 测试1: 飞书存储修复验证
```bash
# 1. 清空SQLite（确保无降级数据）
rm -f fallback.db

# 2. 运行完整流程
.venv/bin/python -m src.main

# 3. 检查日志
tail -100 logs/benchscope.log | grep "飞书存储\|SQLite备份"

# 预期结果:
# ✅ 飞书存储成功: XXX条
# ✅ 同步完成: 0条（无未同步记录）
# ❌ 不应出现: "降级到SQLite"
```

#### 测试2: MCP工具过滤验证
```bash
# 1. 手动构造MCP工具测试用例
cat > /tmp/test_mcp.py <<'EOF'
import asyncio
from src.models import RawCandidate
from src.scorer import LLMScorer

async def test():
    scorer = LLMScorer()
    await scorer.__aenter__()

    # MCP工具示例
    mcp_candidate = RawCandidate(
        title="CAPHTECH/kiri",
        url="https://github.com/CAPHTECH/kiri",
        summary="MCP server for code context extraction",
        source="github",
    )

    result = await scorer.score(mcp_candidate)
    print(f"is_tool: {result.is_tool_not_benchmark}")
    print(f"tool_reasoning: {result.tool_reasoning}")
    print(f"total_score: {result.total_score}")

    await scorer.__aexit__(None, None, None)

asyncio.run(test())
EOF

.venv/bin/python /tmp/test_mcp.py

# 预期结果:
# is_tool: True
# tool_reasoning: 这是MCP协议工具，提供代码上下文提取功能...
# total_score: <原始分数 - 3.0>
```

#### 测试3: 真实Benchmark不受影响
```bash
# 使用arXiv论文作为测试用例
cat > /tmp/test_real_benchmark.py <<'EOF'
import asyncio
from src.models import RawCandidate
from src.scorer import LLMScorer

async def test():
    scorer = LLMScorer()
    await scorer.__aenter__()

    # 真实Benchmark示例
    real_benchmark = RawCandidate(
        title="HumanEval: Hand-Written Evaluation Set",
        url="https://arxiv.org/abs/2107.03374",
        summary="A benchmark for code generation with 164 programming problems",
        source="arxiv",
    )

    result = await scorer.score(real_benchmark)
    print(f"is_tool: {result.is_tool_not_benchmark}")
    print(f"total_score: {result.total_score}")

    await scorer.__aexit__(None, None, None)

asyncio.run(test())
EOF

.venv/bin/python /tmp/test_real_benchmark.py

# 预期结果:
# is_tool: False
# total_score: <原始分数，不扣分>
```

#### 测试4: 配置清理验证
```bash
# 1. 检查trending_url是否完全删除
grep -r "trending_url" src/ config/
# 预期输出: 无结果

# 2. 运行配置加载测试
.venv/bin/python -c "from src.config import get_settings; s = get_settings(); print('GitHub配置加载成功')"
# 预期输出: GitHub配置加载成功

# 3. 运行GitHub采集器
.venv/bin/python -c "
import asyncio
from src.collectors import GitHubCollector
async def test():
    collector = GitHubCollector()
    results = await collector.collect()
    print(f'采集成功: {len(results)}条')
asyncio.run(test())
"
# 预期输出: 采集成功: XX条
```

---

## 成功标准

### P0 - 飞书存储修复
- [x] 日志显示 `✅ 飞书存储成功: XXX条`（不再是SQLite备份）
- [x] 日志显示 `✅ 同步完成: 0条`（无未同步记录）
- [x] 飞书表格实时更新，能看到最新采集结果
- [x] SQLite fallback.db 文件为空或不存在

### P1 - MCP工具过滤
- [x] MCP工具被正确识别为 `is_tool_not_benchmark=True`
- [x] MCP工具总分扣除3分
- [x] 日志显示工具误判警告
- [x] 真实Benchmark不受影响（`is_tool_not_benchmark=False`）

### P2 - 配置清理
- [x] `grep -r "trending_url" src/ config/` 无结果
- [x] `grep -r "GITHUB_TRENDING_URL" src/` 无结果
- [x] GitHub采集器正常工作
- [x] 配置加载无错误

---

## 回滚方案

如果修复后出现问题，使用以下步骤回滚：

### 回滚P0修复
```bash
# 1. 恢复 _ensure_field_cache 方法
git checkout HEAD -- src/storage/feishu_storage.py

# 2. 重新运行，确认回到降级状态
.venv/bin/python -m src.main
```

### 回滚P1修复
```bash
# 1. 恢复评分模型和Prompt
git checkout HEAD -- src/scorer/llm_scorer.py src/models.py

# 2. 重新运行
.venv/bin/python -m src.main
```

### 回滚P2修复
```bash
# 1. 恢复配置文件
git checkout HEAD -- config/sources.yaml src/config.py src/common/constants.py

# 2. 重新运行
.venv/bin/python -m src.main
```

---

## 附录：关键代码位置

### 文件清单
- `src/storage/feishu_storage.py` - 飞书存储逻辑
- `src/scorer/llm_scorer.py` - LLM评分引擎
- `src/models.py` - 数据模型定义
- `config/sources.yaml` - 数据源配置
- `src/config.py` - 配置管理
- `src/common/constants.py` - 常量定义

### 关键方法
- `FeishuStorage._ensure_access_token()` - Token刷新
- `FeishuStorage._ensure_field_cache()` - 字段缓存（Bug位置）
- `LLMScorer.score()` - 单个候选评分
- `BenchmarkScore` - 评分数据模型
- `ScoredCandidate` - 评分后候选模型

---

## 检查清单

提交前请确认：

- [ ] 所有代码修改已完成
- [ ] 单元测试通过（如有）
- [ ] 集成测试通过（完整流程）
- [ ] 飞书表格更新验证
- [ ] 日志输出正确
- [ ] 无新增警告或错误
- [ ] 代码符合PEP8规范
- [ ] 中文注释清晰
- [ ] Git commit message清晰
- [ ] 文档已更新（如需要）

---

**修复完成后，请运行完整流程测试，并将测试结果反馈给Claude Code进行验收。**
