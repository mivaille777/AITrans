export const IPC_CHANNELS = {
  windowShow: "aitrans:window:show",
  windowHide: "aitrans:window:hide",
  windowFocus: "aitrans:window:focus",
  windowMinimize: "aitrans:window:minimize",
  windowToggleMaximize: "aitrans:window:toggle-maximize",
  windowIsMaximized: "aitrans:window:is-maximized",
  windowClose: "aitrans:window:close",
  filesPickKnowledgeDocument: "aitrans:files:pick-knowledge-document",
  filesPickAgentWorkspace: "aitrans:files:pick-agent-workspace",
  filesOpenEvidenceSource: "aitrans:files:open-evidence-source",
} as const
