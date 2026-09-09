# AITrans Repository Structure

## Overview

AITrans is organized around an AI Agent Workspace architecture rather than a traditional translation application.

The repository is divided into several layers:

```
AITrans
 |
 +-- apps/
 |     Desktop Workspace UI
 |
 +-- backend/
 |     Agent Runtime
 |     Knowledge Runtime
 |     Retrieval Services
 |
 +-- config/
 |     Agent and model configuration
 |
 +-- docs/
 |     Architecture and development documents
```

## Backend Architecture

The backend follows an Agent-oriented design:

```
User Request
     |
     v
Agent Router
     |
Supervisor Agent
     |
+----------------+
|                |
Research       Reading
Agent          Agent
|
Translation Agent
     |
Knowledge Runtime
     |
Knowledge Store
```

## Frontend Architecture

The desktop application is centered around Knowledge Workspace:

```
Knowledge Workspace
 |
 +-- Canvas
 |
 +-- Graph
 |
 +-- Library
 |
 +-- Reader
 |
 +-- Agent Interaction
```

## Product Position

Translation remains an important capability, but it is implemented as one specialized agent ability.

The primary product goal is:

- document understanding
- research assistance
- knowledge management
- multi-agent collaboration
