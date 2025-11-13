"""核心数据模型定义"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Literal, Optional

from src.common import constants

from src.common import constants

SourceType = Literal["arxiv", "github", "pwc", "huggingface"]


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
    raw_metadata: Dict[str, str] = field(default_factory=dict)


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
    raw_metadata: Dict[str, str] = field(default_factory=dict)

    # Phase 2评分字段
    activity_score: float = 0.0  # 活跃度 (25%)
    reproducibility_score: float = 0.0  # 可复现性 (30%)
    license_score: float = 0.0  # 许可合规 (20%)
    novelty_score: float = 0.0  # 新颖性 (15%)
    relevance_score: float = 0.0  # MGX适配度 (10%)
    reasoning: str = ""

    # Phase 6 新增字段
    paper_url: Optional[str] = None  # 论文URL (独立于GitHub URL)
    reproduction_script_url: Optional[str] = None  # 复现脚本URL
    evaluation_metrics: Optional[List[str]] = None  # 评估指标列表 (如["Accuracy", "F1"])
    task_type: Optional[str] = None  # 任务类型 (如"Code Generation", "QA")
    license_type: Optional[str] = None  # 具体License类型 (如"MIT", "Apache-2.0")

    @property
    def total_score(self) -> float:
        """加权总分(0-10)"""

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


@dataclass(slots=True)
class GitHubRelease:
    """GitHub Release版本信息"""

    repo_url: str
    tag_name: str
    published_at: datetime
    release_notes: str
    html_url: str


@dataclass(slots=True)
class ArxivVersion:
    """arXiv 论文版本信息"""

    arxiv_id: str
    version: str
    updated_at: datetime
    summary: str
    url: str
