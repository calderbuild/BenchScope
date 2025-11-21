"""BenchScope Phase 2 主流程"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import List

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
from src.config import Settings, get_settings
from src.enhancer import PDFEnhancer
from src.models import RawCandidate
from src.notifier import FeishuNotifier
from src.prefilter import prefilter_batch
from src.scorer import LLMScorer
from src.storage import FeishuImageUploader, StorageManager

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

    # 2. 与飞书已存在URL去重
    storage = StorageManager()
    existing_urls = await storage.get_existing_urls()

    deduplicated = [c for c in internal_deduplicated if c.url not in existing_urls]
    duplicate_count = len(internal_deduplicated) - len(deduplicated)
    logger.info(
        "去重完成: 过滤%d条重复,保留%d条新发现\n", duplicate_count, len(deduplicated)
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

    # Step 5: 图片上传到飞书
    logger.info("[5/7] 图片上传到飞书...")
    uploader = FeishuImageUploader(settings)
    upload_targets = [
        c
        for c in scored
        if c.hero_image_url
        and not c.hero_image_key
        and c.hero_image_url.startswith(("http://", "https://"))
    ]
    success_count = 0
    for candidate in upload_targets:
        try:
            if candidate.hero_image_url is None:
                # 理论不应出现，双重保护避免类型告警
                continue
            candidate.hero_image_key = await uploader.upload_image(
                candidate.hero_image_url
            )
            if candidate.hero_image_key:
                success_count += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("图片上传失败: %s | %s", candidate.title[:50], exc)
    logger.info("图片上传完成: %d/%d 成功\n", success_count, len(upload_targets))

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


if __name__ == "__main__":
    asyncio.run(main())
