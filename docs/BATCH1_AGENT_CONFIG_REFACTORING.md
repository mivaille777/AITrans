# Batch 1: Agent Configuration Refactoring

## Goal

Migrate remaining product-level configuration concepts from the early translation application model to the current AITrans Agent Workspace model.

## Scope

This batch keeps runtime behavior unchanged and focuses on naming, configuration boundaries, and future extensibility.

## Current Findings

`config/default.toml` still contains legacy application naming:

```toml
[app]
name = "Desktop Translator"
```

The translation provider configuration remains valid because translation is now a specialized Agent capability.

## Refactoring Direction

Target architecture:

```text
AITrans Workspace
        |
        +-- Agent Runtime
        |
        +-- Knowledge Runtime
        |
        +-- Research Agent
        +-- Reading Agent
        +-- Translation Agent
        |
        +-- Retrieval / RAG
```

## Planned Changes

### App Identity

Before:

```text
Desktop Translator
```

After:

```text
AITrans Agent Workspace
```

### Translation Configuration

Keep:

- provider
- source language
- target language
- cache

because they belong to Translation Agent.

Move future settings toward:

```text
[agents.translation]
[agents.reading]
[agents.research]

[knowledge]
[workspace]
```

## Safety Rule

No runtime behavior changes are introduced in Batch 1. Existing translation, RAG, and desktop interaction workflows remain compatible.
