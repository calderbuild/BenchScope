"""飞书多维表格存储实现"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx

from src.common import clean_summary_text, constants
from src.common.url_utils import canonicalize_url
from src.config import Settings, get_settings
from src.models import ScoredCandidate

logger = logging.getLogger(__name__)


class FeishuAPIError(Exception):
    """飞书API异常"""


class FeishuStorage:
    """负责与飞书多维表格交互"""

    FIELD_MAPPING: Dict[str, str] = {
        # 基础信息组 (5个字段)
        "title": "标题",
        "source": "来源",
        "url": "URL",
        "abstract": "摘要",
        "publish_date": "发布日期",  # 修复: "开源时间" → "发布日期"
        # 评分信息组 (8个字段)
        "activity_score": "活跃度",
        "reproducibility_score": "可复现性",
        "license_score": "许可合规",  # 修复: "许可合规性" → "许可合规"
        "novelty_score": "新颖性",  # 修复: "任务新颖性" → "新颖性"
        "relevance_score": "MGX适配度",
        "total_score": "总分",
        "priority": "优先级",
        "reasoning": "评分依据",
        # Benchmark特征组 (8个字段)
        "task_domain": "任务领域",
        "metrics": "评估指标",  # 修复: "评估指标（结构化）" → "评估指标"
        "baselines": "基准模型",
        "institution": "机构",
        "authors": "作者",
        "dataset_size": "数据集规模",
        "dataset_size_description": "数据集规模描述",
        "dataset_url": "数据集URL",  # 新增：数据集下载链接
        # GitHub信息组 (3个字段)
        "github_stars": "GitHub Stars",
        "github_url": "GitHub URL",
        "license_type": "许可证",  # 修复: "License类型" → "许可证"
    }

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.base_url = "https://open.feishu.cn/open-apis"
        self.batch_size = constants.FEISHU_BATCH_SIZE
        self.rate_interval = constants.FEISHU_RATE_LIMIT_DELAY
        self.access_token: Optional[str] = None
        self.token_expire_at: Optional[datetime] = None
        self._field_names: Optional[set[str]] = None
        self._missing_fields_logged: bool = False
        # 降低 httpx 日志等级，避免批量拉取时刷屏
        logging.getLogger("httpx").setLevel(logging.WARNING)

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """对飞书API请求增加重试，防止偶发超时导致流程中断"""

        timeout = kwargs.pop(
            "timeout",
            constants.FEISHU_HTTP_TIMEOUT_SECONDS,
        )
        delay = constants.FEISHU_HTTP_RETRY_DELAY_SECONDS
        last_error: Optional[Exception] = None

        for attempt in range(1, constants.FEISHU_HTTP_MAX_RETRIES + 1):
            try:
                return await client.request(
                    method,
                    url,
                    timeout=timeout,
                    **kwargs,
                )
            except (httpx.RequestError, httpx.TimeoutException) as exc:
                last_error = exc
                logger.debug(
                    "飞书请求失败(%s %s)第%d次: %s",
                    method,
                    url,
                    attempt,
                    exc,
                )
                if attempt >= constants.FEISHU_HTTP_MAX_RETRIES:
                    break
                await asyncio.sleep(delay)
                delay *= 1.8

        raise FeishuAPIError("飞书请求重试仍失败") from last_error

    async def save(self, candidates: List[ScoredCandidate]) -> None:
        """批量写入飞书多维表格"""

        if not candidates:
            return

        await self._ensure_access_token()
        existing_urls = await self.get_existing_urls()

        # 写入前按URL做二次去重，防止飞书表已有记录导致重复条目
        deduped_candidates: list[ScoredCandidate] = []
        skipped = 0
        for cand in candidates:
            url_key = canonicalize_url(cand.url)
            if url_key and url_key in existing_urls:
                skipped += 1
                continue
            deduped_candidates.append(cand)

        if skipped:
            logger.info("飞书写入前去重: 跳过%d条已存在URL", skipped)

        if not deduped_candidates:
            logger.info("飞书去重后无新增记录，跳过写入")
            return

        async with httpx.AsyncClient(timeout=10) as client:
            for start in range(0, len(deduped_candidates), self.batch_size):
                chunk = deduped_candidates[start : start + self.batch_size]
                records = [self._to_feishu_record(c) for c in chunk]
                try:
                    await self._batch_create_records(client, records)
                except FeishuAPIError as exc:
                    if "access_token不存在" in str(exc):
                        logger.warning("飞书写入token失效，自动刷新后重试当前批次")
                        await self._ensure_access_token()
                        await self._batch_create_records(client, records)
                    else:
                        raise

                # 将当前批次加入缓存，避免同一次运行内的重复
                for cand in chunk:
                    url_key = canonicalize_url(cand.url)
                    if url_key:
                        existing_urls.add(url_key)

                if start + self.batch_size < len(deduped_candidates):
                    await asyncio.sleep(self.rate_interval)

    async def _batch_create_records(
        self, client: httpx.AsyncClient, records: List[dict]
    ) -> None:
        url = (
            f"{self.base_url}/bitable/v1/apps/{self.settings.feishu.bitable_app_token}/"
            f"tables/{self.settings.feishu.bitable_table_id}/records/batch_create"
        )
        try:
            await self._ensure_field_cache(client)

            filtered_records = [
                {"fields": self._filter_existing_fields(record["fields"])}
                for record in records
            ]

            # 如果全部字段都被过滤掉，直接跳过，避免提交空记录
            filtered_records = [record for record in filtered_records if record["fields"]]
            if not filtered_records:
                logger.error("飞书表字段缺失，导致本批次无可写字段，已终止写入")
                raise FeishuAPIError("飞书表字段缺失，导致写入记录为空")

            resp = await self._request_with_retry(
                client,
                "POST",
                url,
                headers=self._auth_header(),
                json={"records": filtered_records},
            )
            resp.raise_for_status()

            # 检查飞书API业务错误码
            data = resp.json()
            code = data.get("code")
            msg = data.get("msg", "")

            if code != 0:
                # 飞书API业务层面错误
                logger.error("飞书API业务错误: code=%s, msg=%s", code, msg)
                logger.error("请求payload前3条记录: %s", records[:3])
                raise FeishuAPIError(f"飞书API返回错误: {code} - {msg}")

            # 检查实际写入的记录数
            created_records = data.get("data", {}).get("records", [])
            actual_count = len(created_records)
            expected_count = len(filtered_records)

            if actual_count != expected_count:
                logger.warning(
                    "飞书写入数量不匹配: 预期%s条,实际%s条",
                    expected_count,
                    actual_count,
                )

            logger.info(
                "飞书批次写入成功: %s条 (实际创建%s条)",
                len(filtered_records),
                actual_count,
            )

        except httpx.HTTPStatusError as exc:
            logger.error(
                "飞书写入HTTP错误: %s - %s", exc.response.status_code, exc.response.text
            )
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

        async with httpx.AsyncClient() as client:
            resp = await self._request_with_retry(
                client,
                "POST",
                url,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            token = data.get("tenant_access_token")
            if not token:
                raise FeishuAPIError("飞书token获取失败，返回空token")
            self.access_token = token
            expire_seconds = int(data.get("expire", 7200)) - 300
            self.token_expire_at = now + timedelta(seconds=max(expire_seconds, 600))
            logger.info("飞书access_token刷新成功")

    def _auth_header(self) -> dict[str, str]:
        if not self.access_token:
            raise FeishuAPIError("access_token不存在")
        return {"Authorization": f"Bearer {self.access_token}"}

    def _filter_existing_fields(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        if not self._field_names:
            return fields
        filtered = {
            name: value for name, value in fields.items() if name in self._field_names
        }
        if not self._missing_fields_logged:
            missing = set(fields.keys()) - set(filtered.keys())
            if missing:
                logger.warning(
                    "飞书表缺少以下字段，已跳过写入: %s",
                    ", ".join(sorted(missing)),
                )
            self._missing_fields_logged = True
        return filtered

    async def _ensure_field_cache(self, client: httpx.AsyncClient) -> None:
        if self._field_names is not None:
            return

        # 防御性校验：使用前再确保token存在，避免并发/实例重建导致的空token
        await self._ensure_access_token()

        url = (
            f"{self.base_url}/bitable/v1/apps/{self.settings.feishu.bitable_app_token}/"
            f"tables/{self.settings.feishu.bitable_table_id}/fields"
        )
        params: Dict[str, Any] = {"page_size": 500}
        headers = self._auth_header()
        field_names: set[str] = set()

        seen_tokens: set[str] = set()
        max_pages = 100
        page_count = 0
        while page_count < max_pages:
            page_count += 1
            resp = await self._request_with_retry(
                client,
                "GET",
                url,
                headers=headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            data_obj = data.get("data") or {}
            items = data_obj.get("items") or []
            has_more = bool(data_obj.get("has_more"))

            count_before = len(field_names)
            for item in items:
                name = item.get("field_name")
                if name:
                    field_names.add(name)
            page_token = data_obj.get("page_token")
            added_fields = len(field_names) - count_before

            if not page_token or not has_more:
                break
            if added_fields == 0 or page_token in seen_tokens:
                logger.warning(
                    "飞书字段分页返回空结果或重复token(%s)，终止翻页",
                    page_token,
                )
                break

            seen_tokens.add(page_token)
            params["page_token"] = page_token

        if page_count >= max_pages:
            logger.warning(
                "飞书字段分页达到最大次数限制(%d)，可能存在异常响应",
                max_pages,
            )

        self._field_names = field_names
        self._validate_required_fields()

    def _validate_required_fields(self) -> None:
        """确保飞书表包含核心字段，缺失时立即失败并降级到SQLite。"""

        if not self._field_names:
            return

        missing = {
            name for name in constants.FEISHU_REQUIRED_FIELDS if name not in self._field_names
        }
        if missing:
            logger.error(
                "飞书表缺少必需字段: %s，已阻断写入以避免数据丢失",
                ", ".join(sorted(missing)),
            )
            raise FeishuAPIError("飞书表缺少必需字段，请检查表结构")

    @staticmethod
    def _clean_abstract(text: str | None, max_length: int | None = None) -> str:
        """清理摘要文本，优化飞书表格显示

        - 移除换行符，用空格替代
        - 清除HTML/Markdown噪声（图片、注释、标签）
        - 限制长度（可选）
        """
        cleaned = clean_summary_text(text, max_length=max_length)
        if not cleaned:
            return ""

        for char in ["**", "__", "##", "```"]:
            cleaned = cleaned.replace(char, "")

        return cleaned

    def _to_feishu_record(self, candidate: ScoredCandidate) -> dict:
        """转换ScoredCandidate为飞书记录格式

        注意事项:
        - URL字段需要对象格式: {"link": "..."}
        - 日期字段转换为字符串格式: "YYYY-MM-DD"
        - 数组字段转换为逗号分隔的字符串
        - 空值使用空字符串或0代替
        - 摘要字段清理换行符和长度，优化表格显示
        """
        fields = {
            # 基础信息
            self.FIELD_MAPPING["title"]: candidate.title,
            self.FIELD_MAPPING["source"]: candidate.source,
            self.FIELD_MAPPING["url"]: {"link": candidate.url},
            self.FIELD_MAPPING["abstract"]: self._clean_abstract(candidate.abstract),
            # 评分维度
            self.FIELD_MAPPING["activity_score"]: candidate.activity_score,
            self.FIELD_MAPPING[
                "reproducibility_score"
            ]: candidate.reproducibility_score,
            self.FIELD_MAPPING["license_score"]: candidate.license_score,
            self.FIELD_MAPPING["novelty_score"]: candidate.novelty_score,
            self.FIELD_MAPPING["relevance_score"]: candidate.relevance_score,
            self.FIELD_MAPPING["total_score"]: round(candidate.total_score, 2),
            self.FIELD_MAPPING["priority"]: candidate.priority,
            self.FIELD_MAPPING["reasoning"]: (candidate.reasoning or "")[
                : constants.FEISHU_REASONING_PREVIEW_LENGTH
            ],
        }

        # Phase 8字段 - 谨慎处理空值
        if hasattr(candidate, "github_stars") and candidate.github_stars is not None:
            fields[self.FIELD_MAPPING["github_stars"]] = candidate.github_stars

        if hasattr(candidate, "github_url") and candidate.github_url:
            fields[self.FIELD_MAPPING["github_url"]] = {"link": candidate.github_url}

        if hasattr(candidate, "authors") and candidate.authors:
            # 作者列表转换为逗号分隔字符串，限制长度
            authors_str = ", ".join(candidate.authors)[:200]
            fields[self.FIELD_MAPPING["authors"]] = authors_str

        if hasattr(candidate, "publish_date") and candidate.publish_date:
            # 飞书日期字段需要Unix时间戳(毫秒)
            timestamp_ms = int(candidate.publish_date.timestamp() * 1000)
            fields[self.FIELD_MAPPING["publish_date"]] = timestamp_ms

        if getattr(candidate, "task_domain", None):
            # 飞书多选字段需要数组格式
            task_domain = candidate.task_domain
            if isinstance(task_domain, str):
                # 如果是字符串,按逗号分割为数组
                task_domain_list = [d.strip() for d in task_domain.split(",")]
                fields[self.FIELD_MAPPING["task_domain"]] = task_domain_list
            elif isinstance(task_domain, list):
                # 如果已经是列表,直接使用
                fields[self.FIELD_MAPPING["task_domain"]] = task_domain

        metrics = getattr(candidate, "metrics", None)
        if metrics:
            metrics_str = ", ".join(metrics)[:200]
            fields[self.FIELD_MAPPING["metrics"]] = metrics_str

        baselines = getattr(candidate, "baselines", None)
        if baselines:
            baselines_str = ", ".join(baselines)[:200]
            fields[self.FIELD_MAPPING["baselines"]] = baselines_str

        institution = getattr(candidate, "institution", None)
        if institution:
            fields[self.FIELD_MAPPING["institution"]] = institution[:200]

        if getattr(candidate, "dataset_size", None) is not None:
            fields[self.FIELD_MAPPING["dataset_size"]] = candidate.dataset_size

        dataset_size_description = getattr(candidate, "dataset_size_description", None)
        if dataset_size_description:
            desc = dataset_size_description[:200]
            fields[self.FIELD_MAPPING["dataset_size_description"]] = desc

        if hasattr(candidate, "license_type") and candidate.license_type:
            fields[self.FIELD_MAPPING["license_type"]] = candidate.license_type

        if hasattr(candidate, "dataset_url") and candidate.dataset_url:
            fields[self.FIELD_MAPPING["dataset_url"]] = {"link": candidate.dataset_url}

        if getattr(candidate, "hero_image_url", None):
            fields[self.FIELD_MAPPING["hero_image_url"]] = {
                "link": candidate.hero_image_url
            }

        if getattr(candidate, "hero_image_key", None):
            fields[self.FIELD_MAPPING["hero_image_key"]] = candidate.hero_image_key

        return {"fields": fields}

    async def get_existing_urls(self) -> set[str]:
        """查询飞书Bitable已存在的所有URL（用于去重）"""
        await self._ensure_access_token()

        existing_urls: set[str] = set()
        page_token = None
        max_pages = 20  # 避免异常has_more导致死循环
        page_count = 0
        seen_tokens: set[str] = set()

        async with httpx.AsyncClient(timeout=10) as client:
            await self._ensure_field_cache(client)
            while True:
                url = f"{self.base_url}/bitable/v1/apps/{self.settings.feishu.bitable_app_token}/tables/{self.settings.feishu.bitable_table_id}/records/search"

                # 分页查询所有记录
                payload = {"page_size": 1000}
                if page_token:
                    payload["page_token"] = page_token

                resp = await self._request_with_retry(
                    client,
                    "POST",
                    url,
                    headers=self._auth_header(),
                    json=payload,
                )
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
                        url_key = canonicalize_url(url_value)
                        if url_key:
                            existing_urls.add(url_key)
                    # 兼容旧数据可能是字符串格式
                    elif isinstance(url_obj, str):
                        url_key = canonicalize_url(url_obj)
                        if url_key:
                            existing_urls.add(url_key)

                # 检查是否还有下一页
                has_more = data.get("data", {}).get("has_more", False)
                if not has_more:
                    break

                page_token = data.get("data", {}).get("page_token")
                if not page_token:
                    break

                # 防御：重复token或超页直接退出，避免刷屏阻塞
                if page_token in seen_tokens:
                    logger.warning("飞书去重分页检测到重复page_token，提前终止以防死循环")
                    break
                seen_tokens.add(page_token)

                page_count += 1
                if page_count >= max_pages:
                    logger.warning(
                        "飞书去重分页超过上限%d，终止以防卡死，已收集URL:%d",
                        max_pages,
                        len(existing_urls),
                    )
                    break

        logger.info("飞书已存在URL数量: %d", len(existing_urls))
        return existing_urls

    async def read_existing_records(self) -> List[dict[str, Any]]:
        """查询飞书已存在的记录，含URL/发布时间/来源，用于时间窗去重"""

        await self._ensure_access_token()

        records: List[dict[str, Optional[datetime]]] = []
        page_token: Optional[str] = None
        url_field = self.FIELD_MAPPING["url"]
        publish_field = self.FIELD_MAPPING["publish_date"]
        max_pages = 20  # 防止无限分页刷请求
        page_count = 0

        async with httpx.AsyncClient(timeout=10) as client:
            await self._ensure_field_cache(client)
            while True:
                url = f"{self.base_url}/bitable/v1/apps/{self.settings.feishu.bitable_app_token}/tables/{self.settings.feishu.bitable_table_id}/records/search"

                payload: Dict[str, Any] = {"page_size": 1000}
                if page_token:
                    payload["page_token"] = page_token

                resp = await self._request_with_retry(
                    client,
                    "POST",
                    url,
                    headers=self._auth_header(),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("code") != 0:
                    raise FeishuAPIError(f"飞书查询失败: {data}")

                items = data.get("data", {}).get("items", [])

                for item in items:
                    fields = item.get("fields", {})
                    url_obj = fields.get(url_field)
                    publish_raw = fields.get(publish_field)

                    # URL字段兼容两种格式
                    if isinstance(url_obj, dict):
                        url_value = url_obj.get("link")
                    elif isinstance(url_obj, str):
                        url_value = url_obj
                    else:
                        url_value = None

                    url_key = canonicalize_url(url_value)
                    publish_date: Optional[datetime] = None
                    if isinstance(publish_raw, (int, float)):
                        # 飞书存的是毫秒时间戳
                        publish_date = datetime.fromtimestamp(publish_raw / 1000)
                    elif isinstance(publish_raw, str) and publish_raw:
                        try:
                            publish_date = datetime.fromisoformat(
                                publish_raw.replace("Z", "+00:00")
                            )
                        except ValueError:
                            logger.debug("无法解析发布时间: %s", publish_raw)

                    if publish_date:
                        publish_date = publish_date.replace(tzinfo=None)

                    if url_key:
                        source_field = self.FIELD_MAPPING.get("source", "来源")
                        source_value = fields.get(source_field, "default")
                        record_item: dict[str, Any] = {
                            "url": str(url_value),
                            "url_key": url_key,
                            "publish_date": publish_date,
                            "source": str(source_value),
                        }
                        records.append(record_item)

                has_more = data.get("data", {}).get("has_more", False)
                if not has_more:
                    break
                page_token = data.get("data", {}).get("page_token")
                if not page_token:
                    break

                page_count += 1
                if page_count >= max_pages:
                    logger.warning("读取飞书记录超出分页上限%d，提前停止以防刷屏", max_pages)
                    break

        logger.info("飞书历史记录读取完成: %d条", len(records))
        return records

    async def read_brief_records(self, fields: Optional[list[str]] = None) -> List[dict[str, Any]]:
        """读取多维表格指定字段，默认返回标题/来源/任务域/总分/发布日期。

        仅用于分析，不影响主流程。包含分页上限保护防止请求过多。
        """

        await self._ensure_access_token()

        target_fields = fields or [
            "title",
            "source",
            "task_domain",
            "total_score",
            "publish_date",
        ]

        field_map = {f: self.FIELD_MAPPING.get(f, f) for f in target_fields}

        page_token: Optional[str] = None
        max_pages = 20
        page_count = 0
        seen_tokens: set[str] = set()

        records: List[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=10) as client:
            await self._ensure_field_cache(client)
            while True:
                url = f"{self.base_url}/bitable/v1/apps/{self.settings.feishu.bitable_app_token}/tables/{self.settings.feishu.bitable_table_id}/records/search"

                payload: Dict[str, Any] = {"page_size": 1000}
                if page_token:
                    payload["page_token"] = page_token

                resp = await self._request_with_retry(
                    client,
                    "POST",
                    url,
                    headers=self._auth_header(),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("code") != 0:
                    raise FeishuAPIError(f"飞书查询失败: {data}")

                items = data.get("data", {}).get("items", [])

                for item in items:
                    fields_data = item.get("fields", {})
                    record: dict[str, Any] = {}
                    for key, feishu_field in field_map.items():
                        value = fields_data.get(feishu_field)
                        if key == "publish_date":
                            record[key] = self._parse_publish_date(value)
                        else:
                            # URL字段可能是对象，标题等为字符串
                            if isinstance(value, dict):
                                record[key] = value.get("link") or value.get("text") or value
                            else:
                                record[key] = value
                    records.append(record)

                has_more = data.get("data", {}).get("has_more", False)
                if not has_more:
                    break

                page_token = data.get("data", {}).get("page_token")
                if not page_token or page_token in seen_tokens:
                    break
                seen_tokens.add(page_token)

                page_count += 1
                if page_count >= max_pages:
                    logger.warning("read_brief_records 超过分页上限%d，提前结束，已获取%d条", max_pages, len(records))
                    break

        logger.info("飞书brief记录读取完成: %d条", len(records))
        return records

    @staticmethod
    def _parse_publish_date(value: Any) -> Optional[datetime]:
        """解析飞书时间字段，兼容时间戳/ISO字符串。"""

        if value is None:
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000)
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None
