# RAG 语义排序坏例分析与修复

日期：2026-10-05。工作区：`D:\AITrans`。在已有 FAISS 迁移及上一轮内容完整性修复之上增量修改，保留已有工作区修改。未提交、推送、重建资料库或改用户配置。

**坏例已在用户启用的实际查询规划 → 本地检索/重排 → 多查询合并 → 引用上下文流程中修复。固定核心集由 17/18 个完整问题、52/53 条证据要求提升至 18/18、53/53；原问题及五个中英文同义问法由 3/6 提升至 6/6。**这是本地小型集的检索验收，不能外推为任意文献或最终生成答案的质量保证。

## 评测口径

沿用[上一轮报告](local-rag-completeness-2026-10-05.md)的三份资料、469 个有效块及首次检索前固定的 18 个问题、53 条 gold 要求。原文件 SHA-256、有效 generation、块 ID、引文 hash 和原文锚点没有调整。仍只读取有效版本，不把退休版本或邻段算作独立引用。

本轮基线为上一轮修复后的系统，使用旧 planner 1.4.0、原 Top8 重排准入及原多查询 RRF 截断。最终系统使用 planner 1.5.0 和下面三项修改，其余本地模型、索引、dense/sparse/fusion/final 数量及作用域一致。

补充测试族共六种问法，包含原始坏例，全部指向同一条固定事实：

1. 水箱论文为何需要限制 PID 增益变化？
2. 文中为何要约束 PID 增益更新？
3. 为什么需要给 PID 增益的变化设置边界？
4. Why does the water tank paper require limiting changes in PID gains?
5. Why should changes to PID gains be bounded?
6. Why are PID gain updates constrained in this paper?

另对原问题独立采集三组新 planner 响应。三个组分别计数；核心集、同义问法族和重复组包含相同问题/事实，不能相加当作独立样本。

向实际配置的远程 planner 仅发送问题，未发送资料正文或 gold。旧/新 planner 共 27 对真实响应冻结为 `semantic-ranking-plans.json`，之后离线复放，避免每次消融重新生成查询造成混淆。复放经过实际 `CompanionChatService.prepare_knowledge`，使用真实 Qwen embedding、Qwen3-Reranker-0.6B、FAISS 和 BM25，检查最终可引用证据，而非只检查某个候选池。

## 原因与排除证据

坏例 `wen-safety` 的 gold 位于原文章节 `4. Conclusions and perspectives`。它解释了 LLM 增益更新缺少安全约束、骤变可能导致过激控制，以及对更新设界限的必要性。原段完整存在于有效索引；原始中文问题的 dense Top30 与 BM25 Top30 都没有覆盖它。这一轮故障发生在相关性检索和排序，而非资料未入库。

固定九段候选（上一轮最终八段加 gold）的真实模型诊断中，原始问题把 gold 排到 9/9，相关性原始 logit 差为 -3.9375。去元数据仅用正文、清理空白/软连字符、通用科学检索指令均未解决；换正确文章标题及单独加入邻段仍排末位。保留正文和候选，去掉已由 scope 确定的“水箱论文”选择语后，gold 升至 4/9；加邻段的该问法升至 1/9。

上述对照支持的推断是：当前模型对这种问法更偏向匹配文档主题/控制现象，未充分匹配“为什么限制参数更新”的关系。没有做注意力归因，不能把该推断说成已证明的模型内部机制。

CrossEncoder 已正确加载因果语言模型、yes/no LogitScore 和对应 chat template；诊断的 gold 输入仅 262 tokens，未被截断。调用符合 [Qwen 官方模型卡](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B#using-sentence-transformers)。因此保留推理实现和原文；原始分数也不作为概率或修改置信度。

修复过程中进一步确认两个确定性的截断问题：

- 第四种英文问法的互补查询 `Why are updates to PID controller gains bounded or rate-limited?`，gold 在 dense 第 26、BM25 第 14、融合第 10。旧 Top8 准入让重排器根本看不到它；将既有融合池 20 条交给重排后，gold 排第 3。
- 原始中文问题的互补查询 `Why are updates to PID gains constrained or bounded?` 将 gold 排到最终子查询的第 3。另两轮没有返回它；旧多查询 RRF 偏向共同命中的主题段，将它合并到第 9，再被最终 Top8 删除。保留互补查询覆盖后，gold 位于最终证据第 8，进入引用上下文。

## 保留的三项修改

| 修改 | 具体实现 | 高置信度依据 |
| --- | --- | --- |
| 保留解释关系的查询规划 | planner 1.5.0 保留操作、条件、否定及约束关系；非英语解释请求生成英语问题及一个互补问题。仅在调用方确认单文档 scope 时，去除有界、显式的文档选择前缀供规划使用；以参数更新的约束/边界表达限制变化，不加入预设原因或答案 | 同一冻结问法族，单独改规划从 3/6 到 5/6；固定候选去选择语的真实模型对照支持该方向。原问题始终参与第一轮，字面缩写/引号标题丢失时不裁剪，多文档/全库作用域仍用原问题 |
| 解释类问题看完既有融合池 | 无显式 `rerank_candidate_k` 时，why/how/explain 等解释意图重排既有融合池，当前 20 条；最终仍最多 8 条。显式配置优先，精确关键词/引号标题查找维持原准入 | gold 在融合第 10、扩大准入后重排第 3的真实轨迹，直接证明旧截断阻止了正确重排；相同冻结计划的消融证实收益。日志新增 `rerank_pool_policy` 可审计 |
| 合并保留互补查询证据 | 在最终 8 条预算中为每轮高排名证据保留覆盖；重复头部腾出的空间允许一起加深各查询前缀，再按原 RRF 填满与排序。按 generation + chunk_id 去重，保留原分数 | 正确证据子查询第 3 → 旧合并第 9 → 新最终证据第 8 的可重构轨迹；单独重排完整池仍失败的原问题，在加合并覆盖后通过。回归覆盖重复头部、版本隔离及预算不足 |

调用方在 Companion 与 Agent knowledge search 均传入单文档 scope 信号；文档 ID/过滤范围由调用方保持，不交给 planner 变更。最多三轮检索、dense/sparse 各 30、fusion 20、最终 8 和现有 30 秒 deadline 均保持。解释意图识别跳过引号内字面标题及 DOI，避免精确查找触发额外重排。

实现位于 `backend/rag/query_planner.py`、`fusion.py`、`query_router.py`、`retrieval_service.py` 以及两个调用方；没有把 PID、文档 ID、gold 块 ID 或预设安全原因写入生产规则。

## 消融与验收结果

六问法使用同一份冻结计划和相同有效索引。除标注的改动外均使用旧合并/Top8 准入：

| 组合 | 完整问法 | 剩余问题 |
| --- | --- | --- |
| 本轮基线 | 3/6 | 原问法及部分同义问法失败 |
| 仅新规划 | 5/6 | 第四种英文问法未进 Top8 重排池 |
| 新规划 + 合并覆盖，仍 Top8 准入 | 5/6 | 同上，合并不能恢复未进重排的证据 |
| 新规划 + 解释类完整池重排，旧合并 | 5/6 | 原问题的正确证据被最终合并挤出 |
| 新规划 + 完整池重排 + 合并覆盖 | 6/6 | 本测试族全部通过 |

额外试过在每轮保留检索通道首条候选，单独组合仍为 5/6；最终组合去掉它仍为 6/6，因此已撤销。英语词干化只在忽略目录的 BM25 克隆上实验，未解决原问题，未修改生产 tokenizer、索引或依赖清单。早期简单翻译、无准确关系改写时扩大重排池也无效，详见前一轮记录。保留的是经消融支持的组合，不把扩大候选数本身当作解决原因。

| 最终实际流程评测组 | 本轮基线 | 最终代码 |
| --- | --- | --- |
| 固定核心集完整问题 | 17/18 | 18/18 |
| 固定核心集证据要求 | 52/53（98.11%） | 53/53（100%，限此集） |
| 原始问题 + 五种中英文同义问法 | 3/6 | 6/6 |
| 原始问题三组独立新计划 | 0/3 | 3/3 |

最终报告为 `semantic-ranking-final.json`，已在撤销通道首条保留之后用最终生产代码重新运行。各组范围越界、上下文预算违规、超过三轮或模型/通道/规划降级均为 0；manifest、生产 BM25 文件和 SQLite 的前后 SHA-256 不变。核心集此前通过的问题没有退化。

另外复测关闭改写的固定原始单查询，结果仍是 17/18、52/53，`wen-safety` 仍失败；其余通过项没有退化。这准确界定了修复范围：解决的是已启用规划的实际 RAG 流程，未声称改变了 Qwen 对原始问法的直接相关性排序。关闭改写、不同作用域、不同资料或未来新的 planner 响应不能直接沿用本轮 100% 指标。三次新计划验证只能支持这次小样本稳定性。

上下文仍按现有 4 字符/token 估算，默认 6,000 tokens；“预算内”不是最终生成模型的 tokenizer 计数。评测未生成或裁判最终回答。

## 耗时、回归与复现

本机 RTX 4060 Laptop 8GB，使用相同冻结新计划、已预热本地模型、六问法串行消融。每个问题各轮重排耗时之和的中位数由 Top8 的 **1.324 秒**变为解释类 Top20 的 **3.498 秒**；最大值分别为 1.721、3.764 秒。仅六个样本，不推断普遍 P95；该统计不包含远程规划和答案生成。最终证据数没有增大，新增计算用于让相关性模型判断现有候选。该延迟代价属于本轮保留修改的实际影响。

最终回归：**790 passed、1 skipped、5 deselected**，185.04 秒，JUnit 为 `semantic-regression.xml`。包含全部非 opt-in GPU 的 `tests/rag`、Agent 多查询/配置/Search-Read 和 LLM 依赖测试。skip 为未开启 Docling 模型集成；5 项 GPU 标记测试未执行，不计作通过。质量评测另行实际加载了 CUDA embedding/reranker。集合重叠，不与其他历史通过数累加。

Ruff 检查本轮 RAG 模块、评测脚本及相关 RAG 测试；语法和限定文件的 `git diff --check` 通过。两个调用方原有的不相关 lint 未纳入“全库通过”的承诺。

私人引文、冻结计划、诊断轨迹与 JUnit 均留在被 Git 忽略的 `test-results/local-rag-completeness/`。可使用已保存的固定 gold/计划离线重放：

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
& 'C:\Users\mivaille\anaconda3\envs\aitrans\python.exe' scripts/evaluate_local_rag_semantic_ranking.py --name semantic-ranking-final
& 'C:\Users\mivaille\anaconda3\envs\aitrans\python.exe' scripts/evaluate_local_rag_semantic_ranking.py --group variants --stages baseline,planner,merge,rerank,final --name semantic-ranking-ablation-retained
& 'C:\Users\mivaille\anaconda3\envs\aitrans\python.exe' scripts/evaluate_local_rag_completeness.py --name semantic-direct-final
& 'C:\Users\mivaille\anaconda3\envs\aitrans\python.exe' -m pytest tests/rag tests/agent/test_agent_multi_query_retrieval.py tests/agent/test_agent_runtime_config.py tests/agent/test_agent_knowledge_search_read.py tests/api/test_llm_dependencies.py -m 'not rag_gpu' -q
```

脚本校验 gold hash、来源文件/有效版本及冻结的新提示词；改变后直接报错，不静默重建或生成替代 gold。`--capture-plans` 才调用远程 planner，且仅在 HEAD 仍有已审计的 1.4.0 基线时允许；当前验收不需要重新采集或挑选响应。完整消融的旧 `channel` / `combined` 实验阶段只保留为历史诊断，新脚本只支持保留方案。

源码已修复，无需重建资料库。已运行的旧后端或旧打包 sidecar 尚未载入这些改动，需要重新载入更新后端；本轮未停止用户进程或覆盖发行包。
