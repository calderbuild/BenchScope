"""URL 规范化工具函数"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit, urlunsplit

# 需要去除的常见跟踪参数，避免同一链接被视为不同URL
_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "ref_src",
}

# P11新增：arXiv URL版本号匹配模式，统一去除v1/v2等后缀
_ARXIV_VERSION_PATTERN = re.compile(
    r"(arxiv\.org/(?:abs|pdf)/\d+\.\d+)v\d+", re.IGNORECASE
)


def _normalize_arxiv_url(url: str) -> str:
    """P11新增：去除arXiv URL中的版本号后缀，避免重复去重失效。"""
    return _ARXIV_VERSION_PATTERN.sub(r"\1", url)


def canonicalize_url(url: str | None) -> str:
    """对URL做轻量规范化，便于去重比较。

    - 去除首尾空白
    - 统一小写的scheme/host
    - 移除片段(#...)和常见跟踪参数
    - 去掉末尾的多余斜杠
    - P11：arXiv版本号规范化，保证同论文不同版本被视为同一URL
    """
    if not url:
        return ""

    stripped = url.strip()
    if not stripped:
        return ""

    # P11：先规范化arXiv版本号，确保v1/v2一致
    stripped = _normalize_arxiv_url(stripped)

    try:
        parts = urlsplit(stripped)
    except Exception:
        # 非法URL直接返回原始字符串，至少保证可作为键使用
        return stripped

    # 过滤常见跟踪参数，但保留其他query以避免丢失关键信息
    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in _TRACKING_PARAMS
    ]
    cleaned_query = "&".join(
        f"{k}={v}" if v != "" else k for k, v in query_pairs
    )

    # 统一大小写并移除末尾斜杠
    normalized_path = parts.path.rstrip("/") or "/"

    normalized = urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            normalized_path,
            cleaned_query,
            "",  # 丢弃fragment
        )
    )
    return normalized
