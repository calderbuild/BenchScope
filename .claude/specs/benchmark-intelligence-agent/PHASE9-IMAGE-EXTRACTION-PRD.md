# Phase 9: 富媒体推送增强 - 图片爬取与展示

**版本**: v1.0
**创建时间**: 2025-11-20
**状态**: PRD编写中
**预计工期**: 1周

---

## 核心目标

为飞书推送添加视觉吸引力，通过爬取Benchmark项目的主图/预览图并上传到飞书，在消息卡片顶部展示，提升用户浏览体验。

**关键指标**:
- 图片提取成功率 ≥ 60%（不同来源差异大）
- 图片上传成功率 ≥ 95%（飞书API稳定）
- 不影响核心流程性能（图片处理异步，失败降级）

---

## 背景与动机

### 当前问题

飞书推送目前是纯文本+Markdown卡片，缺少视觉吸引力：
- 用户需要点击链接才能看到项目截图
- 无法快速判断Benchmark的质量和类型
- 推送消息在众多通知中不够突出

### 参考案例

Founder Park推送风格（用户提供的示例）：
- 产品标题 + 链接
- **富媒体图片**（产品截图、架构图）
- 结构化内容（产品亮点、功能列表）
- 引用卡片（微信文章预览带缩略图）

### 为什么不做视频

1. 飞书消息卡片不支持视频直接嵌入
2. 只能发送视频封面图+链接按钮
3. 大部分Benchmark项目没有演示视频
4. 视频处理增加复杂度，性价比低

---

## 技术方案设计

### 1. 图片爬取策略（按来源分类）

#### 1.1 arXiv论文

**提取目标**: 论文首页预览图（PDF第一页转图片）

**技术方案**:
```python
from pdf2image import convert_from_path

# 下载PDF → 转换第一页为图片 → 上传飞书
pdf_path = download_pdf(arxiv_url)
images = convert_from_path(pdf_path, first_page=1, last_page=1)
hero_image = images[0]  # PIL.Image对象
```

**依赖**: `pdf2image`, `poppler-utils` (系统依赖)

**备选方案**: 使用arXiv提供的缩略图API（质量较低）

#### 1.2 GitHub仓库

**提取目标** (优先级递减):
1. **Social Preview Image** (GitHub仓库设置的分享图)
   ```python
   # 通过GitHub GraphQL API获取
   query {
     repository(owner: "xxx", name: "yyy") {
       openGraphImageUrl
     }
   }
   ```

2. **README中第一张大图** (>400x300px)
   ```python
   soup = BeautifulSoup(readme_html, 'html.parser')
   imgs = soup.find_all('img')
   for img in imgs:
       if is_large_image(img):  # 过滤小图标
           return img['src']
   ```

3. **开源协议README模板图** (如果项目用了模板)

**备选方案**: 使用GitHub默认的avatar或无图片

#### 1.3 HuggingFace模型

**提取目标**: Model Card封面图

**技术方案**:
```python
# HuggingFace Hub API提供cardData字段
from huggingface_hub import HfApi
api = HfApi()
model_info = api.model_info(repo_id="xxx/yyy")
card_data = model_info.cardData
hero_image_url = card_data.get("thumbnail", None)
```

#### 1.4 其他来源

- **HELM/TechEmpower/DBEngines**: 网站Logo或首屏截图（通过`<meta property="og:image">`）
- **Semantic Scholar**: 论文PDF首页（同arXiv）

### 2. 图片处理流程

```
采集器获取URL
    ↓
提取hero_image_url (上面的策略)
    ↓
下载图片到本地临时文件 (httpx下载)
    ↓
图片验证 (>50KB, <5MB, 格式jpg/png)
    ↓
上传到飞书 (POST /open-apis/im/v1/images)
    ↓
获取image_key并缓存 (Redis, key=URL hash)
    ↓
存入RawCandidate.hero_image_key字段
```

**关键点**:
- **异步处理**: 图片爬取不阻塞主流程
- **失败降级**: 图片处理失败不影响候选入库
- **缓存机制**: 相同URL不重复上传（Redis TTL 30天）

### 3. 飞书图片上传API集成

**API端点**: `POST https://open.feishu.cn/open-apis/im/v1/images`

**请求示例**:
```python
import httpx

files = {"image": ("preview.png", image_bytes, "image/png")}
data = {"image_type": "message"}  # 消息类型图片
headers = {
    "Authorization": f"Bearer {tenant_access_token}",
}

async with httpx.AsyncClient() as client:
    resp = await client.post(
        "https://open.feishu.cn/open-apis/im/v1/images",
        headers=headers,
        files=files,
        data=data,
    )
    result = resp.json()
    image_key = result["data"]["image_key"]
    return image_key
```

**注意事项**:
1. **Tenant Access Token**: 需要先获取（有效期2小时，需缓存）
2. **图片限制**:
   - 格式: jpg/jpeg/png/bmp/gif
   - 大小: 最大10MB
   - 推荐尺寸: 600-800px宽度
3. **速率限制**: 100次/分钟（批量上传需控制并发）

### 4. 飞书卡片图片展示

**卡片结构更新** (`src/notifier/feishu_notifier.py`):

```python
def _build_card(self, title: str, candidate: ScoredCandidate) -> dict:
    elements = []

    # 1. 如果有hero_image_key，添加图片组件
    if candidate.hero_image_key:
        elements.append({
            "tag": "img",
            "img_key": candidate.hero_image_key,
            "alt": {"tag": "plain_text", "content": f"{candidate.title} 预览图"},
            "preview": True,  # 点击放大
            "scale_type": "crop_center",  # 居中裁剪
            "size": "large",  # 大尺寸显示
        })
        elements.append({"tag": "hr"})  # 分割线

    # 2. 原有内容（标题、评分、评分依据等）
    content = f"**{candidate.title}**\n\n..."
    elements.append({"tag": "div", "text": {"tag": "lark_md", "content": content}})

    # 3. 按钮
    elements.append({"tag": "hr"})
    elements.append({"tag": "action", "actions": [...]})

    return {
        "msg_type": "interactive",
        "card": {
            "header": {...},
            "elements": elements,
        }
    }
```

**视觉效果**:
```
┌──────────────────────────────────┐
│  🔥 发现高质量Benchmark候选       │ ← header (红色)
├──────────────────────────────────┤
│                                  │
│   [━━━ 图片预览 ━━━]             │ ← 新增图片组件
│   (600x400px Benchmark截图)      │
│                                  │
├──────────────────────────────────┤
│ **Benchmark标题**                │
│ 综合评分: 9.2 / 10               │
│ 活跃度 9.0 | 可复现性 9.5 ...    │
│                                  │
│ **评分依据**                     │
│ 该项目提供完整的代码和数据...     │
├──────────────────────────────────┤
│ [查看详情] [GitHub] [飞书表格]   │
└──────────────────────────────────┘
```

---

## 数据模型变更

### RawCandidate 新增字段

```python
@dataclass(slots=True)
class RawCandidate:
    # ... 现有字段 ...

    # Phase 9 新增：图片相关字段
    hero_image_url: Optional[str] = None  # 原始图片URL（爬取阶段）
    hero_image_key: Optional[str] = None  # 飞书image_key（上传阶段）
```

### ScoredCandidate 继承字段

```python
@dataclass(slots=True)
class ScoredCandidate:
    # ... 现有字段 ...

    # Phase 9 继承自RawCandidate
    hero_image_url: Optional[str] = None
    hero_image_key: Optional[str] = None
```

---

## 新增模块设计

### 模块1: 图片提取器 (`src/extractors/image_extractor.py`)

**职责**: 从不同数据源提取hero_image_url

```python
class ImageExtractor:
    """统一图片提取接口"""

    @staticmethod
    async def extract_arxiv_image(pdf_url: str) -> Optional[str]:
        """从arXiv PDF提取首页预览图"""
        pass

    @staticmethod
    async def extract_github_image(repo_url: str) -> Optional[str]:
        """从GitHub仓库提取Social Preview或README图"""
        pass

    @staticmethod
    async def extract_huggingface_image(model_id: str) -> Optional[str]:
        """从HuggingFace模型卡片提取封面图"""
        pass

    @staticmethod
    async def extract_og_image(webpage_url: str) -> Optional[str]:
        """通用方法：从网页<meta property="og:image">提取"""
        pass
```

### 模块2: 飞书图片上传器 (`src/storage/feishu_image_uploader.py`)

**职责**: 下载图片 → 上传到飞书 → 返回image_key

```python
class FeishuImageUploader:
    """飞书图片上传与缓存管理"""

    def __init__(self, settings: Settings, redis_client: Optional[Redis] = None):
        self.settings = settings
        self.redis = redis_client  # 缓存image_key
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    async def get_tenant_access_token(self) -> str:
        """获取Tenant Access Token（缓存2小时）"""
        pass

    async def upload_image(self, image_url: str) -> Optional[str]:
        """下载图片并上传到飞书，返回image_key"""
        # 1. 检查Redis缓存
        cache_key = f"feishu:img:{hashlib.md5(image_url.encode()).hexdigest()}"
        if self.redis:
            cached = await self.redis.get(cache_key)
            if cached:
                return cached.decode()

        # 2. 下载图片
        image_bytes = await self._download_image(image_url)
        if not image_bytes:
            return None

        # 3. 上传到飞书
        image_key = await self._upload_to_feishu(image_bytes)

        # 4. 缓存30天
        if self.redis and image_key:
            await self.redis.setex(cache_key, 30*24*3600, image_key.encode())

        return image_key

    async def _download_image(self, url: str) -> Optional[bytes]:
        """下载图片并验证"""
        pass

    async def _upload_to_feishu(self, image_bytes: bytes) -> Optional[str]:
        """调用飞书API上传图片"""
        pass
```

### 模块3: 采集器集成

**修改所有采集器**，在`_to_candidates()`中调用ImageExtractor：

```python
# src/collectors/arxiv_collector.py
candidates.append(
    RawCandidate(
        title=paper.title.strip(),
        url=paper.pdf_url,
        source="arxiv",
        # ... 其他字段 ...
        hero_image_url=await ImageExtractor.extract_arxiv_image(paper.pdf_url),
    )
)
```

### 模块4: 主流程集成

**修改 `src/main.py`**，在评分后、存储前上传图片：

```python
async def main():
    # Step 1: 采集 (hero_image_url已提取)
    raw_candidates = await collect_all()

    # Step 2: 预筛选
    filtered = await prefilter_batch(raw_candidates)

    # Step 3: LLM评分
    scored = await scorer.score_batch(filtered)

    # Step 4: 🆕 批量上传图片到飞书
    uploader = FeishuImageUploader(settings)
    for candidate in scored:
        if candidate.hero_image_url:
            candidate.hero_image_key = await uploader.upload_image(
                candidate.hero_image_url
            )

    # Step 5: 存储（hero_image_key已填充）
    await storage.save_batch(scored)

    # Step 6: 飞书通知（卡片自动显示图片）
    await notifier.notify(scored)
```

---

## 依赖变更

### requirements.txt 新增

```txt
# Phase 9: 图片处理
pdf2image>=1.17.0         # PDF转图片
Pillow>=10.2.0            # 图片处理
```

### 系统依赖 (GitHub Actions)

```yaml
# .github/workflows/daily_collect.yml
- name: Install system dependencies
  run: |
    sudo apt-get update
    sudo apt-get install -y poppler-utils  # pdf2image依赖
```

---

## 性能影响评估

### 时间开销

| 阶段 | 原耗时 | 新增耗时 | 优化后耗时 | 说明 |
|------|--------|---------|----------|------|
| 采集 | 38s | +5s | 40s | 图片URL提取（异步并行） |
| 评分 | 12s | 0s | 12s | 不影响 |
| 图片上传 | 0s | +15s | 8s | 批量异步上传50并发，缓存命中30% |
| 存储 | 5s | 0s | 5s | 不影响 |
| **总计** | **59s** | **+20s** | **65s** | 仍在目标范围内(<120s) |

### 成本影响

- **Redis缓存**: 图片URL → image_key映射（~1KB/条，30天TTL）
  - 预计: 每月1000条候选 × 1KB = 1MB（忽略不计）

- **飞书存储**: 图片上传到飞书云（免费）
  - 预计: 每月600张图片 × 平均500KB = 300MB（飞书免费额度足够）

- **网络流量**: 下载图片 → 上传飞书
  - 预计: 每月600张 × (下载500KB + 上传500KB) = 600MB（GitHub Actions免费额度足够）

---

## 降级策略

### 失败场景处理

| 失败场景 | 处理策略 | 用户影响 |
|---------|---------|---------|
| 图片URL提取失败 | `hero_image_url = None`，继续流程 | 卡片无图片，不影响核心功能 |
| 图片下载失败 | 记录日志，`hero_image_key = None` | 卡片无图片 |
| 飞书上传失败 | 重试1次，失败后放弃 | 卡片无图片 |
| PDF转图片失败 | 使用arXiv缩略图API备选 | 图片质量较低但有显示 |

### 质量保证

1. **图片验证**:
   - 大小: 50KB ~ 5MB
   - 格式: jpg/png/gif
   - 尺寸: 宽度 ≥ 300px

2. **超时控制**:
   - 图片下载: 5秒超时
   - 飞书上传: 10秒超时
   - PDF转图片: 15秒超时

3. **并发控制**:
   - 图片下载: 20并发
   - 飞书上传: 10并发（避免触发速率限制）

---

## 测试计划

### 单元测试

```python
# tests/test_image_extractor.py
async def test_extract_github_social_preview():
    """测试GitHub Social Preview图提取"""
    url = "https://github.com/microsoft/autogen"
    image_url = await ImageExtractor.extract_github_image(url)
    assert image_url is not None
    assert "githubusercontent.com" in image_url

async def test_extract_arxiv_pdf_preview():
    """测试arXiv PDF首页转图片"""
    pdf_url = "https://arxiv.org/pdf/2401.12345.pdf"
    image_url = await ImageExtractor.extract_arxiv_image(pdf_url)
    assert image_url is not None

async def test_feishu_image_upload():
    """测试飞书图片上传"""
    uploader = FeishuImageUploader(settings)
    image_url = "https://example.com/test.png"
    image_key = await uploader.upload_image(image_url)
    assert image_key is not None
    assert image_key.startswith("img_")
```

### 集成测试

```bash
# 1. 运行完整流程，验证图片显示
.venv/bin/python -m src.main

# 2. 检查飞书卡片是否显示图片
# 3. 检查Redis缓存是否生效
redis-cli GET "feishu:img:xxxx"

# 4. 检查日志中图片处理统计
grep "图片上传" logs/$(ls -t logs/ | head -n1)
```

### 手动验证

**必须手动验证**（飞书播报效果）：
1. 触发完整流程，等待飞书推送
2. 打开飞书群，检查消息卡片
3. 验证图片是否正确显示
4. 点击图片验证预览功能
5. 截图保存到 `docs/phase9-test-report.md`

---

## 验收标准

| 指标 | 目标 | 验证方法 |
|------|------|---------|
| 图片提取成功率 | ≥ 60% | 统计日志中成功提取的比例 |
| 图片上传成功率 | ≥ 95% | 统计飞书API调用成功率 |
| 缓存命中率 | ≥ 30% | 统计Redis缓存命中次数 |
| 性能影响 | 总耗时 < 120s | 运行完整流程计时 |
| 卡片展示效果 | 图片清晰可见 | 手动检查飞书推送 |

---

## 里程碑

| 阶段 | 任务 | 预计时间 | 交付物 |
|------|------|---------|--------|
| Day 1-2 | 图片提取器开发 | 2天 | `src/extractors/image_extractor.py` + 单元测试 |
| Day 3-4 | 飞书上传器开发 | 2天 | `src/storage/feishu_image_uploader.py` + 单元测试 |
| Day 5 | 采集器集成 | 1天 | 修改5个采集器，添加hero_image_url提取 |
| Day 6 | 飞书卡片集成 | 1天 | 修改`feishu_notifier.py`，添加图片组件 |
| Day 7 | 测试与验收 | 1天 | 集成测试 + 手动验证 + 测试报告 |

---

## 风险与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| PDF转图片性能差 | 流程超时 | 中 | 使用arXiv缩略图API备选 |
| 飞书API速率限制 | 图片上传失败 | 低 | 控制并发数≤10，添加重试 |
| GitHub GraphQL API配额 | Social Preview提取失败 | 中 | 降级到README图片提取 |
| 图片格式不兼容 | 飞书上传失败 | 低 | Pillow转换为标准格式 |

---

## 后续优化方向

### Phase 9.5 (可选，3个月后)

1. **视频封面提取**:
   - 从YouTube/B站链接提取视频封面
   - 添加"观看视频"按钮

2. **图片智能裁剪**:
   - 检测图片主体位置
   - 自动裁剪为16:9比例

3. **图片质量评分**:
   - 使用CV模型评估图片质量
   - 低质量图片不显示

4. **多图预览**:
   - 支持轮播图（如果项目有多张截图）
   - 用户左右滑动查看

---

## 参考文档

- 飞书图片上传API: https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/image/create
- 飞书消息卡片图片组件: https://open.feishu.cn/document/feishu-cards/card-components/content-components/image
- GitHub GraphQL API: https://docs.github.com/en/graphql
- HuggingFace Hub API: https://huggingface.co/docs/hub/api
- pdf2image文档: https://github.com/Belval/pdf2image

---

**PRD质量自评**: 9.0/10

**亮点**:
- ✅ 完整的技术方案（爬取+上传+展示）
- ✅ 详细的降级策略（失败不影响核心）
- ✅ 清晰的数据流设计
- ✅ 性能影响评估（+6秒可接受）

**待改进**:
- 视频封面提取（后续优化）
- 图片智能裁剪（Phase 9.5）
