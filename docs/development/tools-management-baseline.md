# Tools implementation baseline

2026-10-07. Branch: codex/tools-management. Base: 56675625a24f0fe209202f86b19f3cad846867bb (maindev).

Implementation lives in a managed independent worktree. D:/AITrans contains uncommitted Chat/RAG/startup changes, including full-read refinements; they are intentionally not incorporated into this branch. Their regression results cannot be claimed for this base. Integration with those changes must be separately verified before merging.

Python: use Conda environment aitrans. System/base Python cannot collect backend HTTP tests (missing faiss). Desktop dependencies initially reused a junction; T02 copied the same dependencies locally because Vite emitted external absolute manifest keys that failed the existing PDF guard. No dependency upgrade. Baseline tests: 24 passed in the project environment.

Default lightweight AgentToolRegistry exposes 16 tools: inspect_reading_context; translate_selection; explain_selection; summarize_selection; analyze_section_role; polish_selection; save_research_note; list_research_notes; search_research_notes; get_research_note; update_research_note; define_terms; analyze_equation; summarize_current_section; search_knowledge_base; save_knowledge_card. Production dependencies additionally register knowledge catalog/reads, memory/research/ledger and sandbox tools. Counts therefore come from the active registry, never a constant.

Entry points: /api/agent/tools → registry.list_tools; /api/agent/tools/{name}/execute → registry.execute; ProductAgentService → registry/execution service; ProductAgentToolRuntimePort → authorized task → ProductAgentService; native Chat → KnowledgeFunctionRun → KnowledgeAgentTools; full-read → snapshot_document/read_document_batch. All must obey the same capability policy. Skill functions retain their existing Skills policy.

Native search input: KnowledgeFunctionSearchArgs (document_ids and top_k required, top_k <= 8). Agent search: KnowledgeSearchArgs (optional scope, top_k <= 50). Management test uses Agent definition; native profile is separately shown. Results use typed result_model.

Visual baseline: docs/design/tools-management-redesign-2026-10-07.png. 1680×1050 and 1920×1080 full workbench; 1280×800 inspector drawer; narrow library collapse. Route owns heading and scroll containers; no duplicate WorkspaceHeader. Current application is English, black sidebar and sage functional accents.
