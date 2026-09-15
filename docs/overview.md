# AITrans Overview

## Product Positioning

AITrans is a local-first, knowledge-centric AI Agent workspace.

The project has evolved from an early translation-oriented desktop assistant into a general AI workspace that combines:

- Multi-Agent orchestration
- Knowledge Workspace
- Retrieval-Augmented Generation (RAG)
- Document understanding
- Personal knowledge memory
- Context-aware AI interaction

## Core Idea

AITrans does not treat translation as the final product boundary. Translation is one specialized capability provided by a Translation Agent inside the larger Agent ecosystem.

The system is designed around:

```
User Task
    |
    v
Supervisor Agent
    |
    +----------------+
    |                |
Research Agent   Reading Agent
    |
Translation Agent
    |
Knowledge Runtime
    |
Knowledge Workspace
```

## Agent Capabilities

Current and planned agents include:

- Supervisor Agent: task routing and orchestration
- Research Agent: information discovery and synthesis
- Reading Agent: document understanding and contextual assistance
- Translation Agent: knowledge-aware translation
- Knowledge Agent: knowledge extraction and organization

## Design Principle

Knowledge is the foundation of reasoning. Documents, notes, interactions, and agent outputs are transformed into reusable knowledge structures that improve future agent tasks.
