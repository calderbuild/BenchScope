"""BenchScope Phase 2 主流程"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import List

from src.collectors import ArxivCollector, GitHubCollector, HuggingFaceCollector
from src.config import Settings, get_settings
from src.models import RawCandidate
from src.notifier import FeishuNotifier
from src.prefilter import prefilter_batch
from src.scorer import LLMScorer
from src.storage import StorageManager

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    _configure_logging(settings)

    logger.info("=" * 60)
    logger.info("BenchScope Phase 2 启动")
    logger.info("=" * 60)

    # Step 1: 数据采集
    logger.info("[1/5] 数据采集...")
    collectors = [
        ArxivCollector(),
        GitHubCollector(),
        HuggingFaceCollector(settings=settings),
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

    # Step 1.5: 去重（过滤已推送的URL）
    logger.info("[1.5/5] URL去重...")
    storage = StorageManager()
    existing_urls = await storage.get_existing_urls()

    deduplicated = [c for c in all_candidates if c.url not in existing_urls]
    duplicate_count = len(all_candidates) - len(deduplicated)
    logger.info("去重完成: 过滤%d条重复,保留%d条新发现\n", duplicate_count, len(deduplicated))

    if not deduplicated:
        logger.warning("去重后无新候选,流程终止")
        return

    # Step 2: 规则预筛选
    logger.info("[2/5] 规则预筛选...")
    filtered = prefilter_batch(deduplicated)
    filter_rate = 100 * (1 - len(filtered) / len(deduplicated)) if deduplicated else 0
    logger.info("预筛选完成: 保留%d条 (过滤率%.1f%%)\n", len(filtered), filter_rate)
    if not filtered:
        logger.warning("预筛选后无候选,流程终止")
        return

    # Step 3: LLM评分
    logger.info("[3/5] LLM评分...")
    async with LLMScorer() as scorer:
        scored = await scorer.score_batch(filtered)
    logger.info("评分完成: %d条\n", len(scored))

    # Step 4: 存储入库
    logger.info("[4/5] 存储入库...")
    await storage.save(scored)
    await storage.sync_from_sqlite()
    await storage.cleanup()
    logger.info("存储完成\n")

    # Step 5: 飞书通知
    logger.info("[5/5] 飞书通知...")
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
    handlers = [logging.StreamHandler(), logging.FileHandler(log_path, encoding="utf-8")]
    logging.basicConfig(
        level=settings.logging.level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


if __name__ == "__main__":
    asyncio.run(main())
