"""SQLite 降级存储"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Sequence

from src.common import constants
from src.config import Settings, get_settings
from src.models import ScoredCandidate

logger = logging.getLogger(__name__)


class SQLiteFallback:
    """在飞书不可用时将数据写入SQLite备份"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.db_path = Path(self.settings.sqlite_path or constants.SQLITE_DB_PATH)
        self._init_db()

    def _init_db(self) -> None:
        """初始化数据库结构"""

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fallback_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL,
                score_json TEXT NOT NULL,
                raw_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                synced_to_feishu INTEGER DEFAULT 0
            )
            """
        )
        conn.commit()
        conn.close()

    async def save(self, candidates: List[ScoredCandidate]) -> None:
        """写入SQLite,与飞书写入同构"""

        if not candidates:
            return

        await asyncio.to_thread(self._save_sync, candidates)
        logger.info("SQLite已备份%s条记录", len(candidates))

    def _save_sync(self, candidates: Sequence[ScoredCandidate]) -> None:
        conn = sqlite3.connect(self.db_path)
        for candidate in candidates:
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO fallback_candidates
                    (title, source, url, score_json, raw_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        candidate.title,
                        candidate.source,
                        candidate.url,
                        json.dumps(self._serialize_scores(candidate)),
                        json.dumps(self._serialize_raw(candidate)),
                    ),
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("SQLite写入失败: %s", exc)
        conn.commit()
        conn.close()

    async def get_unsynced(self) -> List[ScoredCandidate]:
        """读取未同步到飞书的记录"""

        return await asyncio.to_thread(self._load_unsynced)

    def _load_unsynced(self) -> List[ScoredCandidate]:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT score_json, raw_json FROM fallback_candidates WHERE synced_to_feishu = 0"
        )
        results: List[ScoredCandidate] = []
        for score_json, raw_json in cursor.fetchall():
            score_dict = json.loads(score_json)
            raw_dict = json.loads(raw_json)
            if "score_reasoning" not in score_dict:
                score_dict["score_reasoning"] = score_dict.pop("reasoning", "")
            candidate_data = self._deserialize_raw(raw_dict)
            candidate = ScoredCandidate(**candidate_data, **score_dict)
            results.append(candidate)
        conn.close()
        return results

    async def mark_synced(self, urls: List[str]) -> None:
        """同步成功后更新标记"""

        await asyncio.to_thread(self._mark_synced_sync, urls)

    def _mark_synced_sync(self, urls: Sequence[str]) -> None:
        conn = sqlite3.connect(self.db_path)
        for url in urls:
            conn.execute(
                "UPDATE fallback_candidates SET synced_to_feishu = 1 WHERE url = ?",
                (url,),
            )
        conn.commit()
        conn.close()

    async def cleanup_old_records(
        self, days: int = constants.SQLITE_RETENTION_DAYS
    ) -> None:
        """清理已同步且超过指定天数的记录"""

        await asyncio.to_thread(self._cleanup_sync, days)

    def _cleanup_sync(self, days: int) -> None:
        cutoff = datetime.now() - timedelta(days=days)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "DELETE FROM fallback_candidates WHERE synced_to_feishu = 1 AND created_at < ?",
            (cutoff,),
        )
        conn.commit()
        conn.close()

    @staticmethod
    def _serialize_raw(candidate: ScoredCandidate) -> dict:
        return {
            "title": candidate.title,
            "url": candidate.url,
            "source": candidate.source,
            "abstract": candidate.abstract,
            "authors": candidate.authors,
            "publish_date": (
                candidate.publish_date.isoformat() if candidate.publish_date else None
            ),
            "github_stars": candidate.github_stars,
            "github_url": candidate.github_url,
            "dataset_url": candidate.dataset_url,
            "hero_image_url": candidate.hero_image_url,
            "hero_image_key": candidate.hero_image_key,
            "raw_metadata": candidate.raw_metadata,
            "raw_metrics": candidate.raw_metrics,
            "raw_baselines": candidate.raw_baselines,
            "raw_authors": candidate.raw_authors,
            "raw_institutions": candidate.raw_institutions,
            "raw_dataset_size": candidate.raw_dataset_size,
        }

    @staticmethod
    def _serialize_scores(candidate: ScoredCandidate) -> dict:
        return {
            "activity_score": candidate.activity_score,
            "reproducibility_score": candidate.reproducibility_score,
            "license_score": candidate.license_score,
            "novelty_score": candidate.novelty_score,
            "relevance_score": candidate.relevance_score,
            "score_reasoning": candidate.score_reasoning,
            "custom_total_score": candidate.custom_total_score,
            "task_domain": candidate.task_domain,
            "metrics": candidate.metrics,
            "baselines": candidate.baselines,
            "institution": candidate.institution,
            "dataset_size": candidate.dataset_size,
            "dataset_size_description": candidate.dataset_size_description,
        }

    @staticmethod
    def _deserialize_raw(data: dict) -> dict:
        publish_date = data.get("publish_date")
        if publish_date:
            try:
                data["publish_date"] = datetime.fromisoformat(publish_date)
            except ValueError:
                data["publish_date"] = None
        return data
