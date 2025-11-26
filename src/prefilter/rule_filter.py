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


def _looks_like_tool_repo(candidate: RawCandidate) -> bool:
    """基于标题与摘要快速判断是否是工具/框架/协议而非Benchmark。

    规则（满足以下任意且缺少benchmark特征则视为工具）：
    - 命中工具类关键词（SDK/protocol/framework等）
    - 摘要/README中未出现Benchmark/数据集正向关键词
    """

    text = f"{candidate.title} {(candidate.abstract or '')}".lower()

    if not _contains_any(text, constants.TOOL_LIKE_KEYWORDS):
        return False

    has_benchmark_signal = _contains_any(text, constants.BENCHMARK_DATASET_KEYWORDS)
    return not has_benchmark_signal


def _looks_like_algo_paper(candidate: RawCandidate) -> bool:
    """针对arXiv等论文源，识别算法/系统方法论（非Benchmark）。

    规则：文本命中算法方法短语，且不包含Benchmark/数据集正向关键词。
    保留“Benchmark方法论”——因为它会包含benchmark/dataset等正向信号。
    """

    text = f"{candidate.title} {(candidate.abstract or '')}".lower()

    has_algo_phrase = _contains_any(text, constants.ALGO_METHOD_PHRASES)
    has_benchmark_signal = _contains_any(text, constants.BENCHMARK_DATASET_KEYWORDS)
    return has_algo_phrase and not has_benchmark_signal


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
    """基于Phase7白/黑名单的关键词过滤（权威来源豁免）"""

    if candidate.source in TRUSTED_SOURCES:
        logger.debug(
            "权威来源豁免关键词检查: %s (%s)",
            candidate.title[: constants.TITLE_TRUNCATE_SHORT],
            candidate.source,
        )
        return True

    text = f"{candidate.title} {(candidate.abstract or '')}".lower()

    if any(excluded in text for excluded in constants.PREFILTER_EXCLUDED_KEYWORDS):
        logger.debug("过滤: 命中排除关键词 - %s", candidate.title)
        return False

    if not any(required in text for required in constants.PREFILTER_REQUIRED_KEYWORDS):
        logger.debug("过滤: 未命中必需关键词 - %s", candidate.title)
        return False

    return True
