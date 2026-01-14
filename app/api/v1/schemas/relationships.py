from pydantic import BaseModel
from pydantic.config import ConfigDict


class RelationshipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    node_id: int
    document_id: int
    relation_type: str = "output"
    created_by: str
