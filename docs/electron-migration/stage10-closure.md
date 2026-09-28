# Electron Stage 10 — Windows Packaging and Distribution

Stage 10 produces a self-contained Windows Electron application with a
PyInstaller `onedir` FastAPI sidecar. Target machines do not need Python,
Conda, Rust, or Node.js.

## Commands

```powershell
cd apps/desktop
npm run electron:package
npm run electron:make
```

The sidecar is built from `aitrans_backend.spec`, smoke-tested, and staged as:

```text
resources/backend/AITransBackend/AITransBackend.exe
```

RAG model weights are not bundled. Managed models remain in the user's local
AITrans model directory.

`electron:package` verifies the packaged executable, unpacked renderer, backend
resource, and frozen backend runtime. `electron:make` additionally verifies
Squirrel.Windows `Setup.exe`, `*-full.nupkg`, and `RELEASES`.

Install Python packaging dependencies before the first local package build:

```powershell
python -m pip install -e ".[build]" -r aitranslator-rag-requirements.txt
```

Code signing is a release concern and is not required for local Stage 10
acceptance.
