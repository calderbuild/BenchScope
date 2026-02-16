"""HuggingFace 数据集采集器"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional

import httpx

from src.common import constants
from src.config import Settings, get_settings
from src.models import RawCandidate

logger = logging.getLogger(__name__)

HF_DATASETS_EXPAND_FIELDS: tuple[str, ...] = (
    "downloads",
    "tags",
    "lastModified",
    "cardData",
    "description",
)


class HuggingFaceCollector:
    """监控 HuggingFace Hub 上的 Benchmark 数据集"""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.cfg = self.settings.sources.huggingface
        self.api_url = self.cfg.api_url or constants.HUGGINGFACE_DATASETS_API_URL
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.cfg.timeout_seconds),
            headers=self._build_headers(),
            follow_redirects=True,
        )

    def _build_headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.cfg.token:
            headers["Authorization"] = f"Bearer {self.cfg.token}"
        return headers

    async def aclose(self) -> None:
        if not self.http_client.is_closed:
            await self.http_client.aclose()

    async def __aenter__(self) -> "HuggingFaceCollector":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.aclose()

    async def collect(self) -> List[RawCandidate]:
        """采集符合下载量与关键词要求的数据集"""

        if not self.cfg.enabled:
            logger.info("HuggingFace采集器已禁用,直接返回空列表")
            await self.aclose()
            return []

        try:
            datasets = await self._fetch_datasets()
            candidates = self._build_candidates(datasets)
            logger.info("HuggingFace采集完成,候选数%s", len(candidates))
            return candidates
        except httpx.TimeoutException as exc:
            logger.error(
                "HuggingFace采集超时: %s, 超时配置=%s秒",
                exc,
                self.cfg.timeout_seconds,
            )
            return []
        except httpx.NetworkError as exc:
            logger.error(
                "HuggingFace网络错误: %s, 请检查网络连接或HuggingFace服务状态, 超时配置=%s秒",
                exc,
                self.cfg.timeout_seconds,
            )
            return []
        except Exception as exc:  # noqa: BLE001
            logger.error("HuggingFace采集失败: %s", exc, exc_info=True)
            return []
        finally:
            await self.aclose()

    def _build_candidates(self, datasets: List[dict[str, Any]]) -> List[RawCandidate]:
        """将原始数据集列表转换为候选项列表"""

        candidates: List[RawCandidate] = []
        for dataset in datasets:
            payload = self._normalize_dataset(dataset)
            if not payload:
                continue
            if not self._is_benchmark_dataset(payload):
                continue

            candidate = self._to_candidate(payload)
            if not candidate:
                continue
            candidates.append(candidate)
        return candidates

    async def _fetch_datasets(self) -> List[dict[str, Any]]:
        """通过HuggingFace API搜索数据集并合并去重"""

        all_datasets: List[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for keyword in self.cfg.keywords:
            keyword = str(keyword or "").strip()
            if not keyword:
                continue
            datasets = await self._fetch_datasets_by_keyword(keyword)
            for ds in datasets:
                ds_id = str(ds.get("id") or ds.get("_id") or "")
                if ds_id and ds_id not in seen_ids:
                    seen_ids.add(ds_id)
                    all_datasets.append(ds)

        return all_datasets

    async def _fetch_datasets_by_keyword(self, keyword: str) -> List[dict[str, Any]]:
        """按关键词搜索数据集"""

        params: dict[str, Any] = {
            "search": keyword,
            "sort": "lastModified",
            "direction": -1,
            "limit": self.cfg.limit,
            "expand": list(HF_DATASETS_EXPAND_FIELDS),
        }

        resp = await self._get_with_retry(params=params)
        payload = resp.json()
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    async def _get_with_retry(self, params: dict[str, Any]) -> httpx.Response:
        """带重试的GET请求"""

        last_exc: Exception | None = None
        for attempt in range(1, constants.HUGGINGFACE_HTTP_MAX_RETRIES + 1):
            try:
                resp = await self.http_client.get(self.api_url, params=params)
                resp.raise_for_status()
                return resp
            except (httpx.TimeoutException, httpx.NetworkError) as exc:  # noqa: PERF203
                last_exc = exc
                if attempt >= constants.HUGGINGFACE_HTTP_MAX_RETRIES:
                    raise
                delay = constants.HUGGINGFACE_HTTP_RETRY_DELAY_SECONDS * attempt
                logger.warning(
                    "HuggingFace请求失败,准备重试(%s/%s), 等待%s秒, 错误: %r",
                    attempt,
                    constants.HUGGINGFACE_HTTP_MAX_RETRIES,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)

        raise RuntimeError(f"HuggingFace请求失败: {last_exc!r}")

    def _normalize_dataset(self, dataset: Any) -> dict[str, Any]:
        """兼容 DatasetInfo/字典,统一输出字典"""

        if dataset is None:
            return {}
        if isinstance(dataset, dict):
            return dataset
        if hasattr(dataset, "to_dict"):
            return dataset.to_dict()
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
        """将数据集信息转换为内部模型（不过滤发布时间，优质数据集不受时间限制）"""

        dataset_id = data.get("id") or data.get("_id")
        if not dataset_id:
            return None

        summary = self._extract_summary(data)
        card_data = data.get("cardData") or data.get("card_data") or {}
        authors_field = card_data.get("authors")
        authors: Optional[List[str]] = None
        if isinstance(authors_field, list):
            authors = [str(item) for item in authors_field if item]
        elif isinstance(authors_field, str):
            authors = [authors_field]
        publish_date = self._parse_datetime(
            data.get("lastModified")
            or data.get("last_modified")
            or data.get("lastModifiedDate")
        )

        tags = data.get("tags") or []
        task_tags = [t for t in tags if t.startswith("task_categories:")]
        task_type = task_tags[0].replace("task_categories:", "") if task_tags else None

        raw_metadata = {
            "downloads": str(data.get("downloads") or ""),
            "tags": ",".join(str(tag) for tag in (data.get("tags") or [])),
        }

        return RawCandidate(
            title=card_data.get("pretty_name") or dataset_id,
            url=f"https://huggingface.co/datasets/{dataset_id}",
            source="huggingface",
            abstract=summary,
            authors=authors,
            publish_date=publish_date,
            dataset_url=f"https://huggingface.co/datasets/{dataset_id}",
            task_type=task_type,
            raw_metadata=raw_metadata,
        )

    def _extract_summary(self, data: dict[str, Any]) -> str:
        """读取README摘要或描述"""

        card_data = data.get("cardData") or data.get("card_data") or {}
        for key in ("summary", "description", "short_description"):
            if card_data.get(key):
                return str(card_data[key])
        return str(data.get("description") or "")

    @staticmethod
    def _parse_datetime(value: str | int | datetime | None) -> datetime | None:
        """解析时间戳：支持 ISO 8601 字符串、Unix 时间戳、datetime 对象"""

        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, int):
            try:
                return datetime.fromtimestamp(value, tz=timezone.utc)
            except (ValueError, OSError):
                return None
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

