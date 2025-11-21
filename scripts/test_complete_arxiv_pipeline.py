"""集成测试：arXiv采集 → PDF下载 → 图片生成 → 存储 → 通知"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from dataclasses import asdict

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.collectors.arxiv_collector import ArxivCollector
from src.enhancer.pdf_enhancer import PDFEnhancer
from src.notifier.feishu_notifier import FeishuNotifier
from src.storage.storage_manager import StorageManager
from src.extractors.image_extractor import POPPLER_AVAILABLE
from src.config import get_settings
from src.models import ScoredCandidate


async def main() -> None:
    print("🧪 测试完整 arXiv 流程")
    print("=" * 60)

    if not POPPLER_AVAILABLE:
        print("⚠️ Poppler/pdf2image 未安装，跳过集成测试")
        return

    try:
        get_settings()  # 确保环境变量齐全
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ 环境变量缺失，跳过测试: {exc}")
        return

    # Step 1: 采集（限制1条，降低成本）
    collector = ArxivCollector()
    original_max = collector.max_results
    collector.max_results = 1
    candidates = await collector.collect()
    collector.max_results = original_max

    if not candidates:
        print("❌ 未采集到arXiv候选")
        return

    candidate = candidates[0]
    print(f"✅ 采集成功: {candidate.title[:60]}...")

    # Step 2: PDF增强（下载 + 解析 + 生成封面）
    enhancer = PDFEnhancer()
    enhanced_candidates = await enhancer.enhance_batch([candidate])
    enhanced_raw = enhanced_candidates[0]
    if enhanced_raw.hero_image_key:
        print(f"✅ 图片Key: {enhanced_raw.hero_image_key}")
    else:
        print("❌ 图片Key为空，可能是PDF转换失败")

    # 转为ScoredCandidate以满足存储/通知接口（评分字段使用默认值）
    scored_candidate = ScoredCandidate(**asdict(enhanced_raw))

    # Step 3: 存储到飞书表格
    storage = StorageManager()
    await storage.save([scored_candidate])
    print("✅ 存储完成")

    # Step 4: 发送飞书通知
    notifier = FeishuNotifier()
    await notifier.notify([scored_candidate])
    print("✅ 飞书通知完成")

    print("\n" + "=" * 60)
    print("完成：请在飞书表格和通知卡片中确认图片展示效果")


if __name__ == "__main__":
    asyncio.run(main())
