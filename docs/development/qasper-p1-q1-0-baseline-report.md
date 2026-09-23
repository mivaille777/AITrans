# QASPER P1 Q1-0 基线与测量验收报告

> 日期：2026-09-24。Q1-0 的实现测量提交：`922dac36ced1a1b0a5faa78e1b5c473e9a0f1277`；阶段审计修正与验收报告提交：`5c839945254e32b8ba4f7bf968d233325db191d5`。真实运行产物保存在已忽略的 `data/benchmarks/qasper/results/`，此报告不复制完整问题、模型回答或私有配置。

## 结论

Q1-0 验收通过。Smoke20 与 Dev100 均使用固定 question ID 清单和公开 QASPER v0.3 validation 数据，真实执行当前检索、重排及 DeepSeek 回答链路。严格审计确认预测、trace、qrels 数量一致，0 运行错误、0 跨论文候选；Dense、BM25、reranker 在每道题上均有实际记录。比较器拒绝不同样本和不同 source SHA，自比较的全部 delta 与区间均为 0。

Q1-0 只建立基线，不代表质量达标。Dev100 的 Gold Evidence Recall@10 为 0.9759，但最终候选 Evidence Precision@10 只有 0.0723、官方 Evidence F1 只有 0.0696；Boolean Answer F1 为 0.0093，Unsupported Claim Rate 为 0.4385。下一阶段应优先缩小送入回答器和最终引用的证据集合，并保持 Top20 检索候选用于诊断。

## 数据、样本与环境

| 项目 | Smoke20 | Dev100 |
| --- | --- | --- |
| Run ID | `p1q0-smoke-aitrans` | `p1q0-dev-current` |
| questions / papers | 20 / 18 | 100 / 86 |
| ID 清单 | `validation-smoke20-seed42.txt` | `validation-dev100-seed42.txt` |
| ID 清单 SHA256 | `8390a28d3d88b68373ab49c60653ea52fc723c48779b5c212dd522fb4bf41e9e` | `856af943ff1f51ba2bc36e392286a731c417dacfb2746e5f575c1ba81076596a` |
| run manifest ID 样本 hash | `89c2f0a1279ca8bc74a56b469e2017c38165a976cefa438e2ecad16067de4e17` | `6dd1fb858c30efc9a42292bdd9fcfe55043f8dcfbc67dcf4cd500eb678bea369` |
| 源数据 SHA256 | `2ae7ee62a65b1c4225791c70de80c2aad4e8998cf1fd4f09a53103db4f21af93` | 同左 |
| 运行代码 SHA | `922dac36ced1a1b0a5faa78e1b5c473e9a0f1277` | 同左 |
| 索引 fingerprint | `9a845617d4f380623a9851a8e20579607b56c9e8ebc4868cf24e536794a892d5` | `83dcc5285e6c5a42b956aa56823081cb40355120c53372cd6cb7aae8fa767241` |
| 模型 | Qwen3-Embedding-0.6B、Qwen3-Reranker-0.6B、DeepSeek V4 Flash | 同左 |
| Python / 设备 | aitrans Python 3.11.7，CUDA 可用 | 同左 |

数据是本地准备的公开 QASPER v0.3 validation（对应官方 dev），不是合成样本。Smoke20 与历史真实 smoke 的题目逐题一致；Dev100 使用固定 seed 42 清单，Holdout905 为其补集。Smoke20/Dev100 的 qrels SHA 分别为 `7347658f6368e881ad1afee7fe8000a6817b5fbe79dc0d984908c6c1c5b4e204`、`70518f10529c57db724a03a7df92a27e764c9bf652145076364b13b6ecbc6826`。

## 真实运行结果

| 指标 | Smoke20（分母） | Dev100（分母） |
| --- | ---: | ---: |
| 运行状态 / errors | complete / 0 | complete / 0 |
| Dense / BM25 / reranker 有实际记录 | 20 / 20 / 20 | 100 / 100 / 100 |
| 同论文最终候选 / 越界 | 319 / 0 | 1,573 / 0 |
| AI retrieval Recall@10 | 0.9688（16 个有映射 Gold） | 0.9699（83 个有映射 Gold） |
| Gold Evidence Recall@10 | 1.0000（16） | 0.9759（83） |
| Evidence Precision@10 | 0.0788（16） | 0.0723（83） |
| 官方 Answer F1（all evidence） | 0.0706（20） | 0.1001（100） |
| 官方 Evidence F1（all evidence） | 0.0681（20） | 0.0696（100） |
| 官方 Evidence F1（text-only） | 0.0683（20） | 0.0699（100） |
| Unsupported Claim Rate | 79 / 187 = 0.4225 | 346 / 789 = 0.4385 |
| 平均上下文 tokens | 3,937.6 | 3,844.6 |
| 检索阶段总延迟 p95 | 1,803 ms | 1,107 ms |
| 回答生成延迟 p95 | 2,586 ms | 2,199 ms |
| 实际 DeepSeek 调用 / 核验回退 / 策略弃答 | 20 / 1 / 0 | 100 / 0 / 0 |

`answer_provider_counts` 按实际调用 provider 计数；Smoke20 的 1 次核验回退是在 DeepSeek 已调用之后发生，不是一次无调用弃答。第一次错误解释器产生的 run 不在上表：系统 Python 3.11.15 未安装 PyTorch，导致 Dense 为 0、reranker 未运行；审计器拒绝该 run。正式运行改用具备 PyTorch、sentence-transformers 和 CUDA 的 aitrans Python 3.11.7。这个发现已加入后续命令的环境预检要求。

### Dev100 分层

答案类型是多标签，分类数相加可超过 100。官方 Answer F1：Extractive 0.1296（61 题）、Abstractive 0.1358（33）、Boolean 0.0093（18）、None 0.0000（15）。按证据作用域统计：Local 58 题（Answer F1 0.1232 / Evidence F1 0.0688）、Cross-section 15（0.0870 / 0.1186）、Global 4（0.0907 / 0.2171）、Unanswerable 7（0 / 0）、Unclassified 16（0.0748 / 0.0201）。检索类指标只统计有映射 Gold 的题，Answer/Evidence F1 统计全部题。

检索错误分类器在 Dev100 标记 2 个 retrieval miss、2 个 rerank drop、2 个 wrong section、91 题出现至少一个 `answer_unsupported` 标签及 7 个 unanswerable failure。该 taxonomy 是自动定位信号，不等同于人工判定；unsupported claim rate 也只是现有 claim verifier 的估计，必须结合以下人工审查解释。

## 配对比较

用 5,000 次、seed 42 的配对 bootstrap，将历史 Smoke20 `real-smoke-final-e2ac883` 与新基线严格按相同 20 个题目比较：

| 指标 | 历史基线 | 当前 | 当前减基线，95% CI |
| --- | ---: | ---: | ---: |
| Answer F1 | 0.0735 | 0.0706 | -0.00295 `[-0.00968, 0.00431]` |
| Evidence F1 | 0.0681 | 0.0681 | 0 ` [0, 0]` |
| Gold Evidence Recall@10（16 题） | 1.0000 | 1.0000 | 0 `[0, 0]` |
| MRR（16 题） | 0.5141 | 0.5141 | 0 `[0, 0]` |

这说明新基线没有在 Smoke20 上显示回答质量提升。Dev100 自比较的四项 delta 与 95% CI 均为 0，证明比较路径可复现，不能当作策略收益。修正后的比较器对 Answer/Evidence F1 使用全体题目；Gold Evidence Recall@10 与 MRR 使用同一批有映射 Gold 的配对题，避免无证据题的占位 0 压缩均值和区间。

## Smoke20 逐题人工审查

人工快速审阅回答、Gold、检索证据与官方分数。此表记录主要失败模式，不把 token-F1 低直接等同于事实错误；完整原始内容保留在被忽略的 run 目录。

| Question ID 前缀 | 人工观察 |
| --- | --- |
| `3de04872` | 提到主要临床数据集，但回答明显过长并增加额外主张。 |
| `fb2b536d` | Gold 为不可回答；系统仍给出论文评估信息，没有正确弃答。 |
| `10d45096` | Boolean 结论 Yes 正确，但附加说明过长。 |
| `fa527bec` | LSTM 架构核心描述基本对应，外围解释过多。 |
| `aefa333b` | 比率定义语义接近 Gold，但加入不必要的方法说明。 |
| `bfc2dc91` | 列出的 LiLi KS 组件有部分重合，回答扩展成较长组件清单。 |
| `2007bfb8` | 对比 violent/nonviolent corpora 时过度强调 n-gram，遗漏 Gold 强调的 topic modeling 与情绪检测。 |
| `4cbe5a36` | 只提 PDTB taggers，Gold 中 SVM/RBF/RF 等基线未覆盖。 |
| `03c96776` | 在 Gold evidence 已映射且 Recall@10=1 的情况下，以证据未命名 baseline 为由弃答。 |
| `584af673` | 捕捉到 encoder/LSTM 的顺序建模主线，但答案冗长、引用 precision 低。 |
| `09a1173e` | Gold 未映射且系统弃答；当前无法区分数据对齐问题与确实缺失的性能数字。 |
| `05887a84` | 推断 unigram 最佳，而 Gold 是 Target-1；属于无证据排序推断。 |
| `2c7494d4` | Boolean 回答 Yes，Gold 为 No；该题 Gold evidence 未映射。 |
| `29c014ba` | 命中 popularity/similarity/hybrid 类别，但扩写出大量具体算法，超出问题所需。 |
| `7438b6b1` | Boolean 回答 Yes，Gold 为 No。 |
| `5b551ba4` | 覆盖 BPE perplexity、BLEU、ROUGE-L、diversity 和 user matching 等部分指标，但细节过多且只部分命中。 |
| `3c3807f2` | DeepSeek 原答未通过引用核验；最终输出泄漏内部回退提示，没有给出 Gold 要求的 No。 |
| `f0848e7a` | 识别 NA/WC 基线，但漏掉 SVM 等方法并附带冗长说明。 |
| `b85fc420` | Boolean Yes 正确，解释性改写过多。 |
| `36ae003c` | 提到 Human Level Attributes 与 dialogue，核心部分对应但展开过多。 |

主要待修问题是证据数量/精度、简答约束、布尔答案规范化、unanswerable 判定、映射可观测性以及核验失败时的用户可见回退。Q1-1 先验证证据收窄是否提高 Evidence Precision/F1，并同时监控 Gold Evidence Recall@5；不要据此预先决定启用抽取式 extractor。

## 验收依据与复跑

- `tests/rag/benchmarks`：36 passed；Ruff 检查通过。
- 固定 Smoke20、Dev100、Holdout905 ID 清单及其哈希已提交于 `backend/rag/benchmarks/qasper/sample_ids/`。
- `check_qasper_run.py` 对 Smoke20 和 Dev100 均返回 `ok: true`；source SHA、qrels SHA、question IDs 完全对齐，errors 文件为空。
- Smoke20 与 Dev100 各题 dense、BM25、reranker 均有正向执行记录；scope audit 检查 319 / 1,573 个最终候选，均无跨论文候选。
- 自比较 delta 为零；source SHA 或 question/qrels 集合不一致时比较器报错，不会静默取交集。

在已激活且安装了 PyTorch、sentence-transformers、Qdrant client 的 `aitrans` 环境中，从仓库根目录复跑：

```powershell
python -c "import torch, sentence_transformers; print(torch.__version__)"
python scripts/run_qasper_benchmark.py --mode smoke --seed 42 --question-ids-file backend/rag/benchmarks/qasper/sample_ids/validation-smoke20-seed42.txt --run-id p1q0-smoke-aitrans
python scripts/run_qasper_benchmark.py --mode dev --seed 42 --question-ids-file backend/rag/benchmarks/qasper/sample_ids/validation-dev100-seed42.txt --run-id p1q0-dev-current
python scripts/check_qasper_run.py --run-directory data/benchmarks/qasper/results/p1q0-dev-current
python scripts/compare_qasper_runs.py --baseline data/benchmarks/qasper/results/p1q0-dev-current --candidate data/benchmarks/qasper/results/p1q0-dev-current --resamples 5000 --seed 42
```

benchmark JSONL、全文回答及真实运行缓存保存在被忽略的 `data/benchmarks/qasper/` 下；以上摘要足以检查结论，未纳入 API 密钥、账户信息或完整私有配置。该基线已记录 provider 调用次数和延迟，但 provider 实际 token usage / 货币成本尚未由当前链路稳定暴露；后续阶段需要继续记录可得的调用成本字段。
