"""HELM 榜单采集器"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from src.config import Settings, get_settings
from src.models import RawCandidate

logger = logging.getLogger(__name__)


class HelmCollector:
    """从HELM官方存储中提取场景信息"""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.helm_config = self.settings.sources.helm
        base_page = self.helm_config.base_url.rstrip("/") + "/"
        self.base_page = base_page
        self.config_url = f"{base_page}config.js"
        self.storage_base = self.helm_config.storage_base.rstrip("/")
        self.default_release = self.helm_config.default_release
        self.timeout = self.helm_config.timeout_seconds
        self.allowed_keywords = {
            kw.lower() for kw in self.helm_config.allowed_scenarios
        }
        self.excluded_keywords = {
            kw.lower() for kw in self.helm_config.excluded_scenarios
        }

    async def collect(self) -> List[RawCandidate]:
        """拉取最新release并解析场景数据"""

        if not self.helm_config.enabled:
            logger.info("HELM采集器已禁用,直接返回空列表")
            return []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            release = await self._fetch_release(client)
            summary = await self._fetch_summary(client, release)
            groups = await self._fetch_groups(client, release)

        publish_date = (
            self._parse_release_date(summary.get("date")) if summary else None
        )
        candidates = await self._parse_groups(groups or [], release, publish_date)
        logger.info("HELM采集完成,候选总数%s", len(candidates))
        return candidates

    async def _fetch_release(self, client: httpx.AsyncClient) -> str:
        """读取config.js获取当前release,失败时回退默认值"""

        try:
            resp = await client.get(self.config_url)
            resp.raise_for_status()
            match = re.search(r'window\.RELEASE\s*=\s*"(?P<release>[^"]+)"', resp.text)
            if match:
                return match.group("release")
        except httpx.HTTPError as exc:  # noqa: BLE001
            logger.warning("获取HELM release失败,使用默认值: %s", exc)
        return self.default_release

    async def _fetch_summary(
        self, client: httpx.AsyncClient, release: str
    ) -> Dict[str, Any] | None:
        url = f"{self.storage_base}/releases/{release}/summary.json"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:  # noqa: BLE001
            logger.warning("获取HELM summary失败(%s): %s", release, exc)
            return None

    async def _fetch_groups(
        self, client: httpx.AsyncClient, release: str
    ) -> List[Dict[str, Any]] | None:
        url = f"{self.storage_base}/releases/{release}/groups.json"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:  # noqa: BLE001
            logger.error("获取HELM groups失败(%s): %s", release, exc)
            return None

    async def _parse_groups(
        self,
        sections: List[Dict[str, Any]],
        release: str,
        publish_date: Optional[datetime],
    ) -> List[RawCandidate]:
        """解析group结构并去重输出RawCandidate"""

        if not sections:
            return []

        candidates: List[RawCandidate] = []
        seen_slugs: set[str] = set()

        filtered_count = 0
        total_rows = 0

        for section in sections:
            title = section.get("title", "")
            if title.strip().lower() == "all scenarios":
                continue

            header = [col.get("value") for col in section.get("header", [])]
            for row in section.get("rows", []):
                total_rows += 1
                row_dict = self._row_to_dict(header, row)
                group_info = row[0] if row else {}
                group_name = (group_info or {}).get("value")
                if not group_name:
                    continue

                slug = self._extract_slug(group_info.get("href")) or self._slugify(
                    group_name
                )
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)

                description = row_dict.get("Description") or ""
                if not self._is_relevant_scenario(group_name, description):
                    filtered_count += 1
                    continue
                adaptation = row_dict.get("Adaptation method") or ""
                models = row_dict.get("# models")

                abstract_parts = []
                if description:
                    desc_clean = description.strip()[:200]
                    if len(description) > 200:
                        desc_clean += "..."
                    abstract_parts.append(desc_clean)
                if adaptation:
                    abstract_parts.append(f"适配策略: {adaptation}")
                if models is not None:
                    abstract_parts.append(f"覆盖模型数: {models}")

                abstract = " | ".join(abstract_parts) if abstract_parts else None

                candidate_url = self._build_group_url(slug)
                metadata = {
                    "release": release,
                    "section": title,
                    "adaptation_method": adaptation,
                    "instances": row_dict.get("# instances"),
                    "references": row_dict.get("# references"),
                    "prompt_tokens": row_dict.get("# prompt tokens"),
                    "completion_tokens": row_dict.get("# completion tokens"),
                    "group_slug": slug,
                }

                candidates.append(
                    RawCandidate(
                        title=f"HELM - {group_name}",
                        url=candidate_url,
                        source="helm",
                        abstract=abstract or None,
                        publish_date=publish_date,
                        dataset_url=candidate_url,
                        raw_metadata={
                            k: v for k, v in metadata.items() if v is not None
                        },
                        hero_image_url=None,
                    )
                )

        if total_rows:
            logger.info(
                "HELM任务过滤: 输入%d条,过滤%d条,保留%d条",
                total_rows,
                filtered_count,
                len(candidates),
            )

        return candidates

    def _is_relevant_scenario(self, name: str, description: str) -> bool:
        """判断场景是否与MGX聚焦领域相关"""

        text = f"{name} {description}".lower()

        # 先检查黑名单关键词,避免误保留
        if any(excluded in text for excluded in self.excluded_keywords):
            logger.debug("HELM场景命中黑名单: %s", name)
            return False

        # 必须命中至少一个白名单关键词
        if not any(allowed in text for allowed in self.allowed_keywords):
            logger.debug("HELM场景未命中白名单: %s", name)
            return False

        return True

    @staticmethod
    def _row_to_dict(headers: List[str], row: List[Dict[str, Any]]) -> Dict[str, Any]:
        """将表格行转换为字典,保留原始值"""

        result: Dict[str, Any] = {}
        for header, cell in zip(headers, row, strict=False):
            if not header:
                continue
            value = cell.get("value") if isinstance(cell, dict) else cell
            result[header] = value
        return result

    @staticmethod
    def _extract_slug(href: Optional[str]) -> Optional[str]:
        if not href or "group=" not in href:
            return None
        return href.split("group=")[-1].strip()

    @staticmethod
    def _slugify(name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")

    def _build_group_url(self, slug: str) -> str:
        return f"{self.base_page}?group={slug}" if slug else self.base_page

    @staticmethod
    def _parse_release_date(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        except ValueError:
            return None
