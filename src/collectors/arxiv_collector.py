"""arXiv 采集器实现"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import arxiv
import requests

from src.common import constants
from src.common.datetime_utils import ensure_utc, get_retry_delay
from src.common.url_extractor import URLExtractor
from src.config import Settings, get_settings
from src.models import RawCandidate

logger = logging.getLogger(__name__)


class ArxivCollector:
    """负责抓取最近24小时内的Benchmark相关论文"""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        cfg = self.settings.sources.arxiv
        self.enabled = cfg.enabled
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

        retry_delays = constants.ARXIV_RETRY_DELAYS_SECONDS
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                results = await asyncio.to_thread(self._fetch_results)
                return await self._to_candidates(results)
            except (TimeoutError, requests.exceptions.Timeout) as exc:
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                delay = get_retry_delay(attempt, retry_delays)
                logger.warning(
                    "arXiv查询超时,准备重试(%s/%s), 等待%s秒后重试, 错误: %r",
                    attempt,
                    self.max_retries,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                delay = get_retry_delay(attempt, retry_delays)
                logger.error(
                    "arXiv采集失败(%s/%s): %s, %s秒后重试",
                    attempt,
                    self.max_retries,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        logger.error(
            "arXiv连续失败%s次,返回空列表, 超时配置=%s秒, 最后错误: %r",
            self.max_retries,
            self.timeout,
            last_exc,
        )
        return []

    def _fetch_results(self) -> List[arxiv.Result]:
        """同步执行arXiv查询,供线程池调用"""

        class _TimeoutSession(requests.Session):
            """给 requests.Session 注入默认 timeout"""

            def __init__(self, timeout_seconds: int) -> None:
                super().__init__()
                self._timeout_seconds = timeout_seconds

            def request(self, method: str, url: str, **kwargs):  # type: ignore[override]
                kwargs.setdefault("timeout", self._timeout_seconds)
                return super().request(method, url, **kwargs)

        query = " OR ".join([f'all:"{kw}"' for kw in self.keywords])
        cat_filter = " OR ".join([f"cat:{cat}" for cat in self.categories])
        search = arxiv.Search(
            query=f"({query}) AND ({cat_filter})",
            max_results=self.max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        client = arxiv.Client(
            page_size=min(self.max_results, constants.ARXIV_PAGE_SIZE_LIMIT),
            num_retries=0,
        )
        client._session = _TimeoutSession(timeout_seconds=self.timeout)
        return list(client.results(search))

    async def _to_candidates(self, results: List[arxiv.Result]) -> List[RawCandidate]:
        """将arXiv返回转成内部数据结构"""

        cutoff = datetime.now(timezone.utc) - self.lookback
        candidates: List[RawCandidate] = []

        for paper in results:
            published_dt = ensure_utc(paper.published)

            if published_dt and published_dt < cutoff:
                continue

            raw_authors, raw_institutions = self._extract_authors_institutions(paper)
            arxiv_id = paper.entry_id.split("/")[-1].split("v")[0]

            text_to_search = f"{paper.summary or ''}\n{paper.comment or ''}"
            dataset_url = URLExtractor.extract_dataset_url(text_to_search)

            candidates.append(
                RawCandidate(
                    title=paper.title.strip(),
                    url=paper.pdf_url or paper.entry_id,
                    source="arxiv",
                    abstract=paper.summary,
                    authors=[author.name for author in paper.authors],
                    publish_date=paper.published,
                    paper_url=paper.entry_id,
                    dataset_url=dataset_url,
                    raw_authors=raw_authors,
                    raw_institutions=raw_institutions,
                    raw_metadata={
                        "arxiv_id": arxiv_id,
                        "categories": ",".join(paper.categories or []),
                        "comment": paper.comment or "",
                    },
                    hero_image_url=None,
                    hero_image_key=None,
                )
            )

        logger.info("arXiv采集完成,有效候选%s条", len(candidates))
        return candidates

    @staticmethod
    def _extract_authors_institutions(
        paper: arxiv.Result,
    ) -> Tuple[Optional[str], Optional[str]]:
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

        authors_str = (
            ", ".join(authors[: constants.MAX_EXTRACTED_AUTHORS]) if authors else None
        )
        institutions_str = ", ".join(sorted(institutions)) if institutions else None
        return authors_str, institutions_str
