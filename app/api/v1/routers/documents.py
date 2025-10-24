from collections import defaultdict
from typing import DefaultDict

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, get_request_context, require_admin_key
from app.api.v1.schemas.document_versions import (
    DocumentVersionDiff,
    DocumentVersionOut,
    DocumentVersionsPage,
)
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
    DocumentVersionNotFoundError,
    MissingUserError,
    get_service_bundle,
)
from app.common.idempotency import IdempotencyService

router = APIRouter()


# Using DocumentCreate/DocumentUpdate from app.api.v1.schemas.documents


def _extract_metadata_filters(request: Request) -> dict[str, list[str]]:
    filters: DefaultDict[str, list[str]] = defaultdict(list)
    for key, value in request.query_params.multi_items():
        if not key.startswith("metadata."):
            continue
        field = key[len("metadata.") :].strip()
        if not field or value in (None, ""):
            continue
        filters[field].append(value)
    return dict(filters)


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
        data = DocumentCreateData(
            title=payload.title,
            metadata=payload.metadata,
            content=payload.content,
            type=payload.type,
            position=payload.position,
        )
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


@router.get("/documents/trash", response_model=DocumentsPage)
def list_deleted_documents(
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    search: str | None = Query(default=None, alias="query"),
    type: str | None = Query(default=None),
    ids: list[int] | None = Query(default=None, alias="id"),
    db: Session = Depends(get_db),
):
    services = get_service_bundle(db)
    document_service = services.document()
    metadata_filters = _extract_metadata_filters(request)
    items, total = document_service.list_deleted_documents(
        page=page,
        size=size,
        metadata_filters=metadata_filters or None,
        search_query=search,
        doc_type=type,
        doc_ids=ids or None,
    )
    return {"page": page, "size": size, "total": total, "items": items}


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
        data = DocumentUpdateData(
            title=payload.title,
            metadata=payload.metadata,
            content=payload.content,
            type=payload.type,
            position=payload.position,
        )
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


@router.delete(
    "/documents/{id}/purge",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin_key)],
)
def purge_document(
    id: int,
    db: Session = Depends(get_db),
    ctx=Depends(get_request_context),
):
    services = get_service_bundle(db)
    document_service = services.document()
    try:
        document_service.purge_document(id, user_id=ctx["user_id"])
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
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    include_deleted: bool = False,
    search: str | None = Query(default=None, alias="query"),
    type: str | None = Query(default=None),
    ids: list[int] | None = Query(default=None, alias="id"),
    db: Session = Depends(get_db),
):
    services = get_service_bundle(db)
    document_service = services.document()
    metadata_filters = _extract_metadata_filters(request)
    items, total = document_service.list_documents(
        page=page,
        size=size,
        include_deleted=include_deleted,
        metadata_filters=metadata_filters or None,
        search_query=search,
        doc_type=type,
        doc_ids=ids or None,
    )
    return {"page": page, "size": size, "total": total, "items": items}


@router.get(
    "/documents/{id}/versions", response_model=DocumentVersionsPage, status_code=200
)
def list_document_versions(
    id: int,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    include_deleted_document: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    services = get_service_bundle(db)
    document_service = services.document()
    version_service = services.document_version()
    try:
        document_service.get_document(id, include_deleted=include_deleted_document)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    items, total = version_service.list_versions(id, page=page, size=size)
    return {"page": page, "size": size, "total": total, "items": items}


@router.get(
    "/documents/{id}/versions/{version_number}",
    response_model=DocumentVersionOut,
    status_code=200,
)
def get_document_version(
    id: int,
    version_number: int,
    include_deleted_document: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    services = get_service_bundle(db)
    document_service = services.document()
    version_service = services.document_version()
    try:
        document_service.get_document(id, include_deleted=include_deleted_document)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        return version_service.get_version(id, version_number)
    except DocumentVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/documents/{id}/versions/{version_number}/diff",
    response_model=DocumentVersionDiff,
    status_code=200,
)
def diff_document_version(
    id: int,
    version_number: int,
    against: int | None = Query(default=None, ge=1),
    include_deleted_document: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    services = get_service_bundle(db)
    document_service = services.document()
    version_service = services.document_version()
    try:
        document = document_service.get_document(
            id, include_deleted=include_deleted_document
        )
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        base_version = version_service.get_version(id, version_number)
    except DocumentVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if against is not None:
        try:
            compare_version = version_service.get_version(id, against)
        except DocumentVersionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        diff = version_service.diff_versions(base_version, compare_version)
    else:
        diff = version_service.diff_version_against_document(base_version, document)
    return diff


@router.post(
    "/documents/{id}/versions/{version_number}/restore",
    response_model=DocumentOut,
    status_code=status.HTTP_200_OK,
)
def restore_document_version(
    id: int,
    version_number: int,
    db: Session = Depends(get_db),
    ctx=Depends(get_request_context),
):
    services = get_service_bundle(db)
    document_service = services.document()
    # version_service = services.document_version()  # no longer used here
    try:
        document_service.get_document(id, include_deleted=True)
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        restored = document_service.restore_document_version(
            id, version_number, user_id=ctx["user_id"]
        )
    except DocumentNotFoundError as exc:
        # Includes the case where the specific version was not found
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return restored
