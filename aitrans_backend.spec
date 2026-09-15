# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir build for the WebReBuild FastAPI sidecar."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path(SPECPATH).resolve()
default_config = project_root / "config" / "default.toml"

# Package only runtime metadata/configuration. Managed Qwen weights always live
# below %LOCALAPPDATA%\AITrans\models and must never be added to this list.
datas = [(str(default_config), "config")]
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
        *collect_submodules("qdrant_client"),
        *collect_submodules("sentence_transformers"),
        *collect_submodules("transformers"),
        "huggingface_hub",
        "safetensors",
    }
)


a = Analysis(
    [str(project_root / "backend" / "sidecar.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["docling", "pytest"],
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
