# RAG Debug Studio 操作 SOP

本文档对应当前 AITrans 的 `RAG Debug Studio` 实现。它是桌面端 Settings 中的本地 RAG 调试和检索评测工作台，不是文档导入/建库页面。

## 1. 适用范围与前置条件

开始前确认：

1. 已启动 AITrans 后端和桌面端。
2. Knowledge 页面中至少有一个文档处于可检索（通常为 `ready`）状态，并已经建立索引。RAG Debug Studio 读取当前本地索引；它不会因为导入 Dataset 而自动导入文档或重建索引。
3. 若要使用 Embedding、Reranker、Answer Generation 等能力，相关本地模型或 AI provider 配置必须已经可用。
4. 如修改了会影响索引的 RAG 配置，先完成文档重新分块/重建索引，再开始对比。

进入方式：桌面端 **Settings → RAG Debug Studio**。

## 2. Studio 中的五个页面

### Trace

用于单条 query 的逐阶段诊断。选择 RAG Config、Top K（1–100），可选 **Include optional answer generation**，点击 **Run trace**。

结果按以下阶段展示：

`Query → Rewrite → Dense Retrieval → BM25 Retrieval → Fusion → Rerank → Context Building → Answer Generation`

点击检索结果行可以查看真实 chunk 的 ID、来源、章节、页码、token 数、各阶段分数和完整文本。Trace 只观察一次检索运行，不会修改 Dataset。

Trace 页顶部的 **Live Capability Routing** 是 AI Chat 的路由/知识 grounding 记录，用于查看最近的聊天是否启用知识库、是否跳过 retrieval、使用了多少 chunks/evidence/citations，以及 verification 是否通过。

### Chunks

用于检查当前索引里的文档和 chunk。可以按文档或文本搜索，查看 chunk 的 parser、chunker、结构质量、页码、token、overlap、字符范围和完整文本。这里的 **Re-chunk & reindex** 会改变索引，属于索引维护操作。

### Datasets

用于创建、编辑、导入、导出和删除检索评测用例集。Dataset 与 Knowledge 文档索引是两套数据：

- Knowledge 文档/Chunks：被检索的事实来源。
- RAG Debug Dataset：用于判断检索结果好不好的一组 query 和人工标注。

导入成功后，左侧会显示 dataset 和 case 数量；选中 case 可编辑 Query、Query Type、Gold Chunk IDs、Expected Answer、Answerable、Tags、Notes。

桌面端导入时只需选择文件即可。若用脚本调用后端，上传内容不是 multipart，而是 JSON 请求体中的字符串：

```powershell
$content = Get-Content .\docs\examples\rag-debug-studio-dataset.json -Raw
$body = @{ name = "RAG Debug Studio demo"; description = "Local smoke set"; format = "json"; content = $content } |
  ConvertTo-Json -Depth 20
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/rag/debug/datasets/import `
  -ContentType "application/json" -Body $body
```

JSONL 的调用方式相同，只需把文件名和 `format` 改为 `.jsonl` / `"jsonl"`。

### Evaluation

选择 Dataset 和 RAG Config，点击 **Run evaluation**。报告展示 Recall@10、MRR、nDCG@10、No-answer accuracy，以及基于真实 `AUTO` 路由的七项 routing/evidence 指标。评测中的可回答 case 会额外强制进入检索，用来隔离检索质量；`no_answer` case 保留自动路径，用于观察拒答和漏检索。

路由指标的分母是固定定义的：Precision/Recall 使用 Dataset 的 expected retrieval label；Unnecessary Retrieval Rate 是预期不检索 case 中被错误触发的比例；Missing Retrieval Rate 是预期检索 case 中被跳过的比例；Scope Violation Rate 统计有明确 scope 时返回到 scope 外的候选 chunk；Second-round Retrieval Rate 以实际触发检索的 run 为分母；Evidence Sufficiency Rate 以实际 retrieval round 为分母，并由现有 deterministic evidence gate 的 `evidence_sufficient` 判定。

### Compare

选择同一 Dataset、Baseline profile 和 Candidate profile，点击 **Compare**。两套配置会运行同一批 query，页面展示每个 case 的命中排名、耗时和 Recall@10 变化。

## 3. Dataset 的准确含义

Dataset 是一组“检索问题（evaluation cases）”，不是 PDF、Markdown 或知识库文档本身。每个 case 至少需要：

| 字段 | 必填 | 作用 |
| --- | --- | --- |
| `case_id` | 是 | Dataset 内唯一 ID |
| `query` | 是 | 要测试的用户问题 |
| `categories` | 否 | `term`、`exact_identifier`、`cross_section`、`multilingual`、`multi_document`、`no_answer` |
| `relevant_chunk_ids` | 否 | 预期命中的 gold chunk ID；必须来自当前索引 |
| `relevance_grades` | 否 | `chunk_id → 非负整数`，用于 nDCG 等 graded 指标 |
| `claims` | 否 | claim 级标注，每项为 `claim_id` 和对应的 `relevant_chunk_ids` |
| `no_answer` | 否 | 没有足够证据时设为 `true` |
| `expected_retrieval` | 否 | 路由金标准：该 query 是否应该访问知识库；省略时按 `not no_answer` 推导 |
| `expected_scope_document_ids` | 否 | 路由允许访问的 document ID；省略时对可回答 case 回退到 `metadata.document_id`，支持用分号分隔多文档 |
| `expected_answer` | 否 | 人工参考答案；用于记录和后续人工核对，不是当前检索 Recall 的唯一依据 |
| `answerable` | 否 | `false` 会在导入时转换为 `no_answer: true`（建议直接写 `no_answer`） |
| `tags` / `notes` | 否 | 维护数据集时的筛选标签和备注 |

重要：`relevant_chunk_ids` 不是随意写的名称。请先到 **Chunks** 页复制实际 chunk ID，再填入 Dataset。示例文件中的 `demo-*` ID 是占位符；若当前索引不存在这些 ID，评测会合法运行但命中率会是 0。

### 标注规则

- 可回答问题：填写至少一个 `relevant_chunk_ids`；可选填写 `relevance_grades`（例如 3=直接回答、2=部分支持、1=弱相关）。
- 不可回答问题：`no_answer: true`、`categories` 包含 `no_answer`，并且不要填写 `relevant_chunk_ids` 或 `relevance_grades`。
- 若 query 虽然可回答但不应访问知识库，显式写 `expected_retrieval: false`；若 query 必须检索，显式写 `expected_retrieval: true`。这样可以避免把 `no_answer` 当成唯一的路由标注。
- 有 workspace/document 边界的 case 应填写 `expected_scope_document_ids`。没有该字段的旧 Dataset 仍可运行，但会对可回答 case 尝试使用 `metadata.document_id` 作为兼容回退。
- 同一 Dataset 内 `case_id` 必须唯一；同一 case 内 chunk ID 和 claim ID 不要重复。
- `categories` 使用当前后端允许的值，不要使用旧评测文件中的 `translation`、`reading` 等业务分类名。

## 4. JSON 与 JSONL 导入格式

### JSON

JSON 文件必须是 case 数组：

```json
[
  {
    "case_id": "case-001",
    "query": "问题文本",
    "categories": ["term"],
    "relevant_chunk_ids": ["真实_chunk_id"],
    "relevance_grades": {"真实_chunk_id": 3},
    "expected_retrieval": true,
    "expected_scope_document_ids": ["真实_document_id"],
    "expected_answer": "参考答案",
    "answerable": true,
    "tags": ["smoke"],
    "notes": "备注"
  }
]
```

导入器也接受 `{ "cases": [...] }` 或 `{ "data": [...] }` 包装形式，但推荐使用数组根节点，最容易与导出文件互换。

### JSONL

JSONL 每行一个完整 JSON 对象，不能把整个文件包在数组里：

```jsonl
{"case_id":"case-001","query":"问题文本","categories":["term"],"relevant_chunk_ids":["真实_chunk_id"],"relevance_grades":{"真实_chunk_id":3}}
{"case_id":"case-002","query":"没有证据的问题","categories":["no_answer"],"no_answer":true}
```

空行会被忽略，以 `#` 开头的行也会被忽略。文件扩展名为 `.json` 或 `.jsonl` 时，桌面端会自动选择导入格式；API 也可显式传 `format: "json"` 或 `format: "jsonl"`。

## 5. 推荐的日常操作流程

1. 在 **Chunks** 中确认文档状态为 ready，复制要测试的真实 chunk ID。
2. 复制示例 Dataset，替换所有 `demo-*` ID，并删除不属于当前索引的 case 或改写 query。
3. 打开 **Datasets → Import JSON/JSONL**，选择文件；导入后的 dataset 名默认取文件名。
4. 回到 **Datasets**，抽查每个 case 的 query、gold chunk、Answerable 和 no-answer 标记。
5. 进入 **Trace**，先用 1–2 条 query 观察 Query、Dense、BM25、Fusion、Rerank 和 Context 是否符合预期。
6. 在 **Evaluation** 运行整套 Dataset，记录 Recall@10、MRR、nDCG@10、No-answer accuracy 和七项 routing/evidence 指标；若路由指标异常，先查看 Dataset 的 expected retrieval/scope 标注，再查看 Trace 中的 Knowledge Decision 和 Knowledge Scope。
7. 若要调参：在 Trace 选择 profile，复制一个 config profile，调整 Dense/BM25/Fusion/Final top K 或 Small-to-big，保存后按提示重建索引（如标记为需要 reindex）。
8. 在 **Compare** 用同一 Dataset 对比 baseline 与 candidate；只有在同一批 case、同一索引状态下比较指标才有意义。
9. 需要归档时，在 Datasets 点击 **Export**；可选择 JSON 或 JSONL，导出的内容可再次导入。

## 6. 常见问题

**导入报 422 / validation error**：检查根节点是否为数组（JSON）或每行是否为对象（JSONL）、`case_id` 是否重复、`query` 是否为空，以及 no-answer case 是否同时包含 `no_answer` 分类且没有 gold chunk。

**评测全是 0**：通常是 gold chunk ID 与当前索引不一致。到 Chunks 页复制真实 ID；不要用文档标题、文件名或 evidence ID 代替 chunk ID。

**Trace 没有结果**：先检查 Knowledge 文档是否完成索引、当前 RAG profile 是否要求重建索引，以及 embedding/vector store/reranker 配置是否可用。

**修改 profile 后结果没有变化**：如果 profile 显示需要 reindex，先在 Chunks 对相关文档执行 Re-chunk & reindex，再重新运行 Trace/Evaluation。

**No-answer 指标异常**：确认不可回答 case 没有误填 `relevant_chunk_ids`；当前评测将“无 ranked chunks”作为 no-answer 命中条件。若需要判断“应该不检索”而不只是“没有答案”，请同时设置 `expected_retrieval: false`。

**Routing 指标显示为 0% 而不是未测量**：0% 表示报告已计算且该分母下没有命中；如果 Dataset 完全没有预期检索 case，Recall 和 Missing Retrieval 的分母为 0，结果按稳定契约返回 0%，应补充 `expected_retrieval` 标注。

## 7. 对应 API（脚本化使用）

桌面端调用的后端根路径是 `/api/rag/debug`：

- `GET /datasets`、`POST /datasets/import`：列出或导入 Dataset
- `GET /datasets/{dataset_id}/cases`：查看 case
- `GET /datasets/{dataset_id}/export?format=json|jsonl`：导出
- `POST /runs`、`GET /runs/{run_id}`：启动和查看 Trace
- `POST /evaluation`：评测 Dataset
- `POST /compare`：比较两个 RAG profile
- `GET /documents`、`GET /chunks`：查看当前索引

桌面端使用本地 API 和本地 `rag_debug_studio.sqlite3` 保存 profile、Dataset 与 case；Dataset 不会上传到第三方服务。
