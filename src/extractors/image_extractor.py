"""图片URL提取器

从不同数据源抽取可用于飞书展示的主图URL。
"""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from src.common import constants
from src.config import get_settings

logger = logging.getLogger(__name__)


class ImageExtractor:
    """统一图片提取接口"""

    SUPPORTED_FORMATS = {fmt.lower() for fmt in constants.IMAGE_SUPPORTED_FORMATS}
    MIN_WIDTH = constants.IMAGE_MIN_WIDTH
    MIN_HEIGHT = constants.IMAGE_MIN_HEIGHT

    @staticmethod
    async def extract_arxiv_image(pdf_url: str) -> Optional[str]:
        """从arXiv PDF提取首页预览图（预留接口，当前降级为None）

        说明：
            - Phase 9.5 计划接入 pdf2image，将PDF首页转为图片
            - 当前阶段返回None，不阻塞主流程
        """
        logger.debug("arXiv图片提取暂未实现，直接返回None: %s", pdf_url)
        return None

    @staticmethod
    async def extract_github_image(
        repo_url: str, readme_html: Optional[str] = None
    ) -> Optional[str]:
        """从GitHub仓库提取图片URL

        策略优先级：
            1) README中首张大图（过滤徽章/图标）
            2) 回退到页面的 og:image
        """
        if readme_html:
            image_from_readme = ImageExtractor._extract_first_large_image(readme_html)
            if image_from_readme:
                return ImageExtractor._normalize_github_image_url(
                    repo_url, image_from_readme
                )

        return await ImageExtractor.extract_og_image(repo_url)

    @staticmethod
    async def extract_huggingface_image(model_id: str) -> Optional[str]:
        """从HuggingFace模型卡片提取封面图（携带认证token）"""
        model_url = f"https://huggingface.co/{model_id}"

        # 从配置获取HuggingFace token
        settings = get_settings()
        extra_headers = {}
        if settings.huggingface.token:
            extra_headers["Authorization"] = f"Bearer {settings.huggingface.token}"

        return await ImageExtractor.extract_og_image(
            model_url, extra_headers=extra_headers
        )

    @staticmethod
    async def extract_og_image(
        webpage_url: str, extra_headers: Optional[dict] = None
    ) -> Optional[str]:
        """通用方法：读取网页<meta property=\"og:image\">

        Args:
            webpage_url: 目标网页URL
            extra_headers: 额外的HTTP headers（如HuggingFace token）
        """
        try:
            headers = {"User-Agent": "BenchScope/1.0"}
            if extra_headers:
                headers.update(extra_headers)

            async with httpx.AsyncClient(
                timeout=constants.IMAGE_DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True
            ) as client:
                resp = await client.get(webpage_url, headers=headers)
                resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            tag = soup.find("meta", property="og:image")
            if not tag or not tag.get("content"):
                logger.debug("页面未找到og:image: %s", webpage_url)
                return None

            raw_url = tag["content"]
            normalized = ImageExtractor._make_absolute(webpage_url, raw_url)
            logger.debug("提取到og:image: %s -> %s", webpage_url, normalized)
            return normalized

        except Exception as exc:  # noqa: BLE001
            logger.warning("提取og:image失败 %s: %s", webpage_url, exc)
            return None

    @staticmethod
    def _extract_first_large_image(readme_html: str) -> Optional[str]:
        """从README HTML中获取首张非徽章类大图"""
        soup = BeautifulSoup(readme_html, "html.parser")
        for img in soup.find_all("img"):
            src = (img.get("src") or "").strip()
            if not src:
                continue

            lowered = src.lower()
            if any(
                keyword in lowered
                for keyword in ["badge", "icon", "shields.io", ".svg"]
            ):
                continue

            if ImageExtractor._looks_like_supported_image(src):
                return src

        return None

    @staticmethod
    def _normalize_github_image_url(repo_url: str, img_src: str) -> str:
        """将GitHub README中的图片地址规范化为可访问的绝对URL"""
        if img_src.startswith("http://") or img_src.startswith("https://"):
            return img_src
        if img_src.startswith("//"):
            return f"https:{img_src}"
        if img_src.startswith("/"):
            return f"https://github.com{img_src}"

        # 无法解析的相对路径直接返回原始内容，保持降级
        logger.debug(
            "未能解析的README相对路径，直接返回: %s (repo=%s)", img_src, repo_url
        )
        return img_src

    @staticmethod
    def _make_absolute(base_url: str, maybe_relative: str) -> str:
        """将相对路径转绝对路径"""
        if maybe_relative.startswith("http://") or maybe_relative.startswith(
            "https://"
        ):
            return maybe_relative
        if maybe_relative.startswith("//"):
            return f"https:{maybe_relative}"
        if maybe_relative.startswith("/"):
            parsed = urlparse(base_url)
            return f"{parsed.scheme}://{parsed.netloc}{maybe_relative}"
        return maybe_relative

    @staticmethod
    def _looks_like_supported_image(src: str) -> bool:
        """简单判断图片后缀是否受支持"""
        return any(
            src.lower().endswith(fmt) for fmt in ImageExtractor.SUPPORTED_FORMATS
        )


__all__ = ["ImageExtractor"]
