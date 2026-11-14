"""AI drafting uses a mocked provider and an isolated database; never sends email."""
import json

import httpx
import pytest
from sqlalchemy import func, select

from app import ai_email, mailer
from app.database import get_db
from app.main import app
from app.models import Account, Email, Lead, Opportunity, RolePermission
from conftest import login_as


@pytest.fixture(autouse=True)
def isolate_key_configuration(monkeypatch):
    # Test requests must never read the real locally mounted key.
    monkeypatch.delenv("OPENAI_ENV_FILE", raising=False)


@pytest.fixture
def record(client, monkeypatch):
    monkeypatch.setattr(mailer, "send", lambda *a, **kw: None)
    response = client.post('/api/leads', json={"source": "Website", "first_name": "Jack", "last_name": "Jones", "company": "Bluebird", "email": "jack@bluebird.example", "welcome_email": False})
    assert response.status_code == 201, response.text
    return response.json()


def request(record, **changes):
    return {"record_field": "lead_id", "record_id": record["id"], "instructions": "Thank Jack after the demo and ask about next steps.", **changes}


def model_reply(subject, body, outcome="draft"):
    return json.dumps({"outcome": outcome, "subject": subject, "body": body})


def completed(text=None):
    return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": text or model_reply("Next steps after our demo", "Hi Jack,\n\nThank you for your time. When would you like to discuss next steps?")}]}]}


def scope_call(req):
    """True for the scope check (the short classification sent before a draft), on either provider."""
    payload = json.loads(req.content)
    system = payload.get("instructions") or (payload.get("messages") or [{}])[0].get("content")
    return system == ai_email.SCOPE_INSTRUCTIONS


@pytest.fixture
def provider(monkeypatch):
    """MOCKED provider (no AI service is called). Drafting requests are captured in [0]; scope checks in
    reply["scope_requests"] and answered with reply["scope"] ("crm_email" unless a test says otherwise)."""
    monkeypatch.setenv("EMAIL_DRAFT_MODE", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-a-real-key")
    captured = []
    reply = {"status": 200, "json": completed(), "scope": "crm_email", "scope_requests": []}
    real_client = httpx.AsyncClient

    def handler(req):
        scope = scope_call(req)
        (reply["scope_requests"] if scope else captured).append(req)
        if reply.get("error"):
            raise reply["error"]
        if scope and reply["status"] == 200:
            verdict = reply.get("scope_text") or json.dumps({"scope": reply["scope"]})
            local = req.url.host != "api.openai.com"
            return httpx.Response(200, json={"done": True, "message": {"content": verdict}} if local else completed(verdict))
        return httpx.Response(reply["status"], json=reply["json"])

    monkeypatch.setattr(ai_email.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    return captured, reply


def test_draft_uses_record_context_and_does_not_send_or_save(client, record, provider, monkeypatch):
    captured, _ = provider
    monkeypatch.setattr(mailer, "send", lambda *a, **kw: pytest.fail("Drafting must not send mail"))
    db = next(app.dependency_overrides[get_db]())
    before = db.scalar(select(func.count()).select_from(Email))
    response = client.post('/api/emails/draft', json=request(record))
    assert response.status_code == 200, response.text
    assert response.json()['subject'] == 'Next steps after our demo'
    assert response.json()['body'].endswith('Best regards,\nRavi Kumar')  # the sender's name only: no role or email
    assert 'ravi@crm.test' not in response.json()['body']
    payload = json.loads(captured[0].content)
    context = json.loads(payload['input'])
    assert context['crm_context']['first_name'] == 'Jack'
    assert context['crm_context']['current_stage'] == 'New'
    assert 'Introduce yourself' in context['stage_guidance']
    assert response.json()['stage'] == 'New'
    assert response.json()['mode'] == 'openai'
    assert 'jack@bluebird.example' not in payload['input']
    assert 'ravi@crm.test' not in payload['input']
    assert payload['store'] is False
    assert payload['text']['format']['strict'] is True
    assert db.scalar(select(func.count()).select_from(Email)) == before
    assert client.get(f"/api/leads/{record['id']}").json()['stage'] == 'New'
    db.close()


def test_missing_configuration_is_actionable(client, record, monkeypatch):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'openai')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert client.get('/api/emails/settings').json()['ai_drafting_enabled'] is False
    response = client.post('/api/emails/draft', json=request(record))
    assert response.status_code == 503
    assert 'OPENAI_API_KEY' in response.json()['detail']


@pytest.mark.parametrize('action', ['formalize', 'friendly', 'shorten'])
def test_refinements_use_existing_draft_and_preserve_subject_and_stage(client, record, provider, monkeypatch, action):
    monkeypatch.setattr(mailer, 'send', lambda *a, **kw: pytest.fail('Refinement must not send email'))
    db = next(app.dependency_overrides[get_db]())
    db.get(Lead, record['id']).stage = 'Revisit'
    db.commit()
    original = 'Hi Jack,\n\nCould you confirm availability on November 12?\n\nBest regards,\nRavi Kumar\nravi@crm.test'
    provider[1]['json'] = completed(model_reply('Model changed subject', original))
    response = client.post('/api/emails/draft', json=request(
        record, action=action, instructions='', current_subject='Checking your availability', current_body=original))
    assert response.status_code == 200, response.text
    assert response.json()['subject'] == 'Checking your availability'
    assert response.json()['body'].count('Best regards,') == 1
    assert response.json()['record_stage'] == 'Revisit'
    payload = json.loads(json.loads(provider[0][0].content)['input'])
    assert payload['existing_message'] == original
    assert payload['email_action'] == action
    assert payload['user_request'] == ai_email.REFINEMENTS[action]
    assert payload['crm_context']['current_stage'] == 'Revisit'
    assert client.get(f"/api/leads/{record['id']}").json()['stage'] == 'Revisit'
    assert db.scalar(select(func.count()).select_from(Email)) == 0
    db.close()


@pytest.mark.parametrize('action', ['formalize', 'friendly', 'shorten'])
def test_refinements_require_existing_message_before_provider_call(client, record, provider, action):
    response = client.post('/api/emails/draft', json=request(record, action=action, current_body='   '))
    assert response.status_code == 422
    assert not provider[0]


@pytest.mark.parametrize('extra', [{'option_id': 'introduce'}, {'email_stage': 'Won'}])
def test_refinements_cannot_override_stage_or_select_a_template(client, record, provider, extra):
    response = client.post('/api/emails/draft', json=request(record, action='friendly', current_body='Hi Jack, let’s reconnect.', **extra))
    assert response.status_code == 422
    assert not provider[0]


def test_refinement_with_blank_subject_can_generate_a_subject(client, record, provider):
    response = client.post('/api/emails/draft', json=request(record, action='shorten', current_body='Hi Jack, please share your availability.'))
    assert response.status_code == 200
    assert response.json()['subject'] == 'Next steps after our demo'


def test_sample_mode_does_not_pretend_to_refine_existing_email(client, record, provider, monkeypatch):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'sample')
    response = client.post('/api/emails/draft', json=request(record, action='formalize', current_body='Hi Jack, let’s reconnect.'))
    assert response.status_code == 422
    assert 'AI mode' in response.json()['detail']
    assert not provider[0]


def test_requires_login(client, record, provider):
    client.headers.pop('Authorization')
    assert client.post('/api/emails/draft', json=request(record)).status_code == 401
    assert not provider[0]


def test_cannot_draft_for_another_owners_record(client, record, provider):
    login_as(client, 1)
    other = client.post('/api/leads', json={"first_name": "Test", "source": "Website", "last_name": "Private", "company": "Private Inc", "welcome_email": False}).json()
    login_as(client, 2)
    assert client.post('/api/emails/draft', json=request(other)).status_code == 404
    assert not provider[0]


def test_requires_email_permission(client, record, provider):
    db = next(app.dependency_overrides[get_db]())
    db.add(RolePermission(role='Salesperson', permission='send_emails', allowed=False))
    db.commit()
    db.close()
    assert client.post('/api/emails/draft', json=request(record)).status_code == 403
    assert not provider[0]


@pytest.mark.parametrize('changes', [{"record_field": "users"}, {"record_id": 0}, {"stage": "Invalid"}, {"instructions": 'x' * 4001}, {"current_body": 'x' * 16001}, {"to": "extra@field.example"}])
def test_request_validation(client, record, provider, changes):
    assert client.post('/api/emails/draft', json=request(record, **changes)).status_code == 422
    assert not provider[0]


@pytest.mark.parametrize('status,expected', [(401, 502), (429, 429), (500, 502)])
def test_provider_errors_are_sanitized(client, record, provider, status, expected):
    _, reply = provider
    reply.update(status=status, json={"error": "SENSITIVE_PROVIDER_DETAIL"})
    response = client.post('/api/emails/draft', json=request(record))
    assert response.status_code == expected
    assert 'SENSITIVE_PROVIDER_DETAIL' not in response.text


@pytest.mark.parametrize('output', [completed('not JSON'), completed(model_reply('Hello', '')), completed(model_reply('Hello\nInjected', 'Text')), {"status": "incomplete", "output": []}])
def test_rejects_bad_or_incomplete_output(client, record, provider, output):
    provider[1]['json'] = output
    assert client.post('/api/emails/draft', json=request(record)).status_code == 502


def test_handles_refusal(client, record, provider):
    provider[1]['json'] = {"status": "completed", "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "Not available"}]}]}
    assert client.post('/api/emails/draft', json=request(record)).status_code == 422


def test_timeout_preserves_email(client, record, provider):
    provider[1]['error'] = httpx.ReadTimeout('timeout')
    response = client.post('/api/emails/draft', json=request(record))
    assert response.status_code == 504
    assert 'unchanged' in response.json()['detail']


def test_custom_model_and_current_message(client, record, provider, monkeypatch):
    monkeypatch.setenv('OPENAI_EMAIL_MODEL', 'configured-model')
    assert client.post('/api/emails/draft', json=request(record, current_subject='My subject', current_body='My draft')).status_code == 200
    payload = json.loads(provider[0][0].content)
    assert payload['model'] == 'configured-model'
    assert json.loads(payload['input'])['existing_message'] == 'My draft'


@pytest.mark.parametrize("stage", ["Unqualified", "New", "Nurturing", "Revisit", "Demo", "Converted", "Lost"])
def test_sample_mode_uses_real_lead_stage_without_a_provider(client, record, monkeypatch, stage):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'sample')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setattr(ai_email.httpx, 'AsyncClient', lambda **kw: pytest.fail('Sample mode must not call OpenAI'))
    monkeypatch.setattr(mailer, 'send', lambda *a, **kw: pytest.fail('Drafts must not send mail'))
    db = next(app.dependency_overrides[get_db]())
    lead = db.get(Lead, record['id'])
    lead.stage = stage
    lead.lost_notes = 'INTERNAL_LOSS_NOTES'
    db.commit()
    before = db.scalar(select(func.count()).select_from(Email))
    response = client.post('/api/emails/draft', json=request(record))
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft['mode'] == 'sample'
    assert draft['stage'] == stage
    assert draft['subject'] == ai_email.SAMPLE_EMAILS[stage][0]
    assert draft['body'].startswith('Hi Jack,')
    assert 'INTERNAL_LOSS_NOTES' not in draft['body']
    assert draft['body'].endswith('\n\nBest regards,\nRavi Kumar') and 'ravi@crm.test' not in draft['body']
    assert db.scalar(select(func.count()).select_from(Email)) == before
    assert db.get(Lead, record['id']).stage == stage
    settings = client.get('/api/emails/settings').json()
    assert settings['draft_mode'] == 'sample'
    assert settings['ai_drafting_enabled'] is True
    db.close()


def test_client_cannot_override_the_real_stage(client, record, provider):
    assert client.post('/api/emails/draft', json=request(record, stage='Won')).status_code == 422
    assert not provider[0]


@pytest.mark.parametrize("action,subject", [("stage", "Let’s connect"), ("follow_up", "Following up on our conversation"), ("meeting", "A convenient time to connect"), ("thanks", "Thank you for your time")])
def test_four_sample_menu_actions_generate_relevant_emails(client, record, monkeypatch, action, subject):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'sample')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.setattr(ai_email.httpx, 'AsyncClient', lambda **kw: pytest.fail('Samples must not call OpenAI'))
    response = client.post('/api/emails/draft', json=request(record, action=action))
    assert response.status_code == 200, response.text
    assert response.json()['subject'] == subject
    assert response.json()['stage'] == 'New'
    assert response.json()['mode'] == 'sample'


def test_sample_mode_does_not_pretend_to_interpret_custom_requests(client, record, monkeypatch):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'sample')
    response = client.post('/api/emails/draft', json=request(record, action='custom'))
    assert response.status_code == 422
    assert 'Custom descriptions need AI mode' in response.json()['detail']


def test_ai_menu_action_reaches_provider(client, record, provider):
    response = client.post('/api/emails/draft', json=request(record, action='meeting', instructions=''))
    assert response.status_code == 200
    content = json.loads(json.loads(provider[0][0].content)['input'])
    assert content['email_action'] == 'meeting'
    assert 'arrange a meeting' in content['user_request']
    assert content['crm_context']['current_stage'] == 'New'


def test_key_is_read_from_secret_file_without_exporting_it(tmp_path, monkeypatch):
    config = tmp_path / '.env'
    config.write_text('OPENAI_API_KEY="synthetic-local-test-key"\n')
    monkeypatch.setenv('OPENAI_ENV_FILE', str(config))
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    assert ai_email.api_key() == 'synthetic-local-test-key'
    import os
    assert 'OPENAI_API_KEY' not in os.environ


def test_missing_secret_file_does_not_use_an_unintended_environment_key(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_ENV_FILE', str(tmp_path / 'absent.env'))
    monkeypatch.setenv('OPENAI_API_KEY', 'do-not-use-this-key')
    assert ai_email.api_key() == ''


@pytest.mark.parametrize('code,expected', [('credit_balance_exhausted','no API credits'), ('insufficient_quota','no available API quota'), ('billing_hard_limit_reached','API billing limit'), ('organization_spend_limit_exceeded','organization reached'), ('project_spend_limit_exceeded','project reached'), ('organization_usage_limit_exceeded','API usage limit')])
def test_quota_errors_have_actionable_sanitized_messages(client, record, provider, code, expected):
    provider[1].update(status=429, json={'error': {'code':code, 'message':'PRIVATE_PROVIDER_DETAIL'}})
    response=client.post('/api/emails/draft',json=request(record))
    assert response.status_code == 429
    assert expected in response.json()['detail']
    assert 'PRIVATE_PROVIDER_DETAIL' not in response.text


@pytest.mark.parametrize('stage,labels', [
    ('New', ['Introduce yourself and your company', 'Understand their needs and priorities', 'Share information relevant to their needs', 'Offer a brief discovery conversation']),
    ('Nurturing', ['Follow up on their current priorities', 'Share information relevant to their needs', 'Ask what questions they need answered', 'Offer a conversation when they’re ready']),
    ('Demo', ['Offer a demo focused on their needs', 'Confirm the demo agenda and availability', 'Request feedback after a completed demo', 'Ask which topics the demo should cover']),
    ('Converted', ['Thank them for continuing the discussion', 'Introduce the account team', 'Align on priorities and next steps', 'Offer a conversation when they’re ready']),
    ('Lost', ['Thank them for their time', 'Invite optional feedback on their decision', 'Offer to reconnect if their needs change', 'Close the conversation respectfully']),
])
def test_lead_menus_and_all_four_drafts_follow_database_stage(client, record, monkeypatch, stage, labels):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'sample')
    monkeypatch.setattr(ai_email.httpx, 'AsyncClient', lambda **kw: pytest.fail('Menu and samples must not call OpenAI'))
    db = next(app.dependency_overrides[get_db]())
    db.get(Lead, record['id']).stage = stage
    db.commit()
    url=f"/api/emails/draft-options?record_field=lead_id&record_id={record['id']}"
    response=client.get(url)
    assert response.status_code == 200
    menu=response.json()
    assert menu['stage'] == stage
    assert [option['label'] for option in menu['options']] == labels
    assert len({option['option_id'] for option in menu['options']}) == 4
    drafts=[]
    for option in menu['options']:
        response=client.post('/api/emails/draft',json=request(record, option_id=option['option_id'], instructions=''))
        assert response.status_code == 200, response.text
        draft=response.json()
        assert draft['stage'] == stage
        assert draft['body'].startswith('Hi Jack,')
        drafts.append(draft['subject'])
    assert len(set(drafts)) == 4
    db.close()


def test_old_stage_options_are_rejected_without_a_model_call(client, record, provider):
    response=client.post('/api/emails/draft',json=request(record,option_id='invite_demo'))
    assert response.status_code == 409
    assert 'current stage' in response.json()['detail']
    assert not provider[0]


def test_menu_refreshes_after_a_stage_change(client, record):
    url=f"/api/emails/draft-options?record_field=lead_id&record_id={record['id']}"
    before=client.get(url).json()
    db=next(app.dependency_overrides[get_db]())
    db.get(Lead,record['id']).stage='Demo'
    db.commit()
    after=client.get(url).json()
    assert before['stage']=='New'
    assert after['stage']=='Demo'
    assert before['options'] != after['options']
    db.close()


def test_stage_specific_choice_reaches_the_real_provider_adapter(client, record, provider):
    response=client.post('/api/emails/draft',json=request(record,option_id='discover_needs',instructions=''))
    assert response.status_code == 200
    payload=json.loads(json.loads(provider[0][0].content)['input'])
    assert payload['email_action']=='discover_needs'
    assert 'goals, and priorities' in payload['user_request']
    assert payload['crm_context']['current_stage']=='New'


def test_draft_menu_requires_record_access_and_email_permission(client, record):
    url=f"/api/emails/draft-options?record_field=lead_id&record_id={record['id']}"
    login_as(client,1)
    other=client.post('/api/leads',json={'first_name': 'Test', 'source': 'Website', 'last_name':'Other','company':'Private','welcome_email':False}).json()
    login_as(client,2)
    assert client.get(f"/api/emails/draft-options?record_field=lead_id&record_id={other['id']}").status_code == 404
    db=next(app.dependency_overrides[get_db]())
    db.add(RolePermission(role='Salesperson',permission='send_emails',allowed=False))
    db.commit()
    assert client.get(url).status_code == 403
    client.headers.pop('Authorization')
    assert client.get(url).status_code == 401
    db.close()


@pytest.mark.parametrize('stage', ['Unqualified','New','Nurturing','Revisit','Demo','Converted','Lost'])
def test_free_text_drafts_receive_actual_stage_and_preserve_user_intent(client, record, provider, stage):
    db=next(app.dependency_overrides[get_db]())
    db.get(Lead,record['id']).stage=stage
    db.commit()
    text='Ask about their priorities and offer a short conversation. Keep it under 100 words.'
    response=client.post('/api/emails/draft',json=request(record,action='custom',instructions=text))
    assert response.status_code == 200
    sent=json.loads(provider[0][0].content)
    payload=json.loads(sent['input'])
    assert payload['user_request'] == text
    assert payload['crm_context']['current_stage'] == stage
    assert payload['stage_guidance'] == ai_email.STAGE_GUIDANCE[stage]
    assert payload['email_action'] == 'custom'
    assert response.json()['body'].count('Best regards,') == 1
    db.close()


@pytest.mark.parametrize('stage', ['New', 'Nurturing', 'Demo', 'Converted', 'Lost'])
def test_inline_suggestion_can_be_edited_before_generation(client, record, provider, stage):
    db = next(app.dependency_overrides[get_db]())
    db.get(Lead, record['id']).stage = stage
    db.commit()
    menu = client.get('/api/emails/draft-options', params={
        'record_field': 'lead_id', 'record_id': record['id'],
    }).json()
    assert menu['stage'] == stage
    assert len(menu['options']) == 4
    description = menu['options'][0]['prompt'] + ' Focus on reporting needs; keep it under 70 words.'
    response = client.post('/api/emails/draft', json=request(record, action='custom', instructions=description))
    assert response.status_code == 200
    payload = json.loads(json.loads(provider[0][0].content)['input'])
    assert payload['user_request'] == description
    assert payload['email_stage'] == stage
    assert client.get(f"/api/leads/{record['id']}").json()['stage'] == stage
    db.close()


def test_generation_rechecks_stage_after_suggestions_were_loaded(client, record, provider):
    menu = client.get('/api/emails/draft-options', params={
        'record_field': 'lead_id', 'record_id': record['id'],
    }).json()
    db = next(app.dependency_overrides[get_db]())
    db.get(Lead, record['id']).stage = 'Nurturing'
    db.commit()
    response = client.post('/api/emails/draft', json=request(
        record, action='custom', instructions=menu['options'][0]['prompt']))
    assert response.status_code == 200
    assert response.json()['record_stage'] == 'Nurturing'
    payload = json.loads(json.loads(provider[0][0].content)['input'])
    assert payload['stage_guidance'] == ai_email.STAGE_GUIDANCE['Nurturing']
    db.close()


@pytest.mark.parametrize('stage', ['Opportunity', 'Proposal', 'Won', 'Lost'])
def test_opportunity_suggestions_and_drafts_follow_opportunity_stage(client, provider, stage):
    db = next(app.dependency_overrides[get_db]())
    account = Account(name='Example customer', owner_id=2)
    db.add(account)
    db.flush()
    opportunity = Opportunity(name='Reporting project', account_id=account.id, owner_id=2, stage=stage)
    db.add(opportunity)
    db.commit()
    menu = client.get('/api/emails/draft-options', params={
        'record_field': 'opportunity_id', 'record_id': opportunity.id,
    }).json()
    assert menu['stage'] == stage
    assert len(menu['options']) == 4
    description = menu['options'][0]['prompt'] + ' Keep the tone friendly.'
    response = client.post('/api/emails/draft', json={
        'record_field': 'opportunity_id', 'record_id': opportunity.id,
        'action': 'custom', 'instructions': description,
    })
    assert response.status_code == 200, response.text
    payload = json.loads(json.loads(provider[0][0].content)['input'])
    assert payload['crm_context']['record_type'] == 'Opportunity'
    assert payload['crm_context']['current_stage'] == stage
    assert payload['stage_guidance'] == ai_email.STAGE_GUIDANCE[stage]
    assert payload['user_request'] == description
    db.refresh(opportunity)
    assert opportunity.stage == stage
    db.close()


@pytest.mark.parametrize('closing', [
    'Best regards,',
    'Best regards,\nRavi Kumar\nravi@crm.test',
    'Best regards,\n[Your Name]\n[Your Title]\n[Your Company]',
    'Kind regards,\n[Your Name]',
    'Best regards, Ravi Kumar',
    'BEST REGARDS,\nRavi Kumar',
    '**Best regards**,\n[Your Name]',
    'Best regards,\nRavi Kumar\nravi@crm.test\n\nBest regards,\nRavi Kumar\nravi@crm.test',
])
def test_model_signature_is_not_added_twice(client, record, provider, closing):
    body='Hi Jack,\n\nWould a short conversation about your priorities be helpful?'
    provider[1]['json']=completed(model_reply('Discussing your priorities', body+'\n\n'+closing))
    response=client.post('/api/emails/draft',json=request(record,action='custom'))
    assert response.status_code == 200, response.text
    expected=body+'\n\nBest regards,\nRavi Kumar'
    assert response.json()['body'] == expected
    assert response.json()['body'].count('Best regards,') == 1


def test_signature_normalization_is_idempotent():
    once=ai_email.with_sender_signature('Hi Jack,\n\nPlease let me know your availability.', 'Ravi Kumar', 'ravi@crm.test')
    assert ai_email.with_sender_signature(once,'Ravi Kumar','ravi@crm.test') == once


def test_signature_normalization_preserves_body_text_that_mentions_a_closing():
    body='Hi Jack,\n\nPlease use the closing phrase below in the document:\nBest regards\nis the phrase our team uses.\n\nThank you for your help.'
    assert ai_email.with_sender_signature(body,'Ravi Kumar','ravi@crm.test').startswith(body+'\n\n')


@pytest.mark.parametrize('email_stage', ['Unqualified','New','Nurturing','Revisit','Demo','Converted','Opportunity','Discovery','Proposal','Won','Lost'])
def test_email_stage_selection_changes_draft_context_not_crm_record(client, record, provider, monkeypatch, email_stage):
    monkeypatch.setattr(mailer,'send',lambda *a,**kw: pytest.fail('Drafting must not send email'))
    response=client.post('/api/emails/draft',json=request(record,action='custom',email_stage=email_stage))
    assert response.status_code == 200, response.text
    assert response.json()['stage'] == email_stage
    assert response.json()['record_stage'] == 'New'
    content=json.loads(json.loads(provider[0][0].content)['input'])
    assert content['email_stage'] == email_stage
    assert content['stage_guidance'] == ai_email.STAGE_GUIDANCE[email_stage]
    assert content['crm_context']['current_stage'] == 'New'
    assert client.get(f"/api/leads/{record['id']}").json()['stage'] == 'New'


def test_invalid_email_stage_is_rejected_before_model_call(client, record, provider):
    response=client.post('/api/emails/draft',json=request(record,email_stage='Invalid'))
    assert response.status_code == 422
    assert not provider[0]


def test_stage_alone_can_generate_a_draft(client, record, provider):
    response=client.post('/api/emails/draft',json=request(record,action='custom',email_stage='Nurturing',instructions=''))
    assert response.status_code == 200
    content=json.loads(json.loads(provider[0][0].content)['input'])
    assert content['email_stage']=='Nurturing'
    assert content['stage_guidance']==ai_email.STAGE_GUIDANCE['Nurturing']


def test_default_email_stage_tracks_current_record(client, record, provider):
    db=next(app.dependency_overrides[get_db]())
    db.get(Lead,record['id']).stage='Demo'
    db.commit()
    response=client.post('/api/emails/draft',json=request(record,email_stage=None,action='custom'))
    assert response.status_code == 200
    assert response.json()['stage']=='Demo'
    assert response.json()['record_stage']=='Demo'
    content=json.loads(json.loads(provider[0][0].content)['input'])
    assert content['email_stage']=='Demo'
    db.close()


# ---------- the drafting bar: new email or revision, CRM-only scope (all replies are mocked) ----------

STARTER = 'Hi Jack,\n\n\n\nBest regards,\nRavi Kumar'  # what New Email starts with for Ravi (name only)
OLD_STARTER = 'Hi Jack,\n\n\n\nBest regards,\nRavi Kumar\nravi@crm.test'  # the earlier starter, with the email
DRAFT = ('Hi Jack,\n\nThank you for the demo on November 12. The proposal covers 25 seats at $40 per seat.\n\n'
         'Best regards,\nRavi Kumar\nravi@crm.test')
UNRELATED = ['Write a leave request to my manager for next Friday.', 'Apply for vacation from December 20 to January 2.',
             'Ask for a day off tomorrow.', 'Write a poem about autumn.', 'Draft my resignation letter.']


def sent_input(provider):
    return json.loads(json.loads(provider[0][0].content)['input'])


@pytest.mark.parametrize('body,content', [
    (STARTER, ''), (OLD_STARTER, ''), ('', ''), ('Hello,', ''), ('Good morning Jack,\n\nBest regards,', ''),
    ('  Dear Jack Jones,  \n\n Kind regards,\nRavi Kumar\nravi@crm.test', ''),
    ('Hi Jack, let’s reconnect.', 'Hi Jack, let’s reconnect.'),
    ('Hi Jack,\n\nThanks for your time.\n\nBest regards,\nRavi Kumar', 'Thanks for your time.'),
    ('Could you share your availability?', 'Could you share your availability?'),
])
def test_draft_content_ignores_only_the_greeting_and_signature(body, content):
    assert ai_email.draft_content(body, 'Ravi Kumar', 'ravi@crm.test') == content


@pytest.mark.parametrize('body', ['', STARTER, OLD_STARTER, 'Hello,\n\nBest regards,\nRavi Kumar'])
def test_a_greeting_and_signature_alone_asks_for_a_new_email(client, record, provider, body):
    response = client.post('/api/emails/draft', json=request(
        record, action='custom', instructions='Invite Jack to a product demo.', current_body=body))
    assert response.status_code == 200, response.text
    draft = response.json()
    assert (draft['subject'], draft['draft_type']) == ('Next steps after our demo', 'new')
    assert draft['body'].startswith('Hi Jack,') and draft['body'].count('Best regards,') == 1
    sent = sent_input(provider)
    assert (sent['task'], sent['existing_message']) == ('new_email', '')


def test_a_new_draft_keeps_the_users_subject_and_fills_a_blank_one(client, record, provider):
    ask = request(record, action='custom', instructions='Invite Jack to a product demo.', current_body=STARTER)
    kept = client.post('/api/emails/draft', json={**ask, 'current_subject': 'Demo invitation'}).json()
    assert (kept['subject'], kept['draft_type']) == ('Demo invitation', 'new')
    assert client.post('/api/emails/draft', json=ask).json()['subject'] == 'Next steps after our demo'


def test_the_subject_changes_only_when_the_request_asks_for_it(client, record, provider):
    response = client.post('/api/emails/draft', json=request(
        record, action='custom', instructions='Invite Jack to a demo and suggest a clearer subject.',
        current_subject='Hello', current_body=STARTER))
    assert response.json()['subject'] == 'Next steps after our demo'


def test_a_request_on_an_existing_draft_revises_it_and_keeps_the_subject(client, record, provider):
    provider[1]['json'] = completed(model_reply('A subject from the model', DRAFT.replace('Thank you', 'Many thanks')))
    response = client.post('/api/emails/draft', json=request(
        record, action='custom', instructions='Make the opening warmer.', current_subject='Your proposal', current_body=DRAFT))
    assert response.status_code == 200, response.text
    draft = response.json()
    assert (draft['subject'], draft['draft_type']) == ('Your proposal', 'revision')
    assert draft['body'].count('Best regards,') == 1 and draft['body'].startswith('Hi Jack,\n\nMany thanks')
    sent = sent_input(provider)
    assert (sent['task'], sent['existing_message'], sent['user_request']) == ('revise_email', DRAFT, 'Make the opening warmer.')


@pytest.mark.parametrize('action', ['formalize', 'friendly', 'shorten'])
@pytest.mark.parametrize('body', [STARTER, 'Hello,\n\nKind regards,\nRavi Kumar'])
def test_refine_needs_more_than_a_greeting_and_signature(client, record, provider, action, body):
    response = client.post('/api/emails/draft', json=request(record, action=action, instructions='', current_body=body))
    assert response.status_code == 422 and response.json()['detail'] == ai_email.DESCRIBE_FIRST
    assert not provider[0]


@pytest.mark.parametrize('action,label', [('formalize', 'Professional'), ('friendly', 'Conversational'), ('shorten', 'Concise')])
def test_refine_keeps_the_facts_the_subject_and_one_signature(client, record, provider, action, label):
    # the mocked model keeps the facts and repeats the signature; the server keeps one signature and the subject
    provider[1]['json'] = completed(model_reply('A subject from the model', DRAFT + '\n\nBest regards,\nRavi Kumar'))
    response = client.post('/api/emails/draft', json=request(
        record, action=action, instructions='', current_subject='Your proposal', current_body=DRAFT))
    assert response.status_code == 200, response.text
    draft = response.json()
    assert (draft['subject'], draft['draft_type']) == ('Your proposal', 'revision')
    # the older signature (with the email) is replaced by the name-only closing, once
    assert draft['body'].count('Best regards,') == 1 and 'ravi@crm.test' not in draft['body']
    assert draft['body'].endswith('\n\nBest regards,\nRavi Kumar')
    assert all(fact in draft['body'] for fact in ('November 12', '25 seats', '$40'))
    sent = sent_input(provider)
    assert sent['task'] == 'revise_email' and sent['user_request'].startswith(label + ':')


@pytest.mark.parametrize('instructions', UNRELATED)
@pytest.mark.parametrize('extra', [{'action': 'custom'}, {'action': 'stage'}, {'action': 'meeting'},
                                   {'action': 'custom', 'email_stage': 'Won'}, {'option_id': 'introduce'}])
def test_clearly_unrelated_requests_are_refused_before_any_call_whatever_the_action_or_stage(client, record, provider, instructions, extra):
    response = client.post('/api/emails/draft', json=request(
        record, instructions=instructions, current_subject='Kept', current_body=DRAFT, **extra))
    assert response.status_code == 422 and response.json()['detail'] == ai_email.NOT_CRM == 'Ask relevant to CRM'
    assert not provider[0] and not provider[1]['scope_requests']


def test_a_customer_note_that_mentions_leave_is_left_to_the_model(client, record, provider):
    response = client.post('/api/emails/draft', json=request(
        record, action='custom', instructions="Tell Jack I'm on annual leave next week and Priya will look after his account."))
    assert response.status_code == 200 and len(provider[0]) == 1


@pytest.mark.parametrize('extra', [{'action': 'custom'}, {'action': 'stage'}, {'action': 'thanks'},
                                   {'action': 'custom', 'email_stage': 'Proposal'}, {'option_id': 'discover_needs'},
                                   {'action': 'formalize', 'instructions': ''}])
def test_the_models_unsupported_outcome_holds_for_every_action_and_stage(client, record, provider, extra):
    # MOCKED: the scope check lets it through, and the drafting model's own scope outcome still refuses it
    provider[1]['json'] = completed(model_reply('Heater repair', 'Dear landlord, the heater is broken.', outcome='unsupported'))
    response = client.post('/api/emails/draft', json={**request(
        record, instructions='Write to my landlord about the broken heater.', current_subject='Kept', current_body=DRAFT), **extra})
    assert response.status_code == 422 and response.json()['detail'] == ai_email.NOT_CRM
    assert 'landlord' not in response.text and len(provider[0]) == 1  # the model's text is never returned


def test_a_vague_request_asks_for_sales_context(client, record, provider):
    provider[1]['json'] = completed(model_reply('', '', outcome='needs_context'))
    response = client.post('/api/emails/draft', json=request(record, action='custom', instructions='Write something.', current_body=STARTER))
    assert response.status_code == 422 and response.json()['detail'] == ai_email.NEEDS_CONTEXT


@pytest.mark.parametrize('output', [
    completed(json.dumps({'subject': 'Hello', 'body': 'Hi Jack,\n\nText'})),                     # no outcome
    completed(model_reply('Hello', 'Hi Jack,\n\nText', outcome='maybe')),                       # unknown outcome
    completed(json.dumps({'outcome': 'draft', 'subject': 'Hi', 'body': 'Text', 'to': 'x@example.test'})),  # extra field
    completed(model_reply('', 'Hi Jack,\n\nText')),                                             # no subject to fill one
    completed(model_reply('Hello', 'Hi Jack,\n\nBest regards,\nRavi Kumar\nravi@crm.test')),     # greeting and signature
    completed(model_reply('Hello', '   ')),                                                     # empty body
    {'status': 'completed', 'output': []},                                                      # nothing at all
])
def test_unusable_model_output_is_rejected_so_nothing_is_applied(client, record, provider, output):
    provider[1]['json'] = output
    response = client.post('/api/emails/draft', json=request(record, action='custom', current_body=STARTER))
    assert response.status_code == 502 and 'unchanged' in response.json()['detail']


def test_links_the_user_did_not_supply_are_replaced(client, record, provider):
    provider[1]['json'] = completed(model_reply('Demo', 'Hi Jack,\n\nBook a slot at https://booking.example/ravi or see '
                                                       'www.vendor.example/pricing. Our guide: https://docs.example.test/start.'))
    response = client.post('/api/emails/draft', json=request(
        record, action='custom', instructions='Invite Jack to a demo and link our guide https://docs.example.test/start'))
    body = response.json()['body']
    assert 'booking.example' not in body and 'vendor.example' not in body and body.count('[link]') == 2
    assert 'Our guide: https://docs.example.test/start.' in body


def test_another_recipient_is_not_greeted_by_the_records_name(client, record, provider):
    client.post('/api/emails/draft', json=request(record, action='custom', recipient_is_record_contact=False))
    context = sent_input(provider)['crm_context']
    assert 'first_name' not in context and 'last_name' not in context
    assert context['recipient_is_record_contact'] is False and context['company'] == 'Bluebird'


def test_a_draft_returns_only_the_email_text_and_changes_nothing_on_the_record(client, record, provider):
    fields = ('stage', 'owner_id', 'email', 'company')
    before = client.get(f"/api/leads/{record['id']}").json()
    response = client.post('/api/emails/draft', json=request(record, action='custom', current_body=STARTER))
    assert set(response.json()) == {'subject', 'body', 'draft_type', 'stage', 'record_stage', 'mode'}
    after = client.get(f"/api/leads/{record['id']}").json()
    assert {f: after[f] for f in fields} == {f: before[f] for f in fields}


def test_instructions_state_the_scope_recipient_and_untrusted_text():
    for phrase in ('"unsupported"', '"needs_context"', 'manager', 'untrusted data', 'meeting links'):
        assert phrase in ai_email.INSTRUCTIONS
    # an unrelated request is never answered with the stage's sales email, on any drafting prompt
    for prompt in (ai_email.INSTRUCTIONS, ai_email.EDIT_INSTRUCTIONS, ai_email.LOCAL_DRAFT_INSTRUCTIONS):
        prompt = ' '.join(prompt.split())
        assert 'question or task for the assistant' in prompt and 'request with a sales email' in prompt
        assert '[Your Name]' in prompt  # the only sender placeholder, filled by the server
    assert 'untrusted data' in ai_email.SCOPE_INSTRUCTIONS and '"unrelated"' in ai_email.SCOPE_INSTRUCTIONS


@pytest.mark.parametrize("code,expected", [("expired_secret_key", "has expired"), ("invalid_api_key", "rejected the API key")])
def test_authentication_error_explains_how_to_restore_drafting(client, record, provider, code, expected):
    provider[1].update(status=401, json={"error": {"code": code, "message": "PRIVATE_PROVIDER_DETAIL"}})
    response = client.post('/api/emails/draft', json=request(record))
    assert response.status_code == 502
    detail = response.json()["detail"]
    assert expected in detail
    assert "OPENAI_API_KEY" in detail
    assert "PRIVATE_PROVIDER_DETAIL" not in detail


@pytest.mark.parametrize('action,current_body', [('custom', ''), ('formalize', 'Please let me know when you can meet.')])
def test_ollama_draft_uses_local_model_without_openai_credentials(client, record, provider, monkeypatch, action, current_body):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'ollama')
    monkeypatch.setenv('OLLAMA_BASE_URL', 'http://host.docker.internal:11434/')
    monkeypatch.setenv('OLLAMA_EMAIL_MODEL', 'qwen3.5:9b')
    monkeypatch.setattr(ai_email, 'api_key', lambda: pytest.fail('Local drafting must not read the OpenAI key'))
    provider[1]['json'] = {'done': True, 'done_reason': 'stop', 'message': {'content': model_reply('Demo availability', 'Hi Jack,\n\nWhen would you be available for a demo?')}}
    response = client.post('/api/emails/draft', json=request(record, action=action, current_body=current_body))
    assert response.status_code == 200, response.text
    assert response.json()['mode'] == 'ollama'
    assert 'available for a demo' in response.json()['body']
    sent = provider[0][0]
    assert str(sent.url) == 'http://host.docker.internal:11434/api/chat'
    assert 'authorization' not in sent.headers
    payload = json.loads(sent.content)
    assert payload['model'] == 'qwen3.5:9b'
    assert payload['format'] == ai_email.DRAFT_SCHEMA
    assert payload['think'] is False
    assert payload['keep_alive'] == '30m'
    assert client.get('/api/emails/settings').json()['ai_drafting_enabled'] is True


@pytest.mark.parametrize('reply,status,expected', [
    ({'done': False, 'message': {'content': '{}'}}, 200, 'unusable draft'),
    ({'done': True, 'done_reason': 'length', 'message': {'content': '{}'}}, 200, 'unusable draft'),
    ({'error': 'PRIVATE_PROVIDER_DETAIL'}, 404, 'model was not found'),
])
def test_ollama_failures_keep_existing_draft(client, record, provider, monkeypatch, reply, status, expected):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'ollama')
    provider[1].update(status=status, json=reply)
    response = client.post('/api/emails/draft', json=request(record))
    assert response.status_code == 502
    assert expected in response.json()['detail']
    assert 'PRIVATE_PROVIDER_DETAIL' not in response.text


@pytest.mark.parametrize('provider_mode', ['openai', 'ollama'])
@pytest.mark.parametrize('action', ['formalize', 'friendly', 'shorten'])
def test_tone_edits_have_body_only_length_budget_on_both_providers(client, record, provider, monkeypatch, provider_mode, action):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', provider_mode)
    # A signature must not inflate the shortening target or the tone-edit length guidance.
    text = ' '.join(['Please review the proposal before our next discussion.'] * 10)
    body = 'Hi Jack,\n\n' + text + '\n\nBest regards,\nRavi Kumar\nravi@crm.test'
    if provider_mode == 'ollama':
        provider[1]['json'] = {'done': True, 'message': {'content': model_reply('Proposal review', 'Hi Jack,\n\nPlease review the proposal.')}}
    response = client.post('/api/emails/draft', json=request(record, action=action, current_body=body, current_subject='Proposal review'))
    assert response.status_code == 200, response.text
    sent = json.loads(provider[0][0].content)
    if provider_mode == 'ollama':
        instruction = sent['messages'][0]['content']
        content = json.loads(sent['messages'][1]['content'])
    else:
        instruction = sent['instructions']
        content = json.loads(sent['input'])
    assert instruction == ai_email.EDIT_INSTRUCTIONS
    expected_body = ai_email.without_signature(body, 'Ravi Kumar', 'ravi@crm.test') if provider_mode == 'ollama' else body
    assert content['existing_message'] == expected_body
    assert content['edit_budget']['source_word_count'] == len(text.split())
    expected_words = int(len(text.split()) * .5) if action == 'shorten' else len(text.split())
    assert content['edit_budget']['target_max_words'] == expected_words
    assert response.json()['subject'] == 'Proposal review'


@pytest.mark.parametrize('provider_mode', ['openai', 'ollama'])
@pytest.mark.parametrize('instructions,expected_policy,expected_subject', [
    ('Rewrite the email and change the subject line to "Demo availability".', 'rewrite', 'Demo availability'),
    ('Rewrite the email but keep the subject line.', 'preserve', 'Original subject'),
    ('Keep the email concise and change the subject line to Demo availability.', 'rewrite', 'Demo availability'),
    ("Make the message warmer. Don't change the subject.", 'preserve', 'Original subject'),
    ('Please write a new email asking for demo availability.', 'preserve', 'Original subject'),
])
def test_explicit_subject_policy_reaches_both_models(client, record, provider, monkeypatch, provider_mode, instructions, expected_policy, expected_subject):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', provider_mode)
    reply = model_reply('Demo availability', 'Hi Jack,\n\nWhen are you available for a demo?')
    provider[1]['json'] = completed(reply) if provider_mode == 'openai' else {'done': True, 'message': {'content': reply}}
    response = client.post('/api/emails/draft', json=request(record, action='custom', instructions=instructions, current_subject='Original subject', current_body=DRAFT))
    assert response.status_code == 200, response.text
    assert response.json()['subject'] == expected_subject
    sent = json.loads(provider[0][0].content)
    content = json.loads(sent['input'] if provider_mode == 'openai' else sent['messages'][1]['content'])
    assert content['subject_policy'] == expected_policy
    if provider_mode == 'ollama':
        assert instructions in sent['messages'][-1]['content']
    assert 'available for a demo' in response.json()['body']


@pytest.mark.parametrize('provider_mode', ['openai', 'ollama'])
@pytest.mark.parametrize('stage,prompt', [('New', 'can you write an email'), ('Demo', 'Please draft an email.'), ('Nurturing', 'Could you please write an email for me?')])
def test_generic_email_request_uses_saved_sales_purpose(client, record, provider, monkeypatch, provider_mode, stage, prompt):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', provider_mode)
    db = next(app.dependency_overrides[get_db]())
    db.get(Lead, record['id']).stage = stage
    db.commit()
    db.close()
    reply = model_reply('Let us connect', 'Hi Jack,\n\nWhen would you be available to discuss your business needs?')
    provider[1]['json'] = completed(reply) if provider_mode == 'openai' else {'done': True, 'message': {'content': reply}}
    response = client.post('/api/emails/draft', json=request(record, action='custom', instructions=prompt, current_body=STARTER))
    assert response.status_code == 200, response.text
    sent = json.loads(provider[0][0].content)
    content = json.loads(sent['input'] if provider_mode == 'openai' else sent['messages'][1]['content'])
    assert ai_email.STAGE_GUIDANCE[stage] in content['user_request']
    assert content['task'] == 'new_email'
    assert response.json()['draft_type'] == 'new'


@pytest.mark.parametrize('prompt', ['Write to my landlord.', 'Write something.', 'Write an email requesting leave.', 'Ask Jack to attend a demo.'])
def test_specific_and_unrelated_requests_are_not_replaced_with_stage_defaults(prompt):
    assert ai_email.writing_request(prompt, False, 'New') == prompt


def test_generic_request_does_not_replace_an_existing_draft():
    prompt = 'Can you write an email?'
    assert ai_email.writing_request(prompt, True, 'New') == prompt


@pytest.mark.parametrize('subject', ['Hello\x00hidden', 'Hello\x1bhidden', 'Hello\tBcc: hidden', 'Hello\r\nBcc: hidden'])
def test_unsafe_subject_is_refused_before_provider_call(client, record, provider, subject):
    response = client.post('/api/emails/draft', json=request(record, current_subject=subject))
    assert response.status_code == 422
    assert not provider[0]


def test_provider_subject_control_characters_are_not_applied(client, record, provider):
    provider[1]['json'] = completed(model_reply('Demo\x00hidden', 'Hi Jack,\n\nWhen can we meet?'))
    response = client.post('/api/emails/draft', json=request(record))
    assert response.status_code == 502
    assert 'unchanged' in response.json()['detail']


@pytest.mark.parametrize('url', ['not-a-url', 'http://user:private@localhost:11434', 'http://localhost:11434?secret=private'])
def test_invalid_local_configuration_is_sanitized_before_network(client, record, provider, monkeypatch, url):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'ollama')
    monkeypatch.setenv('OLLAMA_BASE_URL', url)
    response = client.post('/api/emails/draft', json=request(record))
    assert response.status_code == 503
    assert 'private' not in response.text and url not in response.text
    assert not provider[0]


@pytest.mark.parametrize('action', ['stage', 'custom', 'formalize', 'friendly', 'shorten'])
def test_admin_can_draft_and_refine_another_users_lead(client, record, provider, monkeypatch, action):
    monkeypatch.setattr(mailer, 'send', lambda *args, **kwargs: pytest.fail('Drafting must not send email'))
    login_as(client, 3)  # Asha (Admin), while the lead belongs to Ravi (Salesperson).
    me = client.get('/api/auth/me').json()
    assert me['role'] == 'Admin'
    assert 'send_emails' in me['permissions']
    assert client.get('/api/emails/settings').json()['ai_drafting_enabled'] is True
    assert client.get('/api/emails/draft-options', params={'record_field': 'lead_id', 'record_id': record['id']}).status_code == 200
    before = client.get(f"/api/leads/{record['id']}").json()
    original = 'Hi Jack,\n\nCould you confirm your availability for a demo?\n\nBest regards,\nAsha Rao\nasha@crm.test'
    response = client.post('/api/emails/draft', json=request(record, action=action, instructions='Ask Jack when he is available for a demo.' if action == 'custom' else '', current_body=original if action != 'stage' else '', current_subject='Demo availability'))
    assert response.status_code == 200, response.text
    assert response.json()['body'].endswith('Best regards,\nAsha Rao') and 'asha@crm.test' not in response.json()['body']
    assert response.json()['subject'] == 'Demo availability'
    after = client.get(f"/api/leads/{record['id']}").json()
    assert (after['owner_id'], after['stage']) == (before['owner_id'], before['stage'])
    assert client.get('/api/emails', params={'lead_id': record['id']}).json() == []


# ---------- strict CRM scope: a separate check before any draft (every AI reply here is MOCKED) ----------

GENERIC_SALES = model_reply('Let’s connect', 'Hi Jack,\n\nThank you for your interest. I would love to learn more about your '
                                             'business needs.\n\nWould you be available for a brief introductory conversation?')


@pytest.mark.parametrize('body', [STARTER, DRAFT])
@pytest.mark.parametrize('instructions', ['what is algebra', 'what is alzebra', 'What is the capital of France?'])
def test_an_unrelated_question_is_refused_even_when_the_draft_model_would_return_a_sales_email(client, record, provider, instructions, body):
    # MOCKED: the scope check answers "unrelated"; the drafting model would have returned a generic sales introduction
    provider[1].update(scope='unrelated', json=completed(GENERIC_SALES))
    assert not ai_email.OFF_TOPIC.search(instructions)  # no keyword decides this: the scope check does
    response = client.post('/api/emails/draft', json=request(
        record, action='custom', instructions=instructions, current_subject='Kept subject', current_body=body))
    assert response.status_code == 422 and response.json() == {'detail': 'Ask relevant to CRM'}
    assert not provider[0]  # the drafting model is never asked, so no default sales email can be returned
    [check] = provider[1]['scope_requests']
    question = json.loads(json.loads(check.content)['input'])
    assert question['user_request'] == instructions
    assert question['task'] == ('change_existing_email' if body == DRAFT else 'new_email')
    assert question['existing_message'] == (ai_email.without_signature(DRAFT, 'Ravi Kumar', 'ravi@crm.test') if body == DRAFT else '')


def test_a_misleading_generic_sales_reply_is_never_applied_to_an_unrelated_request(client, record, provider):
    # MOCKED: both layers. The scope check is final, so a "draft" outcome with a sales email can't get through
    provider[1].update(scope='unrelated', json=completed(GENERIC_SALES))
    before = client.get(f"/api/leads/{record['id']}").json()
    response = client.post('/api/emails/draft', json=request(record, action='custom', instructions='what is alzebra', current_body=STARTER))
    assert response.status_code == 422 and 'Let’s connect' not in response.text and 'introductory' not in response.text
    assert client.get(f"/api/leads/{record['id']}").json() == before
    assert client.get('/api/emails', params={'lead_id': record['id']}).json() == []


@pytest.mark.parametrize('action', ['formalize', 'friendly', 'shorten'])
def test_refinement_of_text_that_is_not_a_customer_email_is_refused(client, record, provider, action):
    provider[1]['scope'] = 'unrelated'  # MOCKED
    notes = 'Hi Jack,\n\nWhat is algebra? Explain it with three worked examples for my homework.'
    response = client.post('/api/emails/draft', json=request(record, action=action, instructions='', current_body=notes))
    assert response.status_code == 422 and response.json()['detail'] == 'Ask relevant to CRM'
    assert not provider[0]
    question = json.loads(json.loads(provider[1]['scope_requests'][0].content)['input'])
    assert question['task'] == 'change_existing_email' and question['user_request'] == ai_email.REFINE_REQUESTS[action]
    assert 'What is algebra?' in question['existing_message']


@pytest.mark.parametrize('ask', [
    {'action': 'custom', 'instructions': 'Invite Jack to a product demo next week.', 'current_body': STARTER},
    {'action': 'custom', 'instructions': 'make it shorter', 'current_body': DRAFT},
    {'action': 'custom', 'instructions': 'Thank them for the demo and mention our algebra tutoring module.', 'current_body': STARTER},
    {'action': 'shorten', 'instructions': '', 'current_body': DRAFT},
])
def test_crm_requests_pass_the_scope_check_and_are_drafted(client, record, provider, ask):
    response = client.post('/api/emails/draft', json=request(record, current_subject='Your proposal', **ask))  # MOCKED replies
    assert response.status_code == 200, response.text
    assert len(provider[1]['scope_requests']) == 1 and len(provider[0]) == 1
    check = json.loads(provider[1]['scope_requests'][0].content)
    assert check['store'] is False and check['text']['format']['strict'] is True
    assert check['text']['format']['schema'] == ai_email.SCOPE_SCHEMA and check['model'] == json.loads(provider[0][0].content)['model']
    assert 'jack@bluebird.example' not in check['input'] and 'ravi@crm.test' not in check['input']
    revising = ask['current_body'] == DRAFT
    assert response.json()['draft_type'] == ('revision' if revising else 'new')
    if ask['instructions'] == 'make it shorter':
        assert json.loads(check['input'])['task'] == 'change_existing_email'
        assert sent_input(provider)['user_request'] == 'make it shorter'


@pytest.mark.parametrize('ask', [
    {'action': 'stage', 'instructions': '', 'current_body': STARTER},
    {'action': 'meeting', 'instructions': ''},
    {'option_id': 'introduce', 'instructions': ''},
    {'action': 'custom', 'instructions': 'Please draft an email.', 'current_body': STARTER},
])
def test_requests_written_by_the_server_need_no_scope_check(client, record, provider, ask):
    response = client.post('/api/emails/draft', json=request(record, **ask))
    assert response.status_code == 200, response.text
    assert not provider[1]['scope_requests'] and len(provider[0]) == 1


@pytest.mark.parametrize('verdict', ['not JSON', json.dumps({'scope': 'maybe'}), json.dumps({'scope': 'crm_email', 'extra': 1}), ''])
def test_a_scope_check_without_a_clear_answer_keeps_the_email(client, record, provider, verdict):
    provider[1]['scope_text'] = verdict or json.dumps({})  # MOCKED unusable classification
    response = client.post('/api/emails/draft', json=request(record, action='custom', current_body=STARTER))
    assert response.status_code == 502 and 'unchanged' in response.json()['detail']
    assert not provider[0]  # never treated as in scope


def test_scope_check_errors_use_the_same_safe_messages(client, record, provider):
    provider[1].update(status=401, json={"error": {"code": "expired_secret_key", "message": "PRIVATE_PROVIDER_DETAIL"}})
    response = client.post('/api/emails/draft', json=request(record, action='custom', current_body=STARTER))
    assert response.status_code == 502 and 'has expired' in response.json()['detail']
    assert 'PRIVATE_PROVIDER_DETAIL' not in response.text
    assert len(provider[1]['scope_requests']) == 1 and not provider[0]


def test_ollama_checks_the_scope_with_the_local_model(client, record, provider, monkeypatch):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'ollama')
    monkeypatch.setenv('OLLAMA_BASE_URL', 'http://host.docker.internal:11434/')
    monkeypatch.setattr(ai_email, 'api_key', lambda: pytest.fail('Local drafting must not read the OpenAI key'))
    provider[1]['scope'] = 'unrelated'  # MOCKED
    response = client.post('/api/emails/draft', json=request(record, action='custom', instructions='what is algebra', current_body=STARTER))
    assert response.status_code == 422 and response.json()['detail'] == 'Ask relevant to CRM'
    [check] = provider[1]['scope_requests']
    payload = json.loads(check.content)
    assert str(check.url) == 'http://host.docker.internal:11434/api/chat' and 'authorization' not in check.headers
    assert payload['format'] == ai_email.SCOPE_SCHEMA and payload['options']['num_ctx'] == 8192
    assert json.loads(payload['messages'][1]['content'])['user_request'] == 'what is algebra'
    assert not provider[0]


# ---------- sender details: the signed-in sender's name, never a placeholder or an invented company ----------

@pytest.mark.parametrize('text,expected', [
    ("I'm [Your Name] from [Your Company].", "I'm Ravi Kumar."),
    ('My name is [Your Name] and I am the [Your Title] at [Your Company].', 'My name is Ravi Kumar.'),
    ("I'm [Your Name], [Your Position] at [Your Company].", "I'm Ravi Kumar."),
    ('At [Your Company], we help teams plan their next steps.', 'We help teams plan their next steps.'),
    ('[Your Company] would be glad to help.', 'Our team would be glad to help.'),
    ('Thank you for your interest in [Your Company].', 'Thank you for your interest.'),
    ('Reach me at [Your Email] or reply here. – [Sender Name]', 'Reach me at ravi@crm.test or reply here. – Ravi Kumar'),
    ('This is {Your Full Name} following up.', 'This is Ravi Kumar following up.'),
    ('Hi [First Name], could [Client Company] share the date?', 'Hi [First Name], could [Client Company] share the date?'),  # customer side: kept
    ('Thanks for the call. We discussed the 25 seats.', 'Thanks for the call. We discussed the 25 seats.'),
])
def test_sender_placeholders_are_filled_or_removed(text, expected):
    assert ai_email.without_sender_placeholders(text, 'Ravi Kumar', 'ravi@crm.test') == expected


def test_a_draft_never_returns_sender_placeholders(client, record, provider):
    provider[1]['json'] = completed(model_reply(  # MOCKED reply with the placeholders a model tends to write
        'Introduction from [Your Company]',
        "Hi Jack,\n\nI'm [Your Name] from [Your Company]. I'd welcome a short call about your priorities.\n\n"
        'Best regards,\n[Your Name]\n[Your Title]\n[Your Company]'))
    response = client.post('/api/emails/draft', json=request(record, action='custom', instructions='Introduce myself to Jack.', current_body=STARTER))
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft['subject'] == 'Introduction'
    assert draft['body'] == ("Hi Jack,\n\nI'm Ravi Kumar. I'd welcome a short call about your priorities.\n\n"
                             'Best regards,\nRavi Kumar')
    assert '[' not in draft['body'] and 'Company' not in draft['body']


# ---------- the closing: "Best regards," and the sender's name only (no role or email) ----------

def test_the_closing_is_best_regards_and_the_name_only():
    assert ai_email.sender_closing('Ravi Kumar') == 'Best regards,' + chr(10) + 'Ravi Kumar'
    assert ai_email.sender_closing('  Ravi   Kumar ') == 'Best regards,' + chr(10) + 'Ravi Kumar'
    assert ai_email.sender_closing('') == 'Best regards,'  # no name on the account: none is invented
    nl = chr(10)
    body = ai_email.with_sender_signature(nl.join(['Hi Jack,', '', 'Thanks for the call.', '', 'Best regards,',
                                                   '[Your Name]', '[Your Title]']), '', 'ravi@crm.test')
    assert body == nl.join(['Hi Jack,', '', 'Thanks for the call.', '', 'Best regards,'])


def test_without_a_sender_name_no_name_placeholder_is_left():
    text = ai_email.without_sender_placeholders("Hi Jack, I'm [Your Name] and I'd welcome a short call.", '', 'ravi@crm.test')
    assert '[' not in text and 'Your Name' not in text and text.startswith('Hi Jack')


def lines(*parts):
    return chr(10).join(parts)


@pytest.mark.parametrize('body, expected', [
    # sender details the AI left as placeholders are removed; {sender_name} is filled with the sender's name when sent
    (lines('Hi {first_name},', '', 'Would {company} like a demo?', '', 'Best regards,', '{sender_name}', '[Your Title]',
           '[Your Company]', '[Your Email]', '{your_phone}'),
     lines('Hi {first_name},', '', 'Would {company} like a demo?', '', 'Best regards,', '{sender_name}')),
    # a line the user wrote is kept
    (lines('Hi {first_name},', '', 'Would {company} like a demo?', '', 'Best regards,', '{sender_name}', 'Head of Sales'),
     lines('Hi {first_name},', '', 'Would {company} like a demo?', '', 'Best regards,', '{sender_name}', 'Head of Sales')),
])
def test_a_campaign_sign_off_keeps_the_name_and_drops_sender_placeholders(body, expected):
    assert ai_email.campaign_signature(body) == expected


def test_a_campaign_draft_never_returns_sender_placeholders(client, provider):
    provider[1]['json'] = completed(model_reply('Join our demo', lines(  # MOCKED model reply
        'Hi {first_name},', '', 'Would {company} like a 20-minute demo? Reach me at [Your Email].', '', 'Best regards,',
        '[Your Name]', '[Your Title]', '[Your Company]', '[Your Email]')))
    response = client.post('/api/campaigns/draft', json={'instructions': 'Invite them to a demo next week.'})
    assert response.status_code == 200, response.text
    body = response.json()['body']
    assert body.endswith(lines('Best regards,', '{sender_name}'))
    assert '[' not in body and 'Your ' not in body and body.count('Best regards,') == 1


# ---------- email from a Lost opportunity: drafting only, nothing about the deal changes ----------

def lost_opportunity():
    from app.models import Contact, Task
    db = next(app.dependency_overrides[get_db]())
    account = Account(name='Lost customer', owner_id=2)
    db.add(account)
    db.flush()
    contact = Contact(first_name='Mia', last_name='Lopez', email='mia@lost-customer.example', account_id=account.id,
                      owner_id=2)
    db.add(contact)
    db.flush()
    opportunity = Opportunity(name='Lost deal', account_id=account.id, owner_id=2, stage='Lost',
                              primary_contact_id=contact.id, lost_reason='Price', lost_notes='INTERNAL_LOSS_NOTES')
    db.add(opportunity)
    db.commit()
    counts = (db.scalar(select(func.count()).select_from(Email)), db.scalar(select(func.count()).select_from(Task)))
    return db, opportunity, counts, Task


@pytest.mark.parametrize('user_id', [2, 1, 3])  # Ravi (Salesperson, the owner), Priya (Manager), Asha (Admin)
def test_a_lost_opportunity_can_be_emailed_without_changing_it(client, monkeypatch, user_id):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'sample')
    monkeypatch.setattr(ai_email.httpx, 'AsyncClient', lambda **kw: pytest.fail('Sample mode must not call an AI service'))
    monkeypatch.setattr(mailer, 'send', lambda *a, **kw: pytest.fail('Drafting must not send mail'))
    db, opportunity, before, Task = lost_opportunity()
    login_as(client, user_id)
    menu = client.get('/api/emails/draft-options', params={'record_field': 'opportunity_id', 'record_id': opportunity.id})
    assert menu.status_code == 200, menu.text
    assert menu.json()['stage'] == 'Lost' and len(menu.json()['options']) == 4
    response = client.post('/api/emails/draft', json={'record_field': 'opportunity_id', 'record_id': opportunity.id,
                                                      'option_id': menu.json()['options'][0]['option_id']})
    assert response.status_code == 200, response.text
    draft = response.json()
    assert draft['record_stage'] == 'Lost' and draft['body'].startswith('Hi Mia,')
    assert 'INTERNAL_LOSS_NOTES' not in draft['body'] and 'Price' not in draft['body']  # no internal loss reason
    assert draft['body'].count('Best regards,') == 1
    db.expire_all()
    assert (db.get(Opportunity, opportunity.id).stage, db.get(Opportunity, opportunity.id).owner_id) == ('Lost', 2)
    assert (db.scalar(select(func.count()).select_from(Email)),
            db.scalar(select(func.count()).select_from(Task))) == before  # no Sent entry, no task
    db.close()


def test_a_lost_opportunity_still_needs_the_email_permission(client, monkeypatch):
    monkeypatch.setenv('EMAIL_DRAFT_MODE', 'sample')
    db, opportunity, _, _ = lost_opportunity()
    opportunity_id = opportunity.id
    db.add(RolePermission(role='Salesperson', permission='send_emails', allowed=False))
    db.commit()
    db.close()
    login_as(client, 2)
    response = client.post('/api/emails/draft', json={'record_field': 'opportunity_id', 'record_id': opportunity_id})
    assert response.status_code == 403
