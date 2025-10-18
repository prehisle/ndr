from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, get_request_context
from app.api.v1.schemas.relationships import RelationshipOut
from app.common.idempotency import IdempotencyService
from app.infra.db.models import Document, Node, NodeDocument

router = APIRouter()


@router.post(
    "/relationships",
    response_model=RelationshipOut,
    status_code=status.HTTP_201_CREATED,
)
def bind_relationship(
    request: Request,
    node_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    ctx=Depends(get_request_context),
):
    node = db.get(Node, node_id)
    doc = db.get(Document, document_id)
    if not node or node.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Node not found")
    if not doc or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")

    service = IdempotencyService(db)
    user_id = ctx["user_id"]

    def executor():
        exists_stmt = select(NodeDocument).where(
            NodeDocument.node_id == node_id,
            NodeDocument.document_id == document_id,
        )
        exists = db.execute(exists_stmt).scalar_one_or_none()
        if exists:
            if exists.deleted_at is None:
                return exists
            exists.deleted_at = None
            exists.updated_by = user_id
            db.commit()
            db.refresh(exists)
            return exists
        nd = NodeDocument(
            node_id=node_id,
            document_id=document_id,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(nd)
        db.commit()
        db.refresh(nd)
        return nd

    result = service.handle(
        request=request,
        payload={"node_id": node_id, "document_id": document_id, "user_id": user_id},
        status_code=status.HTTP_201_CREATED,
        executor=executor,
    )
    assert result is not None
    return result.response


@router.delete("/relationships", status_code=status.HTTP_204_NO_CONTENT)
def unbind_relationship(
    node_id: int = Query(...),
    document_id: int = Query(...),
    db: Session = Depends(get_db),
    ctx=Depends(get_request_context),
):
    stmt = select(NodeDocument).where(
        NodeDocument.node_id == node_id, NodeDocument.document_id == document_id
    )
    nd = db.execute(stmt).scalar_one_or_none()
    if not nd or nd.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Relation not found")
    nd.deleted_at = func.now()
    nd.updated_by = ctx["user_id"]
    db.commit()
    return None


@router.get("/relationships", response_model=list[RelationshipOut])
def list_relationships(
    node_id: Optional[int] = None,
    document_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    stmt = select(NodeDocument).where(NodeDocument.deleted_at.is_(None))
    if node_id is not None:
        stmt = stmt.where(NodeDocument.node_id == node_id)
    if document_id is not None:
        stmt = stmt.where(NodeDocument.document_id == document_id)
    items = list(db.execute(stmt).scalars())
    return items
