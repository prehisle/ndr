from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, get_request_context, require_admin_key
from app.api.v1.descriptions import SUBTREE_DOCUMENTS_DESCRIPTION
from app.api.v1.schemas.documents import DocumentsPage
from app.api.v1.schemas.nodes import (
    NodeCreate,
    NodeOut,
    NodeReorderPayload,
    NodesPage,
    NodeUpdate,
)
from app.api.v1.utils import extract_metadata_filters
from app.app.services import (
    DocumentNotFoundError,
    InvalidNodeOperationError,
    MissingUserError,
    NodeConflictError,
    NodeCreateData,
    NodeNotFoundError,
    NodeReorderData,
    NodeUpdateData,
    ParentNodeNotFoundError,
    RelationshipNotFoundError,
    get_service_bundle,
)
from app.common.idempotency import IdempotencyService
from app.domain.repositories.node_repository import LtreeNotAvailableError

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
    services = get_service_bundle(db)
    node_service = services.node()

    def executor():
        try:
            data = NodeCreateData(
                name=payload.name,
                slug=payload.slug,
                parent_path=payload.parent_path,
                type=payload.type,
            )
            return node_service.create_node(data, user_id=user_id)
        except NodeConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ParentNodeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InvalidNodeOperationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
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


@router.get("/nodes/by-path", response_model=NodeOut)
def get_node_by_path(
    path: str = Query(..., description="节点路径，如 'course.chapter.section'"),
    include_deleted: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    """通过路径获取节点。

    路径格式为以点号分隔的 slug 序列，如 "course.chapter.section"。
    """
    services = get_service_bundle(db)
    node_service = services.node()
    try:
        return node_service.get_node_by_path(path, include_deleted=include_deleted)
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/nodes/by-path/subtree-documents",
    response_model=DocumentsPage,
    description=SUBTREE_DOCUMENTS_DESCRIPTION,
)
def get_subtree_documents_by_path(
    request: Request,
    path: str = Query(..., description="节点路径，如 'course.chapter'"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    include_deleted_nodes: bool = Query(default=False),
    include_deleted_documents: bool = Query(default=False),
    include_descendants: bool = Query(default=True),
    search: str | None = Query(default=None, alias="query"),
    type: str | None = Query(default=None),
    doc_ids: list[int] | None = Query(default=None, alias="id"),
    db: Session = Depends(get_db),
):
    """通过节点路径获取子树下的文档列表。

    支持与 /nodes/{id}/subtree-documents 相同的过滤参数。
    """
    services = get_service_bundle(db)
    node_service = services.node()
    metadata_filters = extract_metadata_filters(request)
    try:
        items, total = node_service.paginate_subtree_documents_by_path(
            path,
            page=page,
            size=size,
            include_deleted_nodes=include_deleted_nodes,
            include_deleted_documents=include_deleted_documents,
            include_descendants=include_descendants,
            metadata_filters=metadata_filters or None,
            search_query=search,
            doc_type=type,
            doc_ids=doc_ids,
        )
        return {"page": page, "size": size, "total": total, "items": items}
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LtreeNotAvailableError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.get("/nodes/{id}", response_model=NodeOut)
def get_node(id: int, db: Session = Depends(get_db), include_deleted: bool = False):
    services = get_service_bundle(db)
    node_service = services.node()
    try:
        return node_service.get_node(id, include_deleted=include_deleted)
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/nodes/{id}", response_model=NodeOut)
def update_node(
    request: Request,
    id: int,
    payload: NodeUpdate,
    db: Session = Depends(get_db),
    ctx=Depends(get_request_context),
):
    user_id = ctx["user_id"]
    service = IdempotencyService(db)
    services = get_service_bundle(db)
    node_service = services.node()

    def executor():
        data = NodeUpdateData(
            name=payload.name,
            slug=payload.slug,
            parent_path=payload.parent_path,
            parent_path_set="parent_path" in payload.model_fields_set,
            type=payload.type,
        )
        try:
            return node_service.update_node(id, data, user_id=user_id)
        except NodeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ParentNodeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InvalidNodeOperationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except NodeConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except LtreeNotAvailableError as exc:
            raise HTTPException(status_code=501, detail=str(exc)) from exc
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


@router.delete("/nodes/{id}", status_code=status.HTTP_204_NO_CONTENT)
def soft_delete_node(
    id: int, db: Session = Depends(get_db), ctx=Depends(get_request_context)
):
    services = get_service_bundle(db)
    node_service = services.node()
    try:
        node_service.soft_delete_node(id, user_id=ctx["user_id"])
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return None


@router.delete(
    "/nodes/{id}/purge",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin_key)],
)
def purge_node(
    id: int,
    db: Session = Depends(get_db),
    ctx=Depends(get_request_context),
):
    services = get_service_bundle(db)
    node_service = services.node()
    try:
        node_service.purge_node(id, user_id=ctx["user_id"])
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidNodeOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MissingUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return None


@router.post("/nodes/{id}/restore", response_model=NodeOut)
def restore_node(
    id: int, db: Session = Depends(get_db), ctx=Depends(get_request_context)
):
    services = get_service_bundle(db)
    node_service = services.node()
    try:
        return node_service.restore_node(id, user_id=ctx["user_id"])
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NodeConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except MissingUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/nodes", response_model=NodesPage)
def list_nodes(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    include_deleted: bool = False,
    type: str | None = None,
    db: Session = Depends(get_db),
):
    services = get_service_bundle(db)
    node_service = services.node()
    items, total = node_service.list_nodes(
        page=page, size=size, include_deleted=include_deleted, node_type=type
    )
    return {"page": page, "size": size, "total": total, "items": items}


@router.post("/nodes/reorder", response_model=list[NodeOut])
def reorder_nodes(
    payload: NodeReorderPayload,
    db: Session = Depends(get_db),
    ctx=Depends(get_request_context),
):
    user_id = ctx["user_id"]
    services = get_service_bundle(db)
    node_service = services.node()
    try:
        return node_service.reorder_children(
            NodeReorderData(
                parent_id=payload.parent_id,
                ordered_ids=tuple(payload.ordered_ids),
            ),
            user_id=user_id,
        )
    except ParentNodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidNodeOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MissingUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Restore relationship endpoints under nodes for compatibility
@router.post("/nodes/{id}/bind/{doc_id}")
def bind_document(
    id: int,
    doc_id: int,
    db: Session = Depends(get_db),
    ctx=Depends(get_request_context),
):
    user_id = ctx["user_id"]
    services = get_service_bundle(db)
    rel_service = services.relationship()
    try:
        rel_service.bind(id, doc_id, user_id=user_id)
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DocumentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.delete("/nodes/{id}/unbind/{doc_id}")
def unbind_document(
    id: int,
    doc_id: int,
    db: Session = Depends(get_db),
    ctx=Depends(get_request_context),
):
    services = get_service_bundle(db)
    rel_service = services.relationship()
    try:
        rel_service.unbind(id, doc_id, user_id=ctx["user_id"])
    except RelationshipNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/nodes/{id}/children", response_model=list[NodeOut])
def list_children(
    id: int,
    depth: int = Query(default=1, ge=1),
    type: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    services = get_service_bundle(db)
    node_service = services.node()
    try:
        return node_service.list_children(id, depth=depth, node_type=type)
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LtreeNotAvailableError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc


@router.get(
    "/nodes/{id}/subtree-documents",
    response_model=DocumentsPage,
    description=SUBTREE_DOCUMENTS_DESCRIPTION,
)
def get_subtree_documents(
    request: Request,
    id: int,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    include_deleted_nodes: bool = Query(default=False),
    include_deleted_documents: bool = Query(default=False),
    include_descendants: bool = Query(default=True),
    search: str | None = Query(default=None, alias="query"),
    type: str | None = Query(default=None),
    doc_ids: list[int] | None = Query(default=None, alias="id"),
    db: Session = Depends(get_db),
):
    services = get_service_bundle(db)
    node_service = services.node()
    metadata_filters = extract_metadata_filters(request)
    try:
        items, total = node_service.paginate_subtree_documents(
            id,
            page=page,
            size=size,
            include_deleted_nodes=include_deleted_nodes,
            include_deleted_documents=include_deleted_documents,
            include_descendants=include_descendants,
            metadata_filters=metadata_filters or None,
            search_query=search,
            doc_type=type,
            doc_ids=doc_ids,
        )
        return {"page": page, "size": size, "total": total, "items": items}
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except LtreeNotAvailableError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
