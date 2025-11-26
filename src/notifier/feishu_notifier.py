"""飞书Webhook通知"""

from __future__ import annotations

import asyncio
import base64
import hmac
import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import List, Optional

import httpx

from src.common import constants
from src.common.url_utils import canonicalize_url
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

        # 预过滤：相关性、时间窗、任务领域
        candidates = self._prefilter_for_push(candidates)
        if not candidates:
            logger.info("预过滤后无候选可推送")
            return

        if not constants.ENABLE_SMART_PUSH_STRATEGY:
            qualified = [
                c for c in candidates if c.total_score >= constants.MIN_TOTAL_SCORE
            ]
            if not qualified:
                logger.info("无高分候选,跳过通知")
                return
            high_priority = [c for c in qualified if c.priority == "high"]
            medium_priority = [c for c in qualified if c.priority == "medium"]
            low_priority = [c for c in qualified if c.priority == "low"]
        else:
            high_priority, medium_priority, low_priority = self._smart_filter_candidates(
                candidates
            )

        if not high_priority and not medium_priority:
            logger.info("智能推送策略下无可推送候选")
            return

        covered_domains = self._collect_domains(high_priority + medium_priority)

        # 1. 推送所有高优先级卡片
        for candidate in high_priority:
            await self.send_card("🔥 发现高质量Benchmark候选", candidate)
            await asyncio.sleep(constants.FEISHU_RATE_LIMIT_DELAY)

        # 2. 推送中优先级摘要 (新增)
        if medium_priority:
            await self._send_medium_priority_summary(
                medium_priority, low_priority, covered_domains
            )
            await asyncio.sleep(constants.FEISHU_RATE_LIMIT_DELAY)

        # 3. 推送统计摘要卡片 (支持markdown)
        summary_candidates = self._dedup_by_url(high_priority + medium_priority)
        summary_card = self._build_summary_card(
            summary_candidates, high_priority, medium_priority
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

    @staticmethod
    def _format_institution(candidate: ScoredCandidate) -> str:
        """格式化机构/作者信息，保持卡片信息完整"""

        # GitHub通常无机构信息，避免展示“机构: 未知”
        if candidate.source == "github" and not candidate.raw_institutions:
            return ""

        # 优先使用原始机构字段（论文类数据更可靠）
        if candidate.raw_institutions:
            institutions = candidate.raw_institutions
            if len(institutions) > 50:
                institutions = institutions[:47] + "..."
            return f"机构: {institutions}"

        # 退化使用作者列表的前两位，避免过长
        if candidate.authors:
            if len(candidate.authors) == 1:
                author_text = candidate.authors[0]
            elif len(candidate.authors) == 2:
                author_text = f"{candidate.authors[0]}, {candidate.authors[1]}"
            else:
                author_text = f"{candidate.authors[0]}, {candidate.authors[1]} et al."
            if len(author_text) > 50:
                author_text = author_text[:47] + "..."
            return f"作者: {author_text}"

        # 无信息时返回占位符
        return "机构: 未知"

    @staticmethod
    def _format_stars(stars: Optional[int]) -> str:
        """格式化GitHub stars数，避免卡片溢出"""

        if not stars:
            return "Stars: --"
        if stars >= 1000:
            return f"Stars: {stars/1000:.1f}k"
        return f"Stars: {stars}"

    @staticmethod
    def _canonical_url(candidate: ScoredCandidate) -> str:
        """统一候选的唯一键，优先使用URL。"""

        primary = candidate.url or candidate.github_url or ""
        return canonicalize_url(primary) or primary

    @staticmethod
    def _age_days(candidate: ScoredCandidate) -> int:
        """计算候选距今天数，缺失日期视为远期。"""

        if not candidate.publish_date:
            return 10**6
        publish_dt = candidate.publish_date
        if publish_dt.tzinfo is None:
            publish_dt = publish_dt.replace(tzinfo=timezone.utc)
        return (datetime.now(tz=publish_dt.tzinfo) - publish_dt).days

    def _collect_domains(self, candidates: List[ScoredCandidate]) -> set[str]:
        """收集已有任务领域，便于补位决策。"""

        domains: set[str] = set()
        for cand in candidates:
            domain = (cand.task_domain or constants.DEFAULT_TASK_DOMAIN).strip()
            if domain:
                domains.add(domain)
        return domains

    def _dedup_by_url(self, items: List[ScoredCandidate]) -> List[ScoredCandidate]:
        """按URL去重，保持顺序。"""

        seen: set[str] = set()
        result: list[ScoredCandidate] = []
        for cand in items:
            key = self._canonical_url(cand)
            if key in seen:
                continue
            seen.add(key)
            result.append(cand)
        return result

    @staticmethod
    def _primary_link(candidate: ScoredCandidate) -> str:
        """选择点击跳转的主链接。

        优先：arXiv等论文源用 paper_url，其次 url；GitHub 源用 url；兜底 github_url。
        """

        if candidate.source == "arxiv" and candidate.paper_url:
            return candidate.paper_url
        if candidate.url:
            return candidate.url
        if candidate.github_url:
            return candidate.github_url
        return ""

    def _prefilter_for_push(self, candidates: List[ScoredCandidate]) -> List[ScoredCandidate]:
        """推送前过滤：最新优先、相关性兜底、任务域白名单、总量限额。

        规则：
        - 核心任务域放宽：任务域∈{Coding,Backend,WebDev,GUI} 且 total_score>=5.0 → 保留
        - 最新高相关/高新颖直通：
          * ≤7天 且 relevance>=7.0 且 核心域 → 保留（忽略总分）
          * ≤14天 且 novelty>=8.0 且 核心域 → 保留
        - 基础过滤：relevance_score < PUSH_RELEVANCE_FLOOR 直接丢弃
        - 发布超过 PUSH_MAX_AGE_DAYS，除非 total_score >= 8.0 才保留
        - 任务领域不在已知列表时，仅当 total_score>=8.0 且发布日期<=PUSH_MAX_AGE_DAYS
        - 按新鲜度优先排序，其次总分
        - 总量上限 PUSH_TOTAL_CAP
        """

        if not candidates:
            return []

        allowed_domains = set(constants.TASK_DOMAIN_OPTIONS)
        core_domains = {"Coding", "Backend", "WebDev", "GUI"}
        filtered: List[ScoredCandidate] = []

        for cand in candidates:
            # 相关性过滤
            if cand.relevance_score < constants.PUSH_RELEVANCE_FLOOR:
                continue

            # 时间过滤
            publish_dt = cand.publish_date
            age_days = None
            if publish_dt:
                if publish_dt.tzinfo is None:
                    publish_dt = publish_dt.replace(tzinfo=timezone.utc)
                age_days = (datetime.now(tz=publish_dt.tzinfo) - publish_dt).days
            domain = cand.task_domain or constants.DEFAULT_TASK_DOMAIN
            core_domain = domain in core_domains

            # 最新高相关/高新颖直通
            if age_days is not None:
                if age_days <= 7 and cand.relevance_score >= 7.0 and core_domain:
                    filtered.append(cand)
                    continue
                if age_days <= 14 and cand.novelty_score >= 8.0 and core_domain:
                    filtered.append(cand)
                    continue

            # 核心域放宽阈值
            if core_domain and cand.total_score >= 5.0:
                filtered.append(cand)
                continue

            # 时间过滤
            if age_days is not None and age_days > constants.PUSH_MAX_AGE_DAYS:
                if cand.total_score < 8.0:
                    continue

            # 任务领域过滤
            if domain not in allowed_domains:
                if cand.total_score < 8.0:
                    continue

            filtered.append(cand)

        # 按新鲜度优先，其次分数
        def sort_key(c: ScoredCandidate) -> tuple[int, float]:
            age = self._age_days(c)
            return (age, -c.total_score)

        filtered = sorted(filtered, key=sort_key)

        # 总量上限
        if len(filtered) > constants.PUSH_TOTAL_CAP:
            filtered = filtered[: constants.PUSH_TOTAL_CAP]

        return filtered

    def _smart_filter_candidates(
        self, candidates: List[ScoredCandidate]
    ) -> tuple[List[ScoredCandidate], List[ScoredCandidate], List[ScoredCandidate]]:
        """按来源阈值、TopK与任务领域补位生成推送列表。"""

        if not candidates:
            return [], [], []

        high: list[ScoredCandidate] = []
        medium: list[ScoredCandidate] = []
        low: list[ScoredCandidate] = []

        for cand in candidates:
            score = cand.total_score
            if score >= 8.0:
                high.append(cand)
            elif score >= 6.0:
                medium.append(cand)
            else:
                low.append(cand)

        # 低分但满足来源阈值的候选提升至中优
        promoted: list[ScoredCandidate] = []
        for cand in list(low):
            source = (cand.source or "default").lower()
            threshold = constants.SOURCE_SCORE_THRESHOLDS.get(
                source, constants.SOURCE_SCORE_THRESHOLDS["default"]
            )
            if cand.total_score < threshold:
                continue
            if source == "arxiv" and cand.relevance_score < constants.ARXIV_MIN_RELEVANCE:
                continue
            promoted.append(cand)
            medium.append(cand)
            low.remove(cand)

        if promoted:
            logger.info("来源阈值提升 %d 条至中优", len(promoted))

        # 每来源 TopK 保底（最新优先，其次高分）
        source_groups: dict[str, list[ScoredCandidate]] = {}
        for cand in candidates:
            src = (cand.source or "default").lower()
            source_groups.setdefault(src, []).append(cand)

        medium_urls = {self._canonical_url(c) for c in medium}
        high_urls = {self._canonical_url(c) for c in high}

        for source, group in source_groups.items():
            topk = constants.PER_SOURCE_TOPK_PUSH.get(source, 0)
            if topk <= 0:
                continue
            sorted_group = sorted(
                group,
                key=lambda c: (self._age_days(c), -c.total_score),
            )
            picked = 0
            for cand in sorted_group:
                url_key = self._canonical_url(cand)
                if url_key in medium_urls or url_key in high_urls:
                    continue
                medium.append(cand)
                medium_urls.add(url_key)
                picked += 1
                if picked >= topk:
                    break

        # 任务领域补位：缺席领域从low中按新鲜度+分数补足
        if constants.LOW_PICK_BY_TASK_ENABLED:
            present_domains = self._collect_domains(high + medium)
            priority_domains = [
                "Coding",
                "Backend",
                "WebDev",
                "GUI",
                "ToolUse",
                "Collaboration",
                "LLM/AgentOps",
                "Reasoning",
            ]
            low_sorted = sorted(
                low,
                key=lambda c: (self._age_days(c), -c.total_score),
            )
            for domain in priority_domains:
                if domain in present_domains:
                    continue
                needed = constants.LOW_PICK_TASK_TOPK
                for cand in low_sorted:
                    if (cand.task_domain or constants.DEFAULT_TASK_DOMAIN) != domain:
                        continue
                    if cand.total_score < constants.LOW_PICK_SCORE_FLOOR:
                        continue
                    url_key = self._canonical_url(cand)
                    if url_key in medium_urls or url_key in high_urls:
                        continue
                    medium.append(cand)
                    medium_urls.add(url_key)
                    present_domains.add(domain)
                    needed -= 1
                    if needed <= 0:
                        break

        # 去重后返回
        medium = self._dedup_by_url(medium)
        high = self._dedup_by_url(high)
        low = [
            c
            for c in low
            if self._canonical_url(c) not in medium_urls
            and self._canonical_url(c) not in high_urls
        ]

        return high, medium, low

    async def _send_medium_priority_summary(
        self,
        candidates: List[ScoredCandidate],
        low_candidates: Optional[List[ScoredCandidate]] = None,
        covered_domains: Optional[set[str]] = None,
    ) -> None:
        """发送中优摘要：两分区（最新推荐 + 任务域补位）。"""
        if not candidates:
            return

        # 概览
        avg_medium_score = sum(c.total_score for c in candidates) / len(candidates)
        scores = [c.total_score for c in candidates]
        min_score = min(scores)
        max_score = max(scores)

        content_lines: list[str] = []
        content_lines.append(
            f"**候选概览**\n  总数: {len(candidates)} 条  │  平均分: {avg_medium_score:.1f} / 10  │  分数区间: {min_score:.1f} ~ {max_score:.1f}"
        )

        # 最新推荐（≤30天且已通过预过滤），按 时间↑ → 相关性↓ → 总分↓
        filtered_latest: list[ScoredCandidate] = []
        seen_titles: set[str] = set()

        for cand in sorted(
            candidates,
            key=lambda c: (
                self._age_days(c),
                -c.relevance_score,
                -c.total_score,
            ),
        ):
            # 终极时间过滤：无日期直接丢弃；超过30天且分<8丢弃
            age = self._age_days(cand)
            if age == 10**6:
                continue
            if age > constants.PUSH_MAX_AGE_DAYS and cand.total_score < 8.0:
                continue

            # 标题去重（忽略大小写和多余空格）
            norm_title = " ".join((cand.title or "").lower().split())
            if norm_title in seen_titles:
                continue
            seen_titles.add(norm_title)

            filtered_latest.append(cand)
            if len(filtered_latest) >= constants.MAIN_RECOMMENDATION_LIMIT:
                break

        main_list = filtered_latest
        content_lines.append("**最新推荐**")
        content_lines.extend(self._render_brief_items(main_list))

        # 任务域补位（如果核心域缺席，则从剩余候选或低优池补1条，无分数下限）
        task_fill_section = self._build_task_fill_section(
            main_list,
            (low_candidates if low_candidates is not None else []) + candidates,
            covered_domains,
            allow_any_score=True,
        )
        if task_fill_section:
            content_lines.append("**任务域补位**")
            content_lines.append(task_fill_section)

        content = "\n\n".join(content_lines) + "\n"

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

    def _build_low_pick_section(self, candidates: List[ScoredCandidate]) -> str:
        """从low队列挑选最新且相关的论文/数据集，保证曝光"""

        picks: list[str] = []
        per_source_limits = constants.FEISHU_LOW_PICK_PER_SOURCE

        grouped: dict[str, list[ScoredCandidate]] = {}
        for cand in candidates:
            if cand.priority != "low":
                continue
            source = (cand.source or "unknown").lower()
            if source not in per_source_limits:
                continue
            if cand.publish_date and (
                datetime.now() - cand.publish_date
            ).days > constants.PAPER_MAX_PUBLISH_DAYS_FOR_LOW_PICK:
                continue
            if cand.total_score < constants.PAPER_MIN_SCORE_FOR_LOW_PICK:
                continue
            if cand.relevance_score < constants.PAPER_MIN_RELEVANCE_FOR_LOW_PICK:
                continue
            grouped.setdefault(source, []).append(cand)

        for source, items in grouped.items():
            items = sorted(items, key=lambda x: x.total_score, reverse=True)
            limit = per_source_limits.get(source, 0)
            for cand in items[:limit]:
                title = (
                    cand.title[: constants.TITLE_TRUNCATE_MEDIUM] + "..."
                    if len(cand.title) > constants.TITLE_TRUNCATE_MEDIUM
                    else cand.title
                )
                source_name = self._format_source_name(cand.source)
                date_str = (
                    cand.publish_date.strftime("%Y-%m-%d") if cand.publish_date else "近期"
                )
                picks.append(
                    f"- {source_name}: {title} （MGX {cand.relevance_score:.1f}, {date_str}） [查看详情]({self._primary_link(cand)})"
                )

        return "\n".join(picks)

    def _render_brief_items(self, items: List[ScoredCandidate], tag: str | None = None) -> List[str]:
        """简洁行渲染，提升可扫读性。"""

        lines: list[str] = []
        for c in items:
            title = c.title or "(无标题)"
            source_name = self._format_source_name(c.source)
            domain = c.task_domain or constants.DEFAULT_TASK_DOMAIN
            age = self._age_days(c)
            tag_text = tag or ""
            labels = []
            if age <= 7:
                labels.append("New")
            if tag_text:
                labels.append(tag_text)
            label_str = "/".join(labels) if labels else ""

            date_str = c.publish_date.strftime("%Y-%m-%d") if c.publish_date else "近期"
            meta = f"[{source_name}] {domain}｜{c.total_score:.1f}分" + (f"｜{label_str}" if label_str else "") + f"｜{date_str}"
            subs = (
                f"相关 {c.relevance_score:.1f}｜新颖 {c.novelty_score:.1f}｜"
                f"活跃 {c.activity_score:.1f}｜复现 {c.reproducibility_score:.1f}"
            )

            lines.append(
                f"- **{title}**  \n  {meta}  \n  {subs}  [查看详情]({self._primary_link(c)})"
            )
        return lines

    def _build_task_fill_section(
        self,
        medium_candidates: List[ScoredCandidate],
        low_candidates: List[ScoredCandidate],
        covered_domains: Optional[set[str]] = None,
        allow_any_score: bool = False,
    ) -> str:
        """按任务领域补位，确保关键领域曝光。

        allow_any_score=True 时，不满足 LOW_PICK_SCORE_FLOOR 也可用最新候选兜底。
        """

        if not constants.LOW_PICK_BY_TASK_ENABLED:
            return ""

        present = covered_domains or self._collect_domains(medium_candidates)
        priority_domains = list(constants.CORE_DOMAINS)

        lines: list[str] = []
        sorted_pool = sorted(
            low_candidates,
            key=lambda c: (self._age_days(c), -c.total_score),
        )

        missing_domains: list[str] = []
        for domain in priority_domains:
            if domain in present:
                continue
            picked = 0
            for cand in sorted_pool:
                cand_domain = cand.task_domain or constants.DEFAULT_TASK_DOMAIN
                if cand_domain != domain:
                    continue
                if not allow_any_score and cand.total_score < constants.TASK_FILL_MIN_SCORE:
                    continue
                date_str = (
                    cand.publish_date.strftime("%Y-%m-%d")
                    if cand.publish_date
                    else "近期"
                )
                title = cand.title or "(无标题)"
                source_name = self._format_source_name(cand.source)
                lines.append(
                    f"- {domain}: **{title}**｜{cand.total_score:.1f}分｜{date_str}｜{source_name}  [查看详情]({self._primary_link(cand)})"
                )
                present.add(domain)
                picked += 1
                if picked >= constants.TASK_FILL_PER_DOMAIN_LIMIT:
                    break
            if picked == 0:
                missing_domains.append(domain)

        return "\n".join(lines)

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
                "url": self._primary_link(candidate),
                "type": "primary",
            },
            {
                "tag": "button",
                "text": {"content": "飞书表格", "tag": "plain_text"},
                "url": constants.FEISHU_BENCH_TABLE_URL,
                "type": "default",
            },
        ]

        # 构建卡片元素：标题 → 内容
        title_content = f"**{candidate.title[:constants.TITLE_TRUNCATE_LONG]}**"

        institution = self._format_institution(candidate)
        stars_text = (
            self._format_stars(candidate.github_stars)
            if candidate.source == "github"
            else ""
        )
        source_line_parts = [f"**来源**: {source_name}"]
        if institution:
            source_line_parts.append(institution)
        if stars_text:
            source_line_parts.append(stars_text)
        source_line = "  |  ".join(source_line_parts)

        detail_content = (
            f"综合评分: **{candidate.total_score:.1f}** / 10  |  优先级: **{priority_label}**\n\n"
            "**评分细项**\n"
            f"活跃度 {candidate.activity_score:.1f}  |  "
            f"可复现性 {candidate.reproducibility_score:.1f}  |  "
            f"许可合规 {candidate.license_score:.1f}  |  "
            f"任务新颖性 {candidate.novelty_score:.1f}  |  "
            f"MGX适配度 {candidate.relevance_score:.1f}\n\n"
            f"{source_line}\n\n"
            f"**评分依据**\n{candidate.reasoning}"
        )

        elements = []
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": title_content}})
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
