"""存储层测试"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.models import ScoredCandidate
from src.storage.feishu_storage import FeishuStorage
from src.storage.sqlite_fallback import SQLiteFallback
from src.storage.storage_manager import StorageManager


@pytest.mark.asyncio
async def test_sqlite_fallback_roundtrip(tmp_path, monkeypatch):
    """写入后应能读取并标记同步"""

    db_file = tmp_path / "fallback.db"
    monkeypatch.setenv("SQLITE_DB_PATH", str(db_file))

    fallback = SQLiteFallback()
    candidate = _candidate()

    await fallback.save([candidate])
    unsynced = await fallback.get_unsynced()
    assert len(unsynced) == 1

    await fallback.mark_synced([candidate.url])
    await fallback.cleanup_old_records(days=0)


def test_feishu_record_mapping():
    candidate = _candidate()
    settings = SimpleNamespace(
        feishu=SimpleNamespace(
            app_id="app",
            app_secret="secret",
            bitable_app_token="app_token",
            bitable_table_id="tbl_id",
            webhook_url=None,
        )
    )
    storage = FeishuStorage(settings=settings)
    record = storage._to_feishu_record(candidate)
    fields = record["fields"]

    assert fields["标题"] == candidate.title
    assert fields["总分"] == round(candidate.total_score, 2)
    assert fields["优先级"] == candidate.priority


@pytest.mark.asyncio
async def test_storage_manager_fallback():
    feishu = AsyncMock()
    feishu.save.side_effect = Exception("api down")
    sqlite = AsyncMock()
    manager = StorageManager(feishu=feishu, sqlite=sqlite)

    await manager.save([_candidate()])

    feishu.save.assert_awaited()
    sqlite.save.assert_awaited()


def _candidate() -> ScoredCandidate:
    return ScoredCandidate(
        title="Test Benchmark",
        url="https://example.com",
        source="arxiv",
        abstract="A benchmark abstract that exceeds twenty characters.",
        activity_score=8.0,
        reproducibility_score=7.0,
        license_score=6.0,
        novelty_score=5.0,
        relevance_score=4.0,
        reasoning="Great benchmark",
    )
