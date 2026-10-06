# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir build for the WebReBuild FastAPI sidecar."""

from pathlib import Path
from importlib.metadata import PackageNotFoundError
import os

# Also constrain isolated hook processes before importing numerical packages.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs, copy_metadata, collect_delvewheel_libs_directory


project_root = Path(SPECPATH).resolve()
default_config = project_root / "config" / "default.toml"
version_file = project_root / "VERSION"

# Package only runtime metadata/configuration. Managed Qwen weights always live
# below %LOCALAPPDATA%\AITrans\models and must never be added to this list.
datas = [(str(default_config), "config"), (str(version_file), ".")]
for distribution in ("faiss-cpu", "faiss", "faiss-gpu"):
    try:
        datas.extend(copy_metadata(distribution))
    except PackageNotFoundError:
        pass
datas.extend(copy_metadata("numpy"))
datas.extend(copy_metadata("sentence-transformers"))
datas.extend(copy_metadata("transformers"))
datas.extend(collect_data_files("faiss"))
datas, faiss_binaries = collect_delvewheel_libs_directory(
    "faiss", libdir_name="faiss_cpu.libs", datas=datas, binaries=collect_dynamic_libs("faiss")
)
# Conda GPU builds use shared CUDA/MKL DLLs in Library/bin. Include only the
# FAISS runtime families; PyInstaller also resolves their static dependencies.
from PyInstaller.utils.hooks import conda_support
if "faiss" in conda_support.distributions:
    for source, destination in conda_support.collect_dynamic_libs("faiss"):
        name = Path(source).name.lower()
        if any(part in name for part in ("faiss", "cublas", "cudart", "mkl", "iomp", "blas", "lapack")):
            faiss_binaries.append((source, destination))
    for name, distribution in conda_support.walk_dependency_tree("faiss").items():
        source = Path(distribution.raw.get("link", {}).get("source", "")) / "info" / "licenses"
        if source.is_dir():
            datas.append((str(source), f"faiss_conda_licenses/{name}"))
for package in ("sentence_transformers", "transformers"):
    datas.extend(
        collect_data_files(
            package,
            excludes=[
                "**/tests/**",
                "**/model.safetensors",
                "**/pytorch_model.bin",
                "**/*.gguf",
            ],
        )
    )

hiddenimports = sorted(
    {
        *collect_submodules("app"),
        *collect_submodules("backend"),
        *collect_submodules("faiss"),
        *collect_submodules("sentence_transformers"),
        *collect_submodules("transformers"),
        "huggingface_hub",
        "safetensors",
    }
)


a = Analysis(
    [str(project_root / "backend" / "sidecar.py")],
    pathex=[str(project_root)],
    binaries=faiss_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["docling", "pytest", "qdrant_client", "scripts.migration"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="AITransBackend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    exclude_binaries=True,
    disable_windowed_traceback=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    a.zipfiles,
    a.dependencies,
    strip=False,
    upx=False,
    name="AITransBackend",
)
