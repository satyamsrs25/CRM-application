"""EMAIL_DRAFT_MODE=openai_compatible: drafting through an OpenAI-compatible server (LiteLLM, vLLM, ...) with a mocked
server. Never sends email and never reaches a real model."""
import json

import httpx
import pytest

from app import ai_email, mailer


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.delenv("OPENAI_ENV_FILE", raising=False)
    monkeypatch.setattr(ai_email, "_json_mode_that_worked", {})  # one test's fallback must not leak into the next
    for name in ("COMPAT_BASE_URL", "COMPAT_EMAIL_MODEL", "COMPAT_JSON_MODE", "COMPAT_EXTRA_BODY", "COMPAT_TIMEOUT_SECONDS",
                 "OPENAI_BASE_URL", "OPENAI_MODEL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def record(client, monkeypatch):
    monkeypatch.setattr(mailer, "send", lambda *a, **kw: None)
    response = client.post("/api/leads", json={"first_name": "Jack", "last_name": "Jones", "company": "Bluebird",
                                               "email": "jack@bluebird.example", "welcome_email": False})
    assert response.status_code == 201, response.text
    return response.json()


def draft_request(record, **changes):
    return {"record_field": "lead_id", "record_id": record["id"],
            "instructions": "Thank Jack after the demo and ask about next steps.", **changes}


def answer(subject="Next steps after our demo", body="Hi Jack,\n\nThank you for your time. When could we talk next?",
           outcome="draft"):
    return json.dumps({"outcome": outcome, "subject": subject, "body": body})


def chat(content, finish="stop"):
    return {"choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content}}]}


@pytest.fixture
def server(monkeypatch):
    """The OpenAI-compatible server: what the app sent, and the answers it gets (the last one repeats)."""
    monkeypatch.setenv("EMAIL_DRAFT_MODE", "openai_compatible")
    monkeypatch.setenv("COMPAT_BASE_URL", "https://llm.example/v1/")
    monkeypatch.setenv("COMPAT_EMAIL_MODEL", "qwen2.5:7b-instruct")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-litellm-test")
    seen, replies = [], [(200, chat(answer()))]
    real = httpx.AsyncClient

    def handler(req):
        seen.append(req)
        status, body = replies[min(len(seen), len(replies)) - 1]
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)

    monkeypatch.setattr(ai_email.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return seen, replies


def test_draft_goes_to_the_chat_completions_endpoint_with_the_key_and_model(client, record, server):
    seen, _ = server
    response = client.post("/api/emails/draft", json=draft_request(record))
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == "openai_compatible"
    assert "When could we talk next?" in response.json()["body"]
    assert "ravi@crm.test" in response.json()["body"]  # the server adds the sender's signature
    sent = seen[0]
    assert str(sent.url) == "https://llm.example/v1/chat/completions"
    assert sent.headers["authorization"] == "Bearer sk-litellm-test"
    payload = json.loads(sent.content)
    assert payload["model"] == "qwen2.5:7b-instruct"
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["schema"] == ai_email.DRAFT_SCHEMA
    assert payload["stream"] is False
    assert payload["messages"][0]["role"] == "system"
    assert "ONE JSON object" in payload["messages"][0]["content"]
    assert client.get("/api/emails/settings").json()["draft_mode"] == "openai_compatible"
    assert client.get("/api/emails/settings").json()["ai_drafting_enabled"] is True


def test_the_address_and_model_fall_back_to_the_assistant_settings(client, record, server, monkeypatch):
    seen, _ = server
    monkeypatch.delenv("COMPAT_BASE_URL")
    monkeypatch.delenv("COMPAT_EMAIL_MODEL")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://assistant.example/v1")
    monkeypatch.setenv("OPENAI_MODEL", "mistral-nemo:12b")
    assert client.post("/api/emails/draft", json=draft_request(record)).status_code == 200
    assert str(seen[0].url) == "https://assistant.example/v1/chat/completions"
    assert json.loads(seen[0].content)["model"] == "mistral-nemo:12b"


def test_no_key_means_no_authorization_header(client, record, server, monkeypatch):
    seen, _ = server
    monkeypatch.setattr(ai_email, "api_key", lambda: "")
    assert client.post("/api/emails/draft", json=draft_request(record)).status_code == 200
    assert "authorization" not in seen[0].headers


@pytest.mark.parametrize("content", [
    "<think>The user wants a thank-you.</think>\n" + answer(),
    "```json\n" + answer() + "\n```",
    "Here is the email:\n" + answer() + "\nHope that helps!",
    "reasoning without an opening tag</think>" + answer(),
])
def test_thinking_text_and_code_fences_around_the_json_are_ignored(client, record, server, content):
    server[1][:] = [(200, chat(content))]
    response = client.post("/api/emails/draft", json=draft_request(record))
    assert response.status_code == 200, response.text
    assert response.json()["subject"] == "Next steps after our demo"
    assert "<think>" not in response.json()["body"] and "```" not in response.json()["body"]


def test_extra_keys_and_an_uppercase_outcome_are_tolerated(client, record, server):
    raw = json.dumps({"outcome": "DRAFT", "subject": "Hello", "body": "Hi Jack,\n\nWhen can we speak?", "notes": "extra"})
    server[1][:] = [(200, chat(raw))]
    assert client.post("/api/emails/draft", json=draft_request(record)).status_code == 200


def test_a_server_that_refuses_json_schema_is_retried_with_the_next_option_and_remembered(client, record, server):
    seen, replies = server
    replies[:] = [(400, {"error": "response_format json_schema is not supported"}),
                  (400, {"error": "response_format json_object is not supported"}), (200, chat(answer()))]
    assert client.post("/api/emails/draft", json=draft_request(record)).status_code == 200
    formats = [json.loads(r.content).get("response_format", {}).get("type") for r in seen]
    assert formats == ["json_schema", "json_object", None]
    seen.clear()
    replies[:] = [(200, chat(answer()))]
    assert client.post("/api/emails/draft", json=draft_request(record, instructions="Follow up again please.")).status_code == 200
    assert "response_format" not in json.loads(seen[0].content)  # starts with what worked last time


def test_json_mode_can_be_chosen(client, record, server, monkeypatch):
    monkeypatch.setenv("COMPAT_JSON_MODE", "none")
    assert client.post("/api/emails/draft", json=draft_request(record)).status_code == 200
    assert "response_format" not in json.loads(server[0][0].content)


def test_extra_body_is_added_but_cannot_replace_the_model_or_messages(client, record, server, monkeypatch):
    monkeypatch.setenv("COMPAT_EXTRA_BODY", '{"think": false, "model": "evil", "messages": []}')
    assert client.post("/api/emails/draft", json=draft_request(record)).status_code == 200
    payload = json.loads(server[0][0].content)
    assert payload["think"] is False
    assert payload["model"] == "qwen2.5:7b-instruct" and payload["messages"]


def test_an_unusable_answer_is_asked_for_once_more(client, record, server):
    seen, replies = server
    replies[:] = [(200, chat("Sure! Here you go: no json at all")), (200, chat(answer()))]
    assert client.post("/api/emails/draft", json=draft_request(record)).status_code == 200
    assert len(seen) == 2


@pytest.mark.parametrize("bad", [chat("not json"), chat(answer(), finish="length"), {"choices": []},
                                 chat(json.dumps({"outcome": "maybe", "subject": "x", "body": "y"}))])
def test_two_unusable_answers_keep_the_existing_draft(client, record, server, bad):
    server[1][:] = [(200, bad)]
    response = client.post("/api/emails/draft", json=draft_request(record, current_body="Hi Jack,\n\nOriginal text."))
    assert response.status_code == 502
    assert "unusable draft" in response.json()["detail"]


def test_an_answer_with_only_a_greeting_is_not_a_draft(client, record, server):
    server[1][:] = [(200, chat(answer(body="Hi Jack,")))]
    response = client.post("/api/emails/draft", json=draft_request(record))
    assert response.status_code == 502


@pytest.mark.parametrize("outcome,expected", [("unsupported", "helps with CRM and sales emails"),
                                              ("needs_context", "more sales context")])
def test_the_models_scope_answers_become_the_usual_messages(client, record, server, outcome, expected):
    server[1][:] = [(200, chat(answer(subject="", body="", outcome=outcome)))]
    response = client.post("/api/emails/draft", json=draft_request(record))
    assert response.status_code == 422
    assert expected in response.json()["detail"]


@pytest.mark.parametrize("status,expected,code", [
    (401, "rejected the API key", 502), (403, "rejected the API key", 502),
    (404, "could not find the model", 502), (429, "usage limits", 429), (500, "could not generate a draft", 502)])
def test_server_errors_have_clear_messages_and_no_private_details(client, record, server, status, expected, code):
    server[1][:] = [(status, {"error": {"message": "PRIVATE_PROVIDER_DETAIL"}})]
    response = client.post("/api/emails/draft", json=draft_request(record))
    assert response.status_code == code
    assert expected in response.json()["detail"]
    assert "PRIVATE_PROVIDER_DETAIL" not in response.text


@pytest.mark.parametrize("error,code,expected", [(httpx.ReadTimeout("slow"), 504, "took too long"),
                                                 (httpx.ConnectError("down"), 502, "Cannot reach")])
def test_an_unreachable_or_slow_server_keeps_the_email(client, record, server, error, code, expected):
    server[1][:] = [(200, error)]
    response = client.post("/api/emails/draft", json=draft_request(record))
    assert response.status_code == code
    assert expected in response.json()["detail"]


def test_a_bad_address_is_refused_before_any_request(client, record, server, monkeypatch):
    monkeypatch.setenv("COMPAT_BASE_URL", "ftp://llm.example/v1")
    response = client.post("/api/emails/draft", json=draft_request(record))
    assert response.status_code == 503 and "COMPAT_BASE_URL" in response.json()["detail"]
    assert not server[0]


def test_refining_an_existing_draft_sends_it_without_the_signature(client, record, server):
    seen, _ = server
    body = "Hi Jack,\n\nPlease let me know when you can meet.\n\nBest regards,\nRavi Kumar\nravi@crm.test"
    response = client.post("/api/emails/draft", json=draft_request(record, action="formalize", current_body=body,
                                                                    current_subject="Meeting"))
    assert response.status_code == 200, response.text
    sent = json.loads(seen[0].content)
    assert "ravi@crm.test" not in json.dumps(sent["messages"][1:])
    assert response.json()["subject"] == "Meeting"  # a refinement keeps the subject


def test_the_openai_key_is_not_needed_to_turn_it_on(client, record, server, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setattr(ai_email, "api_key", lambda: "")
    assert client.get("/api/emails/settings").json()["ai_drafting_enabled"] is True


def test_campaign_drafts_use_the_same_server_and_placeholders(client, server):
    seen, replies = server
    replies[:] = [(200, chat(answer(subject="Demo day, {company}", body="Hi [First Name],\n\nJoin our demo at {Company}.\n\n{sender_name}")))]
    response = client.post("/api/campaigns/draft", json={"instructions": "Invite them to a 20 minute demo next week."})
    assert response.status_code == 200, response.text
    assert str(seen[0].url) == "https://llm.example/v1/chat/completions"
    assert response.json()["subject"] == "Demo day, {company}"
    assert "Hi {first_name}," in response.json()["body"]  # the model's placeholder variants are fixed
    assert "{company}" in response.json()["body"]


def test_extract_json_and_parse_reply_directly():
    assert ai_email.extract_json("<think>a { b }</think>{\"x\": 1}") == '{"x": 1}'
    assert ai_email.extract_json("no braces here") == "no braces here"
    reply = ai_email.parse_reply('{"subject": "S", "body": "B"}')  # no outcome: a draft
    assert (reply.outcome, reply.subject, reply.body) == ("draft", "S", "B")
    with pytest.raises(ValueError):
        ai_email.parse_reply("[1, 2]")


def test_the_mode_counts_as_one_of_our_own_models_for_the_one_at_a_time_rule():
    assert "openai_compatible" in ai_email.OPEN_MODEL_MODES and "ollama" in ai_email.OPEN_MODEL_MODES
    assert "openai" not in ai_email.OPEN_MODEL_MODES


def test_assistant_extra_body_is_added_to_model_calls_but_cannot_replace_the_model(monkeypatch):
    from app import assistant, security
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_MODEL", "qwen3:8b")
    monkeypatch.setenv("ASSISTANT_EXTRA_BODY", '{"think": false, "model": "evil"}')
    monkeypatch.setattr(assistant, "tools_for", lambda me: [])
    monkeypatch.setattr(assistant, "acting_user", lambda: None)
    seen = {}

    def fake_post(url, **kw):
        seen.update(kw["json"])
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(assistant.httpx, "post", fake_post)
    assert assistant.call_model([{"role": "user", "content": "hi"}])["content"] == "ok"
    assert seen["think"] is False and seen["model"] == "qwen3:8b"
    monkeypatch.setenv("ASSISTANT_EXTRA_BODY", "not json")
    assert assistant.extra_body() == {}


# ---------- the Assistant with models that never stop calling tools (open models behind Ollama / LiteLLM) ----------

def _assistant_with(monkeypatch, steps):
    """steps: what the model answers, in order. A string is words; a list is tool calls. Also records tools=False asks."""
    from app import assistant
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    asked = []

    def fake(messages, tools=True):
        asked.append(tools)
        step = steps.pop(0)
        return {"role": "assistant", "content": step} if isinstance(step, str) else {"role": "assistant", "content": "", "tool_calls": step}

    monkeypatch.setattr(assistant, "call_model", fake)
    return asked


def test_a_model_that_repeats_the_same_tool_call_is_made_to_answer_in_words(client, monkeypatch):
    from test_assistant import call
    asked = _assistant_with(monkeypatch, [[call("pipeline_summary")], [call("pipeline_summary")],
                                          "You have 1 lead in total."])
    res = client.post("/api/assistant/chat", json={"message": "How many leads do I have?"})
    assert res.status_code == 200, res.text
    assert res.json()["reply"] == "You have 1 lead in total."
    assert asked == [True, True, False]  # the repeat was skipped and the answer asked for without tools
    tool_messages = [m for m in res.json().get("messages", []) if m.get("role") == "tool"]
    assert len(tool_messages) <= 1  # the tool ran once, not twice


def test_a_different_second_tool_call_still_runs(client, monkeypatch):
    from test_assistant import call
    asked = _assistant_with(monkeypatch, [[call("pipeline_summary")], [call("list_users")], "Here you go."])
    res = client.post("/api/assistant/chat", json={"message": "Summary and users please"})
    assert res.status_code == 200, res.text
    assert res.json()["reply"] == "Here you go."
    assert asked == [True, True, True]  # nothing was skipped


def test_call_key_ignores_argument_order_and_spacing():
    from app import assistant
    a = {"function": {"name": "list_leads", "arguments": '{"stage": "New", "search": "x"}'}}
    b = {"function": {"name": "list_leads", "arguments": '{ "search":"x",  "stage":"New" }'}}
    c = {"function": {"name": "list_leads", "arguments": '{"stage": "Demo"}'}}
    assert assistant.call_key(a) == assistant.call_key(b) != assistant.call_key(c)
    assert assistant.call_key({"function": {"name": "x", "arguments": "not json"}}) == ("x", "not json")


# ---------- a thinking model that returns nothing: say what to change ----------

def _thinking_answer(finish="stop", with_reasoning=True):
    message = {"role": "assistant", "content": ""}
    if with_reasoning:
        message["reasoning_content"] = "Let me think about the email step by step ..." * 50
    return {"choices": [{"index": 0, "finish_reason": finish, "message": message}]}


@pytest.mark.parametrize("answer", [_thinking_answer(), _thinking_answer(finish="length", with_reasoning=False)])
def test_an_empty_answer_from_a_thinking_model_says_how_to_fix_it_and_is_not_retried(client, record, server, answer):
    seen, replies = server
    replies[:] = [(200, answer)]
    response = client.post("/api/emails/draft", json=draft_request(record))
    assert response.status_code == 502
    assert 'COMPAT_EXTRA_BODY={"think": false}' in response.json()["detail"]
    assert "unusable draft" not in response.json()["detail"]
    assert len(seen) == 1  # asking again would take as long and fail the same way


def test_the_thinking_message_also_applies_to_campaign_drafts(client, server):
    server[1][:] = [(200, _thinking_answer())]
    response = client.post("/api/campaigns/draft", json={"instructions": "Invite them to a demo next week."})
    assert response.status_code == 502 and "think" in response.json()["detail"]


def test_a_short_unusable_answer_is_still_just_unusable_not_a_thinking_problem(client, record, server):
    server[1][:] = [(200, {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "not json"}}]})]
    response = client.post("/api/emails/draft", json=draft_request(record))
    assert response.status_code == 502 and "unusable draft" in response.json()["detail"]


def test_the_assistant_explains_an_empty_answer_instead_of_showing_nothing(client, monkeypatch):
    _assistant_with(monkeypatch, [""])
    res = client.post("/api/assistant/chat", json={"message": "How many leads do I have?"})
    assert res.status_code == 200, res.text
    assert 'ASSISTANT_EXTRA_BODY={"think": false}' in res.json()["reply"]
