"""GitHub Trending采集器"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List

import httpx

from src.common import constants
from src.models import RawCandidate

logger = logging.getLogger(__name__)


class GitHubCollector:
    """通过GitHub Search API抓取高star仓库"""

    def __init__(self) -> None:
        self.topics = constants.GITHUB_TOPICS
        self.min_stars = constants.GITHUB_MIN_STARS
        self.timeout = constants.GITHUB_TIMEOUT_SECONDS
        self.api_url = "https://api.github.com/search/repositories"
        self.per_page = 5
        self.token = os.getenv("GITHUB_TOKEN")

    async def collect(self) -> List[RawCandidate]:
        candidates: List[RawCandidate] = []

        headers = self._build_headers("application/vnd.github+json")

        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
            tasks = [self._fetch_topic(client, topic) for topic in self.topics]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for topic, result in zip(self.topics, results, strict=False):
            if isinstance(result, Exception):
                logger.error("GitHub API 任务失败(%s): %s", topic, result)
                continue
            candidates.extend(result)

        logger.info("GitHub采集完成,候选总数%s", len(candidates))
        return candidates

    async def _fetch_topic(
        self, client: httpx.AsyncClient, topic: str
    ) -> List[RawCandidate]:
        """调用GitHub搜索API"""

        lookback_date = (datetime.now(timezone.utc) - timedelta(days=constants.GITHUB_LOOKBACK_DAYS)).strftime(
            "%Y-%m-%d"
        )
        params = {
            "q": f"{topic} benchmark in:name,description,readme pushed:>={lookback_date}",
            "sort": "stars",
            "order": "desc",
            "per_page": self.per_page,
        }
        resp = await client.get(self.api_url, params=params)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("items", [])

        parsed: List[RawCandidate] = []
        for repo in items:
            stars = repo.get("stargazers_count", 0)
            if stars < self.min_stars:
                continue

            readme_text = await self._fetch_readme(client, repo.get("full_name", ""))
            abstract = readme_text or repo.get("description")

            # 提取License类型（Phase 6字段）
            license_info = repo.get("license")
            license_type = license_info.get("name") if license_info else None

            # 提取任务类型（Phase 6字段）
            task_type = self._extract_task_type(readme_text or repo.get("description", ""))

            parsed.append(
                RawCandidate(
                    title=repo.get("full_name", ""),
                    url=repo.get("html_url", ""),
                    source="github",
                    abstract=abstract,
                    github_stars=stars,
                    github_url=repo.get("html_url"),
                    publish_date=self._parse_datetime(repo.get("pushed_at")),
                    license_type=license_type,  # Phase 6: License类型（GitHub API返回）
                    task_type=task_type,         # Phase 6: 任务类型（从README提取）
                    raw_metadata={
                        "topic": topic,
                        "language": repo.get("language"),
                    },
                )
            )

        return parsed

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    async def _fetch_readme(self, client: httpx.AsyncClient, full_name: str) -> str:
        """获取README文本,用于后续预筛选长度判断"""

        if not full_name:
            return ""

        url = f"https://api.github.com/repos/{full_name}/readme"
        headers = self._build_headers("application/vnd.github.raw")
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.text
        except httpx.HTTPError:
            return ""

    def _build_headers(self, accept: str) -> dict[str, str]:
        headers = {"Accept": accept}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

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
