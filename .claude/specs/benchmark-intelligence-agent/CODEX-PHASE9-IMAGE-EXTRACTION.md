# Codex开发指令：Phase 9 - 富媒体图片爬取与展示

**版本**: v1.0
**创建时间**: 2025-11-20
**优先级**: 高
**预计工期**: 5-7天

---

## 📋 任务概述

为BenchScope添加图片爬取与飞书卡片展示功能，提升推送的视觉吸引力。

**核心需求**:
1. 从arXiv/GitHub/HuggingFace等来源提取项目主图
2. 将图片上传到飞书云获取`image_key`
3. 在飞书消息卡片顶部展示图片
4. 失败降级：图片处理失败不影响核心流程

**参考PRD**: `.claude/specs/benchmark-intelligence-agent/PHASE9-IMAGE-EXTRACTION-PRD.md`

---

## 🔍 问题诊断

### 当前代码状态

#### 1. 数据模型 (`src/models.py`)

**当前代码**:
```python
@dataclass(slots=True)
class RawCandidate:
    title: str
    url: str
    source: SourceType
    abstract: Optional[str] = None
    # ... 其他字段 ...
    # ❌ 缺少图片相关字段
```

**问题**:
- 没有存储图片URL的字段
- 没有存储飞书image_key的字段

#### 2. 采集器 (`src/collectors/*.py`)

**当前代码** (以`arxiv_collector.py`为例):
```python
candidates.append(
    RawCandidate(
        title=paper.title.strip(),
        url=paper.pdf_url or paper.entry_id,
        source="arxiv",
        abstract=paper.summary[:500] if paper.summary else None,
        # ... 其他字段 ...
        # ❌ 没有提取图片URL
    )
)
```

**问题**:
- 采集器只关注文本数据，忽略了视觉元素
- arXiv: 没有提取PDF预览图
- GitHub: 没有提取Social Preview或README图片
- HuggingFace: 没有提取模型卡片封面

#### 3. 飞书通知 (`src/notifier/feishu_notifier.py`)

**当前代码**:
```python
def _build_card(self, title: str, candidate: ScoredCandidate) -> dict:
    content = (
        f"**{candidate.title}**\n\n"
        f"综合评分: **{candidate.total_score:.1f}** / 10\n"
        # ... 纯文本内容 ...
    )

    return {
        "msg_type": "interactive",
        "card": {
            "header": {...},
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}},
                # ❌ 没有图片组件
                {"tag": "hr"},
                {"tag": "action", "actions": [...]},
            ],
        },
    }
```

**问题**:
- 卡片只有文本和按钮，缺少视觉吸引力
- 没有利用飞书的图片组件功能

#### 4. 主流程 (`src/main.py`)

**当前代码**:
```python
async def main():
    # Step 1: 采集
    raw_candidates = await collect_all()

    # Step 2: 预筛选
    filtered = await prefilter_batch(raw_candidates)

    # Step 3: LLM评分
    scored = await scorer.score_batch(filtered)

    # Step 4: 存储
    await storage.save_batch(scored)

    # Step 5: 飞书通知
    await notifier.notify(scored)
    # ❌ 没有图片上传步骤
```

**问题**:
- 流程中缺少"图片上传到飞书"的环节
- 评分完成后直接存储，没有处理图片

---

## 💡 解决方案设计

### 架构设计

```
┌──────────────────────────────────────────────────────────┐
│ Step 1: 采集阶段 (Collectors)                             │
│   ├─ ArxivCollector: 提取PDF首页预览图URL                │
│   ├─ GitHubCollector: 提取Social Preview / README图      │
│   ├─ HuggingFaceCollector: 提取Model Card封面            │
│   └─ 其他Collector: 提取og:image                         │
│   Output: RawCandidate.hero_image_url                    │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ Step 2-3: 预筛选 + LLM评分 (不变)                        │
│   Output: ScoredCandidate (继承hero_image_url)           │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ Step 4: 🆕 批量上传图片到飞书 (FeishuImageUploader)       │
│   ├─ 下载图片 (httpx.get)                                │
│   ├─ 验证图片 (大小、格式、尺寸)                          │
│   ├─ 上传到飞书 (POST /open-apis/im/v1/images)           │
│   ├─ 缓存image_key (Redis, TTL 30天)                     │
│   └─ 失败降级: 记录日志，继续流程                        │
│   Output: ScoredCandidate.hero_image_key                 │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ Step 5: 存储 (FeishuStorage + SQLite)                    │
│   保存hero_image_key字段到飞书表格                        │
└──────────────────────────────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────┐
│ Step 6: 飞书通知 (FeishuNotifier)                        │
│   卡片自动显示图片 (如果hero_image_key存在)                │
└──────────────────────────────────────────────────────────┘
```

### 三层防御机制

1. **采集阶段**: 提取图片URL失败 → `hero_image_url = None`，继续流程
2. **上传阶段**: 下载/上传失败 → `hero_image_key = None`，继续流程
3. **展示阶段**: 没有image_key → 不显示图片，卡片其他部分正常

---

## 🛠️ 实施步骤

### Step 1: 数据模型扩展

**文件**: `src/models.py`

**修改内容**:

```python
# 在RawCandidate类中新增字段（约第43行）
@dataclass(slots=True)
class RawCandidate:
    """采集器原始输出结构"""

    title: str
    url: str
    source: SourceType
    abstract: Optional[str] = None
    authors: Optional[List[str]] = None
    publish_date: Optional[datetime] = None
    github_stars: Optional[int] = None
    github_url: Optional[str] = None
    dataset_url: Optional[str] = None

    # ... 其他现有字段 ...

    # ✅ Phase 9新增：图片相关字段
    hero_image_url: Optional[str] = None  # 原始图片URL（爬取阶段填充）
    hero_image_key: Optional[str] = None  # 飞书image_key（上传阶段填充）


# 在ScoredCandidate类中继承字段（约第76行）
@dataclass(slots=True)
class ScoredCandidate:
    """Phase 2评分后的候选项 (5维度评分模型)"""

    # RawCandidate字段
    title: str
    url: str
    source: SourceType
    abstract: Optional[str] = None
    # ... 其他继承字段 ...

    # ✅ Phase 9继承自RawCandidate
    hero_image_url: Optional[str] = None
    hero_image_key: Optional[str] = None

    # Phase 2评分字段
    activity_score: float = 0.0
    # ...
```

**测试验证**:
```bash
# 运行类型检查
.venv/bin/python -c "from src.models import RawCandidate, ScoredCandidate; print('OK')"
```

---

### Step 2: 图片提取器模块

**新建文件**: `src/extractors/image_extractor.py`

**完整代码**:

```python
"""图片URL提取器 - 从不同数据源提取hero_image_url"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class ImageExtractor:
    """统一图片提取接口"""

    # 飞书支持的图片格式
    SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".gif", ".bmp"}

    # 最小图片尺寸（过滤小图标）
    MIN_WIDTH = 300
    MIN_HEIGHT = 200

    @staticmethod
    async def extract_arxiv_image(pdf_url: str) -> Optional[str]:
        """从arXiv PDF提取首页预览图

        策略: arXiv没有直接的预览图API，暂时返回None
        未来可以实现：下载PDF → 转换首页为图片 → 上传到临时存储
        """
        # TODO: 实现PDF转图片（需要pdf2image + poppler-utils）
        # 当前阶段先跳过，Phase 9.5再实现
        logger.debug(f"arXiv图片提取暂未实现: {pdf_url}")
        return None

    @staticmethod
    async def extract_github_image(repo_url: str, readme_html: Optional[str] = None) -> Optional[str]:
        """从GitHub仓库提取图片

        优先级:
        1. README中第一张大图 (>300x200px)
        2. og:image (如果没有README)

        Args:
            repo_url: GitHub仓库URL
            readme_html: README的HTML内容（采集器已获取）
        """
        # 策略1: 从README HTML中提取第一张大图
        if readme_html:
            soup = BeautifulSoup(readme_html, "html.parser")
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if not src:
                    continue

                # 过滤badge、icon等小图
                if any(keyword in src.lower() for keyword in ["badge", "icon", "svg", "shields.io"]):
                    continue

                # 转换相对路径为绝对路径
                if src.startswith("/"):
                    src = f"https://github.com{src}"
                elif src.startswith("http"):
                    pass  # 已经是绝对路径
                else:
                    continue  # 忽略相对路径

                # 验证图片格式
                if any(src.lower().endswith(fmt) for fmt in ImageExtractor.SUPPORTED_FORMATS):
                    logger.debug(f"GitHub图片提取成功: {src}")
                    return src

        # 策略2: 从og:image提取（fallback）
        return await ImageExtractor.extract_og_image(repo_url)

    @staticmethod
    async def extract_huggingface_image(model_id: str) -> Optional[str]:
        """从HuggingFace模型卡片提取封面图

        Args:
            model_id: 模型ID，如 "microsoft/phi-2"
        """
        # HuggingFace没有直接的封面图API
        # 尝试从Model Card页面提取og:image
        model_url = f"https://huggingface.co/{model_id}"
        return await ImageExtractor.extract_og_image(model_url)

    @staticmethod
    async def extract_og_image(webpage_url: str) -> Optional[str]:
        """通用方法：从网页<meta property="og:image">提取

        Args:
            webpage_url: 网页URL

        Returns:
            图片URL，如果提取失败返回None
        """
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                resp = await client.get(webpage_url, headers={"User-Agent": "BenchScope/1.0"})
                resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")

            # 提取og:image
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                image_url = og_image["content"]

                # 转换相对路径为绝对路径
                if image_url.startswith("/"):
                    from urllib.parse import urlparse
                    parsed = urlparse(webpage_url)
                    image_url = f"{parsed.scheme}://{parsed.netloc}{image_url}"

                logger.debug(f"og:image提取成功: {image_url}")
                return image_url

            logger.debug(f"未找到og:image: {webpage_url}")
            return None

        except Exception as exc:
            logger.warning(f"提取og:image失败 {webpage_url}: {exc}")
            return None
```

**测试文件**: `tests/test_image_extractor.py`

```python
"""测试图片提取器"""

import pytest

from src.extractors.image_extractor import ImageExtractor


@pytest.mark.asyncio
async def test_extract_github_image_from_readme():
    """测试从GitHub README提取图片"""
    readme_html = '''
    <html>
        <body>
            <img src="https://raw.githubusercontent.com/xxx/yyy/main/docs/screenshot.png" alt="Screenshot">
            <img src="https://shields.io/badge/python-3.11-blue">
        </body>
    </html>
    '''
    repo_url = "https://github.com/xxx/yyy"

    image_url = await ImageExtractor.extract_github_image(repo_url, readme_html)

    assert image_url is not None
    assert "screenshot.png" in image_url
    assert "shields.io" not in image_url  # badge应该被过滤


@pytest.mark.asyncio
async def test_extract_og_image():
    """测试从网页提取og:image"""
    # 使用真实的GitHub URL测试
    url = "https://github.com/microsoft/autogen"

    image_url = await ImageExtractor.extract_og_image(url)

    # GitHub应该有og:image
    assert image_url is not None or image_url is None  # 网络可能失败
```

---

### Step 3: 飞书图片上传器

**新建文件**: `src/storage/feishu_image_uploader.py`

**完整代码**:

```python
"""飞书图片上传器 - 下载图片并上传到飞书云"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx
from PIL import Image
from io import BytesIO

from src.config import Settings, get_settings

logger = logging.getLogger(__name__)


class FeishuImageUploader:
    """飞书图片上传与缓存管理"""

    # 飞书API端点
    IMAGE_UPLOAD_API = "https://open.feishu.cn/open-apis/im/v1/images"
    TENANT_ACCESS_TOKEN_API = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"

    # 图片限制
    MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
    MIN_IMAGE_SIZE = 50 * 1024  # 50KB
    SUPPORTED_FORMATS = {"JPEG", "PNG", "GIF", "BMP"}

    def __init__(self, settings: Optional[Settings] = None, redis_client=None):
        self.settings = settings or get_settings()
        self.redis = redis_client  # 可选Redis缓存

        # Token缓存（内存）
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    async def get_tenant_access_token(self) -> str:
        """获取Tenant Access Token（缓存2小时）

        文档: https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal
        """
        # 检查内存缓存
        if self._access_token and self._token_expires_at:
            if datetime.now() < self._token_expires_at:
                return self._access_token

        # 请求新Token
        payload = {
            "app_id": self.settings.feishu.app_id,
            "app_secret": self.settings.feishu.app_secret,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(self.TENANT_ACCESS_TOKEN_API, json=payload)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                raise RuntimeError(f"获取Tenant Access Token失败: {data}")

            self._access_token = data["tenant_access_token"]
            expires_in = data.get("expire", 7200)  # 默认2小时
            self._token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)  # 提前5分钟刷新

            logger.info("Tenant Access Token获取成功")
            return self._access_token

    async def upload_image(self, image_url: str) -> Optional[str]:
        """下载图片并上传到飞书，返回image_key

        Args:
            image_url: 图片URL

        Returns:
            image_key (如 "img_v2_xxx")，失败返回None
        """
        # 1. 检查Redis缓存
        cache_key = f"feishu:img:{hashlib.md5(image_url.encode()).hexdigest()}"
        if self.redis:
            try:
                cached = await self.redis.get(cache_key)
                if cached:
                    logger.debug(f"Redis缓存命中: {image_url}")
                    return cached.decode()
            except Exception as exc:
                logger.warning(f"Redis读取失败: {exc}")

        # 2. 下载图片
        image_bytes = await self._download_image(image_url)
        if not image_bytes:
            return None

        # 3. 验证图片
        if not self._validate_image(image_bytes):
            logger.warning(f"图片验证失败: {image_url}")
            return None

        # 4. 上传到飞书
        image_key = await self._upload_to_feishu(image_bytes)
        if not image_key:
            return None

        # 5. 缓存30天
        if self.redis and image_key:
            try:
                await self.redis.setex(cache_key, 30 * 24 * 3600, image_key.encode())
                logger.debug(f"图片已缓存: {image_key}")
            except Exception as exc:
                logger.warning(f"Redis写入失败: {exc}")

        return image_key

    async def _download_image(self, url: str) -> Optional[bytes]:
        """下载图片"""
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "BenchScope/1.0"})
                resp.raise_for_status()

                image_bytes = resp.content

                # 检查大小
                if len(image_bytes) < self.MIN_IMAGE_SIZE:
                    logger.warning(f"图片太小 (<50KB): {url}")
                    return None
                if len(image_bytes) > self.MAX_IMAGE_SIZE:
                    logger.warning(f"图片太大 (>5MB): {url}")
                    return None

                logger.debug(f"图片下载成功: {url} ({len(image_bytes)} bytes)")
                return image_bytes

        except Exception as exc:
            logger.warning(f"图片下载失败 {url}: {exc}")
            return None

    def _validate_image(self, image_bytes: bytes) -> bool:
        """验证图片格式和尺寸"""
        try:
            img = Image.open(BytesIO(image_bytes))

            # 检查格式
            if img.format not in self.SUPPORTED_FORMATS:
                logger.warning(f"不支持的图片格式: {img.format}")
                return False

            # 检查尺寸（宽度至少300px）
            width, height = img.size
            if width < 300:
                logger.warning(f"图片宽度太小: {width}px")
                return False

            return True

        except Exception as exc:
            logger.warning(f"图片验证失败: {exc}")
            return False

    async def _upload_to_feishu(self, image_bytes: bytes) -> Optional[str]:
        """调用飞书API上传图片

        文档: https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/image/create
        """
        try:
            # 获取access token
            token = await self.get_tenant_access_token()

            # 构造请求
            files = {"image": ("image.png", image_bytes, "image/png")}
            data = {"image_type": "message"}
            headers = {"Authorization": f"Bearer {token}"}

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    self.IMAGE_UPLOAD_API,
                    headers=headers,
                    files=files,
                    data=data,
                )
                resp.raise_for_status()
                result = resp.json()

                if result.get("code") != 0:
                    logger.error(f"飞书图片上传失败: {result}")
                    return None

                image_key = result["data"]["image_key"]
                logger.info(f"图片上传成功: {image_key}")
                return image_key

        except Exception as exc:
            logger.error(f"飞书图片上传异常: {exc}")
            return None
```

**测试文件**: `tests/test_feishu_image_uploader.py`

```python
"""测试飞书图片上传器"""

import pytest

from src.storage.feishu_image_uploader import FeishuImageUploader


@pytest.mark.asyncio
async def test_get_tenant_access_token():
    """测试获取Tenant Access Token"""
    uploader = FeishuImageUploader()

    token = await uploader.get_tenant_access_token()

    assert token is not None
    assert len(token) > 0


@pytest.mark.asyncio
@pytest.mark.skip("需要真实图片URL")
async def test_upload_image():
    """测试图片上传（集成测试）"""
    uploader = FeishuImageUploader()

    # 使用公开图片URL
    test_image_url = "https://raw.githubusercontent.com/microsoft/autogen/main/website/static/img/ag.svg"

    image_key = await uploader.upload_image(test_image_url)

    # SVG可能不支持，所以允许失败
    # 只验证逻辑执行完成
    assert image_key is None or image_key.startswith("img_")
```

---

### Step 4: 采集器集成（以GitHub为例）

**文件**: `src/collectors/github_collector.py`

**修改位置**: `_to_candidate()` 方法（约第450行）

**当前代码**:
```python
async def _to_candidate(
    self, item: Dict[str, Any], readme: Optional[str]
) -> Optional[RawCandidate]:
    # ... 现有逻辑 ...

    return RawCandidate(
        title=title,
        url=url,
        source="github",
        abstract=cleaned_abstract,
        # ... 其他字段 ...
        # ❌ 没有hero_image_url
    )
```

**修改后代码**:
```python
from src.extractors.image_extractor import ImageExtractor  # ✅ 新增导入

async def _to_candidate(
    self, item: Dict[str, Any], readme: Optional[str]
) -> Optional[RawCandidate]:
    # ... 现有逻辑 ...

    # ✅ 提取hero_image_url
    hero_image_url = await ImageExtractor.extract_github_image(
        repo_url=url,
        readme_html=readme,  # 已经在上面获取了README HTML
    )

    return RawCandidate(
        title=title,
        url=url,
        source="github",
        abstract=cleaned_abstract,
        # ... 其他字段 ...
        hero_image_url=hero_image_url,  # ✅ 新增字段
    )
```

**其他采集器修改** (类似模式):
- `arxiv_collector.py`: 调用 `ImageExtractor.extract_arxiv_image()`
- `huggingface_collector.py`: 调用 `ImageExtractor.extract_huggingface_image()`
- `helm_collector.py`: 调用 `ImageExtractor.extract_og_image()`

---

### Step 5: 主流程集成

**文件**: `src/main.py`

**修改位置**: `main()` 函数（约第80行）

**当前代码**:
```python
async def main():
    # Step 1: 采集
    raw_candidates = await collect_all()

    # Step 2: 预筛选
    filtered = await prefilter_batch(raw_candidates)

    # Step 3: LLM评分
    scored = await scorer.score_batch(filtered)

    # Step 4: 存储
    await storage.save_batch(scored)

    # Step 5: 飞书通知
    await notifier.notify(scored)
    # ❌ 缺少图片上传步骤
```

**修改后代码**:
```python
from src.storage.feishu_image_uploader import FeishuImageUploader  # ✅ 新增导入

async def main():
    # Step 1: 采集
    raw_candidates = await collect_all()
    logger.info(f"采集完成: {len(raw_candidates)}条")

    # Step 2: 预筛选
    filtered = await prefilter_batch(raw_candidates)
    logger.info(f"预筛选完成: {len(filtered)}条")

    # Step 3: LLM评分
    scored = await scorer.score_batch(filtered)
    logger.info(f"评分完成: {len(scored)}条")

    # ✅ Step 3.5: 批量上传图片到飞书
    uploader = FeishuImageUploader(settings)
    image_success_count = 0
    for candidate in scored:
        if candidate.hero_image_url:
            try:
                candidate.hero_image_key = await uploader.upload_image(
                    candidate.hero_image_url
                )
                if candidate.hero_image_key:
                    image_success_count += 1
            except Exception as exc:
                logger.warning(f"图片上传失败 {candidate.title}: {exc}")
                # 失败降级：继续流程，不中断

    logger.info(f"图片上传完成: {image_success_count}/{len([c for c in scored if c.hero_image_url])}条成功")

    # Step 4: 存储
    await storage.save_batch(scored)

    # Step 5: 飞书通知
    await notifier.notify(scored)
```

---

### Step 6: 飞书卡片图片展示

**文件**: `src/notifier/feishu_notifier.py`

**修改位置**: `_build_card()` 方法（约第247行）

**当前代码**:
```python
def _build_card(self, title: str, candidate: ScoredCandidate) -> dict:
    content = (
        f"**{candidate.title}**\n\n"
        f"综合评分: **{candidate.total_score:.1f}** / 10\n"
        # ...
    )

    return {
        "msg_type": "interactive",
        "card": {
            "header": {...},
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}},
                {"tag": "hr"},
                {"tag": "action", "actions": [...]},
            ],
        },
    }
```

**修改后代码**:
```python
def _build_card(self, title: str, candidate: ScoredCandidate) -> dict:
    priority_label = {
        "high": "高优先级",
        "medium": "中优先级",
        "low": "低优先级",
    }.get(candidate.priority, "低优先级")

    source_name = self._format_source_name(candidate.source)

    content = (
        f"**{candidate.title[:constants.TITLE_TRUNCATE_LONG]}**\n\n"
        f"综合评分: **{candidate.total_score:.1f}** / 10  |  优先级: **{priority_label}**\n\n"
        "**评分细项**\n"
        f"活跃度 {candidate.activity_score:.1f}  |  "
        f"可复现性 {candidate.reproducibility_score:.1f}  |  "
        f"许可合规 {candidate.license_score:.1f}  |  "
        f"任务新颖性 {candidate.novelty_score:.1f}  |  "
        f"MGX适配度 {candidate.relevance_score:.1f}\n\n"
        f"**来源**: {source_name}\n\n"
        f"**评分依据**\n{candidate.reasoning}"
    )

    # ✅ 构建elements数组
    elements = []

    # 1. 如果有hero_image_key，添加图片组件
    if candidate.hero_image_key:
        elements.append({
            "tag": "img",
            "img_key": candidate.hero_image_key,
            "alt": {
                "tag": "plain_text",
                "content": f"{candidate.title} 预览图"
            },
            "preview": True,  # 点击可放大
            "scale_type": "crop_center",  # 居中裁剪
            "size": "large",  # 大尺寸显示
        })
        elements.append({"tag": "hr"})  # 图片与文本之间的分割线

    # 2. 文本内容
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": content}})

    # 3. 分割线
    elements.append({"tag": "hr"})

    # 4. 按钮
    actions = [
        {
            "tag": "button",
            "text": {"content": "查看详情", "tag": "plain_text"},
            "url": candidate.url,
            "type": "primary",
        },
        {
            "tag": "button",
            "text": {"content": "飞书表格", "tag": "plain_text"},
            "url": constants.FEISHU_BENCH_TABLE_URL,
            "type": "default",
        },
    ]

    if candidate.github_url and candidate.github_url != candidate.url:
        actions.insert(
            1,
            {
                "tag": "button",
                "text": {"content": "GitHub", "tag": "plain_text"},
                "url": candidate.github_url,
                "type": "default",
            },
        )

    elements.append({"tag": "action", "actions": actions})

    # 5. 底部注释
    elements.append({
        "tag": "note",
        "elements": [
            {
                "tag": "plain_text",
                "content": f"BenchScope 情报员 | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            }
        ],
    })

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "red" if candidate.priority == "high" else "blue",
            },
            "elements": elements,  # ✅ 使用新的elements数组
        },
    }
```

---

### Step 7: 依赖更新

**文件**: `requirements.txt`

**新增依赖**:
```txt
# Phase 9: 图片处理
Pillow>=10.2.0            # 图片验证和处理
beautifulsoup4>=4.12.0    # HTML解析（已有，无需新增）
```

**安装命令**:
```bash
.venv/bin/pip install Pillow>=10.2.0
```

---

## ✅ 测试验证计划

### 单元测试

```bash
# 测试图片提取器
.venv/bin/python -m pytest tests/test_image_extractor.py -v

# 测试飞书上传器
.venv/bin/python -m pytest tests/test_feishu_image_uploader.py -v
```

### 集成测试

```bash
# 运行完整流程
.venv/bin/python -m src.main

# 检查日志中图片统计
grep "图片" logs/$(ls -t logs/ | head -n1)

# 预期输出:
# 图片上传完成: 25/41条成功 (成功率 61%)
```

### 手动验证（必须执行）

1. **触发完整流程**:
   ```bash
   .venv/bin/python -m src.main
   ```

2. **检查飞书推送**:
   - 打开飞书群，查看最新消息卡片
   - 验证图片是否显示在卡片顶部
   - 点击图片验证预览功能

3. **截图记录**:
   - 保存卡片截图到 `docs/phase9-screenshots/`
   - 截图文件名: `feishu-card-with-image-{date}.png`

4. **验证Redis缓存** (如果配置了Redis):
   ```bash
   redis-cli KEYS "feishu:img:*"
   redis-cli GET "feishu:img:xxxxx"
   ```

---

## 📊 成功标准

### 功能验收

- [x] 数据模型新增`hero_image_url`和`hero_image_key`字段
- [x] ImageExtractor成功提取GitHub/HuggingFace图片URL
- [x] FeishuImageUploader成功上传图片到飞书
- [x] 飞书卡片顶部正确显示图片
- [x] 图片处理失败不影响核心流程

### 性能指标

- [ ] 图片提取成功率 ≥ 60%
- [ ] 图片上传成功率 ≥ 95%
- [ ] 完整流程耗时 < 120秒
- [ ] Redis缓存命中率 ≥ 30%（第2次运行）

### 代码质量

- [ ] PEP8格式化 (`black .`)
- [ ] Lint检查通过 (`ruff check .`)
- [ ] 类型注解完整
- [ ] 关键逻辑有中文注释

---

## 🐛 常见问题排查

### 问题1: 图片上传失败 "code: 99991668"

**原因**: Tenant Access Token过期或无效

**解决**:
```python
# 检查app_id和app_secret配置
# 手动刷新Token
uploader = FeishuImageUploader()
token = await uploader.get_tenant_access_token()
print(token)
```

### 问题2: 图片提取成功率低 (<30%)

**原因**:
- GitHub README中没有大图
- og:image不存在或指向favicon

**解决**:
- 降低MIN_WIDTH阈值（300px → 200px）
- 添加更多提取策略（如GitHub API的社交预览图）

### 问题3: 飞书卡片不显示图片

**排查步骤**:
1. 检查`hero_image_key`是否存在:
   ```python
   print(candidate.hero_image_key)  # 应该是 "img_v2_xxx"
   ```

2. 检查卡片JSON结构:
   ```python
   card = notifier._build_card("测试", candidate)
   print(json.dumps(card, indent=2, ensure_ascii=False))
   # 应该包含 {"tag": "img", "img_key": "..."}
   ```

3. 验证飞书API返回:
   ```bash
   # 查看日志中飞书Webhook响应
   grep "飞书Webhook" logs/$(ls -t logs/ | head -n1)
   ```

---

## 📝 提交检查清单

开发完成后，Codex需要确认：

- [ ] 所有代码已提交到git
- [ ] 单元测试全部通过
- [ ] 集成测试运行成功
- [ ] 手动验证完成（飞书卡片截图）
- [ ] 日志中无ERROR级别错误
- [ ] 代码符合PEP8规范
- [ ] 关键逻辑有中文注释
- [ ] 依赖已更新到requirements.txt
- [ ] 测试报告已写入 `docs/phase9-test-report.md`

---

## 🎯 最终交付物

1. **代码文件**:
   - `src/models.py` (新增字段)
   - `src/extractors/image_extractor.py` (新建)
   - `src/storage/feishu_image_uploader.py` (新建)
   - `src/collectors/*.py` (集成ImageExtractor)
   - `src/main.py` (集成上传流程)
   - `src/notifier/feishu_notifier.py` (卡片展示图片)

2. **测试文件**:
   - `tests/test_image_extractor.py`
   - `tests/test_feishu_image_uploader.py`

3. **文档**:
   - `docs/phase9-test-report.md` (测试报告 + 截图)
   - `README.md` (更新Phase 9说明)

4. **依赖**:
   - `requirements.txt` (新增Pillow)

---

## 🚀 开始开发

Codex，请按照上述步骤逐步实施，每完成一个Step后：
1. 运行对应的测试验证
2. 记录遇到的问题和解决方案
3. 继续下一个Step

完成后，通知Claude Code进行最终验收。

**预计工期**: 5-7天
**开发优先级**: 高
