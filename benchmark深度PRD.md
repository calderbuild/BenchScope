 飞书 Benchmark 入口优化 PRD
                                                                                                                                                                 
  ———                                                                                                                                                            
                                                                                                                                                                 
  ### 1. 背景                                                                                                                                                    
                                                                                                                                                                 
  当前 BenchScope 已经具备多源采集 + LLM 评分链路，但在“候选质量”上遇到瓶颈：                                                                                    
                                                                                                                                                                 
  - 噪声来源：GitHub/Arxiv/HuggingFace 等主源里依旧混入非 Benchmark（工具/综述/教程）。                                                                          
  - 评分冗余：LLM 需要对明显无价值的样本做完整 reasoning，消耗大量 token 和时间。                                                                                
  - 飞书表容量有限，推理字段暂未上线，现阶段更需“宁缺毋滥”。                                                                                                     

  目标是对现有主链路“源头过滤 + 评分策略 + 排序写入”联动优化，提高高质量候选的占比，减少人工筛查压力。                                                           
                                                                                                                                                                 
  ———                                                                                                                                                            
                                                                                                                                                                 
  ### 2. 目标
                                                                                                                                                                 
  | 指标 | 当前 | 目标 |                                                                                                                                         
  | --- | --- | --- |
  | 预筛后入仓通过率（入库记录 / LLM 评分记录） | ~5% | ≥15% |
  | LLM 平均评分耗时 | ~40 分钟 / 80 条 | ≤30 分钟 |
  | 飞书入库低质记录（评分<4 或 relevance<5） | 偶发 | 0 |                                                                                                       
  | 日志可解释性（给出过滤/降级原因） | 弱 | 每条都有 FilterReason |                                                                                             

  ———
                                                                                                                                                                 
  ### 3. 范围（Scope）                                                                                                                                           

  在范围：                                                                                                                                                       
                                                                                                                                                                 
  1. 预筛选规则（src/prefilter/rule_filter.py + 采集器元数据）                                                                                                   
      - 利用已有 metadata（stars、pushed_at、keywords、license、has_code 等）强化过滤。                                                                          
      - 统一“非 Benchmark”判定：工具/教程/综述等明确降级。                                                                                                       
  2. LLM 评分策略                                                                                                                                                
      - Prompt 中新增结构化判断 is_benchmark / candidate_type。                                                                                                  
      - 对 score < 阈值的候选在进入飞书前再次过滤。                                                                                                              
      - 简化 reasoning 对于 non-benchmark（少写或标注 “非 Benchmark”）。                                                                                         
  3. 写入策略（飞书 + SQLite）                                                                                                                                   
      - 仅保留现有 26 列，摘要不截断，评分依据可放完整 reasoning。                                                                                               
      - 新增字段 FilterReason（本地 + 飞书）记录过滤/降级原因。                                                                                                  
      - 排序优先：P0 场景（Coding/Backend）优先写入；P2/Other 放低优先级或直接不写。                                                                             
  4. 监控 & Logging                                                                                                                                              
      - 打印各阶段过滤统计：rule_filter -> LLM -> Feishu。                                                                                                       
      - 针对 LLM fails / 重试次数，记录到日志，方便 tuning。                                                                                                     
                                                                                                                                                                 
  不在范围：                                                                                                                                                     
                                                                                                                                                                 
  - 新增数据源（Twitter、小红书等）。
  - 飞书字段扩展（推理字段暂不纳入）。                                                                                                                           
  - LLM 模型切换 / 并发架构调整。                                                                                                                                
  - Redis 等基础设施部署。                                                                                                                                       
                                                                                                                                                                 
  ———                                                                                                                                                            
                                                                                                                                                                 
  ### 4. 用户故事 & 需求分解                                                                                                                                     
                                                                                                                                                                 
  1. 预筛“超标/噪声”                                                                                                                                             
      - 作为运营侧，希望只看到真正的 benchmark 候选。                                                                                                            
      - 需求：rule_filter 根据以下规则过滤：                                                                                                                     
          - GitHub stars < 50 或 pushed_at > 90 天自动淘汰。                                                                                                     
          - README 出现 awesome/tips/tutorial/list 等关键词直接排除。                                                                                            
          - 缺 license + 缺数据 + 缺脚本 → 直接 is_benchmark=false。                                                                                             
          - Arxiv 标题/摘要不含 benchmark|dataset|evaluation|agent，且无 code 链接 → 排除。
  2. 打分“短路”                                                                                                                                                  
      - LLM 需快速判断是否 Benchmark；若 is_benchmark=false，不必写长 reasoning，只返回“不是 Benchmark 的理由”。                                                 
      - 新增结构化字段 candidate_type（Benchmark/Tool/Dataset/Paper/Unknown）。                                                                                  
      - LLM 评分后若 candidate_type != Benchmark 或 relevance < 5，进入“降级队列”，不写飞书。                                                                    
  3. 写入/排序                                                                                                                                                   
      - 只写当前飞书字段：保留 摘要 全文，不截断。                                                                                                               
      - 新增本地字段 filter_reason（保存在 SQLite 和日志，可选择映射到飞书“评分依据”附注）。                                                                     
      - 排序策略：                                                                                                                                               
          1. candidate_type == Benchmark                                                                                                                         
          2. relevance_score (P0 > P1 > P2 > Other)                                                                                                              
          3. novelty_score & activity_score 作为 tie-breaker。                                                                                                   
  4. 可观测性                                                                                                                                                    
      - rule_filter 输出统计：多少条因为“无license/无code/awesome list”被过滤。                                                                                  
      - LLM 阶段输出 is_benchmark 判定结果。                                                                                                                     
      - 飞书写入前打印 保留N条, 过滤M条 (原因...)。                                                                                                              
                                                                                                                                                                 
  ———                                                                                                                                                            
                                                                                                                                                                 
  ### 5. 方案设计                                                                                                                                                
                                                                                                                                                                 
  #### 5.1 rule_filter 增强                                                                                                                                      
                                                                                                                                                                 
  - 输入：RawCandidate + 原始 metadata（stars、language、license 等）。                                                                                          
  - 输出：FilterResult（should_keep + reason).                                                                                                                   
  - 规则集（按优先级执行，命中即返回 reject）：                                                                                                                  
      1. README / Title 包含 awesome|tutorial|tips|list|resources|catalog → reject("non_benchmark_keyword").                                                     
      2. source == github 且 stars < 50 → reject("low_star").                                                                                                    
      3. source == github 且 last_commit > 90 天 → reject("stale_repo").                                                                                         
      4. source == arxiv 且 title/abstract 无 benchmark|dataset|evaluation（正则）→ reject("no_benchmark_key").                                                  
      5. candidate.license_type is None & candidate.dataset_url is None & candidate.raw_metrics is None → reject("insufficient_metadata").                       
      6. candidate.source == huggingface 且 downloads < 100 → reject("low_usage_dataset").                                                                       
  - 保留：为 pass 的候选添加 filter_reason="passed_all_rules"。                                                                                                  
                                                                                                                                                                 
  #### 5.2 LLM Scoring 调整                                                                                                                                      
                                                                                                                                                                 
  - Prompt 中新增要求：                                                                                                                                          
                                                                                                                                                                 
    "is_benchmark": true/false,                                                                                                                                  
    "candidate_type": one of ["Benchmark","Tool","Dataset","Paper","Unknown"],                                                                                   
    "filter_reason": string (e.g., "Only a theoretical paper with no code")
  - 如果 is_benchmark=false，五维分数可设为 0 或默认值，但 reasoning 只需说明为何不是 Benchmark。                                                                
  - _parse_extraction 将这些字段写入 ScoredCandidate，供后续流程二次判断。                                                                                       
                                                                                                                                                                 
  #### 5.3 排序 / 写入策略                                                                                                                                       
                                                                                                                                                                 
  - 在 storage_manager 写飞书前执行：
      - 仅保留 candidate_type == Benchmark && relevance >= 5 && total_score >= 5。                                                                               
      - 其他候选写入 SQLite 兜底 + 日志，不入飞书。                                                                                                              
  - 摘要：取消 300 字截断，直接使用清洗后的全文（仅移除 Markdown/HTML）。                                                                                        
                                                                                                                                                                 
  #### 5.4 监控                                                                                                                                                  
                                                                                                                                                                 
  - 在日志和飞书“评分依据”中附加 filter_reason。                                                                                                                 
  - 每个阶段输出统计：

    [rule_filter] 输入82，过滤80（awesome=12, low_star=30, ...），输出2                                                                                          
    [LLM] 输入2，is_benchmark:true=1 false=1                                                                                                                     
    [Storage] 飞书写入成功1条，降级写SQLite 1条                                                                                                                  
                                                                                                                                                                 
  ———                                                                                                                                                            
                                                                                                                                                                 
  ### 6. 迭代计划                                                                                                                                                
                                                                                                                                                                 
  | 阶段 | 任务 | 产出 | 负责人 |                                                                                                                                
  | --- | --- | --- | --- |                                                                                                                                      
  | Sprint 1 | rule_filter 实现 + metadata 接入 + 日志统计 | 新版过滤模块 | 开发 |                                                                               
  | Sprint 2 | LLM Prompt & schema 更新 + 解析器调整 | 新字段（is_benchmark 等） | 开发 + LLM 调优 |                                                             
  | Sprint 3 | 写入策略优化（排序、阈值、摘要）+ Feishu 逻辑更新 | 干净的飞书入库 | 开发 |                                                                       
  | Sprint 4 | 验收 & 指标复盘（≥15% 通过率）+ 文档更新 | 优化报告 | 开发+运营 |                                                                                 

  ———                                                                                                                                                            
                                                                                                                                                                 
  ### 7. 成功标准回顾                                                                                                                                            
                                                                                                                                                                 
  - rule_filter & LLM 共同作用后，飞书写入率约为评分条目的 15% 以上。                                                                                            
  - 低质量候选（total/relevance <5）不再出现在飞书表。                                                                                                           
  - 摘要、评分依据都为完整文本，且日志中能看到清晰的过滤原因。                                                                                                   
                                                                                                                                                                 
  如确认没有遗漏，可以按 PRD 拆分任务进入开发。需要我先实现其中某个子模块（如 rule_filter、新 prompt），随时告知。
 