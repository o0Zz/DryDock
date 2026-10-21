from typing import Literal

from pydantic import BaseModel, Field

AiProviderId = Literal["openai", "anthropic", "copilot"]


class AiProviderRead(BaseModel):
    id: AiProviderId
    # A key (or, for Copilot, a GitHub sign-in) is stored. The key itself is never sent.
    configured: bool
    model: str
    # OpenAI only: empty means api.openai.com.
    base_url: str
    # Copilot only: the GitHub login it signed in with.
    account: str


class AiConfigRead(BaseModel):
    active: AiProviderId | None
    providers: list[AiProviderRead]


class AiActiveUpdate(BaseModel):
    provider: AiProviderId | None


class AiProviderUpdate(BaseModel):
    model: str = Field(default="", max_length=200)
    # Empty keeps the stored key. Copilot ignores it: it signs in with GitHub.
    api_key: str = Field(default="", max_length=500)
    base_url: str | None = Field(default=None, max_length=500)


class CopilotDevice(BaseModel):
    user_code: str
    verification_uri: str
    interval: int
    expires_in: int


class CopilotPoll(BaseModel):
    status: Literal["pending", "done", "expired", "denied"]
    account: str | None = None


class AiMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=200_000)


class ComposeAssistRequest(BaseModel):
    # The editor's content, saved or not.
    content: str = Field(max_length=500_000)
    messages: list[AiMessage] = Field(min_length=1, max_length=100)


class ComposeAssistReply(BaseModel):
    reply: str
    # The whole proposed file, or null when the answer changes nothing.
    content: str | None
    # Why the proposed file would not save (invalid YAML, no services).
    error: str | None
