# AITrans Architecture

## Overview

AITrans is a knowledge-centric AI Agent Workspace.

The architecture is organized around four layers:

```text
User Interaction Layer
        |
Workspace Layer
        |
Agent Runtime Layer
        |
Knowledge Runtime Layer
```

## Agent Runtime

The Agent Runtime provides:

- Supervisor routing
- Agent execution
- Tool calling
- Shared context
- Agent trace

Core agents:

```text
Supervisor Agent
Research Agent
Reading Agent
Translation Agent
Knowledge Retrieval Agent
```

## Knowledge Runtime

Knowledge Runtime manages:

- Knowledge Cards
- Relations
- Retrieval
- Context construction
- Memory updates

## Execution Flow

```text
User Task
   |
Supervisor Agent
   |
Context Construction
   |
Specialized Agent
   |
Tool Execution
   |
Knowledge Update
```

## Design Principle

Translation is treated as an Agent capability rather than the product center.
