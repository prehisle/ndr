from __future__ import annotations


class Permissions:
    DOCUMENTS_READ = "documents:read"
    DOCUMENTS_WRITE = "documents:write"
    DOCUMENTS_PURGE = "documents:purge"

    NODES_READ = "nodes:read"
    NODES_WRITE = "nodes:write"
    NODES_PURGE = "nodes:purge"

    RELATIONSHIPS_READ = "relationships:read"
    RELATIONSHIPS_WRITE = "relationships:write"


__all__ = ["Permissions"]
