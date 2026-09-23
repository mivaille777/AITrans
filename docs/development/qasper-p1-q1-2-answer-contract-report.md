# QASPER P1 Q1-2：直接答案与弃答协议报告

> 状态：实现与真实运行完成；格式/指标门槛通过，人工事实质量门槛未通过，不晋级为默认策略。代码提交：`b0cd1e4999be089ecd6d30ce4b6565c49bac275c`（`WebReBuild`）。

## 交付内容

- 新增版本化 contract：`p1q2-direct-answer-v1`。模型响应含 `answer`、`answer_type`、`citations`、`supporting_explanation`；评分字段只保存简短直接答案，用户可见字段另行展示答案、说明和有效引用。
- 保存原始模型输出、contract 解析结果、Grounded verification 输入/输出及用户可见输出。运行时 answerer 改为接收不含 Gold 的 `QasperAnswerInput`；答案类型、Gold 答案及证据不进入 prompt。
- 运行审计新增 contract、引用 allowlist、解析回退与直接答案一致性检查；评估新增布尔正确率、错误弃答率、漏弃答率、contract 有效率和答案 token 字符估算。
- 固定 Smoke20 加 8 道布尔/不可回答挑战题，清单见 `backend/rag/benchmarks/qasper/sample_ids/validation-p1q2-smoke28-seed42.txt`。清单 SHA256：`f16837ff97ae9998ff16512ade014711ba57bb320fcbec0ae073aa3869a92830`。
- `p1q2-direct-answer-v2.json` 是一次未晋级的命题极性提示实验，不作为候选默认配置。其同题 Smoke28 Answer F1 相对 v1 差值为 -0.00287（95% CI [-0.09075, 0.05741]），Evidence F1、布尔正确率都未改善。

## 真实运行设置

- 数据：公开 QASPER v0.3 validation；source SHA256 `2ae7ee62a65b1c4225791c70de80c2aad4e8998cf1fd4f09a53103db4f21af93`。
- 回答模型：真实 DeepSeek `deepseek-v4-flash`。Dense、BM25、reranker 均实际执行；选证配置固定为 Q1-1 `p1q1-evidence-selection-v2`（SHA256 `23234a32c85878ad5b7baca32ff87d939914d7cfb1ac6a520eccb42ba1b75fc2`），与旧 contract 对照使用同一索引和 selected evidence。
- contract profile SHA256：`4d900f0fd6757c0fb8706c57dd414b45a34114642d42732caaf68392523adee6`。正式候选的 Smoke28/Dev100 manifests 均记录实现提交 `b0cd1e49`。

## Smoke28

Run：`p1q2-smoke28-contract-final-es-evidence-selection`。该清单包含 20 道固定 Smoke 题和 8 道冻结挑战题，共 28 题、24 篇论文；其中 10 道布尔题、4 道 Gold 不可回答题。

| 检查项 | 结果 |
| --- | ---: |
| 状态 / 运行错误 | complete / 0 |
| 实际 DeepSeek 调用 | 28/28 |
| Dense / BM25 / rerank 覆盖 | 28/28 |
| contract 有效 / 引用 allowlist 有效 | 28/28 / 28/28 |
| 无效引用 / selected offset 错误 | 0 / 0 |
| Grounded verification 安全回退 | 1 |
| 官方 Answer F1 / Evidence F1 | 0.41771 / 0.15236 |
| Boolean 正确率 | 5/10（0.50） |
| 错误弃答 / 漏弃答 | 4/24（16.7%） / 2/4（50.0%） |
| Answer generation p95 | 1824 ms |

运行审计 `ok=true`、issues 为空。1 次 verification fallback 与 contract 解析回退不同：contract 解析回退为 0；本次 fallback 按安全策略显示为 `Unanswerable`，已计入弃答行为指标。

## Dev100 同题比较

Baseline：`p1q2-dev100-legacy-es-evidence-selection`；candidate：`p1q2-dev100-contract-final-es-evidence-selection`。两次运行使用同一 100 个 question ID、source SHA、qrels SHA、Q1-1 profile、索引 fingerprint `83dcc5285e6c5a42b956aa56823081cb40355120c53372cd6cb7aae8fa767241`，并使用 seed 42、5000 次 paired bootstrap。Candidate 的 100 道题均由 DeepSeek 实际作答，审计 `ok=true`、0 错误、0 无效引用、0 offset 错误、100/100 contract 有效，解析回退为 0。

| 指标 | 旧 contract | 新 contract | 候选 - 基线 |
| --- | ---: | ---: | ---: |
| Answer F1 | 0.10466 | 0.42902 | +0.32436；95% CI [+0.25459, +0.39531] |
| Evidence F1 | 0.14524 | 0.14524 | 0.00000；95% CI [0, 0] |
| Gold Evidence Recall@10 | 0.97590 | 0.97590 | 0.00000；95% CI [0, 0] |
| MRR | 0.55496 | 0.55496 | 0.00000；95% CI [0, 0] |
| Unsupported Claim Rate | 0.48062 | 0.39130 | -0.08932 |
| Boolean 正确率（18 题） | 0/18（严格字符串判定） | 7/18（38.9%） | 有提升，但仍低 |
| 错误弃答 | 0/93 | 16/93（17.2%） | 增加 |
| 漏弃答 | 7/7（100%） | 1/7（14.3%） | 减少 |
| Answer 字符估算 token 均值 | 260.84 | 31.50 | provider 未提供原始 token 用量 |
| 用户可见字符估算 token 均值 | 260.84 | 136.28 | provider 未提供原始 token 用量 |
| Answer generation p95 | 2246 ms | 1699 ms | 同一运行环境 |

答案 F1 的增幅有一部分来自评分字段从长段落改为直接答案，不能据此推断事实准确率同幅提升。Evidence F1 与 Q1-1 selected evidence 完全不变；Unsupported Claim Rate 有下降，但仍未达到 Q1-3 的目标 `<=0.25`。

## 25 道布尔/不可回答题人工复核

复核范围是 Dev100 中全部 18 道布尔题和 7 道官方 `no_answer=true` 题。Gold 仅用于运行结束后的离线审查。标注存在多标注者分歧时，表中保留全部可接受标签。

| ID | 类型 | Gold | Candidate 直接答案 | 复核 |
| --- | --- | --- | --- | --- |
| `1f085b9b` | Boolean | No | Unanswerable | 错误弃答；旧回答也称证据没有说明是否使用 crowdsourcing |
| `fb2b536d` | Unanswerable | Unanswerable | Unanswerable | 正确弃答 |
| `10d45096` | Boolean | Yes | Yes | 正确 |
| `d27438b1` | Boolean | Yes | Yes | 正确 |
| `a99fdd34` | Boolean | No | Unanswerable | 错误弃答；旧回答给出 No |
| `e97186c5` | Boolean | No | Yes | 极性错误；旧回答同样给出 Yes（带有限定） |
| `cb196725` | Unanswerable | Unanswerable | Unanswerable | 正确弃答 |
| `7cd22ca9` | Boolean | Yes | Yes | 正确 |
| `b1cf5739` | Boolean | Yes | Unanswerable | 错误弃答；旧回答给出错误的 No |
| `06be47e2` | Boolean | No / Yes | No | 命中一位标注者答案；Gold 有分歧 |
| `133eb4aa` | Boolean | No | Unanswerable | 错误弃答；旧回答语义上给出 No |
| `1170e4ee` | Boolean | No | No | 正确 |
| `58ef2442` | Boolean | No | No | 正确 |
| `e5c8e9e5` | Boolean | Yes | Yes | 正确 |
| `007b13f0` | Unanswerable | Unanswerable | Unanswerable | 正确弃答 |
| `2c7494d4` | Boolean | No | Yes | 极性错误；旧回答也给出 Yes |
| `b1a068c1` | Unanswerable | Unanswerable | “覆盖多种年龄、性别和口音，但未列明口音” | 未按 contract 弃答；没有回答口音清单 |
| `d93c0e78` | Unanswerable | Unanswerable | Unanswerable | 正确弃答 |
| `902b3123` | Unanswerable | Unanswerable | Unanswerable | 正确弃答 |
| `7438b6b1` | Boolean | No | Yes | 极性错误；旧回答也给出 Yes |
| `3c3807f2` | Boolean | No | Unanswerable | 错误弃答；旧回答语义上给出 No |
| `b85fc420` | Boolean | Yes | Unanswerable | 错误弃答；旧回答给出 No |
| `1dc2da50` | Boolean | No / Yes | Unanswerable | 多标注者极性分歧；无法由 Gold 单一裁决 |
| `7d483077` | Unanswerable | Unanswerable | Unanswerable | 正确弃答 |
| `1dac4bc5` | Boolean | No | Yes | 极性错误；旧回答也给出 Yes |

本次 contract 让直接 Yes/No 更易评测，并减少漏弃答；但出现 16/93 错误弃答，且 7 道 Gold 不可回答题仍有 1 道没有明确弃答。人工复核发现多道 Gold No 被弃答或被答成 Yes。相较旧回答，至少 `a99fdd34`、`133eb4aa`、`3c3807f2` 从语义上有用的 No 退化成 Unanswerable。故未满足“布尔/不可回答题人工判断不得退化”的验收条件。Q1-2 仅作为可审计 contract 实现完成，不能将它宣布为 P1 质量晋级，也不能据此启动 P2。

## 复跑命令

在 `aitrans` 环境中运行。真实 LLM/GPU 运行保持 opt-in，原始回答、manifest 与审计文件位于被忽略的 `data/benchmarks/qasper/results/`。

```powershell
python -m pytest tests/rag/benchmarks/test_qasper_answer_contract.py tests/rag/benchmarks/test_qasper_runner.py tests/rag/benchmarks/test_qasper_protocol.py -q
python scripts/run_qasper_evidence_selection_ablation.py --mode smoke --limit 28 --seed 42 --question-ids-file backend/rag/benchmarks/qasper/sample_ids/validation-p1q2-smoke28-seed42.txt --quality-profile backend/rag/benchmarks/qasper/profiles/p1q1-evidence-selection-v2.json --answer-contract backend/rag/benchmarks/qasper/profiles/p1q2-direct-answer-v1.json --variants evidence_selection --suite-id p1q2-smoke28-contract-final
python scripts/check_qasper_run.py --run-directory data/benchmarks/qasper/results/p1q2-smoke28-contract-final-es-evidence-selection
python scripts/run_qasper_evidence_selection_ablation.py --mode dev --seed 42 --question-ids-file backend/rag/benchmarks/qasper/sample_ids/validation-dev100-seed42.txt --quality-profile backend/rag/benchmarks/qasper/profiles/p1q1-evidence-selection-v2.json --answer-contract backend/rag/benchmarks/qasper/profiles/p1q2-direct-answer-v1.json --variants evidence_selection --suite-id p1q2-dev100-contract-final
python scripts/check_qasper_run.py --run-directory data/benchmarks/qasper/results/p1q2-dev100-contract-final-es-evidence-selection
python scripts/compare_qasper_runs.py --baseline data/benchmarks/qasper/results/p1q2-dev100-legacy-es-evidence-selection --candidate data/benchmarks/qasper/results/p1q2-dev100-contract-final-es-evidence-selection --resamples 5000 --seed 42
```

