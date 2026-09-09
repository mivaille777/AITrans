# AITrans

AITrans is a local-first **AI Agent Workspace** focused on document understanding, research assistance, and personal knowledge management.

The project has evolved from an early desktop translation assistant into a knowledge-centric multi-agent system that combines:

- Multi-Agent orchestration
- Knowledge Workspace
- Retrieval-Augmented Generation (RAG)
- Knowledge Graph
- Reading and Research Agents
- Translation Agent as one of many capabilities

中文简介：

> AITrans 是一个以知识空间为核心的本地化 AI Agent 工作平台，通过多智能体协作、RAG、知识图谱和个人知识管理能力，帮助用户完成文献阅读、研究分析、知识沉淀和智能交互。

---

## Core Architecture

```text
User
 |
 v
Supervisor Agent
 |
 +----------------+
 |                |
Research Agent  Reading Agent
 |
Translation Agent
 |
 v
Agent Runtime
 |
Knowledge Runtime
 |
Knowledge Workspace
 |
Personal Memory
```

AITrans does not treat translation as the final product. Translation is provided as an Agent capability inside a larger reading and research workflow.

---

## Knowledge Workspace

The Knowledge Workspace is the central interaction layer.

It provides:

- Knowledge Cards
- Knowledge Graph relationships
- Document context
- Agent-generated insights
- Research notes
- Retrieval and reuse

Typical workflow:

```text
Import Document
      |
Extract Knowledge
      |
Generate Knowledge Cards
      |
Build Relations
      |
Ask Agents
      |
Update Personal Knowledge Base
```

---

## Multi-Agent System

Current agent direction:

```text
Supervisor Agent
        |
        +-- Research Agent
        |
        +-- Reading Agent
        |
        +-- Translation Agent
        |
        +-- Knowledge Retrieval Agent
```

Agents share context through the Knowledge Runtime and Workspace Context system.

---

## Document Intelligence

Supported scenarios:

- PDF reading
- Academic paper analysis
- Web reading context capture
- Word/document understanding
- Research note generation

The original selection and translation features are retained as reading interaction capabilities.

---

## RAG and Knowledge Runtime

AITrans integrates:

- Vector retrieval
- Knowledge relationships
- Context construction
- Agent grounding

The goal is not only answering questions, but building reusable personal knowledge.

---

## Desktop Integration

AITrans supports desktop reading workflows through:

- Browser Selection Bridge
- Reading Context Capture
- AI Chat
- Research Notes

These components serve as entry points for Agent interaction.

---

## Development

Main development branch:

```text
WebReBuild
```

Recommended environment:

```text
Python 3.11
Node.js
Rust/Tauri
```

Run:

```powershell
.\scripts\start.ps1
```

Test:

```powershell
python -m pytest -q
```

---

## Roadmap

Future development focuses on:

- Advanced Agent orchestration
- Multimodal RAG
- Research Agent
- Long-term Memory
- Knowledge Graph evolution
- Personal AI Research Assistant

---

## Project Evolution

AITrans evolution:

```text
Translation Assistant
        |
        v
Reading Assistant
        |
        v
Knowledge Workspace
        |
        v
Multi-Agent AI Research Assistant
```
