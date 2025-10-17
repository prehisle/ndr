from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.api.v1.deps import get_db, get_request_context
from app.infra.db.models import Node, Document, NodeDocument
from app.api.v1.schemas.relationships import RelationshipOut


router = APIRouter()


@router.post("/relationships", response_model=RelationshipOut, status_code=status.HTTP_201_CREATED)
def bind_relationship(node_id: int, document_id: int, db: Session = Depends(get_db), ctx=Depends(get_request_context)):
    node = db.get(Node, node_id)
    doc = db.get(Document, document_id)
    if not node or node.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Node not found")
    if not doc or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")

    # 检查是否已存在
    exists_stmt = select(NodeDocument).where(
        NodeDocument.node_id == node_id, NodeDocument.document_id == document_id
    )
    exists = db.execute(exists_stmt).scalar_one_or_none()
    if exists:
        return exists

    nd = NodeDocument(node_id=node_id, document_id=document_id, created_by=ctx["user_id"])
    db.add(nd)
    db.commit()
    return nd


@router.delete("/relationships", status_code=status.HTTP_204_NO_CONTENT)
def unbind_relationship(
    node_id: int = Query(...),
    document_id: int = Query(...),
    db: Session = Depends(get_db),
):
    stmt = select(NodeDocument).where(NodeDocument.node_id == node_id, NodeDocument.document_id == document_id)
    nd = db.execute(stmt).scalar_one_or_none()
    if not nd:
        raise HTTPException(status_code=404, detail="Relation not found")
    db.delete(nd)
    db.commit()
    return None


@router.get("/relationships", response_model=list[RelationshipOut])
def list_relationships(
    node_id: Optional[int] = None,
    document_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    stmt = select(NodeDocument)
    if node_id is not None:
        stmt = stmt.where(NodeDocument.node_id == node_id)
    if document_id is not None:
        stmt = stmt.where(NodeDocument.document_id == document_id)
    items = list(db.execute(stmt).scalars())
    return items