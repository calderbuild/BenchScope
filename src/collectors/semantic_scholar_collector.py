"""Semantic Scholar 会议论文采集器"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from src.common import constants
from src.models import RawCandidate

logger = logging.getLogger(__name__)


class SemanticScholarCollector:
    """负责调用Semantic Scholar Graph API抓取顶会Benchmark论文"""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("SEMANTIC_SCHOLAR_API_KEY")
        self.base_url = "https://api.semanticscholar.org/graph/v1/paper/search"
        self.venues = constants.SEMANTIC_SCHOLAR_VENUES
        self.keywords = constants.SEMANTIC_SCHOLAR_KEYWORDS
        self.lookback_years = constants.SEMANTIC_SCHOLAR_LOOKBACK_YEARS
        self.limit = constants.SEMANTIC_SCHOLAR_MAX_RESULTS
        self.timeout = constants.SEMANTIC_SCHOLAR_TIMEOUT_SECONDS

    async def collect(self) -> List[RawCandidate]:
        """采集各顶会近2年的Benchmark论文"""

        if not self.api_key:
            logger.warning("未设置SEMANTIC_SCHOLAR_API_KEY,跳过Semantic Scholar采集")
            return []

        async with httpx.AsyncClient(
            timeout=self.timeout, headers=self._build_headers()
        ) as client:
            tasks = [self._fetch_venue(client, venue) for venue in self.venues]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        candidates: List[RawCandidate] = []
        seen_ids: set[str] = set()
        for venue, result in zip(self.venues, results, strict=False):
            if isinstance(result, BaseException):
                logger.error("Semantic Scholar API任务失败(%s): %s", venue, result)
                continue
            for candidate in result:
                paper_id = candidate.raw_metadata.get("paper_id")
                if paper_id and paper_id in seen_ids:
                    continue
                if paper_id:
                    seen_ids.add(paper_id)
                candidates.append(candidate)

        logger.info("Semantic Scholar采集完成,候选总数%s", len(candidates))
        return candidates

    async def _fetch_venue(
        self, client: httpx.AsyncClient, venue: str
    ) -> List[RawCandidate]:
        """调用API,按会议+关键词筛选论文"""

        params = self._build_query_params(venue)
        try:
            response = await client.get(self.base_url, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("Semantic Scholar请求失败(%s): %s", venue, exc)
            return []

        payload = response.json()
        papers: List[Dict[str, Any]] = payload.get("data", [])
        return [self._to_candidate(paper) for paper in papers if paper]

    def _build_query_params(self, venue: str) -> Dict[str, Any]:
        """构建查询参数,控制会议、关键词和时间窗口"""

        keyword_query = " OR ".join(self.keywords)
        start_year = datetime.now(timezone.utc).year - self.lookback_years
        return {
            "query": f'venue:"{venue}" AND ({keyword_query})',
            "year": f"{start_year}-",
            "limit": self.limit,
            "offset": 0,
            "fields": "paperId,title,url,abstract,authors,venue,year,citationCount,publicationDate,externalIds,fieldsOfStudy,openAccessPdf",
        }

    def _to_candidate(self, paper: Dict[str, Any]) -> RawCandidate:
        """将API返回转换为内部RawCandidate结构"""

        publish_date = self._parse_publish_date(
            paper.get("publicationDate"), paper.get("year")
        )
        authors = [
            item.get("name") for item in paper.get("authors", []) if item.get("name")
        ]

        paper_url = paper.get("url")

        fields_of_study = paper.get("fieldsOfStudy") or []
        fields_str = (
            ",".join(str(item) for item in fields_of_study) if fields_of_study else ""
        )
        raw_metadata = {
            "paper_id": str(paper.get("paperId") or ""),
            "venue": str(paper.get("venue") or ""),
            "year": str(paper.get("year") or ""),
            "citation_count": str(paper.get("citationCount") or ""),
            "fields_of_study": fields_str,
            "open_access_pdf": str((paper.get("openAccessPdf") or {}).get("url") or ""),
        }

        return RawCandidate(
            title=paper.get("title") or "",
            url=paper.get("url") or "",
            source="semantic_scholar",
            abstract=paper.get("abstract"),
            authors=authors or None,
            publish_date=publish_date,
            paper_url=paper_url,
            raw_metadata=raw_metadata,
        )

    @staticmethod
    def _parse_publish_date(
        date_str: Optional[str], year: Optional[int]
    ) -> Optional[datetime]:
        """解析发布日期,兜底使用年份"""

        if date_str:
            try:
                return datetime.fromisoformat(
                    date_str.replace("Z", "+00:00")
                ).astimezone(timezone.utc)
            except ValueError:
                logger.debug("Semantic Scholar日期格式异常:%s", date_str)
        if year:
            try:
                return datetime(int(year), 1, 1, tzinfo=timezone.utc)
            except (TypeError, ValueError):
                return None
        return None

    def _build_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Accept": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers
