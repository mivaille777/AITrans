from __future__ import annotations

import json
from hashlib import sha256

from app.research.memory import ResearchMemoryEntityDraft
from backend.rag.graph.models import GraphEntity, normalize_alias


class EntityResolver:
    version = "explicit-alias-context-v1"

    def resolve(
        self, entity: ResearchMemoryEntityDraft, *, scope_id: str, document_id: str
    ) -> GraphEntity:
        if not scope_id.strip() or not document_id.strip():
            raise ValueError("entity scope and source document must be explicit")
        names = sorted(
            {
                name.strip()
                for name in (entity.canonical_name, *entity.aliases)
                if name.strip()
            },
            key=lambda name: (-len(normalize_alias(name)), normalize_alias(name), name),
        )
        if not names:
            raise ValueError("entity must have a non-empty name")
        canonical = names[0]
        # Only identical, source-verified definitions can bridge documents.
        # Without a definition, same-name mentions remain document-local.
        context = (
            ["definition", normalize_alias(entity.description)]
            if entity.description.strip()
            else ["document", document_id]
        )
        identity = json.dumps(
            [
                scope_id,
                normalize_alias(canonical),
                normalize_alias(entity.entity_type),
                context,
            ],
            ensure_ascii=False,
        )
        return GraphEntity(
            entity_id="entity_" + sha256(identity.encode()).hexdigest()[:32],
            scope_id=scope_id,
            canonical_name=canonical,
            entity_type=entity.entity_type,
            description=entity.description,
            aliases=names,
        )
