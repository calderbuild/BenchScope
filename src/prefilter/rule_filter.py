"""规则预筛选引擎"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

from src.common import constants
from src.models import RawCandidate

logger = logging.getLogger(__name__)


TRUSTED_SOURCES: set[str] = {"techempower", "dbengines", "helm"}


def prefilter(candidate: RawCandidate) -> bool:
    """Phase 3 基线预筛选规则（Phase 2优化版）"""

    if (
        not candidate.title
        or len(candidate.title.strip()) < constants.PREFILTER_MIN_TITLE_LENGTH
    ):
        logger.debug("过滤: 标题过短 - %s", candidate.title)
        return False

    # 摘要长度要求：HuggingFace/HELM/Semantic Scholar来源豁免（官方数据源，描述本身较短）
    if candidate.source not in {"helm", "semantic_scholar", "huggingface"}:
        if (
            not candidate.abstract
            or len(candidate.abstract.strip()) < constants.PREFILTER_MIN_ABSTRACT_LENGTH
        ):
            logger.debug("过滤: 摘要过短 - %s", candidate.title)
            return False

    if not candidate.url or not candidate.url.startswith(("http://", "https://")):
        logger.debug("过滤: URL无效 - %s", candidate.url)
        return False

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
        return False

    if not _passes_keyword_rules(candidate):
        return False

    if candidate.source == "github" and not _is_quality_github_repo(candidate):
        return False

    logger.debug(
        "✅ 通过预筛选: %s (source=%s, stars=%s)",
        candidate.title[: constants.TITLE_TRUNCATE_SHORT],
        candidate.source,
        candidate.github_stars or "N/A",
    )
    return True


def prefilter_batch(candidates: List[RawCandidate]) -> List[RawCandidate]:
    """批量预筛选"""

    if not candidates:
        return []

    filtered = [c for c in candidates if prefilter(c)]
    rate = 100 * (1 - len(filtered) / len(candidates))
    logger.info(
        "预筛选完成,输入%d条,输出%d条,过滤率%.1f%%",
        len(candidates),
        len(filtered),
        rate,
    )
    return filtered


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
