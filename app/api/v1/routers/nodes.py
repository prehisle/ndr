from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session
from sqlalchemy import select, func, cast

from app.api.v1.deps import get_db, get_request_context
from app.infra.db.models import Node, Document, NodeDocument
from app.api.v1.schemas.nodes import NodeCreate, NodeUpdate, NodeOut, NodesPage
from app.common.idempotency import IdempotencyService
from app.infra.db.types import HAS_POSTGRES_LTREE

try:  # Optional import; available when PostgreSQL ltree extras are installed.
    from sqlalchemy.dialects.postgresql import LQUERY
except ImportError:  # pragma: no cover - fallback when ltree extras missing
    LQUERY = None


router = APIRouter()


# Using NodeCreate/NodeUpdate from app.api.v1.schemas.nodes

@router.post("/nodes", response_model=NodeOut, status_code=status.HTTP_201_CREATED)
def create_node(
    request: Request,
    payload: NodeCreate,
    db: Session = Depends(get_db),
    ctx=Depends(get_request_context),
):
    user_id = ctx["user_id"]
    service = IdempotencyService(db)

    def executor():
        parent_path = payload.parent_path or None
        path = payload.slug if not parent_path else f"{parent_path}.{payload.slug}"
        # 路径唯一性校验（仅针对未软删节点）
        conflict = db.execute(
            select(Node).where(Node.deleted_at.is_(None), Node.path == path)
        ).scalar_one_or_none()
        if conflict:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Node path already exists")

        # 同一父节点下 name 唯一
        siblings_stmt = select(Node).where(
            Node.deleted_at.is_(None),
            Node.parent_path.is_(parent_path) if parent_path is None else Node.parent_path == parent_path,
            Node.name == payload.name,
        )
        sibling_conflict = db.execute(siblings_stmt).scalar_one_or_none()
        if sibling_conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Node name already exists under the same parent",
            )

        node = Node(
            name=payload.name,
            slug=payload.slug,
            parent_path=parent_path,
            path=path,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(node)
        db.commit()
        db.refresh(node)
        return node

    result = service.handle(
        request=request,
        payload={"body": payload.model_dump(), "user_id": user_id},
        status_code=status.HTTP_201_CREATED,
        executor=executor,
    )
    assert result is not None
    return result.response


@router.get("/nodes/{id}", response_model=NodeOut)
def get_node(id: int, db: Session = Depends(get_db), include_deleted: bool = False):
    node = db.get(Node, id)
    if not node or (node.deleted_at is not None and not include_deleted):
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.put("/nodes/{id}", response_model=NodeOut)
def update_node(
    request: Request,
    id: int,
    payload: NodeUpdate,
    db: Session = Depends(get_db),
    ctx=Depends(get_request_context),
):
    node = db.get(Node, id)
    if not node or node.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Node not found")

    user_id = ctx["user_id"]
    service = IdempotencyService(db)

    def executor():
        if payload.name is not None:
            # 校验同一父路径下 name 唯一
            siblings_stmt = select(Node).where(
                Node.deleted_at.is_(None),
                Node.name == payload.name,
                Node.id != node.id,
                Node.parent_path.is_(node.parent_path) if node.parent_path is None else Node.parent_path == node.parent_path,
            )
            conflict = db.execute(siblings_stmt).scalar_one_or_none()
            if conflict:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Node name already exists under the same parent",
                )
            node.name = payload.name
        if payload.slug is not None:
            parts = node.path.split(".")
            parts[-1] = payload.slug
            new_path = ".".join(parts)
            # 校验路径唯一
            conflict = db.execute(
                select(Node).where(
                    Node.deleted_at.is_(None),
                    Node.path == new_path,
                    Node.id != node.id,
                )
            ).scalar_one_or_none()
            if conflict:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Node path already exists")
            node.slug = payload.slug
            node.path = new_path
        node.updated_by = user_id
        db.commit()
        db.refresh(node)
        return node

    result = service.handle(
        request=request,
        payload={"body": payload.model_dump(mode="json"), "resource_id": id, "user_id": user_id},
        status_code=status.HTTP_200_OK,
        executor=executor,
    )
    assert result is not None
    return result.response


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
    user_id = ctx["user_id"]
    exists_stmt = select(NodeDocument).where(NodeDocument.node_id == id, NodeDocument.document_id == doc_id)
    existing = db.execute(exists_stmt).scalar_one_or_none()
    if existing:
        if existing.deleted_at is None:
            return {"ok": True}
        existing.deleted_at = None
        existing.updated_by = user_id
        db.commit()
        return {"ok": True}
    nd = NodeDocument(node_id=id, document_id=doc_id, created_by=user_id, updated_by=user_id)
    db.add(nd)
    db.commit()
    return {"ok": True}

@router.delete("/nodes/{id}/unbind/{doc_id}")
def unbind_document(id: int, doc_id: int, db: Session = Depends(get_db), ctx=Depends(get_request_context)):
    stmt = select(NodeDocument).where(NodeDocument.node_id == id, NodeDocument.document_id == doc_id)
    nd = db.execute(stmt).scalar_one_or_none()
    if not nd or nd.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Relation not found")
    nd.deleted_at = func.now()
    nd.updated_by = ctx["user_id"]
    db.commit()
    return {"ok": True}

@router.get("/nodes/{id}/children", response_model=list[NodeOut])
def list_children(id: int, depth: int = Query(default=1, ge=1), db: Session = Depends(get_db)):
    node = db.get(Node, id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    bind = db.get_bind()
    is_postgres = bind is not None and bind.dialect.name == "postgresql"

    if (
        is_postgres
        and HAS_POSTGRES_LTREE
        and LQUERY is not None
    ):
        pattern = f"{node.path}.*{{1,{depth}}}"
        stmt = (
            select(Node)
            .where(Node.deleted_at.is_(None))
            .where(Node.path.op("<@")(cast(pattern, LQUERY())))
            .order_by(Node.path)
        )
        items = list(db.execute(stmt).scalars())
    else:
        base = node.path
        stmt = (
            select(Node)
            .where(Node.deleted_at.is_(None))
            .where(Node.path.like(f"{base}.%"))
            .order_by(Node.path)
        )
        items = list(db.execute(stmt).scalars())
        max_level = base.count(".") + depth
        items = [n for n in items if n.path.count(".") <= max_level]

    return items
