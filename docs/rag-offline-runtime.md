# RAG Offline Runtime and Packaging

AITrans keeps the local retrieval runtime and remote answer synthesis as separate
boundaries. With both managed Qwen models installed, document parsing, embedding,
hybrid retrieval, reranking, and evidence construction can run without network
access. A remote LLM outage is handled by the existing Agent/LLM fallback policy;
it does not make local retrieval contact Hugging Face.

## Managed model location

Model weights are installed after application setup and remain outside every EXE
or Tauri bundle:

```text
%LOCALAPPDATA%\AITrans\models\
├── qwen3-embedding-0.6b\
└── qwen3-reranker-0.6b\
```

Providers resolve these directories through `ModelManager` and always pass
`local_files_only=True`. Set both variables below when manually validating a
machine with its network disabled:

```powershell
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
```

## Backend sidecar build

Install the build and RAG runtime requirements, then build from the repository
root:

```powershell
python -m pip install -e ".[build]"
python -m pip install -r aitranslator-rag-requirements.txt
.\scripts\build_rag_backend.ps1 -Clean
```

The build creates `dist\AITransBackend\AITransBackend.exe`. The script rejects
known model-weight files and runs the packaged sidecar import smoke test with the
Hugging Face and Transformers offline flags enabled. The sidecar contains runtime
code and package configuration for Sentence Transformers, Transformers, and the
Qdrant client, but not model weights or a Hugging Face cache.

The real-model GPU integration tests remain opt-in because they load multi-GB
local artifacts. The normal test suite uses injected local model runtimes and
blocks socket connections while exercising parse → embed → hybrid retrieval →
rerank.
