"""arXiv 版本跟踪器"""
from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import feedparser

from src.models import ArxivVersion

logger = logging.getLogger(__name__)


class ArxivVersionTracker:
    """监控 arXiv 论文版本更新"""

    def __init__(self, db_path: str = "fallback.db") -> None:
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS arxiv_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    arxiv_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    summary TEXT,
                    url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(arxiv_id, version)
                )
                """
            )
            conn.commit()
        logger.debug("arXiv版本表检查完成")

    def _extract_arxiv_id(self, url: str) -> Optional[str]:
        pattern = r"arxiv\.org/abs/(\d{4}\.\d{4,5})"
        match = re.search(pattern, url)
        if match:
            return match.group(1)
        logger.debug("无法解析 arXiv URL: %s", url)
        return None

    async def check_updates(self, arxiv_urls: List[str]) -> List[ArxivVersion]:
        if not arxiv_urls:
            return []

        new_versions: List[ArxivVersion] = []
        tasks = []
        for url in arxiv_urls:
            arxiv_id = self._extract_arxiv_id(url)
            if not arxiv_id:
                continue
            tasks.append(self._fetch_latest_version(arxiv_id))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception) or result is None:
                continue
            if self._is_recorded(result):
                continue
            self._store_version(result)
            new_versions.append(result)
            logger.info("发现arXiv新版本: %s %s", result.arxiv_id, result.version)

        return new_versions

    async def _fetch_latest_version(self, arxiv_id: str) -> Optional[ArxivVersion]:
        url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
        try:
            feed = await asyncio.to_thread(feedparser.parse, url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("arXiv API调用失败(%s): %s", arxiv_id, exc)
            return None

        entries = feed.entries
        if not entries:
            return None

        entry = entries[0]
        entry_id = entry.get("id", "")
        version = self._extract_version(entry_id) or "v1"
        updated = entry.get("updated") or entry.get("published")
        if not updated:
            return None

        updated_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        summary = entry.get("summary", "(无摘要)")
        url = entry.get("link", f"https://arxiv.org/abs/{arxiv_id}{version}")

        return ArxivVersion(
            arxiv_id=arxiv_id,
            version=version,
            updated_at=updated_dt,
            summary=summary.strip(),
            url=url,
        )

    def _extract_version(self, entry_id: str) -> Optional[str]:
        match = re.search(r"v\d+$", entry_id)
        if match:
            return match.group(0)
        return None

    def _is_recorded(self, version: ArxivVersion) -> bool:
        query = "SELECT 1 FROM arxiv_versions WHERE arxiv_id = ? AND version = ? LIMIT 1"
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(query, (version.arxiv_id, version.version)).fetchone()
            return row is not None

    def _store_version(self, version: ArxivVersion) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO arxiv_versions (arxiv_id, version, updated_at, summary, url)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    version.arxiv_id,
                    version.version,
                    version.updated_at.isoformat(),
                    version.summary,
                    version.url,
                ),
            )
            conn.commit()
        logger.debug("记录arXiv版本: %s %s", version.arxiv_id, version.version)
