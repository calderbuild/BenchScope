"""LLM评分测试"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models import RawCandidate
from src.scorer.llm_scorer import LLMScorer


@pytest.fixture(autouse=True)
def ensure_openai_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    yield


@pytest.fixture
def sample_candidate():
    return RawCandidate(
        title="AgentBench: Evaluating LLMs as Agents",
        url="https://arxiv.org/abs/2308.03688",
        source="arxiv",
        abstract="We present AgentBench, a benchmark for evaluating LLMs.",
        authors=["Author A"],
        publish_date=datetime.now(timezone.utc),
        github_url="https://github.com/example/agentbench",
        github_stars=1500,
    )


@pytest.mark.asyncio
async def test_llm_scorer_with_mock(sample_candidate):
    """测试LLM评分（Mock OpenAI API）"""

    mock_response = MagicMock()
    mock_response.choices = [
        MagicMock(
            message=MagicMock(
                content='{"activity_score": 8.5, "reproducibility_score": 9.0, "license_score": 10.0, "novelty_score": 7.0, "relevance_score": 8.0, "reasoning": "Test"}'
            )
        )
    ]

    with patch("src.scorer.llm_scorer.AsyncOpenAI") as mock_openai:
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai.return_value = mock_client

        async with LLMScorer() as scorer:
            scorer.redis_client = None  # 禁用Redis
            result = await scorer.score(sample_candidate)

            assert result.title == sample_candidate.title
            assert 0 <= result.activity_score <= 10
            assert 0 <= result.reproducibility_score <= 10
            assert result.reasoning == "Test"


@pytest.mark.asyncio
async def test_fallback_score(sample_candidate):
    """测试规则兜底评分"""

    async with LLMScorer() as scorer:
        fallback = scorer._fallback_score(sample_candidate)

        assert fallback["activity_score"] == 9.0
        assert fallback["reproducibility_score"] == 6.0
        assert "reasoning" in fallback
