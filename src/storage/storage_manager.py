"""存储管理器"""
from __future__ import annotations

import logging
from typing import List, Optional

from src.common import constants
from src.models import ScoredCandidate
from src.storage.feishu_storage import FeishuStorage
from src.storage.sqlite_fallback import SQLiteFallback

logger = logging.getLogger(__name__)


class StorageManager:
    """飞书主存储 + SQLite 降级"""

    def __init__(self, feishu: Optional[FeishuStorage] = None, sqlite: Optional[SQLiteFallback] = None) -> None:
        self.feishu = feishu or FeishuStorage()
        self.sqlite = sqlite or SQLiteFallback()

    async def save(self, candidates: List[ScoredCandidate]) -> None:
        """主备存储策略"""

        if not candidates:
            return

        try:
            await self.feishu.save(candidates)
            logger.info("✅ 飞书存储成功: %d条", len(candidates))
        except Exception as exc:  # noqa: BLE001
            logger.warning("⚠️  飞书存储失败,降级到SQLite: %s", exc)
            await self.sqlite.save(candidates)
            logger.info("✅ SQLite备份成功: %d条", len(candidates))

    async def sync_from_sqlite(self) -> None:
        """将SQLite未同步记录回写到飞书"""

        pending = await self.sqlite.get_unsynced()
        if not pending:
            logger.info("无未同步记录")
            return

        logger.info("发现%d条未同步记录", len(pending))
        try:
            await self.feishu.save(pending)
            await self.sqlite.mark_synced([item.url for item in pending])
            logger.info("✅ 同步完成: %d条", len(pending))
        except Exception as exc:  # noqa: BLE001
            logger.error("❌ 同步失败: %s", exc)

    async def cleanup(self) -> None:
        """清理SQLite中过期记录"""

        await self.sqlite.cleanup_old_records(constants.SQLITE_RETENTION_DAYS)
        logger.info("SQLite已清理过期记录")

    async def get_existing_urls(self) -> set[str]:
        """查询已存在的URL（用于去重）"""
        try:
            return await self.feishu.get_existing_urls()
        except Exception as exc:  # noqa: BLE001
            logger.warning("⚠️  查询飞书失败,返回空集合: %s", exc)
            return set()
