# Codex开发指令：Phase 9.5 - arXiv论文首页预览图生成

**文档版本**: v1.0
**创建时间**: 2025-11-21
**负责人**: Codex
**PRD参考**: `.claude/specs/benchmark-intelligence-agent/PHASE9.5-PRD.md`

---

## 一、任务背景

### 1.1 当前问题诊断

**数据统计**（2025-11-21运行日志）：
```
采集结果:
  - GitHub: 34条
  - HuggingFace: 49条
  - arXiv: 4条 ✅ (关键信息源)

图片提取结果:
  - GitHub: 成功提取og:image
  - HuggingFace: 成功提取社交缩略图
  - arXiv: 0/4 成功 ❌ (当前直接返回None)
```

**根本原因**：
`src/extractors/image_extractor.py:29-37` 中的 `extract_arxiv_image` 是预留接口，当前实现：

```python
@staticmethod
async def extract_arxiv_image(pdf_url: str) -> Optional[str]:
    """从arXiv PDF提取首页预览图（预留接口，当前降级为None）"""
    logger.debug("arXiv图片提取暂未实现，直接返回None: %s", pdf_url)
    return None
```

**业务影响**：
- arXiv占候选池30-40%，是核心信息源
- 飞书通知卡片缺少视觉元素，识别效率降低
- 研究员需要手动打开arXiv链接查看论文首页

---

## 二、解决方案

### 2.1 技术架构

```
┌────────────────────────────────────────────────────────────┐
│ Phase 9.5 完整流程                                          │
└────────────────────────────────────────────────────────────┘

Step 1: PDF下载（复用现有逻辑）
  ArxivCollector.collect()
    ├─ PDFEnhancer已下载PDF到 /tmp/arxiv_pdf_cache/{arxiv_id}.pdf
    ├─ 检查缓存避免重复下载
    └─ 返回RawCandidate (包含pdf_path)

Step 2: 首页转图（新增功能）
  ImageExtractor.extract_arxiv_image(pdf_path, arxiv_id)
    ├─ 检查Redis缓存 (key: arxiv_pdf_image:{arxiv_id})
    ├─ 未命中缓存:
    │   ├─ pdf2image.convert_from_path(pdf_path, first_page=1, last_page=1, dpi=150)
    │   ├─ 转换为PNG字节流 (内存操作，不落盘)
    │   ├─ FeishuImageUploader.upload_image(png_bytes) → image_key
    │   └─ Redis缓存image_key (TTL=30天)
    └─ 返回 image_key

Step 3: 存储飞书表格
  StorageManager.save(candidates)
    ├─ FeishuStorage写入 hero_image_key 字段
    └─ 飞书表格显示图片Key

Step 4: 飞书通知显示
  FeishuNotifier.notify(candidates)
    ├─ 构建交互式卡片
    ├─ 使用 hero_image_key 显示首页预览图
    └─ 用户点击查看完整PDF
```

### 2.2 技术选型理由

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| **pdf2image** | 简单、稳定、跨平台 | 需要Poppler依赖 | ✅ 推荐 |
| PyMuPDF(fitz) | 纯Python、无外部依赖 | 渲染质量不如Poppler | ❌ 备选 |
| Pillow+reportlab | 纯Python | 需解析PDF，复杂度高 | ❌ 过度工程 |

---

## 三、详细实现步骤

### Step 1: 安装依赖

#### 1.1 Python依赖

**修改文件**: `requirements.txt`

```diff
# 图片处理相关依赖
beautifulsoup4>=4.12.0
httpx>=0.25.0
+ pdf2image==1.16.3
+ pillow>=10.0.0  # pdf2image依赖
```

**验证命令**:
```bash
.venv/bin/pip install pdf2image pillow
```

#### 1.2 系统依赖（Poppler）

**Linux (Ubuntu/Debian)**:
```bash
sudo apt-get update
sudo apt-get install -y poppler-utils
```

**macOS**:
```bash
brew install poppler
```

**Windows**:
```bash
# 下载地址: https://github.com/oschwartz10612/poppler-windows/releases/
# 解压后添加bin目录到PATH
```

**验证安装**:
```bash
pdftoppm -v  # 应显示版本号
```

---

### Step 2: 实现 `extract_arxiv_image` 方法

#### 2.1 当前代码（需修改）

**文件**: `src/extractors/image_extractor.py`
**行号**: 29-37

```python
@staticmethod
async def extract_arxiv_image(pdf_url: str) -> Optional[str]:
    """从arXiv PDF提取首页预览图（预留接口，当前降级为None）

    说明：
        - Phase 9.5 计划接入 pdf2image，将PDF首页转为图片
        - 当前阶段返回None，不阻塞主流程
    """
    logger.debug("arXiv图片提取暂未实现，直接返回None: %s", pdf_url)
    return None
```

#### 2.2 修改后代码（完整实现）

**修改文件**: `src/extractors/image_extractor.py`

**Step 2.2.1: 添加导入**

```python
# 在文件顶部添加（约第11行，import httpx之后）
import hashlib
import io
from typing import Optional

try:
    from pdf2image import convert_from_path
    POPPLER_AVAILABLE = True
except ImportError:
    POPPLER_AVAILABLE = False
    logger.warning("pdf2image未安装，arXiv图片提取将被禁用")
```

**Step 2.2.2: 修改方法签名和实现**

将原方法（29-37行）替换为：

```python
@staticmethod
async def extract_arxiv_image(pdf_path: str, arxiv_id: str) -> Optional[str]:
    """从arXiv PDF生成首页预览图并上传到飞书

    Args:
        pdf_path: 本地PDF文件路径 (已由PDFEnhancer下载)
        arxiv_id: arXiv ID (如 "2511.15168")

    Returns:
        飞书image_key，失败返回None

    流程:
        1. 检查Redis缓存 (key: arxiv_pdf_image:{arxiv_id})
        2. pdf2image转换首页为PNG (DPI=150)
        3. FeishuImageUploader上传
        4. Redis缓存image_key (TTL=30天)
    """
    # 检查Poppler可用性
    if not POPPLER_AVAILABLE:
        logger.debug("Poppler不可用，跳过arXiv图片提取: %s", arxiv_id)
        return None

    # 检查PDF文件存在
    from pathlib import Path
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        logger.warning("PDF文件不存在，跳过图片提取: %s", pdf_path)
        return None

    # 步骤1: 检查Redis缓存
    cache_key = f"arxiv_pdf_image:{arxiv_id}"

    # 尝试从Redis缓存获取（如果配置了Redis）
    try:
        from src.storage.redis_cache import RedisCache
        redis_cache = RedisCache()
        cached_image_key = await redis_cache.get(cache_key)
        if cached_image_key:
            logger.info("Redis缓存命中arXiv图片: %s -> %s", arxiv_id, cached_image_key)
            return cached_image_key
    except Exception as e:
        logger.debug("Redis缓存不可用或获取失败: %s", e)
        # 继续执行，不阻塞主流程

    try:
        # 步骤2: PDF首页转PNG
        logger.info("开始转换arXiv PDF首页: %s", arxiv_id)

        # 使用pdf2image转换首页 (DPI=150，平衡清晰度和文件大小)
        images = convert_from_path(
            str(pdf_file),
            dpi=150,
            first_page=1,
            last_page=1,
            fmt="png"
        )

        if not images:
            logger.warning("PDF转换失败，未生成图片: %s", arxiv_id)
            return None

        # 获取首页图片
        first_page_image = images[0]

        # 转换为PNG字节流（内存操作，不落盘）
        png_bytes = io.BytesIO()
        first_page_image.save(png_bytes, format="PNG", optimize=True)
        png_bytes.seek(0)

        # 步骤3: 上传到飞书
        logger.info("上传arXiv图片到飞书: %s", arxiv_id)
        from src.storage.feishu_image_uploader import FeishuImageUploader
        from src.config import get_settings

        uploader = FeishuImageUploader(get_settings())

        # upload_image支持字节流或URL
        image_key = await uploader.upload_image(png_bytes.getvalue())

        if not image_key:
            logger.warning("飞书图片上传失败: %s", arxiv_id)
            return None

        logger.info("arXiv图片上传成功: %s -> %s", arxiv_id, image_key)

        # 步骤4: 写入Redis缓存（30天TTL）
        try:
            await redis_cache.set(cache_key, image_key, ttl=30 * 24 * 3600)
            logger.debug("Redis缓存已更新: %s", cache_key)
        except Exception as e:
            logger.debug("Redis缓存写入失败（不影响主流程）: %s", e)

        return image_key

    except Exception as e:
        # 错误降级：返回None，不阻塞主流程
        logger.warning("arXiv图片提取失败 %s: %s", arxiv_id, e)
        return None
```

---

### Step 3: 修改 ArxivCollector 调用逻辑

#### 3.1 当前调用方式（需修改）

**文件**: `src/collectors/arxiv_collector.py`
**位置**: `collect()` 方法中，约196-199行

```python
# 当前代码 - 传入PDF URL
hero_image_url = await ImageExtractor.extract_arxiv_image(
    result.entry_id
)
```

#### 3.2 修改后调用方式

**修改文件**: `src/collectors/arxiv_collector.py`

找到 `collect()` 方法中的图片提取逻辑，替换为：

```python
# 步骤: 提取图片 (在PDFEnhancer增强后调用)
hero_image_key = None
if result.entry_id and hasattr(self, 'pdf_enhancer'):
    # 构造PDF路径（与PDFEnhancer._get_pdf_path逻辑一致）
    arxiv_id = result.entry_id.split('/')[-1]  # 提取纯ID（如"2511.15168"）
    pdf_path = f"/tmp/arxiv_pdf_cache/{arxiv_id}.pdf"

    from pathlib import Path
    if Path(pdf_path).exists():
        logger.debug("PDF已下载，提取首页预览图: %s", arxiv_id)
        hero_image_key = await ImageExtractor.extract_arxiv_image(
            pdf_path, arxiv_id
        )
        if hero_image_key:
            logger.info("arXiv图片提取成功: %s -> %s", arxiv_id, hero_image_key)
    else:
        logger.debug("PDF未下载或路径不存在，跳过图片提取: %s", pdf_path)

# 创建RawCandidate时设置hero_image_key
candidate = RawCandidate(
    # ... 其他字段 ...
    hero_image_key=hero_image_key,  # 新增字段
    # 注意：不再设置hero_image_url（PDF预览图无外部URL）
)
```

**重要说明**：
- 不再设置 `hero_image_url`（PDF预览图无外部URL）
- 直接设置 `hero_image_key` 用于飞书卡片显示
- PDF路径使用与 `PDFEnhancer._get_pdf_path` 相同的逻辑

---

### Step 4: 修改 FeishuImageUploader 支持字节流上传

#### 4.1 当前实现（只支持URL）

**文件**: `src/storage/feishu_image_uploader.py`
**方法**: `upload_image`

当前只支持传入URL字符串。

#### 4.2 修改后实现（支持URL和字节流）

**修改文件**: `src/storage/feishu_image_uploader.py`

找到 `upload_image` 方法，修改为：

```python
async def upload_image(self, image_source: Union[str, bytes]) -> Optional[str]:
    """上传图片到飞书并返回image_key

    Args:
        image_source: 图片来源，可以是：
            - str: 图片URL
            - bytes: 图片二进制数据（PNG/JPEG）

    Returns:
        飞书image_key (img_v3_xxx格式)，失败返回None
    """
    try:
        # 判断输入类型
        if isinstance(image_source, str):
            # URL模式：下载图片
            logger.debug("下载图片: %s", image_source[:80])
            image_data = await self._download_image(image_source)
            if not image_data:
                return None
        elif isinstance(image_source, bytes):
            # 字节流模式：直接使用
            logger.debug("使用字节流图片 (%d bytes)", len(image_source))
            image_data = image_source
        else:
            logger.error("不支持的image_source类型: %s", type(image_source))
            return None

        # 上传到飞书
        logger.debug("上传图片到飞书 (%d bytes)", len(image_data))
        image_key = await self._upload_to_feishu(image_data)

        if image_key:
            logger.info("飞书图片上传成功: %s", image_key)
        else:
            logger.warning("飞书图片上传失败")

        return image_key

    except Exception as e:
        logger.error("图片上传异常: %s", e)
        return None
```

**添加类型导入**（文件顶部）：
```python
from typing import Union, Optional
```

---

### Step 5: 更新 GitHub Actions 工作流

#### 5.1 修改文件

**文件**: `.github/workflows/daily_collect.yml`

在 `Install dependencies` 步骤后添加Poppler安装：

```yaml
    - name: Install system dependencies
      run: |
        sudo apt-get update
        sudo apt-get install -y poppler-utils

    - name: Verify Poppler installation
      run: |
        pdftoppm -v
```

完整的Steps部分应该是：

```yaml
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install system dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y poppler-utils

      - name: Verify Poppler installation
        run: |
          pdftoppm -v

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      # ... 其余步骤保持不变 ...
```

---

### Step 6: 更新项目文档

#### 6.1 修改 README.md

**文件**: `README.md`

在 `### 系统依赖` 部分添加：

```markdown
### 系统依赖

**Poppler** (PDF渲染引擎，Phase 9.5新增):
```bash
# Ubuntu/Debian
sudo apt-get install -y poppler-utils

# macOS
brew install poppler

# Windows
# 1. 下载: https://github.com/oschwartz10612/poppler-windows/releases/
# 2. 解压并添加bin目录到PATH
# 3. 验证: pdftoppm -v
```

**GROBID** (PDF科学论文解析，Phase 9已集成自动启动):
```bash
# 本地开发时自动启动，GitHub Actions无需配置
```
```

---

## 四、测试验证计划

### 4.1 单元测试

**创建测试脚本**: `scripts/test_arxiv_image_generation.py`

```python
"""测试arXiv PDF首页预览图生成"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.extractors.image_extractor import ImageExtractor


async def main():
    print("🧪 测试arXiv PDF首页预览图生成\n")
    print("=" * 60)

    # 测试用例：真实arXiv PDF（需要先运行一次采集以下载PDF）
    test_cases = [
        ("2511.15168", "/tmp/arxiv_pdf_cache/2511.15168.pdf"),
        ("2511.15752", "/tmp/arxiv_pdf_cache/2511.15752.pdf"),
    ]

    for arxiv_id, pdf_path in test_cases:
        if not Path(pdf_path).exists():
            print(f"⚠️  PDF不存在，跳过: {pdf_path}")
            print(f"    提示：先运行一次采集以下载PDF")
            continue

        print(f"\n测试: {arxiv_id}")
        print(f"  PDF路径: {pdf_path}")

        try:
            image_key = await ImageExtractor.extract_arxiv_image(
                pdf_path, arxiv_id
            )

            if image_key:
                print(f"  ✅ 生成成功: {image_key}")
            else:
                print(f"  ❌ 生成失败（返回None）")

        except Exception as e:
            print(f"  ❌ 异常: {e}")

    print("\n" + "=" * 60)
    print("✅ 测试完成")


if __name__ == "__main__":
    asyncio.run(main())
```

**运行测试**:
```bash
.venv/bin/python scripts/test_arxiv_image_generation.py
```

**预期输出**:
```
🧪 测试arXiv PDF首页预览图生成

============================================================

测试: 2511.15168
  PDF路径: /tmp/arxiv_pdf_cache/2511.15168.pdf
  ✅ 生成成功: img_v3_02dj_a1b2c3d4...

测试: 2511.15752
  PDF路径: /tmp/arxiv_pdf_cache/2511.15752.pdf
  ✅ 生成成功: img_v3_02dj_e5f6g7h8...

============================================================
✅ 测试完成
```

---

### 4.2 集成测试

**创建测试脚本**: `scripts/test_complete_arxiv_pipeline.py`

```python
"""测试完整arXiv流程：采集 → PDF下载 → 图片生成 → 飞书存储 → 通知"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.collectors.arxiv_collector import ArxivCollector
from src.storage.storage_manager import StorageManager
from src.notifier.feishu_notifier import FeishuNotifier


async def main():
    print("🧪 测试完整arXiv流程\n")
    print("=" * 60)

    # Step 1: 采集arXiv论文（限制1条测试）
    print("\n[1/4] 采集arXiv论文...")
    collector = ArxivCollector()
    # 临时修改配置：只采集1条
    original_max = collector.cfg.max_results
    collector.cfg.max_results = 1

    candidates = await collector.collect()

    # 恢复配置
    collector.cfg.max_results = original_max

    if not candidates:
        print("  ❌ 未采集到候选项")
        return

    candidate = candidates[0]
    print(f"  ✅ 采集成功: {candidate.title[:50]}...")

    # Step 2: 验证图片生成
    print("\n[2/4] 验证图片生成...")
    if candidate.hero_image_key:
        print(f"  ✅ 图片Key: {candidate.hero_image_key}")
    else:
        print(f"  ❌ 图片Key为空")
        print(f"     可能原因：PDF下载失败或转换失败")

    # Step 3: 存储飞书表格
    print("\n[3/4] 存储飞书表格...")
    storage = StorageManager()
    await storage.save(candidates)
    print(f"  ✅ 存储完成")

    # Step 4: 发送飞书通知
    print("\n[4/4] 发送飞书通知...")
    notifier = FeishuNotifier()
    await notifier.notify(candidates)
    print(f"  ✅ 通知发送完成")

    print("\n" + "=" * 60)
    print("✅ 完整流程测试通过")
    print("\n请检查：")
    print("  1. 飞书表格中'图片Key'字段有值")
    print("  2. 飞书通知卡片显示首页预览图")


if __name__ == "__main__":
    asyncio.run(main())
```

**运行测试**:
```bash
.venv/bin/python scripts/test_complete_arxiv_pipeline.py
```

---

### 4.3 手动验证清单

**Claude Code负责执行以下手动测试**：

#### 测试1: 本地环境验证
```bash
# 1. 验证Poppler安装
pdftoppm -v

# 2. 验证Python依赖
.venv/bin/python -c "from pdf2image import convert_from_path; print('✓ pdf2image OK')"

# 3. 运行单元测试
.venv/bin/python scripts/test_arxiv_image_generation.py

# 4. 运行集成测试
.venv/bin/python scripts/test_complete_arxiv_pipeline.py
```

#### 测试2: 飞书表格验证
- [ ] 打开飞书多维表格
- [ ] 找到最新的arXiv记录
- [ ] 检查 `图片Key` 字段有值（img_v3_xxx格式）
- [ ] 检查 `图片URL` 字段为空（PDF预览图无外部URL）

#### 测试3: 飞书通知验证
- [ ] 打开飞书群
- [ ] 查看最新推送的通知卡片
- [ ] 确认arXiv候选项显示首页预览图
- [ ] 点击图片确认可以查看大图

#### 测试4: GitHub Actions验证
- [ ] 提交代码到GitHub
- [ ] 等待GitHub Actions运行完成
- [ ] 检查Actions日志无错误
- [ ] 验证Poppler安装步骤成功
- [ ] 验证arXiv图片提取成功

---

## 五、性能与质量标准

### 5.1 性能指标

| 指标 | 目标值 | 验收方法 |
|------|--------|---------|
| PDF转换时间 | <3秒/页 | 测试脚本统计 |
| 图片文件大小 | 100KB-500KB | 检查生成的PNG |
| 内存占用 | <50MB | 只渲染首页 |
| 并发支持 | 4个PDF同时转换 | ArxivCollector并发数 |
| 成功率 | ≥95% | 排除损坏PDF |

### 5.2 质量指标

| 指标 | 标准 | 验收方法 |
|------|------|---------|
| 图片清晰度 | 首页文字清晰可读 | 人工检查10张图片 |
| 飞书卡片显示 | 图片正常加载，尺寸适配 | 飞书群手动验证 |
| Redis缓存命中 | ≥80% (重复论文) | 采集相同论文2次，检查日志 |
| 错误降级 | PDF损坏时返回None | 故意损坏PDF测试 |
| 零破坏 | 不影响现有功能 | 运行完整测试套件 |

---

## 六、成功标准检查清单

**完成以下所有项目即可提交验收**：

### 代码实现
- [ ] `requirements.txt` 添加 `pdf2image` 和 `pillow`
- [ ] `src/extractors/image_extractor.py` 实现 `extract_arxiv_image` 方法
- [ ] `src/collectors/arxiv_collector.py` 修改调用逻辑
- [ ] `src/storage/feishu_image_uploader.py` 支持字节流上传
- [ ] `.github/workflows/daily_collect.yml` 添加Poppler安装
- [ ] `README.md` 更新系统依赖说明

### 测试验证
- [ ] 单元测试通过 (`test_arxiv_image_generation.py`)
- [ ] 集成测试通过 (`test_complete_arxiv_pipeline.py`)
- [ ] 飞书表格正确显示 `图片Key`
- [ ] 飞书通知卡片正确显示首页预览图
- [ ] GitHub Actions运行无错误

### 代码质量
- [ ] 通过 `black .` 格式化
- [ ] 通过 `ruff check .` 检查
- [ ] 关键逻辑添加中文注释
- [ ] 函数添加类型注解和docstring
- [ ] 错误处理：所有外部调用有try-catch

### 文档更新
- [ ] README.md 更新系统依赖部分
- [ ] 创建实现报告 `docs/phase9.5-implementation-report.md`
- [ ] 测试结果截图保存到文档

---

## 七、风险与降级策略

### 7.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Poppler依赖缺失 | 中 | 功能完全不可用 | 启动时检测，日志警告，优雅降级返回None |
| PDF损坏/加密 | 低 | 个别论文转换失败 | try-catch捕获，返回None，不阻塞主流程 |
| 内存OOM | 极低 | 大PDF导致内存溢出 | 只渲染首页，限制DPI=150 |
| 飞书上传失败 | 低 | image_key获取失败 | 复用现有错误处理，最多重试2次 |

### 7.2 降级策略代码示例

**Poppler不可用时的降级**：
```python
try:
    from pdf2image import convert_from_path
    POPPLER_AVAILABLE = True
except ImportError:
    logger.warning("pdf2image未安装，arXiv图片提取将被禁用")
    POPPLER_AVAILABLE = False

# 在extract_arxiv_image中检查
if not POPPLER_AVAILABLE:
    logger.debug("Poppler不可用，跳过arXiv图片提取")
    return None
```

**PDF损坏时的降级**：
```python
try:
    images = convert_from_path(pdf_path, ...)
except Exception as e:
    logger.warning("PDF转换失败 %s: %s", arxiv_id, e)
    return None  # 优雅降级，不阻塞主流程
```

---

## 八、提交验收指南

### 8.1 提交内容

1. **代码文件** (6个文件修改 + 2个测试脚本)
   - `requirements.txt`
   - `src/extractors/image_extractor.py`
   - `src/collectors/arxiv_collector.py`
   - `src/storage/feishu_image_uploader.py`
   - `.github/workflows/daily_collect.yml`
   - `README.md`
   - `scripts/test_arxiv_image_generation.py` (新增)
   - `scripts/test_complete_arxiv_pipeline.py` (新增)

2. **实现报告** (`docs/phase9.5-implementation-report.md`)
   包含：
   - 实现细节说明
   - 测试结果（附截图）
   - 遇到的问题和解决方案
   - 性能数据统计

3. **测试截图**
   - 飞书表格截图（显示图片Key字段）
   - 飞书通知卡片截图（显示首页预览图）
   - GitHub Actions运行日志截图

### 8.2 验收流程

**Codex提交 → Claude Code验收**：

1. **代码审查**：Claude Code检查代码质量
2. **运行测试**：Claude Code执行所有测试脚本
3. **手动验证**：Claude Code验证飞书表格和通知
4. **决策**：
   - ✅ 通过：符合所有成功标准，交付用户
   - ❌ 打回：不符合要求，Codex修复后重新验收

---

## 九、Linus哲学约束检查

### 9.1 三问检查

**Q1: Is this a real problem?**
✅ 是。arXiv占候选池30-40%，无图片影响识别效率，有真实业务价值。

**Q2: Is there a simpler way?**
✅ 已选最简方案。pdf2image + Poppler是业界标准，无需重复造轮。

**Q3: What will this break?**
✅ 零破坏。仅新增功能，现有逻辑不变，降级优雅（返回None）。

### 9.2 代码质量约束

- [x] PEP8合规：使用 `black .` 格式化
- [x] 中文注释：关键逻辑必须中文注释
- [x] 类型注解：函数签名包含类型提示
- [x] 错误处理：所有外部依赖调用有try-catch
- [x] 日志记录：INFO记录成功，WARNING记录降级，ERROR记录失败
- [x] 嵌套层级：≤3层（Linus规则）
- [x] 魔法数字：定义在 `constants.py` 或函数参数

---

## 十、开发时间估算

| 阶段 | 任务 | 预计工时 |
|------|------|---------|
| Day 1 | 环境准备 + 核心实现 | 4h |
| | - 安装依赖（Poppler + pdf2image） | 0.5h |
| | - 实现 `extract_arxiv_image` 方法 | 2h |
| | - 修改 ArxivCollector 调用逻辑 | 1h |
| | - 修改 FeishuImageUploader 支持字节流 | 0.5h |
| Day 2 | 集成测试 + 文档更新 | 3h |
| | - 创建测试脚本并运行 | 1.5h |
| | - 更新 GitHub Actions 工作流 | 0.5h |
| | - 更新 README 文档 | 0.5h |
| | - 编写实现报告（附截图） | 0.5h |
| Day 3 | 部署验证 + 修复问题 | 2h |
| | - GitHub Actions 运行验证 | 1h |
| | - 修复发现的问题 | 1h |

**总计**: 9工时 (约1-2天)

---

## 十一、参考文档

### PRD文档
- `.claude/specs/benchmark-intelligence-agent/PHASE9.5-PRD.md` - 完整产品需求文档

### 相关代码
- `src/extractors/image_extractor.py` - 图片提取器（需修改）
- `src/collectors/arxiv_collector.py` - arXiv采集器（需修改）
- `src/storage/feishu_image_uploader.py` - 飞书图片上传器（需修改）
- `src/enhancers/pdf_enhancer.py` - PDF下载缓存逻辑（参考）

### 相关文档
- `docs/phase9-image-feature-report.md` - Phase 9实现报告（参考）
- `.claude/CLAUDE.md` - 项目开发规范
- `README.md` - 项目说明文档

---

**文档结束** - 请Codex按此指令完整实现Phase 9.5功能。
