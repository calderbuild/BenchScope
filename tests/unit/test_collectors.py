"""数据采集器测试"""
from __future__ import annotations

import pytest

from src.collectors.huggingface_collector import HuggingFaceCollector


@pytest.mark.asyncio
async def test_huggingface_collector_filters(monkeypatch):
    """确保仅返回符合下载量与关键词的数据集"""

    required_env = {
        "OPENAI_API_KEY": "test",
        "FEISHU_APP_ID": "test",
        "FEISHU_APP_SECRET": "test",
        "FEISHU_BITABLE_APP_TOKEN": "app",
        "FEISHU_BITABLE_TABLE_ID": "tbl",
    }
    for key, value in required_env.items():
        monkeypatch.setenv(key, value)

    collector = HuggingFaceCollector()

    async def fake_fetch():
        return [
            {
                "id": "good/dataset",
                "downloads": 200,
                "cardData": {"summary": "A benchmark dataset", "pretty_name": "GoodBench"},
                "lastModified": "2025-11-10T00:00:00Z",
            },
            {
                "id": "bad/dataset",
                "downloads": 50,
                "cardData": {"summary": "toy data"},
            },
        ]

    monkeypatch.setattr(collector, "_fetch_datasets", fake_fetch)

    results = await collector.collect()

    assert len(results) == 1
    assert results[0].source == "huggingface"
    assert results[0].title == "GoodBench"
