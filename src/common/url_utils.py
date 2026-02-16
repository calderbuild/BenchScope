"""URL 规范化工具函数"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit

_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "ref_src",
}

# arXiv URL版本号匹配模式，统一去除v1/v2等后缀
_ARXIV_VERSION_PATTERN = re.compile(
    r"(arxiv\.org/(?:abs|pdf)/\d+\.\d+)v\d+", re.IGNORECASE
)


def canonicalize_url(url: str | None) -> str:
    """对URL做轻量规范化，便于去重比较。

    去除首尾空白、统一scheme/host大小写、移除fragment和跟踪参数、
    去掉末尾斜杠、arXiv版本号规范化。
    """
    if not url or not (stripped := url.strip()):
        return ""

    # 规范化arXiv版本号，确保v1/v2一致
    stripped = _ARXIV_VERSION_PATTERN.sub(r"\1", stripped)

    parts = urlsplit(stripped)

    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in _TRACKING_PARAMS
    ]
    cleaned_query = "&".join(f"{k}={v}" if v != "" else k for k, v in query_pairs)

    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/") or "/",
            cleaned_query,
            "",
        )
    )
