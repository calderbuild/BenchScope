"""DB-Engines 数据库排名采集器"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

import httpx
from bs4 import BeautifulSoup

from src.common import constants
from src.config import Settings, get_settings
from src.models import RawCandidate

logger = logging.getLogger(__name__)


class DBEnginesCollector:
    """抓取 DB-Engines 排名,产出数据库性能相关候选"""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        cfg = self.settings.sources.dbengines
        self.enabled = cfg.enabled
        self.base_url = cfg.base_url or constants.DBENGINES_BASE_URL
        self.timeout = cfg.timeout_seconds
        self.max_results = cfg.max_results

    async def collect(self) -> List[RawCandidate]:
        """采集候选列表"""

        if not self.enabled:
            logger.info("DB-Engines采集器已禁用,跳过")
            return []

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}/ranking")
                resp.raise_for_status()
        except httpx.TimeoutException:
            logger.error("DB-Engines请求超时(>%ss)", self.timeout)
            return []
        except httpx.HTTPError as exc:
            logger.error("DB-Engines请求失败: %s", exc)
            return []
        except Exception as exc:  # noqa: BLE001
            logger.error("DB-Engines采集异常: %s", exc, exc_info=True)
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.select_one("table.dbi")
        if not table:
            logger.warning("DB-Engines页面结构变化,未找到排名表")
            return []

        rows = [
            row
            for row in table.select("tr")
            if row.select_one("td") and row.select_one("th.pad-l")
        ]
        if not rows:
            logger.warning("DB-Engines页面结构变化,未匹配到数据行")
            return []

        candidates: List[RawCandidate] = []
        for idx, row in enumerate(rows[: self.max_results]):
            candidate = self._parse_row(row, idx)
            if candidate:
                candidates.append(candidate)

        logger.info("DB-Engines采集完成,有效候选%d条", len(candidates))
        return candidates

    def _parse_row(self, row: Any, idx: int) -> Optional[RawCandidate]:
        """解析单行排名数据"""

        rank_cell = row.select_one("td:nth-of-type(1)")
        name_cell = row.select_one("th.pad-l a")
        type_cell = row.select_one("th.pad-r")
        score_cell = row.select_one("td.pad-l")

        if not all([rank_cell, name_cell, type_cell, score_cell]):
            return None

        rank_text = (rank_cell.text or "").strip()
        db_name = (name_cell.text or "").strip()
        db_type = (type_cell.text or "").strip()
        score_text = (score_cell.text or "").strip()
        detail_href = name_cell.get("href", "")
        detail_url = self._normalize_url(detail_href)

        description = (
            f"DB-Engines 排名第 {rank_text} 名的 {db_type} 数据库 {db_name}。\n"
            f"流行度评分: {score_text}。查看详情可获取性能评测、技术资料与使用案例。"
        )

        raw_metadata = {
            "database": db_name,
            "type": db_type,
            "ranking_score": score_text,
            "rank": rank_text,
            "detail_url": detail_url,
        }

        return RawCandidate(
            title=f"DB-Engines - {db_name} Benchmark",
            url=detail_url or f"{self.base_url}/ranking",
            source="dbengines",
            abstract=description,
            publish_date=self._get_ranking_update_date(),
            raw_metadata=raw_metadata,
        )

    def _normalize_url(self, href: str) -> str:
        """将相对路径转换为完整URL"""

        if not href:
            return f"{self.base_url}/ranking"
        if href.startswith(("http://", "https://")):
            return href
        if not href.startswith("/"):
            return f"{self.base_url}/{href}"
        return f"{self.base_url.rstrip('/')}{href}"

    @staticmethod
    def _get_ranking_update_date() -> datetime:
        """DB-Engines 每月更新,使用当月1日作为发布日期"""

        now = datetime.now(timezone.utc)
        return datetime(now.year, now.month, 1, tzinfo=timezone.utc)
