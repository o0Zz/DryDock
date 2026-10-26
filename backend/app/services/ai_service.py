"""AI assistant for the Compose editor: one chat call to OpenAI, Anthropic or GitHub Copilot.

The providers are called over plain HTTP with httpx, so no SDK is needed on the Pi.
OpenAI's base URL is editable, which also covers OpenAI-compatible local servers
(Ollama, LM Studio, LiteLLM).

Keys live in `<data>/ai/config.json` (mode 600) and never leave the backend.
Copilot has no API key: an admin signs in with GitHub's device flow, DryDock keeps
the GitHub token and trades it for a short-lived Copilot token before each call,
like the Copilot editor plugins do.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.services import compose_service

logger = logging.getLogger(__name__)

PROVIDERS = ("openai", "anthropic", "copilot")
DEFAULT_MODELS = {"openai": "gpt-5", "anthropic": "claude-opus-5-5", "copilot": "gpt-4.1"}
OPENAI_URL = "https://api.openai.com/v1"
ANTHROPIC_URL = "https://api.anthropic.com/v1"
COPILOT_URL = "https://api.githubcopilot.com"

# Copilot's own OAuth app, the one the editor plugins sign in with. Copilot only
# hands its token to apps it knows.
COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"
COPILOT_HEADERS = {
    "Editor-Version": "vscode/1.99.0",
    "Editor-Plugin-Version": "copilot-chat/0.26.0",
    "User-Agent": "GitHubCopilotChat/0.26.0",
}

# A thinking model can take a minute on a long file.
TIMEOUT = httpx.Timeout(180.0, connect=10.0)
# Older turns beyond this are dropped: the current file is always sent in full.
MAX_MESSAGES = 20


class AiError(Exception):
    """The provider failed or answered with an error."""


class AiNotConfigured(AiError):
    """No provider is chosen, or the chosen one has no key."""


# --- config --------------------------------------------------------------------------


def _path() -> Path:
    return settings.data_path / "ai" / "config.json"


_lock = threading.Lock()


def _load() -> dict[str, Any]:
    try:
        config = json.loads(_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"active": None, "providers": {}}
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Cannot read %s: %s", _path(), exc)
        return {"active": None, "providers": {}}
    config.setdefault("active", None)
    config.setdefault("providers", {})
    return config


def _save(config: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    # Owner-only: the file holds API keys.
    temp.chmod(0o600)
    temp.replace(path)


def _secret(provider: str, values: dict[str, Any]) -> str:
    return values.get("github_token" if provider == "copilot" else "api_key") or ""


def _base_url(provider: str, values: dict[str, Any]) -> str:
    if provider == "openai":
        return (values.get("base_url") or OPENAI_URL).rstrip("/")
    return ANTHROPIC_URL if provider == "anthropic" else COPILOT_URL


def summary() -> dict[str, Any]:
    """The config without any secret."""
    config = _load()
    providers = []
    for provider in PROVIDERS:
        values = config["providers"].get(provider, {})
        providers.append(
            {
                "id": provider,
                "configured": bool(_secret(provider, values)),
                "model": values.get("model") or DEFAULT_MODELS[provider],
                "base_url": values.get("base_url") or "",
                "account": values.get("account") or "",
            }
        )
    active = config["active"] if config["active"] in PROVIDERS else None
    return {"active": active, "providers": providers}


def set_provider(
    provider: str, *, model: str, api_key: str | None = None, base_url: str | None = None
) -> None:
    """Store a provider's model, and its key when given (empty keeps the stored one)."""
    with _lock:
        config = _load()
        values = config["providers"].setdefault(provider, {})
        values["model"] = model.strip() or DEFAULT_MODELS[provider]
        if api_key and provider != "copilot":
            values["api_key"] = api_key.strip()
        if provider == "openai" and base_url is not None:
            values["base_url"] = base_url.strip().rstrip("/")
        # The first provider set up becomes the active one: nothing to pick yet.
        if config["active"] is None and _secret(provider, values):
            config["active"] = provider
        _save(config)


def remove_provider(provider: str) -> bool:
    with _lock:
        config = _load()
        if config["providers"].pop(provider, None) is None:
            return False
        if config["active"] == provider:
            config["active"] = None
        _save(config)
    if provider == "copilot":
        _copilot_token.clear()
    return True


def set_active(provider: str | None) -> None:
    with _lock:
        config = _load()
        if provider is not None and not _secret(provider, config["providers"].get(provider, {})):
            raise AiNotConfigured(f"{provider} has no key yet")
        config["active"] = provider
        _save(config)


# --- HTTP ----------------------------------------------------------------------------


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300] or response.reason_phrase
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    if isinstance(error, str):
        return body.get("error_description") or error
    return response.text[:300]


def _request(method: str, url: str, label: str, **kwargs: Any) -> Any:
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.request(method, url, **kwargs)
    except httpx.TimeoutException as exc:
        raise AiError(f"{label} did not answer in time") from exc
    except httpx.HTTPError as exc:
        raise AiError(f"Cannot reach {label}: {exc}") from exc
    if response.status_code >= 400:
        raise AiError(f"{label} answered {response.status_code}: {_error_text(response)}")
    try:
        return response.json()
    except ValueError as exc:
        raise AiError(f"{label} sent a response that is not JSON") from exc


# --- Copilot sign-in -----------------------------------------------------------------

# One sign-in at a time: an admin starts it and the page polls until GitHub answers.
_device: dict[str, Any] = {}
# GitHub token -> (Copilot token, expiry as epoch seconds, API base URL).
_copilot_token: dict[str, tuple[str, float, str]] = {}


def copilot_device_start() -> dict[str, Any]:
    body = _request(
        "POST",
        "https://github.com/login/device/code",
        "GitHub",
        data={"client_id": COPILOT_CLIENT_ID, "scope": "read:user"},
        headers={"Accept": "application/json"},
    )
    _device.clear()
    _device.update(
        device_code=body["device_code"], expires=time.monotonic() + int(body["expires_in"])
    )
    return {
        "user_code": body["user_code"],
        "verification_uri": body["verification_uri"],
        "interval": int(body.get("interval", 5)),
        "expires_in": int(body["expires_in"]),
    }


def copilot_device_poll() -> dict[str, str]:
    """`pending` until the user enters the code on GitHub, then `done` (or a failure)."""
    if not _device or time.monotonic() > _device["expires"]:
        _device.clear()
        return {"status": "expired"}
    body = _request(
        "POST",
        "https://github.com/login/oauth/access_token",
        "GitHub",
        data={
            "client_id": COPILOT_CLIENT_ID,
            "device_code": _device["device_code"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
        headers={"Accept": "application/json"},
    )
    error = body.get("error")
    if error in ("authorization_pending", "slow_down"):
        return {"status": "pending"}
    _device.clear()
    if error:
        return {"status": "denied" if error == "access_denied" else "expired"}

    github_token = body["access_token"]
    # Fails here, not at the first chat, when the account has no Copilot.
    _copilot_session(github_token)
    user = _request(
        "GET",
        "https://api.github.com/user",
        "GitHub",
        headers={"Authorization": f"token {github_token}", "Accept": "application/json"},
    )
    with _lock:
        config = _load()
        values = config["providers"].setdefault("copilot", {})
        values.update(github_token=github_token, account=user.get("login", ""))
        values.setdefault("model", DEFAULT_MODELS["copilot"])
        if config["active"] is None:
            config["active"] = "copilot"
        _save(config)
    return {"status": "done", "account": values["account"]}


def _copilot_session(github_token: str) -> tuple[str, str]:
    """A Copilot API token and base URL, cached until a minute before it expires."""
    cached = _copilot_token.get(github_token)
    if cached and cached[1] - 60 > time.time():
        return cached[0], cached[2]
    try:
        body = _request(
            "GET",
            "https://api.github.com/copilot_internal/v2/token",
            "GitHub Copilot",
            headers={"Authorization": f"token {github_token}", **COPILOT_HEADERS},
        )
    except AiError as exc:
        if " 401:" in str(exc) or " 403:" in str(exc) or " 404:" in str(exc):
            raise AiError(
                "This GitHub account has no Copilot access, or the sign-in was revoked"
            ) from exc
        raise
    api = (body.get("endpoints") or {}).get("api") or COPILOT_URL
    _copilot_token[github_token] = (body["token"], float(body["expires_at"]), api.rstrip("/"))
    return body["token"], api.rstrip("/")


# --- calls ---------------------------------------------------------------------------


def _provider_values(provider: str | None = None) -> tuple[str, dict[str, Any]]:
    config = _load()
    provider = provider or config["active"]
    if provider not in PROVIDERS:
        raise AiNotConfigured("No AI provider is set up. An admin picks one in Settings.")
    values = config["providers"].get(provider, {})
    if not _secret(provider, values):
        raise AiNotConfigured(f"{provider} has no key yet. An admin adds it in Settings.")
    return provider, values


def _openai_style(
    url: str, label: str, headers: dict[str, str], model: str, system: str, messages: list
) -> str:
    body = _request(
        "POST",
        f"{url}/chat/completions",
        label,
        headers=headers,
        json={"model": model, "messages": [{"role": "system", "content": system}, *messages]},
    )
    try:
        return body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise AiError(f"{label} sent an unexpected response") from exc


def complete(system: str, messages: list[dict[str, str]]) -> str:
    """One reply from the active provider. `messages` alternate user and assistant."""
    provider, values = _provider_values()
    model = values.get("model") or DEFAULT_MODELS[provider]
    secret = _secret(provider, values)

    if provider == "openai":
        return _openai_style(
            _base_url(provider, values),
            "OpenAI",
            {"Authorization": f"Bearer {secret}"},
            model,
            system,
            messages,
        )
    if provider == "copilot":
        token, api = _copilot_session(secret)
        headers = {
            "Authorization": f"Bearer {token}",
            "Copilot-Integration-Id": "vscode-chat",
            **COPILOT_HEADERS,
        }
        return _openai_style(api, "GitHub Copilot", headers, model, system, messages)

    body = _request(
        "POST",
        f"{ANTHROPIC_URL}/messages",
        "Anthropic",
        headers={"x-api-key": secret, "anthropic-version": "2023-06-01"},
        json={"model": model, "max_tokens": 16000, "system": system, "messages": messages},
    )
    if body.get("stop_reason") == "refusal":
        raise AiError("Anthropic declined this request")
    # Thinking blocks come first; only the text blocks are the answer.
    return "".join(
        block.get("text", "") for block in body.get("content", []) if block.get("type") == "text"
    )


def list_models(provider: str) -> list[str]:
    """Model IDs the provider offers to this key, for the settings form."""
    provider, values = _provider_values(provider)
    secret = _secret(provider, values)
    if provider == "openai":
        body = _request(
            "GET",
            f"{_base_url(provider, values)}/models",
            "OpenAI",
            headers={"Authorization": f"Bearer {secret}"},
        )
        return sorted(model["id"] for model in body.get("data", []))
    if provider == "anthropic":
        body = _request(
            "GET",
            f"{ANTHROPIC_URL}/models",
            "Anthropic",
            headers={"x-api-key": secret, "anthropic-version": "2023-06-01"},
            params={"limit": 100},
        )
        return [model["id"] for model in body.get("data", [])]
    token, api = _copilot_session(secret)
    body = _request(
        "GET",
        f"{api}/models",
        "GitHub Copilot",
        headers={"Authorization": f"Bearer {token}", **COPILOT_HEADERS},
    )
    return sorted(
        model["id"]
        for model in body.get("data", [])
        if (model.get("capabilities") or {}).get("type", "chat") == "chat"
    )


# --- Compose editing -----------------------------------------------------------------

COMPOSE_SYSTEM = """\
You help edit one Docker Compose file in DryDock, a web UI for Compose stacks on a \
homelab or a Raspberry Pi. The user asks for a change or asks a question about the file.

Reply in the user's language with a short explanation: what you changed and anything \
they must do by hand (create a folder, set a variable in .env, open a port).

When you change the file, end your reply with the complete new file in one fenced \
```yaml block. Always the whole file, never a part of it or a diff. Keep the comments, \
order and formatting of the parts you do not change. Use only one yaml block.

When the user only asks a question, answer it without a yaml block.

Never invent secrets: use ${VARIABLE} references for passwords and keys. Prefer pinned \
image tags over latest when you add a service.

DryDock reads these service labels. Use them, never a proxy's own labels:
- expose.host: the host name(s) the reverse proxy routes to the service, \
comma-separated (app.example.org). It gets HTTPS.
- expose.port: the container port the proxy forwards to.
- expose.private: true by default (allowed IPs only); false makes it reachable \
from the internet. Only set false when the user asks for public access.
- drydock.update: auto lets DryDock pull and recreate the service once a day \
(when Auto-update is on in Settings) if its tag was rebuilt or its git ref moved. \
It never moves to a newer tag, so it suits a floating tag (latest, stable, a major \
like v3). Do not add it to databases or apps with data migrations (Home Assistant, \
Nextcloud) unless the user asks.
An exposed service must also join the proxy's Docker network (named proxy unless the \
file already uses another one, declared at the top level with external: true) and \
stay on default. The Services panel beside the editor does this for the user. Do \
not write traefik.*, caddy or swag labels: DryDock's proxy sync writes the proxy's \
config from the expose.* labels. Labels that start with drydock. other than \
drydock.update are set by DryDock itself; never add them."""

_FENCE = re.compile(r"```[ \t]*(?:ya?ml)?[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)


@dataclass
class ComposeReply:
    reply: str
    content: str | None
    error: str | None


def _strip_file(text: str) -> str:
    """An earlier proposal, without its file: the current file is sent anyway."""
    return _FENCE.sub("(full file proposed)", text)


def edit_compose(content: str, messages: list[dict[str, str]]) -> ComposeReply:
    """Ask for a change to `content`. The last message is the user's request."""
    history = []
    for message in messages[-MAX_MESSAGES:]:
        body = message["content"]
        if message["role"] == "assistant":
            body = _strip_file(body)
        history.append({"role": message["role"], "content": body})
    # The first message sent must be the user's.
    while history and history[0]["role"] != "user":
        history.pop(0)
    if not history or history[-1]["role"] != "user":
        raise AiError("The last message must be the user's request")
    history[-1] = {
        "role": "user",
        "content": f"Current file:\n```yaml\n{content}\n```\n\n{history[-1]['content']}",
    }

    text = complete(COMPOSE_SYSTEM, history)
    blocks = _FENCE.findall(text)
    if not blocks:
        return ComposeReply(reply=text.strip(), content=None, error=None)
    proposed = blocks[-1].rstrip() + "\n"
    reply = _FENCE.sub("", text).strip()
    try:
        compose_service.validate_yaml(proposed)
    except compose_service.ComposeError as exc:
        return ComposeReply(reply=reply, content=proposed, error=str(exc))
    return ComposeReply(reply=reply, content=proposed, error=None)
