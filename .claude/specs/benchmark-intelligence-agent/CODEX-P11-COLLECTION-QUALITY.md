# CODEX开发指令：P11采集质量优化

## 问题诊断

**今日推送：仅1条新候选（ace-agent/ace），远低于预期**

| 指标 | 当前值 | 目标值 |
|------|--------|--------|
| 每日新候选 | 1条 | >=5条 |
| 飞书已有记录 | 279条 | - |
| arXiv采集数量 | ~20条 | >=30条 |
| GitHub工具库占比 | 较高 | <10% |

**根本原因**：
1. arXiv关键词缺少通用Benchmark术语（如"benchmark"、"evaluation benchmark"）
2. GitHub采集器未过滤Topic黑名单（SDK/client/wrapper等工具类仓库混入）
3. arXiv URL版本号未规范化（v1/v2/v3算不同URL，导致重复）
4. GitHub Fork仓库未过滤（与upstream重复）
5. GitHub Stars阈值静态（新创建的高质量仓库被误杀）

---

## Step 1: arXiv关键词扩展

### 1.1 修改 `config/sources.yaml`

**文件路径**: `/mnt/d/VibeCoding_pgm/BenchScope/config/sources.yaml`

**当前代码** (Line 16-50):
```yaml
arxiv:
  enabled: true
  max_results: 100
  lookback_hours: 168
  timeout_seconds: 20
  max_retries: 2

  # Phase 7: 聚焦MGX核心场景关键词
  keywords:
    # P0 - 编程与代码
    - code generation benchmark
    - code evaluation
    # ... 后续关键词
```

**修改后**:
```yaml
arxiv:
  enabled: true
  max_results: 100
  lookback_hours: 168
  timeout_seconds: 20
  max_retries: 2

  # Phase 11: 扩展通用Benchmark术语 + MGX场景关键词
  keywords:
    # P11新增：通用Benchmark术语（优先匹配，放在最前面）
    - benchmark
    - evaluation benchmark
    - LLM benchmark
    - language model benchmark
    - AI benchmark
    - model evaluation
    - benchmark dataset
    - test suite
    - evaluation framework
    - benchmarking

    # P11新增：MGX场景扩展
    - llm-based agent
    - agent planning
    - function calling
    - tool calling
    - reasoning benchmark
    - agent evaluation

    # P0 - 编程与代码（保持不变）
    - code generation benchmark
    - code evaluation
    - programming benchmark
    - software engineering benchmark
    - program synthesis evaluation
    - code completion benchmark

    # P0 - Web自动化（保持不变）
    - web agent benchmark
    - browser automation benchmark
    - web navigation evaluation
    - GUI automation benchmark

    # P1 - 多智能体（保持不变）
    - multi-agent benchmark
    - agent collaboration evaluation
    - tool use benchmark
    - API usage benchmark

    # Phase 6.5 - 后端开发能力（保持不变）
    - backend development benchmark
    - API design benchmark
    - RESTful API evaluation
    - GraphQL performance benchmark
    - database query benchmark
    - SQL optimization benchmark
    - microservices benchmark
    - distributed systems benchmark
    - system design evaluation
    - backend framework benchmark
    - server performance benchmark
    - web framework comparison
```

**验证命令**:
```bash
.venv/bin/python -c "
from src.config import get_settings
s = get_settings()
keywords = s.sources.arxiv.keywords
print(f'arXiv关键词数量: {len(keywords)}')
assert 'benchmark' in keywords, '缺少通用benchmark关键词'
assert 'LLM benchmark' in keywords, '缺少LLM benchmark关键词'
print('Step 1 验证通过')
"
```

---

## Step 2: GitHub Topic黑名单

### 2.1 修改 `src/common/constants.py`

**文件路径**: `/mnt/d/VibeCoding_pgm/BenchScope/src/common/constants.py`

**在文件末尾添加**:
```python
# ============================================================
# P11: GitHub Topic黑名单（采集阶段排除工具类仓库）
# ============================================================

GITHUB_TOPIC_BLACKLIST: Final[set[str]] = {
    # SDK/客户端
    "sdk", "client", "api-client", "rest-client", "grpc-client",
    # 包装器/适配器
    "wrapper", "adapter", "binding", "connector",
    # 框架/库
    "framework", "library", "toolkit", "package",
    # 工具类
    "cli", "cli-tool", "utility", "helper", "tool",
    # 资源列表
    "awesome", "awesome-list", "curated-list", "resources",
    # 协议类
    "mcp", "model-context-protocol", "protocol",
    # 其他非Benchmark
    "boilerplate", "starter", "template", "scaffold",
    "tutorial", "course", "learning", "guide",
}
```

### 2.2 修改 `src/collectors/github_collector.py`

**文件路径**: `/mnt/d/VibeCoding_pgm/BenchScope/src/collectors/github_collector.py`

**找到 `_passes_basic_repo_filters` 方法** (约Line 269)

**当前代码**:
```python
def _passes_basic_repo_filters(self, repo: Dict[str, Any]) -> bool:
    """基础过滤: stars/语言/更新时间"""

    stars = repo.get("stargazers_count", 0)
    if stars < self.min_stars:
        return False

    # ... 后续代码
```

**修改后**:
```python
def _passes_basic_repo_filters(self, repo: Dict[str, Any]) -> bool:
    """基础过滤: stars/语言/更新时间/topic黑名单/fork"""

    # P11新增：Topic黑名单过滤（放在最前面，快速排除工具类仓库）
    topics = {t.lower() for t in (repo.get("topics") or [])}
    if topics & constants.GITHUB_TOPIC_BLACKLIST:
        logger.debug("GitHub topic黑名单过滤: %s (topics=%s)",
                     repo.get("full_name"), topics)
        return False

    stars = repo.get("stargazers_count", 0)
    if stars < self.min_stars:
        return False

    # ... 后续代码保持不变
```

**验证命令**:
```bash
.venv/bin/python -c "
from src.common import constants
assert 'sdk' in constants.GITHUB_TOPIC_BLACKLIST
assert 'awesome' in constants.GITHUB_TOPIC_BLACKLIST
print(f'GitHub Topic黑名单: {len(constants.GITHUB_TOPIC_BLACKLIST)}个')
print('Step 2 验证通过')
"
```

---

## Step 3: arXiv URL版本号规范化

### 3.1 修改 `src/common/url_utils.py`

**文件路径**: `/mnt/d/VibeCoding_pgm/BenchScope/src/common/url_utils.py`

**当前代码**:
```python
"""URL 规范化工具函数"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlsplit, urlunsplit


# 需要去除的常见跟踪参数，避免同一链接被视为不同URL
_TRACKING_PARAMS = {
    "utm_source",
    # ...
}


def canonicalize_url(url: str | None) -> str:
    """对URL做轻量规范化，便于去重比较。"""
    if not url:
        return ""

    stripped = url.strip()
    if not stripped:
        return ""

    try:
        parts = urlsplit(stripped)
    # ... 后续代码
```

**修改后**:
```python
"""URL 规范化工具函数"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit


# 需要去除的常见跟踪参数，避免同一链接被视为不同URL
_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "ref_src",
}

# P11新增：arXiv URL版本号匹配模式
# 匹配: arxiv.org/abs/2312.12345v1, arxiv.org/pdf/2312.12345v2
_ARXIV_VERSION_PATTERN = re.compile(
    r"(arxiv\.org/(?:abs|pdf)/\d+\.\d+)v\d+", re.IGNORECASE
)


def _normalize_arxiv_url(url: str) -> str:
    """P11新增：去除arXiv URL中的版本号后缀。

    确保同一论文不同版本被视为相同URL。

    Examples:
        https://arxiv.org/abs/2312.12345v1 -> https://arxiv.org/abs/2312.12345
        https://arxiv.org/pdf/2312.12345v2 -> https://arxiv.org/pdf/2312.12345
    """
    return _ARXIV_VERSION_PATTERN.sub(r"\1", url)


def canonicalize_url(url: str | None) -> str:
    """对URL做轻量规范化，便于去重比较。

    - 去除首尾空白
    - 统一小写的scheme/host
    - 移除片段(#...)和常见跟踪参数
    - 去掉末尾的多余斜杠
    - P11新增：arXiv版本号规范化
    """
    if not url:
        return ""

    stripped = url.strip()
    if not stripped:
        return ""

    # P11新增：arXiv版本号规范化
    stripped = _normalize_arxiv_url(stripped)

    try:
        parts = urlsplit(stripped)
    except Exception:
        # 非法URL直接返回原始字符串，至少保证可作为键使用
        return stripped

    # 过滤常见跟踪参数，但保留其他query以避免丢失关键信息
    query_pairs = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in _TRACKING_PARAMS
    ]
    cleaned_query = "&".join(f"{k}={v}" if v != "" else k for k, v in query_pairs)

    # 统一大小写并移除末尾斜杠
    normalized_path = parts.path.rstrip("/") or "/"

    normalized = urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            normalized_path,
            cleaned_query,
            "",  # 丢弃fragment
        )
    )
    return normalized
```

**验证命令**:
```bash
.venv/bin/python -c "
from src.common.url_utils import canonicalize_url

# 测试arXiv版本号规范化
url1 = 'https://arxiv.org/abs/2312.12345v1'
url2 = 'https://arxiv.org/abs/2312.12345v2'
url3 = 'https://arxiv.org/pdf/2312.12345v3'
url4 = 'https://arxiv.org/abs/2312.12345'

assert canonicalize_url(url1) == canonicalize_url(url2), 'v1和v2应该相同'
assert canonicalize_url(url1) == canonicalize_url(url4), 'v1和无版本应该相同'
print(f'{url1} -> {canonicalize_url(url1)}')
print(f'{url2} -> {canonicalize_url(url2)}')
print(f'{url3} -> {canonicalize_url(url3)}')
print('Step 3 验证通过')
"
```

---

## Step 4: GitHub Fork过滤

### 4.1 修改 `src/collectors/github_collector.py`

**文件路径**: `/mnt/d/VibeCoding_pgm/BenchScope/src/collectors/github_collector.py`

**在Step 2的基础上，继续修改 `_passes_basic_repo_filters` 方法**:

**修改后**:
```python
def _passes_basic_repo_filters(self, repo: Dict[str, Any]) -> bool:
    """基础过滤: fork/topic黑名单/stars/语言/更新时间"""

    # P11新增：Fork仓库过滤（最先检查，快速排除）
    if repo.get("fork", False):
        logger.debug("GitHub Fork仓库过滤: %s", repo.get("full_name"))
        return False

    # P11新增：Topic黑名单过滤
    topics = {t.lower() for t in (repo.get("topics") or [])}
    if topics & constants.GITHUB_TOPIC_BLACKLIST:
        logger.debug("GitHub topic黑名单过滤: %s (topics=%s)",
                     repo.get("full_name"), topics)
        return False

    stars = repo.get("stargazers_count", 0)
    if stars < self.min_stars:
        return False

    # ... 后续代码保持不变
```

**验证**: 运行完整采集流程，检查日志中是否有Fork仓库被过滤的记录

---

## Step 5: GitHub动态Stars阈值

### 5.1 修改 `src/common/constants.py`

**文件路径**: `/mnt/d/VibeCoding_pgm/BenchScope/src/common/constants.py`

**在Step 2添加的黑名单之后，继续添加**:
```python
# ============================================================
# P11: GitHub动态Stars阈值（按仓库年龄调整，捕获新兴Benchmark）
# ============================================================

GITHUB_DYNAMIC_STARS_THRESHOLDS: Final[list[tuple[int, int]]] = [
    # (仓库年龄天数, 最低stars)
    (7, 5),      # 7天内创建：stars >= 5（非常新，降低门槛）
    (30, 15),    # 30天内创建：stars >= 15
    (90, 30),    # 90天内创建：stars >= 30
]
GITHUB_DEFAULT_MIN_STARS: Final[int] = 50  # 超过90天的仓库使用默认阈值
```

### 5.2 修改 `src/collectors/github_collector.py`

**文件路径**: `/mnt/d/VibeCoding_pgm/BenchScope/src/collectors/github_collector.py`

**在类中添加新方法** (在 `_passes_basic_repo_filters` 方法之前):
```python
def _get_dynamic_stars_threshold(self, repo: Dict[str, Any]) -> int:
    """P11新增：根据仓库创建时间动态计算stars阈值。

    新仓库使用较低阈值，避免遗漏新兴Benchmark。
    """
    created_at = self._parse_datetime(repo.get("created_at"))
    if not created_at:
        return constants.GITHUB_DEFAULT_MIN_STARS

    now = datetime.now(timezone.utc)
    age_days = (now - created_at).days

    for threshold_days, min_stars in constants.GITHUB_DYNAMIC_STARS_THRESHOLDS:
        if age_days <= threshold_days:
            logger.debug("GitHub动态Stars阈值: %s (年龄%d天 -> 阈值%d)",
                        repo.get("full_name"), age_days, min_stars)
            return min_stars

    return constants.GITHUB_DEFAULT_MIN_STARS
```

**修改 `_passes_basic_repo_filters` 方法**:
```python
def _passes_basic_repo_filters(self, repo: Dict[str, Any]) -> bool:
    """基础过滤: fork/topic黑名单/动态stars/语言/更新时间"""

    # P11：Fork仓库过滤
    if repo.get("fork", False):
        logger.debug("GitHub Fork仓库过滤: %s", repo.get("full_name"))
        return False

    # P11：Topic黑名单过滤
    topics = {t.lower() for t in (repo.get("topics") or [])}
    if topics & constants.GITHUB_TOPIC_BLACKLIST:
        logger.debug("GitHub topic黑名单过滤: %s (topics=%s)",
                     repo.get("full_name"), topics)
        return False

    # P11修改：使用动态stars阈值（替代静态self.min_stars）
    stars = repo.get("stargazers_count", 0)
    min_stars_required = self._get_dynamic_stars_threshold(repo)
    if stars < min_stars_required:
        logger.debug("GitHub stars不足: %s (%d < %d)",
                     repo.get("full_name"), stars, min_stars_required)
        return False

    # ... 后续代码保持不变
```

**验证命令**:
```bash
.venv/bin/python -c "
from src.common import constants

# 验证动态阈值配置
thresholds = constants.GITHUB_DYNAMIC_STARS_THRESHOLDS
print(f'动态Stars阈值配置: {thresholds}')
print(f'默认阈值: {constants.GITHUB_DEFAULT_MIN_STARS}')

assert thresholds[0] == (7, 5), '7天阈值应为5'
assert thresholds[1] == (30, 15), '30天阈值应为15'
assert thresholds[2] == (90, 30), '90天阈值应为30'
print('Step 5 验证通过')
"
```

---

## 完整测试计划

### 单元测试

```bash
# 1. 测试arXiv关键词配置
.venv/bin/python -c "
from src.config import get_settings
s = get_settings()
keywords = s.sources.arxiv.keywords
print(f'arXiv关键词数量: {len(keywords)}')
assert 'benchmark' in keywords
assert 'LLM benchmark' in keywords
print('arXiv关键词测试通过')
"

# 2. 测试arXiv URL规范化
.venv/bin/python -c "
from src.common.url_utils import canonicalize_url
url1 = 'https://arxiv.org/abs/2312.12345v1'
url2 = 'https://arxiv.org/abs/2312.12345v2'
assert canonicalize_url(url1) == canonicalize_url(url2)
print('arXiv URL规范化测试通过')
"

# 3. 测试GitHub Topic黑名单
.venv/bin/python -c "
from src.common import constants
assert 'sdk' in constants.GITHUB_TOPIC_BLACKLIST
assert 'awesome' in constants.GITHUB_TOPIC_BLACKLIST
print('GitHub Topic黑名单测试通过')
"

# 4. 测试动态Stars阈值
.venv/bin/python -c "
from src.common import constants
assert constants.GITHUB_DYNAMIC_STARS_THRESHOLDS[0] == (7, 5)
assert constants.GITHUB_DEFAULT_MIN_STARS == 50
print('动态Stars阈值测试通过')
"
```

### 集成测试

```bash
# 完整流程测试
.venv/bin/python -m src.main

# 检查日志
grep -E "(Topic黑名单|Fork仓库|动态Stars|版本号规范化)" logs/benchscope.log | tail -20
```

---

## 验收标准

| 指标 | 当前值 | 目标值 | 验证方法 |
|------|--------|--------|----------|
| arXiv关键词数量 | 27个 | >=40个 | 配置检查 |
| arXiv采集数量 | ~20条 | >=30条 | 单独测试采集器 |
| GitHub Topic黑名单 | 无 | 已配置 | 常量检查 |
| arXiv URL规范化 | v1/v2分开 | 合并去重 | 单元测试 |
| Fork仓库过滤 | 无 | 已启用 | 日志检查 |
| 动态Stars阈值 | 无 | 7/30/90天分级 | 常量检查 |

---

## 成功检查清单

- [ ] `config/sources.yaml` 添加了通用Benchmark关键词
- [ ] `src/common/constants.py` 添加了Topic黑名单和动态Stars配置
- [ ] `src/common/url_utils.py` 添加了arXiv版本号规范化
- [ ] `src/collectors/github_collector.py` 添加了Fork过滤和Topic过滤
- [ ] `src/collectors/github_collector.py` 实现了动态Stars阈值方法
- [ ] 所有单元测试通过
- [ ] 完整流程测试通过
- [ ] 代码符合PEP8规范
- [ ] 关键逻辑有中文注释
