"""全局配置加载逻辑"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
import yaml

from src.common import constants

# 明确加载.env.local文件（覆盖.env）
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env.local", override=True)


@dataclass(slots=True)
class OpenAISettings:
    api_key: str
    model: str = constants.LLM_DEFAULT_MODEL
    base_url: Optional[str] = None


@dataclass(slots=True)
class RedisSettings:
    url: str = constants.REDIS_DEFAULT_URL


@dataclass(slots=True)
class FeishuSettings:
    app_id: str
    app_secret: str
    bitable_app_token: str
    bitable_table_id: str
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None  # Webhook签名密钥（可选）


@dataclass(slots=True)
class LoggingSettings:
    level: str
    directory: Path
    file_name: str = constants.LOG_FILE_NAME


@dataclass(slots=True)
class ArxivSourceSettings:
    enabled: bool = True
    max_results: int = constants.ARXIV_MAX_RESULTS
    lookback_hours: int = constants.ARXIV_LOOKBACK_HOURS
    timeout_seconds: int = constants.ARXIV_TIMEOUT_SECONDS
    max_retries: int = constants.ARXIV_MAX_RETRIES
    keywords: list[str] = field(default_factory=lambda: constants.ARXIV_KEYWORDS.copy())
    categories: list[str] = field(
        default_factory=lambda: constants.ARXIV_CATEGORIES.copy()
    )


@dataclass(slots=True)
class HelmSourceSettings:
    enabled: bool = True
    base_url: str = constants.HELM_BASE_PAGE
    storage_base: str = constants.HELM_STORAGE_BASE
    default_release: str = constants.HELM_DEFAULT_RELEASE
    timeout_seconds: int = constants.HELM_TIMEOUT_SECONDS
    allowed_scenarios: list[str] = field(
        default_factory=lambda: constants.HELM_ALLOWED_SCENARIOS.copy()
    )
    excluded_scenarios: list[str] = field(
        default_factory=lambda: constants.HELM_EXCLUDED_SCENARIOS.copy()
    )


@dataclass(slots=True)
class GitHubSourceSettings:
    enabled: bool = True
    topics: list[str] = field(default_factory=lambda: constants.GITHUB_TOPICS.copy())
    languages: list[str] = field(
        default_factory=lambda: constants.GITHUB_LANGUAGES.copy()
    )
    search_api: str = constants.GITHUB_SEARCH_API
    trending_url: str = constants.GITHUB_TRENDING_URL
    min_stars: int = constants.GITHUB_MIN_STARS
    lookback_days: int = constants.GITHUB_LOOKBACK_DAYS
    timeout_seconds: int = constants.GITHUB_TIMEOUT_SECONDS
    token: Optional[str] = None
    min_readme_length: int = constants.GITHUB_MIN_README_LENGTH
    max_days_since_update: int = constants.GITHUB_MAX_DAYS_SINCE_UPDATE
    max_retries: int = constants.GITHUB_MAX_RETRIES
    retry_delay_seconds: float = constants.GITHUB_RETRY_DELAY_SECONDS


@dataclass(slots=True)
class HuggingFaceSourceSettings:
    enabled: bool = True
    keywords: list[str] = field(
        default_factory=lambda: constants.HUGGINGFACE_KEYWORDS.copy()
    )
    task_categories: list[str] = field(
        default_factory=lambda: constants.HUGGINGFACE_TASK_CATEGORIES.copy()
    )
    min_downloads: int = constants.HUGGINGFACE_MIN_DOWNLOADS
    limit: int = constants.HUGGINGFACE_MAX_RESULTS
    lookback_days: int = constants.HUGGINGFACE_LOOKBACK_DAYS
    token: Optional[str] = None


@dataclass(slots=True)
class TechEmpowerSourceSettings:
    enabled: bool = True
    base_url: str = constants.TECHEMPOWER_BASE_URL
    timeout_seconds: int = constants.TECHEMPOWER_TIMEOUT_SECONDS
    min_composite_score: float = constants.TECHEMPOWER_MIN_COMPOSITE_SCORE


@dataclass(slots=True)
class DBEnginesSourceSettings:
    enabled: bool = True
    base_url: str = constants.DBENGINES_BASE_URL
    timeout_seconds: int = constants.DBENGINES_TIMEOUT_SECONDS
    max_results: int = constants.DBENGINES_MAX_RESULTS


@dataclass(slots=True)
class TwitterSourceSettings:
    """Twitter/X 数据源配置"""

    enabled: bool = False
    lookback_days: int = constants.TWITTER_LOOKBACK_DAYS
    max_results_per_query: int = constants.TWITTER_MAX_RESULTS_PER_QUERY
    tier1_queries: list[str] = field(
        default_factory=lambda: constants.TWITTER_TIER1_QUERIES.copy()
    )
    tier2_queries: list[str] = field(
        default_factory=lambda: constants.TWITTER_TIER2_QUERIES.copy()
    )
    min_likes: int = constants.TWITTER_MIN_LIKES
    min_retweets: int = constants.TWITTER_MIN_RETWEETS
    must_have_url: bool = True
    language: str = constants.TWITTER_DEFAULT_LANGUAGE
    rate_limit_delay: float = constants.TWITTER_RATE_LIMIT_DELAY


@dataclass(slots=True)
class SourcesSettings:
    arxiv: ArxivSourceSettings = field(default_factory=ArxivSourceSettings)
    helm: HelmSourceSettings = field(default_factory=HelmSourceSettings)
    github: GitHubSourceSettings = field(default_factory=GitHubSourceSettings)
    huggingface: HuggingFaceSourceSettings = field(
        default_factory=HuggingFaceSourceSettings
    )
    techempower: TechEmpowerSourceSettings = field(
        default_factory=TechEmpowerSourceSettings
    )
    dbengines: DBEnginesSourceSettings = field(
        default_factory=DBEnginesSourceSettings
    )
    twitter: TwitterSourceSettings = field(
        default_factory=TwitterSourceSettings
    )


@dataclass(slots=True)
class Settings:
    openai: OpenAISettings
    redis: RedisSettings
    feishu: FeishuSettings
    logging: LoggingSettings
    sqlite_path: Path
    sources: SourcesSettings
    twitter_bearer_token: Optional[str] = None


def _get_env(key: str, default: Optional[str] = None) -> str:
    """读取环境变量并确保非空"""

    value = os.getenv(key, default)
    if value is None:
        raise RuntimeError(f"缺少必要环境变量: {key}")
    return value


# @lru_cache(maxsize=1)  # 临时禁用缓存，避免环境变量更新后读取旧值
def get_settings() -> Settings:
    """构建全局配置实例,使用缓存避免重复解析"""

    log_dir = Path(os.getenv("LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)

    sqlite_path_str = os.getenv("SQLITE_DB_PATH", constants.SQLITE_DB_PATH)
    sources_path = Path("config/sources.yaml")

    return Settings(
        openai=OpenAISettings(
            api_key=_get_env("OPENAI_API_KEY", ""),
            model=os.getenv("OPENAI_MODEL", constants.LLM_DEFAULT_MODEL),
            base_url=os.getenv("OPENAI_BASE_URL"),
        ),
        redis=RedisSettings(url=os.getenv("REDIS_URL", constants.REDIS_DEFAULT_URL)),
        feishu=FeishuSettings(
            app_id=_get_env("FEISHU_APP_ID", ""),
            app_secret=_get_env("FEISHU_APP_SECRET", ""),
            bitable_app_token=_get_env("FEISHU_BITABLE_APP_TOKEN", ""),
            bitable_table_id=_get_env("FEISHU_BITABLE_TABLE_ID", ""),
            webhook_url=os.getenv("FEISHU_WEBHOOK_URL"),
            webhook_secret=os.getenv("FEISHU_WEBHOOK_SECRET"),  # 可选：Webhook签名密钥
        ),
        logging=LoggingSettings(
            level=os.getenv("LOG_LEVEL", "INFO"),
            directory=log_dir,
        ),
        sqlite_path=Path(sqlite_path_str),
        sources=_load_sources_settings(sources_path),
        twitter_bearer_token=os.getenv("TWITTER_BEARER_TOKEN"),
    )


def _load_sources_settings(path: Path) -> SourcesSettings:
    """从YAML加载数据源配置,异常时使用默认值"""

    if not path.exists():
        return SourcesSettings()

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("加载sources.yaml失败: %s", exc)
        return SourcesSettings()

    arxiv_cfg = data.get("arxiv", {})
    helm_cfg = data.get("helm", {})
    github_cfg = data.get("github", {})
    huggingface_cfg = data.get("huggingface", {})
    techempower_cfg = data.get("techempower", {})
    dbengines_cfg = data.get("dbengines", {})
    twitter_cfg = data.get("twitter", {})
    twitter_filters = twitter_cfg.get("filters", {}) or {}
    twitter_queries = twitter_cfg.get("search_queries", {}) or {}
    return SourcesSettings(
        arxiv=ArxivSourceSettings(
            enabled=bool(arxiv_cfg.get("enabled", True)),
            max_results=int(arxiv_cfg.get("max_results", constants.ARXIV_MAX_RESULTS)),
            lookback_hours=int(
                arxiv_cfg.get("lookback_hours", constants.ARXIV_LOOKBACK_HOURS)
            ),
            timeout_seconds=int(
                arxiv_cfg.get("timeout_seconds", constants.ARXIV_TIMEOUT_SECONDS)
            ),
            max_retries=int(arxiv_cfg.get("max_retries", constants.ARXIV_MAX_RETRIES)),
            keywords=_ensure_list(arxiv_cfg.get("keywords"), constants.ARXIV_KEYWORDS),
            categories=_ensure_list(
                arxiv_cfg.get("categories"), constants.ARXIV_CATEGORIES
            ),
        ),
        helm=HelmSourceSettings(
            enabled=bool(helm_cfg.get("enabled", True)),
            base_url=helm_cfg.get("base_url", constants.HELM_BASE_PAGE),
            storage_base=helm_cfg.get("storage_base", constants.HELM_STORAGE_BASE),
            default_release=helm_cfg.get(
                "default_release", constants.HELM_DEFAULT_RELEASE
            ),
            timeout_seconds=int(
                helm_cfg.get("timeout_seconds", constants.HELM_TIMEOUT_SECONDS)
            ),
            allowed_scenarios=_ensure_list(
                helm_cfg.get("allowed_scenarios"), constants.HELM_ALLOWED_SCENARIOS
            ),
            excluded_scenarios=_ensure_list(
                helm_cfg.get("excluded_scenarios"), constants.HELM_EXCLUDED_SCENARIOS
            ),
        ),
        github=GitHubSourceSettings(
            enabled=bool(github_cfg.get("enabled", True)),
            topics=_ensure_list(github_cfg.get("topics"), constants.GITHUB_TOPICS),
            languages=_ensure_list(
                github_cfg.get("languages"), constants.GITHUB_LANGUAGES
            ),
            search_api=github_cfg.get("search_api", constants.GITHUB_SEARCH_API),
            trending_url=github_cfg.get("trending_url", constants.GITHUB_TRENDING_URL),
            min_stars=int(github_cfg.get("min_stars", constants.GITHUB_MIN_STARS)),
            lookback_days=int(
                github_cfg.get("lookback_days", constants.GITHUB_LOOKBACK_DAYS)
            ),
            timeout_seconds=int(
                github_cfg.get("timeout_seconds", constants.GITHUB_TIMEOUT_SECONDS)
            ),
            token=_resolve_env_placeholder(github_cfg.get("token"))
            or os.getenv("GITHUB_TOKEN"),
            min_readme_length=int(
                github_cfg.get("min_readme_length", constants.GITHUB_MIN_README_LENGTH)
            ),
            max_days_since_update=int(
                github_cfg.get(
                    "max_days_since_update", constants.GITHUB_MAX_DAYS_SINCE_UPDATE
                )
            ),
        ),
        huggingface=HuggingFaceSourceSettings(
            enabled=bool(huggingface_cfg.get("enabled", True)),
            keywords=huggingface_cfg.get("keywords")
            or constants.HUGGINGFACE_KEYWORDS.copy(),
            task_categories=huggingface_cfg.get("task_categories")
            or constants.HUGGINGFACE_TASK_CATEGORIES.copy(),
            min_downloads=int(
                huggingface_cfg.get(
                    "min_downloads", constants.HUGGINGFACE_MIN_DOWNLOADS
                )
            ),
            limit=int(
                huggingface_cfg.get(
                    "max_results",
                    huggingface_cfg.get("limit", constants.HUGGINGFACE_MAX_RESULTS),
                )
            ),
            lookback_days=int(
                huggingface_cfg.get(
                    "lookback_days", constants.HUGGINGFACE_LOOKBACK_DAYS
                )
            ),
            token=os.getenv("HUGGINGFACE_TOKEN"),
        ),
        techempower=TechEmpowerSourceSettings(
            enabled=bool(techempower_cfg.get("enabled", True)),
            base_url=techempower_cfg.get(
                "base_url", constants.TECHEMPOWER_BASE_URL
            ),
            timeout_seconds=int(
                techempower_cfg.get(
                    "timeout_seconds", constants.TECHEMPOWER_TIMEOUT_SECONDS
                )
            ),
            min_composite_score=float(
                techempower_cfg.get(
                    "min_composite_score",
                    constants.TECHEMPOWER_MIN_COMPOSITE_SCORE,
                )
            ),
        ),
        dbengines=DBEnginesSourceSettings(
            enabled=bool(dbengines_cfg.get("enabled", True)),
            base_url=dbengines_cfg.get(
                "base_url", constants.DBENGINES_BASE_URL
            ),
            timeout_seconds=int(
                dbengines_cfg.get(
                    "timeout_seconds", constants.DBENGINES_TIMEOUT_SECONDS
                )
            ),
            max_results=int(
                dbengines_cfg.get("max_results", constants.DBENGINES_MAX_RESULTS)
            ),
        ),
        twitter=TwitterSourceSettings(
            enabled=bool(twitter_cfg.get("enabled", False)),
            lookback_days=int(
                twitter_cfg.get(
                    "lookback_days", constants.TWITTER_LOOKBACK_DAYS
                )
            ),
            max_results_per_query=int(
                twitter_cfg.get(
                    "max_results_per_query",
                    constants.TWITTER_MAX_RESULTS_PER_QUERY,
                )
            ),
            tier1_queries=_ensure_list(
                twitter_queries.get("tier1"), constants.TWITTER_TIER1_QUERIES
            ),
            tier2_queries=_ensure_list(
                twitter_queries.get("tier2"), constants.TWITTER_TIER2_QUERIES
            ),
            min_likes=int(
                twitter_filters.get("min_likes", constants.TWITTER_MIN_LIKES)
            ),
            min_retweets=int(
                twitter_filters.get("min_retweets", constants.TWITTER_MIN_RETWEETS)
            ),
            must_have_url=bool(twitter_filters.get("must_have_url", True)),
            language=str(
                twitter_filters.get(
                    "language", constants.TWITTER_DEFAULT_LANGUAGE
                )
            ),
            rate_limit_delay=float(
                twitter_cfg.get(
                    "rate_limit_delay", constants.TWITTER_RATE_LIMIT_DELAY
                )
            ),
        ),
    )


def _ensure_list(value: object, fallback: list[str]) -> list[str]:
    if isinstance(value, list) and value:
        return [str(item) for item in value]
    return fallback.copy()


def _resolve_env_placeholder(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    if raw.startswith("${") and raw.endswith("}"):
        env_key = raw[2:-1]
        return os.getenv(env_key)
    return raw


__all__ = ["get_settings", "Settings"]
