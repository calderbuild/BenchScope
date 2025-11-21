"""图片URL提取器

从不同数据源抽取可用于飞书展示的主图URL。
"""

from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from src.common import constants
from src.config import get_settings

logger = logging.getLogger(__name__)

try:  # pdf2image依赖Poppler，若未安装需要降级
    from pdf2image import convert_from_path

    POPPLER_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    convert_from_path = None  # type: ignore[assignment]
    POPPLER_AVAILABLE = False
    logger.warning("pdf2image未安装或不可用，arXiv图片提取将被禁用: %s", exc)

try:
    from redis.asyncio import Redis as AsyncRedis
except Exception:  # noqa: BLE001
    AsyncRedis = None


class ImageExtractor:
    """统一图片提取接口"""

    SUPPORTED_FORMATS = {fmt.lower() for fmt in constants.IMAGE_SUPPORTED_FORMATS}
    MIN_WIDTH = constants.IMAGE_MIN_WIDTH
    MIN_HEIGHT = constants.IMAGE_MIN_HEIGHT

    @staticmethod
    async def extract_arxiv_image(pdf_path: str, arxiv_id: str) -> Optional[str]:
        """从本地arXiv PDF生成首页预览图并上传飞书。

        优先命中Redis缓存；未命中时使用pdf2image渲染首页PNG并上传。
        """
        # Poppler缺失直接降级
        if not POPPLER_AVAILABLE or not convert_from_path:
            logger.debug("Poppler不可用，跳过arXiv图片提取: %s", arxiv_id)
            return None

        pdf_file = Path(pdf_path)
        if not pdf_file.exists():
            logger.debug("PDF不存在，跳过图片提取: %s", pdf_file)
            return None

        cache_key = f"{constants.ARXIV_IMAGE_CACHE_PREFIX}{arxiv_id}"
        redis_client = await ImageExtractor._get_redis_client()

        if redis_client:
            try:
                cached = await redis_client.get(cache_key)
                if cached:
                    logger.info("Redis命中arXiv图片缓存: %s", arxiv_id)
                    await redis_client.aclose()
                    return cached
            except Exception as exc:  # noqa: BLE001
                logger.debug("读取Redis缓存失败，继续执行: %s", exc)

        try:
            # PDF转PNG放到线程池，避免阻塞事件循环
            images = await asyncio.to_thread(
                convert_from_path,
                str(pdf_file),
                dpi=constants.ARXIV_IMAGE_CONVERT_DPI,
                first_page=1,
                last_page=1,
                fmt="png",
            )
            if not images:
                logger.warning("PDF转换未生成图片: %s", arxiv_id)
                await ImageExtractor._safe_close_redis(redis_client)
                return None

            png_buffer = io.BytesIO()
            images[0].save(png_buffer, format="PNG", optimize=True)
            png_bytes = png_buffer.getvalue()

            from src.storage.feishu_image_uploader import FeishuImageUploader

            uploader = FeishuImageUploader(get_settings())
            image_key = await uploader.upload_image(png_bytes)
            if not image_key:
                await ImageExtractor._safe_close_redis(redis_client)
                return None

            if redis_client:
                try:
                    await redis_client.setex(
                        cache_key,
                        constants.IMAGE_CACHE_TTL_SECONDS,
                        image_key,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("写入Redis缓存失败: %s", exc)

            await ImageExtractor._safe_close_redis(redis_client)
            return image_key

        except Exception as exc:  # noqa: BLE001
            logger.warning("arXiv图片提取失败 %s: %s", arxiv_id, exc)
            await ImageExtractor._safe_close_redis(redis_client)
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
    async def extract_huggingface_image(dataset_id: str) -> Optional[str]:
        """从HuggingFace数据集卡片提取封面图（携带认证token）

        Args:
            dataset_id: 数据集ID，格式为 'org/dataset-name'
        """
        # HuggingFace数据集URL格式：https://huggingface.co/datasets/{id}
        dataset_url = f"https://huggingface.co/datasets/{dataset_id}"

        # 从配置获取HuggingFace token
        settings = get_settings()
        extra_headers = {}
        if settings.sources.huggingface.token:
            extra_headers["Authorization"] = f"Bearer {settings.sources.huggingface.token}"

        return await ImageExtractor.extract_og_image(
            dataset_url, extra_headers=extra_headers
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

    @staticmethod
    async def _get_redis_client() -> Optional["AsyncRedis"]:
        """获取Redis异步客户端，失败时返回None"""

        if not AsyncRedis:
            return None
        try:
            settings = get_settings()
            client = AsyncRedis.from_url(
                settings.redis.url,
                decode_responses=True,
            )
            # ping一次确保可用
            await client.ping()
            return client
        except Exception as exc:  # noqa: BLE001
            logger.debug("初始化Redis失败，跳过缓存: %s", exc)
            return None

    @staticmethod
    async def _safe_close_redis(client: Optional["AsyncRedis"]) -> None:
        """安全关闭Redis连接"""
        if client:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass


__all__ = ["ImageExtractor"]
