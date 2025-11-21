#!/usr/bin/env python
"""测试GROBID自动启动功能"""

import asyncio
import logging
import sys
from pathlib import Path

# 添加项目路径到sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.main import ensure_grobid_running

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


async def main():
    """测试GROBID自动启动"""
    print("=" * 60)
    print("测试GROBID自动启动功能")
    print("=" * 60)

    grobid_url = "http://localhost:8070"
    result = await ensure_grobid_running(grobid_url=grobid_url, max_wait_seconds=60)

    if result:
        print("\n✅ 测试成功：GROBID服务已启动")
        return 0
    else:
        print("\n❌ 测试失败：GROBID服务未能启动")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
