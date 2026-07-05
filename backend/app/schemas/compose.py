from pydantic import BaseModel


class ComposeContent(BaseModel):
    content: str


class ComposeWriteResponse(BaseModel):
    backup_path: str


class ActionResult(BaseModel):
    action: str
    exit_code: int
    stdout: str
    stderr: str
