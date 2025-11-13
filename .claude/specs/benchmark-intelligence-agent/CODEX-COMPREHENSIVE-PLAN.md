# Codex 综合开发方案：BenchScope Phase 3-5 完整实施指令

**文档版本**: v1.0
**创建时间**: 2025-11-13
**执行者**: Codex
**监督者**: Claude Code
**前置条件**: Phase 1-2 MVP已完成并验收通过

---

## 📋 文档目录

1. [项目现状总结](#项目现状总结)
2. [Phase 3: 核心优化 (2-3天)](#phase-3-核心优化)
3. [Phase 4: 版本跟踪 (3-4天)](#phase-4-版本跟踪)
4. [Phase 5: 增强功能 (2-3天)](#phase-5-增强功能)
5. [测试与验收流程](#测试与验收流程)
6. [代码规范与约束](#代码规范与约束)

---

## 项目现状总结

### ✅ Phase 1-2 已完成功能

| 模块 | 状态 | 关键指标 |
|------|------|---------|
| **数据采集** | ✅ 完成 | arXiv(7天) + GitHub(30天) + HuggingFace(14天) |
| **URL去重** | ✅ 完成 | 查询飞书Bitable，过滤已推送候选 |
| **规则预筛选** | ✅ 完成 | 过滤率目标70-90%（当前GitHub 100%过滤） |
| **LLM评分** | ✅ 完成 | GPT-4o评分，平均分6.81/10，月成本<$1 |
| **飞书存储** | ✅ 完成 | 主存储(Bitable) + SQLite降级备份 |
| **飞书通知** | ✅ 完成 | Webhook推送，完整reasoning显示 |
| **主流程编排** | ✅ 完成 | `src/main.py` 5步流程自动化 |
| **实用工具** | ✅ 完成 | 去重脚本 + 清空表格脚本 |

### 🔄 已知问题与待优化点

1. **GitHub候选100%被过滤**: stars阈值50过高，需降低到10并增加多维度检查
2. **时间过滤未启用**: 采集器未使用已定义的时间窗口常量
3. **PwC API失效**: 301永久重定向到HuggingFace，需移除
4. **缺少运维工具**: 无日志分析工具，排查问题不便
5. **评分权重待优化**: MGX适配度权重过低（10% → 20%）
6. **缺少版本跟踪**: 无法监控Benchmark更新和SOTA变化
7. **通知单一**: 仅文本通知，无卡片消息和交互按钮

---

## Phase 3: 核心优化

**目标**: 解决Phase 1-2遗留问题，提升系统稳定性和质量
**预计耗时**: 2-3天
**优先级**: 🔴 高（影响核心功能）

---

### Task 3.1: 移除Papers with Code采集器

**优先级**: 🔴 P0（最高优先级，立即执行）
**预计耗时**: 30分钟
**难度**: ⭐ (简单)

#### 问题诊断

Papers with Code API已永久301重定向到HuggingFace:
```
https://paperswithcode.com/api/v1/tasks/ → https://huggingface.co/papers/trending
```

当前状态：
- `src/collectors/pwc_collector.py` 存在但无法使用
- `src/main.py` 中仍然尝试实例化PwC采集器
- `src/common/constants.py` 中有大量PwC配置常量

#### 代码修改清单

**Step 1**: 删除采集器文件
```bash
rm src/collectors/pwc_collector.py
```

**Step 2**: 更新 `src/collectors/__init__.py`

找到：
```python
from src.collectors.arxiv_collector import ArxivCollector
from src.collectors.github_collector import GitHubCollector
from src.collectors.huggingface_collector import HuggingFaceCollector
from src.collectors.pwc_collector import PwCCollector

__all__ = [
    "ArxivCollector",
    "GitHubCollector",
    "HuggingFaceCollector",
    "PwCCollector",
]
```

改为：
```python
from src.collectors.arxiv_collector import ArxivCollector
from src.collectors.github_collector import GitHubCollector
from src.collectors.huggingface_collector import HuggingFaceCollector

__all__ = [
    "ArxivCollector",
    "GitHubCollector",
    "HuggingFaceCollector",
]
```

**Step 3**: 更新 `src/main.py`

找到：
```python
from src.collectors import ArxivCollector, GitHubCollector, HuggingFaceCollector, PwCCollector

collectors = [
    ArxivCollector(),
    GitHubCollector(),
    PwCCollector(),
    HuggingFaceCollector(settings=settings),
]
```

改为：
```python
from src.collectors import ArxivCollector, GitHubCollector, HuggingFaceCollector

collectors = [
    ArxivCollector(),
    GitHubCollector(),
    HuggingFaceCollector(settings=settings),
]
```

**Step 4**: 清理 `src/common/constants.py`

删除所有PwC相关常量（通常在文件中搜索"PWC_"）：
```python
# 删除以下所有行:
PWC_API_BASE: Final[str] = "https://paperswithcode.com/api/v1"
PWC_TIMEOUT_SECONDS: Final[int] = 15
PWC_QUERY_KEYWORDS: Final[list[str]] = ["coding", "agent", "reasoning"]
PWC_MIN_TASK_PAPERS: Final[int] = 3
PWC_PAGE_SIZE: Final[int] = 20
```

#### 验收标准

```bash
# 1. 运行pipeline，不应看到PwC相关错误
python src/main.py 2>&1 | grep -i "pwc"

# 预期输出: 无输出（或只有采集完成的日志，但无PwC错误）

# 2. 检查文件是否已删除
ls src/collectors/pwc_collector.py

# 预期输出: ls: cannot access 'src/collectors/pwc_collector.py': No such file or directory

# 3. 检查导入是否成功
python -c "from src.collectors import ArxivCollector, GitHubCollector, HuggingFaceCollector"

# 预期输出: 无报错
```

#### Commit格式

```bash
git add src/collectors/__init__.py src/main.py src/common/constants.py
git commit -m "feat(collectors): 移除Papers with Code采集器

- PwC API已永久301重定向到HuggingFace
- 删除pwc_collector.py及相关配置常量
- 更新collectors/__init__.py和main.py导入
- 数据源简化为arXiv + GitHub + HuggingFace"
```

---

### Task 3.2: 优化GitHub预筛选规则

**优先级**: 🔴 P0（解决100%过滤问题）
**预计耗时**: 1-2小时
**难度**: ⭐⭐ (中等)

#### 问题诊断

**当前问题**:
```python
# src/common/constants.py
PREFILTER_MIN_GITHUB_STARS: Final[int] = 50  # 过高，导致100%过滤

# 实际情况:
# - GitHub采集器已按stars排序，只取Top 5
# - 再用50 stars过滤导致大量有价值repo被过滤
# - 测试显示：16个采集候选 → 0个通过预筛选（100%过滤率）
```

**根本原因**:
1. GitHub采集器返回的是Top 5热门repo，stars通常>100
2. 但是新兴Benchmark可能stars较少（10-50范围）
3. 单一stars指标不足以判断质量

**解决方案**:
1. 降低stars阈值: `50 → 10`
2. 增加README长度检查: `>500字符`（避免空repo）
3. 增加最近更新检查: `90天内有commit`（避免废弃repo）

#### 代码修改清单

**Step 1**: 修改 `src/common/constants.py`

找到预筛选配置部分（通常在"# ---- Prefilter 配置 ----"注释下）：
```python
# ---- Prefilter 配置 ----
PREFILTER_MIN_GITHUB_STARS: Final[int] = 50
```

修改为：
```python
# ---- Prefilter 配置 ----
PREFILTER_MIN_GITHUB_STARS: Final[int] = 10  # 降低到10 stars（新兴Benchmark可能stars较少）
PREFILTER_MIN_README_LENGTH: Final[int] = 500  # README最少500字符（避免空repo）
PREFILTER_RECENT_DAYS: Final[int] = 90  # 90天内有更新（避免废弃repo）
```

**Step 2**: 修改 `src/prefilter/rule_filter.py`

找到 `_is_quality_github_repo` 方法（可能在RuleFilter类中），当前实现可能只检查stars：

```python
def _is_quality_github_repo(self, candidate: RawCandidate) -> bool:
    """GitHub仓库质量检查"""
    stars = candidate.github_stars or 0
    if stars < constants.PREFILTER_MIN_GITHUB_STARS:
        logger.debug(f"GitHub stars不足: {candidate.title} ({stars})")
        return False
    return True
```

完全替换为多维度检查版本：

```python
def _is_quality_github_repo(self, candidate: RawCandidate) -> bool:
    """GitHub仓库质量检查（多维度）

    检查维度:
    1. Stars数量: 至少10个（新兴Benchmark可能较少）
    2. 最近更新: 90天内有活动（避免废弃项目）
    3. README长度: 至少500字符（避免空repo或占位项目）
    """
    from datetime import datetime, timedelta, timezone

    # 1. Stars检查（降低阈值到10）
    stars = candidate.github_stars or 0
    if stars < constants.PREFILTER_MIN_GITHUB_STARS:
        logger.debug(
            f"GitHub stars不足: {candidate.title} "
            f"({stars} < {constants.PREFILTER_MIN_GITHUB_STARS})"
        )
        return False

    # 2. 最近更新检查（90天内）
    if candidate.publish_date:
        now = datetime.now(timezone.utc)
        days_since_update = (now - candidate.publish_date).days

        if days_since_update > constants.PREFILTER_RECENT_DAYS:
            logger.debug(
                f"GitHub更新时间过久: {candidate.title} "
                f"({days_since_update}天前，超过{constants.PREFILTER_RECENT_DAYS}天阈值)"
            )
            return False

    # 3. README长度检查（避免空repo）
    abstract_length = len(candidate.abstract or "")
    if abstract_length < constants.PREFILTER_MIN_README_LENGTH:
        logger.debug(
            f"GitHub README过短: {candidate.title} "
            f"({abstract_length}字符 < {constants.PREFILTER_MIN_README_LENGTH})"
        )
        return False

    logger.debug(
        f"GitHub仓库通过预筛选: {candidate.title} "
        f"(stars={stars}, 更新={days_since_update if candidate.publish_date else 'N/A'}天前, "
        f"README={abstract_length}字符)"
    )
    return True
```

**注意事项**:
- 如果 `_is_quality_github_repo` 方法不存在，需要在 `RuleFilter` 类中新增
- 如果 `apply` 方法中没有调用GitHub检查，需要添加调用逻辑：
  ```python
  if candidate.source == "github":
      if not self._is_quality_github_repo(candidate):
          continue
  ```

#### 验收标准

```bash
# 1. 运行pipeline并检查预筛选结果
python src/main.py 2>&1 | grep -A5 "预筛选完成"

# 预期输出示例:
# 预筛选完成: 保留5条 (过滤率75.0%)
#
# 其中:
# - 过滤率应该在 70-90% 范围（不再是100%）
# - 应该有 1-5 条GitHub候选通过

# 2. 检查详细日志（调试模式）
python src/main.py 2>&1 | grep "GitHub" | grep -E "(通过预筛选|stars不足|更新时间过久|README过短)"

# 预期: 看到具体的过滤原因和通过的候选
```

#### Commit格式

```bash
git add src/common/constants.py src/prefilter/rule_filter.py
git commit -m "feat(prefilter): 优化GitHub预筛选规则，解决100%过滤问题

- 降低stars阈值: 50 → 10 (新兴Benchmark可能stars较少)
- 增加README长度检查: ≥500字符 (避免空repo)
- 增加最近更新检查: 90天内有活动 (避免废弃项目)
- 多维度质量评估替代单一stars指标
- 预期GitHub候选通过率: 10-30%"
```

---

### Task 3.3: 实现时间窗口过滤

**优先级**: 🟡 P1（优化采集效率）
**预计耗时**: 1-2小时
**难度**: ⭐⭐ (中等)

#### 问题诊断

**当前状态**:
- `src/common/constants.py` 已定义时间窗口常量:
  - `GITHUB_LOOKBACK_DAYS = 30`
  - `HUGGINGFACE_LOOKBACK_DAYS = 14`
- **但采集器未使用这些常量**，导致采集所有历史数据

**影响**:
- GitHub采集可能返回几个月前的repo（已过时）
- HuggingFace采集返回大量旧数据集（增加评分成本）
- 无法保证"日更"策略的时效性

#### 代码修改清单

**Step 1**: 修改 `src/collectors/github_collector.py`

找到 `_fetch_topic` 方法（构建GitHub搜索query的地方）：

当前实现可能类似：
```python
async def _fetch_topic(self, client: httpx.AsyncClient, topic: str) -> List[RawCandidate]:
    """调用GitHub搜索API"""
    params = {
        "q": f"{topic} benchmark in:name,description,readme",
        "sort": "stars",
        "order": "desc",
        "per_page": self.per_page,
    }
    # ... 后续逻辑
```

修改为增加时间过滤：
```python
from datetime import datetime, timedelta, timezone

async def _fetch_topic(self, client: httpx.AsyncClient, topic: str) -> List[RawCandidate]:
    """调用GitHub搜索API（增加时间过滤）

    使用GitHub搜索语法 pushed:>YYYY-MM-DD 过滤最近更新的仓库
    """
    # 计算时间窗口（从constants中读取）
    lookback_date = datetime.now(timezone.utc) - timedelta(days=constants.GITHUB_LOOKBACK_DAYS)
    date_filter = lookback_date.strftime("%Y-%m-%d")  # 格式: 2025-10-14

    params = {
        "q": f"{topic} benchmark in:name,description,readme pushed:>{date_filter}",  # 增加时间过滤
        "sort": "stars",
        "order": "desc",
        "per_page": self.per_page,
    }

    logger.debug(
        f"GitHub搜索query: {params['q']} "
        f"(时间窗口: 最近{constants.GITHUB_LOOKBACK_DAYS}天)"
    )

    # ... 后续逻辑不变
```

**注意**: 确保在文件开头导入 `from src.common import constants`

**Step 2**: 修改 `src/collectors/huggingface_collector.py`

找到 `collect` 方法（主采集逻辑）：

当前实现可能在最后直接返回 `all_candidates`：
```python
async def collect(self) -> List[RawCandidate]:
    """采集HuggingFace数据集"""
    all_candidates = []

    # ... 采集逻辑 ...

    logger.info("HuggingFace采集完成,候选数%d", len(all_candidates))
    return all_candidates
```

修改为增加时间过滤后处理：
```python
from datetime import datetime, timedelta, timezone

async def collect(self) -> List[RawCandidate]:
    """采集HuggingFace数据集（增加时间过滤）

    采集后根据publish_date过滤，只保留最近N天的数据集
    """
    all_candidates = []

    # ... 原有采集逻辑 ...

    # 时间窗口过滤（采集后处理）
    lookback_date = datetime.now(timezone.utc) - timedelta(days=constants.HUGGINGFACE_LOOKBACK_DAYS)

    filtered_candidates = []
    for candidate in all_candidates:
        if candidate.publish_date and candidate.publish_date >= lookback_date:
            filtered_candidates.append(candidate)
        else:
            # 记录被过滤的候选（调试用）
            if candidate.publish_date:
                days_old = (datetime.now(timezone.utc) - candidate.publish_date).days
                logger.debug(
                    f"HuggingFace过滤旧数据集: {candidate.title} "
                    f"(发布于{days_old}天前，超过{constants.HUGGINGFACE_LOOKBACK_DAYS}天窗口)"
                )

    logger.info(
        "HuggingFace采集完成: 原始%d条 → 时间过滤后%d条 (窗口: %d天)",
        len(all_candidates),
        len(filtered_candidates),
        constants.HUGGINGFACE_LOOKBACK_DAYS,
    )
    return filtered_candidates
```

**注意**:
- 确保在文件开头导入 `from src.common import constants`
- HuggingFace API可能不支持直接的时间过滤，所以采用后处理方式

#### 验收标准

```bash
# 1. 运行pipeline，检查采集日志
python src/main.py 2>&1 | grep -E "(GitHub|HuggingFace)采集完成"

# 预期输出示例:
# GitHubCollector采集完成: 8条 (时间窗口: 最近30天)
# HuggingFace采集完成: 原始25条 → 时间过滤后12条 (窗口: 14天)

# 2. 对比修改前后的采集数量
# 预期: 修改后采集数量应该减少（只采集最近N天的数据）

# 3. 检查时间过滤是否生效
python src/main.py 2>&1 | grep "时间窗口"

# 预期: 看到时间窗口相关的日志
```

#### Commit格式

```bash
git add src/collectors/github_collector.py src/collectors/huggingface_collector.py
git commit -m "feat(collectors): 实现时间窗口过滤

- GitHub: 使用pushed:>date语法过滤30天内更新的仓库
- HuggingFace: 采集后过滤14天内的数据集
- 提升数据时效性，减少无效采集和评分成本
- 支持日更策略，避免重复处理历史数据"
```

---

### Task 3.4: 创建日志分析工具

**优先级**: 🟢 P2（运维辅助工具）
**预计耗时**: 1小时
**难度**: ⭐ (简单)

#### 需求说明

创建 `scripts/analyze_logs.py`，用于分析每日采集效果，输出格式化报告。

**功能需求**:
1. 解析日志文件，提取关键统计数据
2. 生成美观的文本报告
3. 支持命令行参数指定日志文件

**统计维度**:
- 采集统计: 各数据源采集数量
- 去重统计: 重复过滤、新发现数量
- 预筛选统计: 输出数量、过滤率
- 评分统计: 平均分
- 优先级统计: 高/中/低优先级数量

#### 完整代码实现

**文件**: `scripts/analyze_logs.py`

```python
"""日志分析工具

解析BenchScope日志文件，生成格式化的统计报告

用法:
    python scripts/analyze_logs.py logs/benchscope.log
    python scripts/analyze_logs.py logs/test_20251113_143022.log

输出示例:
    ============================================================
    BenchScope 日志分析报告
    ============================================================

    ## 数据采集
      ArxivCollector: 12条
      GitHubCollector: 8条
      HuggingFaceCollector: 15条

    ## 去重
      重复过滤: 3条
      新发现: 32条

    ## 预筛选
      输出: 8条
      过滤率: 75.0%

    ## 评分
      平均分: 6.81/10

    ## 优先级
      高: 2条
      中: 5条
      低: 1条

    ============================================================
"""
import re
import sys
from collections import defaultdict
from pathlib import Path


def parse_log_file(log_path: Path) -> dict:
    """解析日志文件，提取统计数据

    Args:
        log_path: 日志文件路径

    Returns:
        包含各维度统计数据的字典
    """
    stats = {
        "采集统计": {},
        "去重统计": {},
        "预筛选统计": {},
        "评分统计": {},
        "优先级统计": {},
    }

    with open(log_path, encoding="utf-8") as f:
        for line in f:
            # 采集统计: 匹配 "✓ ArxivCollector: 12条"
            if match := re.search(r"✓ (\w+Collector): (\d+)条", line):
                collector, count = match.groups()
                stats["采集统计"][collector] = int(count)

            # 去重统计: 匹配 "去重完成: 过滤3条重复,保留32条新发现"
            if match := re.search(r"去重完成: 过滤(\d+)条重复,保留(\d+)条新发现", line):
                duplicate, new = match.groups()
                stats["去重统计"] = {"重复": int(duplicate), "新发现": int(new)}

            # 预筛选统计: 匹配 "预筛选完成: 保留8条 (过滤率75.0%)"
            if match := re.search(r"预筛选完成: 保留(\d+)条 \(过滤率([\d.]+)%\)", line):
                output, filter_rate = match.groups()
                stats["预筛选统计"] = {"输出": int(output), "过滤率": float(filter_rate)}

            # 评分统计: 匹配 "平均分: 6.81/10"
            if match := re.search(r"平均分: ([\d.]+)/10", line):
                stats["评分统计"]["平均分"] = float(match.group(1))

            # 优先级统计: 匹配 "高优先级: 2条" "中优先级: 5条" "低优先级: 1条"
            if match := re.search(r"(高|中|低)优先级: (\d+)条", line):
                priority, count = match.groups()
                stats["优先级统计"][priority] = int(count)

    return stats


def generate_report(stats: dict) -> str:
    """生成格式化报告

    Args:
        stats: 统计数据字典

    Returns:
        格式化的报告字符串
    """
    lines = [
        "=" * 60,
        "BenchScope 日志分析报告",
        "=" * 60,
        "",
    ]

    # 数据采集
    if stats["采集统计"]:
        lines.append("## 数据采集")
        for collector, count in stats["采集统计"].items():
            lines.append(f"  {collector}: {count}条")
        lines.append("")

    # 去重
    if stats["去重统计"]:
        lines.extend([
            "## 去重",
            f"  重复过滤: {stats['去重统计']['重复']}条",
            f"  新发现: {stats['去重统计']['新发现']}条",
            "",
        ])

    # 预筛选
    if stats["预筛选统计"]:
        lines.extend([
            "## 预筛选",
            f"  输出: {stats['预筛选统计']['输出']}条",
            f"  过滤率: {stats['预筛选统计']['过滤率']:.1f}%",
            "",
        ])

    # 评分
    if stats["评分统计"]:
        avg_score = stats["评分统计"].get("平均分", 0)
        lines.extend([
            "## 评分",
            f"  平均分: {avg_score:.2f}/10",
            "",
        ])

    # 优先级
    if stats["优先级统计"]:
        lines.append("## 优先级")
        for priority in ["高", "中", "低"]:
            if priority in stats["优先级统计"]:
                count = stats["优先级统计"][priority]
                lines.append(f"  {priority}: {count}条")
        lines.append("")

    lines.extend(["=" * 60])
    return "\n".join(lines)


def main():
    """主函数：解析命令行参数并执行分析"""
    if len(sys.argv) < 2:
        print("用法: python scripts/analyze_logs.py <日志文件>")
        print("\n示例:")
        print("  python scripts/analyze_logs.py logs/benchscope.log")
        print("  python scripts/analyze_logs.py logs/test_20251113_143022.log")
        sys.exit(1)

    log_path = Path(sys.argv[1])
    if not log_path.exists():
        print(f"错误: 日志文件不存在 - {log_path}")
        sys.exit(1)

    # 解析日志并生成报告
    stats = parse_log_file(log_path)
    report = generate_report(stats)
    print(report)


if __name__ == "__main__":
    main()
```

#### 验收标准

```bash
# 1. 测试脚本语法
python -m py_compile scripts/analyze_logs.py

# 预期: 无输出（编译成功）

# 2. 测试帮助信息
python scripts/analyze_logs.py

# 预期输出:
# 用法: python scripts/analyze_logs.py <日志文件>
#
# 示例:
#   python scripts/analyze_logs.py logs/benchscope.log
#   python scripts/analyze_logs.py logs/test_20251113_143022.log

# 3. 运行真实日志分析
python src/main.py 2>&1 | tee logs/test_$(date +%Y%m%d_%H%M%S).log
python scripts/analyze_logs.py logs/test_*.log

# 预期: 输出格式化的统计报告（如文档开头示例所示）

# 4. 测试不存在的文件
python scripts/analyze_logs.py logs/nonexistent.log

# 预期输出:
# 错误: 日志文件不存在 - logs/nonexistent.log
```

#### Commit格式

```bash
git add scripts/analyze_logs.py
git commit -m "feat(scripts): 创建日志分析工具

- 解析pipeline日志文件，提取关键统计数据
- 生成格式化报告：采集/去重/预筛选/评分/优先级
- 支持命令行参数指定日志文件
- 用于每日运行效果分析和问题排查"
```

---

### Task 3.5: 调整评分权重（可选）

**优先级**: 🟢 P3（可选，根据实际效果决定）
**预计耗时**: 30分钟
**难度**: ⭐ (简单)

#### 问题诊断

**当前权重**:
```
活跃度:     25%  (GitHub stars/commits)
可复现性:   30%  (代码/数据开源状态)
许可合规:   20%  (MIT/Apache/BSD)
任务新颖性: 15%  (与已有任务相似度)
MGX适配度:  10%  (与MetaGPT业务相关性)
```

**潜在问题**:
- 活跃度25%权重过高（GitHub stars波动大，新项目不公平）
- MGX适配度10%权重过低（这是核心业务相关性指标）

**建议调整**:
```
活跃度:     25% → 20%  (降低5%)
可复现性:   30% → 30%  (保持)
许可合规:   20% → 15%  (降低5%)
任务新颖性: 15% → 15%  (保持)
MGX适配度:  10% → 20%  (提高10%)
```

#### 代码修改清单

**文件**: `src/scorer/llm_scorer.py`

找到 `_build_prompt` 方法中的评分维度说明部分：

当前可能类似：
```python
请基于以下维度评分(0-10分):

1. 活跃度(25%): GitHub stars/近期commits/社区参与度
2. 可复现性(30%): 代码/数据集开源状态,复现文档完整性
3. 许可合规(20%): MIT/Apache/BSD等商业友好许可
4. 任务新颖性(15%): 与已有Benchmark的差异度,创新性
5. MGX适配度(10%): 与MetaGPT多agent/代码生成/工具使用的相关性
```

修改为：
```python
请基于以下维度评分(0-10分):

1. 活跃度(20%): GitHub stars/近期commits/社区参与度
   - 考虑项目成熟度，但不过分惩罚新项目

2. 可复现性(30%): 代码/数据集开源状态,复现文档完整性
   - 开源代码库、公开数据集、详细文档优先

3. 许可合规(15%): MIT/Apache/BSD等商业友好许可
   - 商业友好许可加分，GPL等限制性许可减分

4. 任务新颖性(15%): 与已有Benchmark的差异度,创新性
   - 填补现有Benchmark空白的任务加分

5. MGX适配度(20%): 与MetaGPT多agent/代码生成/工具使用的相关性
   - 重点关注：多agent协作、代码生成、Web/GUI交互、工具使用
   - 这是核心业务相关性指标，权重提高到20%
```

**注意**:
- 如果prompt中还有权重计算公式，也需要同步更新：
  ```python
  total_score = (
      activity_score * 0.20 +
      reproducibility_score * 0.30 +
      license_score * 0.15 +
      novelty_score * 0.15 +
      relevance_score * 0.20
  )
  ```

#### 重要提醒

**权重调整会影响历史评分的可比性**:
1. 修改前的候选（总分基于旧权重）
2. 修改后的候选（总分基于新权重）
3. 两者分数不能直接对比

**建议策略**:
- **Option A（推荐）**: 清空Redis缓存，重新评分所有候选
  ```bash
  redis-cli FLUSHALL
  ```
- **Option B**: 在飞书表格中增加"评分版本"字段，标记v1/v2

#### 验收标准

```bash
# 1. 清空Redis缓存（如果执行Option A）
redis-cli FLUSHALL

# 预期输出: OK

# 2. 运行pipeline，检查平均分变化
python src/main.py 2>&1 | grep "平均分"

# 预期:
# - MGX相关候选（如multi-agent benchmark）分数应该提升
# - 活跃度一般但MGX相关性高的候选分数应该提升

# 3. 对比修改前后的评分结果
# 手动检查几个典型候选的分数变化
```

#### Commit格式

```bash
git add src/scorer/llm_scorer.py
git commit -m "feat(scorer): 调整评分权重，提升MGX适配度重要性

- 活跃度: 25% → 20% (降低对新项目的惩罚)
- 许可合规: 20% → 15% (降低许可证权重)
- MGX适配度: 10% → 20% (提升核心业务相关性权重)
- 更加重视多agent/代码生成/工具使用相关的Benchmark
- 注意: 需清空Redis缓存重新评分"
```

---

### Phase 3 总结测试

**完成所有Task后，执行以下测试**:

```bash
# 1. 激活环境
source .venv/bin/activate
export PYTHONPATH=.

# 2. 清空Redis缓存（如果修改了评分权重）
redis-cli FLUSHALL

# 3. 清空飞书表格（可选，重新开始）
python scripts/clear_feishu_table.py

# 4. 运行完整pipeline
python src/main.py 2>&1 | tee logs/phase3_test_$(date +%Y%m%d_%H%M%S).log

# 5. 分析日志
python scripts/analyze_logs.py logs/phase3_test_*.log

# 6. 检查关键指标
grep "GitHub" logs/phase3_test_*.log | grep -E "(采集|预筛选)"
```

**预期结果**:
- ✅ GitHub采集数量: 5-15条（30天窗口）
- ✅ GitHub预筛选通过: 1-5条（10-30%通过率，不再是100%）
- ✅ 无PwC错误日志
- ✅ 日志分析工具正常输出
- ✅ 平均分在合理范围（6-8分）

---

## Phase 4: 版本跟踪

**目标**: 监控已入库Benchmark的更新，及时推送版本变化
**预计耗时**: 3-4天
**优先级**: 🟡 中（价值高但非紧急）

---

### Task 4.1: GitHub Release监控

**优先级**: 🟡 P1
**预计耗时**: 2-3小时
**难度**: ⭐⭐⭐ (中高)

#### 需求说明

监控已入库的GitHub仓库，当有新Release时推送通知。

**功能需求**:
1. 从飞书Bitable读取所有GitHub类型的候选
2. 查询GitHub API获取最新Release信息
3. 对比本地存储的版本，识别新Release
4. 推送飞书通知（标题+版本号+更新说明）

**数据模型**:
需要在SQLite中新增表 `github_releases`:
```sql
CREATE TABLE github_releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_url TEXT NOT NULL,          -- GitHub仓库URL
    tag_name TEXT NOT NULL,          -- Release tag (e.g., v1.2.0)
    published_at TIMESTAMP NOT NULL, -- 发布时间
    release_notes TEXT,              -- Release说明
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(repo_url, tag_name)       -- 同一repo+tag唯一
);
```

#### 代码实现清单

**Step 1**: 创建数据模型 `src/models.py`

在文件末尾增加：
```python
@dataclass
class GitHubRelease:
    """GitHub Release版本信息"""
    repo_url: str                      # 仓库URL
    tag_name: str                      # 版本tag
    published_at: datetime             # 发布时间
    release_notes: str                 # Release说明
    html_url: str                      # Release页面URL
```

**Step 2**: 创建版本跟踪器 `src/tracker/github_tracker.py`

```python
"""GitHub Release版本跟踪器"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import httpx

from src.models import GitHubRelease

logger = logging.getLogger(__name__)


class GitHubReleaseTracker:
    """监控GitHub仓库的新Release"""

    def __init__(self, db_path: str = "fallback.db", github_token: str | None = None):
        """
        Args:
            db_path: SQLite数据库路径
            github_token: GitHub Personal Access Token (可选，提高API限额)
        """
        self.db_path = Path(db_path)
        self.github_token = github_token
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS github_releases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_url TEXT NOT NULL,
                    tag_name TEXT NOT NULL,
                    published_at TIMESTAMP NOT NULL,
                    release_notes TEXT,
                    html_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(repo_url, tag_name)
                )
            """)
            conn.commit()
        logger.info("GitHub Release跟踪数据库初始化完成")

    def _extract_owner_repo(self, github_url: str) -> tuple[str, str] | None:
        """从GitHub URL提取owner和repo名称

        支持格式:
        - https://github.com/owner/repo
        - https://github.com/owner/repo.git
        - github.com/owner/repo

        Returns:
            (owner, repo) 或 None
        """
        pattern = r"github\.com/([^/]+)/([^/\.]+)"
        if match := re.search(pattern, github_url):
            return match.group(1), match.group(2)
        return None

    async def fetch_latest_release(self, repo_url: str) -> GitHubRelease | None:
        """查询GitHub仓库的最新Release

        Args:
            repo_url: GitHub仓库URL

        Returns:
            最新Release对象，如果无Release则返回None
        """
        if not (pair := self._extract_owner_repo(repo_url)):
            logger.warning(f"无法解析GitHub URL: {repo_url}")
            return None

        owner, repo = pair
        api_url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"

        headers = {"Accept": "application/vnd.github+json"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(api_url, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                return GitHubRelease(
                    repo_url=repo_url,
                    tag_name=data["tag_name"],
                    published_at=datetime.fromisoformat(data["published_at"].replace("Z", "+00:00")),
                    release_notes=data.get("body", "")[:1000],  # 限制1000字符
                    html_url=data["html_url"],
                )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                logger.debug(f"仓库无Release: {repo_url}")
            else:
                logger.warning(f"查询GitHub Release失败: {repo_url} - {exc}")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.error(f"查询GitHub Release异常: {repo_url} - {exc}")
            return None

    def is_new_release(self, release: GitHubRelease) -> bool:
        """检查Release是否为新版本（未记录过）"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM github_releases WHERE repo_url = ? AND tag_name = ?",
                (release.repo_url, release.tag_name),
            )
            count = cursor.fetchone()[0]
            return count == 0

    def save_release(self, release: GitHubRelease):
        """保存Release到数据库"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO github_releases
                (repo_url, tag_name, published_at, release_notes, html_url)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    release.repo_url,
                    release.tag_name,
                    release.published_at.isoformat(),
                    release.release_notes,
                    release.html_url,
                ),
            )
            conn.commit()
        logger.info(f"保存GitHub Release: {release.repo_url} - {release.tag_name}")

    async def check_updates(self, repo_urls: List[str]) -> List[GitHubRelease]:
        """检查多个仓库的更新

        Args:
            repo_urls: GitHub仓库URL列表

        Returns:
            新Release列表
        """
        new_releases = []

        for repo_url in repo_urls:
            logger.debug(f"检查GitHub仓库: {repo_url}")
            release = await self.fetch_latest_release(repo_url)

            if release and self.is_new_release(release):
                logger.info(f"发现新Release: {repo_url} - {release.tag_name}")
                self.save_release(release)
                new_releases.append(release)

        logger.info(f"GitHub Release检查完成: 共{len(repo_urls)}个仓库, 发现{len(new_releases)}个新版本")
        return new_releases
```

**Step 3**: 创建跟踪任务脚本 `scripts/track_github_releases.py`

```python
"""GitHub Release版本跟踪任务

从飞书Bitable读取所有GitHub仓库，检查新Release并推送通知

用法:
    python scripts/track_github_releases.py
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings
from src.notifier import FeishuNotifier
from src.storage import StorageManager
from src.tracker.github_tracker import GitHubReleaseTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    settings = get_settings()

    # 1. 从飞书Bitable读取所有GitHub候选
    logger.info("从飞书Bitable读取GitHub仓库列表...")
    storage = StorageManager()
    existing_urls = await storage.get_existing_urls()

    github_urls = [url for url in existing_urls if "github.com" in url]
    logger.info(f"找到{len(github_urls)}个GitHub仓库")

    if not github_urls:
        logger.info("无GitHub仓库需要跟踪")
        return

    # 2. 检查新Release
    logger.info("检查GitHub Release更新...")
    github_token = settings.github.token if hasattr(settings, "github") else None
    tracker = GitHubReleaseTracker(github_token=github_token)
    new_releases = await tracker.check_updates(github_urls)

    if not new_releases:
        logger.info("无新Release")
        return

    # 3. 推送飞书通知
    logger.info(f"推送{len(new_releases)}个新Release通知...")
    notifier = FeishuNotifier(settings=settings)

    for release in new_releases:
        message = (
            f"**GitHub Release更新**\n\n"
            f"仓库: {release.repo_url}\n"
            f"版本: {release.tag_name}\n"
            f"发布时间: {release.published_at.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"**更新说明**:\n{release.release_notes[:500]}\n\n"
            f"[查看详情]({release.html_url})"
        )
        await notifier.send_text(message)

    logger.info("GitHub Release跟踪任务完成")


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 4**: 更新 `src/tracker/__init__.py`

```python
from src.tracker.github_tracker import GitHubReleaseTracker

__all__ = ["GitHubReleaseTracker"]
```

**Step 5**: 配置GitHub Actions定时任务

在 `.github/workflows/track_releases.yml` 创建：
```yaml
name: Track GitHub Releases

on:
  schedule:
    - cron: '0 10 * * *'  # 每天UTC 10:00 (北京时间18:00)
  workflow_dispatch:      # 支持手动触发

jobs:
  track:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Track GitHub Releases
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          FEISHU_APP_ID: ${{ secrets.FEISHU_APP_ID }}
          FEISHU_APP_SECRET: ${{ secrets.FEISHU_APP_SECRET }}
          FEISHU_BITABLE_APP_TOKEN: ${{ secrets.FEISHU_BITABLE_APP_TOKEN }}
          FEISHU_BITABLE_TABLE_ID: ${{ secrets.FEISHU_BITABLE_TABLE_ID }}
          FEISHU_WEBHOOK_URL: ${{ secrets.FEISHU_WEBHOOK_URL }}
          GITHUB_TOKEN: ${{ secrets.GH_PAT }}  # GitHub Personal Access Token
        run: |
          python scripts/track_github_releases.py
```

#### 验收标准

```bash
# 1. 创建测试数据（手动添加一个GitHub repo到飞书表格）

# 2. 运行跟踪脚本
python scripts/track_github_releases.py

# 预期输出:
# 从飞书Bitable读取GitHub仓库列表...
# 找到X个GitHub仓库
# 检查GitHub Release更新...
# 发现新Release: https://github.com/xxx/yyy - v1.2.0
# 推送1个新Release通知...
# GitHub Release跟踪任务完成

# 3. 检查飞书通知
# 预期: 收到包含版本号和更新说明的通知

# 4. 再次运行（应该无新Release）
python scripts/track_github_releases.py

# 预期输出:
# 无新Release
```

#### Commit格式

```bash
git add src/models.py src/tracker/ scripts/track_github_releases.py .github/workflows/track_releases.yml
git commit -m "feat(tracker): 实现GitHub Release版本跟踪

- 创建GitHubReleaseTracker跟踪器
- 从飞书Bitable读取GitHub仓库列表
- 查询GitHub API获取最新Release
- SQLite存储已通知的版本，避免重复
- 飞书推送新Release通知
- GitHub Actions定时任务（每日18:00）"
```

---

### Task 4.2: arXiv版本更新提醒

**优先级**: 🟢 P2
**预计耗时**: 1-2小时
**难度**: ⭐⭐ (中等)

#### 需求说明

arXiv论文可能有多个版本（v1, v2, v3...），监控已入库论文的版本更新。

**实现策略**:
1. 从飞书Bitable读取所有arXiv类型的候选
2. 提取arXiv ID（如 `2311.04355`）
3. 查询arXiv API获取最新版本号
4. 对比本地记录，识别版本更新
5. 推送飞书通知

**数据模型**:
SQLite新增表 `arxiv_versions`:
```sql
CREATE TABLE arxiv_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arxiv_id TEXT NOT NULL,            -- arXiv ID (e.g., 2311.04355)
    version TEXT NOT NULL,             -- 版本号 (e.g., v3)
    updated_at TIMESTAMP NOT NULL,     -- 更新时间
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(arxiv_id, version)
);
```

#### 代码实现清单

**Step 1**: 创建版本跟踪器 `src/tracker/arxiv_tracker.py`

```python
"""arXiv论文版本跟踪器"""
from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List

import feedparser

logger = logging.getLogger(__name__)


class ArxivVersionTracker:
    """监控arXiv论文的版本更新"""

    def __init__(self, db_path: str = "fallback.db"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS arxiv_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    arxiv_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(arxiv_id, version)
                )
            """)
            conn.commit()
        logger.info("arXiv版本跟踪数据库初始化完成")

    def _extract_arxiv_id(self, arxiv_url: str) -> str | None:
        """从arXiv URL提取ID

        支持格式:
        - https://arxiv.org/abs/2311.04355
        - http://arxiv.org/abs/2311.04355v1
        - arxiv.org/abs/2311.04355

        Returns:
            arXiv ID (e.g., 2311.04355) 或 None
        """
        pattern = r"arxiv\.org/abs/(\d{4}\.\d{4,5})"
        if match := re.search(pattern, arxiv_url):
            return match.group(1)
        return None

    async def fetch_latest_version(self, arxiv_id: str) -> dict | None:
        """查询arXiv论文的最新版本

        Args:
            arxiv_id: arXiv ID (e.g., 2311.04355)

        Returns:
            {'arxiv_id': str, 'version': str, 'updated': datetime, 'title': str} 或 None
        """
        query_url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"

        try:
            feed = feedparser.parse(query_url)

            if not feed.entries:
                logger.warning(f"未找到arXiv论文: {arxiv_id}")
                return None

            entry = feed.entries[0]
            arxiv_url = entry.id  # 格式: http://arxiv.org/abs/2311.04355v3

            # 提取版本号
            version_match = re.search(r"v(\d+)$", arxiv_url)
            version = f"v{version_match.group(1)}" if version_match else "v1"

            return {
                "arxiv_id": arxiv_id,
                "version": version,
                "updated": datetime.fromisoformat(entry.updated.replace("Z", "+00:00")),
                "title": entry.title,
            }
        except Exception as exc:  # noqa: BLE001
            logger.error(f"查询arXiv版本失败: {arxiv_id} - {exc}")
            return None

    def is_new_version(self, arxiv_id: str, version: str) -> bool:
        """检查版本是否为新版本（未记录过）"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM arxiv_versions WHERE arxiv_id = ? AND version = ?",
                (arxiv_id, version),
            )
            count = cursor.fetchone()[0]
            return count == 0

    def save_version(self, arxiv_id: str, version: str, updated_at: datetime):
        """保存版本到数据库"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO arxiv_versions
                (arxiv_id, version, updated_at)
                VALUES (?, ?, ?)
                """,
                (arxiv_id, version, updated_at.isoformat()),
            )
            conn.commit()
        logger.info(f"保存arXiv版本: {arxiv_id} - {version}")

    async def check_updates(self, arxiv_urls: List[str]) -> List[dict]:
        """检查多个论文的版本更新

        Args:
            arxiv_urls: arXiv论文URL列表

        Returns:
            新版本列表 [{'arxiv_id': str, 'version': str, 'updated': datetime, 'title': str}]
        """
        new_versions = []

        for url in arxiv_urls:
            arxiv_id = self._extract_arxiv_id(url)
            if not arxiv_id:
                logger.warning(f"无法解析arXiv URL: {url}")
                continue

            logger.debug(f"检查arXiv论文: {arxiv_id}")
            version_info = await self.fetch_latest_version(arxiv_id)

            if version_info and self.is_new_version(version_info["arxiv_id"], version_info["version"]):
                logger.info(f"发现新版本: {arxiv_id} - {version_info['version']}")
                self.save_version(arxiv_id, version_info["version"], version_info["updated"])
                new_versions.append(version_info)

        logger.info(f"arXiv版本检查完成: 共{len(arxiv_urls)}篇论文, 发现{len(new_versions)}个新版本")
        return new_versions
```

**Step 2**: 创建跟踪任务脚本 `scripts/track_arxiv_versions.py`

```python
"""arXiv论文版本跟踪任务

从飞书Bitable读取所有arXiv论文，检查版本更新并推送通知

用法:
    python scripts/track_arxiv_versions.py
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings
from src.notifier import FeishuNotifier
from src.storage import StorageManager
from src.tracker.arxiv_tracker import ArxivVersionTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    settings = get_settings()

    # 1. 从飞书Bitable读取所有arXiv候选
    logger.info("从飞书Bitable读取arXiv论文列表...")
    storage = StorageManager()
    existing_urls = await storage.get_existing_urls()

    arxiv_urls = [url for url in existing_urls if "arxiv.org" in url]
    logger.info(f"找到{len(arxiv_urls)}篇arXiv论文")

    if not arxiv_urls:
        logger.info("无arXiv论文需要跟踪")
        return

    # 2. 检查版本更新
    logger.info("检查arXiv版本更新...")
    tracker = ArxivVersionTracker()
    new_versions = await tracker.check_updates(arxiv_urls)

    if not new_versions:
        logger.info("无新版本")
        return

    # 3. 推送飞书通知
    logger.info(f"推送{len(new_versions)}个版本更新通知...")
    notifier = FeishuNotifier(settings=settings)

    for version_info in new_versions:
        message = (
            f"**arXiv论文版本更新**\n\n"
            f"标题: {version_info['title']}\n"
            f"arXiv ID: {version_info['arxiv_id']}\n"
            f"新版本: {version_info['version']}\n"
            f"更新时间: {version_info['updated'].strftime('%Y-%m-%d %H:%M')}\n\n"
            f"[查看论文](https://arxiv.org/abs/{version_info['arxiv_id']})"
        )
        await notifier.send_text(message)

    logger.info("arXiv版本跟踪任务完成")


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 3**: 更新 `src/tracker/__init__.py`

```python
from src.tracker.arxiv_tracker import ArxivVersionTracker
from src.tracker.github_tracker import GitHubReleaseTracker

__all__ = ["ArxivVersionTracker", "GitHubReleaseTracker"]
```

**Step 4**: 更新GitHub Actions工作流（合并到同一个文件）

修改 `.github/workflows/track_releases.yml`:
```yaml
name: Track Updates

on:
  schedule:
    - cron: '0 10 * * *'  # 每天UTC 10:00 (北京时间18:00)
  workflow_dispatch:

jobs:
  track:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Track GitHub Releases
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          FEISHU_APP_ID: ${{ secrets.FEISHU_APP_ID }}
          FEISHU_APP_SECRET: ${{ secrets.FEISHU_APP_SECRET }}
          FEISHU_BITABLE_APP_TOKEN: ${{ secrets.FEISHU_BITABLE_APP_TOKEN }}
          FEISHU_BITABLE_TABLE_ID: ${{ secrets.FEISHU_BITABLE_TABLE_ID }}
          FEISHU_WEBHOOK_URL: ${{ secrets.FEISHU_WEBHOOK_URL }}
          GITHUB_TOKEN: ${{ secrets.GH_PAT }}
        run: |
          python scripts/track_github_releases.py

      - name: Track arXiv Versions
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          FEISHU_APP_ID: ${{ secrets.FEISHU_APP_ID }}
          FEISHU_APP_SECRET: ${{ secrets.FEISHU_APP_SECRET }}
          FEISHU_BITABLE_APP_TOKEN: ${{ secrets.FEISHU_BITABLE_APP_TOKEN }}
          FEISHU_BITABLE_TABLE_ID: ${{ secrets.FEISHU_BITABLE_TABLE_ID }}
          FEISHU_WEBHOOK_URL: ${{ secrets.FEISHU_WEBHOOK_URL }}
        run: |
          python scripts/track_arxiv_versions.py
```

#### 验收标准

```bash
# 1. 运行跟踪脚本
python scripts/track_arxiv_versions.py

# 预期输出:
# 从飞书Bitable读取arXiv论文列表...
# 找到X篇arXiv论文
# 检查arXiv版本更新...
# 发现新版本: 2311.04355 - v2
# 推送1个版本更新通知...
# arXiv版本跟踪任务完成

# 2. 检查飞书通知
# 预期: 收到包含版本号和更新时间的通知

# 3. 再次运行（应该无新版本）
python scripts/track_arxiv_versions.py

# 预期输出:
# 无新版本
```

#### Commit格式

```bash
git add src/tracker/arxiv_tracker.py scripts/track_arxiv_versions.py .github/workflows/track_releases.yml
git commit -m "feat(tracker): 实现arXiv论文版本跟踪

- 创建ArxivVersionTracker跟踪器
- 从飞书Bitable读取arXiv论文列表
- 查询arXiv API获取最新版本号
- SQLite存储已通知的版本，避免重复
- 飞书推送版本更新通知
- GitHub Actions定时任务（与Release跟踪合并）"
```

---

### Task 4.3: Leaderboard SOTA变化追踪（可选）

**优先级**: 🟢 P3（可选）
**预计耗时**: 2-3小时
**难度**: ⭐⭐⭐⭐ (高)

#### 需求说明

监控Benchmark排行榜（如Papers with Code Leaderboards）的SOTA变化。

**挑战**:
- 各Benchmark的Leaderboard格式不统一
- 需要定期爬取并对比分数变化
- 数据清洗和解析复杂度高

**建议实现方案**:
1. 从飞书Bitable读取候选的Leaderboard URL
2. 使用BeautifulSoup爬取排行榜数据
3. 提取Top 1的模型名称和分数
4. 对比上次记录，识别SOTA变化
5. 推送飞书通知

**由于时间和复杂度限制，建议Phase 5实现或单独立项**

---

## Phase 5: 增强功能

**目标**: 提升用户体验，增加交互功能
**预计耗时**: 2-3天
**优先级**: 🟢 低（锦上添花）

---

### Task 5.1: 飞书卡片消息替代文本通知

**优先级**: 🟢 P1
**预计耗时**: 2-3小时
**难度**: ⭐⭐⭐ (中高)

#### 需求说明

当前通知是简单文本，改为飞书卡片消息（更美观、支持按钮交互）。

**卡片消息示例**:
```json
{
  "msg_type": "interactive",
  "card": {
    "header": {
      "title": {
        "content": "🔥 发现高质量Benchmark候选",
        "tag": "plain_text"
      },
      "template": "blue"
    },
    "elements": [
      {
        "tag": "div",
        "text": {
          "content": "**标题**: BenchX - Code Generation Benchmark\n**来源**: arXiv\n**总分**: 8.5/10",
          "tag": "lark_md"
        }
      },
      {
        "tag": "action",
        "actions": [
          {
            "tag": "button",
            "text": {
              "content": "查看详情",
              "tag": "plain_text"
            },
            "url": "https://arxiv.org/abs/xxx",
            "type": "default"
          },
          {
            "tag": "button",
            "text": {
              "content": "✅ 加入候选池",
              "tag": "plain_text"
            },
            "value": {
              "action": "approve",
              "candidate_id": "xxx"
            },
            "type": "primary"
          }
        ]
      }
    ]
  }
}
```

#### 代码修改清单

**Step 1**: 修改 `src/notifier/feishu_notifier.py`

增加卡片消息方法：
```python
async def send_card(self, title: str, candidate: ScoredCandidate):
    """发送飞书卡片消息

    Args:
        title: 卡片标题
        candidate: 评分后的候选对象
    """
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"content": title, "tag": "plain_text"},
                "template": "blue" if candidate.priority == "high" else "green",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": (
                            f"**标题**: {candidate.title}\n"
                            f"**来源**: {candidate.source}\n"
                            f"**总分**: {candidate.total_score:.2f}/10\n"
                            f"**优先级**: {candidate.priority}"
                        ),
                        "tag": "lark_md",
                    },
                },
                {
                    "tag": "div",
                    "text": {
                        "content": f"**评分依据**:\n{candidate.reasoning[:300]}...",
                        "tag": "lark_md",
                    },
                },
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"content": "查看详情", "tag": "plain_text"},
                            "url": candidate.url,
                            "type": "default",
                        }
                    ],
                },
            ],
        },
    }

    await self._send_webhook(card)
```

修改 `notify` 方法：
```python
async def notify(self, candidates: List[ScoredCandidate]) -> None:
    """推送候选通知（卡片消息）"""
    if not candidates:
        return

    high_priority = [c for c in candidates if c.priority == "high"]

    # 推送高优先级候选（单独卡片）
    for candidate in high_priority[:3]:  # 限制最多3个
        await self.send_card("🔥 发现高质量Benchmark候选", candidate)
        await asyncio.sleep(0.5)  # 防止限流

    # 推送汇总通知
    summary = (
        f"本次采集完成:\n"
        f"- 高优先级: {len(high_priority)}条\n"
        f"- 中优先级: {len([c for c in candidates if c.priority == 'medium'])}条\n"
        f"- 平均分: {sum(c.total_score for c in candidates) / len(candidates):.2f}/10"
    )
    await self.send_text(summary)
```

#### 验收标准

```bash
# 运行pipeline
python src/main.py

# 预期: 飞书收到美观的卡片消息（带标题、评分、按钮）
```

#### Commit格式

```bash
git add src/notifier/feishu_notifier.py
git commit -m "feat(notifier): 飞书通知升级为卡片消息

- 替换简单文本通知为交互式卡片
- 卡片显示: 标题/来源/总分/优先级/评分依据
- 增加"查看详情"按钮跳转原文
- 优先级高的候选单独推送卡片
- 提升通知可读性和交互体验"
```

---

### Phase 5 其他可选任务

**Task 5.2**: 一键添加按钮 + Flask回调服务（需要部署Web服务，复杂度高）
**Task 5.3**: 候选池管理后台（Web界面，可视化管理，建议单独立项）
**Task 5.4**: 评分模型微调（基于人工反馈，长期迭代任务）

---

## 测试与验收流程

### 单元测试规范

**测试文件组织**:
```
tests/
├── unit/
│   ├── test_collectors.py      # 采集器测试
│   ├── test_prefilter.py        # 预筛选测试
│   ├── test_scorer.py           # 评分器测试
│   ├── test_storage.py          # 存储层测试
│   ├── test_notifier.py         # 通知器测试
│   └── test_tracker.py          # 跟踪器测试（新增）
└── integration/
    └── test_pipeline.py         # 完整流程测试
```

**测试命令**:
```bash
# 运行所有单元测试
pytest tests/unit/ -v

# 运行特定模块测试
pytest tests/unit/test_tracker.py -v

# 运行集成测试（需要真实API配置）
pytest tests/integration/ -v

# 测试覆盖率
pytest --cov=src --cov-report=html
```

### 集成测试流程

**完整Pipeline测试**:
```bash
# 1. 激活环境
source .venv/bin/activate
export PYTHONPATH=.

# 2. 清空Redis缓存
redis-cli FLUSHALL

# 3. 清空飞书表格（可选）
python scripts/clear_feishu_table.py

# 4. 运行完整pipeline
python src/main.py 2>&1 | tee logs/integration_test_$(date +%Y%m%d_%H%M%S).log

# 5. 分析日志
python scripts/analyze_logs.py logs/integration_test_*.log

# 6. 验证关键指标
grep -E "(采集|去重|预筛选|评分|存储|通知)" logs/integration_test_*.log
```

**预期结果**:
- ✅ 数据采集成功率 > 95%
- ✅ 去重功能正常（过滤已推送URL）
- ✅ GitHub预筛选通过率 10-30%（不再100%）
- ✅ LLM评分成功，平均分6-8/10
- ✅ 飞书存储成功，无降级到SQLite
- ✅ 飞书通知成功推送
- ✅ 执行时间 < 20分钟

### 手动验收检查清单

**Phase 3验收**:
- [ ] 运行pipeline无PwC错误日志
- [ ] GitHub采集数量合理（5-15条，30天窗口）
- [ ] GitHub预筛选通过1-5条（10-30%通过率）
- [ ] HuggingFace时间过滤生效（日志显示过滤数量）
- [ ] 日志分析工具正常输出报告
- [ ] 评分权重调整生效（MGX相关候选分数提升）

**Phase 4验收**:
- [ ] GitHub Release跟踪正常（检测到新版本）
- [ ] arXiv版本跟踪正常（检测到v2/v3更新）
- [ ] 飞书收到版本更新通知
- [ ] SQLite正确存储版本记录
- [ ] GitHub Actions定时任务运行成功

**Phase 5验收**:
- [ ] 飞书收到卡片消息（非文本）
- [ ] 卡片显示完整信息（标题/评分/按钮）
- [ ] 点击按钮跳转正确

---

## 代码规范与约束

### Python代码规范（强制执行）

1. **PEP8合规**:
   ```bash
   # 自动格式化
   black src/ tests/ scripts/

   # 代码检查
   ruff check src/ tests/ scripts/
   ```

2. **类型注解**:
   ```python
   # 好的例子
   def fetch_latest_release(self, repo_url: str) -> GitHubRelease | None:
       ...

   # 坏的例子
   def fetch_latest_release(self, repo_url):
       ...
   ```

3. **中文注释（关键逻辑必须）**:
   ```python
   # 好的例子
   # 计算时间窗口（从constants中读取）
   lookback_date = datetime.now(timezone.utc) - timedelta(days=constants.GITHUB_LOOKBACK_DAYS)

   # 坏的例子
   lookback_date = datetime.now(timezone.utc) - timedelta(days=constants.GITHUB_LOOKBACK_DAYS)  # 无注释
   ```

4. **常量定义（禁止魔法数字）**:
   ```python
   # 好的例子
   PREFILTER_MIN_GITHUB_STARS: Final[int] = 10
   if stars < constants.PREFILTER_MIN_GITHUB_STARS:
       ...

   # 坏的例子
   if stars < 10:  # 魔法数字
       ...
   ```

5. **函数嵌套层级（最多3层）**:
   ```python
   # 好的例子（使用early return）
   def validate(self, candidate):
       if not candidate.url:
           return False
       if not self._is_valid_source(candidate.source):
           return False
       return True

   # 坏的例子（嵌套过深）
   def validate(self, candidate):
       if candidate.url:
           if self._is_valid_source(candidate.source):
               if self._check_quality(candidate):
                   return True
       return False
   ```

### Git Commit规范

**格式**:
```
<type>(<scope>): <subject>

<body>

<footer>
```

**类型（type）**:
- `feat`: 新功能
- `fix`: Bug修复
- `refactor`: 重构（不改变功能）
- `perf`: 性能优化
- `docs`: 文档更新
- `test`: 测试相关
- `chore`: 构建/工具链更新

**范围（scope）**:
- `collectors`: 数据采集器
- `prefilter`: 预筛选引擎
- `scorer`: 评分引擎
- `storage`: 存储层
- `notifier`: 通知引擎
- `tracker`: 版本跟踪器
- `scripts`: 脚本工具

**示例**:
```bash
feat(tracker): 实现GitHub Release版本跟踪

- 创建GitHubReleaseTracker跟踪器
- 从飞书Bitable读取GitHub仓库列表
- 查询GitHub API获取最新Release
- SQLite存储已通知的版本，避免重复
- 飞书推送新Release通知
- GitHub Actions定时任务（每日18:00）

Closes #42
```

### 异常处理规范

```python
# 好的例子（具体异常+日志）
try:
    resp = await client.get(api_url)
    resp.raise_for_status()
except httpx.HTTPStatusError as exc:
    if exc.response.status_code == 404:
        logger.debug(f"仓库无Release: {repo_url}")
    else:
        logger.warning(f"查询失败: {repo_url} - {exc}")
    return None
except httpx.TimeoutException:
    logger.error(f"请求超时: {repo_url}")
    return None

# 坏的例子（通用异常+无日志）
try:
    resp = await client.get(api_url)
    resp.raise_for_status()
except Exception:
    return None
```

---

## 开发执行顺序建议

**Codex，请严格按照以下顺序执行开发任务**:

### Week 1: Phase 3核心优化

**Day 1**:
- [ ] Task 3.1: 移除PwC采集器（30分钟）
- [ ] Task 3.2: 优化GitHub预筛选规则（2小时）
- [ ] 测试验收，提交代码

**Day 2**:
- [ ] Task 3.3: 实现时间窗口过滤（2小时）
- [ ] Task 3.4: 创建日志分析工具（1小时）
- [ ] 测试验收，提交代码

**Day 3**:
- [ ] Task 3.5: 调整评分权重（30分钟，可选）
- [ ] Phase 3完整集成测试
- [ ] 提交Phase 3总结报告给Claude Code验收

### Week 2: Phase 4版本跟踪

**Day 4**:
- [ ] Task 4.1: GitHub Release监控（3小时）
- [ ] 测试验收，提交代码

**Day 5**:
- [ ] Task 4.2: arXiv版本更新提醒（2小时）
- [ ] Phase 4集成测试
- [ ] 提交Phase 4总结报告给Claude Code验收

### Week 3: Phase 5增强功能（可选）

**Day 6**:
- [ ] Task 5.1: 飞书卡片消息（3小时）
- [ ] Phase 5测试验收

**Day 7**:
- [ ] 全流程集成测试
- [ ] 文档更新（README, CLAUDE.md）
- [ ] 最终验收报告

---

## 完成标准与验收

### Phase 3验收标准

**功能完整性**:
- [x] PwC采集器已移除，无错误日志
- [x] GitHub预筛选通过率10-30%
- [x] 时间窗口过滤生效
- [x] 日志分析工具可用
- [x] 评分权重已调整（可选）

**代码质量**:
- [x] 所有修改符合PEP8规范
- [x] 关键逻辑有中文注释
- [x] 无硬编码魔法数字
- [x] 异常处理完善

**测试覆盖**:
- [x] 单元测试通过
- [x] 集成测试通过
- [x] 手动验收完成

### Phase 4验收标准

**功能完整性**:
- [x] GitHub Release监控正常
- [x] arXiv版本跟踪正常
- [x] 飞书通知推送成功
- [x] SQLite存储版本记录
- [x] GitHub Actions定时任务运行

**代码质量**:
- [x] 符合代码规范
- [x] 异常处理健壮
- [x] 日志完善清晰

**测试覆盖**:
- [x] 单元测试通过
- [x] 集成测试通过
- [x] 手动验收完成

### Phase 5验收标准

**功能完整性**:
- [x] 飞书卡片消息显示正常
- [x] 按钮跳转功能正常

**代码质量**:
- [x] 符合代码规范

**测试覆盖**:
- [x] 手动验收完成

---

## 常见问题FAQ

**Q1: 如何处理API限流?**
A: 使用指数退避重试 + 降低并发度 + 增加延迟。示例:
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def fetch_with_retry(url):
    ...
```

**Q2: 飞书API失败如何降级?**
A: 自动降级到SQLite备份，参考`StorageManager`实现。

**Q3: 如何调试LLM评分问题?**
A:
1. 检查`logs/benchscope.log`中的"LLM原始响应"
2. 确认JSON格式是否正确
3. 检查是否被markdown代码块包裹

**Q4: GitHub Actions无法访问secrets怎么办?**
A: 在GitHub仓库Settings → Secrets and variables → Actions中添加。

**Q5: 如何清空测试数据重新开始?**
A:
```bash
# 清空飞书表格
python scripts/clear_feishu_table.py

# 清空Redis缓存
redis-cli FLUSHALL

# 删除SQLite数据库
rm fallback.db
```

---

## 联系与支持

**开发过程中遇到问题**:
1. 检查本文档FAQ部分
2. 查看`docs/test-report.md`历史测试结果
3. 通知Claude Code验收时说明具体问题

**提交代码前检查**:
- [ ] 代码符合PEP8规范（运行`black`和`ruff`）
- [ ] 关键逻辑有中文注释
- [ ] 单元测试通过
- [ ] 手动测试通过
- [ ] Commit message符合规范
- [ ] 已通知Claude Code验收

---

**祝开发顺利！请严格按照本文档执行，每完成一个Task立即提交并通知Claude Code验收。** 🚀
