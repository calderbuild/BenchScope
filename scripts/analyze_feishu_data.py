#!/usr/bin/env python3
"""分析飞书表格数据完整性和LLM评分质量"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from src.config import get_settings


async def main():
    settings = get_settings()

    print("分析飞书表格数据...")
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

        # 获取前10条记录
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{settings.feishu.bitable_app_token}/tables/{settings.feishu.bitable_table_id}/records/search"
        headers = {"Authorization": f"Bearer {access_token}"}
        payload = {"page_size": 10}

        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") == 0:
            items = data.get("data", {}).get("items", [])
            print(f"共取样 {len(items)} 条记录\n")

            # 统计字段填充率
            field_stats = {}
            total_records = len(items)

            for item in items:
                fields = item.get("fields", {})
                for field_name, value in fields.items():
                    if field_name not in field_stats:
                        field_stats[field_name] = 0
                    if value is not None and value != "" and value != []:
                        field_stats[field_name] += 1

            # 评分统计
            scores = {
                "活跃度": [],
                "可复现性": [],
                "许可合规性": [],
                "任务新颖性": [],
                "MGX适配度": [],
                "总分": [],
            }

            for item in items:
                fields = item.get("fields", {})
                for score_name in scores.keys():
                    if score_name in fields and fields[score_name] is not None:
                        scores[score_name].append(fields[score_name])

            # 输出字段填充率
            print("📊 字段数据完整性:")
            print("-" * 80)
            for field_name, count in sorted(field_stats.items(), key=lambda x: -x[1]):
                rate = count / total_records * 100
                bar = "█" * int(rate / 5) + "░" * (20 - int(rate / 5))
                print(f"{field_name:20s} {bar} {rate:5.1f}% ({count}/{total_records})")

            # 输出评分统计
            print("\n📈 评分质量分析:")
            print("-" * 80)
            for score_name, values in scores.items():
                if values:
                    avg = sum(values) / len(values)
                    min_val = min(values)
                    max_val = max(values)
                    print(
                        f"{score_name:15s} 平均:{avg:4.1f} | 最低:{min_val:4.1f} | 最高:{max_val:4.1f} | 样本:{len(values)}"
                    )

            # 输出样例记录
            print("\n📋 样例记录 (前3条):")
            print("-" * 80)
            for idx, item in enumerate(items[:3], 1):
                fields = item.get("fields", {})
                print(f"\n{idx}. {fields.get('标题', 'N/A')}")
                print(f"   来源: {fields.get('来源', 'N/A')}")
                print(f"   总分: {fields.get('总分', 'N/A')}")
                print(
                    f"   活跃度:{fields.get('活跃度', 'N/A')} | 可复现性:{fields.get('可复现性', 'N/A')} | "
                    f"许可合规性:{fields.get('许可合规性', 'N/A')} | 新颖性:{fields.get('任务新颖性', 'N/A')} | "
                    f"MGX适配度:{fields.get('MGX适配度', 'N/A')}"
                )
                print(f"   优先级: {fields.get('优先级', 'N/A')}")
                print(f"   GitHub Stars: {fields.get('GitHub Stars', 'N/A')}")
                print(f"   开源时间: {fields.get('开源时间', 'N/A')}")
                print(f"   评分依据: {fields.get('评分依据', 'N/A')[:100]}...")

        else:
            print(f"查询失败: {data.get('msg')}")


if __name__ == "__main__":
    asyncio.run(main())
