"""AI Assistant with a local model through Ollama (e.g. Qwen): turned on by OLLAMA_MODEL, no OpenAI key needed.
Ollama's /api/chat is replaced by a scripted stand-in. All data is made up."""
import json

import httpx
import pytest

from app import assistant


class Reply:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, json.dumps(body)

    def json(self):
        return self._body


@pytest.fixture
def ollama(monkeypatch):
    """Each item in `script` is Ollama's next answer (a message dict, or a Reply for an error)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ASSISTANT_PROVIDER", raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:9b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.synthetic:11434/")
    script, sent = [], []

    def post(url, json=None, timeout=None, **kw):
        sent.append((url, json))
        step = script.pop(0)
        return step if isinstance(step, Reply) else Reply(200, {"message": step})

    monkeypatch.setattr(assistant.httpx, "post", post)
    return script, sent


def test_status_and_settings(client, ollama, monkeypatch):
    assert client.get("/api/assistant/status").json() == {"enabled": True, "model": "qwen3.5:9b", "provider": "ollama"}
    # with an OpenAI key too, OpenAI is used unless ASSISTANT_PROVIDER says ollama
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert assistant.settings()["provider"] == "openai"
    monkeypatch.setenv("ASSISTANT_PROVIDER", "ollama")
    assert assistant.settings() == {"provider": "ollama", "key": "", "model": "qwen3.5:9b",
                                    "base_url": "http://ollama.synthetic:11434"}


def test_qwen_creates_a_lead_with_tools(client, ollama):
    script, sent = ollama
    script += [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "create_lead", "arguments": {
            "first_name": "Mohan", "last_name": "Reddy", "company": "Orbit Synthetic", "email": "mohan@orbit.example",
            "source": "Referral"}}}]},
        {"role": "assistant", "content": "<think>The lead was made.</think>Created lead Mohan Reddy (Orbit Synthetic)."},
    ]
    res = client.post("/api/assistant/chat", json={"message": "Create a lead Mohan Reddy at Orbit Synthetic"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["reply"] == "Created lead Mohan Reddy (Orbit Synthetic)."  # the thinking part left out
    assert body["links"][0]["type"] == "Lead" and body["links"][0]["name"] == "Mohan Reddy"
    url, first = sent[0]
    assert url == "http://ollama.synthetic:11434/api/chat" and first["model"] == "qwen3.5:9b"
    assert first["stream"] is False and first["think"] is False and first["options"]["num_ctx"] == 16384
    assert {t["function"]["name"] for t in first["tools"]} >= {"create_lead", "crm_report"}
    # the second call carries the tool call (arguments as an object) and its result, named by the tool
    _, second = sent[1]
    call, result = second["messages"][-2], second["messages"][-1]
    assert call["tool_calls"][0]["function"]["arguments"]["company"] == "Orbit Synthetic"
    assert result["role"] == "tool" and result["tool_name"] == "create_lead" and "Orbit Synthetic" in result["content"]


def test_ollama_errors_are_explained(client, ollama, monkeypatch):
    script, _ = ollama
    script.append(Reply(404, {"error": "model 'qwen3.5:9b' not found"}))
    res = client.post("/api/assistant/chat", json={"message": "How many open leads do I have?"})
    assert res.status_code == 502 and "was not found" in res.json()["detail"]
    script.append(Reply(400, {"error": "registry.ollama.ai/library/gemma:2b does not support tools"}))
    assert "can't use tools" in client.post("/api/assistant/chat", json={"message": "How many open leads do I have?"}).json()["detail"]
    # a model without the thinking switch: asked again without it
    script += [Reply(400, {"error": "\"gemma\" does not support thinking"}), {"role": "assistant", "content": "Hello!"}]
    assert client.post("/api/assistant/chat", json={"message": "How many open leads do I have?"}).json()["reply"] == "Hello!"

    def down(*a, **k):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(assistant.httpx, "post", down)
    assert "Ollama could not be reached" in client.post("/api/assistant/chat", json={"message": "How many open leads do I have?"}).json()["detail"]
