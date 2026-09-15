# AITrans Backend Architecture

## Overview

The backend provides the runtime foundation for AITrans Agents.

Current architecture:

```
API Layer
   |
Agent Runtime
   |
+----------------------+
|                      |
Supervisor Runtime   Agent Tools
|
Research / Reading / Translation Agents
|
Knowledge Runtime
|
RAG + Memory + Storage
```

## Major Components

### Agent Runtime

Responsible for:

- Agent lifecycle
- Task execution
- Context passing
- Multi-agent coordination

### Knowledge Runtime

Responsible for:

- Knowledge cards
- Relations
- Retrieval
- Context construction

### RAG System

Provides:

- Document retrieval
- Semantic search
- Agent grounding

### Agent Tools

External capabilities exposed to agents:

- Document processing
- Search
- Translation
- Knowledge operations

## Agent Roles

### Supervisor Agent

Responsible for:

- Task understanding
- Agent routing
- Workflow coordination

### Research Agent

Handles:

- Literature analysis
- Information synthesis

### Reading Agent

Handles:

- Document understanding
- Context extraction

### Translation Agent

Provides translation capability as part of the larger workflow.
