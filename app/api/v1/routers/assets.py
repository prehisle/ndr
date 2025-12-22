"""Asset API router.

This module provides REST API endpoints for managing file assets,
including multipart upload, download URL generation, and node binding.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, get_request_context
from app.api.v1.schemas.assets import (
    AssetBatchBind,
    AssetBindingOut,
    AssetBindingStatus,
    AssetDownloadUrlOut,
    AssetMultipartComplete,
    AssetMultipartInit,
    AssetMultipartInitOut,
    AssetOut,
    AssetPartUrl,
    AssetPartUrlsOut,
    AssetPartUrlsRequest,
    AssetsPage,
)
from app.app.services.asset_service import (
    AssetMultipartInitData,
    AssetNotFoundError,
    AssetService,
    InvalidAssetOperationError,
)
from app.app.services.base import MissingUserError
from app.app.services.bundle import get_service_bundle
from app.app.services.node_asset_service import (
    NodeAssetRelationshipNotFoundError,
    NodeAssetService,
)
from app.app.services.node_service import NodeNotFoundError
from app.common.config import get_settings
from app.common.idempotency import IdempotencyService
from app.infra.storage.client import CompletedPart

router = APIRouter()


def _format_node_path(raw_path: str) -> str:
    """Format ltree path as a slash-separated path."""
    if not raw_path:
        return "/"
    normalized = raw_path.replace(".", "/")
    return normalized if normalized.startswith("/") else f"/{normalized}"


@router.post(
    "/assets/multipart/init",
    response_model=AssetMultipartInitOut,
    status_code=status.HTTP_201_CREATED,
    summary="Initialize multipart upload",
    description="Create an asset and initialize a multipart upload session.",
)
def init_multipart_upload(
    request: Request,
    payload: AssetMultipartInit,
    db: Session = Depends(get_db),
    ctx: dict = Depends(get_request_context),
) -> AssetMultipartInitOut:
    user_id = ctx["user_id"]
    idempotency = IdempotencyService(db)
    services = get_service_bundle(db)
    asset_service: AssetService = services.asset()

    def executor():
        data = AssetMultipartInitData(
            filename=payload.filename,
            content_type=payload.content_type,
            size_bytes=payload.size_bytes,
        )
        try:
            return asset_service.create_multipart_upload(data, user_id=user_id)
        except MissingUserError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except InvalidAssetOperationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = idempotency.handle(
        request=request,
        payload={"body": payload.model_dump(), "user_id": user_id},
        status_code=status.HTTP_201_CREATED,
        executor=executor,
    )
    assert result is not None
    init = result.response
    return AssetMultipartInitOut(
        asset=init.asset,
        upload_id=init.upload_id,
        part_size_bytes=init.part_size_bytes,
        expires_in=init.expires_in,
    )


@router.post(
    "/assets/{asset_id}/multipart/part-urls",
    response_model=AssetPartUrlsOut,
    summary="Get presigned part URLs",
    description="Generate presigned URLs for uploading parts.",
)
def presign_upload_part_urls(
    asset_id: int,
    payload: AssetPartUrlsRequest,
    db: Session = Depends(get_db),
) -> AssetPartUrlsOut:
    services = get_service_bundle(db)
    asset_service: AssetService = services.asset()
    settings = get_settings()

    try:
        upload_id, urls = asset_service.presign_upload_parts(
            asset_id, payload.part_numbers
        )
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidAssetOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AssetPartUrlsOut(
        upload_id=upload_id,
        urls=[AssetPartUrl(part_number=u.part_number, url=u.url) for u in urls],
        expires_in=settings.STORAGE_PRESIGN_EXPIRES_SECONDS,
    )


@router.post(
    "/assets/{asset_id}/multipart/complete",
    response_model=AssetOut,
    summary="Complete multipart upload",
    description="Complete a multipart upload by combining all parts.",
)
def complete_multipart_upload(
    request: Request,
    asset_id: int,
    payload: AssetMultipartComplete,
    db: Session = Depends(get_db),
    ctx: dict = Depends(get_request_context),
) -> AssetOut:
    user_id = ctx["user_id"]
    idempotency = IdempotencyService(db)
    services = get_service_bundle(db)
    asset_service: AssetService = services.asset()

    def executor():
        try:
            parts = [
                CompletedPart(part_number=p.part_number, etag=p.etag)
                for p in payload.parts
            ]
            return asset_service.complete_multipart_upload(
                asset_id, parts=parts, user_id=user_id
            )
        except AssetNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except InvalidAssetOperationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MissingUserError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = idempotency.handle(
        request=request,
        payload={
            "body": payload.model_dump(),
            "resource_id": asset_id,
            "user_id": user_id,
        },
        status_code=status.HTTP_200_OK,
        executor=executor,
    )
    assert result is not None
    return result.response


@router.get(
    "/assets/{asset_id}",
    response_model=AssetOut,
    summary="Get asset",
    description="Get asset metadata by ID.",
)
def get_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    include_deleted: bool = False,
) -> AssetOut:
    services = get_service_bundle(db)
    asset_service: AssetService = services.asset()

    try:
        asset = asset_service.get_asset(asset_id, include_deleted=include_deleted)
        return AssetOut.model_validate(asset)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/assets/{asset_id}/download-url",
    response_model=AssetDownloadUrlOut,
    summary="Get download URL",
    description="Generate a presigned URL for downloading the asset.",
)
def get_asset_download_url(
    asset_id: int,
    db: Session = Depends(get_db),
) -> AssetDownloadUrlOut:
    services = get_service_bundle(db)
    asset_service: AssetService = services.asset()

    try:
        result = asset_service.presign_download_url(asset_id)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidAssetOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return AssetDownloadUrlOut(url=result.url, expires_in=result.expires_in)


@router.get(
    "/assets",
    response_model=AssetsPage,
    summary="List assets",
    description="List assets with pagination and optional filters.",
)
def list_assets(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    include_deleted: bool = False,
    status: str | None = Query(default=None),
    query: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> AssetsPage:
    services = get_service_bundle(db)
    asset_service: AssetService = services.asset()

    items, total = asset_service.list_assets(
        page=page,
        size=size,
        include_deleted=include_deleted,
        search_query=query,
        status=status,
    )
    items_out = [AssetOut.model_validate(item) for item in items]
    return AssetsPage(page=page, size=size, total=total, items=items_out)


@router.delete(
    "/assets/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete asset",
    description="Soft-delete an asset.",
)
def soft_delete_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    ctx: dict = Depends(get_request_context),
):
    services = get_service_bundle(db)
    asset_service: AssetService = services.asset()

    try:
        asset_service.soft_delete_asset(asset_id, user_id=ctx["user_id"])
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/assets/{asset_id}/bindings",
    response_model=List[AssetBindingOut],
    summary="List asset bindings",
    description="List all nodes an asset is bound to.",
)
def list_asset_bindings(
    asset_id: int,
    db: Session = Depends(get_db),
) -> List[AssetBindingOut]:
    services = get_service_bundle(db)
    node_asset_service: NodeAssetService = services.node_asset()

    try:
        bindings = node_asset_service.list_bindings_for_asset(asset_id)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return [
        AssetBindingOut(
            node_id=b.node_id,
            node_name=b.node_name,
            node_path=_format_node_path(b.node_path),
            created_at=b.created_at,
        )
        for b in bindings
    ]


@router.post(
    "/assets/{asset_id}/batch-bind",
    response_model=List[AssetBindingOut],
    summary="Batch bind asset",
    description="Bind an asset to multiple nodes at once.",
)
def batch_bind_asset(
    asset_id: int,
    payload: AssetBatchBind,
    db: Session = Depends(get_db),
    ctx: dict = Depends(get_request_context),
) -> List[AssetBindingOut]:
    user_id = ctx["user_id"]
    services = get_service_bundle(db)
    node_asset_service: NodeAssetService = services.node_asset()

    try:
        bindings = node_asset_service.batch_bind(
            asset_id, payload.node_ids, user_id=user_id
        )
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return [
        AssetBindingOut(
            node_id=b.node_id,
            node_name=b.node_name,
            node_path=_format_node_path(b.node_path),
            created_at=b.created_at,
        )
        for b in bindings
    ]


@router.get(
    "/assets/{asset_id}/binding-status",
    response_model=AssetBindingStatus,
    summary="Get binding status",
    description="Get a summary of an asset's bindings.",
)
def asset_binding_status(
    asset_id: int,
    db: Session = Depends(get_db),
) -> AssetBindingStatus:
    services = get_service_bundle(db)
    node_asset_service: NodeAssetService = services.node_asset()

    try:
        summary = node_asset_service.binding_status(asset_id)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return AssetBindingStatus(
        total_bindings=summary.total_bindings,
        node_ids=summary.node_ids,
    )


@router.post(
    "/nodes/{node_id}/assets/{asset_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Bind asset to node",
    description="Bind an asset to a specific node.",
)
def bind_asset_to_node(
    node_id: int,
    asset_id: int,
    db: Session = Depends(get_db),
    ctx: dict = Depends(get_request_context),
) -> dict:
    user_id = ctx["user_id"]
    services = get_service_bundle(db)
    node_asset_service: NodeAssetService = services.node_asset()

    try:
        node_asset_service.bind(node_id, asset_id, user_id=user_id)
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True}


@router.post(
    "/assets/{asset_id}/multipart/abort",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Abort multipart upload",
    description="Abort an in-progress multipart upload.",
)
def abort_multipart_upload(
    asset_id: int,
    db: Session = Depends(get_db),
    ctx: dict = Depends(get_request_context),
):
    user_id = ctx["user_id"]
    services = get_service_bundle(db)
    asset_service: AssetService = services.asset()

    try:
        asset_service.abort_multipart_upload(asset_id, user_id=user_id)
    except AssetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidAssetOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MissingUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/nodes/{node_id}/assets",
    response_model=List[AssetOut],
    summary="List node assets",
    description="List all assets bound to a specific node.",
)
def list_node_assets(
    node_id: int,
    db: Session = Depends(get_db),
) -> List[AssetOut]:
    services = get_service_bundle(db)
    node_asset_service: NodeAssetService = services.node_asset()

    try:
        assets = node_asset_service.list_assets_for_node(node_id)
    except NodeNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return [AssetOut.model_validate(asset) for asset in assets]


@router.delete(
    "/nodes/{node_id}/assets/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unbind asset from node",
    description="Unbind an asset from a specific node.",
)
def unbind_asset_from_node(
    node_id: int,
    asset_id: int,
    db: Session = Depends(get_db),
    ctx: dict = Depends(get_request_context),
):
    user_id = ctx["user_id"]
    services = get_service_bundle(db)
    node_asset_service: NodeAssetService = services.node_asset()

    try:
        node_asset_service.unbind(node_id, asset_id, user_id=user_id)
    except NodeAssetRelationshipNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
