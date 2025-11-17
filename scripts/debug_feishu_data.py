#!/usr/bin/env python
"""检查飞书表格中的数据结构"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings
from src.storage.feishu_storage import FeishuStorage
import httpx


async def main():
    settings = get_settings()
    storage = FeishuStorage(settings)
    await storage._ensure_access_token()

    async with httpx.AsyncClient(timeout=30) as client:
        url = f"{storage.base_url}/bitable/v1/apps/{settings.feishu.bitable_app_token}/tables/{settings.feishu.bitable_table_id}/records/search"

        payload = {"page_size": 10}  # 只取10条样本

        resp = await client.post(url, headers=storage._auth_header(), json=payload)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            print(f"飞书查询失败: {data}")
            return

        items = data.get("data", {}).get("items", [])

        print(f"获取到 {len(items)} 条记录样本\n")
        print("=" * 80)

        source_values = set()

        for idx, item in enumerate(items, 1):
            fields = item.get("fields", {})
            source = fields.get("来源")
            title = fields.get("标题", "")[:50]
            url_obj = fields.get("URL")

            source_values.add(source)

            print(f"\n[{idx}] 标题: {title}...")
            print(f"    来源: {source}")
            print(f"    URL类型: {type(url_obj)}")
            if isinstance(url_obj, dict):
                print(f"    URL链接: {url_obj.get('link', '')[:60]}...")
            elif isinstance(url_obj, str):
                print(f"    URL字符串: {url_obj[:60]}...")

        print("\n" + "=" * 80)
        print(f"\n所有来源值: {source_values}")
        print(f"\narXiv来源数量: {sum(1 for item in items if item.get('fields', {}).get('来源') == 'arXiv')}")
        print(f"ArXiv来源数量: {sum(1 for item in items if item.get('fields', {}).get('来源') == 'ArXiv')}")


if __name__ == "__main__":
    asyncio.run(main())
