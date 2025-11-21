"""飞书Webhook通知"""

from __future__ import annotations

import asyncio
import base64
import hmac
import hashlib
import logging
import time
from datetime import datetime
from typing import List, Optional

import httpx

from src.common import constants
from src.config import Settings, get_settings
from src.models import ScoredCandidate

logger = logging.getLogger(__name__)


class FeishuNotifier:
    """飞书Webhook卡片通知"""

    def __init__(
        self, webhook_url: Optional[str] = None, settings: Optional[Settings] = None
    ) -> None:
        self.settings = settings or get_settings()
        self.webhook_url = webhook_url or self.settings.feishu.webhook_url

    async def notify(self, candidates: List[ScoredCandidate]) -> None:
        """分层推送: 高优先级卡片 + 中优先级摘要"""
        if not self.webhook_url:
            logger.warning("未配置飞书Webhook,跳过通知")
            return

        if not candidates:
            logger.info("无候选需要通知")
            return

        qualified = [
            c for c in candidates if c.total_score >= constants.MIN_TOTAL_SCORE
        ]
        if not qualified:
            logger.info("无高分候选,跳过通知")
            return

        # 分层处理
        high_priority = [c for c in qualified if c.priority == "high"]
        medium_priority = [c for c in qualified if c.priority == "medium"]

        # 1. 推送所有高优先级卡片
        for candidate in high_priority:
            await self.send_card("🔥 发现高质量Benchmark候选", candidate)
            await asyncio.sleep(constants.FEISHU_RATE_LIMIT_DELAY)

        # 2. 推送中优先级摘要 (新增)
        if medium_priority:
            await self._send_medium_priority_summary(medium_priority)
            await asyncio.sleep(constants.FEISHU_RATE_LIMIT_DELAY)

        # 3. 推送统计摘要卡片 (支持markdown)
        summary_card = self._build_summary_card(
            qualified, high_priority, medium_priority
        )
        await self._send_webhook(summary_card)

        # 4. 日志记录推送统计
        logger.info(
            f"✅ 推送完成: 高优先级{len(high_priority)}条(卡片), "
            f"中优先级{len(medium_priority)}条(摘要)"
        )

    async def send_card(self, title: str, candidate: ScoredCandidate) -> None:
        """发送单条候选的卡片消息"""

        card = self._build_card(title, candidate)
        await self._send_webhook(card)

    async def send_text(self, message: str) -> None:
        """发送纯文本消息"""

        if not self.webhook_url:
            logger.warning("未配置飞书Webhook,跳过通知")
            return

        payload = {"msg_type": "text", "content": {"text": message}}
        await self._send_webhook(payload)

    @staticmethod
    def _format_source_name(source: str) -> str:
        """统一来源展示名称，避免多处硬编码"""

        fallback = source or "unknown"
        normalized = fallback.lower()
        return constants.FEISHU_SOURCE_NAME_MAP.get(normalized, fallback.title())

    async def _send_medium_priority_summary(
        self, candidates: List[ScoredCandidate]
    ) -> None:
        """发送中优先级候选摘要卡片 - 专业排版版"""
        top_limit = constants.FEISHU_MEDIUM_TOPK
        top_candidates = sorted(candidates, key=lambda x: x.total_score, reverse=True)[
            :top_limit
        ]
        avg_medium_score = sum(c.total_score for c in candidates) / len(candidates)

        # 计算分数范围
        scores = [c.total_score for c in candidates]
        min_score = min(scores)
        max_score = max(scores)

        # 构建内容 - 专业排版
        content = (
            f"**候选概览**\n"
            f"  总数: {len(candidates)} 条  │  平均分: {avg_medium_score:.1f} / 10  │  分数区间: {min_score:.1f} ~ {max_score:.1f}\n\n"
            f"**Top {min(top_limit, len(top_candidates))} 推荐**\n\n"
        )

        for i, c in enumerate(top_candidates, 1):
            title = (
                c.title[: constants.TITLE_TRUNCATE_MEDIUM] + "..."
                if len(c.title) > constants.TITLE_TRUNCATE_MEDIUM
                else c.title
            )
            source_name = self._format_source_name(c.source)

            content += (
                f"**{i}. {title}**\n"
                f"   来源: {source_name}  │  评分: {c.total_score:.1f}  │  "
                f"活跃度: {c.activity_score:.1f}  │  可复现性: {c.reproducibility_score:.1f}\n"
                f"   [查看详情]({c.url})\n\n"
            )

        if len(candidates) > top_limit:
            content += f"\n其余 {len(candidates)-top_limit} 条候选可在飞书表格查看\n"

        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": "中优先级候选推荐"},
                    "template": "yellow",
                },
                "elements": [
                    {"tag": "div", "text": {"tag": "lark_md", "content": content}},
                    {"tag": "hr"},
                    {
                        "tag": "action",
                        "actions": [
                            {
                                "tag": "button",
                                "text": {
                                    "content": "查看完整表格",
                                    "tag": "plain_text",
                                },
                                "url": constants.FEISHU_BENCH_TABLE_URL,
                                "type": "primary",
                            }
                        ],
                    },
                ],
            },
        }

        await self._send_webhook(card)

    def _build_summary_card(
        self,
        qualified: List[ScoredCandidate],
        high_priority: List[ScoredCandidate],
        medium_priority: List[ScoredCandidate],
    ) -> dict:
        """构建统计摘要卡片 - 紧凑版"""
        avg_score = sum(c.total_score for c in qualified) / len(qualified)

        # 统计数据源分布 - 简化为单行
        source_counts = {}
        for c in qualified:
            source_counts[c.source] = source_counts.get(c.source, 0) + 1
        source_items = [
            f"{self._format_source_name(src)} {cnt}"
            for src, cnt in sorted(source_counts.items(), key=lambda x: x[1], reverse=True)
        ]
        source_breakdown = "  |  ".join(source_items)

        # 统计分数分布 - 合并为单行
        excellent = len([c for c in qualified if c.total_score >= 9.0])
        good = len([c for c in qualified if 8.0 <= c.total_score < 9.0])
        medium = len([c for c in qualified if 7.0 <= c.total_score < 8.0])
        pass_level = len([c for c in qualified if 6.0 <= c.total_score < 7.0])

        # 质量评级
        if avg_score >= constants.QUALITY_EXCELLENT_THRESHOLD:
            quality_indicator = "优质"
        elif avg_score >= constants.QUALITY_GOOD_THRESHOLD:
            quality_indicator = "良好"
        elif avg_score >= constants.QUALITY_PASS_THRESHOLD:
            quality_indicator = "合格"
        else:
            quality_indicator = "一般"

        # 紧凑排版
        content = (
            f"**{datetime.now().strftime('%Y-%m-%d %H:%M')}**  |  "
            f"共 {len(qualified)} 条候选  |  "
            f"平均 {avg_score:.1f}分 ({quality_indicator})\n\n"
            f"**优先级**: 高 {len(high_priority)} 条 (已详细卡片)  |  "
            f"中 {len(medium_priority)} 条 (已摘要)\n\n"
            f"**分数分布**: 9.0+ {excellent}  |  8.0~8.9 {good}  |  7.0~7.9 {medium}  |  6.0~6.9 {pass_level}\n\n"
            f"**数据源**: {source_breakdown}\n\n"
            f"[查看飞书表格]({constants.FEISHU_BENCH_TABLE_URL})"
        )

        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": "📊 采集汇总"},
                    "template": "blue",
                },
                "elements": [
                    {"tag": "div", "text": {"tag": "lark_md", "content": content}},
                ],
            },
        }

    def _build_card(self, title: str, candidate: ScoredCandidate) -> dict:
        """构建高优先级候选卡片 - 专业简洁版"""
        priority_label = {
            "high": "高优先级",
            "medium": "中优先级",
            "low": "低优先级",
        }.get(candidate.priority, "低优先级")

        source_name = self._format_source_name(candidate.source)

        actions = [
            {
                "tag": "button",
                "text": {"content": "查看详情", "tag": "plain_text"},
                "url": candidate.url,
                "type": "primary",
            },
            {
                "tag": "button",
                "text": {"content": "飞书表格", "tag": "plain_text"},
                "url": constants.FEISHU_BENCH_TABLE_URL,
                "type": "default",
            },
        ]

        # 如果有GitHub链接，添加GitHub按钮
        if candidate.github_url and candidate.github_url != candidate.url:
            actions.insert(
                1,
                {
                    "tag": "button",
                    "text": {"content": "GitHub", "tag": "plain_text"},
                    "url": candidate.github_url,
                    "type": "default",
                },
            )

        # 构建卡片元素：标题 → 图片 → 内容
        title_content = f"**{candidate.title[:constants.TITLE_TRUNCATE_LONG]}**"

        detail_content = (
            f"综合评分: **{candidate.total_score:.1f}** / 10  |  优先级: **{priority_label}**\n\n"
            "**评分细项**\n"
            f"活跃度 {candidate.activity_score:.1f}  |  "
            f"可复现性 {candidate.reproducibility_score:.1f}  |  "
            f"许可合规 {candidate.license_score:.1f}  |  "
            f"任务新颖性 {candidate.novelty_score:.1f}  |  "
            f"MGX适配度 {candidate.relevance_score:.1f}\n\n"
            f"**来源**: {source_name}\n\n"
            f"**评分依据**\n{candidate.reasoning}"
        )

        elements = []
        # 1. 显示标题
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": title_content}})

        # 2. 如果有图片，在标题下方显示
        if candidate.hero_image_key:
            elements.append(
                {
                    "tag": "img",
                    "img_key": candidate.hero_image_key,
                    "alt": {
                        "tag": "plain_text",
                        "content": f"{candidate.title} 预览图",
                    },
                    "preview": True,
                    "scale_type": "crop_center",
                    "size": "large",
                }
            )
            elements.append({"tag": "hr"})

        # 3. 显示详细内容
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": detail_content}})
        elements.append({"tag": "hr"})
        elements.append({"tag": "action", "actions": actions})
        elements.append(
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": f"BenchScope 情报员 | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                    }
                ],
            }
        )

        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "red" if candidate.priority == "high" else "blue",
                },
                "elements": elements,
            },
        }

    async def _send_webhook(self, payload: dict) -> None:
        """发送Webhook，支持签名验证

        飞书Webhook签名算法:
        1. 拼接字符串: timestamp + "\\n" + secret
        2. 使用HMAC-SHA256计算签名
        3. Base64编码签名结果

        文档: https://open.feishu.cn/document/ukTMukTMukTM/ucTM5YjL3ETO24yNxkjN
        """
        # 如果配置了webhook_secret，添加签名
        if self.settings.feishu.webhook_secret:
            timestamp = int(time.time())
            sign = self._generate_signature(
                timestamp, self.settings.feishu.webhook_secret
            )
            payload["timestamp"] = str(timestamp)
            payload["sign"] = sign
            logger.debug("Webhook签名已添加: timestamp=%s", timestamp)

        if not self.webhook_url:
            raise RuntimeError("未配置飞书Webhook URL，无法发送通知")

        async with httpx.AsyncClient(timeout=constants.HTTP_CLIENT_TIMEOUT) as client:
            resp = await client.post(self.webhook_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"飞书Webhook返回错误: {data}")
            if payload.get("msg_type") == "interactive":
                logger.info("✅ 飞书卡片推送成功")
            else:
                logger.info("✅ 飞书文本推送成功")

    def _generate_signature(self, timestamp: int, secret: str) -> str:
        """生成飞书Webhook签名

        Args:
            timestamp: Unix时间戳（秒）
            secret: Webhook签名密钥

        Returns:
            Base64编码的HMAC-SHA256签名
        """
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")
