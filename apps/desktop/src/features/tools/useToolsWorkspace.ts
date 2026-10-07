import { useEffect, useState } from "react"
import { useInfiniteQuery, useQuery } from "@tanstack/react-query"
import { useSearchParams } from "react-router-dom"
import { getTool, getTools } from "../../api/tools"
import { queryKeys } from "../../shared/query/query-keys"

export function useToolsWorkspace() {
  const [params, setParams] = useSearchParams()
  const search = params.get("q") ?? ""
  const status = params.get("status") ?? "all"
  const category = params.get("category") ?? ""
  const [query, setQuery] = useState(search)
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search), 250)
    return () => clearTimeout(timer)
  }, [search])
  const totals = useQuery({ queryKey: ["tools", "counts"], queryFn: () => getTools(), retry: false })
  const library = useInfiniteQuery({
    queryKey: [...queryKeys.tools.list(query, status), category],
    queryFn: ({ pageParam }) => getTools({ q: query, status, category, ...(pageParam ? { cursor: pageParam } : {}) }),
    initialPageParam: "",
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    retry: false,
  })
  const items = library.data?.pages.flatMap((page) => page.items) ?? []
  const selected = params.get("tool") ?? items.find((tool) => tool.name === "search_knowledge_base")?.tool_id ?? items[0]?.tool_id ?? ""
  const detail = useQuery({
    queryKey: queryKeys.tools.detail(selected),
    queryFn: () => getTool(selected),
    enabled: Boolean(selected),
    retry: false,
  })
  function setParam(name: string, value: string) {
    setParams((previous) => { const next = new URLSearchParams(previous); if (value) next.set(name, value); else next.delete(name); return next }, { replace: true })
  }
  return { library, totals, items, selected, detail, search, status, category, setParam }
}
