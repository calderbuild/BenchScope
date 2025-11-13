"""arXiv 论文版本跟踪任务"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_settings
from src.notifier.feishu_notifier import FeishuNotifier
from src.storage.storage_manager import StorageManager
from src.tracker.arxiv_tracker import ArxivVersionTracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    storage = StorageManager()

    logger.info("从飞书Bitable读取URL列表...")
    existing_urls = await storage.get_existing_urls()
    arxiv_urls = sorted(url for url in existing_urls if "arxiv.org/abs" in url)
    logger.info("发现 %d 篇arXiv论文", len(arxiv_urls))

    if not arxiv_urls:
        logger.info("无arXiv论文需要跟踪")
        return

    tracker = ArxivVersionTracker(db_path=str(settings.sqlite_path))
    new_versions = await tracker.check_updates(arxiv_urls)

    if not new_versions:
        logger.info("无新版本")
        return

    notifier = FeishuNotifier(settings=settings)
    for version in new_versions:
        message = (
            f"**arXiv 版本更新**\n\n"
            f"论文: {version.arxiv_id}\n"
            f"版本: {version.version}\n"
            f"更新时间: {version.updated_at.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"摘要:\n{version.summary[:500]}\n\n"
            f"🔗 查看详情: {version.url}"
        )
        await notifier.send_text(message)
        await asyncio.sleep(0.5)

    logger.info("arXiv 版本跟踪完成 -> 新版本 %d 条", len(new_versions))


if __name__ == "__main__":
    asyncio.run(main())
