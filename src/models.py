"""核心数据模型定义"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Literal, Optional

from src.common import constants

SourceType = Literal[
    "arxiv",
    "github",
    "pwc",
    "huggingface",
    "semantic_scholar",
    "helm",
    "techempower",
    "dbengines",
    "twitter",
]


@dataclass(slots=True)
class RawCandidate:
    """采集器原始输出结构"""

    title: str
    url: str
    source: SourceType
    abstract: Optional[str] = None
    authors: Optional[List[str]] = None
    publish_date: Optional[datetime] = None
    github_stars: Optional[int] = None
    github_url: Optional[str] = None
    dataset_url: Optional[str] = None
    hero_image_url: Optional[str] = None  # Phase 9: 图片原始URL
    hero_image_key: Optional[str] = None  # Phase 9: 飞书image_key
    # Phase 8新增：采集阶段粗提取的元数据
    raw_metrics: Optional[List[str]] = None  # 原始指标文本
    raw_baselines: Optional[List[str]] = None  # 原始baseline文本
    raw_authors: Optional[str] = None  # 原始作者字符串
    raw_institutions: Optional[str] = None  # 原始机构字符串
    raw_dataset_size: Optional[str] = None  # 原始数据规模描述

    raw_metadata: Dict[str, str] = field(default_factory=dict)

    # Phase 6 新增字段（从采集器直接提取）
    paper_url: Optional[str] = None  # 论文URL（arXiv/SemanticScholar自动填充）
    task_type: Optional[str] = None  # 任务类型（从README/metadata提取）
    license_type: Optional[str] = None  # License类型（GitHub API返回）
    evaluation_metrics: Optional[List[str]] = None  # 评估指标（从摘要/README提取）
    reproduction_script_url: Optional[str] = None  # 复现脚本链接（从README提取）


@dataclass(slots=True)
class ScoredCandidate:
    """Phase 2评分后的候选项 (5维度评分模型)"""

    # RawCandidate字段
    title: str
    url: str
    source: SourceType
    abstract: Optional[str] = None
    authors: Optional[List[str]] = None
    publish_date: Optional[datetime] = None
    github_stars: Optional[int] = None
    github_url: Optional[str] = None
    dataset_url: Optional[str] = None
    hero_image_url: Optional[str] = None
    hero_image_key: Optional[str] = None
    raw_metadata: Dict[str, str] = field(default_factory=dict)
    raw_metrics: Optional[List[str]] = None
    raw_baselines: Optional[List[str]] = None
    raw_authors: Optional[str] = None
    raw_institutions: Optional[str] = None
    raw_dataset_size: Optional[str] = None

    # Phase 2评分字段
    activity_score: float = 0.0  # 活跃度 (25%)
    reproducibility_score: float = 0.0  # 可复现性 (30%)
    license_score: float = 0.0  # 许可合规 (20%)
    novelty_score: float = 0.0  # 新颖性 (15%)
    relevance_score: float = 0.0  # MGX适配度 (10%)
    score_reasoning: str = ""
    custom_total_score: Optional[float] = None  # 后端专项评分可覆盖总分

    # 全LLM统一评分新增：详细推理字段（每个维度150+字符）
    activity_reasoning: str = ""  # 活跃度详细推理
    reproducibility_reasoning: str = ""  # 可复现性详细推理
    license_reasoning: str = ""  # 许可合规详细推理
    novelty_reasoning: str = ""  # 新颖性详细推理
    relevance_reasoning: str = ""  # MGX适配度详细推理

    # 后端专项评分字段（仅后端Benchmark）
    backend_mgx_relevance: float = 0.0  # 后端MGX相关性评分 (0-10)
    backend_mgx_reasoning: str = ""  # 后端MGX相关性详细推理 (200+字符)
    backend_engineering_value: float = 0.0  # 后端工程实践价值评分 (0-10)
    backend_engineering_reasoning: str = ""  # 后端工程价值详细推理 (200+字符)

    # 综合推理字段（50+字符，总结性陈述）
    overall_reasoning: str = ""  # 综合评估推理

    # Phase 6 新增字段
    paper_url: Optional[str] = None  # 论文URL (独立于GitHub URL)
    reproduction_script_url: Optional[str] = None  # 复现脚本URL
    evaluation_metrics: Optional[List[str]] = (
        None  # 评估指标列表 (如["Accuracy", "F1"])
    )
    task_type: Optional[str] = None  # 任务类型 (如"Code Generation", "QA")
    license_type: Optional[str] = None  # 具体License类型 (如"MIT", "Apache-2.0")

    # Phase 8新增：LLM抽取字段
    task_domain: Optional[str] = None
    metrics: Optional[List[str]] = None
    baselines: Optional[List[str]] = None
    institution: Optional[str] = None
    dataset_size: Optional[int] = None
    dataset_size_description: Optional[str] = None

    @property
    def reasoning(self) -> str:
        """兼容旧字段命名"""

        return self.score_reasoning

    @reasoning.setter
    def reasoning(self, value: str) -> None:
        self.score_reasoning = value

    @property
    def total_score(self) -> float:
        """加权总分(0-10)"""

        if self.custom_total_score is not None:
            return self.custom_total_score

        weights = constants.SCORE_WEIGHTS
        return (
            self.activity_score * weights["activity"]
            + self.reproducibility_score * weights["reproducibility"]
            + self.license_score * weights["license"]
            + self.novelty_score * weights["novelty"]
            + self.relevance_score * weights["relevance"]
        )

    @property
    def priority(self) -> str:
        """自动分级"""

        total = self.total_score
        if total >= 8.0:
            return "high"
        if total >= 6.0:
            return "medium"
        return "low"
