# QASPER Benchmark Sources

The loader's answer/evidence normalization and staged experiment organization
were adapted for AITrans from `BalakumaranM/rag_sdk`, specifically
`research/shared/qasper_dataset.py` and `research/shared/qasper_harness.py`.
The upstream project is licensed under MIT; its notice is retained in
[`LICENSE-rag_sdk.txt`](LICENSE-rag_sdk.txt). AITrans uses its own normalized
document contracts and retrieval runtime; no rag_sdk runtime dependency is
vendored.

Upstream references:

- <https://github.com/BalakumaranM/rag_sdk/blob/9b49ebd4ba5ea014f3ba8864051ce4968682c320/research/shared/qasper_dataset.py>
- <https://github.com/BalakumaranM/rag_sdk/blob/9b49ebd4ba5ea014f3ba8864051ce4968682c320/research/shared/qasper_harness.py>
- <https://github.com/BalakumaranM/rag_sdk/blob/9b49ebd4ba5ea014f3ba8864051ce4968682c320/LICENSE>

The benchmark dataset is downloaded from AllenAI's official QASPER v0.3
archive. Dataset files, prepared corpora, indexes, and experiment outputs stay
under the ignored `data/benchmarks/qasper/` directory and are not committed.
