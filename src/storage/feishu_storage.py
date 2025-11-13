"""飞书多维表格存储实现"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import httpx

from src.common import constants
from src.config import Settings, get_settings
from src.models import ScoredCandidate

logger = logging.getLogger(__name__)


class FeishuAPIError(Exception):
    """飞书API异常"""


class FeishuStorage:
    """负责与飞书多维表格交互"""

    FIELD_MAPPING: Dict[str, str] = {
        # 基础信息
        "title": "标题",
        "source": "来源",
        "url": "URL",
        "abstract": "摘要",
        # 评分维度
        "activity_score": "活跃度",
        "reproducibility_score": "可复现性",
        "license_score": "许可合规",
        "novelty_score": "任务新颖性",
        "relevance_score": "MGX适配度",
        "total_score": "总分",
        "priority": "优先级",
        "reasoning": "评分依据",
        "status": "状态",
        # 新增字段 (Phase 6)
        "paper_url": "论文 URL",
        "github_stars": "GitHub Stars",
        "authors": "作者信息",
        "publish_date": "开源时间",
        "reproduction_script_url": "复现脚本链接",
        "evaluation_metrics": "评价指标摘要",
        "dataset_url": "数据集 URL",
        "task_type": "任务类型",
    }

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = "https://open.feishu.cn/open-apis"
        self.batch_size = constants.FEISHU_BATCH_SIZE
        self.rate_interval = constants.FEISHU_RATE_LIMIT_DELAY
        self.access_token: Optional[str] = None
        self.token_expire_at: Optional[datetime] = None

    async def save(self, candidates: List[ScoredCandidate]) -> None:
        """批量写入飞书多维表格"""

        if not candidates:
            return

        await self._ensure_access_token()

        async with httpx.AsyncClient(timeout=10) as client:
            for start in range(0, len(candidates), self.batch_size):
                chunk = candidates[start : start + self.batch_size]
                records = [self._to_feishu_record(c) for c in chunk]
                await self._batch_create_records(client, records)

                if start + self.batch_size < len(candidates):
                    await asyncio.sleep(self.rate_interval)

    async def _batch_create_records(self, client: httpx.AsyncClient, records: List[dict]) -> None:
        url = (
            f"{self.base_url}/bitable/v1/apps/{self.settings.feishu.bitable_app_token}/"
            f"tables/{self.settings.feishu.bitable_table_id}/records/batch_create"
        )
        try:
            resp = await client.post(url, headers=self._auth_header(), json={"records": records})
            resp.raise_for_status()
            logger.info("飞书批次写入成功: %s条", len(records))
        except httpx.HTTPStatusError as exc:  # noqa: BLE001
            logger.error("飞书写入失败: %s - %s", exc.response.status_code, exc.response.text)
            raise FeishuAPIError("批量写入失败") from exc

    async def _ensure_access_token(self) -> None:
        now = datetime.now()
        if self.access_token and self.token_expire_at and now < self.token_expire_at:
            return

        url = f"{self.base_url}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.settings.feishu.app_id,
            "app_secret": self.settings.feishu.app_secret,
        }

        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            self.access_token = data.get("tenant_access_token")
            expire_seconds = int(data.get("expire", 7200)) - 300
            self.token_expire_at = now + timedelta(seconds=max(expire_seconds, 600))
            logger.info("飞书access_token刷新成功")

    def _auth_header(self) -> dict[str, str]:
        if not self.access_token:
            raise FeishuAPIError("access_token不存在")
        return {"Authorization": f"Bearer {self.access_token}"}

    def _to_feishu_record(self, candidate: ScoredCandidate) -> dict:
        """转换ScoredCandidate为飞书记录格式

        注意事项:
        - URL字段需要对象格式: {"link": "..."}
        - 日期字段转换为字符串格式: "YYYY-MM-DD"
        - 数组字段转换为逗号分隔的字符串
        - 空值使用空字符串或0代替
        """
        fields = {
            # 基础信息
            self.FIELD_MAPPING["title"]: candidate.title,
            self.FIELD_MAPPING["source"]: candidate.source,
            self.FIELD_MAPPING["url"]: {"link": candidate.url},
            self.FIELD_MAPPING["abstract"]: candidate.abstract or "",
            # 评分维度
            self.FIELD_MAPPING["activity_score"]: candidate.activity_score,
            self.FIELD_MAPPING["reproducibility_score"]: candidate.reproducibility_score,
            self.FIELD_MAPPING["license_score"]: candidate.license_score,
            self.FIELD_MAPPING["novelty_score"]: candidate.novelty_score,
            self.FIELD_MAPPING["relevance_score"]: candidate.relevance_score,
            self.FIELD_MAPPING["total_score"]: round(candidate.total_score, 2),
            self.FIELD_MAPPING["priority"]: candidate.priority,
            self.FIELD_MAPPING["reasoning"]: candidate.reasoning[:500] if candidate.reasoning else "",
            self.FIELD_MAPPING["status"]: "pending",
        }

        # 新增字段 (Phase 6) - 谨慎处理空值
        if hasattr(candidate, "paper_url") and candidate.paper_url:
            fields[self.FIELD_MAPPING["paper_url"]] = {"link": candidate.paper_url}

        if hasattr(candidate, "github_stars") and candidate.github_stars is not None:
            fields[self.FIELD_MAPPING["github_stars"]] = candidate.github_stars

        if hasattr(candidate, "authors") and candidate.authors:
            # 作者列表转换为逗号分隔字符串，限制长度
            authors_str = ", ".join(candidate.authors)[:200]
            fields[self.FIELD_MAPPING["authors"]] = authors_str

        if hasattr(candidate, "publish_date") and candidate.publish_date:
            fields[self.FIELD_MAPPING["publish_date"]] = candidate.publish_date.strftime("%Y-%m-%d")

        if hasattr(candidate, "reproduction_script_url") and candidate.reproduction_script_url:
            fields[self.FIELD_MAPPING["reproduction_script_url"]] = {"link": candidate.reproduction_script_url}

        if hasattr(candidate, "evaluation_metrics") and candidate.evaluation_metrics:
            # 评估指标列表转换为逗号分隔字符串
            metrics_str = ", ".join(candidate.evaluation_metrics)[:200]
            fields[self.FIELD_MAPPING["evaluation_metrics"]] = metrics_str

        if hasattr(candidate, "dataset_url") and candidate.dataset_url:
            fields[self.FIELD_MAPPING["dataset_url"]] = {"link": candidate.dataset_url}

        if hasattr(candidate, "task_type") and candidate.task_type:
            fields[self.FIELD_MAPPING["task_type"]] = candidate.task_type

        return {"fields": fields}

    async def get_existing_urls(self) -> set[str]:
        """查询飞书Bitable已存在的所有URL（用于去重）"""
        await self._ensure_access_token()

        existing_urls: set[str] = set()
        page_token = None

        async with httpx.AsyncClient(timeout=10) as client:
            while True:
                url = f"{self.base_url}/bitable/v1/apps/{self.settings.feishu.bitable_app_token}/tables/{self.settings.feishu.bitable_table_id}/records/search"

                # 分页查询所有记录
                payload = {"page_size": 500}
                if page_token:
                    payload["page_token"] = page_token

                resp = await client.post(url, headers=self._auth_header(), json=payload)
                resp.raise_for_status()
                data = resp.json()

                if data.get("code") != 0:
                    raise FeishuAPIError(f"飞书查询失败: {data}")

                # 提取URL字段
                items = data.get("data", {}).get("items", [])
                url_field_name = self.FIELD_MAPPING["url"]

                for item in items:
                    fields = item.get("fields", {})
                    url_obj = fields.get(url_field_name)

                    # 飞书URL字段是对象格式: {"link": "url", "text": "display text"}
                    if isinstance(url_obj, dict):
                        url_value = url_obj.get("link")
                        if url_value:
                            existing_urls.add(url_value)
                    # 兼容旧数据可能是字符串格式
                    elif isinstance(url_obj, str):
                        existing_urls.add(url_obj)

                # 检查是否还有下一页
                has_more = data.get("data", {}).get("has_more", False)
                if not has_more:
                    break

                page_token = data.get("data", {}).get("page_token")
                if not page_token:
                    break

        logger.info("飞书已存在URL数量: %d", len(existing_urls))
        return existing_urls

