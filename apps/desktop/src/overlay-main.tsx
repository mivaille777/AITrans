import { StrictMode } from "react"
import { QueryClientProvider } from "@tanstack/react-query"
import { createRoot } from "react-dom/client"

import OverlayView from "./components/OverlayView"
import { desktop } from "./desktop"
import {
  applyOverlayNativeVisualTheme,
  applyOverlayThemeToDocument,
  subscribeOverlayVisualThemeEvents,
} from "./desktop/overlay-native-theme"
import {
  readOverlayPreferences,
  subscribeOverlayPreferences,
} from "./desktop/overlay-preferences"
import AppErrorBoundary from "./shared/errors/AppErrorBoundary"
import { createAppQueryClient } from "./shared/query/query-client"
import { queryKeys } from "./shared/query/query-keys"
import "./index.css"
import "./overlay.css"
import "./overlay-fix.css"
import "./overlay-mode-navigation.css"
import "./overlay-theme.css"
import "./overlay-light-readability.css"

document.documentElement.dataset.aitView = "overlay"

function applyOverlayVisualTheme(theme: "light" | "dark"): void {
  applyOverlayThemeToDocument(theme)
  void applyOverlayNativeVisualTheme(theme).catch(() => undefined)
}

const initialOverlayPreferences = readOverlayPreferences()
applyOverlayVisualTheme(initialOverlayPreferences.theme)

subscribeOverlayPreferences((preferences) => {
  applyOverlayVisualTheme(preferences.theme)
})

// Tauri events provide immediate main-window -> overlay synchronization. The
// persisted preference subscription above remains the recovery/source-of-truth
// path after reloads and non-Tauri browser development. Native material state
// is already changed by the sender, so this listener only updates the DOM
// theme. WebView2 background transparency stays static from Tauri config to
// avoid Windows caption artifacts during focus/drag transitions.
void subscribeOverlayVisualThemeEvents((theme) => {
  applyOverlayThemeToDocument(theme)
})

const queryClient = createAppQueryClient()

void desktop.overlay.onStateChanged(() => {
  void queryClient.refetchQueries({ queryKey: queryKeys.overlay.state, type: "active" })
})

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AppErrorBoundary>
        <OverlayView />
      </AppErrorBoundary>
    </QueryClientProvider>
  </StrictMode>,
)
