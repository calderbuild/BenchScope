#!/usr/bin/env python
"""
测试PDF增强功能（使用飞书已有的arXiv候选）

目标：
1. 从飞书表格获取已有的arXiv来源候选
2. 对这些候选进行PDF增强
3. 对比增强前后的数据质量
4. 生成测试报告
"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_settings
from src.enhancer import PDFEnhancer
from src.models import RawCandidate
from src.storage.feishu_storage import FeishuStorage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def fetch_arxiv_candidates() -> List[RawCandidate]:
    """从飞书表格获取arXiv来源的候选项"""
    logger.info("正在从飞书表格获取arXiv候选...")

    settings = get_settings()
    storage = FeishuStorage(settings)

    # 确保有access token
    await storage._ensure_access_token()

    # 使用search API分页获取所有记录
    import httpx

    arxiv_candidates = []
    page_token = None

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            url = f"{storage.base_url}/bitable/v1/apps/{settings.feishu.bitable_app_token}/tables/{settings.feishu.bitable_table_id}/records/search"

            payload = {"page_size": 100}
            if page_token:
                payload["page_token"] = page_token

            resp = await client.post(url, headers=storage._auth_header(), json=payload)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                logger.error(f"飞书查询失败: {data}")
                break

            # 提取记录
            items = data.get("data", {}).get("items", [])

            for item in items:
                fields = item.get("fields", {})
                source = fields.get("来源")

                if source == "arxiv":  # 修正：飞书表格使用小写arxiv
                    # 提取URL字段（可能是对象或字符串）
                    url_obj = fields.get("URL")
                    url_value = ""
                    if isinstance(url_obj, dict):
                        url_value = url_obj.get("link", "")
                    elif isinstance(url_obj, str):
                        url_value = url_obj

                    # 提取标题（可能是列表结构 [{'text': '...', 'type': 'text'}]）
                    title_obj = fields.get("标题", "")
                    title_value = ""
                    if isinstance(title_obj, list) and len(title_obj) > 0:
                        # 标题是列表结构
                        title_value = title_obj[0].get("text", "")
                    elif isinstance(title_obj, str):
                        title_value = title_obj

                    # 转换为RawCandidate
                    candidate = RawCandidate(
                        title=title_value or "Untitled",
                        url=url_value,
                        source="arxiv",
                        abstract=fields.get("摘要", ""),
                        paper_url=url_value,  # arXiv使用URL作为paper_url
                        raw_metadata={
                            "feishu_record_id": item.get("record_id"),
                            "original_abstract_length": len(fields.get("摘要", "")),
                        },
                    )
                    arxiv_candidates.append(candidate)

            # 检查是否还有下一页
            has_more = data.get("data", {}).get("has_more", False)
            if not has_more:
                break

            page_token = data.get("data", {}).get("page_token")
            if not page_token:
                break

    logger.info(f"获取到 {len(arxiv_candidates)} 条arXiv候选")
    return arxiv_candidates


async def test_pdf_enhancement(candidates: List[RawCandidate], sample_size: int = 5) -> Dict[str, Any]:
    """测试PDF增强功能

    Args:
        candidates: 候选项列表
        sample_size: 测试样本数量

    Returns:
        测试结果字典
    """
    logger.info(f"开始PDF增强测试（样本量: {sample_size}）...")

    # 随机选择样本（取前N条）
    samples = candidates[:sample_size]
    logger.info(f"选择了 {len(samples)} 条样本进行测试")

    # 初始化PDF增强器
    enhancer = PDFEnhancer()

    # 统计数据
    results = {
        "total_samples": len(samples),
        "success_count": 0,
        "failed_count": 0,
        "before_stats": {
            "abstract_lengths": [],
            "empty_abstracts": 0,
        },
        "after_stats": {
            "abstract_lengths": [],
            "empty_abstracts": 0,
            "has_evaluation": 0,
            "has_dataset": 0,
            "has_baselines": 0,
        },
        "samples": [],
    }

    # 记录增强前的统计
    for candidate in samples:
        abstract_len = len(candidate.abstract or "")
        results["before_stats"]["abstract_lengths"].append(abstract_len)
        if abstract_len == 0:
            results["before_stats"]["empty_abstracts"] += 1

    # 执行PDF增强
    for idx, candidate in enumerate(samples, 1):
        logger.info(f"处理 [{idx}/{len(samples)}]: {candidate.title[:50]}...")

        try:
            enhanced = await enhancer.enhance_candidate(candidate)

            # 检查是否增强成功
            metadata = enhanced.raw_metadata or {}
            has_enhancement = bool(
                metadata.get("evaluation_summary") or
                metadata.get("dataset_summary") or
                metadata.get("baselines_summary")
            )

            if has_enhancement:
                results["success_count"] += 1
                logger.info(f"  ✅ 增强成功")
            else:
                results["failed_count"] += 1
                logger.warning(f"  ⚠️  未获取到PDF内容")

            # 统计增强后的数据
            abstract_len = len(enhanced.abstract or "")
            results["after_stats"]["abstract_lengths"].append(abstract_len)
            if abstract_len == 0:
                results["after_stats"]["empty_abstracts"] += 1

            if metadata.get("evaluation_summary"):
                results["after_stats"]["has_evaluation"] += 1
            if metadata.get("dataset_summary"):
                results["after_stats"]["has_dataset"] += 1
            if metadata.get("baselines_summary"):
                results["after_stats"]["has_baselines"] += 1

            # 记录样本详情
            sample_result = {
                "title": enhanced.title,
                "url": enhanced.url or enhanced.paper_url,
                "before_abstract_length": len(candidate.abstract or ""),
                "after_abstract_length": abstract_len,
                "has_evaluation": bool(metadata.get("evaluation_summary")),
                "has_dataset": bool(metadata.get("dataset_summary")),
                "has_baselines": bool(metadata.get("baselines_summary")),
                "evaluation_summary_length": len(metadata.get("evaluation_summary", "")),
                "dataset_summary_length": len(metadata.get("dataset_summary", "")),
                "baselines_summary_length": len(metadata.get("baselines_summary", "")),
            }
            results["samples"].append(sample_result)

        except Exception as e:
            logger.error(f"  ❌ 增强失败: {e}")
            results["failed_count"] += 1
            results["after_stats"]["abstract_lengths"].append(0)

    # 计算平均值
    if results["before_stats"]["abstract_lengths"]:
        results["before_stats"]["avg_abstract_length"] = sum(
            results["before_stats"]["abstract_lengths"]
        ) / len(results["before_stats"]["abstract_lengths"])

    if results["after_stats"]["abstract_lengths"]:
        results["after_stats"]["avg_abstract_length"] = sum(
            results["after_stats"]["abstract_lengths"]
        ) / len(results["after_stats"]["abstract_lengths"])

    return results


def print_report(results: Dict[str, Any]):
    """打印测试报告"""
    print("\n" + "=" * 80)
    print("PDF增强功能测试报告")
    print("=" * 80)
    print(f"\n测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"样本数量: {results['total_samples']}")
    print(f"成功增强: {results['success_count']}")
    print(f"增强失败: {results['failed_count']}")
    print(f"成功率: {results['success_count'] / results['total_samples'] * 100:.1f}%")

    print("\n" + "-" * 80)
    print("数据质量对比")
    print("-" * 80)

    before = results["before_stats"]
    after = results["after_stats"]

    print(f"\n【摘要长度】")
    print(f"  增强前平均: {before.get('avg_abstract_length', 0):.0f} 字符")
    print(f"  增强后平均: {after.get('avg_abstract_length', 0):.0f} 字符")
    if before.get('avg_abstract_length', 0) > 0:
        improvement = (after.get('avg_abstract_length', 0) - before.get('avg_abstract_length', 0)) / before.get('avg_abstract_length', 0) * 100
        print(f"  提升幅度: {improvement:+.1f}%")

    print(f"\n【空摘要数量】")
    print(f"  增强前: {before['empty_abstracts']}")
    print(f"  增强后: {after['empty_abstracts']}")

    print(f"\n【PDF深度内容覆盖率】")
    print(f"  Evaluation摘要: {after['has_evaluation']}/{results['total_samples']} ({after['has_evaluation']/results['total_samples']*100:.1f}%)")
    print(f"  Dataset摘要: {after['has_dataset']}/{results['total_samples']} ({after['has_dataset']/results['total_samples']*100:.1f}%)")
    print(f"  Baselines摘要: {after['has_baselines']}/{results['total_samples']} ({after['has_baselines']/results['total_samples']*100:.1f}%)")

    print("\n" + "-" * 80)
    print("样本详情")
    print("-" * 80)

    for idx, sample in enumerate(results["samples"], 1):
        print(f"\n[{idx}] {sample['title'][:60]}...")
        print(f"    URL: {sample['url']}")
        print(f"    摘要长度: {sample['before_abstract_length']} → {sample['after_abstract_length']}")
        print(f"    Evaluation: {'✅' if sample['has_evaluation'] else '❌'} ({sample['evaluation_summary_length']} 字符)")
        print(f"    Dataset: {'✅' if sample['has_dataset'] else '❌'} ({sample['dataset_summary_length']} 字符)")
        print(f"    Baselines: {'✅' if sample['has_baselines'] else '❌'} ({sample['baselines_summary_length']} 字符)")

    print("\n" + "=" * 80)


async def main():
    """主函数"""
    try:
        # 1. 获取arXiv候选
        candidates = await fetch_arxiv_candidates()

        if not candidates:
            logger.error("未找到arXiv候选，测试终止")
            return

        # 2. 执行PDF增强测试
        results = await test_pdf_enhancement(candidates, sample_size=5)

        # 3. 打印报告
        print_report(results)

        # 4. 保存报告到文件
        report_file = f"logs/pdf_enhancement_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        Path("logs").mkdir(exist_ok=True)

        import json
        with open(report_file, "w", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write("PDF增强功能测试报告\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"样本数量: {results['total_samples']}\n")
            f.write(f"成功增强: {results['success_count']}\n")
            f.write(f"增强失败: {results['failed_count']}\n\n")
            f.write("详细数据（JSON格式）:\n")
            f.write(json.dumps(results, indent=2, ensure_ascii=False))

        logger.info(f"报告已保存到: {report_file}")

    except Exception as e:
        logger.error(f"测试失败: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
