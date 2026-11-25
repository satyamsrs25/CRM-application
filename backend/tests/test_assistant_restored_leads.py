"""The AI Assistant answers about deleted and restored leads (deleted_leads_report, and get_lead's
restored_from_deleted_leads): which leads were restored, by whom and when, and what is still in Deleted Leads.

The model is scripted (no AI service), as in test_assistant_assignment_counts.py. Users: 1 Priya (Manager),
2 Ravi (Salesperson in Priya's team), 3 Asha (Admin). All data is made up."""
import json

from app import assistant
from conftest import login_as
from test_assistant import ai, call  # noqa: F401
from test_deleted_leads import deleted, new_lead

PRIYA, RAVI, ASHA = 1, 2, 3


def tool(client, ai, user_id, name="deleted_leads_report", **args):  # noqa: F811
    script, seen = ai
    script += [[call(name, **args)], "Scripted answer."]
    res = login_as(client, user_id).post("/api/assistant/chat", json={"message": "Which leads were restored?"})
    assert res.status_code == 200, res.text
    return json.loads(seen[-1][-1]["content"])


def test_restored_and_waiting_deleted_leads_are_reported(client, ai):  # noqa: F811
    login_as(client, ASHA)
    back, waiting = new_lead(client, "Restored"), new_lead(client, "Waiting")
    for item in (back, waiting):
        assert client.delete(f"/api/leads/{item['id']}").status_code == 200
    row = next(r for r in deleted(client)["items"] if r["name"] == "Test Restored")
    assert client.post("/api/deleted-leads/restore", json={"ids": [row["id"]]}).json()["restored"]

    out = tool(client, ai, ASHA)
    assert out["restored_count"] == 1 and out["restored_by"] == {"Asha Rao": 1}
    first = out["restored"][0]
    assert first["lead"] == "Test Restored" and first["lead_id"] == back["id"] and first["owner_now"] == "Unassigned Pool"
    assert first["restored_by"] == "Asha Rao" and first["restored_at"].endswith("IST")
    assert out["in_deleted_leads_count"] == 1 and out["in_deleted_leads"][0]["lead"] == "Test Waiting"
    assert out["in_deleted_leads"][0]["days_left_to_restore"] == 90 and out["in_deleted_leads"][0]["deleted_by"] == "Asha Rao"

    lead = tool(client, ai, ASHA, name="get_lead", lead_id=back["id"])
    assert lead["restored_from_deleted_leads"][0]["note"].startswith("Restored from Deleted Leads by Asha Rao")
    other = new_lead(login_as(client, ASHA), "Never")
    assert "restored_from_deleted_leads" not in tool(client, ai, ASHA, name="get_lead", lead_id=other["id"])


def test_a_salesperson_sees_only_restored_leads_they_own_and_no_deleted_leads(client, ai):  # noqa: F811
    login_as(client, ASHA)
    item = new_lead(client, "Pooled")
    client.delete(f"/api/leads/{item['id']}")
    client.post("/api/deleted-leads/restore", json={"ids": [deleted(client)["items"][0]["id"]]})
    out = tool(client, ai, RAVI)
    assert out["restored_count"] == 0 and "Only the Admin and Managers" in out["deleted_leads"]
    assert "in_deleted_leads" not in out
    assert tool(client, ai, PRIYA)["restored_count"] == 1  # a pooled lead: the Manager sees it


def test_the_assistant_is_told_to_use_the_report(client, ai):  # noqa: F811
    tool(client, ai, ASHA)
    prompt = ai[1][0][0]["content"]
    assert "Deleted or restored leads (Leads > Deleted Leads): always use deleted_leads_report" in prompt
    me = type("Me", (), {"role": "Admin", "can": lambda self, p: False})()
    assert "deleted_leads_report" in {t["function"]["name"] for t in assistant.tools_for(me)}
