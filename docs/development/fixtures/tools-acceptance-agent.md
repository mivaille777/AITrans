# Tools acceptance source

## Agent tool policy

An AI agent uses registered tools to read a document, retrieve evidence, and save a research note.
The Tools workbench separates typed arguments from trusted document scope. Search can only access explicitly selected documents.
A write call waits for approval bound to its tool call ID, input fingerprint, and configuration revision.
Cancelling a response does not prove that the underlying executor has stopped. An uncertain write must not be automatically retried.

## Retrieval pipeline

The local index parses Markdown, creates document chunks, and stores dense vectors and a BM25 sparse index.
Hybrid retrieval combines scoped dense and sparse candidates. Reading a returned chunk exposes the source text for evidence.
