# Knowledge UI Refinement Batch 1

Status: complete on `WebReBuild`.

## Scope completed

- Removed the stacked legacy Knowledge Canvas from the active Knowledge route.
- Consolidated the active workspace into one primary navigation: Canvas / Graph / Library, with Reader as a contextual mode.
- Kept the existing board interaction engine for drag, resize, zoom, pan, relation creation, delete, and minimap.
- Routed canvas node content through `KnowledgeCardRenderer` so visual presentation is separated from canvas interaction logic.
- Added a productized `KnowledgeInspector` with card metadata, relation information, and AI action entry points.
- Added `KnowledgeActionMenu` actions for summarize, explain, translate, note generation, and Ask Agent.
- Added a typed UI action dispatcher and workspace event boundary for later Agent Runtime integration.
- Added `KnowledgeWorkspaceProvider` so canvas selection, inspector state, and knowledge actions share one workspace context.
- Added focused tests for action dispatch and inspector interaction.

## Active UI flow

```text
KnowledgeRoute
  -> KnowledgeWorkspaceProvider
    -> KnowledgeWorkspacePanel
      -> Canvas
         -> KnowledgeBoardCanvas
         -> KnowledgeCardRenderer
         -> KnowledgeInspector
            -> KnowledgeActionMenu
            -> knowledge-action-dispatcher
            -> knowledge-workspace-events
      -> Graph
      -> Library
      -> Reader
```

## Local validation

From the repository root on Windows PowerShell:

```powershell
cd D:\AITranslator
conda activate aitrans
git checkout WebReBuild
git pull origin WebReBuild

python -c "import backend.main; print('backend-import-ok')"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Push-Location apps\desktop
npm ci
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Pop-Location

python -m backend
```

The GitHub connector can write and inspect source code, but it does not execute the local Python/Node toolchains. Run the validation block locally before starting the next UI batch.

## Next batch boundary

Batch 2 should connect emitted knowledge workspace events to the existing Agent Runtime / Supervisor and implement real results for Summarize, Explain, Translate, Generate Notes, and Ask Agent instead of adding more UI-only abstractions.
