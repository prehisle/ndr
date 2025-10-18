from pydantic import BaseModel
from pydantic.config import ConfigDict


class RelationshipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node_id: int
    document_id: int
    created_by: str
