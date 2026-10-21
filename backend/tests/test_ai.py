"""AI assistant: provider config, the three providers' HTTP calls, and the Compose edit."""

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import ai_service

FILE = "services:\n  web:\n    image: nginx:1.27\n"
NEW_FILE = "services:\n  web:\n    image: nginx:1.27\n    restart: unless-stopped\n"


@pytest.fixture(autouse=True)
def data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(settings, "data_path", tmp_path / "data")
    ai_service._copilot_token.clear()
    ai_service._device.clear()
    return tmp_path / "data"


def mock_http(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    real_client = httpx.Client
    monkeypatch.setattr(
        ai_service.httpx,
        "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(record), **kwargs),
    )
    return seen


def test_config_never_returns_keys(client: TestClient, data: Path) -> None:
    response = client.put(
        "/api/ai/providers/anthropic", json={"model": "", "api_key": "sk-ant-secret"}
    )
    assert response.status_code == 200
    body = response.json()
    # The first provider set up becomes the active one, with the default model.
    assert body["active"] == "anthropic"
    anthropic = next(p for p in body["providers"] if p["id"] == "anthropic")
    assert anthropic == {
        "id": "anthropic",
        "configured": True,
        "model": ai_service.DEFAULT_MODELS["anthropic"],
        "base_url": "",
        "account": "",
    }
    assert "sk-ant-secret" not in response.text
    assert "sk-ant-secret" not in client.get("/api/ai").text

    # An empty key keeps the stored one.
    client.put("/api/ai/providers/anthropic", json={"model": "claude-haiku-5-5"})
    stored = json.loads((data / "ai" / "config.json").read_text(encoding="utf-8"))
    assert stored["providers"]["anthropic"] == {
        "model": "claude-haiku-5-5",
        "api_key": "sk-ant-secret",
    }


def test_active_needs_a_key(client: TestClient) -> None:
    response = client.put("/api/ai/active", json={"provider": "openai"})
    assert response.status_code == 400

    client.put("/api/ai/providers/openai", json={"api_key": "sk-1"})
    client.put("/api/ai/providers/anthropic", json={"api_key": "sk-2"})
    assert client.put("/api/ai/active", json={"provider": "anthropic"}).json()["active"] == (
        "anthropic"
    )
    # Removing the active provider leaves none active.
    assert client.delete("/api/ai/providers/anthropic").json()["active"] is None
    assert client.delete("/api/ai/providers/anthropic").status_code == 404


def test_chat_without_provider(client: TestClient) -> None:
    response = client.post(
        "/api/ai/compose", json={"content": FILE, "messages": [{"role": "user", "content": "x"}]}
    )
    assert response.status_code == 400
    assert "No AI provider" in response.json()["detail"]


def test_anthropic_edit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    ai_service.set_provider("anthropic", model="claude-opus-5-5", api_key="sk-ant")
    reply = f"Added a restart policy.\n\n```yaml\n{NEW_FILE}```\n"
    seen = mock_http(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            json={
                "stop_reason": "end_turn",
                "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": reply}],
            },
        ),
    )
    response = client.post(
        "/api/ai/compose",
        json={
            "content": FILE,
            "messages": [
                {"role": "user", "content": "add a port"},
                {"role": "assistant", "content": f"Done.\n```yaml\n{FILE}```"},
                {"role": "user", "content": "restart it always"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "reply": "Added a restart policy.",
        "content": NEW_FILE,
        "error": None,
    }
    request = seen[0]
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "sk-ant"
    assert request.headers["anthropic-version"] == "2023-06-01"
    sent = json.loads(request.content)
    assert sent["model"] == "claude-opus-5-5"
    assert sent["system"] == ai_service.COMPOSE_SYSTEM
    # The older proposal is dropped; the current file rides on the last request.
    assert sent["messages"][1]["content"] == "Done.\n(full file proposed)"
    assert sent["messages"][2]["content"].startswith(f"Current file:\n```yaml\n{FILE}")
    assert sent["messages"][2]["content"].endswith("restart it always")


def test_openai_question_and_invalid_file(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_service.set_provider("openai", model="gpt-5", api_key="sk-oa", base_url="http://llm:11434/v1/")
    answers = iter(["It runs nginx.", "Here:\n```yaml\nimage: nginx\n```"])
    seen = mock_http(
        monkeypatch,
        lambda request: httpx.Response(
            200, json={"choices": [{"message": {"content": next(answers)}}]}
        ),
    )
    ask = {"content": FILE, "messages": [{"role": "user", "content": "what is this?"}]}

    assert client.post("/api/ai/compose", json=ask).json() == {
        "reply": "It runs nginx.",
        "content": None,
        "error": None,
    }
    proposal = client.post("/api/ai/compose", json=ask).json()
    assert proposal["content"] == "image: nginx\n"
    assert "services" in proposal["error"]

    # An OpenAI-compatible server at its own base URL.
    assert str(seen[0].url) == "http://llm:11434/v1/chat/completions"
    assert seen[0].headers["authorization"] == "Bearer sk-oa"
    assert json.loads(seen[0].content)["messages"][0]["role"] == "system"


def test_provider_error_is_a_502(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    ai_service.set_provider("openai", model="gpt-5", api_key="bad")
    mock_http(
        monkeypatch,
        lambda request: httpx.Response(401, json={"error": {"message": "Incorrect API key"}}),
    )
    response = client.post(
        "/api/ai/compose", json={"content": FILE, "messages": [{"role": "user", "content": "x"}]}
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "OpenAI answered 401: Incorrect API key"


def test_copilot_sign_in_and_chat(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    pending = iter([True, False])

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/login/device/code":
            return httpx.Response(
                200,
                json={
                    "device_code": "dev",
                    "user_code": "ABCD-1234",
                    "verification_uri": "https://github.com/login/device",
                    "expires_in": 900,
                    "interval": 5,
                },
            )
        if path == "/login/oauth/access_token":
            if next(pending):
                return httpx.Response(200, json={"error": "authorization_pending"})
            return httpx.Response(200, json={"access_token": "gho_token"})
        if path == "/copilot_internal/v2/token":
            assert request.headers["authorization"] == "token gho_token"
            return httpx.Response(
                200,
                json={
                    "token": "cop_token",
                    "expires_at": 4_000_000_000,
                    "endpoints": {"api": "https://api.individual.githubcopilot.com"},
                },
            )
        if path == "/user":
            return httpx.Response(200, json={"login": "octocat"})
        assert str(request.url) == "https://api.individual.githubcopilot.com/chat/completions"
        assert request.headers["authorization"] == "Bearer cop_token"
        assert request.headers["copilot-integration-id"] == "vscode-chat"
        return httpx.Response(200, json={"choices": [{"message": {"content": "Fine as is."}}]})

    seen = mock_http(monkeypatch, handler)

    device = client.post("/api/ai/copilot/device").json()
    assert device["user_code"] == "ABCD-1234"
    assert client.post("/api/ai/copilot/poll").json() == {"status": "pending", "account": None}
    assert client.post("/api/ai/copilot/poll").json() == {"status": "done", "account": "octocat"}
    config = client.get("/api/ai").json()
    assert config["active"] == "copilot"
    assert next(p for p in config["providers"] if p["id"] == "copilot")["account"] == "octocat"
    assert "gho_token" not in json.dumps(config)

    reply = client.post(
        "/api/ai/compose", json={"content": FILE, "messages": [{"role": "user", "content": "ok?"}]}
    )
    assert reply.json()["reply"] == "Fine as is."
    # The Copilot token is cached: one exchange for the sign-in and the chat.
    assert [r.url.path for r in seen].count("/copilot_internal/v2/token") == 1


def test_admin_only_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app.core.security import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=2, is_admin=False)
    try:
        user = TestClient(app)
        assert user.get("/api/ai").status_code == 200
        assert user.put("/api/ai/providers/openai", json={"api_key": "x"}).status_code == 403
        assert user.post("/api/ai/copilot/device").status_code == 403
    finally:
        app.dependency_overrides.clear()
