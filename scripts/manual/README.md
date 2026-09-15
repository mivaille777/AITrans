# Manual smoke tests

These scripts are opt-in diagnostics rather than pytest tests. They may require
saved provider credentials, network access, optional model dependencies, or a
CUDA-capable GPU. Run them directly from the repository root; normal CI and
`scripts/test.ps1` do not execute them.

- `deepseek_api_smoke_test.py`: real DeepSeek API connectivity.
- `google_translation_smoke_test.py`: real Google web translation connectivity.
- `youdao_translation_smoke_test.py`: real Youdao WebFanyi connectivity.
- `qwen3_embedding_smoke_test.py`: local Qwen3 embedding model and GPU memory.
