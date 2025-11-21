# Phase 9.5 PRD: arXiv论文首页预览图生成

**文档版本**: v1.0
**创建时间**: 2025-11-21
**负责人**: Claude Code
**开发人**: Codex

---

## 一、需求背景

### 1.1 当前问题

Phase 9已实现图片提取和飞书卡片展示功能，但存在以下限制：

- **GitHub**: ✅ 已支持（README图片 + og:image）
- **HuggingFace**: ✅ 已支持（数据集社交缩略图）
- **arXiv**: ❌ 未支持（当前直接返回None）

**实际影响**：
- 2025-11-21运行日志显示：4条arXiv候选，图片上传0成功
- arXiv是核心信息源（占候选池30-40%），无图片影响信息密度
- 飞书通知卡片缺少视觉元素，识别效率降低

### 1.2 业务价值

**为什么要做**：
1. **视觉识别效率** - 论文首页通常包含标题、作者、机构、摘要，一图胜千言
2. **快速筛选** - 研究员可通过首页排版、公式密度、图表质量初判论文质量
3. **信息完整性** - 统一所有数据源的卡片展示体验（GitHub/HuggingFace/arXiv）

**不做的后果**：
- arXiv候选持续无图，与GitHub/HuggingFace候选视觉差异明显
- 用户需要手动打开arXiv链接查看论文首页，增加筛选成本

---

## 二、解决方案

### 2.1 核心方案：PDF首页转PNG

**技术路线**：
1. **下载PDF** - 复用现有`PDFEnhancer`的下载逻辑（已有缓存机制）
2. **首页转图** - 使用`pdf2image`库将PDF第1页转为PNG
3. **上传飞书** - 复用`FeishuImageUploader`上传并获取image_key
4. **缓存管理** - Redis缓存image_key（30天TTL，MD5键）

**为什么选择pdf2image**：
- 依赖Poppler（跨平台，Linux/macOS/Windows均可用）
- 支持DPI/格式控制（输出质量可调）
- 内存友好（只渲染首页，不加载整个PDF）
- 社区活跃（PyPI周下载200万+，维护良好）

### 2.2 替代方案对比

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| **pdf2image** | 简单、稳定、跨平台 | 需要Poppler依赖 | ✅ 推荐 |
| PyMuPDF(fitz) | 纯Python、无外部依赖 | 渲染质量不如Poppler | ❌ 备选 |
| Pillow+reportlab | 纯Python | 需解析PDF，复杂度高 | ❌ 过度工程 |
| 外部API(Cloudmersive) | 无需本地依赖 | 成本高、有限流风险 | ❌ 不适合 |

### 2.3 技术架构

```
┌────────────────────────────────────────────────────────────┐
│ Phase 9.5 - arXiv图片生成流程                              │
└────────────────────────────────────────────────────────────┘

Step 1: PDF下载（复用现有逻辑）
  ↓
ArxivCollector.collect()
  ├─ PDFEnhancer已下载PDF到 /tmp/arxiv_pdf_cache/{arxiv_id}.pdf
  ├─ 检查缓存避免重复下载
  └─ 返回RawCandidate (包含pdf_path)

Step 2: 首页转图（新增ImageExtractor.extract_arxiv_image）
  ↓
ImageExtractor.extract_arxiv_image(pdf_path: str) -> Optional[str]
  ├─ 检查Redis缓存 (key: arxiv_pdf_image:{md5(pdf_path)})
  ├─ 未命中缓存:
  │   ├─ 调用 pdf2image.convert_from_path(pdf_path, first_page=1, last_page=1, dpi=150)
  │   ├─ 转换为PNG字节流 (内存操作，不落盘)
  │   ├─ 上传到飞书 → 获取image_key
  │   └─ Redis缓存image_key (TTL=30天)
  └─ 返回 image_key

Step 3: 存储到飞书表格
  ↓
StorageManager.save(candidates)
  ├─ FeishuStorage写入 hero_image_key 字段
  └─ 飞书表格显示图片Key

Step 4: 飞书通知显示
  ↓
FeishuNotifier.notify(candidates)
  ├─ 构建交互式卡片
  ├─ 使用 hero_image_key 显示首页预览图
  └─ 用户点击查看完整PDF
```

---

## 三、核心功能设计

### 3.1 功能规格

| 功能点 | 详细说明 | 验收标准 |
|--------|---------|---------|
| **PDF首页提取** | 渲染PDF第1页为PNG图片 | DPI=150，宽度约1200px，高度约1600px |
| **图片质量** | PNG格式，RGB色彩空间 | 文件大小100KB-500KB，清晰可读 |
| **上传飞书** | 复用FeishuImageUploader | 返回有效的image_key (img_v3_xxx格式) |
| **Redis缓存** | 缓存image_key避免重复转换 | TTL=30天，命中率≥80% (相同论文重复采集) |
| **错误降级** | PDF损坏/转换失败时优雅降级 | 返回None，不阻塞主流程 |

### 3.2 技术约束

**必须满足**：
- 不修改现有PDF下载逻辑（PDFEnhancer）
- 不修改现有图片上传逻辑（FeishuImageUploader）
- 转换失败不影响主流程（返回None）

**性能要求**：
- 单次转换 < 3秒（150 DPI，首页）
- 内存占用 < 50MB（只加载首页）
- 并发支持4个PDF同时转换（ArxivCollector.collect并发数）

**兼容性要求**：
- Linux (Ubuntu 20.04+, WSL2)
- macOS (Homebrew安装Poppler)
- Windows (需预装Poppler，文档说明)

---

## 四、实现步骤

### Step 1: 安装依赖（环境准备）

**Python依赖**：
```bash
pip install pdf2image pillow
```

**系统依赖（Poppler）**：
```bash
# Ubuntu/Debian
sudo apt-get install -y poppler-utils

# macOS
brew install poppler

# Windows (需手动下载)
# 下载地址: https://github.com/oschwartz10612/poppler-windows/releases/
# 解压后添加bin目录到PATH
```

**验证安装**：
```bash
pdftoppm -v  # 应显示版本号
```

### Step 2: 修改ImageExtractor.extract_arxiv_image

**当前实现**（返回None的占位符）：
```python
@staticmethod
async def extract_arxiv_image(pdf_url: str) -> Optional[str]:
    """从arXiv PDF提取首页预览图（预留接口，当前降级为None）"""
    logger.debug("arXiv图片提取暂未实现，直接返回None: %s", pdf_url)
    return None
```

**目标实现**：
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
```

### Step 3: 修改ArxivCollector调用逻辑

**当前调用**（传入PDF URL）：
```python
hero_image_url = await ImageExtractor.extract_arxiv_image(
    result.entry_id
)
```

**修改为**（传入PDF路径）：
```python
# 在PDFEnhancer增强后调用图片提取
if entry.pdf_url:  # arXiv论文必有pdf_url
    pdf_path = self.pdf_enhancer._get_pdf_path(arxiv_id)
    if pdf_path.exists():  # PDF已下载
        hero_image_key = await ImageExtractor.extract_arxiv_image(
            str(pdf_path), arxiv_id
        )
        # 注意：不再设置hero_image_url（PDF预览图无外部URL）
        # 直接设置hero_image_key用于飞书卡片显示
```

### Step 4: 更新依赖文件

**requirements.txt**：
```diff
+ pdf2image==1.16.3
+ pillow>=10.0.0  # pdf2image依赖
```

### Step 5: 更新文档

**README.md - 系统依赖部分**：
```markdown
### 系统依赖

**Poppler** (PDF渲染引擎):
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
```

---

## 五、测试验证

### 5.1 单元测试

**测试脚本**: `scripts/test_arxiv_image_generation.py`

```python
"""测试arXiv PDF首页预览图生成"""

import asyncio
from pathlib import Path
from src.extractors.image_extractor import ImageExtractor

async def test_arxiv_image_generation():
    # 测试用例1: 真实arXiv PDF
    test_cases = [
        ("2511.15168", "/tmp/arxiv_pdf_cache/2511.15168.pdf"),
        ("2511.15752", "/tmp/arxiv_pdf_cache/2511.15752.pdf"),
    ]

    for arxiv_id, pdf_path in test_cases:
        if not Path(pdf_path).exists():
            print(f"⚠️  PDF不存在，跳过: {pdf_path}")
            continue

        print(f"\n测试: {arxiv_id}")
        image_key = await ImageExtractor.extract_arxiv_image(
            pdf_path, arxiv_id
        )

        if image_key:
            print(f"  ✅ 生成成功: {image_key}")
        else:
            print(f"  ❌ 生成失败")

asyncio.run(test_arxiv_image_generation())
```

### 5.2 集成测试

**测试脚本**: `scripts/test_complete_arxiv_pipeline.py`

```python
"""测试完整arXiv流程：采集 → PDF下载 → 图片生成 → 飞书存储 → 通知"""

import asyncio
from src.collectors.arxiv_collector import ArxivCollector
from src.storage.storage_manager import StorageManager
from src.notifier import FeishuNotifier

async def test_complete_pipeline():
    # Step 1: 采集arXiv论文（限制1条测试）
    collector = ArxivCollector()
    collector.cfg.max_results = 1
    candidates = await collector.collect()

    # Step 2: 验证图片生成
    assert len(candidates) > 0
    candidate = candidates[0]
    print(f"论文: {candidate.title}")
    print(f"图片Key: {candidate.hero_image_key}")
    assert candidate.hero_image_key is not None

    # Step 3: 存储飞书表格
    storage = StorageManager()
    await storage.save(candidates)

    # Step 4: 发送飞书通知
    notifier = FeishuNotifier()
    await notifier.notify(candidates)

    print("✅ 完整流程测试通过")

asyncio.run(test_complete_pipeline())
```

### 5.3 验收标准

| 测试项 | 验收标准 | 测试方法 |
|--------|---------|---------|
| **PDF转图成功率** | ≥95% (排除损坏PDF) | 运行100条arXiv采集，统计成功率 |
| **图片质量** | 首页文字清晰可读 | 人工检查10张图片 |
| **飞书卡片显示** | 图片正常加载，尺寸适配卡片 | 飞书群手动验证 |
| **Redis缓存命中** | 重复论文命中率≥80% | 采集相同论文2次，检查日志 |
| **性能** | 单次转换<3秒，内存<50MB | 性能测试脚本 |
| **错误降级** | PDF损坏时返回None，主流程继续 | 故意损坏PDF测试 |

---

## 六、风险评估

### 6.1 技术风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| **Poppler依赖缺失** | 功能完全不可用 | 中 | 启动时检测Poppler，未安装则日志警告并降级 |
| **PDF损坏/加密** | 个别论文转换失败 | 低 | try-catch捕获，返回None，不阻塞主流程 |
| **内存OOM** | 大PDF导致内存溢出 | 极低 | 只渲染首页，限制DPI=150 |
| **飞书上传失败** | image_key获取失败 | 低 | 复用现有错误处理，最多重试2次 |

### 6.2 依赖风险

**Poppler不可用场景**：
1. **GitHub Actions**: 需在workflow中安装 `sudo apt-get install poppler-utils`
2. **Docker容器**: Dockerfile需添加 `RUN apt-get install -y poppler-utils`
3. **Windows用户**: 需手动安装，文档必须清晰说明

**降级策略**：
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

---

## 七、后续优化（Phase 9.6+）

### 7.1 图片质量优化

**当前方案限制**：
- DPI固定150（平衡清晰度和文件大小）
- 无智能裁剪（保留完整首页）

**优化方向**：
- 自适应DPI（根据论文页面大小调整）
- 智能裁剪（去除页眉页脚空白区域）
- OCR文字识别（提取标题/作者/机构作为alt text）

### 7.2 多页预览

**需求场景**：
- 有些论文首页只有标题，图表在第2-3页
- 研究员希望看到关键图表

**实现思路**：
- 检测首页是否有图表（简单启发式：检测图片元素）
- 若首页无图表，尝试提取前3页中首个包含图表的页面

### 7.3 缓存优化

**当前限制**：
- Redis缓存依赖外部服务（可选）
- 本地无持久化缓存

**优化方向**：
- 本地文件缓存 (`/tmp/arxiv_image_cache/`)
- 双层缓存（Redis + 本地文件）

---

## 八、项目规范遵循

### 8.1 Linus哲学约束

**Is this a real problem?**
✅ 是。arXiv占候选池30-40%，无图片影响识别效率，有真实业务价值。

**Is there a simpler way?**
✅ 已选最简方案。pdf2image + Poppler是业界标准，无需重复造轮。

**What will this break?**
✅ 零破坏。仅新增功能，现有逻辑不变，降级优雅（返回None）。

### 8.2 代码质量标准

- **PEP8合规**: 所有代码通过 `black .` 和 `ruff check .`
- **中文注释**: 关键逻辑必须中文注释说明
- **类型注解**: 函数签名必须包含类型提示
- **错误处理**: 所有外部依赖调用必须try-catch
- **日志记录**: INFO记录成功，WARNING记录降级，ERROR记录失败

### 8.3 测试要求

- **单元测试**: 覆盖PDF转图核心逻辑
- **集成测试**: 端到端流程验证
- **手动测试**: 飞书卡片人工确认（截图记录）
- **文档更新**: README系统依赖部分必须更新

---

## 九、开发交付物

### 9.1 代码文件

1. **src/extractors/image_extractor.py** (修改)
   - 实现 `extract_arxiv_image` 方法
   - 添加Poppler可用性检测
   - 添加错误降级逻辑

2. **src/collectors/arxiv_collector.py** (修改)
   - 修改图片提取调用逻辑
   - 传入PDF路径而非URL

3. **requirements.txt** (修改)
   - 添加 `pdf2image==1.16.3`

4. **README.md** (修改)
   - 更新系统依赖安装说明

5. **.github/workflows/daily_collect.yml** (修改)
   - 添加Poppler安装步骤

### 9.2 测试文件

1. **scripts/test_arxiv_image_generation.py** (新增)
   - 单元测试脚本

2. **scripts/test_complete_arxiv_pipeline.py** (新增)
   - 集成测试脚本

### 9.3 文档

1. **docs/phase9.5-implementation-report.md** (新增)
   - 实现细节技术报告
   - 测试结果截图
   - 已知问题和解决方案

---

## 十、时间规划

| 阶段 | 任务 | 预计工时 | 交付物 |
|------|------|---------|--------|
| **Day 1** | 环境准备 + 核心实现 | 4h | 代码完成，本地测试通过 |
| **Day 2** | 集成测试 + 文档更新 | 3h | 测试通过，文档完整 |
| **Day 3** | 部署验证 + 修复问题 | 2h | GitHub Actions运行成功 |

**总计**: 9工时 (约1-2天)

---

## 十一、成功标准

**Phase 9.5完成的标志**：
1. ✅ arXiv候选图片生成成功率 ≥95%
2. ✅ 飞书通知卡片正常显示首页预览图
3. ✅ 飞书表格 `图片Key` 字段正确填充
4. ✅ GitHub Actions每日自动运行无报错
5. ✅ README文档更新，Poppler安装说明清晰
6. ✅ 测试报告完整，包含截图验证

**验收方式**：
- 运行一次完整采集流程
- 检查飞书表格中arXiv记录的 `图片Key` 字段
- 飞书群查看通知卡片，确认首页预览图显示正常
- 截图保存到 `docs/phase9.5-implementation-report.md`

---

**文档结束**
