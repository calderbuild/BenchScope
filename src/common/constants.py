"""项目级常量定义,避免魔法数字散落各处"""

from __future__ import annotations

from typing import Final

# ---- PDF增强配置 ----
GROBID_LOCAL_URL: Final[str] = "http://localhost:8070"
GROBID_CLOUD_URL: Final[str] = "https://kermitt2-grobid.hf.space"
GROBID_HEALTH_PATH: Final[str] = "/api/version"
GROBID_HEALTH_TIMEOUT: Final[float] = 2.0
GROBID_MAX_RETRIES: Final[int] = 3
GROBID_RETRY_DELAY_SECONDS: Final[float] = 2.0  # 降低重试延迟，加快失败恢复
PDF_ENHANCER_MAX_CONCURRENCY: Final[int] = 3  # 降低并发，减轻云端GROBID压力
PDF_DOWNLOAD_CHUNK_SIZE: Final[int] = 8192
ARXIV_PDF_EXPORT_BASE: Final[str] = "https://export.arxiv.org/pdf"
ARXIV_PDF_PRIMARY_BASE: Final[str] = "https://arxiv.org/pdf"
ARXIV_PDF_TIMEOUT_SECONDS: Final[int] = 30
ARXIV_PDF_HTTP_MAX_RETRIES: Final[int] = 2
ARXIV_PDF_HTTP_RETRY_DELAY_SECONDS: Final[float] = 5.0
ARXIV_PDF_CACHE_DIR: Final[str] = "/tmp/arxiv_pdf_cache"  # PDF缓存目录
ARXIV_IMAGE_CACHE_PREFIX: Final[str] = "arxiv_pdf_image:"
ARXIV_IMAGE_CONVERT_DPI: Final[int] = 150  # pdf2image渲染DPI
PDF_SECTION_P1_CONFIGS: Final[list[tuple[str, list[str], int]]] = [
    ("introduction", ["introduction", "background", "motivation"], 2000),
    ("method", ["method", "approach", "methodology", "design", "framework"], 3000),
    ("evaluation", ["evaluation", "experiments", "results", "performance"], 3000),
    ("dataset", ["dataset", "data", "benchmark", "corpus"], 2000),
]
PDF_SECTION_P2_CONFIGS: Final[list[tuple[str, list[str], int]]] = [
    ("baselines", ["baselines", "comparison", "related work", "prior work"], 2000),
    ("conclusion", ["conclusion", "discussion", "future work", "summary"], 2000),
]
PDF_MIN_P1_SECTIONS: Final[int] = 2
PDF_MIN_P2_SECTIONS: Final[int] = 1

# ---- Collector 配置 ----
ARXIV_MAX_RESULTS: Final[int] = 50
ARXIV_TIMEOUT_SECONDS: Final[int] = 10
ARXIV_MAX_RETRIES: Final[int] = 3
ARXIV_LOOKBACK_HOURS: Final[int] = 168  # 7天窗口，相关论文发布频率低
ARXIV_KEYWORDS: Final[list[str]] = [
    # P0 - 编程
    "code generation benchmark",
    "code evaluation",
    "programming benchmark",
    "software engineering benchmark",
    "program synthesis evaluation",
    "code completion benchmark",
    # P0 - Web自动化
    "web agent benchmark",
    "browser automation benchmark",
    "web navigation evaluation",
    "gui automation benchmark",
    # P1 - 多智能体
    "multi-agent benchmark",
    "agent collaboration evaluation",
    "tool use benchmark",
    "api usage benchmark",
    # Phase 6.5 - 后端
    "backend development benchmark",
    "api design benchmark",
    "restful api evaluation",
    "graphql performance benchmark",
    "database query benchmark",
    "sql optimization benchmark",
    "microservices benchmark",
    "distributed systems benchmark",
    "system design evaluation",
    "backend framework benchmark",
    "server performance benchmark",
    "web framework comparison",
]
ARXIV_CATEGORIES: Final[list[str]] = [
    "cs.SE",
    "cs.AI",
    "cs.CL",
    "cs.DC",
    "cs.DB",
    "cs.NI",
]

GITHUB_TRENDING_URL: Final[str] = "https://github.com/trending"
GITHUB_SEARCH_API: Final[str] = "https://api.github.com/search/repositories"
GITHUB_TOPICS: Final[list[str]] = [
    # P0 - 编程
    "code-generation",
    "code-benchmark",
    "program-synthesis",
    "coding-challenge",
    "software-testing",
    # P0 - Web自动化
    "web-automation",
    "browser-automation",
    "web-agent",
    "selenium-testing",
    "playwright",
    # P1 - GUI/Agent
    "gui-automation",
    "agent-benchmark",
    "multi-agent",
    "llm-agent",
    # Phase 6.5 - 后端
    "backend-benchmark",
    "api-benchmark",
    "database-benchmark",
    "microservices-benchmark",
    "distributed-systems",
    "system-design",
    "restful-api",
    "graphql",
    "performance-testing",
    "load-testing",
    "api-testing",
    "backend-framework",
    "server-benchmark",
    "web-framework-benchmark",
    "database-performance",
    "sql-benchmark",
]
GITHUB_LANGUAGES: Final[list[str]] = [
    "Python",
    "JavaScript",
    "TypeScript",
    "Go",
    "Java",
    "Rust",
]
GITHUB_TIMEOUT_SECONDS: Final[int] = 5
GITHUB_MAX_RETRIES: Final[int] = 3
GITHUB_RETRY_DELAY_SECONDS: Final[float] = 2.0
GITHUB_MIN_STARS: Final[int] = 50
GITHUB_MIN_README_LENGTH: Final[int] = 500
GITHUB_MAX_DAYS_SINCE_UPDATE: Final[int] = 90
GITHUB_README_REQUIRED_KEYWORDS: Final[list[str]] = [
    "benchmark",
    "evaluation",
    "eval",
    "dataset",
    "leaderboard",
    "test set",
    "baseline",
    "metric",
    "评测",
    "评估",
    "基准",
]
GITHUB_README_EXCLUDED_KEYWORDS: Final[list[str]] = [
    "awesome list",
    "curated list",
    "collection of",
    "resources list",
    "list of tools",
    "tutorial",
    "course",
    "guide for",
    "learning path",
    "sdk wrapper",
    "api wrapper",
    "资源汇总",
    "教程",
    "课程",
    "学习指南",
]
GITHUB_LOOKBACK_DAYS: Final[int] = 30  # 30天窗口，新Benchmark创建频率低
GITHUB_METADATA_TIMEOUT_SECONDS: Final[float] = 5.0
GITHUB_METADATA_MAX_RETRIES: Final[int] = 1

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
HELM_STORAGE_BASE: Final[str] = (
    "https://storage.googleapis.com/crfm-helm-public/benchmark_output"
)
HELM_DEFAULT_RELEASE: Final[str] = "v0.4.0"
HELM_TIMEOUT_SECONDS: Final[int] = 15
HELM_ALLOWED_SCENARIOS: Final[list[str]] = [
    "code",
    "coding",
    "program",
    "reasoning",
    "math",
    "logic",
    "tool",
    "api",
    "agent",
    "web",
    "browser",
    "gui",
]
HELM_EXCLUDED_SCENARIOS: Final[list[str]] = [
    "qa",
    "question",
    "answer",
    "reading",
    "comprehension",
    "dialogue",
    "conversation",
    "summarization",
    "summary",
    "translation",
    "sentiment",
    "classification",
    "image",
    "vision",
    "video",
]

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
    "code",
    "programming",
    "software",
    "benchmark",
    "backend",
    "api",
    "database",
    "sql",
    "microservices",
    "system-design",
]
HUGGINGFACE_TASK_CATEGORIES: Final[list[str]] = [
    "code",
    "software-engineering",
]
HUGGINGFACE_MIN_DOWNLOADS: Final[int] = 100
HUGGINGFACE_MAX_RESULTS: Final[int] = 50
HUGGINGFACE_LOOKBACK_DAYS: Final[int] = 14  # 14天窗口，数据集更新频率中等

# Twitter/X配置
TWITTER_LOOKBACK_DAYS: Final[int] = 7
TWITTER_MAX_RESULTS_PER_QUERY: Final[int] = 100
TWITTER_MIN_LIKES: Final[int] = 10
TWITTER_MIN_RETWEETS: Final[int] = 5
TWITTER_RATE_LIMIT_DELAY: Final[float] = 2.0
TWITTER_DEFAULT_LANGUAGE: Final[str] = "en"
TWITTER_TIER1_QUERIES: Final[list[str]] = [
    "AI agent benchmark",
    "LLM code generation",
    "multi-agent evaluation",
    "coding benchmark",
    "agent framework",
]
TWITTER_TIER2_QUERIES: Final[list[str]] = [
    "HumanEval",
    "MBPP benchmark",
    "SWE-bench",
    "agent leaderboard",
    "LLM evaluation",
    "code interpreter",
]

TECHEMPOWER_BASE_URL: Final[str] = "https://tfb-status.techempower.com"
TECHEMPOWER_TIMEOUT_SECONDS: Final[int] = 15
TECHEMPOWER_MIN_COMPOSITE_SCORE: Final[float] = 50.0
TECHEMPOWER_SCORE_SCALE: Final[float] = 100000.0  # 将req/s换算为分数

DBENGINES_BASE_URL: Final[str] = "https://db-engines.com/en"
DBENGINES_TIMEOUT_SECONDS: Final[int] = 15
DBENGINES_MAX_RESULTS: Final[int] = 50

# ---- Prefilter 配置 ----
PREFILTER_SIMILARITY_THRESHOLD: Final[float] = 0.9
PREFILTER_MIN_GITHUB_STARS: Final[int] = 10
PREFILTER_MIN_README_LENGTH: Final[int] = 500
PREFILTER_RECENT_DAYS: Final[int] = 90
PREFILTER_REQUIRED_KEYWORDS: Final[list[str]] = [
    # ====== Benchmark核心术语（通用） ======
    "benchmark",
    "benchmarking",
    "evaluation",
    "leaderboard",
    "dataset",
    "corpus",
    "test set",
    "test suite",
    "testbed",
    "baseline",
    "validation",
    "benchmark suite",
    "benchmark collection",
    # ====== Code相关 ======
    "code",
    "coding",
    "program",
    "programming",
    "software",
    "repository",
    "code generation",
    "code benchmark",
    "execution benchmark",
    # ====== Web/GUI ======
    "web",
    "browser",
    "gui",
    "ui",
    "automation",
    "web automation",
    # ====== Agent/Tool Use ======
    "agent",
    "multi-agent",
    "tool",
    "tool use",
    "api",
    "workflow",
    "planning",
    "agent benchmark",
    # ====== Backend/Performance ======
    "backend",
    "database",
    "sql",
    "microservices",
    "system-design",
    "performance",
    "framework",
    "server",
    "software benchmark",
    # ====== Reasoning（新增）======
    "reasoning",
    "logic",
    "logical reasoning",
    "chain-of-thought",
    "cot",
    "reasoning benchmark",
    "math",
    "mathematics",
    "mathematical reasoning",
    "problem solving",
    # ====== Knowledge（新增）======
    "knowledge",
    "question answering",
    "qa",
    "knowledge graph",
    "fact checking",
    "factual",
    "world knowledge",
    # ====== Multimodal（新增）======
    "multimodal",
    "vision-language",
    "image-text",
    "visual",
    "vision",
    "video",
    "audio",
    "speech",
    # ====== Language Understanding（新增）======
    "language",
    "nlp",
    "natural language",
    "text",
    "linguistic",
    "language understanding",
    "comprehension",
    "reading comprehension",
    # ====== Task相关（新增）======
    "task",
    "tasks",
    "challenge",
    "competition",
]
PREFILTER_EXCLUDED_KEYWORDS: Final[list[str]] = [
    # 纯NLP/多模态
    "translation",
    "summarization",
    "sentiment analysis",
    "text classification",
    "dialogue system",
    "conversational ai",
    "chatbot tutorial",
    "speech recognition",
    "audio processing",
    "image classification",
    "computer vision",
    "video processing",
    # 资源与教程
    "awesome list",
    "curated list",
    "collection of resources",
    "list of tools",
    "tutorial series",
    "online course",
    "learning guide",
    # 工具包装
    "sdk wrapper",
    "api wrapper library",
]

# ---- Scorer 配置 ----
LLM_DEFAULT_MODEL: Final[str] = "gpt-4o"  # 评分质量优先,月成本<$1完全在预算内
LLM_MODEL: Final[str] = LLM_DEFAULT_MODEL
LLM_TIMEOUT_SECONDS: Final[int] = 30
LLM_CACHE_TTL_SECONDS: Final[int] = 7 * 24 * 3600
LLM_MAX_RETRIES: Final[int] = 3
LLM_COMPLETION_MAX_TOKENS: Final[int] = 2000  # 提高max_tokens确保评分依据完整详细
LLM_REASONING_MIN_CHARS: Final[int] = 100  # 放宽至100字符，减少频繁纠偏
LLM_BACKEND_REASONING_MIN_CHARS: Final[int] = 150  # 后端专项推理最小字符数
LLM_OVERALL_REASONING_MIN_CHARS: Final[int] = 150  # overall_reasoning最小字符数
LLM_TOTAL_REASONING_MIN_CHARS: Final[int] = 800  # 总推理最少字数，降低容错
LLM_SELF_HEAL_MAX_ATTEMPTS: Final[int] = 3  # 允许最多3次纠偏，降低失败率
SCORE_CONCURRENCY: Final[int] = 50  # GPT-4o速率限制高，充分利用并发能力
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
    "activity": 0.15,  # 降低：GitHub stars容易虚高
    "reproducibility": 0.30,  # 保持：可复现性是核心
    "license": 0.15,  # 降低：不是核心指标
    "novelty": 0.15,  # 提高：Benchmark需要创新
    "relevance": 0.25,  # 提高：MGX适配度是关键
}

# ---- 存储与通知 ----
FEISHU_BATCH_SIZE: Final[int] = 20
FEISHU_RATE_LIMIT_SECONDS: Final[float] = 0.6
FEISHU_RATE_LIMIT_DELAY: Final[float] = FEISHU_RATE_LIMIT_SECONDS
FEISHU_HTTP_TIMEOUT_SECONDS: Final[int] = 15
FEISHU_HTTP_MAX_RETRIES: Final[int] = 3
FEISHU_HTTP_RETRY_DELAY_SECONDS: Final[float] = 1.5
FEISHU_BENCH_TABLE_URL: Final[str] = (
    "https://deepwisdom.feishu.cn/base/SbIibGBIWayQncslz5kcYMnrnGf?table=tblG5cMwubU6AJcV&view=vewUfT4GO6"
)
FEISHU_MEDIUM_TOPK: Final[int] = 5
FEISHU_REASONING_PREVIEW_LENGTH: Final[int] = 1500  # 评分依据字段最大长度
FEISHU_SOURCE_NAME_MAP: Final[dict[str, str]] = {
    "arxiv": "arXiv",
    "github": "GitHub",
    "huggingface": "HuggingFace",
    "semantic_scholar": "Semantic Scholar",
    "helm": "HELM",
    "techempower": "TechEmpower",
    "dbengines": "DB-Engines",
    "twitter": "Twitter",
}

# ---- 图片处理配置 ----
IMAGE_MIN_SIZE_BYTES: Final[int] = 30 * 1024  # 30KB下限（GitHub og:image约40KB）
IMAGE_MAX_SIZE_BYTES: Final[int] = 5 * 1024 * 1024  # 5MB上限，避免大文件拖慢
IMAGE_MIN_WIDTH: Final[int] = 300  # 最小宽度限制，过滤徽标/小图标
IMAGE_MIN_HEIGHT: Final[int] = 200
IMAGE_DOWNLOAD_TIMEOUT_SECONDS: Final[int] = 5
IMAGE_UPLOAD_TIMEOUT_SECONDS: Final[int] = 10
IMAGE_CACHE_TTL_SECONDS: Final[int] = 30 * 24 * 3600  # 30天缓存
IMAGE_CACHE_PREFIX: Final[str] = "feishu:img:"
IMAGE_SUPPORTED_FORMATS: Final[list[str]] = ["JPEG", "PNG", "GIF", "BMP"]

# 字符串截断长度
TITLE_TRUNCATE_SHORT: Final[int] = 50  # 日志显示
TITLE_TRUNCATE_MEDIUM: Final[int] = 60  # 摘要卡片
TITLE_TRUNCATE_LONG: Final[int] = 150  # 详细卡片
TITLE_TRUNCATE_CARD: Final[int] = 10_000  # 推送卡片标题不过滤，保留全量展示

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
# ---- Phase 8新增：任务领域 & 提取限制 ----
TASK_DOMAIN_OPTIONS: Final[list[str]] = [
    # P0核心场景
    "Coding",
    "WebDev",
    "Backend",  # Phase 7: 后端性能基准 (TechEmpower/DBEngines)
    "GUI",
    # P1高优先级
    "ToolUse",
    "Collaboration",
    "LLM/AgentOps",  # LLM运维、Agent编排、评测平台（与MGX相关）
    # P2中优先级
    "Reasoning",
    "DeepResearch",
    # 低优先级
    "Other",
]
DEFAULT_TASK_DOMAIN: Final[str] = "Other"
MAX_EXTRACTED_METRICS: Final[int] = 5
MAX_EXTRACTED_BASELINES: Final[int] = 5
MAX_EXTRACTED_AUTHORS: Final[int] = 5
DATASET_SIZE_MULTIPLIERS: Final[dict[str, int]] = {
    "k": 1_000,
    "m": 1_000_000,
}

# ============================================================
# 去重配置
# ============================================================
# 去重时仅对比最近N天内的已入库记录，降低新数据被老记录覆盖的概率
DEDUP_LOOKBACK_DAYS: Final[int] = 14
# 按来源定制去重窗口，未命中则使用default
DEDUP_LOOKBACK_DAYS_BY_SOURCE: Final[dict[str, int]] = {
    "arxiv": 3,  # arXiv仅对比近3天，避免与7天采集窗口完全重叠
    "default": DEDUP_LOOKBACK_DAYS,
}

# ============================================================
# 推送多样性与低优先精选配置
# ============================================================
FEISHU_PER_SOURCE_TOPK: Final[int] = 1  # 每个来源至少推送1条（中优摘要补齐）
FEISHU_LOW_PICK_ENABLED: Final[bool] = True  # 是否开启低优先精选分区
FEISHU_LOW_PICK_PER_SOURCE: Final[dict[str, int]] = {
    "arxiv": 2,
    "huggingface": 1,
    "helm": 1,
}
# 推送过滤与质量控制
PUSH_MAX_AGE_DAYS: Final[int] = 30  # 超过30天仅保留高分(>=8)的历史优质项
PUSH_RELEVANCE_FLOOR: Final[float] = 5.5  # 任务相关性下限，低于则不推
PUSH_TOTAL_CAP: Final[int] = 15  # 单次推送总条数上限

# 推送卡片UX（方案B：两分区）
CORE_DOMAINS: Final[list[str]] = [
    "Coding",
    "Backend",
    "WebDev",
    "GUI",
    "ToolUse",
    "Collaboration",
    "LLM/AgentOps",
    "Reasoning",
    "DeepResearch",
    "Other",
]
MAIN_RECOMMENDATION_LIMIT: Final[int] = 12  # 最新推荐区最多条目
TASK_FILL_MIN_SCORE: Final[float] = 5.0  # 补位候选最低分（若无则放宽由调用方控制）
TASK_FILL_PER_DOMAIN_LIMIT: Final[int] = 1
TASK_FILL_SHOW_MISSING: Final[bool] = True
# 论文来源评分折扣（后处理，用于平衡活跃度/复现性偏低）
PAPER_ACTIVITY_DISCOUNT: Final[float] = 1.0  # 关闭论文活跃度折扣，防止非GitHub源被压分
PAPER_REPRODUCIBILITY_DISCOUNT: Final[float] = 1.0  # 关闭论文复现性折扣
PAPER_MGX_BONUS: Final[float] = 0.1  # MGX适配度加权
PAPER_MIN_SCORE_FOR_LOW_PICK: Final[float] = 5.5  # 放宽门槛，避免全被过滤
PAPER_MIN_RELEVANCE_FOR_LOW_PICK: Final[float] = 5.5
PAPER_MAX_PUBLISH_DAYS_FOR_LOW_PICK: Final[int] = 10  # 放宽到10天，保留更多最新论文

# ============================================================
# 智能推送策略配置（任务领域与新鲜度优先）
# ============================================================
SOURCE_SCORE_THRESHOLDS: Final[dict[str, float]] = {
    "arxiv": 2.5,
    "helm": 3.0,
    "huggingface": 3.0,
    "dbengines": 3.0,
    "techempower": 3.0,
    "github": 6.0,
    "default": MIN_TOTAL_SCORE,
}

# arXiv 需兼顾任务相关性，避免无关低分噪声
ARXIV_MIN_RELEVANCE: Final[float] = 6.0

# 时间新鲜度加权（以发布日期为基准）
FRESHNESS_BOOST_7D: Final[float] = 1.5
FRESHNESS_BOOST_14D: Final[float] = 0.8
FRESHNESS_BOOST_30D: Final[float] = 0.3

# 各来源保底推送 TopK，优先最新、其次高分
PER_SOURCE_TOPK_PUSH: Final[dict[str, int]] = {
    "arxiv": 3,
    "github": 3,
    "helm": 2,
    "huggingface": 2,
    "dbengines": 1,
    "techempower": 1,
}

# 低优池按任务类型补位配置
LOW_PICK_BY_TASK_ENABLED: Final[bool] = True
LOW_PICK_TASK_TOPK: Final[int] = 2
LOW_PICK_SCORE_FLOOR: Final[float] = 5.0

# 智能推送开关
ENABLE_SMART_PUSH_STRATEGY: Final[bool] = True
