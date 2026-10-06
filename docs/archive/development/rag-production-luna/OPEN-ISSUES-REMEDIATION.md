# 问题清单功能修复

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../../start.ps1)；最新检索修复见 [语义排序报告](../../../development/rag-semantic-ranking-2026-10-05.md)。

日期：2026-09-30。依据用户“先解决问题清单中的问题”和此前“功能优先、最小修改”要求实施；本轮修改 4 个生产文件、2 个直接测试文件和 3 个记录文件。原有 S06–S08 和其他用户改动保留。

## 已修复与修改范围

| 文件 | 必须修改的原因 |
|---|---|
| `backend/rag/graph/extractor.py` | 把无反馈的重复抽取改为一次错误反馈修复；反馈带上一份输出，二次 schema/原文校验不变。图提示升级 `graph-1.1.1`，自动形成新图版本，避免复用旧版本。 |
| `backend/services/research_memory_extraction_service.py` | 从原流程提取私有请求/校验方法，供图服务复用请求、异常处理和 draft 转换；公开 `extract` / `complete` 接口与普通记忆抽取单次调用行为保持。 |
| `backend/models/research_memory.py` | 校验错误增加关系序号及具体未声明名称，让模型知道修复哪些端点；校验条件不放宽。 |
| `backend/services/knowledge_access_router.py` | 非对象 proposal 显式进入现有异常回退，避免沿用上一轮成功诊断；选定文档边界保持。 |
| `tests/rag/graph/test_extractor.py` | 验证 JSON/端点/证据的有限反馈修复、持续错误仍失败、精确回源和 provider 错误不追加抽取重试。 |
| `tests/agent/test_knowledge_access_router.py` | 覆盖先成功、后非对象 proposal 的真实诊断残留问题与 scope 保留。 |
| `OPEN-ISSUES.md` / `STATUS.md` / 本报告 | 更新当前阻塞，澄清已修复的权重身份保护与历史失败记录，保存验证、成本和剩余输入。 |

抽取调用链：IndexService → GraphIndexer → GraphExtractor → GraphExtractionService → 现有 ResearchMemoryExtractionService/客户端。修复只在图服务的 schema/证据失败后调用；认证、网络等 provider 错误继续传播。每次抽取最多 2 次 complete；SDK 原有传输 timeout/retry 保持，未声称这是硬中断或 HTTP 请求总上限。持续失败仍由原生命周期逻辑保留旧 READY generation，不发布未校验图。

## 验证

先增加回归复现，再修改实现：6 个抽取反馈断言及 1 个路由诊断断言在旧实现失败，修复后通过。未删除校验或跳过测试。

```text
python -m pytest tests/rag/graph/test_extractor.py tests/agent/test_research_memory_stage17.py tests/agent/test_knowledge_access_router.py -q
48 passed in 6.10s

python -m pytest tests/rag/graph tests/rag/test_index_manifest.py tests/rag/test_retrieval_service.py tests/rag/test_knowledge_dependencies.py tests/agent/test_research_memory_reliability_stage17_3.py tests/agent/test_research_memory_agent_stage17_2.py tests/agent/test_knowledge_access_router.py tests/agent/test_knowledge_access_contract.py tests/rag/test_companion_rag.py -q
148 passed in 20.21s
```

两组存在重叠，不相加为不同用例总数。使用 `aitrans` 环境。6 个代码/测试文件的 Ruff 诊断逐项与 HEAD 比较：无新增；原模型文件 1 个 UP037、路由文件 5 个历史诊断保留。直接检查 extractor/service/两个测试通过；最终 diff 检查通过。

### 原失败段落与两篇完整 PDF

原 Attention 训练/Adam 段落固定文本 SHA-256：`030c401392130c40c3560b5448aab85f708493ddf088fb57bbc957009f25a1c1`。新提示返回 3 条严格原文证据 claim，验证通过。

真实 `deepseek-v4-flash`、Qwen3 embedding、pypdf、Qdrant/BM25/SQLite；隔离基准启用 Graph，应用默认 Graph 关闭。本轮沿用 S06 冻结 PDF 原文件。

| 文档 | 页 / chunk | 图导入 | 原文关系/span | 导入用时 | 重建用时 |
|---|---:|---|---:|---:|---:|
| BERT `1810.04805` | 16 / 70 | READY | 6 / 6 | 103.648 s | 5.523 s |
| Attention `1706.03762` | 15 / 26 | READY | 2 / 2 | 69.052 s | 3.712 s |

两篇均完成导入 → 复用 → 重建 → 删除。复用 complete 调用 0；重建切换 generation、同版本已验证缓存复用，complete 调用 0，关系数量保持，旧版本边不在线可见。所有关系 span 解析回原文；删除后 graph_generation/entity/alias/chunk_entity/relation/relation_span 六表均 0 行。

BERT 文件 SHA-256：`5692a5514787a8c6727b4ff3b726a3385798bc68e12138d1d4af83947e2acf6e`。

Attention 文件 SHA-256：`bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697`。

最终复测 65 次 SDK complete 调用（含 6 次修复，均通过）、60 次缓存读取，API usage 实测输入 86,692 / 输出 44,553 token。前一次 `graph-1.1.0` 段落试验失败，2 次调用的输入 2,076 / 输出 1,169 token 另存；本轮合计 67 次调用、输入 88,768 / 输出 45,722 token。账单金额仍为 null，不能解释为 0。

缓存仅保存同 provider/model/提示/服务版本/源文本/元数据的真实已验证输出，不以金标生成结果。Graph 关系仅 6/2 条，说明当前严格谓词/实体规则保守；没有真实金标，不能判定漏召回比例或生产抽取质量。

可复跑脚本与结果位于本机 `data/benchmarks/issue-remediation/`：`replay_graph.py`、`failed-chunk-replay.json`、`graph-results.json`、`provider-attempts.json`、`probe-graph-1.1.0-attempts.json` 和对应日志。原 `data/benchmarks/s06/` 失败产物及 manifest 未覆盖。181 题 holdout 未运行。

## 清单处理结论

| 问题 | 当前结论 / 后续所需 |
|---|---|
| OI-003 | 实际权重指纹、防混用已在前轮修复；本轮纠正历史文字。默认发布 snapshot 仍需指定。 |
| OI-007 | 两篇完整论文的功能阻塞已解除，S06.4 生命周期功能门通过；真实抽取/消歧质量与预算仍未验收。 |
| OI-009 | 非对象 proposal 诊断残留已修复；真实路由/改写收益、无答案语料与回答验证保留。 |
| OI-001/002 | 仍缺脱敏真实文档、完整证据金标，以及业务门槛/预算。公开论文功能复测不能替代用户语料。 |
| OI-004/005/006 | 原质量门及 Sparse/RRF 坏例保留；按用户先前指示，本轮不调效果，不降低候选阈值。恢复效果优化后，优先同配置对照与 S09 既有 reranker。 |
| OI-008/009 超时 | 同步 get_chunk 和改写 complete 无调用方硬取消；现有协作 deadline/客户端 timeout 有效边界保持如实记录。线程等待超时无法终止底层操作，资源隔离/可取消接口需另行实施，不用线程包装假装硬中断。 |
| 人工 UI / 回答质量 | 未完成人工 Debug/Trace 点击；引用及 claim 验证属于后续 S10。完整生产门保持 BLOCKED。 |

## 开源/官方方案核对

[Microsoft GraphRAG 模型格式要求](https://microsoft.github.io/graphrag/config/models/) 强调可靠结构化输出，并指出可用提示/响应处理应对格式问题。本轮沿用现有模型接入和 source-span 设计，没有安装 GraphRAG/LiteLLM 或复制新框架。

[DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode/) 和 [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) 提供 JSON 格式约束；JSON 格式不代表端点/引用合法（根据当前 schema 的额外原文与引用校验推断）。本轮实际失败都是声明/原文校验，先使用有限反馈解决，不增加 AI 公共接口或依赖。

## 指纹

下表保存本轮实现和评测产物的 SHA-256；与原 S06/S07/S08 manifest 的历史实验分开读取。

| File | SHA-256 |
|---|---|
| `backend/models/research_memory.py` | `690396d232b472e940c9eb220475851e67ff84ec6ba67f66294bb5fed69f09c9` |
| `backend/rag/graph/extractor.py` | `2faccac1f72aa0528130987de491fb0892e2c8a95f365f0b56afc0ed378ddbf0` |
| `backend/services/research_memory_extraction_service.py` | `1ed63c7bb162ab0c9b3638c7b2aeb87eaa8258dd785be94b3d16f1311674d35f` |
| `backend/services/knowledge_access_router.py` | `8846c9a1f3d9fbf179e38ac60e9d218fe688a01490ecef5b23c9e05219676cec` |
| `tests/rag/graph/test_extractor.py` | `7db139718deb00ea361a9e02754a4b353bf8a2630743e82c96e4ccf660a37465` |
| `tests/agent/test_knowledge_access_router.py` | `d71cb36364a03821fe7414d00a07fa7a3ed72324a471c9bceeb3c5dfa9a601af` |
| `data\benchmarks\issue-remediation\replay_graph.py` | `1578b758b55fb3e4f2d31c1a322661df533ee56dacac8047defb7267c9997437` |
| `data\benchmarks\issue-remediation\failed-chunk-replay.json` | `9d7152a99a4b2021888604e7ff60ce54553a4e34be34854dad1e1f551f865047` |
| `data\benchmarks\issue-remediation\graph-results.json` | `75945ea471c1d3b33c28ae94bc4b1e9b722a2603644e416de8fec18503822a3a` |
| `data\benchmarks\issue-remediation\provider-attempts.json` | `ebb6b7ab6399f9b0093f72c5800bf4ab6d2a062c646ee0d012c82fbd565268de` |
| `data\benchmarks\issue-remediation\probe-graph-1.1.0-attempts.json` | `cb81d3bd7ece78c0060e18a53adb7b0e071a8b58ac24ec63f487fdd1ff2c47e1` |
