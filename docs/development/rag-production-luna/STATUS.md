# RAG Luna 执行状态

- 仓库：`mivaille777/AITrans`
- 分支：`electronrebuild`
- 本地基准提交：`3f39f81b377aa6e4618ee88ab0a25be8569a03c5`
- 执行计划：`D:\AITrans\AITrans-RAG-Production-Improvement-Plan-GPT6-Luna.md`
- S00.1：PASS
- S00.2：PASS
- S00.3：BLOCKED（已建立基线与数据/模型/索引/机器指纹；生产数据、经确认门槛、完整坏例回放缺失）
- 生产 Go/No-Go：BLOCKED；不得据此启用 Graph 默认值或宣称生产达标
- S01.1：PASS（只读检查三库 document/chunk/generation 差异；当前 generation 缺失会明确报告 incomplete）
- S01.2：PASS（manifest generation 状态迁移、active pointer、旧版保留和重启恢复）
- S01.3：PASS（Qdrant/BM25 generation 并存、定向读写删除）
- S01.4：PASS（校验后原子发布；检索只读取 active generation；失败清理半成品并保留旧版）
- S01.5：PASS（PDF/DOCX/HTML/TXT 导入、重导入、重启、删除与零残留）
- S01 Stage 门禁：PASS（工程一致性门；不代表生产质量门通过）
- S02.1：PASS（版本化 source span、Unicode codepoint 定位、旧 JSON 兼容）
- S02.2：PASS（Docling 低文本/页序/OCR/表格来源页诊断；空文档拒绝；真实三页 PDF 集成验证）
- S02.3：PASS（Chunk SourceSpan 集成；Qdrant/BM25 共 1312/1312 精确回源；错文本/错页失败关闭）
- S02 Stage 门禁：BLOCKED（缺真实用户文件及引用金标；已知论文集检索 P95 825.297 ms；生产阈值未批准）
- S03.1：PASS（embedding 指纹进入 provider 与 READY manifest；模型 ID/维度变化触发重建；Hugging Face snapshot revision 未包含，见 OI-003）
- S03.2：PASS（Qdrant search 前后按 allowlist 与 active generation 过滤；注入越权/过期 payload 均拒绝）
- S03.3：PASS（环境化 batch/warmup 配置；Frozen dev100 Vector Only、冷启动/内存、缩写/跨语言 bad cases、generation 排序 smoke 已完成，见 [S03.3.md](S03.3.md)）
- S03 Stage 门禁：BLOCKED（Vector Only Recall@5/MRR/nDCG@10 低于 S00 Hybrid；门禁语义、snapshot revision 和应用级 scope 接线仍未完成；用户 2026-09-30 明确授权使用 HF 数据评测并进入 S04）
- S04.1：PASS（scientific-v2、DOI/化学式/缩写/CJK 混排；固定标识符 Top-1 7/7；BM25 倒排计算）
- S04.2：PASS（tokenizer 版本迁移；重建/删除/重启/active scope；完整 SciFact 和中文 MedicalRetrieval 评测及坏例保存）
- S04 相对 Sparse/安全门：PASS（补测 S00 Sparse 原代码，冻结 QASPER dev100 Recall@5/10 持平、MRR/nDCG 上升；过期/越权候选 0）
- S04 完整 Stage 验收：BLOCKED（人工 Debug Studio UI 未核验；公开检索质量缺口见 OI-005；生产 Go/No-Go 仍 BLOCKED）
- 当前工程任务：S04 工程和公开数据评测已完成，报告见 S04.md；下一工程 ID S05.1 未开始
- Holdout：181 个问题、56 篇论文，已冻结、未运行、不得用于调参
- GitHub 写入：此前 S00–S03 已推送至 `fc0a5c6b`；本轮 S04 仅本地提交，代码提交 `6885677b`
- 工作区原有用户修改：保留；提交时只暂存任务书当前允许的文件

详细指标见 [S00.md](S00.md)、[S00.3.md](S00.3.md)、[baseline-manifest.json](baseline-manifest.json) 和 [gate.json](gate.json)。S01 汇总和子任务报告见 [S01.md](S01.md)、[S01.1.md](S01.1.md)、[S01.2.md](S01.2.md)、[S01.3.md](S01.3.md)、[S01.4.md](S01.4.md)、[S01.5.md](S01.5.md)；S02 汇总和子任务报告见 [S02.md](S02.md)、[S02.1.md](S02.1.md)、[S02.2.md](S02.2.md)、[S02.3.md](S02.3.md)；S03 子任务报告见 [S03.1.md](S03.1.md)、[S03.2.md](S03.2.md)、[S03.3.md](S03.3.md)；S04 汇总见 [S04.md](S04.md)、[S04.1.md](S04.1.md)、[S04.2.md](S04.2.md)、[S04-benchmark-manifest.json](S04-benchmark-manifest.json)。待用户提供/确认事项见 [OPEN-ISSUES.md](OPEN-ISSUES.md)。
