"""文本清洗工具函数。"""

from __future__ import annotations

import re

_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]*\)")


def clean_summary_text(text: str | None, max_length: int | None = None) -> str:
    """去除HTML/Markdown噪声，保留可读摘要。"""

    if not text:
        return ""

    cleaned = _HTML_COMMENT_PATTERN.sub(" ", text)
    cleaned = _MARKDOWN_IMAGE_PATTERN.sub(" ", cleaned)
    cleaned = _MARKDOWN_LINK_PATTERN.sub(r"\1", cleaned)
    cleaned = _HTML_TAG_PATTERN.sub(" ", cleaned)
    cleaned = cleaned.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    cleaned = " ".join(cleaned.split())

    if max_length and len(cleaned) > max_length:
        cleaned = cleaned[: max_length - 3].rstrip() + "..."

    return cleaned
