"""GitHub Benchmark采集器 (Phase 7强化版)"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, cast

import httpx

from src.common import clean_summary_text, constants
from src.common.url_extractor import URLExtractor
from src.config import Settings, get_settings
from src.models import RawCandidate
from src.extractors import ImageExtractor

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ReadmeExtraction:
    """README解析结果容器"""

    metrics: List[str]
    baselines: List[str]
    dataset_size: Optional[str]


class GitHubCollector:
    """通过GitHub Search API抓取高质量Benchmark仓库"""

    README_REQUIRED_KEYWORDS = {
        kw.lower() for kw in constants.GITHUB_README_REQUIRED_KEYWORDS
    }
    README_EXCLUDED_KEYWORDS = {
        kw.lower() for kw in constants.GITHUB_README_EXCLUDED_KEYWORDS
    }
    METRIC_PATTERNS: Dict[str, str] = {
        r"pass@\d+": "PASS",
        r"bleu(?:-\d+)?": "BLEU",
        r"rouge(?:-[l1-3])?": "ROUGE",
        r"f1-?score": "F1-Score",
        r"accuracy": "Accuracy",
        r"precision": "Precision",
        r"recall": "Recall",
        r"exact match": "Exact Match",
        r"code pass rate": "Code Pass Rate",
        r"success rate": "Success Rate",
    }
    BASELINE_PATTERNS: Dict[str, str] = {
        r"gpt-4(?:-turbo|-o)?": "GPT-4",
        r"gpt-3\.5(?:-turbo)?": "GPT-3.5",
        r"claude[\s-]?(?:3\.5|3|opus|sonnet)": "Claude",
        r"llama[-\s]?3(?:\.1)?-?\d{1,3}[mb]?": "Llama",
        r"llama[-\s]?2-?\d{1,3}[mb]?": "Llama",
        r"code\s?llama": "Code Llama",
        r"starcoder": "StarCoder",
        r"codex": "Codex",
        r"mistral": "Mistral",
        r"deepseek": "DeepSeek",
    }
    DATASET_SIZE_PATTERNS: List[str] = [
        r"\b\d{1,3}(?:[,\s]\d{3})*(?:\s*(?:k|m))?\s*(?:samples?|problems?|questions?|tasks?|examples?|test\s+cases?)\b",
        r"(?:contains|includes|consists\s+of)\s+\d{1,3}(?:[,\s]\d{3})*(?:\s*(?:k|m))?\s*\w*",
    ]

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self.github_config = self.settings.sources.github
        self.topics = self.github_config.topics or constants.GITHUB_TOPICS
        self.min_stars = self.github_config.min_stars
        self.timeout = self.github_config.timeout_seconds
        self.api_url = self.github_config.search_api or constants.GITHUB_SEARCH_API
        self.per_page = 5
        self.lookback_days = self.github_config.lookback_days
        self.languages = {lang.lower() for lang in (self.github_config.languages or [])}
        self.min_readme_length = self.github_config.min_readme_length
        self.max_days_since_update = self.github_config.max_days_since_update
        self.token = self.github_config.token or os.getenv("GITHUB_TOKEN")
        self.max_retries = self.github_config.max_retries
        self.retry_delay = self.github_config.retry_delay_seconds
        self._readme_cache: Dict[str, Optional[str]] = {}

    async def collect(self) -> List[RawCandidate]:
        if not self.github_config.enabled:
            logger.info("GitHub采集器已禁用,直接返回空列表")
            return []

        candidates: List[RawCandidate] = []

        headers = self._build_headers("application/vnd.github+json")
        timeout = httpx.Timeout(self.timeout)

        async with httpx.AsyncClient(
            timeout=timeout, headers=headers, follow_redirects=True
        ) as client:
            tasks = [self._fetch_topic(client, topic) for topic in self.topics]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for topic, result in zip(self.topics, results, strict=False):
            if isinstance(result, BaseException):
                logger.error("GitHub API 任务失败(%s): %r", topic, result)
                continue
            candidates.extend(cast(List[RawCandidate], result))

        logger.info("GitHub采集完成,候选总数%s", len(candidates))
        return candidates

    async def _fetch_topic(
        self, client: httpx.AsyncClient, topic: str
    ) -> List[RawCandidate]:
        """调用GitHub搜索API"""

        lookback_date = (
            datetime.now(timezone.utc) - timedelta(days=self.lookback_days)
        ).strftime("%Y-%m-%d")
        params = {
            "q": f"{topic} benchmark in:name,description,readme pushed:>={lookback_date}",
            "sort": "stars",
            "order": "desc",
            "per_page": self.per_page,
        }
        resp = await self._request_with_retry(client, params, topic)
        data = resp.json()
        items = data.get("items", [])

        parsed: List[RawCandidate] = []
        for repo in items:
            if not self._passes_basic_repo_filters(repo):
                continue

            candidate = await self._build_candidate(client, repo, topic)
            if candidate:
                parsed.append(candidate)

        return parsed

    async def _request_with_retry(
        self, client: httpx.AsyncClient, params: Dict[str, Any], topic: str
    ) -> httpx.Response:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = await client.get(self.api_url, params=params)
                resp.raise_for_status()
                return resp
            except (httpx.HTTPError, httpx.TransportError) as exc:  # noqa: PERF203
                last_exc = exc
                if attempt == self.max_retries:
                    break
                delay = self.retry_delay * attempt
                logger.warning(
                    "GitHub API调用失败(topic=%s, attempt=%s/%s): %r，%s后重试",
                    topic,
                    attempt,
                    self.max_retries,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        if last_exc:
            raise last_exc
        raise RuntimeError("GitHub API未知错误")

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    async def _build_candidate(
        self,
        client: httpx.AsyncClient,
        repo: Dict[str, Any],
        topic: str,
    ) -> Optional[RawCandidate]:
        """拉取README并根据白/黑名单判断是否为Benchmark"""

        full_name = repo.get("full_name", "")
        readme_text = await self._fetch_readme(client, full_name)
        if not readme_text:
            logger.debug("GitHub仓库无README: %s", full_name)
            return None

        if len(readme_text) < self.min_readme_length:
            logger.debug("GitHub README过短(%s): %s", len(readme_text), full_name)
            return None

        if not self._is_benchmark_repo(readme_text):
            logger.debug("GitHub仓库不符合Benchmark特征: %s", full_name)
            return None

        stars = repo.get("stargazers_count", 0)
        license_info = repo.get("license")
        license_type = license_info.get("name") if license_info else None
        task_type = self._extract_task_type(readme_text or repo.get("description", ""))

        readme_meta = self._extract_raw_metadata(readme_text)

        # 从README中提取数据集URL
        dataset_url = URLExtractor.extract_dataset_url(readme_text) if readme_text else None

        # 清理README文本（去除HTML/Markdown噪声）
        # 这是为了解决飞书表格中abstract字段被污染的问题（包含<!-- <p align="center"> <img alt=... 等HTML标签）
        cleaned_abstract = clean_summary_text(readme_text, max_length=2000) if readme_text else None

        hero_image_url = await ImageExtractor.extract_github_image(
            repo_url=repo.get("html_url", ""),
            readme_html=readme_text,
        )

        return RawCandidate(
            title=repo.get("full_name", ""),
            url=repo.get("html_url", ""),
            source="github",
            abstract=cleaned_abstract,  # 使用清理后的文本
            github_stars=stars,
            github_url=repo.get("html_url"),
            publish_date=self._parse_datetime(repo.get("pushed_at")),
            license_type=license_type,
            task_type=task_type,
            dataset_url=dataset_url,  # 新增：从README提取数据集URL
            raw_metrics=readme_meta.metrics or None,
            raw_baselines=readme_meta.baselines or None,
            raw_dataset_size=readme_meta.dataset_size,
            raw_metadata={
                "topic": topic,
                "language": str(repo.get("language") or ""),
            },
            hero_image_url=hero_image_url,
        )

    async def _fetch_readme(
        self,
        client: httpx.AsyncClient,
        full_name: str,
        max_size: int = 10000,
    ) -> Optional[str]:
        """获取README文本并做简单缓存,避免重复请求"""

        if not full_name:
            return None

        if full_name in self._readme_cache:
            return self._readme_cache[full_name]

        url = f"https://api.github.com/repos/{full_name}/readme"
        headers = self._build_headers("application/vnd.github.raw")
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            content = resp.text[:max_size]
            self._readme_cache[full_name] = content
            return content
        except httpx.HTTPError as exc:
            logger.debug("README获取失败(%s): %s", full_name, exc)
            self._readme_cache[full_name] = None
            return None

    def _build_headers(self, accept: str) -> dict[str, str]:
        headers = {"Accept": accept, "User-Agent": "BenchScope/1.0"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _passes_basic_repo_filters(self, repo: Dict[str, Any]) -> bool:
        """基础过滤: stars/语言/更新时间"""

        stars = repo.get("stargazers_count", 0)
        if stars < self.min_stars:
            return False

        language = (repo.get("language") or "").lower()
        if self.languages and language and language not in self.languages:
            return False

        pushed_at = self._parse_datetime(repo.get("pushed_at"))
        if pushed_at is None:
            return False

        now = datetime.now(timezone.utc)
        if (now - pushed_at).days > self.max_days_since_update:
            return False

        return True

    def _is_benchmark_repo(self, readme_text: str) -> bool:
        """通过关键词白/黑名单识别Benchmark仓库"""

        text = readme_text.lower()
        if any(excluded in text for excluded in self.README_EXCLUDED_KEYWORDS):
            return False

        return any(required in text for required in self.README_REQUIRED_KEYWORDS)

    def _extract_raw_metadata(self, readme_text: str) -> ReadmeExtraction:
        """从README中提取Phase8所需的基础元数据"""

        metrics: List[str] = []
        baselines: List[str] = []
        dataset_size: Optional[str] = None

        lowered = readme_text.lower()

        for pattern, label in self.METRIC_PATTERNS.items():
            for match in re.finditer(pattern, lowered, flags=re.IGNORECASE):
                raw_text = match.group(0).strip()
                if not raw_text:
                    continue
                if label == "PASS":
                    formatted = raw_text.lower().replace("pass", "Pass")
                elif label in {"BLEU", "ROUGE"}:
                    formatted = raw_text.upper().replace(" ", "")
                elif label == "F1-Score":
                    formatted = "F1-Score"
                elif label == "Exact Match":
                    formatted = "Exact Match"
                elif label == "Code Pass Rate":
                    formatted = "Code Pass Rate"
                else:
                    formatted = label
                if formatted not in metrics:
                    metrics.append(formatted)
                if len(metrics) >= constants.MAX_EXTRACTED_METRICS:
                    break
            if len(metrics) >= constants.MAX_EXTRACTED_METRICS:
                break

        for pattern, label in self.BASELINE_PATTERNS.items():
            for _match in re.finditer(pattern, lowered, flags=re.IGNORECASE):
                if label not in baselines:
                    baselines.append(label)
                if len(baselines) >= constants.MAX_EXTRACTED_BASELINES:
                    break
            if len(baselines) >= constants.MAX_EXTRACTED_BASELINES:
                break

        for pattern in self.DATASET_SIZE_PATTERNS:
            size_match = re.search(pattern, readme_text, flags=re.IGNORECASE)
            if size_match:
                dataset_size = size_match.group(0).strip()
                break

        return ReadmeExtraction(metrics=metrics, baselines=baselines, dataset_size=dataset_size)

    @staticmethod
    def _extract_task_type(text: str) -> str | None:
        """从README或描述中提取任务类型"""
        if not text:
            return None

        text_lower = text.lower()

        # 任务类型映射（按优先级排序）
        task_patterns = {
            "Code Generation": [
                "code generation",
                "codegen",
                "code synthesis",
                "program synthesis",
            ],
            "Question Answering": [
                "question answering",
                "qa benchmark",
                "reading comprehension",
            ],
            "Reasoning": [
                "reasoning",
                "chain-of-thought",
                "logical reasoning",
                "math reasoning",
            ],
            "Tool Use": [
                "tool use",
                "tool calling",
                "function calling",
                "api calling",
            ],
            "Multi-Agent": [
                "multi-agent",
                "agent collaboration",
                "multi agent",
            ],
            "Web Automation": [
                "web automation",
                "browser automation",
                "web agent",
                "web navigation",
            ],
            "Code Understanding": [
                "code understanding",
                "code comprehension",
                "code analysis",
            ],
            "Text Generation": [
                "text generation",
                "summarization",
                "translation",
            ],
        }

        # 匹配第一个出现的任务类型
        for task_type, patterns in task_patterns.items():
            if any(pattern in text_lower for pattern in patterns):
                return task_type

        return None
