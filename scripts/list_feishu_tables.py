#!/usr/bin/env python3
"""列出飞书多维表格base下的所有表格"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from src.config import get_settings


async def main():
    settings = get_settings()

    print("查询飞书多维表格base下的所有表格...")
    print(f"App Token: {settings.feishu.bitable_app_token}")
    print("=" * 80)

    async with httpx.AsyncClient(timeout=30) as client:
        # 获取access token
        token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        token_resp = await client.post(
            token_url,
            json={
                "app_id": settings.feishu.app_id,
                "app_secret": settings.feishu.app_secret,
            },
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
        access_token = token_data["tenant_access_token"]

        # 获取表格列表
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.feishu.bitable_app_token}/tables"
        headers = {"Authorization": f"Bearer {access_token}"}

        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") == 0:
            tables = data.get("data", {}).get("items", [])
            print(f"找到 {len(tables)} 个表格:\n")

            for idx, table in enumerate(tables, 1):
                table_name = table.get("name")
                table_id = table.get("table_id")
                print(f"{idx}. {table_name}")
                print(f"   Table ID: {table_id}")
                print()
        else:
            print(f"查询失败: {data.get('msg')}")


if __name__ == "__main__":
    asyncio.run(main())
