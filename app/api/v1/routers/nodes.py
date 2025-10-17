from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.api.v1.deps import get_db, get_request_context
from app.infra.db.models import Node, Document, NodeDocument
from app.api.v1.schemas.nodes import NodeCreate, NodeUpdate, NodeOut, NodesPage


router = APIRouter()


# Using NodeCreate/NodeUpdate from app.api.v1.schemas.nodes

@router.post("/nodes", response_model=NodeOut, status_code=status.HTTP_201_CREATED)
def create_node(payload: NodeCreate, db: Session = Depends(get_db), ctx=Depends(get_request_context)):
    user_id = ctx["user_id"]
    # path 以 slug 构建，父路径存在时以父路径作为前缀
    path = payload.slug if not payload.parent_path else f"{payload.parent_path}.{payload.slug}"
    node = Node(name=payload.name, slug=payload.slug, path=path, created_by=user_id, updated_by=user_id)
    db.add(node)
    db.commit()
    db.refresh(node)
    return node


@router.get("/nodes/{id}", response_model=NodeOut)
def get_node(id: int, db: Session = Depends(get_db), include_deleted: bool = False):
    node = db.get(Node, id)
    if not node or (node.deleted_at is not None and not include_deleted):
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.put("/nodes/{id}", response_model=NodeOut)
def update_node(id: int, payload: NodeUpdate, db: Session = Depends(get_db), ctx=Depends(get_request_context)):
    node = db.get(Node, id)
    if not node or node.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Node not found")
    if payload.name is not None:
        node.name = payload.name
    if payload.slug is not None:
        # 更新 slug 同步更新 path 的最后一段（简化处理）
        parts = node.path.split(".")
        parts[-1] = payload.slug
        node.slug = payload.slug
        node.path = ".".join(parts)
    node.updated_by = ctx["user_id"]
    db.commit()
    db.refresh(node)
    return node


@router.delete("/nodes/{id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete_node(id: int, db: Session = Depends(get_db), ctx=Depends(get_request_context)):
    node = db.get(Node, id)
    if not node or node.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Node not found or already deleted")
    node.deleted_at = func.now()
    node.updated_by = ctx["user_id"]
    db.commit()
    return None


@router.get("/nodes", response_model=NodesPage)
def list_nodes(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    include_deleted: bool = False,
    db: Session = Depends(get_db),
):
    base_stmt = select(Node)
    count_stmt = select(func.count()).select_from(Node)
    if not include_deleted:
        base_stmt = base_stmt.where(Node.deleted_at.is_(None))
        count_stmt = count_stmt.where(Node.deleted_at.is_(None))
    base_stmt = base_stmt.order_by(Node.created_at.desc()).offset((page - 1) * size).limit(size)
    items = list(db.execute(base_stmt).scalars())
    total = db.execute(count_stmt).scalar_one()
    return {"page": page, "size": size, "total": total, "items": items}

# Restore relationship endpoints under nodes for compatibility
@router.post("/nodes/{id}/bind/{doc_id}")
def bind_document(id: int, doc_id: int, db: Session = Depends(get_db), ctx=Depends(get_request_context)):
    node = db.get(Node, id)
    doc = db.get(Document, doc_id)
    if not node or node.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Node not found")
    if not doc or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    # check exists
    exists_stmt = select(NodeDocument).where(NodeDocument.node_id == id, NodeDocument.document_id == doc_id)
    if db.execute(exists_stmt).scalar_one_or_none():
        return {"ok": True}
    nd = NodeDocument(node_id=id, document_id=doc_id, created_by=ctx["user_id"]) 
    db.add(nd)
    db.commit()
    return {"ok": True}

@router.delete("/nodes/{id}/unbind/{doc_id}")
def unbind_document(id: int, doc_id: int, db: Session = Depends(get_db)):
    stmt = select(NodeDocument).where(NodeDocument.node_id == id, NodeDocument.document_id == doc_id)
    nd = db.execute(stmt).scalar_one_or_none()
    if not nd:
        raise HTTPException(status_code=404, detail="Relation not found")
    db.delete(nd)
    db.commit()
    return {"ok": True}

@router.get("/nodes/{id}/children", response_model=list[NodeOut])
def list_children(id: int, depth: int = Query(default=1, ge=1), db: Session = Depends(get_db)):
    # 简化实现：使用字符串前缀匹配模拟 ltree 子树查询
    node = db.get(Node, id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    base = node.path
    stmt = select(Node).where(Node.path.like(f"{base}.%"))
    items = list(db.execute(stmt).scalars())
    # 过滤最大深度（以点分层级）
    max_level = base.count(".") + depth
    items = [n for n in items if n.path.count(".") <= max_level]
    return items