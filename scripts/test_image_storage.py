"""测试图片数据写入飞书表格"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings
from src.extractors.image_extractor import ImageExtractor
from src.models import ScoredCandidate
from src.storage.storage_manager import StorageManager
from src.storage.feishu_image_uploader import FeishuImageUploader


async def main():
    print("🧪 测试图片数据写入飞书表格\n")
    print("=" * 60)

    settings = get_settings()

    # Step 1: 提取GitHub图片
    print("\n[1/4] 提取 GitHub 图片...")
    test_repo = "https://github.com/microsoft/autogen"
    image_url = await ImageExtractor.extract_github_image(test_repo)

    if not image_url:
        print("  ❌ 图片提取失败")
        return

    print(f"  ✅ 提取成功: {image_url[:80]}...")

    # Step 2: 上传图片到飞书
    print("\n[2/4] 上传图片到飞书...")
    uploader = FeishuImageUploader(settings)
    image_key = await uploader.upload_image(image_url)

    if not image_key:
        print("  ❌ 图片上传失败")
        return

    print(f"  ✅ 上传成功: {image_key}")

    # Step 3: 创建测试候选项
    print("\n[3/4] 创建测试候选项...")
    test_candidate = ScoredCandidate(
        title="[测试] AutoGen: 多智能体对话框架 (图片存储测试)",
        abstract="测试图片URL和图片Key是否正确写入飞书表格",
        url=test_repo,
        source="github",
        github_url=test_repo,
        publish_date=datetime.now(timezone.utc),
        hero_image_url=image_url,  # 图片URL字段
        hero_image_key=image_key,  # 图片Key字段
        activity_score=9.0,
        reproducibility_score=9.0,
        license_score=9.0,
        novelty_score=8.0,
        relevance_score=9.0,
        score_reasoning="测试图片存储功能",
        activity_reasoning="高活跃度",
        reproducibility_reasoning="易复现",
        license_reasoning="开源许可",
        novelty_reasoning="新颖",
        relevance_reasoning="高相关",
        overall_reasoning="测试候选项",
    )

    print(f"  ✅ 候选项创建完成")
    print(f"     - hero_image_url: {test_candidate.hero_image_url[:60]}...")
    print(f"     - hero_image_key: {test_candidate.hero_image_key}")

    # Step 4: 写入飞书表格
    print("\n[4/4] 写入飞书表格...")
    storage = StorageManager()
    await storage.save([test_candidate])

    print("  ✅ 写入完成！")
    print("\n" + "=" * 60)
    print("✅ 完整流程测试通过！")
    print("\n请检查飞书表格，确认：")
    print("  1. 记录已添加")
    print("  2. '图片URL' 字段显示完整链接")
    print("  3. '图片Key' 字段显示飞书image_key")
    print("  4. 点击图片URL可以打开原图")


if __name__ == "__main__":
    asyncio.run(main())
