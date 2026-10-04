# 功能收尾：架构、运行边界与回滚

日期：2026-09-30。用户确认效果验收暂缓；本文件记录决定，不宣称生产发布通过。验收证据见 [最终功能报告](final-benchmark.md)。

## 最小修改决定

- 保留现有 IndexService/manifest 原子发布、Qdrant Local、BM25 JSON、Graph SQLite 与已有 RRF/模型。新增坏例快照复用 Debug SQLite，不另建数据库或框架。
- 修复真实缺陷：完整 rerank 池测量、切片原文锚点、context引用allowlist、引用前源存在/存活版本、Graph调试配置克隆、StrictMode页面不结束。其他能力作为兼容扩展，不做依赖升级和无关 Agent 重构。
- 沿用已有 sentence-transformers CrossEncoder。已安装5.7.0实现支持Qwen3的LogitScore路径；真实0.6B重排运行通过，无需重写推理或新增技术栈。
- Graph扩展和Qwen3调用的截止时间属于协作检查；在调用返回后拒绝晚结果。**它们不提供线程/native/GPU硬取消**，不得用deadline配置宣称请求时延被严格限制。
- 默认 Graph/新Router继续关闭，原有rewrite默认true及重排池保留。新 embedding_cache_size默认0，channel_deadline_ms、reranker deadline/max_input_tokens默认None。只在隔离功能测试中启用缓存/图/token上限。
- Embedding缓存有界LRU与TTL，key绑定query/scope/active generations/model/query version。发布或删除后新版本不会命中旧键；不缓存检索结果，避免额外过期引用风险。首次并发miss尚无singleflight。
- BadCase/Trace默认脱敏，不伪造原文回放。完整重放需要显式保存原文、旧索引、有效config/model指纹；缺任一项失败，不自动换用新版。固定修复状态必须有根因/commit/回归测试。
- 固定功能测试及fixture的SHA按CRLF→LF规范化，跨Git检出保留同一内容指纹；真实原文件和模型权重仍按原始bytes SHA审核。

## 存储迁移决定

1000次并发4小型混合检索无未预期异常，已有调用点与一致性保护工作。没有数据支持立即迁移，因此保留三种现有存储。该实验**没有验证生产容量或多进程能力**；若未来代表性大库实测出现锁/内存/P95瓶颈，再做Qdrant Server adapter或BM25/Graph服务化配对试验，先保留旧后端和回滚开关。

## 许可证与复用记录

本轮未复制第三方项目源码、未新增或升级依赖；合成图抽取fixture为本项目此前S07真实provider输出，原文是项目自建短句。公开数据沿用此前下载和许可记录，不把合成输入当用户数据。

| 现有组件 | 本机版本/来源 | 已核验许可 |
|---|---|---|
| sentence-transformers | 5.7.0，本机distribution的License-Expression及LICENSE | Apache-2.0 |
| qdrant-client | 1.19.0，本机distribution metadata | Apache-2.0 |
| networkx | 3.6.1，本机distribution License-Expression及LICENSE.txt | BSD-3-Clause |
| torch | 2.13.0+cu130，本机distribution License-Expression及LICENSE | 复合许可：Apache-2.0、LLVM-exception、BSD-2/3、BSL-1.0、MIT，沿用原包附带许可 |
| Qwen3-Embedding-0.6B | 本地snapshot `97b0c614…` README头部 | Apache-2.0 |
| Qwen3-Reranker-0.6B | 本地snapshot `e61197ed…` README头部 | Apache-2.0 |
| 既有HF数据 | S04-benchmark-manifest.json 的dataset_license_metadata | 本轮不新增数据或改变使用范围，保留原许可记录 |

模型README与包LICENSE已从现有本地文件读取；未依赖模型名称推断许可。商业分发应连同现有NOTICE/LICENSE保存，不把本轮功能验收当作法律结论。

## 操作及回滚

1. 使用 `aitrans` 环境和本轮冻结manifest，先运行64项固定功能回归；正式release另需全部生产门。目前不启用效果门，不使用holdout调参。
2. 所有实测runtime、逐题数据和截图位于隔离的 `data/benchmarks/rag-final/`。正常Knowledge数据目录未被测试runtime替换；临时开发服务和浏览器页已关闭。
3. 若启用了新增缓存或deadline，先在调用方配置设置cache_size=0、deadline=None/max_input_tokens=None，退回原行为；保留故障错误记录。Graph/Router可以独立关闭，Graph关闭继续走已有Dense/BM25/RRF。
4. 发布回滚沿用IndexManifest既有旧generation保留/active pointer流程。删除时按document与generation清理各库；不要通过删完整数据目录“修复”。本轮未迁移生产存储。
5. 本轮尚未提交；后续提交时只暂存本轮报告中列出的RAG相关文件，保留原有Agent变更和删除。出现回归时回退已审核的专属RAG提交，不能重置整个共享工作区。
6. Debug新增快照表为附加表，旧配置/接口继续兼容。旧代码可忽略新表；回滚代码无需删用户Debug数据库。脱敏快照只用于诊断，原文重放遵守显式保留输入合同。

## 留给后续开发的明确缺口

恢复效果工作前必须先准备真实source/claim金标与独立人工协议，运行真实QASPER/原文件/未知文档分层、Graph/rewrite/候选池消融、校准judge、holdout和成本预算。随后才判断默认Graph/Router/池大小。

工程边界包括同步硬取消/多进程隔离、代表性长文档与大库负载、历史坏例缺版本、旧无span数据重建、完整answer事件与阶段绝对时间、Companion持久化与Agent缓存消费链。均见OPEN-ISSUES新增项；本轮没有把这些未完成项标为生产PASS。
