import type {
  CompanionConversationChangeSignal,
  CompanionNavigationSignal,
  DesktopCredentialPreview,
  DesktopCredentialStatus,
  DesktopOverlayTheme,
  DesktopPoint,
  DesktopSize,
  OverlayPositionMode,
} from "../adapter"

export interface ElectronDesktopApi {
  window: {
    show(): Promise<void>
    hide(): Promise<void>
    focus(): Promise<void>
    minimize(): Promise<void>
    toggleMaximize(): Promise<boolean>
    isMaximized(): Promise<boolean>
    close(): Promise<void>
  }
  files: {
    pickKnowledgeDocument(): Promise<string | null>
    pickAgentWorkspace(): Promise<string | null>
    openEvidenceSource(resourceUrl: string): Promise<void>
  }
  credentials: {
    getStatus(provider: string): Promise<DesktopCredentialStatus>
    getPreview(provider: string): Promise<DesktopCredentialPreview>
    save(provider: string, apiKey: string): Promise<void>
    delete(provider: string): Promise<void>
  }
  overlay: {
    show(): Promise<void>
    hide(): Promise<void>
    focus(): Promise<void>
    place(
      mode: OverlayPositionMode,
      customPosition?: DesktopPoint | null,
    ): Promise<DesktopPoint | null>
    resize(size: DesktopSize): Promise<void>
    getPosition(): Promise<DesktopPoint | null>
    setAlwaysOnTop(enabled: boolean): Promise<void>
    setClickThrough(enabled: boolean): Promise<void>
    startDragging(): Promise<void>
    setVisualTheme(theme: DesktopOverlayTheme): Promise<void>
    onVisualThemeChanged(
      callback: (theme: DesktopOverlayTheme) => void,
    ): Promise<() => void>
    onMoved(callback: (position: DesktopPoint) => void): Promise<() => void>
    notifyStateChanged(contextId?: string): Promise<void>
    onStateChanged(callback: (contextId: string) => void): Promise<() => void>
    notifyCompanionNavigation(signal: CompanionNavigationSignal): Promise<void>
    onCompanionNavigation(
      callback: (signal: CompanionNavigationSignal) => void,
    ): Promise<() => void>
    notifyCompanionConversationChanged(
      signal: CompanionConversationChangeSignal,
    ): Promise<void>
    onCompanionConversationChanged(
      callback: (signal: CompanionConversationChangeSignal) => void,
    ): Promise<() => void>
  }
}
