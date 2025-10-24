from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, get_request_context, require_permission
from app.common.permissions import Permissions
from app.api.v1.schemas.relationships import RelationshipOut
from app.app.services import (
    DocumentNotFoundError,
    MissingUserError,
    NodeNotFoundError,
    RelationshipNotFoundError,
    get_service_bundle,
)
from app.common.idempotency import IdempotencyService

router = APIRouter()


@router.post(
    "/relationships",
    response_model=RelationshipOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission(Permissions.RELATIONSHIPS_WRITE))],
)
def bind_relationship(
    request: Request,
    node_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    ctx=Depends(get_request_context),
):
    service = IdempotencyService(db)
    user_id = ctx["user_id"]
    services = get_service_bundle(db)
    rel_service = services.relationship()

    def executor():
        try:
            return rel_service.bind(node_id, document_id, user_id=user_id)
        except NodeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MissingUserError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = service.handle(
        request=request,
        payload={"node_id": node_id, "document_id": document_id, "user_id": user_id},
        status_code=status.HTTP_201_CREATED,
        executor=executor,
    )
    assert result is not None
    return result.response


@router.delete(
    "/relationships",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission(Permissions.RELATIONSHIPS_WRITE))],
)
def unbind_relationship(
    node_id: int = Query(...),
    document_id: int = Query(...),
    db: Session = Depends(get_db),
    ctx=Depends(get_request_context),
):
    services = get_service_bundle(db)
    rel_service = services.relationship()
    try:
        rel_service.unbind(node_id, document_id, user_id=ctx["user_id"])
    except RelationshipNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return None


@router.get(
    "/relationships",
    response_model=list[RelationshipOut],
    dependencies=[Depends(require_permission(Permissions.RELATIONSHIPS_READ))],
)
def list_relationships(
    node_id: Optional[int] = None,
    document_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    services = get_service_bundle(db)
    rel_service = services.relationship()
    return rel_service.list(node_id=node_id, document_id=document_id)
