"""项目级常量定义,避免魔法数字散落各处"""
from __future__ import annotations

from typing import Final

# ---- Collector 配置 ----
ARXIV_MAX_RESULTS: Final[int] = 50
ARXIV_TIMEOUT_SECONDS: Final[int] = 10
ARXIV_MAX_RETRIES: Final[int] = 3
ARXIV_LOOKBACK_HOURS: Final[int] = 168  # 7天窗口，相关论文发布频率低
ARXIV_KEYWORDS: Final[list[str]] = [
    "benchmark",
    "agent evaluation",
    "code generation",
    "web automation",
]
ARXIV_CATEGORIES: Final[list[str]] = ["cs.AI", "cs.CL", "cs.SE"]

GITHUB_TRENDING_URL: Final[str] = "https://github.com/trending"
GITHUB_TOPICS: Final[list[str]] = ["benchmark", "evaluation", "agent"]
GITHUB_TIMEOUT_SECONDS: Final[int] = 5
GITHUB_MIN_STARS: Final[int] = 0
GITHUB_LOOKBACK_DAYS: Final[int] = 30  # 30天窗口，新Benchmark创建频率低

# Semantic Scholar配置
SEMANTIC_SCHOLAR_LOOKBACK_YEARS: Final[int] = 2
SEMANTIC_SCHOLAR_VENUES: Final[list[str]] = [
    "NeurIPS",
    "ICLR",
    "ICML",
    "ACL",
    "EMNLP",
    "CVPR",
    "ICCV",
    "KDD",
    "WWW",
]
SEMANTIC_SCHOLAR_KEYWORDS: Final[list[str]] = [
    "benchmark",
    "evaluation",
    "dataset",
    "leaderboard",
    "test set",
]
SEMANTIC_SCHOLAR_MAX_RESULTS: Final[int] = 100
SEMANTIC_SCHOLAR_TIMEOUT_SECONDS: Final[int] = 15

# HELM配置
HELM_CONFIG_URL: Final[str] = "https://crfm.stanford.edu/helm/classic/latest/config.js"
HELM_BASE_PAGE: Final[str] = "https://crfm.stanford.edu/helm/classic/latest/"
HELM_STORAGE_BASE: Final[str] = "https://storage.googleapis.com/crfm-helm-public/benchmark_output"
HELM_DEFAULT_RELEASE: Final[str] = "v0.4.0"
HELM_TIMEOUT_SECONDS: Final[int] = 15

# ---- Benchmark 关键词 ----
BENCHMARK_KEYWORDS: Final[list[str]] = [
    "benchmark",
    "evaluation",
    "leaderboard",
    "dataset",
    "agent",
    "coding",
    "reasoning",
    "tool use",
    "multi-agent",
    "code generation",
]

HUGGINGFACE_KEYWORDS: Final[list[str]] = [
    "benchmark",
    "evaluation",
    "leaderboard",
]
HUGGINGFACE_TASK_CATEGORIES: Final[list[str]] = [
    "text-generation",
    "question-answering",
    "code",
]
HUGGINGFACE_MIN_DOWNLOADS: Final[int] = 100
HUGGINGFACE_MAX_RESULTS: Final[int] = 50
HUGGINGFACE_LOOKBACK_DAYS: Final[int] = 14  # 14天窗口，数据集更新频率中等

# ---- Prefilter 配置 ----
PREFILTER_SIMILARITY_THRESHOLD: Final[float] = 0.9
PREFILTER_MIN_GITHUB_STARS: Final[int] = 10
PREFILTER_MIN_README_LENGTH: Final[int] = 500
PREFILTER_RECENT_DAYS: Final[int] = 90

# ---- Scorer 配置 ----
LLM_DEFAULT_MODEL: Final[str] = "gpt-4o"  # 评分质量优先,月成本<$1完全在预算内
LLM_MODEL: Final[str] = LLM_DEFAULT_MODEL
LLM_TIMEOUT_SECONDS: Final[int] = 30
LLM_CACHE_TTL_SECONDS: Final[int] = 7 * 24 * 3600
LLM_MAX_RETRIES: Final[int] = 3
LLM_COMPLETION_MAX_TOKENS: Final[int] = 2000  # 提高max_tokens确保评分依据完整详细
SCORE_CONCURRENCY: Final[int] = 10
REDIS_DEFAULT_URL: Final[str] = "redis://localhost:6379/0"
REDIS_TTL_DAYS: Final[int] = 7
REDIS_KEY_PREFIX: Final[str] = "benchscope:"
RULE_SCORE_THRESHOLDS: Final[dict[int, int]] = {
    1000: 8,
    500: 6,
    100: 4,
}
RULE_SCORE_MIN: Final[int] = 2
PRIORITY_HIGH_THRESHOLD: Final[int] = 40
PRIORITY_MEDIUM_THRESHOLD: Final[int] = 30

# 评分阈值
MIN_TOTAL_SCORE: Final[float] = 6.0  # 低于6分不入库
SCORE_WEIGHTS: Final[dict[str, float]] = {
    "activity": 0.15,        # 降低：GitHub stars容易虚高
    "reproducibility": 0.30,  # 保持：可复现性是核心
    "license": 0.15,         # 降低：不是核心指标
    "novelty": 0.15,         # 提高：Benchmark需要创新
    "relevance": 0.25,       # 提高：MGX适配度是关键
}

# ---- 存储与通知 ----
FEISHU_BATCH_SIZE: Final[int] = 20
FEISHU_RATE_LIMIT_SECONDS: Final[float] = 0.6
FEISHU_RATE_LIMIT_DELAY: Final[float] = FEISHU_RATE_LIMIT_SECONDS
FEISHU_BENCH_TABLE_URL: Final[str] = (
    "https://jcnqgpxcjdms.feishu.cn/base/WgI0bpHRVacs43skW24cR6JznWg?table=tblv2kzbzt4S2NSk&view=vewiJRxzFs"
)
FEISHU_MEDIUM_TOPK: Final[int] = 5
FEISHU_REASONING_PREVIEW_LENGTH: Final[int] = 1500  # 评分依据字段最大长度
FEISHU_SOURCE_NAME_MAP: Final[dict[str, str]] = {
    "arxiv": "arXiv",
    "github": "GitHub",
    "huggingface": "HuggingFace",
    "semantic_scholar": "Semantic Scholar",
    "helm": "HELM",
}

# 字符串截断长度
TITLE_TRUNCATE_SHORT: Final[int] = 50   # 日志显示
TITLE_TRUNCATE_MEDIUM: Final[int] = 60  # 摘要卡片
TITLE_TRUNCATE_LONG: Final[int] = 150   # 详细卡片

# 质量评级阈值
QUALITY_EXCELLENT_THRESHOLD: Final[float] = 8.0
QUALITY_GOOD_THRESHOLD: Final[float] = 7.0
QUALITY_PASS_THRESHOLD: Final[float] = 6.5

# HTTP请求配置
HTTP_CLIENT_TIMEOUT: Final[int] = 10  # 飞书webhook请求超时(秒)

# 预筛选规则
PREFILTER_MIN_TITLE_LENGTH: Final[int] = 10
PREFILTER_MIN_ABSTRACT_LENGTH: Final[int] = 20

SQLITE_DB_PATH: Final[str] = "fallback.db"
SQLITE_RETENTION_DAYS: Final[int] = 7
NOTIFY_TOP_K: Final[int] = 5

# ---- 日志 ----
LOG_FILE_NAME: Final[str] = "benchscope.log"
