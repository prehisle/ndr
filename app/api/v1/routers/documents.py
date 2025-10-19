from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, get_request_context
from app.api.v1.schemas.documents import (
    DocumentCreate,
    DocumentOut,
    DocumentsPage,
    DocumentUpdate,
)
from app.app.services import (
    DocumentCreateData,
    DocumentNotFoundError,
    DocumentUpdateData,
    MissingUserError,
    get_service_bundle,
)
from app.common.idempotency import IdempotencyService

router = APIRouter()


# Using DocumentCreate/DocumentUpdate from app.api.v1.schemas.documents


@router.post(
    "/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED
)
def create_document(
    request: Request,
    payload: DocumentCreate,
    db: Session = Depends(get_db),
    ctx=Depends(get_request_context),
):
    user_id = ctx["user_id"]
    service = IdempotencyService(db)
    services = get_service_bundle(db)
    document_service = services.document()

    def executor():
        data = DocumentCreateData(title=payload.title, metadata=payload.metadata)
        try:
            return document_service.create_document(data, user_id=user_id)
        except MissingUserError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = service.handle(
        request=request,
        payload={"body": payload.model_dump(), "user_id": user_id},
        status_code=status.HTTP_201_CREATED,
        executor=executor,
    )
    assert result is not None
    return result.response


@router.get("/documents/{id}", response_model=DocumentOut)
def get_document(id: int, db: Session = Depends(get_db), include_deleted: bool = False):
    services = get_service_bundle(db)
    document_service = services.document()
    try:
        return document_service.get_document(id, include_deleted=include_deleted)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/documents/{id}", response_model=DocumentOut)
def update_document(
    request: Request,
    id: int,
    payload: DocumentUpdate,
    db: Session = Depends(get_db),
    ctx=Depends(get_request_context),
):
    user_id = ctx["user_id"]
    service = IdempotencyService(db)
    services = get_service_bundle(db)
    document_service = services.document()

    def executor():
        data = DocumentUpdateData(title=payload.title, metadata=payload.metadata)
        try:
            return document_service.update_document(id, data, user_id=user_id)
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MissingUserError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = service.handle(
        request=request,
        payload={
            "body": payload.model_dump(mode="json"),
            "resource_id": id,
            "user_id": user_id,
        },
        status_code=status.HTTP_200_OK,
        executor=executor,
    )
    assert result is not None
    return result.response


@router.delete("/documents/{id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete_document(
    id: int, db: Session = Depends(get_db), ctx=Depends(get_request_context)
):
    services = get_service_bundle(db)
    document_service = services.document()
    try:
        document_service.soft_delete_document(id, user_id=ctx["user_id"])
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return None


@router.post("/documents/{id}/restore", response_model=DocumentOut)
def restore_document(
    id: int, db: Session = Depends(get_db), ctx=Depends(get_request_context)
):
    services = get_service_bundle(db)
    document_service = services.document()
    try:
        return document_service.restore_document(id, user_id=ctx["user_id"])
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/documents", response_model=DocumentsPage)
def list_documents(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    include_deleted: bool = False,
    db: Session = Depends(get_db),
):
    document_service = DocumentService(db)
    items, total = document_service.list_documents(
        page=page, size=size, include_deleted=include_deleted
    )
    return {"page": page, "size": size, "total": total, "items": items}
