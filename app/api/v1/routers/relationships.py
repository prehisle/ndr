from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.v1.deps import get_db, get_request_context
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
)
def bind_relationship(
    request: Request,
    node_id: int,
    document_id: int,
    relation_type: str = Query(
        "output", description="关系类型: output(产出文档) 或 source(源文档)"
    ),
    db: Session = Depends(get_db),
    ctx=Depends(get_request_context),
):
    service = IdempotencyService(db)
    user_id = ctx["user_id"]
    services = get_service_bundle(db)
    rel_service = services.relationship()

    def executor():
        try:
            return rel_service.bind(
                node_id, document_id, relation_type=relation_type, user_id=user_id
            )
        except NodeNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except MissingUserError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = service.handle(
        request=request,
        payload={
            "node_id": node_id,
            "document_id": document_id,
            "relation_type": relation_type,
            "user_id": user_id,
        },
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
    services = get_service_bundle(db)
    rel_service = services.relationship()
    try:
        rel_service.unbind(node_id, document_id, user_id=ctx["user_id"])
    except RelationshipNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except MissingUserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return None


@router.get("/relationships", response_model=list[RelationshipOut])
def list_relationships(
    node_id: Optional[int] = None,
    document_id: Optional[int] = None,
    relation_type: Optional[str] = Query(
        None, description="按关系类型过滤: output 或 source"
    ),
    db: Session = Depends(get_db),
):
    services = get_service_bundle(db)
    rel_service = services.relationship()
    return rel_service.list(
        node_id=node_id, document_id=document_id, relation_type=relation_type
    )
