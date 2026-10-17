from pydantic import BaseModel


class ComposeContent(BaseModel):
    content: str


class ComposeWriteResponse(BaseModel):
    backup_path: str
