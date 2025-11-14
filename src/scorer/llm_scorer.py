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
                        "content": """你是一名AI Benchmark评审专家,负责严格识别和评估真正的Benchmark项目。

**什么是真正的Benchmark（必须同时满足以下4项）**:
1. ✅ 明确的评测任务定义（如代码生成、问答、推理、Agent规划）
2. ✅ 标准化测试数据集（test set/eval set，不是demo数据）
3. ✅ 明确的评估指标（Accuracy/F1/BLEU/Pass@k/Success Rate等）
4. ✅ 基准结果（baseline performance，如GPT-4得分X%）

**不是Benchmark的项目类型（必须严格排除）**:
- ❌ Awesome lists / 资源汇总 / curated collections
- ❌ 工具/库/框架（如Agent框架、API wrapper、工具集）
- ❌ 教程/课程/学习资料（如system design guides）
- ❌ Demo/Example项目（仅展示功能，无标准评测）
- ❌ 数据集（仅提供数据，无评测任务和指标）

MGX技术背景:
- MGX (https://mgx.dev): 多智能体协作框架,专注Vibe Coding(AI原生编程)
- 基于MetaGPT开源框架构建
- 核心技术方向: 多智能体协作与编排、代码生成与理解、工具调用与任务自动化、智能工作流设计

MGX适配度评估标准(relevance_score) - **仅对真Benchmark评分**:

**真正的Benchmark项目**:
1. 直接评测多智能体系统性能 → 9-10分 (如AgentBench, WebArena)
2. 代码生成/理解Benchmark → 7-9分 (如HumanEval, MBPP, CodeXGLUE)
3. 任务规划/工具使用Benchmark → 6-8分 (如ToolBench, API-Bank)
4. Agent推理/决策Benchmark → 6-8分 (如GSM8K, MATH, ALFWorld)
5. 通用AI能力Benchmark → 3-5分 (如MMLU, HellaSwag)
6. 完全无关领域Benchmark → 0-2分 (如图像分类ImageNet, 语音识别LibriSpeech)

**非Benchmark项目（工具/教程/资源汇总）**:
- 无论stars多高，relevance_score必须≤2分
- 示例: system-design-primer (stars虽高但是学习资源) → relevance=1分
- 示例: awesome-chatgpt-prompts (资源汇总) → relevance=1分
- 示例: langchain (工具库) → relevance=2分

**核心判断逻辑**:
- 首先判断"是否是真Benchmark"（有评测任务+数据集+指标+基准结果）
- 如果不是Benchmark → relevance_score自动≤2分，reasoning必须明确说明"不是Benchmark"
- 如果是真Benchmark → 再按MGX适配度打分

注意:
- 必须在reasoning中明确说明"是否是真正的Benchmark"
- 如果缺少评测任务/数据集/指标/基准结果中的任何一项，必须标注为"非标准Benchmark"并降低相关性评分""",
                    },
                    {"role": "user", "content": self._build_prompt(candidate)},
                ],
                temperature=0.2,
                max_tokens=constants.LLM_COMPLETION_MAX_TOKENS,  # 提升token上限确保reasoning更完整
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

**首要判断: 是否为真正的Benchmark?**
- 检查是否包含: 评测任务 + 测试数据集 + 评估指标 + 基准结果
- 如果是工具/教程/资源汇总 → relevance_score必须≤2分

评分维度:
1. 活跃度(activity_score): GitHub stars 与最近更新情况
2. 可复现性(reproducibility_score): 代码/数据/文档公开程度
3. 许可合规(license_score): MIT/Apache/BSD得分更高,未知/专有扣分
4. 任务新颖性(novelty_score): 是否提供全新 Benchmark 或方法
5. MGX适配度(relevance_score):
   - **真Benchmark**: 按多智能体/代码/工具场景相关度打分(0-10分)
   - **非Benchmark（工具/教程/资源汇总）**: 无论stars多高，必须≤2分

**重要**: reasoning字段必须详细、具体、基于事实数据，**最少250字**，格式要求:

【Benchmark类型判断】★ 新增必需部分 ★
- 明确说明"是真正的Benchmark"或"不是Benchmark（工具/教程/资源汇总）"
- 如果是真Benchmark: 列举评测任务、数据集、评估指标、基准结果
- 如果不是: 说明缺少哪些关键要素（如"无标准测试集"、"仅为工具库"）

【活跃度分析】
- 必须引用具体stars数量（如"GitHub 1,500+ stars"）
- 必须说明最近更新情况（如"近30天有X次提交"或"最后更新于X天前"）
- 评估社区活跃度和维护状态

【可复现性分析】
- 具体列举开源内容：代码仓库/数据集/评估脚本/技术文档
- 说明文档质量（如"包含详细README、API文档、使用示例"）
- 评估复现成本和门槛

【许可合规分析】
- 明确指出License类型（如"MIT License"、"Apache-2.0"）
- 说明是否适合商业使用
- 如果未知License，明确标注并扣分

【任务新颖性分析】
- 说明该项目的核心创新点或评测维度
- 对比已有同类Benchmark的差异（如"相比HumanEval增加了X维度"）
- 评估学术/工业价值

【MGX适配度分析】
- 如果是真Benchmark: 明确说明与多智能体协作/代码生成/工具使用的关联
- 如果不是Benchmark: 明确标注"非Benchmark项目，relevance_score设为1-2分"
- 列举具体评测维度（如"测试Agent规划能力"、"评估代码生成质量"）

**禁止使用模糊描述**:
- ❌ "GitHub stars较高" → ✅ "GitHub 1,500 stars"
- ❌ "近期有更新" → ✅ "最后更新于7天前，近30天有12次提交"
- ❌ "代码开源" → ✅ "代码仓库完全开源，包含训练脚本、评估代码和完整文档"
- ❌ "可能是工具" → ✅ "这是Agent框架工具，不是Benchmark，缺少标准测试集和评估指标"

请输出JSON,示例1（真Benchmark）:
{{
  "activity_score": 8.5,
  "reproducibility_score": 9.0,
  "license_score": 10.0,
  "novelty_score": 7.5,
  "relevance_score": 8.5,
  "reasoning": "【Benchmark判断】✅ 真正的Benchmark - 评测多智能体代码生成能力，包含标准测试集（153道编程题）、明确指标（Pass@k）和基准结果（GPT-4得分67%）；【活跃度】GitHub 2,400 stars，近30天有15次提交，社区活跃；【可复现性】代码完全开源，包含评估脚本、数据集和详细文档；【许可合规】MIT License，适合商业使用；【新颖性】首个多Agent协作编程benchmark，填补该领域空白；【MGX适配度】直接评测多Agent代码生成，与MGX核心场景高度匹配"
}}

示例2（非Benchmark - 工具库）:
{{
  "activity_score": 9.0,
  "reproducibility_score": 8.0,
  "license_score": 10.0,
  "novelty_score": 6.0,
  "relevance_score": 2.0,
  "reasoning": "【Benchmark判断】❌ 不是Benchmark - 这是Agent开发框架/工具库，缺少标准评测任务、测试数据集和评估指标；【活跃度】GitHub 15,000 stars，近30天有50+提交，维护积极；【可复现性】代码开源+详细文档+示例代码；【许可合规】MIT License；【新颖性】提供便捷的Agent开发工具；【MGX适配度】虽然与Agent相关，但本身是工具不是Benchmark，relevance_score设为2分"
}}

示例3（非Benchmark - 资源汇总）:
{{
  "activity_score": 7.0,
  "reproducibility_score": 3.0,
  "license_score": 8.0,
  "novelty_score": 2.0,
  "relevance_score": 1.0,
  "reasoning": "【Benchmark判断】❌ 不是Benchmark - awesome-list资源汇总，仅收集链接，无评测任务/数据集/指标/基准结果；【活跃度】GitHub 8,000 stars，近30天有5次提交；【可复现性】无代码实现，仅为链接集合；【许可合规】CC0-1.0 License；【新颖性】资源整理无创新性；【MGX适配度】虽整理AI资源，但本质是列表不是Benchmark，relevance_score设为1分"
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
