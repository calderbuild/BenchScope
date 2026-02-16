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

    @staticmethod
    def _format_url(url: Optional[str]) -> Optional[Dict[str, str]]:
        """格式化URL为飞书链接格式"""
        return {"link": url} if url else None

    @staticmethod
    def _truncate_str(value: Optional[str], max_len: int = 200) -> Optional[str]:
        """截断字符串到指定长度"""
        return value[:max_len] if value else None

    @staticmethod
    def _list_to_str(items: Optional[List[str]], max_len: int = 200) -> Optional[str]:
        """将列表转为逗号分隔字符串并截断"""
        if not items:
            return None
        return ", ".join(items)[:max_len]

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        """对飞书API请求增加重试，针对429限流使用更长指数退避

        重试策略：
        - 普通错误：指数退避 2→3.6→6.5→... 秒
        - 429限流：额外等待10秒 + 指数退避，最长30秒
        - 最多重试5次，总等待时间可达90秒
        """

        timeout = kwargs.pop(
            "timeout",
            constants.FEISHU_HTTP_TIMEOUT_SECONDS,
        )
        delay = constants.FEISHU_HTTP_RETRY_DELAY_SECONDS
        max_delay = constants.FEISHU_HTTP_MAX_RETRY_DELAY_SECONDS
        last_error: Optional[Exception] = None

        for attempt in range(1, constants.FEISHU_HTTP_MAX_RETRIES + 1):
            try:
                resp = await client.request(
                    method,
                    url,
                    timeout=timeout,
                    **kwargs,
                )

                # 针对429限流错误特殊处理
                if resp.status_code == 429:
                    if attempt >= constants.FEISHU_HTTP_MAX_RETRIES:
                        logger.error(
                            "飞书API限流(429)重试%d次仍失败: %s",
                            attempt,
                            url,
                        )
                        resp.raise_for_status()

                    # 429错误使用更长的退避时间：基础延迟 + 额外等待
                    wait_time = min(
                        delay + constants.FEISHU_HTTP_429_EXTRA_DELAY_SECONDS,
                        max_delay,
                    )
                    logger.warning(
                        "飞书API限流(429)，等待%.1f秒后重试(%d/%d): %s",
                        wait_time,
                        attempt,
                        constants.FEISHU_HTTP_MAX_RETRIES,
                        url,
                    )
                    await asyncio.sleep(wait_time)
                    delay = min(delay * 2, max_delay)  # 指数退避
                    continue

                return resp

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
                delay = min(delay * 1.8, max_delay)

        raise FeishuAPIError("飞书请求重试仍失败") from last_error

    async def save(self, candidates: List[ScoredCandidate]) -> List[ScoredCandidate]:
        """批量写入飞书多维表格

        Args:
            candidates: 待写入的候选列表

        Returns:
            实际成功写入的候选列表（用于后续通知）
        """

        if not candidates:
            return []

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
            return []

        actually_saved: list[ScoredCandidate] = []

        async with httpx.AsyncClient(timeout=10) as client:
            for start in range(0, len(deduped_candidates), self.batch_size):
                chunk = deduped_candidates[start : start + self.batch_size]
                records = [self._to_feishu_record(c) for c in chunk]
                try:
                    created_count, expected_count = (
                        await self._batch_create_records_with_count(client, records)
                    )
                except FeishuAPIError as exc:
                    if "access_token不存在" in str(exc):
                        logger.warning("飞书写入token失效，自动刷新后重试当前批次")
                        await self._ensure_access_token()
                        created_count, expected_count = (
                            await self._batch_create_records_with_count(client, records)
                        )
                    else:
                        raise
                except Exception:
                    # 未知异常直接跳过当前批次，避免影响后续流程
                    logger.exception("飞书批次写入出现异常，已跳过当前批次")
                    created_count = -1
                    expected_count = len(chunk)

                # 仅在完全成功时返回并更新缓存；部分成功不纳入通知列表
                if created_count == expected_count == len(chunk):
                    actually_saved.extend(chunk)
                    for cand in chunk:
                        url_key = canonicalize_url(cand.url)
                        if url_key:
                            existing_urls.add(url_key)
                else:
                    logger.warning(
                        "飞书批次写入未完全成功: 预期%d条, 成功%d条",
                        len(chunk),
                        created_count,
                    )

                if start + self.batch_size < len(deduped_candidates):
                    await asyncio.sleep(self.rate_interval)

        logger.info(
            "飞书写入完成: 去重后待写入%d条, 实际成功%d条",
            len(deduped_candidates),
            len(actually_saved),
        )
        return actually_saved

    async def _batch_create_records_with_count(
        self, client: httpx.AsyncClient, records: List[dict]
    ) -> tuple[int, int]:
        """批量创建记录并返回(实际创建数, 预期创建数)

        P14: 返回实际成功数量，便于调用方与通知保持一致
        """
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
            filtered_records = [
                record for record in filtered_records if record["fields"]
            ]
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
                "飞书批次写入完成: %s条 (实际创建%s条)",
                len(filtered_records),
                actual_count,
            )
            return actual_count, expected_count

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
                # 打印飞书业务错误码，便于定位 app_id/app_secret/租户问题；不输出敏感字段
                code = data.get("code")
                msg = data.get("msg")
                if code or msg:
                    logger.error("飞书token获取失败: code=%s, msg=%s", code, msg)
                raise FeishuAPIError("飞书token获取失败，返回空token")
            self.access_token = token
            expire_seconds = int(data.get("expire", 7200)) - 300
            self.token_expire_at = now + timedelta(seconds=max(expire_seconds, 600))
            logger.info("飞书access_token刷新成功")

    def _auth_header(self) -> dict[str, str]:
        if not self.access_token:
            raise FeishuAPIError("access_token不存在")
        return {"Authorization": f"Bearer {self.access_token}"}

    async def _paginated_fetch(
        self,
        client: httpx.AsyncClient,
        max_pages: int = 20,
        page_size: int = 500,
    ) -> List[dict]:
        """通用分页获取飞书记录

        Args:
            client: httpx客户端
            max_pages: 最大分页数，防止无限循环
            page_size: 每页记录数

        Returns:
            所有items列表
        """
        all_items: List[dict] = []
        page_token: Optional[str] = None
        page_count = 0

        while True:
            url = (
                f"{self.base_url}/bitable/v1/apps/"
                f"{self.settings.feishu.bitable_app_token}/tables/"
                f"{self.settings.feishu.bitable_table_id}/records"
            )

            params: Dict[str, Any] = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token

            resp = await self._request_with_retry(
                client,
                "GET",
                url,
                headers=self._auth_header(),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                raise FeishuAPIError(f"飞书查询失败: {data}")

            items = data.get("data", {}).get("items", [])
            all_items.extend(items)

            has_more = data.get("data", {}).get("has_more", False)
            if not has_more:
                break

            page_token = data.get("data", {}).get("page_token")
            if not page_token:
                break

            page_count += 1
            if page_count >= max_pages:
                logger.warning(
                    "飞书分页超过上限%d，已获取%d条记录",
                    max_pages,
                    len(all_items),
                )
                break

        return all_items

    def _filter_existing_fields(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        if not self._field_names:
            return fields
        filtered = {
            name: value for name, value in fields.items() if name in self._field_names
        }
        if not self._missing_fields_logged:
            missing = fields.keys() - filtered.keys()
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
            name
            for name in constants.FEISHU_REQUIRED_FIELDS
            if name not in self._field_names
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
        - 日期字段转换为Unix时间戳(毫秒)
        - 数组字段转换为逗号分隔的字符串
        - 空值使用空字符串或0代替
        - 摘要字段清理换行符和长度，优化表格显示
        """
        FM = self.FIELD_MAPPING  # 简化访问

        fields = {
            # 基础信息
            FM["title"]: candidate.title,
            FM["source"]: candidate.source,
            FM["url"]: {"link": candidate.url},
            FM["abstract"]: self._clean_abstract(candidate.abstract),
            # 评分维度
            FM["activity_score"]: candidate.activity_score,
            FM["reproducibility_score"]: candidate.reproducibility_score,
            FM["license_score"]: candidate.license_score,
            FM["novelty_score"]: candidate.novelty_score,
            FM["relevance_score"]: candidate.relevance_score,
            FM["total_score"]: round(candidate.total_score, 2),
            FM["priority"]: candidate.priority,
            FM["reasoning"]: (candidate.reasoning or "")[
                : constants.FEISHU_REASONING_PREVIEW_LENGTH
            ],
        }

        # 可选字段：使用辅助方法简化
        if candidate.github_stars is not None:
            fields[FM["github_stars"]] = candidate.github_stars

        if url := self._format_url(candidate.github_url):
            fields[FM["github_url"]] = url

        if authors_str := self._list_to_str(candidate.authors):
            fields[FM["authors"]] = authors_str

        if candidate.publish_date:
            fields[FM["publish_date"]] = int(candidate.publish_date.timestamp() * 1000)

        # 任务领域：支持字符串或列表格式
        if candidate.task_domain:
            if isinstance(candidate.task_domain, str):
                fields[FM["task_domain"]] = [
                    d.strip() for d in candidate.task_domain.split(",")
                ]
            elif isinstance(candidate.task_domain, list):
                fields[FM["task_domain"]] = candidate.task_domain

        if metrics_str := self._list_to_str(candidate.metrics):
            fields[FM["metrics"]] = metrics_str

        if baselines_str := self._list_to_str(candidate.baselines):
            fields[FM["baselines"]] = baselines_str

        if institution := self._truncate_str(candidate.institution):
            fields[FM["institution"]] = institution

        if candidate.dataset_size is not None:
            fields[FM["dataset_size"]] = candidate.dataset_size

        if desc := self._truncate_str(candidate.dataset_size_description):
            fields[FM["dataset_size_description"]] = desc

        if candidate.license_type:
            fields[FM["license_type"]] = candidate.license_type

        if url := self._format_url(candidate.dataset_url):
            fields[FM["dataset_url"]] = url

        return {"fields": fields}

    @staticmethod
    def _extract_url_value(url_obj: Any) -> Optional[str]:
        """从飞书URL字段提取链接值，兼容对象和字符串格式"""
        if isinstance(url_obj, dict):
            return url_obj.get("link")
        if isinstance(url_obj, str):
            return url_obj
        return None

    async def get_existing_urls(self) -> set[str]:
        """查询飞书Bitable已存在的所有URL（用于去重）"""
        await self._ensure_access_token()

        existing_urls: set[str] = set()
        url_field_name = self.FIELD_MAPPING["url"]

        async with httpx.AsyncClient(timeout=10) as client:
            await self._ensure_field_cache(client)
            items = await self._paginated_fetch(client)

            for item in items:
                url_obj = item.get("fields", {}).get(url_field_name)
                url_value = self._extract_url_value(url_obj)
                url_key = canonicalize_url(url_value)
                if url_key:
                    existing_urls.add(url_key)

        logger.info("飞书已存在URL数量: %d", len(existing_urls))
        return existing_urls

    async def read_existing_records(self) -> List[dict[str, Any]]:
        """查询飞书已存在的记录，含URL/发布时间/创建时间/来源，用于时间窗去重

        P12修复: 读取飞书系统字段创建时间，基于入库时间完成去重
        P13修复: 改用GET records接口，避免search分页token重复导致漏数
        """

        await self._ensure_access_token()

        records: List[dict[str, Any]] = []
        url_field = self.FIELD_MAPPING["url"]
        publish_field = self.FIELD_MAPPING["publish_date"]

        async with httpx.AsyncClient(timeout=10) as client:
            await self._ensure_field_cache(client)
            items = await self._paginated_fetch(client)

            for item in items:
                fields = item.get("fields", {})
                url_value = self._extract_url_value(fields.get(url_field))
                publish_raw = fields.get(publish_field)
                created_raw = fields.get("创建时间")

                url_key = canonicalize_url(url_value)
                publish_date = self._parse_timestamp(publish_raw)
                created_at = self._parse_timestamp(created_raw)

                if url_key:
                    source_value = fields.get(self.FIELD_MAPPING["source"], "default")
                    # P18修复：规范化source字段，飞书可能存为列表或大写
                    if isinstance(source_value, list):
                        source_value = source_value[0] if source_value else "default"
                    source_value = str(source_value).lower()
                    record_item: dict[str, Any] = {
                        "url": str(url_value),
                        "url_key": url_key,
                        "publish_date": publish_date,
                        "created_at": created_at,
                        "source": source_value,
                    }
                    records.append(record_item)

        logger.info("飞书历史记录读取完成: %d条", len(records))
        return records

    @staticmethod
    def _parse_timestamp(value: Any) -> Optional[datetime]:
        """解析飞书时间字段，兼容毫秒时间戳/ISO字符串，返回naive datetime"""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000)
        if isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return dt.replace(tzinfo=None)
            except ValueError:
                return None
        return None

    async def read_brief_records(
        self, fields: Optional[list[str]] = None
    ) -> List[dict[str, Any]]:
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
        records: List[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=10) as client:
            await self._ensure_field_cache(client)
            items = await self._paginated_fetch(client)

            for item in items:
                fields_data = item.get("fields", {})
                record: dict[str, Any] = {}
                for key, feishu_field in field_map.items():
                    value = fields_data.get(feishu_field)
                    if key == "publish_date":
                        record[key] = self._parse_timestamp(value)
                    elif isinstance(value, dict):
                        record[key] = value.get("link") or value.get("text") or value
                    else:
                        record[key] = value
                records.append(record)

        logger.info("飞书brief记录读取完成: %d条", len(records))
        return records
