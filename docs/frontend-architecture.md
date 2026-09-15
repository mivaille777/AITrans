# AITrans Frontend Architecture

## Overview

The frontend is designed as a Knowledge Workspace rather than a traditional translation interface.

The main interaction model is:

```
User
 |
 v
Knowledge Workspace
 |
 +----------------+
 |                |
Reader        Knowledge Canvas
 |
Agent Panel
 |
Context Interaction
```

## Core UI Modules

### Knowledge Workspace

Central user workspace containing:

- Knowledge Cards
- Document views
- Knowledge Graph visualization
- Agent results
- Research notes

### Reader

Provides document understanding workflows:

- PDF/document reading
- Context extraction
- Highlight interaction
- Agent assistance

### Agent Panel

Displays:

- Supervisor routing
- Agent execution trace
- Tool calls
- Generated insights

### Translation Capability

Translation is retained as an Agent capability:

```
Translation Request
        |
        v
Translation Agent
        |
        v
Knowledge-aware Result
```

It is not the primary product entry point.
