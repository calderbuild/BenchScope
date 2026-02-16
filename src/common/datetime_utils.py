"""日期时间工具函数"""

from __future__ import annotations

from datetime import datetime, timezone


def ensure_utc(dt: datetime | None) -> datetime | None:
    """确保datetime有UTC时区信息，naive datetime会被添加UTC时区"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def calculate_age_days(publish_date: datetime | None) -> int | None:
    """计算发布距今天数"""
    if publish_date is None:
        return None

    publish_dt = ensure_utc(publish_date)
    now = datetime.now(tz=timezone.utc)
    return (now - publish_dt).days


def get_retry_delay(attempt: int, delays: tuple[int, ...]) -> int:
    """获取第attempt次重试的延迟秒数（从1开始），超出序列长度则取末尾值"""
    return delays[min(attempt - 1, len(delays) - 1)]
