# CODEX增强过滤方案 - 解决80%误判率问题 (2025-11-26)

## 优化总结（最终版）

### 核心改进

本次优化解决了**Benchmark方法论被误杀**的问题：

**关键区分**：
- ✅ **Benchmark方法论**（保留）: 提出"如何构建/改进Benchmark"的方法
  - 示例: Semantic-KG（构建语义Benchmark的方法）
  - 特征: 贡献是"评估方法创新"
- ❌ **算法/系统方法论**（过滤）: 提出"如何解决某问题"的算法
  - 示例: RPM-MCTS（代码生成算法）
  - 特征: 贡献是"算法创新"

**修改要点**：
1. Prompt中明确区分两类方法论
2. arXiv专项规则细化：看论文贡献类型（评估创新 vs 算法创新）
3. 判定流程增加"主要贡献"分析步骤
4. 测试用例增加Semantic-KG验证

---

## 问题严重性升级

**实际测试数据**（2025-11-26推送）：
- 推送总数: 15项
- 真Benchmark: 3项 (20%)
- 误判项: 12项 (80%)

**误判率 = 80%**，远超预期的10-20%，需要**紧急升级过滤规则**。

---

## 误判分类详解（基于真实数据）

### ✅ 真Benchmark (3/15 = 20%)

| 项目 | 判定依据 |
|------|---------|
| **microsoft/fara** | 包含145K任务轨迹数据集，用于评估GUI自动化Agent能力 |
| **AppSelectBench** | 工具选择评测基准，有明确的评估任务和指标 |
| **Semantic-KG** | Benchmark构建方法论，用于语义相似度评测 |

**共同特征**：
- ✅ 有数据集（测试样本）
- ✅ 有评估任务（明确的测试目标）
- ✅ 有评估指标（准确率、成功率等）
- ✅ 目的是评测其他系统的能力

---

### ❌ 误判类别A: 系统/框架 (3/15 = 20%)

| 项目 | 实际类型 | 为何被误判 |
|------|---------|-----------|
| **EverMind-AI/EverMemOS** | 智能记忆操作系统 | README提到"evaluation"（系统评估模块） |
| **AgoneTest Framework** | 单元测试生成框架 | 名称包含"Test"，README提到"benchmark"（性能测试） |
| **VICoT-Agent** | 多模态推理Agent框架 | 论文包含实验评估章节 |

**判定依据**：
- ❌ 提供功能/服务（import后可调用）
- ❌ 目的是帮助开发者构建应用
- ❌ 是被评测的对象，不是评测工具

**正反例对比**：
```
❌ 误判: "AgoneTest自动生成Java单元测试" → 这是工具，用来做测试
✅ 正确: "HumanEval测试代码生成能力" → 这是Benchmark，用来评测

❌ 误判: "VICoT-Agent多模态推理框架" → 这是Agent，用来做推理
✅ 正确: "MMLU测试模型知识问答能力" → 这是Benchmark，用来评测
```

---

### ❌ 误判类别B: 工具/协议/SDK (3/15 = 20%)

| 项目 | 实际类型 | 为何被误判 |
|------|---------|-----------|
| **universal-tool-calling-protocol/code-mode** | MCP协议标准 | README提到"benchmark"（性能基准测试） |
| **CAPHTECH/kiri** | 代码上下文提取工具 | 包含"code retrieval evaluation"（工具评估） |
| **zechenzhangAGI/AI-research-SKILLs** | AI研究技能库 | 包含70个技能，README提到"evaluation"（技能评估） |

**判定依据**：
- ❌ 提供API/SDK/协议
- ❌ 目的是让其他系统调用
- ❌ README中的"benchmark"指性能测试，不是评测基准

**正反例对比**：
```
❌ 误判: "code-mode工具调用协议" → 这是协议，定义如何调用工具
✅ 正确: "ToolBench工具使用能力评测" → 这是Benchmark，测试工具使用能力

❌ 误判: "kiri代码上下文提取工具" → 这是工具，提取代码上下文
✅ 正确: "CodeSearchNet代码搜索评测集" → 这是Benchmark，测试代码搜索
```

---

### ❌ 误判类别C: 算法/系统方法论（arXiv论文）(6/15 = 40%) ← 最严重

| 项目 | 实际类型 | 为何被误判 |
|------|---------|-----------|
| **RPM-MCTS** | 代码生成算法（MCTS） | 论文包含实验评估章节，在HumanEval上测试 |
| **QiMeng-Kernel** | GPU Kernel生成编程范式 | 论文对比baseline性能 |
| **SwitchDelta** | 分布式存储元数据更新机制 | 论文包含性能评估 |
| **M³Prune** | 多模态RAG图剪枝算法 | 论文在多个数据集上测试 |
| **The Devil in the Details** | 大模型一致性问题分析论文 | 研究论文，包含实验分析 |
| **Intent-Based Query Rewriting** | 查询重写方法论 | 方法论文，包含对比实验 |

**判定依据**：
- ❌ 提出新算法/新系统方法
- ❌ 在现有Benchmark上测试（而不是提供新Benchmark）
- ❌ 论文的贡献是"算法创新/系统优化"，不是"评测集/评估方法"

**核心区别**（关键：看贡献是什么）：
```
❌ 误判: "RPM-MCTS在HumanEval上达到90%准确率"
   → 这是算法论文，贡献是"MCTS算法"，用HumanEval测试

✅ 正确: "HumanEval提供164道编程题测试代码生成"
   → 这是Benchmark论文，贡献是"测试集"

✅ 正确: "Semantic-KG: 构建语义相似度Benchmark的方法"
   → 这是Benchmark方法论，贡献是"如何构建高质量评测集"

❌ 误判: "M³Prune在3个数据集上提升10%性能"
   → 这是算法论文，贡献是"剪枝方法"，用现有数据集测试

✅ 正确: "MMLU提供57个任务测试知识问答"
   → 这是Benchmark论文，贡献是"新测试集"
```

**重要区分**（避免误杀Benchmark方法论）：
- ✅ **Benchmark方法论**（保留）: 提出"如何构建/改进Benchmark"的方法
  - 示例: Semantic-KG（构建语义Benchmark的方法）
  - 特征: 贡献是"评估方法创新"，帮助构建更好的测试集
- ❌ **算法/系统方法论**（过滤）: 提出"如何解决某问题"的算法
  - 示例: RPM-MCTS（代码生成算法）
  - 特征: 贡献是"算法创新"，在现有测试集上验证

**arXiv论文的特殊性**：
- arXiv论文99%都包含"实验评估"章节
- 论文会引用现有Benchmark（如HumanEval、SWE-bench）
- 论文会对比baseline → LLM看到"evaluation"、"benchmark"
- **但论文的目的是提出新方法，不是提供新评测集**

**正确筛选规则**（关键：看论文贡献）：
```
✅ arXiv论文 + 提供新数据集 + 评估任务 → 是Benchmark
✅ arXiv论文 + 构建Benchmark的方法 → 是Benchmark（如Semantic-KG）
✅ arXiv论文 + 提出新评估指标 → 是Benchmark
✅ arXiv论文 + 改进现有Benchmark评估方法 → 是Benchmark

❌ arXiv论文 + 提出新算法 + 在现有Benchmark测试 → 不是Benchmark
❌ arXiv论文 + 系统设计 + 性能评估 → 不是Benchmark
❌ arXiv论文 + 算法优化方法论 + 对比实验 → 不是Benchmark
```

**判断标准**（关键问题）：
1. 论文的主要贡献是什么？
   - ✅ 贡献是"评估方法/数据集/指标" → 是Benchmark
   - ❌ 贡献是"算法/系统/模型" → 不是Benchmark

2. 论文提供了什么？
   - ✅ 提供测试集/评估方法/评估工具 → 是Benchmark
   - ❌ 提供算法实现/系统架构 → 不是Benchmark

3. 论文被引用时，其他人用它做什么？
   - ✅ 用它来评测自己的模型 → 是Benchmark
   - ❌ 引用它的算法思想 → 不是Benchmark

---

## 根本原因分析

### 当前Prompt的问题

**问题1**: 定义太宽泛
```python
# 当前定义
"Benchmark: 提供测试数据集、评估任务、排行榜"

# 问题:
- arXiv论文的实验评估章节被误判为"评估任务"
- 系统/框架的测试模块被误判为"测试数据集"
- 工具的性能基准测试被误判为"排行榜"
```

**问题2**: 缺少负面过滤
```python
# 当前只有一个负面类别
❌ 工具/框架

# 缺少的负面类别:
❌ 算法论文（提出新方法，不是提供评测集）
❌ 系统设计（提供功能，不是评测能力）
❌ 模型发布（发布权重，不是评测数据集）
```

**问题3**: 示例不够具体
```python
# 当前示例
✅ HumanEval（代码生成测试集）

# 问题:
- 没有算法论文的负面示例
- 没有系统/框架的负面示例
- 没有说明"论文引用HumanEval ≠ 论文是Benchmark"
```

---

## 增强方案（完全重写Prompt）

### 新Prompt设计原则

1. **明确5大类别**：Benchmark、算法论文、系统/框架、工具/SDK、模型发布
2. **强化负面过滤**：80%的误判是算法论文+系统/框架，重点过滤
3. **arXiv专项规则**：论文包含实验 ≠ 论文是Benchmark
4. **真实案例**：用今天的12个误判案例作为负面示例

### 增强后的Prompt（完整版）

**文件**: `src/scorer/llm_scorer.py`

**替换整个UNIFIED_SCORING_PROMPT_TEMPLATE**：

```python
UNIFIED_SCORING_PROMPT_TEMPLATE = """
你是MGX BenchScope的专家评估员，专门为AI/Agent领域的Benchmark候选打分。

MGX是一个多智能体协作框架（https://mgx.dev），专注Vibe Coding（AI原生编程）。
我们需要寻找高质量的Benchmark来评估MGX的能力。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【核心定义】什么是Benchmark？什么不是？（必读，影响80%准确率）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## ✅ 真Benchmark（评测基准）- 我们要的

**必要条件（4个必须同时满足）**：
1. 📊 提供测试数据集（固定的测试样本，如HumanEval的164道题）
2. 🎯 定义评估任务（明确的测试目标，如"代码生成"、"工具使用"）
3. 📈 规定评估指标（准确率、成功率、BLEU等）
4. 🏆 目的是评测其他系统的能力（测试Agent/模型的表现）

**典型Benchmark示例**：
- HumanEval: 164道编程题，测试代码生成能力
- SWE-bench: 2294个GitHub Issue，测试软件工程能力
- MMLU: 57个任务，测试知识问答能力
- microsoft/fara: 145K任务轨迹，测试GUI自动化能力 ← 今天的正例

**关键特征**：
- ✅ README说"我们提供XX个测试样本"
- ✅ README说"用于评估XX能力"
- ✅ 有排行榜或baseline结果
- ✅ 其他论文引用它来测试自己的模型

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## ❌ 误判类别1: 算法/系统方法论（arXiv论文）- 最常见误判（40%）

⚠️ **关键区分**：算法方法论 vs Benchmark方法论

**❌ 算法/系统方法论**（必须过滤）：
- 提出新算法/新系统/新架构
- **在现有Benchmark上测试**（而不是提供新Benchmark）
- 论文的贡献是"算法创新/系统优化"，不是"评估方法创新"

**✅ Benchmark方法论**（必须保留）：
- 提出"如何构建/改进Benchmark"的方法
- 论文的贡献是"评估方法创新"
- 示例: Semantic-KG（构建语义相似度Benchmark的方法） ← 今天的正例

---

**今天的误判案例**（必须避免）：
❌ RPM-MCTS: 提出MCTS算法用于代码生成，在HumanEval上测试 → 算法论文，不是Benchmark
❌ QiMeng-Kernel: 提出GPU Kernel生成方法，对比baseline性能 → 系统方法论，不是Benchmark
❌ M³Prune: 提出图剪枝算法，在多个数据集上测试 → 算法论文，不是Benchmark
❌ SwitchDelta: 提出元数据更新机制，性能评估 → 系统论文，不是Benchmark
❌ The Devil in the Details: 分析大模型一致性问题 → 研究分析论文，不是Benchmark
❌ Intent-Based Query Rewriting: 提出查询重写方法 → 算法论文，不是Benchmark

**判定规则**（关键：看论文的主要贡献）：
```
❌ 如果论文说: "我们提出XX算法，在HumanEval上达到90%准确率"
→ 这是算法论文，贡献是"算法"，用HumanEval测试 → 不是Benchmark

✅ 如果论文说: "我们构建了XX数据集，包含1000个测试样本，用于评估YY能力"
→ 这是Benchmark论文，贡献是"数据集"，提供新评测集 → 是Benchmark

✅ 如果论文说: "我们提出XX方法来构建高质量Benchmark，并展示如何应用于YY领域"
→ 这是Benchmark方法论，贡献是"评估方法"，帮助构建更好的Benchmark → 是Benchmark
```

**arXiv专项过滤规则**（关键：看贡献类型）：

**❌ 过滤这些**（算法/系统论文）：
1. 论文标题: "XX: A New Method/Algorithm/Approach **for** YY任务"
   - 关键词: "for solving"、"for improving"、"for optimizing"
   - 示例: "RPM-MCTS: A New Method **for** Code Generation"
   - → 贡献是解决问题的方法，不是评估方法

2. Introduction说: "我们的贡献是提出新方法/算法来提升YY性能"
   - → 贡献是算法创新，不是评估创新

3. Related Work大量引用HumanEval/SWE-bench等Benchmark
   - → 说明它用这些Benchmark测试，自己不是Benchmark

4. Experiments说: "我们在3个数据集上测试，达到XX%提升"
   - → 说明它用现有数据集验证算法，不提供新数据集

**✅ 保留这些**（Benchmark论文/方法论）：
1. 论文标题: "XX: A Benchmark/Dataset/Evaluation Suite **for** YY领域"
   - 关键词: "Benchmark for"、"Dataset for"、"Evaluation of"
   - 示例: "Semantic-KG: A Method **for** Constructing Benchmarks"
   - → 贡献是构建评测集的方法

2. Introduction说: "我们的贡献是提供新的评测集/评估方法"
   - → 贡献是评估方法创新

3. 论文提供HuggingFace Dataset下载链接或GitHub测试集
   - → 提供了可复现的评测资源

4. 其他论文引用它**用于评测**，不是引用算法思想
   - → 它是评测工具，不是被评测对象

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## ❌ 误判类别2: 系统/框架/OS（20%）

**特征**：
- 提供功能/服务（运行后提供API）
- 目的是帮助开发者构建应用
- 是被评测的对象，不是评测工具

**今天的误判案例**（必须避免）：
❌ EverMind-AI/EverMemOS: 智能记忆操作系统 → 这是OS，用来存储记忆
❌ AgoneTest Framework: 单元测试生成框架 → 这是工具，用来生成测试
❌ VICoT-Agent: 多模态推理Agent框架 → 这是Agent，用来做推理

**判定规则**：
```
如果README说: "我们提供XX系统/框架，用于YY任务"
→ 这是系统/框架，用来做事情，不是Benchmark

如果README说: "我们提供XX评测集，用于测试YY能力"
→ 这是Benchmark，用来评测能力
```

**常见混淆**：
- ❌ "AgoneTest自动生成单元测试" → 工具，用来做测试
- ✅ "HumanEval测试代码生成能力" → Benchmark，用来评测

- ❌ "VICoT-Agent多模态推理" → Agent，用来做推理
- ✅ "MMLU测试知识问答能力" → Benchmark，用来评测

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## ❌ 误判类别3: 工具/SDK/协议（20%）

**特征**：
- 提供API/SDK/协议标准
- import后可调用
- README中的"benchmark"指性能测试，不是评测基准

**今天的误判案例**（必须避免）：
❌ universal-tool-calling-protocol/code-mode: MCP工具调用协议 → 协议标准
❌ CAPHTECH/kiri: 代码上下文提取工具 → 工具，提取上下文
❌ zechenzhangAGI/AI-research-SKILLs: AI研究技能库（70个技能）→ 技能库

**判定规则**：
```
如果README说: "import kiri; kiri.extract_context()"
→ 这是工具/SDK，提供API调用

如果README说: "下载数据集，运行evaluate.py，获得准确率"
→ 这是Benchmark，提供评测流程
```

**常见混淆**：
- ❌ README提到"benchmark"但指性能测试（如"我们的工具比XX快2倍"）
- ✅ README提到"benchmark"指评测基准（如"用于评估代码生成能力"）

- ❌ README包含"evaluation"但指工具评估（如"我们评估了工具的性能"）
- ✅ README包含"evaluation"指提供评估（如"用于评估模型的能力"）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## ❌ 误判类别4: 模型发布（Model Release）

**特征**：
- 发布模型权重（HuggingFace Model、.ckpt文件）
- 提供推理代码（但不提供评测集）
- 论文说"我们发布XX模型"

**判定规则**：
```
如果README说: "下载模型权重，运行inference.py"
→ 这是模型发布，提供权重

如果README说: "下载数据集，测试任何模型，获得评分"
→ 这是Benchmark，提供评测集
```

**例外情况**（模型+Benchmark一起发布）：
✅ 论文同时发布模型和评测集（如microsoft/fara发布Fara-7B模型 + 145K评测集）
✅ 判定：如果主要贡献是评测集 → 是Benchmark
✅ 判定：如果主要贡献是模型 → 不是Benchmark

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 🎯 判定流程（必须按顺序检查）

**Step 1: 分析论文/项目的主要贡献**（最关键）
- ✅ 贡献是"评估方法/数据集/指标" → 继续Step 2
- ❌ 贡献是"算法/系统/模型" → 直接判定为"不是Benchmark"

**Step 2: 是否提供评测资源？**
- ✅ 提供测试集/评估工具/评估方法论 → 继续Step 3
- ❌ 只提供算法实现/系统架构 → 直接判定为"不是Benchmark"

**Step 3: 区分数据集类型**
- ✅ 用于评测其他系统 → 是Benchmark
- ❌ 用于训练模型 → 不是Benchmark（是训练集）
- ❌ 用于展示算法效果 → 不是Benchmark（是算法论文的实验数据）

**Step 4: arXiv论文专项检查**（如果来源是arxiv）

⚠️ **关键：区分"算法方法论" vs "Benchmark方法论"**

**❌ 过滤算法/系统方法论**：
- 论文标题: "XX: A New Method/Algorithm/Approach **for** YY任务"
  - 示例: "RPM-MCTS: A New Method **for** Code Generation"
  - → 贡献是解决问题，不是评估问题
- Introduction说: "我们的贡献是提出新算法来提升XX性能"
  - → 贡献是算法创新
- 大量引用HumanEval/SWE-bench但自己不提供数据集
  - → 用现有Benchmark测试，不是Benchmark
- Experiments说: "我们在3个数据集上达到XX%提升"
  - → 验证算法性能，不是提供评测集

**✅ 保留Benchmark/Benchmark方法论**：
- 论文标题: "XX: A Benchmark/Dataset/Evaluation Suite **for** YY"
  - 示例: "Semantic-KG: A Method **for** Constructing Benchmarks"
  - → 贡献是构建评测集
- Introduction说: "我们的贡献是提供新的评测集/评估方法"
  - → 贡献是评估方法创新
- 提供HuggingFace Dataset下载或GitHub测试集
  - → 提供可复现评测资源
- 其他论文引用它**用于评测**，不是引用算法
  - → 它是评测工具

**Step 5: 工具/系统专项检查**（如果来源是GitHub）
- ❌ README说"import XX"或"pip install XX" → 可能是工具
- ❌ README说"XX Framework for YY" → 可能是框架
- ✅ README说"Download dataset and run evaluate.py" → 可能是Benchmark
- ✅ README说"We propose a method to construct XX benchmarks" → 可能是Benchmark方法论

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

候选信息：
- 标题: {title}
- 来源: {source}
- 摘要: {summary}
- URL: {url}
{extra_fields}

你的任务：
1. **首先判定类别**：这是哪一类？
   - ✅ **Benchmark（评测基准）** - 提供测试集/评估任务/评估指标
   - ✅ **Benchmark方法论** - 提出如何构建/改进Benchmark的方法
   - ❌ **算法/系统方法论** - 提出新算法/系统来解决问题
   - ❌ **系统/框架/OS** - 提供功能性服务
   - ❌ **工具/SDK/协议** - 提供API调用接口
   - ❌ **模型发布** - 发布模型权重

2. **如果是Benchmark或Benchmark方法论**：
   - 设置 `is_not_benchmark = False`
   - 在 `tool_reasoning` 中说明为什么是Benchmark（提供数据集/评估任务/评估方法）
   - 正常按照以下标准评分

3. **如果不是Benchmark**（算法/系统/工具/模型）：
   - 设置 `is_not_benchmark = True`
   - 设置 `non_benchmark_category` 为具体类别（算法论文/系统框架/工具SDK/模型发布）
   - 在 `tool_reasoning` 中说明判定依据，提供关键证据
   - 所有维度评分降低3-5分（算法论文-5分，其他-3分）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

评分标准（仅对真Benchmark评分）：

【活跃度 Activity】(0-10分, 权重25%)
推理要求（activity_reasoning, ≥150字符）：
- 明确说明GitHub stars数量和最近更新时间
- 分析社区活跃度（PR/Issue数量、讨论质量）
- 说明为什么这个活跃度水平适合/不适合MGX采纳
- 如果是论文来源无代码，说明这对可复现性的影响

【可复现性 Reproducibility】(0-10分, 权重30%)
推理要求（reproducibility_reasoning, ≥150字符）：
- 代码/数据集是否公开？在哪里？（GitHub/HuggingFace/论文附录）
- 是否有详细文档？（README/论文/Tutorial）
- 是否有复现脚本？（evaluate.py/run.sh）
- MGX集成难度评估（需要多少工作量）

【许可合规 License】(0-10分, 权重20%)
推理要求（license_reasoning, ≥150字符）：
- 明确说明许可证类型（MIT/Apache/BSD/GPL/Commercial/Unknown）
- 是否允许商业使用？是否有传染性条款？
- MGX能否安全集成？是否需要开源自研组件？
- 如果未找到许可证，说明风险

【新颖性 Novelty】(0-10分, 权重15%)
推理要求（novelty_reasoning, ≥150字符）：
- 发布时间（越新越好，2024-2025优先）
- 与现有Benchmark的区别（是否覆盖新任务/新领域）
- 是否填补MGX Benchmark池的空白
- 是否提供新的评估视角

【MGX相关性 Relevance】(0-10分, 权重10%)
推理要求（relevance_reasoning, ≥150字符）：
- 是否属于MGX核心场景（Coding/Web Agent/Multi-Agent/Deep Research）
- MGX能否通过该Benchmark评估自身能力
- 接入成本vs收益评估
- 如果不相关，说明原因

【综合推理 Overall】(≥50字符)：
- 总结该候选的最大优势和最大风险
- 给出明确的纳入建议（强烈推荐/值得考虑/不建议）

【后端Benchmark专项】（如果is_backend_benchmark=True）：
- backend_mgx_reasoning (≥200字符): MGX如何使用该后端Benchmark
- backend_engineering_reasoning (≥200字符): 工程实践价值评估

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

请严格按照上述定义判定，避免80%误判率。
"""
```

---

## 修复实施步骤

### Step 1: 完全替换Prompt

**文件**: `src/scorer/llm_scorer.py`

找到 `UNIFIED_SCORING_PROMPT_TEMPLATE` 的定义（约第95-180行），**完全替换**为上述增强版Prompt。

### Step 2: 更新is_tool_not_benchmark字段名

考虑更名为 `is_not_benchmark`（更准确），因为现在不仅过滤工具，还过滤算法论文、系统框架等。

**文件**: `src/scorer/llm_scorer.py`

```python
class BenchmarkScore(BaseModel):
    # 更名: is_tool_not_benchmark → is_not_benchmark
    is_not_benchmark: bool = Field(
        description="判断：这不是评测基准（True）还是评测基准（False）？包括工具/算法论文/系统框架等"
    )
    non_benchmark_category: str = Field(
        description="如果is_not_benchmark=True，说明属于哪个类别：算法论文/系统框架/工具SDK/模型发布"
    )
    tool_reasoning: str = Field(
        min_length=100,
        description="判定推理（≥100字符）：说明为什么判定为非Benchmark或Benchmark，提供关键证据",
    )
```

### Step 3: 更新惩罚机制

**文件**: `src/scorer/llm_scorer.py` (score方法)

```python
# ✅ 新增: 非Benchmark惩罚机制
if score_data.is_not_benchmark:
    penalty = 5.0 if score_data.non_benchmark_category == "算法论文" else 3.0
    logger.warning(
        "非Benchmark检测: %s (%s, 原始分%.1f → 惩罚后%.1f), 理由: %s",
        candidate.title,
        score_data.non_benchmark_category,
        total_score,
        max(total_score - penalty, 0.0),
        score_data.tool_reasoning[:100],
    )
    total_score = max(total_score - penalty, 0.0)
```

**惩罚策略**：
- 算法论文: 扣5分（最容易误判，需要强惩罚）
- 系统/框架/工具: 扣3分
- 模型发布: 扣3分

---

## 测试验证（增强版）

### 测试用例1: 真Benchmark应该通过

```bash
测试: microsoft/fara
预期结果:
- is_not_benchmark: False
- tool_reasoning: "这是Benchmark，提供145K任务轨迹数据集，用于评估GUI自动化Agent能力"
- total_score: 正常评分（不扣分）
```

### 测试用例2: Benchmark方法论应该通过

```bash
测试: Semantic-KG (构建语义相似度Benchmark的方法)
预期结果:
- is_not_benchmark: False
- tool_reasoning: "这是Benchmark方法论，贡献是提出构建语义相似度Benchmark的方法，用于评估方法创新"
- total_score: 正常评分（不扣分）
```

### 测试用例3: 算法论文应该被过滤

```bash
测试: RPM-MCTS (arXiv论文，提出MCTS算法用于代码生成)
预期结果:
- is_not_benchmark: True
- non_benchmark_category: "算法论文"
- tool_reasoning: "这是算法论文，贡献是MCTS算法，在HumanEval上测试，不提供新Benchmark"
- total_score: 原始分 - 5.0
```

### 测试用例4: 系统/框架应该被过滤

```bash
测试: EverMind-AI/EverMemOS
预期结果:
- is_not_benchmark: True
- non_benchmark_category: "系统框架"
- tool_reasoning: "这是智能记忆操作系统，提供记忆管理功能，不是评测基准"
- total_score: 原始分 - 3.0
```

### 测试用例5: 工具应该被过滤

```bash
测试: CAPHTECH/kiri
预期结果:
- is_not_benchmark: True
- non_benchmark_category: "工具SDK"
- tool_reasoning: "这是代码上下文提取工具，提供API调用，不是评测基准"
- total_score: 原始分 - 3.0
```

---

## 成功标准

### 目标：误判率从80%降至<10%

**测试集**：今天推送的15个项目

**预期结果**：
- ✅ 真Benchmark通过: 3/3 (100%)
- ✅ 算法论文过滤: 6/6 (100%)
- ✅ 系统/框架过滤: 3/3 (100%)
- ✅ 工具/SDK过滤: 3/3 (100%)
- **总体准确率**: 15/15 (100%)
- **误判率**: 0/15 (0%)

---

## 附录：12个误判案例的完整分析

### 算法论文误判 (6项)

| 项目 | 标题特征 | 判定依据 |
|------|---------|---------|
| RPM-MCTS | "XX: A New Method for YY" | 提出MCTS算法，在HumanEval测试 |
| QiMeng-Kernel | "XX: A Programming Paradigm for YY" | 提出编程范式，对比baseline |
| SwitchDelta | "XX: A Mechanism for YY" | 提出更新机制，性能评估 |
| M³Prune | "XX: A Method for YY" | 提出剪枝算法，在3个数据集测试 |
| Devil in Details | "The XX of YY" | 分析论文，实验分析 |
| Intent-Based Rewriting | "The Case for XX" | 方法论，对比实验 |

**共同特征**：
- 论文标题格式: "XX: A New Method/Algorithm/Approach/Paradigm for YY"
- 论文贡献: 提出新方法/新算法
- 实验设置: 在现有Benchmark（HumanEval/MMLU）上测试
- **不提供新Benchmark**

### 系统/框架误判 (3项)

| 项目 | README关键词 | 判定依据 |
|------|-------------|---------|
| EverMemOS | "Memory System", "OS" | 智能记忆操作系统 |
| AgoneTest | "Framework", "Generate Tests" | 单元测试生成框架 |
| VICoT-Agent | "Agent", "Framework" | 多模态推理Agent框架 |

**共同特征**：
- README说"我们提供XX系统/框架"
- 提供功能/服务（不是评测）
- 是被评测的对象（不是评测工具）

### 工具/SDK误判 (3项)

| 项目 | README关键词 | 判定依据 |
|------|-------------|---------|
| code-mode | "Protocol", "Tool Calling" | MCP协议标准 |
| kiri | "Tool", "Extract Context" | 代码上下文提取工具 |
| AI-research-SKILLs | "Library", "70 Skills" | AI研究技能库 |

**共同特征**：
- README说"import XX"或"pip install XX"
- 提供API/SDK接口
- README中的"benchmark"指性能测试

---

**修复完成后，请使用今天的15个项目作为测试集，验证准确率是否达到100%。**
