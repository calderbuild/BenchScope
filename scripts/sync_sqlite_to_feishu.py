#!/usr/bin/env python3
"""将SQLite降级备份数据同步到飞书多维表格"""
import asyncio
import logging
import sys
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.storage import StorageManager

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    """手动触发SQLite到飞书的同步"""
    logger.info("开始同步SQLite数据到飞书...")

    storage_manager = StorageManager()

    # 获取未同步记录
    unsync_records = await storage_manager.sqlite.get_unsynced()
    logger.info(f"发现 {len(unsync_records)} 条未同步记录")

    if len(unsync_records) == 0:
        logger.info("无需同步，退出")
        return

    # 尝试同步
    try:
        await storage_manager.sync_from_sqlite()
        logger.info("✅ 同步完成")
    except Exception as exc:  # noqa: BLE001
        logger.error(f"❌ 同步失败: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
