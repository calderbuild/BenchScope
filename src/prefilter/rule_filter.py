"""规则预筛选引擎"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import List

from src.common import constants
from src.models import RawCandidate

logger = logging.getLogger(__name__)


TRUSTED_SOURCES: set[str] = {"arxiv", "techempower", "dbengines", "helm"}


def _contains_any(text: str, keywords: list[str]) -> bool:
    """检查文本是否包含任意关键词"""

    lowered = text.lower()
    return any(kw in lowered for kw in keywords)


def _has_benchmark_positive_signal(candidate: RawCandidate) -> bool:
    """检查是否包含Benchmark正向信号词"""

    text = f"{candidate.title} {(candidate.abstract or '')}".lower()
    return _contains_any(text, constants.BENCHMARK_POSITIVE_SIGNALS)


def _has_benchmark_characteristics(candidate: RawCandidate) -> bool:
    """检测是否具备真实Benchmark特征（适用于所有来源）

    排除规则：
    - 框架/系统描述 + 无强Benchmark信号 → 过滤
    - 资源列表/教程/课程 + 无强Benchmark信号 → 过滤
    """

    text = f"{candidate.title} {(candidate.abstract or '')}".lower()

    # 排除模式（非Benchmark特征）
    exclude_patterns = [
        # 框架/系统描述
        "framework for",
        "we propose a",
        "we implement",
        "we develop",
        "a novel system",
        "agent framework",
        "gui agent",
        # 资源列表
        "awesome",
        "curated list",
        "collection of",
        "list of tools",
        "list of resources",
        # 教程/课程
        "tutorial",
        "course",
        "learning path",
        "how to",
        # 无关领域
        "robot",
        "robotics",
        "autonomous vehicle",
        "medical",
        "healthcare",
    ]

    has_exclude_pattern = any(p in text for p in exclude_patterns)

    if has_exclude_pattern:
        # 有排除模式时，必须有强Benchmark信号才通过
        strong_signals = ["benchmark", "evaluation", "leaderboard", "test set", "dataset"]
        if not any(s in text for s in strong_signals):
            logger.debug("排除: 有排除模式但无强Benchmark信号 - %s", candidate.title[:50])
            return False

    # 正向特征检查
    return _has_benchmark_positive_signal(candidate)


def _has_tool_suffix(title: str) -> bool:
    """检查标题是否以工具类后缀结尾（如 xxx-lib, xxx-client, xxx-tokenizer）"""
    tool_suffixes = [
        "-lib",
        "-library",
        "-client",
        "-sdk",
        "-wrapper",
        "-tool",
        "-utils",
        "-helper",
        "-connector",
        "-adapter",
        "-parser",
        "-tokenizer",
        "-splitter",
        "-package",
    ]
    title_lower = title.lower().replace(" ", "-").replace("_", "-")
    return any(title_lower.endswith(suffix) for suffix in tool_suffixes)


def _looks_like_tool_repo(candidate: RawCandidate) -> bool:
    """P10优化版：基于标题与摘要判断是否是工具/框架/协议而非Benchmark。

    改进逻辑（OR逻辑，满足任一即视为工具）：
    1. 标题以工具类后缀结尾（如 xxx-tokenizer）
    2. 摘要包含工具声明短语（如 "this is a library"）
    3. 命中工具类关键词 且 缺少强Benchmark信号

    例外：如果有强Benchmark信号（benchmark dataset, evaluation benchmark等），
    则不视为工具，避免误杀 "Tokenizer Benchmark" 这类真正的Benchmark。
    """

    text = f"{candidate.title} {(candidate.abstract or '')}".lower()

    # 检查强Benchmark信号（优先级最高，有此信号则不视为工具）
    strong_benchmark_signals = [
        "benchmark dataset",
        "evaluation benchmark",
        "test set",
        "leaderboard",
        "benchmark suite",
        "evaluation suite",
    ]
    if _contains_any(text, strong_benchmark_signals):
        return False

    # 检测1：标题以工具类后缀结尾
    if _has_tool_suffix(candidate.title):
        logger.debug("工具检测命中：标题后缀 - %s", candidate.title)
        return True

    # 检测2：摘要包含工具声明短语
    if _contains_any(text, constants.TOOL_NEGATIVE_PATTERNS):
        logger.debug("工具检测命中：声明短语 - %s", candidate.title)
        return True

    # 检测3：命中工具类关键词 且 缺少benchmark信号
    has_tool_keyword = _contains_any(text, constants.TOOL_LIKE_KEYWORDS)
    has_benchmark_signal = _contains_any(text, constants.BENCHMARK_DATASET_KEYWORDS)
    if has_tool_keyword and not has_benchmark_signal:
        logger.debug("工具检测命中：关键词无benchmark信号 - %s", candidate.title)
        return True

    return False


def _looks_like_algo_paper(candidate: RawCandidate) -> bool:
    """针对arXiv等论文源，识别算法/系统方法论（非Benchmark）。

    规则：文本命中算法方法短语，且不包含Benchmark/数据集正向关键词。
    保留“Benchmark方法论”——因为它会包含benchmark/dataset等正向信号。
    """

    text = f"{candidate.title} {(candidate.abstract or '')}".lower()

    has_algo_phrase = _contains_any(
        text, constants.ALGO_METHOD_PHRASES_EXTENDED
    )
    has_benchmark_signal = _contains_any(text, constants.BENCHMARK_DATASET_KEYWORDS)
    return has_algo_phrase and not has_benchmark_signal


def _looks_like_technical_report(candidate: RawCandidate) -> bool:
    """检测技术报告/模型发布论文（非Benchmark）。"""

    title_lower = (candidate.title or "").lower()
    has_tech_report_pattern = _contains_any(
        title_lower, constants.TECHNICAL_REPORT_PATTERNS
    )
    has_model_name = _contains_any(title_lower, constants.MODEL_RELEASE_KEYWORDS)
    has_benchmark_signal = _contains_any(
        title_lower, constants.BENCHMARK_TITLE_SIGNALS
    )

    if has_tech_report_pattern and not has_benchmark_signal:
        return True

    if has_model_name and "technical report" in title_lower and not has_benchmark_signal:
        return True

    return False


def _looks_like_non_mgx_application(candidate: RawCandidate) -> bool:
    """检测非MGX相关的应用领域论文。"""

    text = f"{candidate.title} {(candidate.abstract or '')}".lower()
    has_non_mgx_app = _contains_any(text, constants.NON_MGX_APPLICATION_KEYWORDS)
    if not has_non_mgx_app:
        return False

    mgx_core_keywords = [
        "code generation",
        "code completion",
        "code review",
        "multi-agent",
        "agent collaboration",
        "tool use",
        "api call",
        "function call",
        "web automation",
        "gui automation",
        "browser automation",
        "software engineering",
        "programming",
    ]
    has_mgx_signal = _contains_any(text, mgx_core_keywords)
    return not has_mgx_signal


def prefilter(candidate: RawCandidate) -> bool:
    """Phase 3 基线预筛选规则（Phase 2优化版）

    兼容老接口，内部复用带原因版以便统计。
    """

    passed, _reason = _prefilter_with_reason(candidate)
    return passed


def prefilter_batch(candidates: List[RawCandidate]) -> List[RawCandidate]:
    """批量预筛选"""

    if not candidates:
        return []

    reason_stats: Counter[str] = Counter()
    source_stats: dict[str, dict[str, int]] = {}  # 按来源统计输入/输出
    filtered: List[RawCandidate] = []

    for candidate in candidates:
        source = candidate.source
        if source not in source_stats:
            source_stats[source] = {"input": 0, "output": 0}
        source_stats[source]["input"] += 1

        passed, reason = _prefilter_with_reason(candidate)
        reason_stats[reason] += 1
        if passed:
            filtered.append(candidate)
            source_stats[source]["output"] += 1

    rate = 100 * (1 - len(filtered) / len(candidates))
    # 只输出被过滤的主要原因，避免日志过长
    drop_reasons = {
        k: v for k, v in reason_stats.items() if k not in {"pass"} and v > 0
    }
    reason_text = (
        ", ".join(f"{k}:{v}" for k, v in sorted(drop_reasons.items(), key=lambda x: -x[1]))
        if drop_reasons
        else "无"
    )

    logger.info(
        "预筛选完成,输入%d条,输出%d条,过滤率%.1f%%,过滤原因分布: %s",
        len(candidates),
        len(filtered),
        rate,
        reason_text,
    )

    # 输出按来源的通过统计，便于定位召回差异
    if source_stats:
        logger.info("===== 预筛选按来源统计 =====")
        for source, stats in sorted(source_stats.items()):
            pass_rate = (
                stats["output"] / stats["input"] * 100 if stats["input"] else 0
            )
            logger.info(
                "  %s: %d/%d (通过率%.1f%%)",
                source.ljust(15),
                stats["output"],
                stats["input"],
                pass_rate,
            )
    return filtered


def _prefilter_with_reason(candidate: RawCandidate) -> tuple[bool, str]:
    """返回是否通过及原因，方便统计定位问题"""

    if (
        not candidate.title
        or len(candidate.title.strip()) < constants.PREFILTER_MIN_TITLE_LENGTH
    ):
        logger.debug("过滤: 标题过短 - %s", candidate.title)
        return False, "title_short"

    # 摘要长度要求：HuggingFace/HELM/Semantic Scholar来源豁免（官方数据源，描述本身较短）
    if candidate.source not in {"helm", "semantic_scholar", "huggingface"}:
        if (
            not candidate.abstract
            or len(candidate.abstract.strip()) < constants.PREFILTER_MIN_ABSTRACT_LENGTH
        ):
            logger.debug("过滤: 摘要过短 - %s", candidate.title)
            return False, "abstract_short"

    if not candidate.url or not candidate.url.startswith(("http://", "https://")):
        logger.debug("过滤: URL无效 - %s", candidate.url)
        return False, "invalid_url"

    valid_sources = {
        "arxiv",
        "github",
        "huggingface",
        "helm",
        "semantic_scholar",
        "techempower",
        "dbengines",
    }
    if candidate.source not in valid_sources:
        logger.debug("过滤: 来源不在白名单 - %s", candidate.source)
        return False, "invalid_source"

    if not _passes_keyword_rules(candidate):
        return False, "keyword_rule"

    # P10新增: 所有来源统一执行Benchmark特征检测（GitHub除外，已有更严格检测）
    if candidate.source != "github" and not _has_benchmark_characteristics(candidate):
        logger.debug("过滤: 缺少Benchmark特征 - %s (%s)", candidate.title, candidate.source)
        return False, "no_benchmark_feature"

    if candidate.source == "github" and not _is_quality_github_repo(candidate):
        return False, "github_quality"

    # 工具/协议类仓库过滤（避免MCP/SDK误判为Benchmark）
    if candidate.source == "github" and _looks_like_tool_repo(candidate):
        logger.debug("过滤: 疑似工具/协议仓库 - %s", candidate.title)
        return False, "tool_repo"

    # arXiv等论文源：过滤算法/系统方法论文，保留Benchmark/Benchmark方法论
    if candidate.source == "arxiv" and _looks_like_algo_paper(candidate):
        logger.debug("过滤: 算法/系统方法论文 - %s", candidate.title)
        return False, "algo_paper"

    # 技术报告/模型发布论文过滤（arXiv等论文源）
    if candidate.source == "arxiv" and _looks_like_technical_report(candidate):
        logger.debug("过滤: 技术报告/模型发布论文 - %s", candidate.title)
        return False, "tech_report"

    # 非MGX应用领域论文过滤（arXiv等论文源）
    if candidate.source == "arxiv" and _looks_like_non_mgx_application(candidate):
        logger.debug("过滤: 非MGX应用领域论文 - %s", candidate.title)
        return False, "non_mgx_app"

    logger.debug(
        "✅ 通过预筛选: %s (source=%s, stars=%s)",
        candidate.title[: constants.TITLE_TRUNCATE_SHORT],
        candidate.source,
        candidate.github_stars or "N/A",
    )
    return True, "pass"


def _is_quality_github_repo(candidate: RawCandidate) -> bool:
    """GitHub仓库需要满足stars、最近更新与README长度要求"""

    stars = candidate.github_stars or 0
    if stars < constants.PREFILTER_MIN_GITHUB_STARS:
        logger.debug("GitHub stars不足: %s (%s)", candidate.title, stars)
        return False

    if not candidate.publish_date:
        logger.debug("GitHub无最近更新时间: %s", candidate.title)
        return False

    now = datetime.now(timezone.utc)
    if (now - candidate.publish_date).days > constants.PREFILTER_RECENT_DAYS:
        logger.debug("GitHub更新时间过久: %s", candidate.title)
        return False

    readme_length = len(candidate.abstract or "")
    if readme_length < constants.PREFILTER_MIN_README_LENGTH:
        logger.debug("GitHub README过短: %s (%s字符)", candidate.title, readme_length)
        return False

    # Phase 6 优化: 排除awesome-list和工具类项目
    title_lower = candidate.title.lower()
    readme_lower = (candidate.abstract or "").lower()

    # 排除awesome-list
    if "awesome-" in title_lower or "awesome " in title_lower:
        logger.debug("排除awesome-list: %s", candidate.title)
        return False

    # 排除资源汇总类项目
    curated_patterns = [
        "curated list",
        "collection of",
        "list of tools",
        "awesome list",
        "资源汇总",
        "资源列表",
    ]
    if any(pattern in readme_lower for pattern in curated_patterns):
        logger.debug("排除资源汇总类项目: %s", candidate.title)
        return False

    # Benchmark特征检测（至少满足一项）
    benchmark_features = [
        "benchmark",
        "evaluation",
        "test set",
        "dataset",
        "leaderboard",
        "baseline",
        "performance",
        "comparison",
        "vs",
        "versus",
        "testing",
        "test suite",
        "test framework",
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


def _passes_keyword_rules(candidate: RawCandidate) -> bool:
    """基于Phase7白/黑名单的关键词过滤

    P10优化: 权威来源不再完全豁免，仍需通过Benchmark正向特征检查
    """

    if candidate.source in TRUSTED_SOURCES:
        # 权威来源仅豁免排除词检查，仍需具备正向特征
        if _has_benchmark_positive_signal(candidate):
            logger.debug(
                "权威来源通过正向特征检查: %s (%s)",
                candidate.title[: constants.TITLE_TRUNCATE_SHORT],
                candidate.source,
            )
            return True
        logger.debug(
            "权威来源未通过正向特征检查: %s (%s)",
            candidate.title[: constants.TITLE_TRUNCATE_SHORT],
            candidate.source,
        )
        return False

    text = f"{candidate.title} {(candidate.abstract or '')}".lower()

    if any(excluded in text for excluded in constants.PREFILTER_EXCLUDED_KEYWORDS):
        logger.debug("过滤: 命中排除关键词 - %s", candidate.title)
        return False

    if not any(required in text for required in constants.PREFILTER_REQUIRED_KEYWORDS):
        logger.debug("过滤: 未命中必需关键词 - %s", candidate.title)
        return False

    return True
