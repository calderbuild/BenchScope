"""HELM 榜单采集器"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from src.common import constants
from src.models import RawCandidate

logger = logging.getLogger(__name__)


class HelmCollector:
    """从HELM官方存储中提取场景信息"""

    def __init__(self) -> None:
        self.config_url = constants.HELM_CONFIG_URL
        self.base_page = constants.HELM_BASE_PAGE
        self.storage_base = constants.HELM_STORAGE_BASE
        self.default_release = constants.HELM_DEFAULT_RELEASE
        self.timeout = constants.HELM_TIMEOUT_SECONDS

    async def collect(self) -> List[RawCandidate]:
        """拉取最新release并解析场景数据"""

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            release = await self._fetch_release(client)
            summary = await self._fetch_summary(client, release)
            groups = await self._fetch_groups(client, release)

        publish_date = self._parse_release_date(summary.get("date")) if summary else None
        candidates = self._parse_groups(groups or [], release, publish_date)
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

    async def _fetch_summary(self, client: httpx.AsyncClient, release: str) -> Dict[str, Any] | None:
        url = f"{self.storage_base}/releases/{release}/summary.json"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:  # noqa: BLE001
            logger.warning("获取HELM summary失败(%s): %s", release, exc)
            return None

    async def _fetch_groups(self, client: httpx.AsyncClient, release: str) -> List[Dict[str, Any]] | None:
        url = f"{self.storage_base}/releases/{release}/groups.json"
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:  # noqa: BLE001
            logger.error("获取HELM groups失败(%s): %s", release, exc)
            return None

    def _parse_groups(
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

        for section in sections:
            title = section.get("title", "")
            # "All scenarios"只是目录,实际字段在后续分组中重复,可直接跳过
            if title.strip().lower() == "all scenarios":
                continue

            header = [col.get("value") for col in section.get("header", [])]
            for row in section.get("rows", []):
                row_dict = self._row_to_dict(header, row)
                group_info = row[0] if row else {}
                group_name = (group_info or {}).get("value")
                if not group_name:
                    continue

                slug = self._extract_slug(group_info.get("href")) or self._slugify(group_name)
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)

                description = row_dict.get("Description") or ""
                adaptation = row_dict.get("Adaptation method") or ""
                models = row_dict.get("# models")

                # 摘要格式优化：截断过长描述，用空格连接避免换行影响飞书表格排版
                abstract_parts = []
                if description:
                    # 截断到200字符，避免摘要过长
                    desc_clean = description.strip()[:200]
                    if len(description) > 200:
                        desc_clean += "..."
                    abstract_parts.append(desc_clean)
                if adaptation:
                    abstract_parts.append(f"适配策略: {adaptation}")
                if models is not None:
                    abstract_parts.append(f"覆盖模型数: {models}")

                # 用" | "分隔，保持单行显示
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
                        raw_metadata={k: v for k, v in metadata.items() if v is not None},
                    )
                )

        return candidates

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
