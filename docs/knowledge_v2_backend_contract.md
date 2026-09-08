# Knowledge 2.0 Backend Contract

## Base Path

`/api/knowledge/v2`

## Cards

GET `/cards`

Returns Knowledge Cards for the canvas.

GET `/cards/{card_id}`

Returns card detail, evidence and relations.

## Graph

GET `/graph`

Returns React Flow compatible graph data:

```json
{
  "nodes": [],
  "edges": []
}
```

## Agent Events

GET `/events`

Returns Agent generated knowledge operations for observability.
