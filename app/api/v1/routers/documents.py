from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from app.api.v1.deps import get_db, get_request_context
from app.infra.db.models import Document
from app.api.v1.schemas.documents import DocumentCreate, DocumentUpdate, DocumentOut, DocumentsPage


router = APIRouter()


# Using DocumentCreate/DocumentUpdate from app.api.v1.schemas.documents

@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def create_document(payload: DocumentCreate, db: Session = Depends(get_db), ctx=Depends(get_request_context)):
    user_id = ctx["user_id"]
    doc = Document(title=payload.title, metadata_=payload.metadata or {}, created_by=user_id, updated_by=user_id)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


@router.get("/documents/{id}", response_model=DocumentOut)
def get_document(id: int, db: Session = Depends(get_db), include_deleted: bool = False):
    doc = db.get(Document, id)
    if not doc or (doc.deleted_at is not None and not include_deleted):
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.put("/documents/{id}", response_model=DocumentOut)
def update_document(id: int, payload: DocumentUpdate, db: Session = Depends(get_db), ctx=Depends(get_request_context)):
    doc = db.get(Document, id)
    if not doc or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found")
    if payload.title is not None:
        doc.title = payload.title
    if payload.metadata is not None:
        doc.metadata_ = payload.metadata
    doc.updated_by = ctx["user_id"]
    db.commit()
    db.refresh(doc)
    return doc


@router.delete("/documents/{id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete_document(id: int, db: Session = Depends(get_db), ctx=Depends(get_request_context)):
    doc = db.get(Document, id)
    if not doc or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Document not found or already deleted")
    doc.deleted_at = func.now()
    doc.updated_by = ctx["user_id"]
    db.commit()
    return None


@router.get("/documents", response_model=DocumentsPage)
def list_documents(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    include_deleted: bool = False,
    db: Session = Depends(get_db),
):
    base_stmt = select(Document)
    count_stmt = select(func.count()).select_from(Document)
    if not include_deleted:
        base_stmt = base_stmt.where(Document.deleted_at.is_(None))
        count_stmt = count_stmt.where(Document.deleted_at.is_(None))
    base_stmt = base_stmt.order_by(Document.created_at.desc()).offset((page - 1) * size).limit(size)
    items = list(db.execute(base_stmt).scalars())
    total = db.execute(count_stmt).scalar_one()
    return {"page": page, "size": size, "total": total, "items": items}