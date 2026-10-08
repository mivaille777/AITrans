import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  getChatConfiguration,
  updateChatConfiguration,
  importChatFile,
  detachChatFile,
  type ChatSessionConfiguration,
} from "../../../api/chat-sessions"
import {
  createFilesystemWorkspace,
  listFilesystemWorkspaces,
} from "../../../api/filesystem-workspaces"
import { desktop } from "../../../desktop"

export function useChatConfiguration(sessionId: string) {
  const client = useQueryClient()
  const key = ["chat-configuration", sessionId]
  const configuration = useQuery({
    queryKey: key,
    queryFn: () => getChatConfiguration(sessionId),
    enabled: Boolean(sessionId),
    retry: 0,
  })
  const workspaces = useQuery({
    queryKey: ["chat-filesystem-workspaces"],
    queryFn: listFilesystemWorkspaces,
    retry: 0,
  })
  const mutation = useMutation({
    mutationFn: async (
      action:
        | { kind: "choose" }
        | {
            kind: "update"
            update: Partial<
              Pick<
                ChatSessionConfiguration,
                "execution_mode" | "filesystem_workspace_id"
              >
            >
          }
        | { kind: "import" }
        | { kind: "detach"; id: string },
    ) => {
      if (action.kind === "update")
        return updateChatConfiguration(sessionId, action.update)
      if (action.kind === "detach") return detachChatFile(sessionId, action.id)
      if (action.kind === "choose") {
        const directory = await desktop.files.pickAgentWorkspace()
        if (!directory) return null
        const workspace = await createFilesystemWorkspace(directory)
        await client.invalidateQueries({
          queryKey: ["chat-filesystem-workspaces"],
        })
        return updateChatConfiguration(sessionId, {
          filesystem_workspace_id: workspace.workspace_id,
        })
      }
      const file = await desktop.files.pickKnowledgeDocument()
      return file ? importChatFile(sessionId, file) : null
    },
    onSuccess: (value) => {
      if (value)
        client.setQueryData(["chat-configuration", value.session_id], value)
    },
  })
  return { configuration, workspaces, mutation }
}
