# FAISS 迁移和维护

适用范围：Windows 本机知识库。正常应用只使用 `faiss_local`；旧客户端仅用于一次性导出与旧版本回滚。真实执行记录见 [迁移验收报告](../../docs/development/faiss-migration-acceptance.md)。

## 当前机器

源码目录为 `D:\AITrans`，实际 Python 为：

```powershell
$python = 'C:\Users\mivaille\anaconda3\envs\aitrans\python.exe'
& $python -m pip check
```

最初 CPU 基线安装 `faiss-cpu==1.15.1`、`tomlkit==0.15.1`。用户追加 GPU 优先要求后，使用 Conda `faiss-gpu=1.9.0` / CUDA Toolkit 11.8；兼容依赖为 NumPy 1.26.4、OpenCV 4.11.0.86，保留原 PyTorch CUDA 13 与模型版本。`tomlkit` 仅用于保留 TOML 注释的配置切换。

正常安装先使用项目 `pyproject.toml` 和 RAG requirements，再运行 FAISS 选择脚本。不要在 GPU 环境另装 `.[faiss-cpu]` 或 `faiss-cpu` wheel，它们会覆盖同名模块：

```powershell
$env:CONDA_PKGS_DIRS = 'D:\AITrans\.cache\conda-pkgs'
./scripts/install_faiss.ps1 -PythonExecutable 'C:\Users\mivaille\anaconda3\envs\aitrans\python.exe' -CondaExecutable 'C:\Users\mivaille\anaconda3\Scripts\conda.exe'
```

默认 `AITRANS_FAISS_DEVICE=auto`，先检测 FAISS GPU 构建、设备并尝试真实 CUDA 分配；失败使用同构建中的 CPU 索引。`AITRANS_FAISS_DEVICE=cpu` 可强制 CPU，`AITRANS_FAISS_GPU_DEVICE` 选择设备（默认 0）。文本及视觉候选召回共用策略，MaxSim 继续 NumPy。Manhattan 或 top-k 超出 GPU 的 2048 限制使用 CPU。

本机 C 盘空间不足，环境 `Library` 已转到 `D:\PythonEnvironments\aitrans-library`，原路径保留 directory junction；Python 路径没有改变。不要删除该 D 盘目录。安装脚本本身不会移动目录。

BLAS 使用 OpenBLAS 0.3.34，避免新 MKL 与现有模型环境的 DLL 冲突。后端及 PyInstaller 默认 `OPENBLAS_NUM_THREADS=1`，减少多进程 scratch 内存；显式用户环境设置仍优先。后续 pip 升级请用 `-c aitranslator-faiss-gpu-constraints.txt` 保持此 GPU 构建所需的 NumPy 1.x。

## 导出

停止应用及索引任务，再在具有旧 `qdrant-client` 的环境执行。导出器取得 Local 数据库锁，不能与应用同时访问旧 Local 库。

```powershell
& $python -m scripts.migration.export_qdrant `
  --source-root D:\AITrans\config\rag `
  --qdrant-path D:\AITrans\config\rag\qdrant `
  --text-collection aitrans_knowledge `
  --config-snapshot D:\AITrans\config\user.toml `
  --output D:\AITrans\test-results\faiss-migration\new-export
```

输出目录必须全新且在来源状态目录之外。`--source` 是 `--qdrant-path` 的兼容别名；未指定 Local 路径时使用 `source-root/qdrant`。`--visual-collection` 可限定预期视觉 collection；视觉不存在时无需虚构数据。

旧视觉物理名称的 `_2stage_mv<dim>_<distance>` / `_mv<dim>_<distance>` 后缀在迁移包中映射为新逻辑 collection，并保留原 `source_name`。旧库同时保存两种变体时，用 `--visual-collection` 指定当前使用的变体，其余完整数据仍在 rollback 快照中。多视觉 index version 并存时，用 `--visual-index-version` 指明当前配置版本；历史 rows 保留，禁止自动混用。源 config 中 `collection_name` 仍是逻辑前缀，不把旧后缀写入新用户配置。

导出包包含 `bundle.json`、`vectors.jsonl`、完整 Local 向量快照、manifest、BM25、Graph SQLite backup、状态根下的 `assets/visual_pages`，并记录文件 SHA-256。配置快照只写明确允许的存储/模型字段，过滤聊天和 API 凭据。实际回滚用的完整用户配置需另外保存于受保护位置。

远程模式使用 `--source-url`（兼容 `--url`），必须提供配套 `--source-root` 和 `--server-writes-frozen`，不得同时提供 Local 路径。认证使用 `--api-key-env ENV_NAME`；URL 不允许带凭据或 query 参数。冻结远程写入和取得一致的 manifest/BM25 是运维前提，工具无法替远程服务实施全局写锁。本机已验收 Local 模式，远程服务未做实际连通验收。

原文及自定义外部图片目录不能从默认目录推断。导出前枚举 chunk 的 `source_uri/metadata.asset_uri`，单独保留其文件与目录。此次为同机切换，所有原 URI 保留；不自动改写 BM25、manifest 或 chunk 的资产 URI。跨机器改目录应先恢复原路径，或在完整备份后用新应用重新索引。

## 校验和导入

新环境无须旧客户端或模型，导入仅使用中立 JSON 和 FAISS/NumPy/SQLite。

```powershell
& $python -m scripts.migration.import_faiss --bundle D:\path\new-export --validate-only
& $python -m scripts.migration.import_faiss --bundle D:\path\new-export --destination D:\path\staging
& $python -m scripts.migration.import_faiss --bundle D:\path\new-export --destination D:\path\staging --resume
& $python -m scripts.migration.import_faiss --bundle D:\path\new-export --destination D:\path\staging --verify-only
```

`--verify` 是 `--verify-only` 的别名。成功退出码为 0；异常为非 0，禁止切换。`--validate-only` 不创建目标；`--verify-only` 使用只读 SQLite。校验覆盖文件摘要、shape/finite、完整 payload/vector/coarse、generation 身份、数量和 READY 的 dense/BM25 精确集合。

首次导入要求全新目标；`--resume` 只能使用同一 bundle digest。中断后重放批次为稳定 ID 的幂等 upsert。已完成导入的 `--resume` 只做验证，避免覆盖切换后的用户修改。开始写入后 `migration.json` 为 `importing`；只有全部核对成功才写 `verified`。应用拒绝未完成迁移及 READY 指向缺失数据。

未知模型 fingerprint、混合文本 embedding 空间、错误维度/度量不能通过改配置强行使用，应在独立新 collection 中重建。视觉 index version 同样是模型/渲染参数的身份；更改参数或 model_path 时需重新建立对应索引。

## 切换

1. 停止应用，验证旧快照与 staging；确认没有其他写入所有者。
2. 校验源和目标绝对路径。新库关闭并 checkpoint 后，将完整 staging 目录放到目标 `config/rag/faiss`。已有目标先保留快照，不覆盖正在使用的数据库。
3. 只更新 `[rag.vector_store]` 的 `provider = "faiss_local"` 和 `storage_path`。同机切换保留原 BM25/manifest/Graph/资产根及模型、解析和视觉开关。
4. 启动新应用，执行查询与引用校验，并在隔离目录验证索引、重建、删除和重开。

源码默认 data root 为项目根；冻结应用默认 `%APPDATA%\AITranslator`。`AITRANSLATOR_DATA_DIR` 可覆盖应用根。模型根 `%LOCALAPPDATA%\AITrans\models` 是独立目录。已有生产 `AITRANS_QDRANT_URL/API_KEY` 不再影响新运行时。

第一版运行时将文本与原生视觉放入同一个 repository，保持原来的共享存储生命周期；视觉 `storage_path` 不用于拆分运行时库。基准可自行创建隔离 repository。数据格式是 `vector_store.sqlite3` + SQLite WAL，SQLite 是持久化权威；没有必须备份的 `.faiss` 文件。

## 备份和回滚

在线向量备份使用 `LocalVectorRepository.backup(path)`，或者停止应用并 checkpoint 后保存整个目录。不能在线只复制主 SQLite 文件。BM25/manifest/Graph/资产须在同一写入冻结窗口一并保留。

本次完整快照：`D:\AITrans\test-results\faiss-migration\real-export-v2\rollback`；旧源码：同级 `rollback-source.zip`。完整配置备份含用户凭据，不提交 Git、不贴到日志。旧原文仍在原位置。

回滚步骤：

1. 停止新应用，另存新 SQLite、状态、配置以及切换后的新增/重建/删除操作清单。
2. 在独立目录恢复旧源码归档与完整 `rollback` 状态，恢复原文和图片的原 URI。使用旧环境依赖。
3. 本机 Local 回滚设置旧 `provider = "qdrant_local"`、绝对 `storage_path`、`url = ""`，并清除该启动进程的 `AITRANS_QDRANT_URL`；否则旧应用可能优先连接远程服务。
4. 核对文档/向量数量，执行实际模型查询与引用验证，再让旧应用接管。恢复快照之后的新操作须重放，不能假定快照包含它们。

本次隔离回滚演练已用旧源码、恢复后的 1,328 条向量、BM25/manifest/资产运行真实查询。生产新库未被回滚。旧库和所有快照继续保留，未约定自动删除时间。

## 可重复验收

```powershell
& $python -m pytest tests/rag/test_local_vector_repository.py tests/rag/test_faiss_store.py tests/rag/test_faiss_visual_store.py tests/rag/test_visual_scoring.py tests/rag/test_faiss_migration.py tests/rag/test_faiss_recovery.py tests/rag/test_no_qdrant_runtime.py
& $python -m scripts.benchmark_faiss_storage --output D:\path\new-storage-benchmark
$env:AITRANS_PYTHON_EXECUTABLE = $python
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_rag_backend.ps1
node apps/desktop/scripts/build-backend-sidecar.mjs
```

真实文本生命周期入口是 `scripts.migration.validate_real_text`，参数为全新 `--output`、已缓存模型的 `--embedding-path/--reranker-path`。真实视觉入口是 `scripts.migration.validate_real_visual`，参数为全新 `--output`、`--model-path`、`--cache-dir`、`--embedding-path`。设置 `HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1`，并保证适配器和基础模型均已缓存。视觉测试使用 CUDA NF4、256 image tokens，输出 token shape、独立 MaxSim oracle、重开、RRF/引用及改图拒绝结果。

上述模型验收使用真实权重；规模测试使用可复现的合成向量，只测存储，不用于声明真实质量。冻结 `--runtime-smoke-test` 使用临时数据执行运算，不加载模型或触碰生产库。

本次还以最终冻结 exe 启动了隔离 HTTP 服务，通过 PDF 导入、实际文本/视觉检索与证据输出、删除；日志在 `test-results/faiss-migration/frozen-api/`。该服务已经停止。不要把本机 HTTP/PATH 隔离验收当作干净 Windows VM 和完整 Electron UI 验收。
