"""Twitter/X 推文采集器

注意: Twitter API v2 搜索需要 Basic 套餐($100/月)或更高级别。
免费 API 每月仅100次读取,不支持 Search API。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

import httpx

from src.common import constants
from src.config import Settings, get_settings
from src.models import RawCandidate

logger = logging.getLogger(__name__)


class TwitterCollector:
    """通过 Twitter API v2 搜索推文,提取 Benchmark 相关线索"""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

        twitter_cfg = getattr(self.settings.sources, "twitter", None)
        if twitter_cfg is None:
            self.enabled = False
            self.lookback_days = constants.TWITTER_LOOKBACK_DAYS
            self.max_results_per_query = constants.TWITTER_MAX_RESULTS_PER_QUERY
            self.tier1_queries = constants.TWITTER_TIER1_QUERIES
            self.tier2_queries = constants.TWITTER_TIER2_QUERIES
            self.min_likes = constants.TWITTER_MIN_LIKES
            self.min_retweets = constants.TWITTER_MIN_RETWEETS
            self.must_have_url = True
            self.language = constants.TWITTER_DEFAULT_LANGUAGE
            self.rate_limit_delay = constants.TWITTER_RATE_LIMIT_DELAY
        else:
            self.enabled = twitter_cfg.enabled
            self.lookback_days = twitter_cfg.lookback_days
            self.max_results_per_query = twitter_cfg.max_results_per_query
            self.tier1_queries = (
                twitter_cfg.tier1_queries or constants.TWITTER_TIER1_QUERIES
            )
            self.tier2_queries = (
                twitter_cfg.tier2_queries or constants.TWITTER_TIER2_QUERIES
            )
            self.min_likes = twitter_cfg.min_likes
            self.min_retweets = twitter_cfg.min_retweets
            self.must_have_url = twitter_cfg.must_have_url
            self.language = twitter_cfg.language or constants.TWITTER_DEFAULT_LANGUAGE
            self.rate_limit_delay = twitter_cfg.rate_limit_delay

        self.bearer_token = getattr(
            self.settings, "twitter_bearer_token", None
        ) or os.getenv("TWITTER_BEARER_TOKEN")

        if self.enabled and not self.bearer_token:
            raise ValueError("TWITTER_BEARER_TOKEN环境变量未配置")

    async def collect(self) -> List[RawCandidate]:
        """采集 Twitter 推文并转换为 RawCandidate 列表"""

        if not self.enabled:
            logger.info("Twitter采集器已禁用,直接返回空列表")
            return []

        if not self.bearer_token:
            logger.warning("Twitter采集器未配置Bearer Token,跳过采集")
            return []

        logger.info("开始 Twitter 采集...")

        all_tweets: List[Dict] = []
        queries: List[str] = list(self.tier1_queries) + list(self.tier2_queries)

        if not queries:
            logger.info("Twitter关键词列表为空,直接返回空列表")
            return []

        headers = {
            "Authorization": f"Bearer {self.bearer_token}",
            "User-Agent": "BenchScope/1.0",
        }

        async with httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(constants.HTTP_CLIENT_TIMEOUT),
        ) as client:
            for idx, query in enumerate(queries, 1):
                logger.info("搜索关键词 [%s/%s]: %s", idx, len(queries), query)
                try:
                    tweets = await self._search_tweets(client, query)
                    all_tweets.extend(tweets)
                    logger.info("  找到 %s 条推文", len(tweets))
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    if status_code == 429:
                        logger.error("Twitter API限流(429), 请适当降低请求频率")
                    else:
                        logger.error("Twitter API错误(%s): %s", status_code, exc)
                except Exception as exc:  # noqa: BLE001
                    logger.error("搜索失败(%s): %s", query, exc)

                if idx < len(queries) and self.rate_limit_delay > 0:
                    await asyncio.sleep(self.rate_limit_delay)

        unique_tweets = self._deduplicate(all_tweets)
        logger.info("Twitter 去重后: %s 条推文", len(unique_tweets))

        filtered_tweets = self._prefilter(unique_tweets)
        logger.info("Twitter 预筛选后: %s 条推文", len(filtered_tweets))

        candidates: List[RawCandidate] = []
        for tweet in filtered_tweets:
            try:
                candidate = self._to_candidate(tweet)
                candidates.append(candidate)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Twitter 推文转换失败(id=%s): %s", tweet.get("id"), exc)

        logger.info("Twitter采集完成,有效候选 %s 条", len(candidates))
        return candidates

    async def _search_tweets(
        self,
        client: httpx.AsyncClient,
        query: str,
    ) -> List[Dict]:
        """调用 Twitter API v2 搜索最近推文"""

        start_time = (
            (datetime.now(timezone.utc) - timedelta(days=self.lookback_days))
            .isoformat()
            .replace("+00:00", "Z")
        )

        params = {
            "query": f"{query} lang:{self.language} -is:retweet",
            "max_results": min(self.max_results_per_query, 100),
            "start_time": start_time,
            "tweet.fields": "created_at,public_metrics,entities,author_id",
            "expansions": "author_id",
            "user.fields": "username,public_metrics",
        }

        resp = await client.get(
            "https://api.twitter.com/2/tweets/search/recent",
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

        tweets = data.get("data") or []
        includes = data.get("includes") or {}
        users = {u["id"]: u for u in includes.get("users") or []}

        for tweet in tweets:
            author_id = tweet.get("author_id")
            if author_id and author_id in users:
                tweet["author"] = users[author_id]

        return tweets

    @staticmethod
    def _deduplicate(tweets: List[Dict]) -> List[Dict]:
        """基于推文 ID 去重"""

        seen_ids: set[str] = set()
        unique: List[Dict] = []
        for tweet in tweets:
            tweet_id = tweet.get("id")
            if not tweet_id or tweet_id in seen_ids:
                continue
            seen_ids.add(tweet_id)
            unique.append(tweet)
        return unique

    def _prefilter(self, tweets: List[Dict]) -> List[Dict]:
        """基于互动数与 URL 存在性的预筛选"""

        filtered: List[Dict] = []

        for tweet in tweets:
            metrics = tweet.get("public_metrics") or {}
            if metrics.get("like_count", 0) < self.min_likes:
                continue
            if metrics.get("retweet_count", 0) < self.min_retweets:
                continue
            if self.must_have_url:
                urls = tweet.get("entities", {}).get("urls") or []
                if not urls:
                    continue

            filtered.append(tweet)

        return filtered

    def _to_candidate(self, tweet: Dict) -> RawCandidate:
        """将 Twitter 推文转换为 RawCandidate"""

        urls = tweet.get("entities", {}).get("urls") or []
        primary_url = urls[0].get("expanded_url") if urls else None

        source: str = "twitter"
        paper_url: Optional[str] = None
        github_url: Optional[str] = None

        if primary_url:
            if self._is_arxiv_url(primary_url):
                source = "arxiv"
                paper_url = primary_url
            elif self._is_github_url(primary_url):
                source = "github"
                github_url = primary_url
            elif self._is_huggingface_url(primary_url):
                source = "huggingface"

        text = tweet.get("text", "") or ""
        title = self._extract_title(text)
        abstract = self._clean_text(text, urls)

        created_at = self._parse_datetime(tweet.get("created_at"))
        metrics = tweet.get("public_metrics") or {}
        author = tweet.get("author") or {}
        author_metrics = author.get("public_metrics") or {}

        return RawCandidate(
            title=title,
            url=primary_url or "",
            source=source,
            abstract=abstract,
            authors=None,
            publish_date=created_at,
            github_stars=metrics.get("like_count"),
            github_url=github_url,
            paper_url=paper_url,
            raw_metadata={
                "tweet_id": tweet.get("id", ""),
                "retweets": str(metrics.get("retweet_count", 0)),
                "replies": str(metrics.get("reply_count", 0)),
                "quotes": str(metrics.get("quote_count", 0)),
                "author_username": author.get("username", ""),
                "author_followers": str(author_metrics.get("followers_count", 0)),
                "tweet_url": f"https://twitter.com/i/web/status/{tweet.get('id', '')}",
            },
        )

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        """解析 Twitter 的 ISO 时间字符串为 datetime"""

        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _is_arxiv_url(url: str) -> bool:
        return "arxiv.org" in urlparse(url).netloc.lower()

    @staticmethod
    def _is_github_url(url: str) -> bool:
        """判断是否为 GitHub 仓库主链接（排除文件/Issue等子页面）"""

        parsed = urlparse(url)
        if parsed.netloc.lower() not in {"github.com", "www.github.com"}:
            return False

        path = parsed.path.rstrip("/")
        if path.count("/") < 2:
            return False

        excluded_segments = ("/blob/", "/tree/", "/issues/", "/pull/", "/commit/")
        return not any(seg in path for seg in excluded_segments)

    @staticmethod
    def _is_huggingface_url(url: str) -> bool:
        return "huggingface.co" in urlparse(url).netloc.lower()

    @staticmethod
    def _extract_title(text: str) -> str:
        """从推文文本提取标题（前 100 字符）"""

        title = text.replace("\n", " ").strip()
        if len(title) > 100:
            title = title[:97] + "..."
        return title

    @staticmethod
    def _clean_text(text: str, urls: List[Dict]) -> str:
        """移除推文中的短链接,得到干净的摘要文本"""

        cleaned = text
        for url_obj in urls:
            short_url = url_obj.get("url", "")
            if short_url:
                cleaned = cleaned.replace(short_url, "")
        return re.sub(r"\s+", " ", cleaned).strip()
