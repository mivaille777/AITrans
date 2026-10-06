# S00–S04 问题整理与最小功能修复

> 历史归档（2026-10-06）：本文保留当时的方案、状态和验收结论，不代表当前启动方式或运行时配置。当前入口为 [start.ps1](../../../../start.ps1)；最新检索修复见 [语义排序报告](../../../development/rag-semantic-ranking-2026-10-05.md)。

日期：2026-09-30。基准：`570864be21148a6412d165f6a7b5def524b9d073`。

用户最新要求：以功能正常为验收目标，暂缓效果提升并尽快收尾。此次只补现有链路的缺口；检索默认配置、分词规则和 Graph 开关保持原值。

## 1. 问题、方案与执行结果

| 来源 | 问题及证据 | 最小解决方案 / 结果 |
|---|---|---|
| S00 | 已知论文过滤的 QASPER 不能证明全库发现；缺生产金标、回答质量和业务阈值 | S04 已补完整 SciFact/Medical 全库评测。真实用户数据与回答质量验证保留在 OI-001/002，效果工作延期 |
| S00 | Debug dataset 将最终 ID 同时当作重排前 ID，导致重排收益被错误记成 0 | Trace 保存原始融合池排名；多查询按相同 RRF 规则合并原始排名，dataset 从 Trace 读取。真实 MRR 0.5→1 的回归用例已复现并修复 |
| S01 | 分步写库可能暴露半成品、旧版或残留 | 已有原子 generation 发布、失败保留旧版、删除/重启测试，继续保留，不新增存储层 |
| S02 | 回源锚点和真实解析的覆盖不足 | 已有 SourceSpan 与空文档拒绝等功能；真实用户扫描件/引用金标仍缺失，留待后续验证 |
| S03 | provider 有 fingerprint，但 IndexService 写的是合成指纹，复用只比模型名/维度 | 写入真实 provider 指纹，复用检查整个指纹；同名同维度的输入或权重变化会重新建 generation |
| S03 | 下载/加载模型未固定实际内容身份 | 摘要覆盖实际权重、模型/分词配置、输入上限和精度；每个 provider 计算一次，加载绑定到同一已解析目录。兼容旧 manifest 字段 |
| S03 | 新查询向量可能与旧权重生成的同维度向量混用 | Dense 只查询指纹匹配的文档 generation；不匹配时提示重建，Hybrid 可降级 BM25 |
| S03/S04 | 单独启用一个通道且该通道失败时，原实现返回空“成功” | 全部已启用通道失败就抛出检索错误；成功但无匹配的空结果仍合法；正常降级保留 |
| S03 | Vector Only 与 S00 Hybrid 比较：R@5 0.6724 对 0.8161 | 是不同检索组合的差距；此次不改指标或门禁。新索引 Dense 的质量与原 Dense 基线相同 |
| S04 | 中文全库 BM25 P95 452 ms；质量不足 | 功能正常；预计算实验无排名回归，但按用户最终最小修改要求撤回优化，BM25 代码恢复原值 |
| S04 | Medical R@5 0.378；SciFact 有已记录的 0.00333 回退 | 保留质量问题，停止调优。分词实验和扩大重排池的结果见下，不启用失败方案 |

## 2. 已完成的报告分析

### BM25 已撤回实验记录

| 全库数据 | S04 → 本次 Recall@5 | MRR@100 | P95 ms：S04 → 本次 |
|---|---:|---:|---:|
| Medical，100,999 段 / 1,000 题 | 0.378 → 0.378 | 0.3264 → 0.3264 | 452.304 → 226.490 |
| SciFact，5,183 篇 / 300 test 题 | 0.7094 → 0.7094 | 0.6274 → 0.6274 | 16.652 → 8.433 |

上述为曾完成的性能实验，不是最终保留代码的性能承诺。Medical 逐题 Top-100 排名差异为 0。索引 JSON 大小不变；Medical 建索引时间约 15.888→24.364 秒。按用户最终要求撤回优化；BM25 生产文件无 diff。

Medical 的 Recall@100 只有 0.553，447/1,000 题的 gold 未进入 Top-100。因此，只重排现有候选无法把该组 Recall@5 提高到 0.80；后续需要验证语义/Hybrid 的全库增益。其收益目前未实测，不作保证。

### QASPER 同索引诊断

重建隔离索引，固定原 dev100/80 篇/1,312 chunks、模型快照和 query ID；质量统计为 87 个可映射 gold 问题，P95 为全部 100 题。关闭结构检索及 small-to-big，直接调用产品 RetrievalService，不调用生成器。

| 组合 | Recall@5 | Recall@10 | MRR（最多 Top20） | nDCG@10 | P95 ms |
|---|---:|---:|---:|---:|---:|
| Dense | 0.6724 | 0.9425 | 0.4640 | 0.5723 | 83.991 |
| BM25 | 0.6805 | 0.9069 | 0.4154 | 0.5237 | 6.003 |
| Hybrid RRF | 0.7184 | 0.9356 | 0.4753 | 0.5806 | 83.852 |
| Hybrid + rerank8 | 0.8161 | 0.8989 | 0.5181 | 0.6122 | 841.586 |
| Hybrid + rerank12 | 0.8126 | 0.9529 | 0.5351 | 0.6329 | 1009.577 |
| Hybrid + rerank20 | 0.8011 | 0.9448 | 0.5344 | 0.6285 | 1361.859 |

扩大重排池有成本和 Top-5 取舍，不能作为无条件的默认修复。默认池保持原值。Dense 指标与 S03.3 完全一致；rerank8 复现 S00 Hybrid 质量。

### 已停止的探索

完整 Medical corpus，固定 seed42 的 200 题开发子集：原 R@5=0.370；移除冗余单字为 0.350；单字权重 0.5/0.75 为 0.360/0.365。均未采用，也未对剩余 800 题继续调参。SciFact test、QASPER holdout 未用于选择参数；181 题 holdout 未运行。

## 3. 改动与兼容

- 5 个产品模块：embedding base/Qwen3、IndexService、RetrievalService、RagDebugService；另改 QASPER index adapter 的指纹写入与复用检查，以保持评测一致。
- 公共知识 API、候选模型、默认检索配置和 tokenizer 不变；没有新依赖。
- 旧索引缺完整指纹时，需要重建一次。正常重新导入会触发重建；期间 Hybrid 可使用现有 BM25，Dense Only 会明确报告需要重建。
- 模型内容摘要是实际运行身份。默认发布版本的选择与生产质量政策可后续决定，无需为本次功能修复更换模型。

## 4. 验证与产物

- 修复前：真实指纹写入、Debug 排名各 1 个失败用例；单通道失效共 2 个失败用例。
- 首轮完整 RAG / Agent / API / Debug / scope：464 passed、3 skipped；跳过项是显式 opt-in Docling、embedding、reranker 集成测试，真实 embedding/reranker 已用于上述 QASPER 诊断。
- 最后故障处理补丁：56 passed，8.15 秒，退出码 0；Ruff 检查通过。最后定向组覆盖 RetrievalService、generation、IndexService、embedding、Debug、Agent 和知识 API 合同。
- 撤回性能优化与无关格式 diff 后，只回放本次 8 个直接回归用例：8 passed，5.90 秒；最终 Ruff 与 git diff --check 通过。临时探针脚本和探针索引已删除，必要的评测记录保留。
- 索引写入/复用、同名权重变更、路径无关摘要、输入上限变化、旧权重 Dense 拒绝和 BM25 降级均有回归测试。
- 实验只使用 `data/benchmarks/s00-s04-repair/` 的隔离存储；原 S00/S04 结果和用户生产库保留。
- 本机逐题结果：`qasper-repair-results.json`、`results/{medical-dev,scifact-test}-current-results.json`；失败方案：`sparse-probe.json`、`sparse-weights-probe.json`。这些数据产物由仓库忽略规则排除。
- 本机复跑入口：`python data/benchmarks/s00-s04-repair/benchmark_qasper.py`；公开 BM25 使用现有 `scripts/run_hf_sparse_benchmark.py --dataset medical --split dev --root data/benchmarks/s00-s04-repair`（SciFact 对应 `--dataset scifact --split test`）。

## 5. 收尾结论

本轮功能修复：PASS，回归验证完成。效果、真实用户数据、回答/引用质量、人工桌面 UI 与 GraphRAG 的后续任务记录在 OPEN-ISSUES，生产质量门仍未通过。按用户最新指示，当前不继续效果实验或 S05。

参考：Hugging Face 的 [快照下载与缓存](https://huggingface.co/docs/huggingface_hub/en/package_reference/file_download)、Sentence Transformers 的 [模型加载合同](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html)、[Qwen3 Reranker 官方用法](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)。此次使用已有依赖，没有引入其他 RAG 框架。
