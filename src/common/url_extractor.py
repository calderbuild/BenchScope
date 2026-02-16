"""URL提取工具 - 从文本中提取数据集、论文等相关URL"""

from __future__ import annotations

import re


class URLExtractor:
    """从文本中提取特定类型的URL"""

    DATASET_SECTION_SCAN_LENGTH = 1000

    # 数据集URL模式（优先级从高到低）
    DATASET_URL_PATTERNS = [
        r"https?://huggingface\.co/datasets/[\w\-./]+",
        r"https?://github\.com/[\w\-]+/[\w\-]+(?:/(?:tree|blob)/[\w\-/]+)?(?:data|dataset)",
        r"https?://(?:www\.)?zenodo\.org/record(?:s)?/\d+",
        r"https?://(?:www\.)?zenodo\.org/doi/[\w\-.]+",
        r"https?://(?:www\.)?kaggle\.com/datasets/[\w\-/]+",
        r"https?://paperswithcode\.com/dataset/[\w\-]+",
        r"https?://drive\.google\.com/(?:file/d/|drive/folders/|open\?id=)[\w\-]+",
        r"https?://(?:www\.)?dropbox\.com/(?:s|sh)/[\w\-/]+",
        r"https?://[\w\-.]+\.edu/[\w\-/]*(?:data|dataset|corpus)[\w\-/]*",
        r"https?://[\w\-.]+/[\w\-/]*(?:data|dataset|corpus)[\w\-/]*\.(?:zip|tar\.gz|tgz|tar)",
    ]

    PAPER_URL_PATTERNS = [
        r"https?://arxiv\.org/(?:abs|pdf)/\d+\.\d+(?:v\d+)?",
        r"https?://aclanthology\.org/[\w\-.]+",
        r"https?://openreview\.net/(?:forum\?id=|pdf\?id=)[\w\-]+",
        r"https?://proceedings\.mlr\.press/v\d+/[\w\-]+\.html",
        r"https?://papers\.nips\.cc/paper/[\w\-/]+",
        r"https?://(?:dx\.)?doi\.org/[\w\-.]+/[\w\-.]+",
    ]

    DATASET_SECTION_MARKERS = [
        r"##?\s*dataset",
        r"##?\s*data",
        r"##?\s*download",
        r"##?\s*getting\s+the\s+data",
        r"##?\s*corpus",
    ]

    # 排除明显不是数据集的URL路径
    _EXCLUDED_URL_PATHS = {
        "/issues/",
        "/pull/",
        "/releases/",
        "/wiki/",
        "/discussions/",
        "/actions/",
    }

    @classmethod
    def extract_dataset_url(cls, text: str) -> str | None:
        """从文本中提取第一个数据集URL，优先从Dataset章节提取"""
        if not text:
            return None

        dataset_section_start = cls._find_dataset_section(text.lower())

        # 如果找到Dataset章节，优先从该章节提取
        if dataset_section_start is not None:
            section_text = text[
                dataset_section_start : dataset_section_start
                + cls.DATASET_SECTION_SCAN_LENGTH
            ]
            url = cls._extract_from_patterns(section_text)
            if url:
                return url

        return cls._extract_from_patterns(text)

    @classmethod
    def extract_paper_url(cls, text: str) -> str | None:
        """从文本中提取第一个论文URL"""
        if not text:
            return None

        for pattern in cls.PAPER_URL_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)

        return None

    @classmethod
    def extract_all_dataset_urls(cls, text: str) -> list[str]:
        """从文本中提取所有数据集URL（去重）"""
        if not text:
            return []

        urls: set[str] = set()
        for pattern in cls.DATASET_URL_PATTERNS:
            urls.update(re.findall(pattern, text, re.IGNORECASE))

        return list(urls)

    @classmethod
    def _find_dataset_section(cls, text_lower: str) -> int | None:
        """查找README中的Dataset章节起始位置"""
        for marker_pattern in cls.DATASET_SECTION_MARKERS:
            match = re.search(marker_pattern, text_lower)
            if match:
                return match.start()
        return None

    @classmethod
    def _extract_from_patterns(cls, text: str) -> str | None:
        """按优先级从文本中提取URL"""
        for pattern in cls.DATASET_URL_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0)
        return None

    @classmethod
    def is_valid_dataset_url(cls, url: str) -> bool:
        """验证URL是否为有效的数据集URL"""
        if not url:
            return False

        url_lower = url.lower()

        if any(path in url_lower for path in cls._EXCLUDED_URL_PATHS):
            return False

        return any(
            re.search(pattern, url, re.IGNORECASE)
            for pattern in cls.DATASET_URL_PATTERNS
        )
