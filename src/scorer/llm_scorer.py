"""全LLM统一评分引擎 - Phase 9重构版

完全基于LLM的单次调用统一评分架构，取代硬编码规则和多次调用，追求最高数据质量和可解释性。

关键特性：
- 单次LLM调用返回全部26个字段
- 4000+ token超详细prompt，包含MGX场景定义和评分标准
- 强制字段完成，不允许N/A返回
- 每个维度150+字详细推理，后端专项200+字详细推理
- 总推理字数≥1200字符，确保完整可解释性
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any, Awaitable, Dict, List, Optional, Tuple, cast

import redis.asyncio as redis
from redis.asyncio import Redis as AsyncRedis
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from tenacity import retry, stop_after_attempt, wait_exponential

from src.common import clean_summary_text, constants
from src.config import get_settings
from src.models import RawCandidate, ScoredCandidate

logger = logging.getLogger(__name__)

REASONING_FIELD_ORDER = [
    "activity_reasoning",
    "reproducibility_reasoning",
    "license_reasoning",
    "novelty_reasoning",
    "relevance_reasoning",
    "backend_mgx_reasoning",
    "backend_engineering_reasoning",
    "overall_reasoning",
]

REASONING_FIELD_LABELS = {
    "activity_reasoning": "activity_reasoning（活跃度推理）",
    "reproducibility_reasoning": "reproducibility_reasoning（可复现性推理）",
    "license_reasoning": "license_reasoning（许可推理）",
    "novelty_reasoning": "novelty_reasoning（新颖性推理）",
    "relevance_reasoning": "relevance_reasoning（MGX相关性推理）",
    "backend_mgx_reasoning": "backend_mgx_reasoning（后端MGX相关性推理）",
    "backend_engineering_reasoning": "backend_engineering_reasoning（后端工程价值推理）",
    "overall_reasoning": "overall_reasoning（综合推理）",
}


# ==================== 全LLM统一评分Prompt ====================
# 这是一个4000+ token的超详细prompt，涵盖MGX场景定义、评分标准、推理要求
UNIFIED_SCORING_PROMPT_TEMPLATE = """你是BenchScope的Benchmark情报分析专家，负责为MGX多智能体协作框架评估Benchmark候选项。

=== 第1部分：候选基础信息 ===
标题: {title}
来源: {source}
URL: {url}
摘要/README（截断）: {abstract}
GitHub Stars: {github_stars}
发布日期: {publish_date}
GitHub URL: {github_url}
数据集URL: {dataset_url}
论文URL: {paper_url}
许可证（初步识别）: {license_type}
任务类型（初步识别）: {task_type}

=== 第2部分：MGX场景定义 ===
MGX是一个AI原生的多智能体协作框架（Vibe Coding），专注以下领域：

【P0优先级 - 核心场景】（relevance_score建议 8-10分）
1. Coding: 代码生成、补全、调试、重构、单元测试、代码理解
2. GUI/App: GUI自动化、桌面应用交互、手机App自动化、UI测试
3. WebDev: Web开发、前端组件、后端API、全栈应用生成
4. Backend: 后端性能优化、数据库设计、API设计、分布式系统

【P1优先级 - 高价值辅助】（relevance_score建议 6-8分）
5. ToolUse: 外部工具调用、API集成、函数调用、工具链编排
6. Collaboration: 多Agent协作、任务分工、通信协议、团队编程
7. LLM/AgentOps: Agent系统运维、监控、调试、性能优化

【P2优先级 - 支撑场景】（relevance_score建议 4-6分）
8. Reasoning: 逻辑推理、数学解题、因果分析、复杂决策
9. DeepResearch: 文献综述、数据分析、科研助手、知识图谱

【Other - 低相关】（relevance_score建议 ≤3分）
10. 纯NLP/视觉/语音任务（无Agent或代码关联）
11. 理论研究（无实际工程应用）
12. 与MGX场景完全无关的领域

=== 第3部分：5维评分任务 ===
你必须对以下5个维度给出0-10分的量化评分，并为每个维度提供**至少150字符**的详细推理。

【维度1: 活跃度 activity_score】
评分标准：
- 10分: GitHub >5000 stars, 近30天有提交, 活跃社区
- 8-9分: 1000-5000 stars, 近60天有提交, 有PR讨论
- 6-7分: 100-1000 stars, 近90天有提交, 有基础维护
- 4-5分: 10-100 stars, 或90天内无更新但项目完整
- 2-3分: <10 stars, 或长期停更, 或仅论文无代码
- 0-1分: 链接失效, 或明显废弃项目

推理要求（activity_reasoning, **必须≥150字符，建议写到180+字符**）：
- 明确说明GitHub stars数量、最后一次commit时间和contributor活跃度（给出具体数字/日期）
- 分析PR/Issue数量、讨论质量以及社区治理模式，对MGX的稳定维护有何影响
- 如果只有论文或私有仓库，解释缺乏代码对复现/维护的风险
- 最后一两句话要总结MGX是否应采纳，以及活跃度对技术债的影响
- **字符计数示例**："该候选项来自GitHub，拥有1200+ stars，说明有一定的社区关注度。最近30天内有5次提交，表明项目仍在活跃维护中。PR讨论较活跃，有15个open issues正在被处理，社区参与度良好。这种活跃度适合MGX采纳，因为持续维护意味着更少技术债和更好的兼容性。"（≈180字符）

【维度2: 可复现性 reproducibility_score】
评分标准：
- 10分: 开源代码+公开数据集+评估脚本+清晰文档+基准结果
- 8-9分: 开源代码+公开数据集+部分脚本+基本文档
- 6-7分: 开源代码+说明如何获取数据+文档较完整
- 4-5分: 仅开源代码, 或仅数据集, 文档不全
- 2-3分: 仅论文描述, 无代码或数据集
- 0-1分: 完全闭源, 或商业许可严格限制使用

推理要求（reproducibility_reasoning, **必须≥150字符，建议写到180+字符**）：
- 逐条描述代码仓库、数据集、评估脚本、复现实验文档是否开源，补充对应链接或字段
- 说明复现所需的算力/依赖（GPU规格、API密钥、私有数据申请流程等）
- 评估嵌入MGX流水线的工作量，举例需要编写哪些Agent工具或适配器
- 如果存在复现障碍（缺数据/缺脚本/需昂贵资源），必须指出并解释风险
- **字符计数示例**："代码与评估脚本均在GitHub公开，并附有Dockerfile方便还原环境。数据集通过Hugging Face下载，无需审批但体积达80GB，需要具备A100×2的算力才能重现作者报告的成绩。README列出逐步命令，但缺乏自动化验证脚本，MGX需要额外编写任务编排器来驱动评估。"（≈190字符）

【维度3: 许可合规 license_score】
评分标准：
- 10分: MIT, Apache-2.0, BSD (商业友好，无传染性)
- 8-9分: Apache-2.0 with LLVM Exception (基本商业友好)
- 6-7分: GPL-3.0, AGPL-3.0 (强传染性，需谨慎)
- 4-5分: CC-BY, CC-BY-SA (数据集常用，代码需评估)
- 2-3分: 自定义许可, 研究用途only, 商业需授权
- 0-1分: 完全闭源, 或明确禁止商业使用

推理要求（license_reasoning, **必须≥150字符，建议写到180+字符**）：
- 说明许可证来源（GitHub API、LICENSE文件、论文脚注等），若缺失需记录查证过程
- 分析许可证条款对商业化、再分发、衍生作品的限制，指出是否存在传染性
- 若为未知/自定义许可，说明推断理由及必须的风控动作（如联系作者或限制用途）
- 总结MGX能否安全引用，并给出合规建议
- **字符计数示例**："仓库根目录提供MIT License，GitHub API同样标记为MIT，意味着可自由商用、修改与再分发且无传染条款。对于MGX而言，可直接集成其数据与脚本，不会强制开源自研组件。唯一需要注意的是依赖的第三方模型需单独确认许可。总体来看，该许可完全满足MGX的商业与合规需求。"（≈185字符）

【维度4: 新颖性 novelty_score】
评分标准：
- 10分: 2024+发布, 全新任务/指标, 补位MGX空白场景
- 8-9分: 2023-2024发布, 创新任务或指标, 与MGX高度相关
- 6-7分: 2022-2023发布, 经典任务但指标有创新
- 4-5分: 2020-2022发布, 成熟任务, 但可作为基线对比
- 2-3分: 2020年前发布, 非常传统的任务
- 0-1分: 完全过时, 或任务与MGX完全无关

推理要求（novelty_reasoning, **必须≥150字符，建议写到180+字符**）：
- 写明发布时间、场景与现有Benchmark（HumanEval、SWE-bench、HELM等）的差异
- 归纳新的任务设定、数据来源、评估指标或工具链，为何能补齐MGX短板
- 若属于老任务但仍重要，解释其基线价值或覆盖范围
- 给出MGX在采用该Benchmark后可获得的新增洞察
- **字符计数示例**："该Benchmark发布于2025年3月，引入“多Agent分工+代码审阅”任务，相比HumanEval只测单轮生成，它额外考察沟通准确率和审阅反馈质量。指标方面新增交互轮次成功率，弥补MGX在协作编码评测上的空白。即便延续经典Pass@k，也通过高难度多文件项目提高区分度。"（≈190字符）

【维度5: MGX适配度 relevance_score】
评分标准：
- 10分: 核心场景(P0), 直接可用, 与MGX高度契合
- 8-9分: 核心场景(P0), 或高优先级(P1), 需少量适配
- 6-7分: P1场景, 或P0场景但需较多工程改造
- 4-5分: P2场景, 或P1场景但适配成本高
- 2-3分: Other场景, 但可能对特定子场景有价值
- 0-1分: 完全无关, 不推荐纳入MGX

推理要求（relevance_reasoning, **必须≥150字符，建议写到180+字符**）：
- 明确归类至九大场景之一，引用任务描述/指标/输入输出形式作为证据
- 描述MGX若接入该Benchmark会测到哪些能力（编码、工具调用、协同、推理等）
- 若需工程改造，指出具体适配项（接口格式、评测脚本、环境依赖）
- 若相关性低，也需陈述原因及可能的次要价值
- **字符计数示例**："任务要求多Agent协作完成Web端漏洞修复，核心流程包括阅读源码、生成补丁、运行E2E测试，明显属于P0级Coding+WebDev场景。MGX可直接把该基准作为Vibe Coding协作任务，衡量Agent在代码检索、工具链调用及回归测试的闭环能力，适配成本仅需编写浏览器控制工具。"（≈200字符）

=== 第4部分：后端专项评分（仅后端Benchmark需要） ===
如果候选明确属于Backend场景（数据库/框架性能/API设计/分布式系统），则必须额外提供以下2个专项评分，否则填0.0和空字符串。

【后端维度1: MGX相关性 backend_mgx_relevance】
评分标准（0-10分）：
- 10分: 直接评测MGX后端能力（如：生成高性能API、优化数据库查询）
- 8-9分: 评测通用后端能力，MGX可直接借鉴（如：框架性能基准）
- 6-7分: 后端通用指标，对MGX有参考价值但需转化
- 4-5分: 后端理论研究，工程价值一般
- 2-3分: 仅数据库排名/框架流行度，无实际评测
- 0分: 非后端Benchmark

推理要求（backend_mgx_reasoning, **必须≥200字符，建议写到250字符**）：
- 详细描述Benchmark聚焦的后端维度（吞吐量、延迟、可扩展性、安全性、事务一致性等）
- 结合指标/场景说明MGX如何利用该数据集评估自动生成的API、微服务或数据库脚本
- 若涉及数据库或分布式系统，指出对MGX存储/协调模块的启发
- 分析评测环境、负载模型是否贴近真实生产，从而影响MGX在后端场景的可信度
- **字符计数示例**："该后端Benchmark专注评测Web框架在高并发下的吞吐量、P95延迟与资源占用，并提供REST与GraphQL两种模式。MGX可用它来测试自动生成的FastAPI/Express服务，在真实压测脚本下比较代理编写代码与人工基线的性能差异。场景涵盖TLS终止和数据库交互，能够为MGX的后端Agent提供可量化的优化目标。"（≈240字符）

【后端维度2: 工程实践价值 backend_engineering_value】
评分标准（0-10分）：
- 10分: 生产级基准，业界广泛认可，有真实负载模拟
- 8-9分: 工程实践完善，有详细测试方法和环境配置
- 6-7分: 基本工程实践，可复现但环境要求高
- 4-5分: 理论性强，工程落地需较多改造
- 2-3分: 仅排名或简单对比，无详细测试方法
- 0分: 非后端Benchmark

推理要求（backend_engineering_reasoning, **必须≥200字符，建议写到250字符**）：
- 评估测试脚本、环境配置、监控指标是否足够工程化，可否一键复现
- 分析该Benchmark在业界/学术中的采用度，以及是否提供与生产类似的工作负载
- 指出潜在局限（如仅测试理想网络、缺少持久化层），并评估对MGX决策的影响
- 给出MGX是否应采纳/参考的建议，并说明需要补充的工程工作
- **字符计数示例**："测试框架提供Docker Compose与k6脚本，可在30分钟内复现压测，并导出Prometheus指标，工程成熟度较高。虽然负载模型集中在API读写，对复杂分布式事务覆盖不足，但足以指导MGX评估自动生成的后端应用在CPU/内存曲线上的表现。建议MGX采纳该基准作为性能回归测试，同时补充数据库写压场景。"（≈250字符）

=== 第5部分：结构化字段抽取 ===
除了评分，你还需要抽取以下结构化字段：

【task_domain】任务领域（必填，不允许null）
- 从以下选项中选择（可多选，用逗号分隔，按优先级降序）：
  {task_domain_options}
- 如果无法判断，必须选择"Other"
- 示例："Coding,ToolUse" 或 "Backend" 或 "Other"

【metrics】评估指标（数组，最多{max_metrics}个）
- 用标准缩写或大写表示，例如：["Pass@1", "BLEU-4", "Accuracy", "F1-Score"]
- 如果摘要/README中未提及具体指标，返回空数组[]（不是null）

【baselines】对比基线（数组，最多{max_metrics}个）
- 列出论文/项目中对比的主要模型，例如：["GPT-4", "Claude-3.5-Sonnet", "Llama-3-70B"]
- 如果未提及，返回空数组[]

【institution】主要机构（字符串）
- 填写第一作者所属机构的完整名称，例如："Stanford University" 或 "Google DeepMind"
- 如果无法确定，填写"Unknown"（不是null）

【authors】作者列表（数组，最多5人）
- 格式：["First Last", "First Last"]，例如：["Yann LeCun", "Geoffrey Hinton"]
- 如果无法提取，返回空数组[]

【dataset_size】数据集规模（整数）
- 尽量解析数字，例如："1000 problems" → 1000
- 如果无法解析，返回null

【dataset_size_description】数据集规模描述（字符串）
- 原始描述文本，例如："1000 coding problems across 5 difficulty levels"
- 如果未提及，填写"Not specified"

【task_type】任务类型（字符串）
- 具体任务名称，例如："Code Generation" / "Question Answering" / "GUI Automation"
- 如果无法判断，填写"Other"

【license_type】许可证类型（字符串）
- 具体License名称，例如："MIT" / "Apache-2.0" / "GPL-3.0"
- 如果未知，填写"Unknown"

【paper_url】论文链接（字符串）
- arXiv/会议论文的URL
- 如果非论文来源或无链接，返回空字符串""

【reproduction_script_url】复现脚本链接（字符串）
- 评估脚本的GitHub链接或文档链接
- 如果未提及，返回空字符串""

【evaluation_metrics】评估指标列表（数组，与metrics字段相同）
- 为了兼容性，与metrics字段保持一致

=== 第6部分：综合评分与推荐逻辑 ===

【综合推理 overall_reasoning】（≥50字符）
基于5维评分，给出总体推荐意见：
- 如果 总分≥6.5 且 relevance_score≥7：强烈推荐纳入MGX
- 如果 总分≥6.0 且 relevance_score≥5：推荐纳入，但需优先级排序
- 如果 总分<6.0 或 relevance_score<5：不推荐纳入
- 说明主要优势和主要风险

【推理字数验证】
- activity_reasoning + reproducibility_reasoning + license_reasoning + novelty_reasoning + relevance_reasoning ≥ 750字符
- backend_mgx_reasoning + backend_engineering_reasoning ≥ 400字符（仅后端）
- overall_reasoning ≥ 50字符
- **总推理字数必须 ≥1200字符（非后端Benchmark至少800字符）**

=== 第7部分：JSON输出格式 ===

你必须严格按照以下JSON Schema输出，不能新增/删除字段，不能返回null（除非明确说明可选）：

{{
  "activity_score": float,  // 0-10
  "reproducibility_score": float,  // 0-10
  "license_score": float,  // 0-10
  "novelty_score": float,  // 0-10
  "relevance_score": float,  // 0-10
  "activity_reasoning": "string",  // ≥150字符
  "reproducibility_reasoning": "string",  // ≥150字符
  "license_reasoning": "string",  // ≥150字符
  "novelty_reasoning": "string",  // ≥150字符
  "relevance_reasoning": "string",  // ≥150字符
  "backend_mgx_relevance": float,  // 0-10，非后端填0.0
  "backend_mgx_reasoning": "string",  // ≥200字符，非后端填空字符串""
  "backend_engineering_value": float,  // 0-10，非后端填0.0
  "backend_engineering_reasoning": "string",  // ≥200字符，非后端填空字符串""
  "overall_reasoning": "string",  // ≥50字符
  "task_domain": "string",  // 必填，不能是null
  "metrics": ["string"],  // 数组，可以为空[]
  "baselines": ["string"],  // 数组，可以为空[]
  "institution": "string",  // 必填，不能是null
  "authors": ["string"],  // 数组，可以为空[]
  "dataset_size": int or null,
  "dataset_size_description": "string",  // 必填
  "task_type": "string",  // 必填
  "license_type": "string",  // 必填
  "paper_url": "string",  // 可以为空字符串""
  "reproduction_script_url": "string",  // 可以为空字符串""
  "evaluation_metrics": ["string"]  // 与metrics相同
}}

=== 第8部分：特殊情况处理 ===

【情况1：摘要字段被污染】
如果abstract字段包含HTML标签、Markdown语法、图片链接（如`<!-- <p align="center"> <img alt=...`），说明这是GitHub README原始内容未清理。你需要：
- 尝试从污染内容中提取有价值的文本信息
- 在推理中明确说明"摘要字段被污染，从README中提取到的有效信息有限"
- 适当降低reproducibility_score（因为文档质量差）

【情况2：缺少GitHub stars】
如果github_stars为null或0，但有GitHub URL：
- 说明"候选提供了GitHub链接但未获取到stars数据，可能是新项目或私有仓库"
- activity_score适当保守评分（≤6分）

【情况3：非Benchmark候选】
如果发现候选不是Benchmark而是工具/框架/库：
- 在overall_reasoning中明确说明"该候选不是Benchmark，而是[工具/框架/库]"
- novelty_score和relevance_score给予较低分数（≤4分）
- 不推荐纳入MGX Benchmark池

【情况4：后端Benchmark识别】
如果候选标题或摘要包含以下关键词，判断为后端Benchmark：
- 数据库性能: "database", "SQL", "NoSQL", "query optimization"
- Web框架性能: "web framework", "HTTP benchmark", "throughput", "latency"
- API设计: "API benchmark", "RESTful", "GraphQL performance"
- 分布式系统: "distributed", "consensus", "replication"
则必须填写backend_mgx_relevance和backend_engineering_value及其推理。

=== 第9部分：质量检查清单 ===

输出JSON前，请自检：
- [ ] 所有score字段在0-10范围内
- [ ] activity_reasoning ≥ 150字符
- [ ] reproducibility_reasoning ≥ 150字符
- [ ] license_reasoning ≥ 150字符
- [ ] novelty_reasoning ≥ 150字符
- [ ] relevance_reasoning ≥ 150字符
- [ ] 如果是后端Benchmark: backend_mgx_reasoning ≥ 200字符, backend_engineering_reasoning ≥ 200字符
- [ ] overall_reasoning ≥ 50字符
- [ ] task_domain不是null，从预定义列表中选择
- [ ] institution不是null（可以是"Unknown"）
- [ ] task_type不是null（可以是"Other"）
- [ ] license_type不是null（可以是"Unknown"）
- [ ] dataset_size_description不是null（可以是"Not specified"）
- [ ] JSON严格符合Schema，没有多余字段
- [ ] JSON可以被标准解析器解析（没有语法错误）

【PDF深度内容 (Phase 8)】
> Evaluation部分摘要 (2000字):
{evaluation_summary}

> Dataset部分摘要 (1000字):
{dataset_summary}

> Baselines部分摘要 (1000字):
{baselines_summary}

【原始提取数据 (采集器粗提取)】
- 原始指标: {raw_metrics}
- 原始Baseline: {raw_baselines}
- 原始作者: {raw_authors}
- 原始机构: {raw_institutions}
- 原始数据规模: {raw_dataset_size}

现在，请严格按照上述9个部分的要求，输出规范的JSON评分结果。**不要在JSON前后添加任何解释性文字，直接输出纯JSON。**
"""


# ==================== Pydantic数据模型 ====================
class UnifiedBenchmarkExtraction(BaseModel):
    """全LLM统一评分输出模型（26个字段）"""

    model_config = ConfigDict(extra="forbid")  # 禁止额外字段

    # 5维评分
    activity_score: float = Field(..., ge=0.0, le=10.0)
    reproducibility_score: float = Field(..., ge=0.0, le=10.0)
    license_score: float = Field(..., ge=0.0, le=10.0)
    novelty_score: float = Field(..., ge=0.0, le=10.0)
    relevance_score: float = Field(..., ge=0.0, le=10.0)

    # 5维详细推理（每个≥150字符）
    activity_reasoning: str = Field(
        ..., min_length=constants.LLM_REASONING_MIN_CHARS
    )
    reproducibility_reasoning: str = Field(
        ..., min_length=constants.LLM_REASONING_MIN_CHARS
    )
    license_reasoning: str = Field(
        ..., min_length=constants.LLM_REASONING_MIN_CHARS
    )
    novelty_reasoning: str = Field(
        ..., min_length=constants.LLM_REASONING_MIN_CHARS
    )
    relevance_reasoning: str = Field(
        ..., min_length=constants.LLM_REASONING_MIN_CHARS
    )

    # 后端专项评分（仅后端Benchmark）
    backend_mgx_relevance: float = Field(default=0.0, ge=0.0, le=10.0)
    backend_mgx_reasoning: str = Field(default="")
    backend_engineering_value: float = Field(default=0.0, ge=0.0, le=10.0)
    backend_engineering_reasoning: str = Field(default="")

    # 综合推理
    overall_reasoning: str = Field(
        ..., min_length=constants.LLM_OVERALL_REASONING_MIN_CHARS
    )

    # 结构化字段
    task_domain: str  # 必填，不能是None
    metrics: List[str] = Field(default_factory=list)
    baselines: List[str] = Field(default_factory=list)
    institution: str  # 必填，不能是None
    authors: List[str] = Field(default_factory=list)
    dataset_size: Optional[int] = None
    dataset_size_description: str  # 必填
    task_type: str  # 必填
    license_type: str  # 必填
    paper_url: str = ""
    reproduction_script_url: str = ""
    evaluation_metrics: List[str] = Field(default_factory=list)

    @field_validator("backend_mgx_reasoning", "backend_engineering_reasoning")
    @classmethod
    def validate_backend_reasoning(cls, v: str, info) -> str:
        """后端推理字段验证：如果后端评分>0，推理必须≥200字符"""
        data = info.data
        required = constants.LLM_BACKEND_REASONING_MIN_CHARS
        needs_backend_reasoning = False
        if data.get("backend_mgx_relevance", 0) > 0:
            needs_backend_reasoning = True
        if info.field_name == "backend_engineering_reasoning":
            needs_backend_reasoning = needs_backend_reasoning or (
                data.get("backend_engineering_value", 0) > 0
            )
        if needs_backend_reasoning and len(v) < required:
            raise ValueError(
                f"后端推理字段必须≥{required}字符，当前{len(v)}字符"
            )
        return v


# ==================== LLM评分引擎 ====================
class LLMScorer:
    """全LLM统一评分引擎（单次调用返回所有26个字段）"""

    def __init__(self) -> None:
        self.settings = get_settings()
        api_key = self.settings.openai.api_key
        base_url = self.settings.openai.base_url
        self.client: Optional[AsyncOpenAI] = None
        if api_key:
            self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.redis_client: Optional[AsyncRedis] = None

    async def __aenter__(self) -> "LLMScorer":
        try:
            self.redis_client = redis.from_url(
                self.settings.redis.url,
                encoding="utf-8",
                decode_responses=True,
            )
            ping_future = cast(Awaitable[bool], self.redis_client.ping())
            await ping_future
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis连接失败,将不使用缓存: %s", exc)
            self.redis_client = None
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self.redis_client:
            await self.redis_client.aclose()
            self.redis_client = None

    def _cache_key(self, candidate: RawCandidate) -> str:
        """生成Redis缓存键（基于标题+URL的MD5）"""
        key_str = f"v2:{candidate.title}:{candidate.url}"  # v2表示新版prompt
        digest = hashlib.md5(
            key_str.encode(), usedforsecurity=False
        ).hexdigest()
        return f"{constants.REDIS_KEY_PREFIX}unified_score:{digest}"

    async def _get_cached_score(
        self, candidate: RawCandidate
    ) -> Optional[UnifiedBenchmarkExtraction]:
        """从Redis读取缓存评分"""
        if not self.redis_client:
            return None
        try:
            cached = await self.redis_client.get(self._cache_key(candidate))
            if cached:
                logger.debug("评分缓存命中: %s", candidate.title[:50])
                return UnifiedBenchmarkExtraction.parse_raw(cached)
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取Redis缓存失败: %s", exc)
        return None

    async def _set_cached_score(
        self, candidate: RawCandidate, extraction: UnifiedBenchmarkExtraction
    ) -> None:
        """将评分结果写入Redis缓存"""
        if not self.redis_client:
            return
        try:
            await self.redis_client.setex(
                self._cache_key(candidate),
                constants.REDIS_TTL_DAYS * 86400,
                extraction.json(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("写入Redis缓存失败: %s", exc)

    def _build_prompt(self, candidate: RawCandidate) -> str:
        """构建4000+ token的超详细评分prompt"""
        abstract = clean_summary_text(candidate.abstract or "无") or "无"
        if len(abstract) > 2000:
            abstract = abstract[:2000] + "..."

        # 提取PDF增强内容
        raw_metadata = candidate.raw_metadata or {}
        evaluation_summary = raw_metadata.get("evaluation_summary") or "未提供（论文无Evaluation章节或PDF解析失败）"
        dataset_summary = raw_metadata.get("dataset_summary") or "未提供（论文无Dataset章节或PDF解析失败）"
        baselines_summary = raw_metadata.get("baselines_summary") or "未提供（论文无Baselines章节或PDF解析失败）"

        # 原始提取数据
        raw_metrics = ", ".join(candidate.raw_metrics or []) if candidate.raw_metrics else "未提取"
        raw_baselines = ", ".join(candidate.raw_baselines or []) if candidate.raw_baselines else "未提取"
        raw_authors = candidate.raw_authors or (", ".join(candidate.authors or []) if candidate.authors else "未提取")
        raw_institutions = candidate.raw_institutions or "未提取"
        raw_dataset = candidate.raw_dataset_size or "未提取"

        return UNIFIED_SCORING_PROMPT_TEMPLATE.format(
            task_domain_options=", ".join(constants.TASK_DOMAIN_OPTIONS),
            max_metrics=constants.MAX_EXTRACTED_METRICS,
            title=candidate.title,
            source=candidate.source,
            url=candidate.url,
            abstract=abstract,
            github_stars=candidate.github_stars or "未提供",
            publish_date=candidate.publish_date.strftime("%Y-%m-%d") if candidate.publish_date else "未知",
            github_url=candidate.github_url or "未提供",
            dataset_url=candidate.dataset_url or "未提供",
            paper_url=candidate.paper_url or "未提供",
            license_type=candidate.license_type or "未知",
            task_type=candidate.task_type or "未识别",
            evaluation_summary=evaluation_summary,
            dataset_summary=dataset_summary,
            baselines_summary=baselines_summary,
            raw_metrics=raw_metrics,
            raw_baselines=raw_baselines,
            raw_authors=raw_authors,
            raw_institutions=raw_institutions,
            raw_dataset_size=raw_dataset,
        )

    @retry(
        stop=stop_after_attempt(constants.LLM_MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def _call_llm(
        self, candidate: RawCandidate
    ) -> UnifiedBenchmarkExtraction:
        """调用LLM获取评分（单次返回所有26个字段）"""
        if not self.client:
            raise RuntimeError("未配置OpenAI接口,无法调用LLM")

        prompt = self._build_prompt(candidate)
        logger.debug("LLM评分prompt长度: %d 字符", len(prompt))

        messages: List[ChatCompletionMessageParam] = [
            {
                "role": "system",
                "content": (
                    "你是MGX BenchScope的Benchmark评估专家，将输出可直接入库的JSON评分结果。\n\n"
                    "【关键硬性要求——违反任意一条将视为失败】\n"
                    "1. activity/reproducibility/license/novelty/relevance_reasoning 各≥150字符（建议≥180字符）\n"
                    "2. 若 backend_mgx_relevance 或 backend_engineering_value > 0，则对应的 backend_*_reasoning 各≥200字符；否则可留空字符串\n"
                    "3. overall_reasoning ≥ 50字符，需要总结推荐意见、优势与风险\n"
                    "4. 总推理字数≥1200字符（即便无后端字段，也需通过展开细节满足要求）\n\n"
                    "【如何保证字符要求】\n"
                    "- 提供具体数据（GitHub stars、提交时间、PR/Issue数量、算力需求等）并展开论述\n"
                    "- 每个推理段落结构为“证据→分析→结论”，至少2-3句话\n"
                    "- 如果信息不足也要写明推断依据与潜在风险，不得以一句话带过\n"
                    "- 输出前自行检查字符数；若不满足要求，继续补充细节再输出\n\n"
                    "【输出限制】严格遵循给定JSON Schema，不允许新增/缺失字段，不得返回 null（除明确允许）。"
                ),
            },
            {"role": "user", "content": prompt},
        ]

        repair_attempt = 0
        while True:
            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.settings.openai.model or constants.LLM_MODEL,
                    messages=messages,
                    temperature=0.1,
                    max_tokens=4096,  # 增加max_tokens以容纳详细推理
                ),
                timeout=constants.LLM_TIMEOUT_SECONDS * 2,  # 增加超时时间
            )

            content = response.choices[0].message.content or ""
            logger.debug("LLM原始响应长度: %d 字符", len(content))
            payload = self._load_payload(content)
            try:
                extraction = UnifiedBenchmarkExtraction.parse_obj(payload)
            except ValidationError as exc:  # noqa: PERF203
                violations = self._extract_length_violations(exc, payload)
                if (
                    violations
                    and repair_attempt < constants.LLM_SELF_HEAL_MAX_ATTEMPTS
                ):
                    repair_attempt += 1
                    fix_prompt = self._build_length_fix_prompt(violations)
                    messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": fix_prompt})
                    logger.warning(
                        "LLM推理长度不足，触发第%d次纠偏: %s",
                        repair_attempt,
                        candidate.title[:50],
                    )
                    continue

                logger.error("LLM响应字段校验失败: %s", exc)
                logger.error(
                    "解析的payload: %s",
                    json.dumps(payload, indent=2, ensure_ascii=False)[:1000],
                )
                raise

            total_reasoning_length = (
                len(extraction.activity_reasoning)
                + len(extraction.reproducibility_reasoning)
                + len(extraction.license_reasoning)
                + len(extraction.novelty_reasoning)
                + len(extraction.relevance_reasoning)
                + len(extraction.backend_mgx_reasoning)
                + len(extraction.backend_engineering_reasoning)
                + len(extraction.overall_reasoning)
            )
            if total_reasoning_length < 1200:
                logger.warning(
                    "推理总字数不足: %d < 1200，候选：%s",
                    total_reasoning_length,
                    candidate.title[:50],
                )

            return extraction



    def _load_payload(self, content: str) -> dict[str, Any]:
        """解析LLM响应文本为JSON对象"""
        json_str = self._strip_code_fence(content)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as exc:  # noqa: BLE001
            logger.error("LLM响应解析失败(JSON): %s", exc)
            logger.error("原始响应: %s", content[:1000])
            raise

    @staticmethod
    def _strip_code_fence(content: str) -> str:
        """去除Markdown代码块标记"""
        text = content.strip()
        if text.startswith("```") and text.endswith("```"):
            lines = text.split("\n")
            lines = lines[1:-1]
            return "\n".join(lines).strip()
        if text.startswith("```"):
            return text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return text

    def _extract_length_violations(
        self, error: ValidationError, payload: dict[str, Any]
    ) -> Dict[str, Tuple[int, int]]:
        """从Pydantic错误中提取可自动修复的字符长度问题"""
        violations: Dict[str, Tuple[int, int]] = {}
        for err in error.errors():
            loc = err.get("loc") or ()
            field = loc[0] if loc else None
            if not isinstance(field, str):
                continue

            min_length: Optional[int] = None
            err_type = err.get("type")
            if err_type == "string_too_short":
                min_length = err.get("ctx", {}).get("min_length")
            elif err_type == "value_error" and "后端推理字段" in err.get("msg", ""):
                min_length = constants.LLM_BACKEND_REASONING_MIN_CHARS
            else:
                continue

            if not isinstance(min_length, int):
                continue

            current_value = payload.get(field, "") or ""
            current_length = len(str(current_value))
            violations[field] = (min_length, current_length)

        return violations

    def _build_length_fix_prompt(
        self, violations: Dict[str, Tuple[int, int]]
    ) -> str:
        """构造提示语，让LLM扩写字符不足的推理字段"""
        ordered_fields: List[str] = []
        for field in REASONING_FIELD_ORDER:
            if field in violations:
                ordered_fields.append(field)
        for field in violations:
            if field not in ordered_fields:
                ordered_fields.append(field)

        tips = [
            "上一次的JSON输出未通过校验：以下推理字段字符数不足。",
            "请保留所有字段并重新输出完整JSON，通过补充证据、数据来源、MGX场景影响、潜在风险等方式扩写对应推理段落。",
        ]
        for field in ordered_fields:
            required, current = violations[field]
            label = REASONING_FIELD_LABELS.get(field, field)
            tips.append(
                f"- {label}: 当前{current}字符，至少{required}字符。"
            )
        tips.append("只输出符合Schema的纯JSON，不要添加额外解释或省略字段。")
        return "\n".join(tips)

    async def score(self, candidate: RawCandidate) -> ScoredCandidate:
        """评分单个候选项"""
        # 尝试读取缓存
        extraction = await self._get_cached_score(candidate)
        if not extraction:
            if not self.client:
                logger.error("OpenAI未配置且无缓存,无法评分: %s", candidate.title[:50])
                raise RuntimeError("未配置OpenAI且无缓存,无法评分")
            try:
                extraction = await self._call_llm(candidate)
                await self._set_cached_score(candidate, extraction)
            except Exception as exc:
                logger.error("LLM评分失败: %s, 候选: %s", exc, candidate.title[:50])
                raise

        return self._to_scored_candidate(candidate, extraction)

    def _to_scored_candidate(
        self,
        candidate: RawCandidate,
        extraction: UnifiedBenchmarkExtraction,
    ) -> ScoredCandidate:
        """将评分结果转换为ScoredCandidate"""
        # 合并作者信息
        authors = extraction.authors or candidate.authors
        # 合并指标信息
        metrics = extraction.metrics or candidate.evaluation_metrics
        # 机构信息
        institution = extraction.institution if extraction.institution != "Unknown" else candidate.raw_institutions
        # 数据集规模描述
        dataset_size_desc = (
            extraction.dataset_size_description
            if extraction.dataset_size_description != "Not specified"
            else candidate.raw_dataset_size
        )

        # 构建score_reasoning（兼容旧版）
        score_reasoning = (
            f"【综合推理】{extraction.overall_reasoning}\n\n"
            f"【活跃度】{extraction.activity_reasoning}\n\n"
            f"【可复现性】{extraction.reproducibility_reasoning}\n\n"
            f"【许可合规】{extraction.license_reasoning}\n\n"
            f"【新颖性】{extraction.novelty_reasoning}\n\n"
            f"【MGX适配度】{extraction.relevance_reasoning}"
        )
        if extraction.backend_mgx_reasoning:
            score_reasoning += (
                f"\n\n【后端MGX相关性】{extraction.backend_mgx_reasoning}\n\n"
                f"【后端工程价值】{extraction.backend_engineering_reasoning}"
            )

        return ScoredCandidate(
            # RawCandidate字段
            title=candidate.title,
            url=candidate.url,
            source=candidate.source,
            abstract=candidate.abstract,
            authors=authors,
            publish_date=candidate.publish_date,
            github_stars=candidate.github_stars,
            github_url=candidate.github_url,
            dataset_url=candidate.dataset_url,
            hero_image_url=candidate.hero_image_url,
            hero_image_key=candidate.hero_image_key,
            raw_metadata=candidate.raw_metadata,
            raw_metrics=candidate.raw_metrics,
            raw_baselines=candidate.raw_baselines,
            raw_authors=candidate.raw_authors,
            raw_institutions=candidate.raw_institutions,
            raw_dataset_size=candidate.raw_dataset_size,
            # Phase 6字段
            paper_url=extraction.paper_url or candidate.paper_url,
            task_type=extraction.task_type,
            license_type=extraction.license_type,
            evaluation_metrics=extraction.evaluation_metrics or candidate.evaluation_metrics,
            reproduction_script_url=extraction.reproduction_script_url or candidate.reproduction_script_url,
            # 5维评分
            activity_score=extraction.activity_score,
            reproducibility_score=extraction.reproducibility_score,
            license_score=extraction.license_score,
            novelty_score=extraction.novelty_score,
            relevance_score=extraction.relevance_score,
            # 兼容旧版score_reasoning
            score_reasoning=score_reasoning,
            # 新增详细推理字段
            activity_reasoning=extraction.activity_reasoning,
            reproducibility_reasoning=extraction.reproducibility_reasoning,
            license_reasoning=extraction.license_reasoning,
            novelty_reasoning=extraction.novelty_reasoning,
            relevance_reasoning=extraction.relevance_reasoning,
            # 后端专项评分
            backend_mgx_relevance=extraction.backend_mgx_relevance,
            backend_mgx_reasoning=extraction.backend_mgx_reasoning,
            backend_engineering_value=extraction.backend_engineering_value,
            backend_engineering_reasoning=extraction.backend_engineering_reasoning,
            # 综合推理
            overall_reasoning=extraction.overall_reasoning,
            # Phase 8字段
            task_domain=extraction.task_domain,
            metrics=metrics,
            baselines=extraction.baselines,
            institution=institution,
            dataset_size=extraction.dataset_size,
            dataset_size_description=dataset_size_desc,
        )

    async def score_batch(
        self, candidates: List[RawCandidate]
    ) -> List[ScoredCandidate]:
        """批量评分（并发控制）"""
        if not candidates:
            return []

        semaphore = asyncio.Semaphore(constants.SCORE_CONCURRENCY)

        async def score_with_semaphore(candidate: RawCandidate) -> ScoredCandidate:
            async with semaphore:
                return await self.score(candidate)

        tasks = [score_with_semaphore(candidate) for candidate in candidates]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常
        scored_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "评分失败: %s, 候选: %s",
                    result,
                    candidates[i].title[:50],
                )
            else:
                scored_results.append(result)

        logger.info(
            "批量评分完成: 成功%d条/共%d条 (并发上限=%d)",
            len(scored_results),
            len(candidates),
            constants.SCORE_CONCURRENCY,
        )
        return scored_results
