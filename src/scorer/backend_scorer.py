"""后端Benchmark专项评分器"""

from __future__ import annotations

import logging
from typing import Dict

from src.common import constants
from src.models import RawCandidate, ScoredCandidate

logger = logging.getLogger(__name__)


class BackendBenchmarkScorer:
    """基于启发式规则的后端Benchmark评分"""

    WEIGHTS = {
        "engineering_value": 0.30,
        "performance_coverage": 0.25,
        "reproducibility": 0.20,
        "industry_adoption": 0.15,
        "relevance": 0.10,
    }

    BACKEND_KEYWORDS = [
        "backend",
        "api",
        "database",
        "microservice",
        "microservices",
        "rest",
        "graphql",
        "latency",
        "throughput",
        "qps",
        "rps",
        "scalability",
        "distributed",
        "server",
        "system design",
    ]

    PERFORMANCE_DIMENSIONS = {
        "latency": ["latency", "p99", "p95", "response time"],
        "throughput": ["throughput", "qps", "rps", "requests per second"],
        "concurrency": ["concurrency", "parallel", "async", "goroutine"],
        "memory": ["memory", "heap", "gc", "allocation"],
        "database": ["sql", "query", "database", "transaction", "orm"],
    }

    MGX_KEYWORDS = [
        "ai",
        "code generation",
        "agent",
        "automation",
        "tool",
    ]

    def score(self, candidate: RawCandidate) -> ScoredCandidate:
        """对后端相关候选进行启发式打分"""

        scores = {
            "engineering_value": self._score_engineering_value(candidate),
            "performance_coverage": self._score_performance_coverage(candidate),
            "reproducibility": self._score_reproducibility(candidate),
            "industry_adoption": self._score_industry_adoption(candidate),
            "relevance": self._score_relevance(candidate),
        }

        backend_total = sum(scores[key] * self.WEIGHTS[key] for key in scores)
        reasoning = self._build_reasoning(scores)

        return self._to_scored_candidate(candidate, scores, backend_total, reasoning)

    def _score_engineering_value(self, candidate: RawCandidate) -> float:
        """依据描述和来源评估工程价值"""

        text = self._concat_text(candidate)
        hits = sum(1 for kw in self.BACKEND_KEYWORDS if kw in text)

        base = 5.0
        if candidate.source in {"techempower", "dbengines"}:
            base = 7.0
        stars = candidate.github_stars or 0
        if stars >= 500:
            base += 1.0
        elif stars >= 100:
            base += 0.5

        score = base + hits * 0.4
        return min(10.0, score)

    def _score_performance_coverage(self, candidate: RawCandidate) -> float:
        """统计覆盖的性能维度数量"""

        text_lower = self._concat_text(candidate)
        coverage = 0
        for keywords in self.PERFORMANCE_DIMENSIONS.values():
            if any(kw in text_lower for kw in keywords):
                coverage += 1
        return min(10.0, coverage * 2.0)

    def _score_reproducibility(self, candidate: RawCandidate) -> float:
        """可复现性评分，基于代码、数据等信号"""

        score = 3.0
        if candidate.github_url:
            score += 3.0
        if candidate.dataset_url:
            score += 2.0
        license_value = (
            (candidate.license_type or "")
            or candidate.raw_metadata.get("license", "")
        ).lower()
        if any(keyword in license_value for keyword in ["mit", "apache", "bsd"]):
            score += 1.5
        elif license_value:
            score += 0.5
        docs_signal = candidate.raw_metadata.get("readme_length")
        try:
            readme_len = int(docs_signal) if docs_signal else 0
        except ValueError:
            readme_len = 0
        if readme_len > 800:
            score += 0.5
        return min(10.0, score)

    def _score_industry_adoption(self, candidate: RawCandidate) -> float:
        """行业采用度，结合Stars与权威来源"""

        if candidate.source == "techempower":
            return 9.0
        if candidate.source == "dbengines":
            return 7.5

        stars = candidate.github_stars or 0
        if stars >= 5000:
            return 10.0
        if stars >= 1000:
            return 8.0
        if stars >= 500:
            return 6.5
        if stars >= 100:
            return 5.0

        ranking_score = self._parse_float(candidate.raw_metadata.get("ranking_score"))
        if ranking_score and ranking_score > 20:
            return 6.0

        return 4.0

    def _score_relevance(self, candidate: RawCandidate) -> float:
        """MGX相关性，后端默认高相关"""

        base = 6.0
        text_lower = (candidate.abstract or "") + " " + candidate.title
        text_lower = text_lower.lower()
        hits = sum(1 for kw in self.MGX_KEYWORDS if kw in text_lower)
        return min(10.0, base + hits * 1.0)

    def _build_reasoning(self, scores: Dict[str, float]) -> str:
        """生成中文说明，突出得分最高的两个维度"""

        top_dims = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:2]
        mapping = {
            "engineering_value": "工程实践价值",
            "performance_coverage": "性能覆盖面",
            "reproducibility": "可复现性",
            "industry_adoption": "行业采用度",
            "relevance": "MGX相关性",
        }
        highlights = ", ".join(
            f"{mapping[dim]} {score:.1f}" for dim, score in top_dims
        )
        return f"后端专项评分：{highlights}"

    def _to_scored_candidate(
        self,
        candidate: RawCandidate,
        scores: Dict[str, float],
        backend_total: float,
        reasoning: str,
    ) -> ScoredCandidate:
        """将候选与评分合并输出"""

        # 复用通用的5个维度字段，分别映射到后端专项含义
        return ScoredCandidate(
            title=candidate.title,
            url=candidate.url,
            source=candidate.source,
            abstract=candidate.abstract,
            authors=candidate.authors,
            publish_date=candidate.publish_date,
            github_stars=candidate.github_stars,
            github_url=candidate.github_url,
            dataset_url=candidate.dataset_url,
            hero_image_url=candidate.hero_image_url,
            hero_image_key=candidate.hero_image_key,
            raw_metadata=candidate.raw_metadata,
            raw_metrics=candidate.raw_metrics,
            raw_baselines=candidate.raw_baselines,
            raw_authors=candidate.raw_authors,
            raw_institutions=candidate.raw_institutions,
            raw_dataset_size=candidate.raw_dataset_size,
            paper_url=candidate.paper_url,
            task_type=candidate.task_type,
            license_type=candidate.license_type,
            evaluation_metrics=candidate.evaluation_metrics,
            reproduction_script_url=candidate.reproduction_script_url,
            activity_score=scores["engineering_value"],
            reproducibility_score=scores["reproducibility"],
            license_score=scores["industry_adoption"],
            novelty_score=scores["performance_coverage"],
            relevance_score=scores["relevance"],
            score_reasoning=reasoning,
            custom_total_score=round(backend_total, 2),
            task_domain=candidate.task_type or constants.DEFAULT_TASK_DOMAIN,
            metrics=candidate.evaluation_metrics,
            baselines=candidate.raw_baselines,
            institution=candidate.raw_institutions,
            dataset_size=None,
            dataset_size_description=candidate.raw_dataset_size,
        )

    def _concat_text(self, candidate: RawCandidate) -> str:
        """合并摘要和原始元数据文本并转小写"""

        meta_text = " ".join(
            str(value) for value in candidate.raw_metadata.values() if value
        )
        return f"{candidate.abstract or ''} {meta_text}".lower()

    @staticmethod
    def _parse_float(value: str | None) -> float | None:
        """安全解析字符串为float"""

        if not value:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
