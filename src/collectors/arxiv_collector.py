"""arXiv 采集器实现"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

import arxiv

from src.common import constants
from src.common.url_extractor import URLExtractor
from src.config import Settings, get_settings
from src.models import RawCandidate
from src.extractors import ImageExtractor

logger = logging.getLogger(__name__)


class ArxivCollector:
    """负责抓取最近24小时内的Benchmark相关论文"""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        cfg = self.settings.sources.arxiv
        self.enabled = cfg.enabled
        # Phase 7: arXiv查询策略完全可配置,修改YAML即可调整
        self.keywords = cfg.keywords or constants.ARXIV_KEYWORDS
        self.categories = cfg.categories or constants.ARXIV_CATEGORIES
        self.max_results = cfg.max_results
        self.timeout = cfg.timeout_seconds
        self.max_retries = cfg.max_retries
        self.lookback = timedelta(hours=cfg.lookback_hours)

    async def collect(self) -> List[RawCandidate]:
        """抓取并返回候选列表,失败时返回空列表"""

        if not self.enabled:
            logger.info("arXiv采集器已禁用,直接返回空列表")
            return []

        for attempt in range(1, self.max_retries + 1):
            try:
                async with asyncio.timeout(self.timeout):
                    results = await asyncio.to_thread(self._fetch_results)
                return await self._to_candidates(results)
            except asyncio.TimeoutError:
                logger.warning(
                    "arXiv查询超时,准备重试(%s/%s)", attempt, self.max_retries
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("arXiv采集失败(%s/%s): %s", attempt, self.max_retries, exc)

            await asyncio.sleep(attempt)

        logger.error("arXiv连续失败,返回空列表")
        return []

    def _fetch_results(self) -> List[arxiv.Result]:
        """同步执行arXiv查询,供线程池调用"""

        query = " OR ".join([f'all:"{kw}"' for kw in self.keywords])
        cat_filter = " OR ".join([f"cat:{cat}" for cat in self.categories])
        search = arxiv.Search(
            query=f"({query}) AND ({cat_filter})",
            max_results=self.max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        return list(search.results())

    async def _to_candidates(self, results: List[arxiv.Result]) -> List[RawCandidate]:
        """将arXiv返回转成内部数据结构"""

        from datetime import timezone

        cutoff = datetime.now(timezone.utc) - self.lookback
        candidates: List[RawCandidate] = []

        for paper in results:
            # 确保published是timezone-aware
            published_dt = paper.published
            if published_dt and published_dt.tzinfo is None:
                # 如果是naive datetime，添加UTC时区
                published_dt = published_dt.replace(tzinfo=timezone.utc)

            if published_dt and published_dt < cutoff:
                continue

            raw_authors, raw_institutions = self._extract_authors_institutions(paper)
            arxiv_id = paper.entry_id.split("/")[-1].split("v")[0]

            # 从论文摘要和comment中提取数据集URL
            text_to_search = f"{paper.summary or ''}\n{paper.comment or ''}"
            dataset_url = URLExtractor.extract_dataset_url(text_to_search)

            hero_image_key = None
            cached_pdf = Path(constants.ARXIV_PDF_CACHE_DIR) / f"{arxiv_id}.pdf"
            if cached_pdf.exists():
                hero_image_key = await ImageExtractor.extract_arxiv_image(
                    str(cached_pdf), arxiv_id
                )

            candidates.append(
                RawCandidate(
                    title=paper.title.strip(),
                    url=paper.pdf_url or paper.entry_id,
                    source="arxiv",
                    abstract=paper.summary,
                    authors=[author.name for author in paper.authors],
                    publish_date=paper.published,
                    paper_url=paper.entry_id,  # arXiv论文页面链接
                    dataset_url=dataset_url,  # 新增：从摘要提取数据集URL
                    raw_authors=raw_authors,
                    raw_institutions=raw_institutions,
                    raw_metadata={
                        "arxiv_id": arxiv_id,
                        "categories": ",".join(paper.categories or []),
                        "comment": paper.comment or "",
                    },
                    hero_image_url=None,
                    hero_image_key=hero_image_key,
                )
            )

        logger.info("arXiv采集完成,有效候选%s条", len(candidates))
        return candidates

    @staticmethod
    def _extract_authors_institutions(paper: arxiv.Result) -> Tuple[Optional[str], Optional[str]]:
        """提取arXiv作者与机构信息"""

        authors: List[str] = []
        institutions: set[str] = set()

        for author in getattr(paper, "authors", []) or []:
            name = getattr(author, "name", "") or ""
            name = name.strip()
            if name:
                authors.append(name)

            affiliation = getattr(author, "affiliation", None)
            aff_text = ""
            if isinstance(affiliation, str):
                aff_text = affiliation
            elif affiliation is not None:
                aff_text = getattr(affiliation, "name", "") or ""
            aff_text = aff_text.strip()
            if aff_text:
                institutions.add(aff_text)

        authors_str = ", ".join(authors[: constants.MAX_EXTRACTED_AUTHORS]) if authors else None
        institutions_str = ", ".join(sorted(institutions)) if institutions else None
        return authors_str, institutions_str
