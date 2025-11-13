"""LLM评分引擎"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

import redis.asyncio as redis
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from src.common import constants
from src.config import get_settings
from src.models import RawCandidate, ScoredCandidate

logger = logging.getLogger(__name__)


class LLMScorer:
    """使用LLM完成Phase 2评分的引擎"""

    def __init__(self) -> None:
        self.settings = get_settings()
        api_key = self.settings.openai.api_key
        base_url = self.settings.openai.base_url
        self.client: Optional[AsyncOpenAI] = None
        if api_key:
            self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.redis_client: Optional[redis.Redis] = None

    async def __aenter__(self) -> "LLMScorer":
        try:
            self.redis_client = redis.from_url(
                self.settings.redis.url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self.redis_client.ping()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis连接失败,将不使用缓存: %s", exc)
            self.redis_client = None
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.redis_client:
            await self.redis_client.aclose()
            self.redis_client = None

    def _cache_key(self, candidate: RawCandidate) -> str:
        key_str = f"{candidate.title}:{candidate.url}"
        digest = hashlib.md5(key_str.encode(), usedforsecurity=False).hexdigest()  # noqa: S324
        return f"{constants.REDIS_KEY_PREFIX}score:{digest}"

    async def _get_cached_score(self, candidate: RawCandidate) -> Optional[Dict[str, Any]]:
        if not self.redis_client:
            return None
        try:
            cached = await self.redis_client.get(self._cache_key(candidate))
            if cached:
                logger.debug("评分缓存命中: %s", candidate.title[:50])
                return json.loads(cached)
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取Redis失败: %s", exc)
        return None

    async def _set_cached_score(self, candidate: RawCandidate, payload: Dict[str, Any]) -> None:
        if not self.redis_client:
            return
        try:
            await self.redis_client.setex(
                self._cache_key(candidate),
                constants.REDIS_TTL_DAYS * 86400,
                json.dumps(payload),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("写入Redis失败: %s", exc)

    @retry(
        stop=stop_after_attempt(constants.LLM_MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _call_llm(self, candidate: RawCandidate) -> Dict[str, Any]:
        if not self.client:
            raise RuntimeError("未配置OpenAI接口,无法调用LLM")

        response = await asyncio.wait_for(
            self.client.chat.completions.create(
                model=self.settings.openai.model or constants.LLM_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": """你是一名AI Benchmark评审专家,负责严格量化候选项目。

MGX与DeepWisdom背景:
- MGX (https://mgx.dev): 多智能体协作框架,专注Vibe Coding(AI原生编程)
- DeepWisdom: 基础智能体技术公司,2025年获蚂蚁集团等数亿元投资
- 核心开源项目: MetaGPT (GitHub 15万+ stars) + OpenManus
- 团队背景: Google/Anthropic/字节/腾讯/阿里/CMU/Berkeley,含Claude Code/MCP核心开发者
- 核心技术方向: 多智能体协作、Vibe Coding、任务自动化、智能工作流

MGX适配度评估标准(relevance_score):
1. 直接评测多智能体系统性能 → 9-10分 (如Agent协作benchmark)
2. 涉及代码生成/理解能力 → 7-9分 (如HumanEval, MBPP)
3. 包含任务规划/工具使用 → 6-8分 (如API调用, 文件操作)
4. 评估Agent推理/决策能力 → 6-8分 (如复杂问题求解)
5. 通用AI能力评测 → 4-6分 (如MMLU, HellaSwag)
6. 纯学习资源/教程 → 1-3分 (如awesome lists, system design guides)
7. 完全无关领域 → 0-2分 (如图像分类, 语音识别)

注意:
- system-design-primer虽然stars很高,但与AI/Coding无直接关联 → relevance_score应为1-2分
- MetaGPT相关项目/Agent框架/Coding benchmark → relevance_score应为8-10分""",
                    },
                    {"role": "user", "content": self._build_prompt(candidate)},
                ],
                temperature=0.2,
                max_tokens=400,
            ),
            timeout=constants.LLM_TIMEOUT_SECONDS,
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM未返回内容")

        # 调试日志：输出LLM原始响应
        logger.debug(f"LLM原始响应 (前500字符): {content[:500]}")

        # 提取JSON：处理markdown代码块包裹的情况
        json_str = content.strip()
        if json_str.startswith("```"):
            # 去除markdown代码块标记
            lines = json_str.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]  # 去除开头的```json或```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]  # 去除结尾的```
            json_str = "\n".join(lines).strip()

        scores = json.loads(json_str)
        required = [
            "activity_score",
            "reproducibility_score",
            "license_score",
            "novelty_score",
            "relevance_score",
            "reasoning",
        ]
        for field in required:
            if field not in scores:
                raise ValueError(f"LLM响应缺少字段: {field}")
            if field != "reasoning":
                scores[field] = max(0.0, min(10.0, float(scores[field])))
        return scores

    def _build_prompt(self, candidate: RawCandidate) -> str:
        # 构建具体的数据上下文
        github_info = ""
        if candidate.github_url:
            github_info = f"\nGitHub链接: {candidate.github_url}"
            if candidate.github_stars is not None:
                github_info += f"\nGitHub Stars: {candidate.github_stars:,}"

        # 提取具体的技术信息
        task_info = f"\n任务类型: {candidate.task_type}" if candidate.task_type else ""
        license_info = f"\nLicense: {candidate.license_type}" if candidate.license_type else ""

        return f"""请对以下AI Benchmark候选进行评分(0-10分,可保留一位小数)。

候选信息:
- 标题: {candidate.title}
- 来源: {candidate.source}
- URL: {candidate.url}
- 摘要: {(candidate.abstract or 'N/A')[:500]}
{github_info}{task_info}{license_info}

评分维度:
1. 活跃度(activity_score): GitHub stars 与最近更新情况
2. 可复现性(reproducibility_score): 代码/数据/文档公开程度
3. 许可合规(license_score): MIT/Apache/BSD得分更高,未知/专有扣分
4. 任务新颖性(novelty_score): 是否提供全新 Benchmark 或方法
5. MGX适配度(relevance_score): 是否贴合多智能体/代码/工具使用场景

**重要**: reasoning字段必须**基于上述具体数据**给出判断,格式如下:
【活跃度】引用具体stars数字或更新时间；【可复现性】具体说明哪些资源开源(代码/数据/文档)；【许可合规】明确指出License类型；【新颖性】对比已有方法的具体区别；【MGX适配度】明确说明与多智能体/代码生成的关联。
**禁止使用**"GitHub stars较高"、"近期有更新"等模糊描述,必须用具体数字和事实。

请输出JSON,示例:
{{
  "activity_score": 8.5,
  "reproducibility_score": 9.0,
  "license_score": 10.0,
  "novelty_score": 7.0,
  "relevance_score": 8.0,
  "reasoning": "【活跃度】GitHub 326,329 stars，近30天有10+commits，社区活跃度极高；【可复现性】代码完全开源+详细文档+多语言支持，复现成本低；【许可合规】MIT License，符合商业使用；【新颖性】系统设计学习资源集合，非新Benchmark，复用已有知识；【MGX适配度】与多智能体直接相关性低，但对系统架构设计有参考价值"
}}
"""

    async def score(self, candidate: RawCandidate) -> ScoredCandidate:
        cached = await self._get_cached_score(candidate)
        if cached:
            scores = cached
        else:
            if not self.client:
                logger.warning("OpenAI未配置,使用规则兜底评分")
                scores = self._fallback_score(candidate)
            else:
                try:
                    scores = await self._call_llm(candidate)
                except Exception as exc:  # noqa: BLE001
                    logger.error("LLM评分失败,使用兜底: %s", exc)
                    scores = self._fallback_score(candidate)
                else:
                    await self._set_cached_score(candidate, scores)

        return ScoredCandidate(
            title=candidate.title,
            url=candidate.url,
            source=candidate.source,
            abstract=candidate.abstract,
            authors=candidate.authors,
            publish_date=candidate.publish_date,
            github_stars=candidate.github_stars,
            github_url=candidate.github_url,
            dataset_url=candidate.dataset_url,
            raw_metadata=candidate.raw_metadata,
            # Phase 6新增字段：从RawCandidate复制到ScoredCandidate
            paper_url=candidate.paper_url,
            task_type=candidate.task_type,
            license_type=candidate.license_type,
            evaluation_metrics=candidate.evaluation_metrics,
            reproduction_script_url=candidate.reproduction_script_url,
            # 评分维度
            activity_score=scores["activity_score"],
            reproducibility_score=scores["reproducibility_score"],
            license_score=scores["license_score"],
            novelty_score=scores["novelty_score"],
            relevance_score=scores["relevance_score"],
            reasoning=scores.get("reasoning", ""),
        )

    def _fallback_score(self, candidate: RawCandidate) -> Dict[str, Any]:
        activity = 5.0
        if candidate.github_stars:
            if candidate.github_stars >= 1000:
                activity = 9.0
            elif candidate.github_stars >= 500:
                activity = 7.5
            elif candidate.github_stars >= 100:
                activity = 6.0

        reproducibility = 3.0
        if candidate.github_url:
            reproducibility += 3.0
        if candidate.dataset_url:
            reproducibility += 3.0

        return {
            "activity_score": activity,
            "reproducibility_score": min(10.0, reproducibility),
            "license_score": 5.0,
            "novelty_score": 5.0,
            "relevance_score": 5.0,
            "reasoning": "规则兜底评分(LLM不可用)",
        }

    async def score_batch(self, candidates: List[RawCandidate]) -> List[ScoredCandidate]:
        if not candidates:
            return []

        tasks = [self.score(candidate) for candidate in candidates]
        results = await asyncio.gather(*tasks)
        logger.info("批量评分完成: %d条", len(results))
        return list(results)
