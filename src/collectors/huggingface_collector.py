"""HuggingFace 数据集采集器"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from huggingface_hub import HfApi

from src.common import constants
from src.config import Settings, get_settings
from src.models import RawCandidate

logger = logging.getLogger(__name__)


class HuggingFaceCollector:
    """监控 HuggingFace Hub 上的 Benchmark 数据集"""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.cfg = self.settings.sources.huggingface
        self.api = HfApi(token=os.getenv("HUGGINGFACE_TOKEN"))

    async def collect(self) -> List[RawCandidate]:
        """采集符合下载量与关键词要求的数据集"""

        try:
            datasets = await self._fetch_datasets()
        except Exception as exc:  # noqa: BLE001
            logger.error("HuggingFace采集失败: %s", exc)
            return []

        candidates: List[RawCandidate] = []
        for dataset in datasets:
            payload = self._normalize_dataset(dataset)
            if not payload:
                continue
            if not self._is_benchmark_dataset(payload):
                continue

            candidate = self._to_candidate(payload)
            if candidate:
                candidates.append(candidate)

        logger.info("HuggingFace采集完成,候选数%s", len(candidates))
        return candidates

    async def _fetch_datasets(self) -> List[Any]:
        """在线程池执行同步API调用"""

        return await asyncio.to_thread(self._list_datasets)

    def _list_datasets(self) -> List[Any]:
        search_query = " OR ".join(self.cfg.keywords)
        datasets = self.api.list_datasets(
            task_categories=self.cfg.task_categories,
            search=search_query,
            sort="lastModified",
            limit=self.cfg.limit,
        )
        return list(datasets)

    def _normalize_dataset(self, dataset: Any) -> dict[str, Any]:
        """兼容 DatasetInfo/字典,统一输出字典"""

        if dataset is None:
            return {}
        if isinstance(dataset, dict):
            return dataset
        if hasattr(dataset, "to_dict"):
            return dataset.to_dict()
        if hasattr(dataset, "dict"):
            return dataset.dict()
        return getattr(dataset, "__dict__", {})

    def _is_benchmark_dataset(self, data: dict[str, Any]) -> bool:
        """通过下载量与关键词(标题/标签/摘要)判断是否为Benchmark"""

        downloads = int(data.get("downloads") or 0)
        if downloads < self.cfg.min_downloads:
            return False

        summary = self._extract_summary(data).lower()
        dataset_id = (data.get("id") or data.get("_id") or "").lower()
        tags = " ".join((data.get("tags") or []))
        keywords = [kw.lower() for kw in self.cfg.keywords]

        haystacks = [summary, tags.lower(), dataset_id]
        return any(kw in field for kw in keywords for field in haystacks if field)

    def _to_candidate(self, data: dict[str, Any]) -> RawCandidate | None:
        """将数据集信息转换为内部模型

        注意：不对发布时间进行过滤
        原因：优质Benchmark数据集即使发布时间较早也有价值
        过滤依据：下载量 + 关键词匹配（在_is_benchmark_dataset中实现）
        """

        dataset_id = data.get("id") or data.get("_id")
        if not dataset_id:
            return None

        summary = self._extract_summary(data)
        authors = data.get("cardData", {}).get("authors") or data.get("card_data", {}).get("authors")
        publish_date = self._parse_datetime(
            data.get("lastModified")
            or data.get("last_modified")
            or data.get("lastModifiedDate")
        )

        # 不再过滤发布时间 - 让优质数据集不受时间限制
        # 时间过滤更适合GitHub（关注活跃维护）和arXiv（关注最新研究）

        return RawCandidate(
            title=data.get("cardData", {}).get("pretty_name")
            or data.get("card_data", {}).get("pretty_name")
            or dataset_id,
            url=f"https://huggingface.co/datasets/{dataset_id}",
            source="huggingface",
            abstract=summary,
            authors=authors,
            publish_date=publish_date,
            dataset_url=f"https://huggingface.co/datasets/{dataset_id}",
            raw_metadata={
                "downloads": data.get("downloads"),
                "tags": data.get("tags"),
            },
        )

    def _extract_summary(self, data: dict[str, Any]) -> str:
        """读取README摘要或描述"""

        card_data = data.get("cardData") or data.get("card_data") or {}
        for key in ("summary", "description", "short_description"):
            if card_data.get(key):
                return str(card_data[key])
        return str(data.get("description") or "")

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _is_within_lookback(self, publish_date: datetime) -> bool:
        now = datetime.now(timezone.utc)
        return now - publish_date <= timedelta(days=constants.HUGGINGFACE_LOOKBACK_DAYS)
