"""BenchScope Phase 2 主流程"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List

import httpx

from src.collectors import (
    ArxivCollector,
    DBEnginesCollector,
    GitHubCollector,
    HelmCollector,
    HuggingFaceCollector,
    TechEmpowerCollector,
    TwitterCollector,
)
from src.common import constants
from src.config import Settings, get_settings
from src.enhancer import PDFEnhancer
from src.models import RawCandidate, ScoredCandidate
from src.notifier import FeishuNotifier
from src.prefilter import prefilter_batch
from src.scorer import LLMScorer
from src.storage import StorageManager

logger = logging.getLogger(__name__)


async def ensure_grobid_running(grobid_url: str, max_wait_seconds: int = 60) -> bool:
    """确保GROBID服务运行，如果未运行则自动启动

    Args:
        grobid_url: GROBID服务URL（如 http://localhost:8070）
        max_wait_seconds: 最大等待时间（秒）

    Returns:
        bool: GROBID服务是否成功运行
    """
    # 1. 检查GROBID是否已运行
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{grobid_url}/api/isalive")
            if resp.text.strip() == "true":
                logger.info("✅ GROBID服务已运行: %s", grobid_url)
                return True
    except Exception:
        logger.info("GROBID服务未运行，准备启动...")

    # 2. 检查Docker是否可用
    try:
        subprocess.run(
            ["docker", "--version"],
            check=True,
            capture_output=True,
            timeout=5,
        )
    except Exception as exc:
        logger.warning("Docker不可用，跳过GROBID启动: %s", exc)
        return False

    # 3. 检查GROBID容器是否存在但未运行
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--filter", "name=grobid", "--format", "{{.Names}}"],
            check=True,
            capture_output=True,
            timeout=5,
            text=True,
        )
        if "grobid" in result.stdout:
            logger.info("发现已存在的GROBID容器，尝试启动...")
            subprocess.run(["docker", "start", "grobid"], check=True, timeout=10)
        else:
            # 4. 启动新的GROBID容器
            logger.info("启动GROBID Docker容器...")
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    "grobid",
                    "--rm",
                    "--init",
                    "--ulimit",
                    "core=0",
                    "-p",
                    "8070:8070",
                    "lfoppiano/grobid:0.8.0",
                ],
                check=True,
                timeout=30,
                capture_output=True,
            )
    except Exception as exc:
        logger.error("启动GROBID容器失败: %s", exc)
        return False

    # 5. 等待GROBID服务就绪
    logger.info("等待GROBID服务启动（最多%d秒）...", max_wait_seconds)
    start_time = time.time()
    while time.time() - start_time < max_wait_seconds:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"{grobid_url}/api/isalive")
                if resp.text.strip() == "true":
                    logger.info("✅ GROBID服务启动成功")
                    return True
        except Exception:
            pass
        await asyncio.sleep(2)

    logger.error("GROBID服务启动超时")
    return False


async def main() -> None:
    settings = get_settings()
    _configure_logging(settings)

    logger.info("=" * 60)
    logger.info("BenchScope Phase 2 启动")
    logger.info("=" * 60)

    # Step 0: 确保GROBID服务运行（用于PDF增强）
    grobid_url = os.getenv("GROBID_URL", "http://localhost:8070")
    grobid_running = await ensure_grobid_running(
        grobid_url=grobid_url,
        max_wait_seconds=60,
    )
    if not grobid_running:
        logger.warning("GROBID服务未运行，PDF增强功能将被禁用")
    else:
        logger.info("GROBID服务就绪，PDF增强功能已启用")

    # Step 1: 数据采集
    logger.info("[1/7] 数据采集...")
    collectors = [
        ArxivCollector(settings=settings),
        # SemanticScholarCollector(),  # 暂时禁用：无API密钥
        HelmCollector(settings=settings),
        GitHubCollector(settings=settings),
        HuggingFaceCollector(settings=settings),
        TechEmpowerCollector(settings=settings),
        DBEnginesCollector(settings=settings),
        TwitterCollector(settings=settings),
    ]

    all_candidates: List[RawCandidate] = []
    for collector in collectors:
        try:
            candidates = await collector.collect()
            all_candidates.extend(candidates)
            logger.info("  ✓ %s: %d条", collector.__class__.__name__, len(candidates))
        except Exception as exc:  # noqa: BLE001
            logger.error("  ✗ %s失败: %s", collector.__class__.__name__, exc)

    logger.info("采集完成: 共%d条候选\n", len(all_candidates))
    if not all_candidates:
        logger.warning("无采集数据,流程终止")
        return

    # Step 1.5: 去重（本次采集内部去重 + 过滤已推送的URL）
    logger.info("[1.5/7] URL去重...")

    # 1. 本次采集内部去重（保留第一次出现）
    seen_urls_this_batch: set[str] = set()
    internal_deduplicated: List[RawCandidate] = []
    for candidate in all_candidates:
        if candidate.url not in seen_urls_this_batch:
            seen_urls_this_batch.add(candidate.url)
            internal_deduplicated.append(candidate)

    internal_dup_count = len(all_candidates) - len(internal_deduplicated)
    if internal_dup_count > 0:
        logger.info("本次采集内部去重: 过滤%d条重复URL", internal_dup_count)

    # 2. 与飞书已存在URL去重（仅对比近N天记录，降低新鲜度损耗）
    storage = StorageManager()
    now = datetime.now()
    existing_records: list[dict[str, Any]] = await storage.read_existing_records()
    # 按来源应用不同的去重窗口
    recent_urls_by_source: dict[str, set[str]] = {}
    for record in existing_records:
        publish_date = record.get("publish_date")
        url_value = record.get("url")
        source_value = record.get("source", "default")
        if not isinstance(publish_date, datetime) or not url_value:
            continue
        window_days = constants.DEDUP_LOOKBACK_DAYS_BY_SOURCE.get(
            source_value, constants.DEDUP_LOOKBACK_DAYS_BY_SOURCE["default"]
        )
        if publish_date >= now - timedelta(days=window_days):
            recent_urls_by_source.setdefault(source_value, set()).add(url_value)

    deduplicated: List[RawCandidate] = []
    duplicate_count = 0
    for c in internal_deduplicated:
        window_days = constants.DEDUP_LOOKBACK_DAYS_BY_SOURCE.get(
            c.source, constants.DEDUP_LOOKBACK_DAYS_BY_SOURCE["default"]
        )
        recent_urls = recent_urls_by_source.get(c.source, set())
        if c.url in recent_urls:
            duplicate_count += 1
            continue
        deduplicated.append(c)

    logger.info(
        "去重完成: 飞书总记录%d条, arXiv窗口%d天, 默认窗口%d天, 过滤%d条重复, 保留%d条新发现\n",
        len(existing_records),
        constants.DEDUP_LOOKBACK_DAYS_BY_SOURCE.get("arxiv"),
        constants.DEDUP_LOOKBACK_DAYS_BY_SOURCE.get("default"),
        duplicate_count,
        len(deduplicated),
    )

    # 按来源输出去重后的新发现，帮助观察来源多样性
    source_counts = Counter(c.source for c in deduplicated)
    if source_counts:
        logger.info("===== 去重后按来源统计 =====")
        for source, count in sorted(source_counts.items(), key=lambda x: -x[1]):
            collected = sum(1 for c in internal_deduplicated if c.source == source)
            dup_rate = (
                (collected - count) / collected * 100 if collected else 0
            )
            logger.info(
                "  %s: %d条新发现 / %d条采集 (去重率%.1f%%)",
                source.ljust(15),
                count,
                collected,
                dup_rate,
            )

    if not deduplicated:
        logger.warning("去重后无新候选,流程终止")
        return

    # Step 2: 规则预筛选
    logger.info("[2/7] 规则预筛选...")
    filtered = prefilter_batch(deduplicated)
    filter_rate = 100 * (1 - len(filtered) / len(deduplicated)) if deduplicated else 0
    logger.info("预筛选完成: 保留%d条 (过滤率%.1f%%)\n", len(filtered), filter_rate)
    if not filtered:
        logger.warning("预筛选后无候选,流程终止")
        return

    # Step 3: PDF 内容增强（仅对通过预筛选的候选进行深度解析）
    logger.info("[3/7] PDF内容增强...")
    pdf_enhancer = PDFEnhancer()
    enhanced_candidates = await pdf_enhancer.enhance_batch(filtered)
    arxiv_count = sum(1 for c in filtered if c.source == "arxiv")
    logger.info(
        "PDF增强完成: %d条候选 (其中arXiv %d条)\n",
        len(enhanced_candidates),
        arxiv_count,
    )

    # Step 4: LLM评分（使用增强后的候选）
    logger.info("[4/7] LLM评分...")
    async with LLMScorer() as scorer:
        scored = await scorer.score_batch(enhanced_candidates)
    logger.info("评分完成: %d条\n", len(scored))

    # Step 4.5: 论文/权威源兜底打分（最新且相关不因无GitHub被重罚）
    logger.info("[4.5/7] 权威源分数兜底...")
    scored = [_apply_recency_domain_floor(c) for c in scored]

    # Step 4.6: 时间新鲜度加权（最新优先，兼顾任务相关性）
    logger.info("[4.6/7] 新鲜度加权...")
    scored = [_apply_freshness_boost(c) for c in scored]

    # Step 5: 图片上传已禁用以节省时间
    logger.info("[5/7] 图片上传已跳过，减少耗时")

    # Step 6: 存储入库
    logger.info("[6/7] 存储入库...")
    await storage.save(scored)
    await storage.sync_from_sqlite()
    await storage.cleanup()
    logger.info("存储完成\n")

    # Step 7: 飞书通知
    logger.info("[7/7] 飞书通知...")
    notifier = FeishuNotifier(settings=settings)
    await notifier.notify(scored)
    logger.info("通知完成\n")

    high_priority = [c for c in scored if c.priority == "high"]
    medium_priority = [c for c in scored if c.priority == "medium"]
    avg_score = sum(c.total_score for c in scored) / len(scored) if scored else 0

    logger.info("=" * 60)
    logger.info("BenchScope Phase 2 完成")
    logger.info("  采集: %d条", len(all_candidates))
    logger.info("  去重: %d条新发现 (过滤%d条重复)", len(deduplicated), duplicate_count)
    logger.info("  预筛选: %d条", len(filtered))
    logger.info("  高优先级: %d条", len(high_priority))
    logger.info("  中优先级: %d条", len(medium_priority))
    logger.info("  平均分: %.2f/10", avg_score)
    logger.info("=" * 60)


def _configure_logging(settings: Settings) -> None:
    log_path = Path(settings.logging.directory) / settings.logging.file_name
    handlers = [
        logging.StreamHandler(),
        logging.FileHandler(log_path, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=settings.logging.level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


def _apply_freshness_boost(candidate: ScoredCandidate) -> ScoredCandidate:
    """对近期发布的候选加权，突出最新、任务相关内容。

    - 7天内: +1.5
    - 14天内: +0.8
    - 30天内: +0.3
    加权后封顶10分，避免分数膨胀。
    """

    if not candidate.publish_date:
        return candidate

    publish_dt = candidate.publish_date
    if publish_dt.tzinfo is None:
        publish_dt = publish_dt.replace(tzinfo=timezone.utc)

    now = datetime.now(tz=publish_dt.tzinfo)
    days = (now - publish_dt).days

    boost = 0.0
    if days <= 7:
        boost = constants.FRESHNESS_BOOST_7D
    elif days <= 14:
        boost = constants.FRESHNESS_BOOST_14D
    elif days <= 30:
        boost = constants.FRESHNESS_BOOST_30D

    if boost <= 0:
        return candidate

    boosted_total = min(10.0, candidate.total_score + boost)
    candidate.custom_total_score = boosted_total

    logger.debug(
        "新鲜度加权: %s | %dd | +%.1f -> %.1f",
        candidate.title[: constants.TITLE_TRUNCATE_SHORT],
        days,
        boost,
        boosted_total,
    )
    return candidate


def _apply_recency_domain_floor(candidate: ScoredCandidate) -> ScoredCandidate:
    """对近期且任务相关的权威来源设置评分下限，避免因缺少GitHub被过度扣分。

    条件：
    - 来源属于权威/论文类（arxiv/helm/techempower/dbengines/huggingface/semantic_scholar）
    - MGX相关性 >= 6.0（确保任务领域相关）
    - 发布距今 <= 30 天
    下限：活跃度>=4.0，可复现性>=4.5，许可>=3.0
    """

    authority_sources = {
        "arxiv",
        "helm",
        "techempower",
        "dbengines",
        "huggingface",
        "semantic_scholar",
    }

    source = (candidate.source or "").lower()
    if source not in authority_sources:
        return candidate

    if candidate.relevance_score < 6.0:
        return candidate

    publish_dt = candidate.publish_date
    if publish_dt is None:
        return candidate
    if publish_dt.tzinfo is None:
        publish_dt = publish_dt.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(tz=publish_dt.tzinfo) - publish_dt).days
    # 放宽到90天，避免新榜单/论文被过早压分
    if age_days > 90:
        return candidate

    # 下限保护（HuggingFace 更高，其他权威源使用基线）
    if source == "huggingface":
        candidate.activity_score = max(candidate.activity_score, 5.5)
        candidate.reproducibility_score = max(candidate.reproducibility_score, 5.5)
        candidate.license_score = max(candidate.license_score, 4.5)
    else:
        candidate.activity_score = max(candidate.activity_score, 4.5)
        candidate.reproducibility_score = max(candidate.reproducibility_score, 5.0)
        candidate.license_score = max(candidate.license_score, 3.5)

    # 若已有新鲜度加权(custom_total_score)未设或偏低，则用下限重算
    weights = constants.SCORE_WEIGHTS
    base_total = (
        candidate.activity_score * weights["activity"]
        + candidate.reproducibility_score * weights["reproducibility"]
        + candidate.license_score * weights["license"]
        + candidate.novelty_score * weights["novelty"]
        + candidate.relevance_score * weights["relevance"]
    )
    if candidate.custom_total_score is None:
        candidate.custom_total_score = base_total
    else:
        candidate.custom_total_score = max(candidate.custom_total_score, base_total)

    logger.debug(
        "权威源下限保护: %s | %dd | total>=%.2f",
        candidate.title[: constants.TITLE_TRUNCATE_SHORT],
        age_days,
        candidate.custom_total_score,
    )
    return candidate


if __name__ == "__main__":
    asyncio.run(main())
