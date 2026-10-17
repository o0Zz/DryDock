from pydantic import BaseModel


class ComposeContent(BaseModel):
    content: str


class ComposeWriteResponse(BaseModel):
    backup_path: str


class EnvContent(BaseModel):
    content: str
    # False when the project folder has no .env yet; saving creates it.
    exists: bool = True


class EnvWriteResponse(BaseModel):
    # None when there was no .env to back up.
    backup_path: str | None = None
