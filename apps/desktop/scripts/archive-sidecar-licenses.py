"""Keep bundled numerical-runtime notices without exceeding Squirrel's path limit."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

REPO_ROOT = Path(__file__).resolve().parents[3]
BUILD_ROOT = REPO_ROOT / "build"
ALLOWED_ROOTS = {
    (BUILD_ROOT / "pyinstaller" / "AITransBackend").resolve(),
    (BUILD_ROOT / "electron-resources" / "backend" / "AITransBackend").resolve(),
    (REPO_ROOT / "dist" / "AITransBackend").resolve(),
}


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: archive-sidecar-licenses.py SIDEcar_DIRECTORY")

    sidecar = Path(sys.argv[1]).resolve(strict=True)
    if sidecar not in ALLOWED_ROOTS:
        raise ValueError(f"Unexpected sidecar directory: {sidecar}")

    internal = (sidecar / "_internal").resolve(strict=True)
    license_dirs = sorted(
        directory for pattern in ("torch-*.dist-info/licenses", "faiss_cpu-*.dist-info/licenses", "faiss_conda_licenses", "numpy-*.dist-info/licenses")
        for directory in internal.glob(pattern)
    )
    archive = sidecar / "THIRD_PARTY_LICENSES.zip"
    if not any("faiss" in str(directory) for directory in license_dirs):
        if not archive.is_file():
            raise RuntimeError("FAISS license notices are missing from the sidecar")
        with ZipFile(archive) as existing:
            if not any("faiss" in name for name in existing.namelist()):
                raise RuntimeError("FAISS license notices are missing from the sidecar archive")
    if not license_dirs:
        if not archive.is_file():
            with ZipFile(archive, "w", compression=ZIP_DEFLATED) as output:
                output.writestr("README.txt", "No loose PyTorch license files were collected.\n")
        print("No loose PyTorch license directories to archive.")
        return 0

    files: list[Path] = []
    for directory in license_dirs:
        if directory.is_symlink() or not directory.resolve().is_relative_to(internal):
            raise ValueError(f"Unsafe license directory: {directory}")
        for entry in directory.rglob("*"):
            if entry.is_symlink():
                raise ValueError(f"Unexpected license symlink: {entry}")
            if entry.is_file():
                files.append(entry)

    temporary = sidecar / "THIRD_PARTY_LICENSES.zip.tmp"
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=9) as output:
            for file in files:
                output.write(file, file.relative_to(internal).as_posix())
        with ZipFile(temporary) as written:
            if len(written.namelist()) != len(files) or written.testzip() is not None:
                raise RuntimeError("PyTorch license archive verification failed")
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)

    for directory in license_dirs:
        shutil.rmtree(directory)

    print(f"Archived {len(files)} PyTorch license files to {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
