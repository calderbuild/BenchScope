"""Notification History Tracking for Deduplication

核心逻辑：已通知过的项目不再重复通知。
用户需求：只看最新且相关的benchmark推送，避免重复内容。
实现：一旦某URL被成功推送，永久记录，后续采集中过滤。
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from typing import Optional

from src.common.url_utils import canonicalize_url

logger = logging.getLogger(__name__)

# 配置常量
NOTIFICATION_HISTORY_DB = "notification_history.db"


class NotificationHistory:
    """Track notification history per project URL.

    核心逻辑：一次通知后永久过滤，确保用户只看到新鲜内容。
    使用SQLite持久化存储每个项目的通知记录。
    """

    def __init__(self, db_path: str = NOTIFICATION_HISTORY_DB) -> None:
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create notification_history table if not exists."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS notification_history (
                        url_key TEXT PRIMARY KEY,
                        notify_count INTEGER DEFAULT 0,
                        first_notified TEXT,
                        last_notified TEXT,
                        title TEXT
                    )
                """)
                conn.commit()
            logger.debug("Notification history table ready: %s", self.db_path)
        except Exception as e:
            logger.warning("Failed to create notification history table: %s", e)

    def get_notify_count(self, url: str) -> int:
        """Get notification count for a URL."""
        url_key = canonicalize_url(url)
        if not url_key:
            return 0

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT notify_count FROM notification_history WHERE url_key = ?",
                    (url_key,)
                )
                row = cursor.fetchone()
                return row[0] if row else 0
        except Exception as e:
            logger.warning("Failed to get notify count for %s: %s", url_key, e)
            return 0

    def should_notify(self, url: str) -> bool:
        """Check if project should be notified.

        核心逻辑：已通知过的URL返回False，从未通知过的返回True。
        确保用户只收到新鲜内容，避免重复推送。
        """
        count = self.get_notify_count(url)
        return count == 0  # 只有从未通知过的才允许推送

    def increment_notify_count(
        self, url: str, title: Optional[str] = None
    ) -> int:
        """Increment notification count for a URL. Returns new count.

        每次成功发送通知后调用此方法更新计数。
        """
        url_key = canonicalize_url(url)
        if not url_key:
            return 0

        now = datetime.now().isoformat()

        try:
            with sqlite3.connect(self.db_path) as conn:
                # 检查是否存在
                cursor = conn.execute(
                    "SELECT notify_count FROM notification_history WHERE url_key = ?",
                    (url_key,)
                )
                row = cursor.fetchone()

                if row:
                    new_count = row[0] + 1
                    conn.execute("""
                        UPDATE notification_history
                        SET notify_count = ?, last_notified = ?, title = COALESCE(?, title)
                        WHERE url_key = ?
                    """, (new_count, now, title, url_key))
                else:
                    new_count = 1
                    conn.execute("""
                        INSERT INTO notification_history
                        (url_key, notify_count, first_notified, last_notified, title)
                        VALUES (?, ?, ?, ?, ?)
                    """, (url_key, new_count, now, now, title or ""))

                conn.commit()
                return new_count
        except Exception as e:
            logger.warning("Failed to increment notify count for %s: %s", url_key, e)
            return 0

    def batch_increment(
        self, items: list[tuple[str, Optional[str]]]
    ) -> int:
        """Batch increment notification counts.

        Args:
            items: List of (url, title) tuples

        Returns:
            Number of successfully updated items
        """
        if not items:
            return 0

        now = datetime.now().isoformat()
        success_count = 0

        try:
            with sqlite3.connect(self.db_path) as conn:
                for url, title in items:
                    url_key = canonicalize_url(url)
                    if not url_key:
                        continue

                    cursor = conn.execute(
                        "SELECT notify_count FROM notification_history WHERE url_key = ?",
                        (url_key,)
                    )
                    row = cursor.fetchone()

                    if row:
                        new_count = row[0] + 1
                        conn.execute("""
                            UPDATE notification_history
                            SET notify_count = ?, last_notified = ?,
                                title = COALESCE(?, title)
                            WHERE url_key = ?
                        """, (new_count, now, title, url_key))
                    else:
                        conn.execute("""
                            INSERT INTO notification_history
                            (url_key, notify_count, first_notified, last_notified, title)
                            VALUES (?, ?, ?, ?, ?)
                        """, (url_key, 1, now, now, title or ""))

                    success_count += 1

                conn.commit()
        except Exception as e:
            logger.warning("Failed to batch increment notification counts: %s", e)

        return success_count

    def get_notified_urls(self) -> set[str]:
        """Get all URL keys that have been notified at least once."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    "SELECT url_key FROM notification_history WHERE notify_count >= 1"
                )
                return {row[0] for row in cursor.fetchall()}
        except Exception as e:
            logger.warning("Failed to get notified URLs: %s", e)
            return set()

    def get_stats(self) -> dict:
        """Get notification history statistics."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN notify_count >= 1 THEN 1 ELSE 0 END) as notified_once,
                        MAX(notify_count) as max_count
                    FROM notification_history
                """)
                row = cursor.fetchone()
                return {
                    "total_tracked": row[0] or 0,
                    "notified_urls": row[1] or 0,
                    "max_notify_count": row[2] or 0,
                }
        except Exception as e:
            logger.warning("Failed to get notification history stats: %s", e)
            return {
                "total_tracked": 0,
                "notified_urls": 0,
                "max_notify_count": 0,
            }
