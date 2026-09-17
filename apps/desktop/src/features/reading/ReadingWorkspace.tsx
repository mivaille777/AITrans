import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import UnifiedReadingWorkspace from "./UnifiedReadingWorkspace"

export default function ReadingWorkspace({ workspace }: { workspace: TranslationWorkspaceController }) {
  return <UnifiedReadingWorkspace workspace={workspace} />
}
