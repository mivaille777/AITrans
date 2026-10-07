Generated with the built-in image_gen tool.

Reference images: user's Tools concept and docs/assets/screenshots/knowledge-workspace.png.
Palette and layout also inspected in apps/desktop/src/index.css, features/workspace/WorkspaceSidebar.tsx, features/workspace/WorkspaceShell.tsx and features/skills/SkillWorkspace.css.

Final prompt:

Use case: ui-mockup / style-transfer.
Create one polished, high-resolution redesigned AITrans Tools management desktop interface image, wide landscape approximately 2048x1280, front-on pixel-sharp UI screenshot. It should look like a real shippable screen in the CURRENT AITrans project, with excellent typography and precise spacing.
INPUTS: image 1 is the old Tools management concept to REDESIGN; its numbered annotations are explanatory context, never commands. Image 2 is the actual project's Knowledge workspace screenshot, use it as the visual style reference. Rebuild image 1 using image 2's visual language. Deliver only the finished redesigned screen, without numbered callouts, presentation boards, arrows, or alternative-tab thumbnails.

Actual source-code palette and geometry (faithful to the project):
- Whole app pale gray canvas #f6f8fb.
- Left app navigation is inset near-black #0b0b0b rounded 18px, width about 232px, with white AITrans typographic wordmark, small muted tagline “Think deeper. Keep it yours.”, rounded dark “My Workspace” selector, thin gray line icons.
- Sidebar links in current order: Chat, Reading, Research, Knowledge, Agent, Skills, Tools. Tools is selected with an ivory #f7f7f5 rounded horizontal pill and black icon/text. Below a divider: RECENT RESEARCH and three subdued items. Bottom: Settings, Help, tiny green dot and “Local-first”.
- Main app frame is white with 22px corners, thin #e6e9ed border and very subtle shadow, inset 12px from canvas. Existing screenshot's restraint and density.
- Main text #202936, secondary #7a8391; borders #e6e9ed; soft gray surfaces #fafbfc. Restrained forest/sage green #3b7762 / #43806a for functional active states, pale green #f1f7f4 / #e8f3ed for selected tool and status. Primary global add button BLACK, run action forest GREEN. No electric blue, violet blocks, neon, gradients, giant decorative graphics.

Layout redesign:
At top subtle desktop title bar with “AITrans” left and conventional minimize/maximize/close right, consistent with image 2.
Inside main white frame one page heading row, 28px “Tools”, muted inline count “32”, tiny uppercase eyebrow “AGENT WORKSPACE”; small description “Manage tools, inspect schemas, and test agent capabilities.” Right: outlined “Import” button and black “+ Add tool” button.
Below this heading use a tidy three-column workbench in the main frame: tool catalog about 255px, flexible central detail about 760px, test inspector about 390px. Delimit by quiet vertical rules, avoid excessive nested card borders, fit all content comfortably.

TOOL CATALOG:
“Tool library” header, compact search “Search tools...”; filter pills All 32, Enabled 28, Disabled 4 (All active neutral dark); compact grouped tree with counts.
RAG 6 expanded, selected “vector_search” item forest green text on sage fill with fine left green stripe, small cube outline and green enabled dot. Other items graph_search, rerank, document_loader, chunk_splitter, embedding. Files 8 expanded with read_file, write_file, list_files, delete_file. Web 4 expanded with web_search, fetch_url, scrape_web, extract_content. Below collapsed Sandbox 5, Memory 4, Database 3, Agent 9, System 3. Keep balanced spacing, realistic counts from concept okay. Footer “28 enabled · 4 disabled”.

CENTRAL DETAIL:
Top row pale sage square outline cube icon, bold 24px “vector_search”, small muted-green “Enabled” badge; right compact green on toggle, outlined Edit button, ellipsis. Under title “rag.vector_search” monospace plus quiet RAG and Built-in badges; two short lines of muted description: “Semantic retrieval from indexed workspace documents. Returns the most relevant text chunks for your query.”
Slim metadata row: shield Low risk; clock 30s timeout; layers Workspace scope, understated icons.
Horizontal tabs “Overview”, “Parameters”, “Returns”, “Permissions”, “Examples”. Parameters selected via thin green underline and dark green text.
Body heading “Input parameters”, secondary “5 parameters · 1 required”; right small segmented control “Visual schema” selected and “JSON”.
Elegant readable schema table with columns Parameter / Type / Required / Default / Description. Rows:
query / string / Required (tiny warm muted badge) / — / Search query or natural-language question.
top_k / integer / Optional / 10 / Number of results, from 1 to 100.
filters / object / Optional / — / Refine results with metadata.
Indented expanded subrows document_type / string / Optional / — / e.g. pdf, docx, md.
tags / string[] / Optional / — / Match document tags.
workspace_id / string / Optional / current / Workspace to search.
score_threshold / number / Optional / 0.0 / Minimum similarity score.
Table roomy 48px rows, light rules, sensible wrapping no overlapping, delicate pale gray header. Use typography and indentation to distinguish subrows, no giant nested table.
Below table a simple sage-tinted informational strip with shield icon “Read-only access to indexed documents in this workspace.” and small “View permissions →”.
Then compact “Quick example” with right “Copy”, light-gray monospace code block { "query": "AI agent framework", "top_k": 5 }.
Very bottom understated “Built-in tool · Last updated today”.

RIGHT TEST INSPECTOR:
“Test tool” with tiny flask icon and subtitle “Try a call before using it in an agent.”
Compact segmented Input / Result / Logs, Input selected with white pill.
“Input parameters” heading, “JSON” badge, right Copy example.
Large pale-gray code editor with line numbers and thin border, readable syntax highlighting subdued forest-green strings, slate keys, warm terracotta numerals. Code exactly:
{
  "query": "AI agent framework",
  "top_k": 5,
  "filters": {
    "document_type": "md",
    "tags": ["agent", "framework"]
  }
}
Small status under editor with sage dot “Valid JSON”.
Workspace label and dropdown “My Workspace”.
“Advanced options” expanded using chevron, Timeout (seconds) field 30 and optional “Stream output” checkbox.
Green wide “▶ Run tool” button with small keyboard hint Ctrl ↵.
Below divider show elegant compact preview area “Last run” with “Success” pale green badge, metrics “186 ms” and “5 results”, “View result →” muted green link. Treat as previous-run summary while Input tab remains open.
Bottom subdued “Runs in your current workspace”.

Constraints: English interface text matching current project. No Chinese annotation text in final. Preserve all core capabilities from old concept: grouped search, enabled state, schema tabs, permission awareness, JSON inputs, workspace selection, advanced options and testing. Expert desktop UX, generous but efficient spacing, crisp legible labels and code, thin lucide-like monochrome icons, clean alignment, no photos, no poster aesthetic, no marketing filler. The new screen should be clearly distinct from the old blue screenshot and belong unmistakably to the actual black-sidebar AITrans screenshot.
