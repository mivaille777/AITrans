# AITrans Architecture Overview

## System Layers

```
                         User
                           |
                           v
                Knowledge Workspace
                           |
                           v
                 Supervisor Agent
                           |
        ---------------------------------
        |               |               |
        v               v               v
 Research Agent   Reading Agent   Translation Agent
        |               |               |
        ---------------------------------
                           |
                           v
                  Agent Runtime Layer
                           |
                           v
                 Knowledge Runtime
                           |
        ---------------------------------
        |               |               |
       RAG        Knowledge Graph    Memory
```

## Layer Responsibilities

### Knowledge Workspace

The primary user interaction layer:

- Document reading
- Knowledge cards
- Graph visualization
- Agent interaction
- Research memory

### Agent Runtime

Responsible for:

- Agent lifecycle
- Routing
- Context construction
- Tool execution
- Trace generation

### Knowledge Runtime

Responsible for:

- Document ingestion
- Retrieval
- Knowledge representation
- Context grounding

## Product Evolution

AITrans has moved from a translation-focused application toward a general AI Agent workspace. Existing desktop interaction and translation features remain as capabilities inside the Agent ecosystem.
