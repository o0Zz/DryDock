from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import require_admin
from app.schemas.ai import (
    AiActiveUpdate,
    AiConfigRead,
    AiProviderId,
    AiProviderUpdate,
    ComposeAssistReply,
    ComposeAssistRequest,
    CopilotDevice,
    CopilotPoll,
)
from app.services import ai_service

router = APIRouter(prefix="/api/ai", tags=["ai"])
_admin = [Depends(require_admin)]


# Readable by everyone: the editor needs to know whether the assistant is set up.
@router.get("", response_model=AiConfigRead)
def read_config() -> dict:
    return ai_service.summary()


@router.put("/active", response_model=AiConfigRead, dependencies=_admin)
def set_active(body: AiActiveUpdate) -> dict:
    ai_service.set_active(body.provider)
    return ai_service.summary()


@router.put("/providers/{provider}", response_model=AiConfigRead, dependencies=_admin)
def set_provider(provider: AiProviderId, body: AiProviderUpdate) -> dict:
    ai_service.set_provider(
        provider, model=body.model, api_key=body.api_key, base_url=body.base_url
    )
    return ai_service.summary()


@router.delete("/providers/{provider}", response_model=AiConfigRead, dependencies=_admin)
def remove_provider(provider: AiProviderId) -> dict:
    if not ai_service.remove_provider(provider):
        raise HTTPException(status_code=404, detail=f"{provider} is not set up")
    return ai_service.summary()


@router.get("/providers/{provider}/models", response_model=list[str], dependencies=_admin)
def list_models(provider: AiProviderId) -> list[str]:
    return ai_service.list_models(provider)


@router.post("/copilot/device", response_model=CopilotDevice, dependencies=_admin)
def copilot_device() -> dict:
    """Start GitHub's device sign-in. The user enters the code on GitHub."""
    return ai_service.copilot_device_start()


@router.post("/copilot/poll", response_model=CopilotPoll, dependencies=_admin)
def copilot_poll() -> dict:
    return ai_service.copilot_device_poll()


# Anyone who can edit a Compose file can ask for help with it. This one waits for
# the model instead of queueing a job: it is a chat, the editor waits for the answer.
@router.post("/compose", response_model=ComposeAssistReply)
def assist_compose(body: ComposeAssistRequest) -> ComposeAssistReply:
    reply = ai_service.edit_compose(
        body.content, [message.model_dump() for message in body.messages]
    )
    return ComposeAssistReply(**asdict(reply))
