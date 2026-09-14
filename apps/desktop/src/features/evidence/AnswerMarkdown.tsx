import type { ReactNode } from "react"
import ReactMarkdown, { type Components } from "react-markdown"

import { CitationChip } from "./CitationChip"
import {
  citationSegments,
  resolveCitation,
  type ResolvedCitation,
} from "./citation-model"
import type { AgentCitationRef, AgentEvidenceItem } from "./evidence-types"

type TableAlignment = "left" | "center" | "right" | undefined

type MarkdownBlock =
  | { type: "markdown"; content: string }
  | {
      type: "table"
      headers: string[]
      rows: string[][]
      alignments: TableAlignment[]
    }

const CITATION_HREF_PREFIX = "#ait-citation-"

function splitPipeRow(line: string): string[] {
  let source = line.trim()
  if (source.startsWith("|")) source = source.slice(1)
  if (source.endsWith("|")) source = source.slice(0, -1)

  const cells: string[] = []
  let current = ""
  let escaped = false
  for (const character of source) {
    if (escaped) {
      current += character
      escaped = false
      continue
    }
    if (character === "\\") {
      escaped = true
      current += character
      continue
    }
    if (character === "|") {
      cells.push(current.trim())
      current = ""
      continue
    }
    current += character
  }
  cells.push(current.trim())
  return cells
}

function delimiterAlignment(cell: string): TableAlignment | null {
  const normalized = cell.trim()
  if (!/^:?-{3,}:?$/.test(normalized)) return null
  if (normalized.startsWith(":") && normalized.endsWith(":")) return "center"
  if (normalized.endsWith(":")) return "right"
  return "left"
}

function splitMarkdownBlocks(markdown: string): MarkdownBlock[] {
  const lines = markdown.split("\n")
  const blocks: MarkdownBlock[] = []
  let markdownLines: string[] = []
  let inFence = false
  let fenceMarker = ""

  const flushMarkdown = () => {
    if (markdownLines.length === 0) return
    blocks.push({ type: "markdown", content: markdownLines.join("\n") })
    markdownLines = []
  }

  let index = 0
  while (index < lines.length) {
    const line = lines[index]
    const fence = line.trim().match(/^(`{3,}|~{3,})/)
    if (fence) {
      const marker = fence[1][0]
      if (!inFence) {
        inFence = true
        fenceMarker = marker
      } else if (marker === fenceMarker) {
        inFence = false
        fenceMarker = ""
      }
      markdownLines.push(line)
      index += 1
      continue
    }

    if (!inFence && index + 1 < lines.length && line.includes("|")) {
      const headers = splitPipeRow(line)
      const delimiterCells = splitPipeRow(lines[index + 1])
      const alignments = delimiterCells.map(delimiterAlignment)
      const isTable = headers.length > 0
        && headers.length === delimiterCells.length
        && alignments.every((alignment) => alignment !== null)

      if (isTable) {
        flushMarkdown()
        const rows: string[][] = []
        index += 2
        while (index < lines.length) {
          const rowLine = lines[index]
          if (!rowLine.trim() || !rowLine.includes("|")) break
          const row = splitPipeRow(rowLine)
          if (row.length !== headers.length) break
          rows.push(row)
          index += 1
        }
        blocks.push({
          type: "table",
          headers,
          rows,
          alignments: alignments as TableAlignment[],
        })
        continue
      }
    }

    markdownLines.push(line)
    index += 1
  }

  flushMarkdown()
  return blocks
}

function withCitationLinks(content: string, citations: AgentCitationRef[]): string {
  if (citations.length === 0) return content
  return citationSegments(content, citations)
    .map((segment) => {
      if (!segment.citation) return segment.text
      return `[citation](${CITATION_HREF_PREFIX}${encodeURIComponent(segment.citation.citation_id)})`
    })
    .join("")
}

function componentsFor({
  evidence,
  citations,
  onCitation,
  inline = false,
}: {
  evidence: AgentEvidenceItem[]
  citations: AgentCitationRef[]
  onCitation?: (resolved: ResolvedCitation) => void
  inline?: boolean
}): Components {
  const citationById = new Map(citations.map((citation) => [citation.citation_id, citation] as const))

  return {
    h1: ({ children }) => inline ? <span>{children}</span> : (
      <h1 className="mb-4 mt-7 text-xl font-semibold tracking-tight text-slate-950 first:mt-0">{children}</h1>
    ),
    h2: ({ children }) => inline ? <span>{children}</span> : (
      <h2 className="mb-3 mt-6 text-lg font-semibold tracking-tight text-slate-950 first:mt-0">{children}</h2>
    ),
    h3: ({ children }) => inline ? <span>{children}</span> : (
      <h3 className="mb-2 mt-5 text-base font-semibold text-slate-900 first:mt-0">{children}</h3>
    ),
    h4: ({ children }) => inline ? <span>{children}</span> : (
      <h4 className="mb-2 mt-4 text-sm font-semibold text-slate-900 first:mt-0">{children}</h4>
    ),
    p: ({ children }) => inline
      ? <span>{children}</span>
      : <p className="my-3 text-sm leading-7 text-slate-700 first:mt-0 last:mb-0">{children}</p>,
    strong: ({ children }) => <strong className="font-semibold text-slate-950">{children}</strong>,
    em: ({ children }) => <em className="italic text-slate-700">{children}</em>,
    ul: ({ children }) => inline
      ? <span>{children}</span>
      : <ul className="my-3 list-disc space-y-1.5 pl-6 text-sm leading-7 marker:text-slate-400">{children}</ul>,
    ol: ({ children }) => inline
      ? <span>{children}</span>
      : <ol className="my-3 list-decimal space-y-1.5 pl-6 text-sm leading-7 marker:text-slate-500">{children}</ol>,
    li: ({ children }) => <li className="pl-1 text-slate-700">{children}</li>,
    blockquote: ({ children }) => inline
      ? <span>{children}</span>
      : <blockquote className="my-4 border-l-2 border-slate-300 pl-4 text-sm leading-7 text-slate-600">{children}</blockquote>,
    hr: () => inline ? null : <hr className="my-5 border-slate-200" />,
    pre: ({ children }) => inline
      ? <span>{children}</span>
      : (
        <pre className="my-4 max-w-full overflow-x-auto rounded-[14px] border border-slate-800 bg-slate-950 p-4 text-xs leading-6 text-slate-100 [&>code]:bg-transparent [&>code]:p-0 [&>code]:text-inherit">
          {children}
        </pre>
      ),
    code: ({ children, className }) => (
      <code className={`${className ?? ""} rounded bg-slate-200/70 px-1.5 py-0.5 font-mono text-[0.9em] text-slate-800`}>
        {children}
      </code>
    ),
    a: ({ href, children, title }) => {
      if (href?.startsWith(CITATION_HREF_PREFIX)) {
        const citationId = decodeURIComponent(href.slice(CITATION_HREF_PREFIX.length))
        const citation = citationById.get(citationId)
        if (!citation) return <span>{children}</span>
        const resolved = resolveCitation(citation, evidence)
        return (
          <CitationChip
            citation={citation}
            evidence={resolved.evidence[0]}
            onClick={() => onCitation?.(resolved)}
          />
        )
      }
      return (
        <a
          href={href}
          title={title}
          target="_blank"
          rel="noreferrer"
          className="font-medium text-cyan-700 underline decoration-cyan-200 underline-offset-2 transition hover:text-cyan-900 hover:decoration-cyan-400"
        >
          {children}
        </a>
      )
    },
  }
}

function InlineMarkdown({
  content,
  evidence,
  citations,
  onCitation,
}: {
  content: string
  evidence: AgentEvidenceItem[]
  citations: AgentCitationRef[]
  onCitation?: (resolved: ResolvedCitation) => void
}) {
  return (
    <ReactMarkdown components={componentsFor({ evidence, citations, onCitation, inline: true })}>
      {content}
    </ReactMarkdown>
  )
}

function MarkdownTable({
  headers,
  rows,
  alignments,
  evidence,
  citations,
  onCitation,
}: {
  headers: string[]
  rows: string[][]
  alignments: TableAlignment[]
  evidence: AgentEvidenceItem[]
  citations: AgentCitationRef[]
  onCitation?: (resolved: ResolvedCitation) => void
}) {
  return (
    <div className="my-4 max-w-full overflow-x-auto rounded-[14px] border border-slate-200 bg-white">
      <table className="w-full min-w-[520px] border-collapse text-left text-xs leading-5 text-slate-700">
        <thead className="bg-slate-50 text-slate-900">
          <tr>
            {headers.map((header, index) => (
              <th
                key={`${header}-${index}`}
                className="border-b border-slate-200 px-3 py-2.5 font-semibold"
                style={{ textAlign: alignments[index] }}
              >
                <InlineMarkdown content={header} evidence={evidence} citations={citations} onCitation={onCitation} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`} className="border-b border-slate-100 last:border-b-0">
              {row.map((cell, columnIndex) => (
                <td
                  key={`cell-${rowIndex}-${columnIndex}`}
                  className="px-3 py-2.5 align-top"
                  style={{ textAlign: alignments[columnIndex] }}
                >
                  <InlineMarkdown content={cell} evidence={evidence} citations={citations} onCitation={onCitation} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function AnswerMarkdown({
  content,
  evidence = [],
  citations = [],
  onCitation,
}: {
  content: string
  evidence?: AgentEvidenceItem[]
  citations?: AgentCitationRef[]
  onCitation?: (resolved: ResolvedCitation) => void
}) {
  const markdown = withCitationLinks(content, citations)
  const blocks = splitMarkdownBlocks(markdown)

  return (
    <div className="max-w-none break-words text-slate-700">
      {blocks.map((block, index) => block.type === "table" ? (
        <MarkdownTable
          key={`table-${index}`}
          headers={block.headers}
          rows={block.rows}
          alignments={block.alignments}
          evidence={evidence}
          citations={citations}
          onCitation={onCitation}
        />
      ) : (
        <ReactMarkdown
          key={`markdown-${index}`}
          components={componentsFor({ evidence, citations, onCitation })}
        >
          {block.content}
        </ReactMarkdown>
      ))}
    </div>
  )
}
