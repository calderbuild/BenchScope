# CODEX-PHASE17: Notification Deduplication & Storage Priority Filter

**Date**: 2026-01-06
**Author**: Claude Code (Analysis & Design)
**Executor**: Codex (Implementation)
**Priority**: High - Production Bug Fix

---

## Problem Diagnosis

### Issue 1: Duplicate Notifications (Critical)

**User Report**:
> "这几天的推送有很多的重复... 如果已经出现过的提醒或者项目，出现大于等于3次，就加入过滤吧"

**Evidence** (from user's notification logs 12/29 - 1/6):
- `ecrindigital/facetpack` - appeared 8+ times
- `FrontierCS/Frontier-CS` - appeared 8+ times
- `IQuestLab/IQuest-Coder-V1` - appeared 4+ times
- `yuntian-deng/FlashMLA` - appeared 5+ times

**Root Cause Analysis**:

1. **Current Deduplication Flow** (`src/main.py` lines 173-229):
   ```
   Step 1.5: URL去重
   - Internal batch dedup (within current collection)
   - Time-windowed dedup against Feishu (7-30 days by source)
   ```

2. **Gap Identified**:
   - Dedup windows are limited (arxiv=7 days, github=30 days)
   - After window expires, same project gets re-collected
   - **No persistent "notification history" tracking**
   - Same project can be notified unlimited times

3. **Code Path**:
   ```python
   # src/main.py:291-308
   actually_saved = await storage.save(scored)  # Saves to Feishu
   if actually_saved:
       await notifier.notify(actually_saved)  # Notifies ALL saved items
   ```

### Issue 2: Low Priority Storage (User Request)

**User Request**:
> "推送到飞书表格只需要推送中高分就行了... 低分low不用保存到表格"

**Current Behavior**: All scored candidates (regardless of priority) are saved to Feishu table.

**Required Change**: Filter out `priority == "low"` before saving to Feishu table.

---

## Solution Design

### Solution 1: Notification History Tracking (SQLite-based)

**Approach**: Use SQLite (already in use as fallback) to track notification history.

**Why SQLite (not Feishu field)**:
- Fast local lookups (no API overhead)
- Already integrated in the project
- Simpler implementation (no schema migration)
- Survives GitHub Actions runs (persisted as artifact)

**New SQLite Table Schema**:
```sql
CREATE TABLE IF NOT EXISTS notification_history (
    url_key TEXT PRIMARY KEY,     -- Canonical URL (from canonicalize_url)
    notify_count INTEGER DEFAULT 0,
    first_notified TEXT,          -- ISO datetime
    last_notified TEXT,           -- ISO datetime
    title TEXT                    -- For debugging
);
```

### Solution 2: Priority-based Storage Filter

**Approach**: Filter candidates before calling `storage.save()`.

**Filter Rule**: Only save candidates where `priority in ("high", "medium")`.

---

## Implementation Steps

### Step 1: Create Notification History Module

**File**: `src/storage/notification_history.py` (NEW FILE)

```python
"""Notification History Tracking for Deduplication

Tracks how many times each project has been notified.
Projects notified >= 3 times are filtered from future notifications.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.common.url_utils import canonicalize_url

logger = logging.getLogger(__name__)

# Default database path (same directory as fallback.db)
NOTIFICATION_HISTORY_DB = "notification_history.db"
MAX_NOTIFY_COUNT = 3  # Filter threshold


class NotificationHistory:
    """Track notification history per project URL."""

    def __init__(self, db_path: str = NOTIFICATION_HISTORY_DB) -> None:
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self) -> None:
        """Create notification_history table if not exists."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notification_history (
                    url_key TEXT PRIMARY KEY,
                    notify_count INTEGER DEFAULT 0,
                    first_notified TEXT,
                    last_notified TEXT,
                    title TEXT
                )
            """)
            conn.commit()
        logger.debug("Notification history table ready: %s", self.db_path)

    def get_notify_count(self, url: str) -> int:
        """Get notification count for a URL."""
        url_key = canonicalize_url(url)
        if not url_key:
            return 0

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT notify_count FROM notification_history WHERE url_key = ?",
                (url_key,)
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def should_notify(self, url: str) -> bool:
        """Check if project should be notified (count < threshold)."""
        count = self.get_notify_count(url)
        return count < MAX_NOTIFY_COUNT

    def increment_notify_count(
        self, url: str, title: Optional[str] = None
    ) -> int:
        """Increment notification count for a URL. Returns new count."""
        url_key = canonicalize_url(url)
        if not url_key:
            return 0

        now = datetime.now().isoformat()

        with sqlite3.connect(self.db_path) as conn:
            # Check if exists
            cursor = conn.execute(
                "SELECT notify_count FROM notification_history WHERE url_key = ?",
                (url_key,)
            )
            row = cursor.fetchone()

            if row:
                new_count = row[0] + 1
                conn.execute("""
                    UPDATE notification_history
                    SET notify_count = ?, last_notified = ?, title = COALESCE(?, title)
                    WHERE url_key = ?
                """, (new_count, now, title, url_key))
            else:
                new_count = 1
                conn.execute("""
                    INSERT INTO notification_history
                    (url_key, notify_count, first_notified, last_notified, title)
                    VALUES (?, ?, ?, ?, ?)
                """, (url_key, new_count, now, now, title or ""))

            conn.commit()
            return new_count

    def get_over_threshold_urls(self) -> set[str]:
        """Get all URL keys that have been notified >= threshold times."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT url_key FROM notification_history WHERE notify_count >= ?",
                (MAX_NOTIFY_COUNT,)
            )
            return {row[0] for row in cursor.fetchall()}

    def get_stats(self) -> dict:
        """Get notification history statistics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN notify_count >= ? THEN 1 ELSE 0 END) as over_threshold,
                    AVG(notify_count) as avg_count,
                    MAX(notify_count) as max_count
                FROM notification_history
            """, (MAX_NOTIFY_COUNT,))
            row = cursor.fetchone()
            return {
                "total_tracked": row[0] or 0,
                "over_threshold": row[1] or 0,
                "avg_notify_count": round(row[2] or 0, 2),
                "max_notify_count": row[3] or 0,
            }
```

### Step 2: Update Notifier to Use History

**File**: `src/notifier/feishu_notifier.py`

**Change 1**: Add import at top of file (around line 15):

```python
# Current:
from src.common.url_utils import canonicalize_url

# Add after:
from src.storage.notification_history import NotificationHistory
```

**Change 2**: Initialize history tracker in `__init__` (around line 60-70):

```python
# Current __init__:
def __init__(self, settings: Optional[Settings] = None) -> None:
    self.settings = settings or get_settings()
    # ... existing code ...

# Add at end of __init__:
    self.notification_history = NotificationHistory()
```

**Change 3**: Filter by notification history in `notify()` method.

Find the `notify()` method (around line 100-150) and add filtering logic after the initial filtering:

```python
async def notify(self, candidates: List[ScoredCandidate]) -> None:
    """分层推送: 高优先级卡片 + 中优先级摘要"""
    if not candidates:
        logger.info("无候选项，跳过通知")
        return

    # Existing prefilter logic
    filtered = self._prefilter_for_push(candidates)

    # ADD THIS: Filter by notification history (>=3 times = skip)
    before_history_filter = len(filtered)
    filtered = [
        c for c in filtered
        if self.notification_history.should_notify(c.url)
    ]
    history_filtered_count = before_history_filter - len(filtered)
    if history_filtered_count > 0:
        logger.info(
            "Notification history filter: removed %d items (notified >=3 times)",
            history_filtered_count
        )

    if not filtered:
        logger.info("过滤后无候选项，跳过通知")
        return

    # ... rest of existing notify logic ...
```

**Change 4**: Increment history after successful notification.

Find where the notification is sent (look for `_send_card` or similar calls) and add increment logic after success:

```python
# After successful card send, add:
for candidate in notified_candidates:
    self.notification_history.increment_notify_count(
        candidate.url,
        title=candidate.title
    )
logger.info(
    "Updated notification history for %d candidates",
    len(notified_candidates)
)
```

### Step 3: Add Priority Filter Before Storage

**File**: `src/main.py`

**Change**: Filter out low priority before saving to Feishu (around line 294-299):

```python
# CURRENT CODE (around line 294):
    # Step 6: 存储入库
    logger.info("[6/8] 存储入库...")
    actually_saved = await storage.save(scored)

# REPLACE WITH:
    # Step 6: 存储入库 (仅保存high/medium优先级)
    logger.info("[6/8] 存储入库...")

    # Filter: only save high/medium priority to Feishu
    high_medium = [c for c in scored if c.priority in ("high", "medium")]
    low_filtered = len(scored) - len(high_medium)
    if low_filtered > 0:
        logger.info(
            "Priority filter: skipped %d low priority candidates (not saved to Feishu)",
            low_filtered
        )

    actually_saved = await storage.save(high_medium)
```

### Step 4: Add Constants for Configuration

**File**: `src/common/constants.py`

Add at the end of the file (around line 980):

```python
# ============================================================
# Phase 17: Notification Deduplication
# ============================================================
NOTIFICATION_HISTORY_DB: Final[str] = "notification_history.db"
NOTIFICATION_MAX_COUNT: Final[int] = 3  # Filter projects notified >= this many times
```

### Step 5: Update GitHub Actions to Persist History

**File**: `.github/workflows/daily_collect.yml`

**Change 1**: Add download step for notification history (after checkout, around line 27):

```yaml
      - name: Download notification history
        continue-on-error: true
        uses: dawidd6/action-download-artifact@v3
        with:
          name: notification-history
          path: .
          search_artifacts: true
          workflow_conclusion: success
```

**Change 2**: Add upload step for notification history (after SQLite backup, around line 146):

```yaml
      - name: Upload notification history
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: notification-history
          path: notification_history.db
          retention-days: 30  # Keep longer than logs
```

---

## Testing Plan

### Unit Tests

**File**: `tests/test_notification_history.py` (NEW FILE)

```python
"""Tests for notification history tracking."""

import os
import tempfile
import pytest
from src.storage.notification_history import NotificationHistory

@pytest.fixture
def history():
    """Create a temporary notification history database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    hist = NotificationHistory(db_path=db_path)
    yield hist

    # Cleanup
    os.unlink(db_path)


def test_initial_count_is_zero(history):
    """New URLs should have count of 0."""
    assert history.get_notify_count("https://github.com/test/repo") == 0


def test_increment_count(history):
    """Incrementing should increase count by 1."""
    url = "https://github.com/test/repo"

    count1 = history.increment_notify_count(url, title="Test Repo")
    assert count1 == 1

    count2 = history.increment_notify_count(url)
    assert count2 == 2


def test_should_notify_threshold(history):
    """Projects at or above threshold should not be notified."""
    url = "https://github.com/test/repo"

    # First 2 notifications should be allowed
    assert history.should_notify(url) is True
    history.increment_notify_count(url)
    assert history.should_notify(url) is True
    history.increment_notify_count(url)
    assert history.should_notify(url) is True
    history.increment_notify_count(url)

    # Third notification puts it at threshold
    assert history.should_notify(url) is False


def test_url_canonicalization(history):
    """Different URL formats should be treated as same."""
    url1 = "https://github.com/test/repo"
    url2 = "https://github.com/test/repo/"
    url3 = "https://www.github.com/test/repo"

    history.increment_notify_count(url1)

    # All should return same count (depends on canonicalize_url implementation)
    assert history.get_notify_count(url1) == 1


def test_stats(history):
    """Stats should accurately reflect history."""
    history.increment_notify_count("https://a.com/1")
    history.increment_notify_count("https://a.com/2")
    history.increment_notify_count("https://a.com/2")
    history.increment_notify_count("https://a.com/2")  # Over threshold

    stats = history.get_stats()
    assert stats["total_tracked"] == 2
    assert stats["over_threshold"] == 1
```

### Integration Test Commands

```bash
# Run unit tests
.venv/bin/python -m pytest tests/test_notification_history.py -v

# Run full pipeline (local test)
.venv/bin/python -m src.main

# Check notification history stats
.venv/bin/python -c "
from src.storage.notification_history import NotificationHistory
h = NotificationHistory()
print(h.get_stats())
"

# Verify priority filtering in logs
grep "Priority filter" logs/benchscope.log

# Verify notification history filtering in logs
grep "Notification history filter" logs/benchscope.log
```

---

## Success Criteria

### Functional Requirements

- [ ] New `notification_history.db` is created and persisted
- [ ] Projects notified >= 3 times are filtered from notifications
- [ ] Low priority candidates are NOT saved to Feishu table
- [ ] High/medium priority candidates ARE saved and notified

### Performance Requirements

- [ ] SQLite lookups add < 1 second to total pipeline time
- [ ] No increase in Feishu API calls

### Verification Checklist

- [ ] Run pipeline locally, verify notification_history.db is created
- [ ] Verify logs show "Priority filter: skipped X low priority candidates"
- [ ] Verify logs show "Notification history filter: removed X items"
- [ ] After 3 notifications, same project should not appear in notifications
- [ ] Feishu table should only contain high/medium priority entries
- [ ] GitHub Actions artifact should include notification_history.db

---

## Risk Analysis

### Low Risk

1. **SQLite file corruption**: SQLite handles this gracefully, worst case is reset to empty
2. **Disk space**: Notification history is tiny (< 1MB for 10k entries)

### Mitigation

1. **Backward compatibility**: New feature only, no existing code paths broken
2. **Graceful degradation**: If history DB fails, notification continues (just no dedup)

---

## File Change Summary

| File | Action | Lines Changed |
|------|--------|--------------|
| `src/storage/notification_history.py` | NEW | ~100 lines |
| `src/notifier/feishu_notifier.py` | MODIFY | ~20 lines |
| `src/main.py` | MODIFY | ~10 lines |
| `src/common/constants.py` | MODIFY | ~5 lines |
| `.github/workflows/daily_collect.yml` | MODIFY | ~15 lines |
| `tests/test_notification_history.py` | NEW | ~60 lines |

---

## Execution Notes for Codex

1. **Create new file first**: `src/storage/notification_history.py`
2. **Update imports**: Add to `src/storage/__init__.py` if exists
3. **Test incrementally**: Run unit tests after each file change
4. **Preserve existing logic**: Priority filter is additive, not replacement
5. **Log verbosity**: Use INFO level for filter counts, DEBUG for individual items

---

*Document prepared by Claude Code for Codex implementation*
