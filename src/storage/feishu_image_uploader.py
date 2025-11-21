"""飞书图片上传器

负责：下载图片 -> 验证 -> 上传飞书 -> 缓存 image_key
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional, Union

import httpx
from PIL import Image

from src.common import constants
from src.config import Settings, get_settings

logger = logging.getLogger(__name__)


class FeishuImageUploader:
    """飞书图片上传与缓存管理"""

    IMAGE_UPLOAD_API = "https://open.feishu.cn/open-apis/im/v1/images"
    TENANT_ACCESS_TOKEN_API = (
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    )

    def __init__(
        self,
        settings: Optional[Settings] = None,
        redis_client: Optional[object] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.redis = redis_client  # 可选Redis缓存，须为redis.asyncio.Redis兼容实例
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    async def get_tenant_access_token(self) -> str:
        """获取Tenant Access Token（内存缓存 + 提前刷新）"""
        now = datetime.now()
        if (
            self._access_token
            and self._token_expires_at
            and now < self._token_expires_at
        ):
            return self._access_token

        payload = {
            "app_id": self.settings.feishu.app_id,
            "app_secret": self.settings.feishu.app_secret,
        }

        async with httpx.AsyncClient(
            timeout=constants.IMAGE_UPLOAD_TIMEOUT_SECONDS
        ) as client:
            resp = await client.post(self.TENANT_ACCESS_TOKEN_API, json=payload)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"获取Tenant Access Token失败: {data}")

        self._access_token = data["tenant_access_token"]
        expires_in = int(data.get("expire", 7200))
        # 提前5分钟刷新，避免边界过期
        self._token_expires_at = now + timedelta(seconds=max(expires_in - 300, 600))
        logger.info("Tenant Access Token获取成功")
        return self._access_token

    async def upload_image(self, image_source: Union[str, bytes]) -> Optional[str]:
        """上传图片到飞书，支持URL与字节流"""

        cache_key: Optional[str] = None
        image_bytes: Optional[bytes] = None

        if isinstance(image_source, str):
            cache_key = f"{constants.IMAGE_CACHE_PREFIX}{hashlib.md5(image_source.encode()).hexdigest()}"
            if self.redis and cache_key:
                try:
                    cached = await self.redis.get(cache_key)
                    if cached:
                        logger.debug("命中Redis图片缓存: %s", image_source)
                        return cached.decode()
                except Exception as exc:  # noqa: BLE001
                    logger.warning("读取图片缓存失败: %s", exc)

            image_bytes = await self._download_image(image_source)
        elif isinstance(image_source, bytes):
            image_bytes = image_source
        else:
            logger.error("不支持的图片来源类型: %s", type(image_source))
            return None

        if not image_bytes:
            return None

        if not self._validate_image(image_bytes):
            return None

        image_key = await self._upload_to_feishu(image_bytes)
        if not image_key:
            return None

        if self.redis and cache_key:
            try:
                await self.redis.setex(
                    cache_key, constants.IMAGE_CACHE_TTL_SECONDS, image_key.encode()
                )
                logger.debug("图片上传结果已缓存: %s", cache_key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("写入图片缓存失败: %s", exc)

        return image_key

    async def _download_image(self, url: str) -> Optional[bytes]:
        """下载图片并做体积校验"""
        try:
            headers = {"User-Agent": "BenchScope/1.0"}
            async with httpx.AsyncClient(
                timeout=constants.IMAGE_DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True
            ) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                content = resp.content

            if len(content) < constants.IMAGE_MIN_SIZE_BYTES:
                logger.warning("图片过小，可能无效: %s", url)
                return None
            if len(content) > constants.IMAGE_MAX_SIZE_BYTES:
                logger.warning("图片过大，跳过上传: %s", url)
                return None
            return content

        except Exception as exc:  # noqa: BLE001
            logger.warning("图片下载失败 %s: %s", url, exc)
            return None

    def _validate_image(self, image_bytes: bytes) -> bool:
        """校验图片格式与尺寸"""
        try:
            with Image.open(BytesIO(image_bytes)) as img:
                if img.format not in constants.IMAGE_SUPPORTED_FORMATS:
                    logger.warning("图片格式不支持: %s", img.format)
                    return False

                width, height = img.size
                if (
                    width < constants.IMAGE_MIN_WIDTH
                    or height < constants.IMAGE_MIN_HEIGHT
                ):
                    logger.warning("图片尺寸过小: %sx%s", width, height)
                    return False

            return True

        except Exception as exc:  # noqa: BLE001
            logger.warning("图片验证失败: %s", exc)
            return False

    async def _upload_to_feishu(self, image_bytes: bytes) -> Optional[str]:
        """调用飞书API上传图片"""
        try:
            token = await self.get_tenant_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            files = {"image": ("preview.png", image_bytes, "image/png")}
            data = {"image_type": "message"}

            async with httpx.AsyncClient(
                timeout=constants.IMAGE_UPLOAD_TIMEOUT_SECONDS
            ) as client:
                resp = await client.post(
                    self.IMAGE_UPLOAD_API, headers=headers, files=files, data=data
                )

                # 打印飞书API返回信息（调试用）
                result = resp.json()
                if resp.status_code != 200:
                    logger.error("飞书API返回错误 (HTTP %d): %s", resp.status_code, result)

                resp.raise_for_status()

            if result.get("code") != 0:
                logger.error("飞书图片上传失败: %s", result)
                return None

            image_key = result["data"]["image_key"]
            logger.info("图片上传成功: %s", image_key)
            return image_key

        except Exception as exc:  # noqa: BLE001
            logger.error("飞书图片上传异常: %s", exc)
            return None


__all__ = ["FeishuImageUploader"]
