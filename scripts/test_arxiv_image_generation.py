"""测试arXiv PDF首页预览图生成"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.extractors.image_extractor import ImageExtractor, POPPLER_AVAILABLE
from src.config import get_settings


async def main() -> None:
    print("🧪 测试 arXiv PDF 首页预览图生成")
    print("=" * 60)

    if not POPPLER_AVAILABLE:
        print("⚠️ Poppler/pdf2image 未安装，跳过测试")
        return

    try:
        get_settings()  # 验证环境变量是否齐全
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ 环境变量缺失，跳过测试: {exc}")
        return

    test_cases = [
        ("2511.15168", f"{Path('/tmp/arxiv_pdf_cache')/'2511.15168.pdf'}"),
        ("2511.15752", f"{Path('/tmp/arxiv_pdf_cache')/'2511.15752.pdf'}"),
    ]

    for arxiv_id, pdf_path in test_cases:
        path_obj = Path(pdf_path)
        if not path_obj.exists():
            print(f"⚠️  PDF不存在，跳过: {pdf_path}")
            print("   提示: 先运行一次采集以下载PDF")
            continue

        print(f"\n测试: {arxiv_id}")
        print(f"  PDF路径: {pdf_path}")
        try:
            image_key = await ImageExtractor.extract_arxiv_image(pdf_path, arxiv_id)
            if image_key:
                print(f"  ✅ 生成成功: {image_key}")
            else:
                print("  ❌ 生成失败（返回None）")
        except Exception as exc:  # noqa: BLE001
            print(f"  ❌ 异常: {exc}")

    print("\n" + "=" * 60)
    print("测试结束")


if __name__ == "__main__":
    asyncio.run(main())
