"""Manage Access > People shows each user's Open Leads: the leads they own at an open status (New, Nurturing, Revisit,
Demo), counted the same way as their own My Open Leads view, uploads nobody has worked on yet included (issue 42).
Users: 1 Priya (Manager), 2 Ravi (Salesperson, default), 3 Asha (Admin). All data is made up."""
import csv
import io

from conftest import alpha, login_as

PRIYA, RAVI, ASHA = 1, 2, 3
TASK = {"title": "Synthetic follow-up task", "due_date": "2030-01-15T10:00:00"}
LOST = {"lost_reason": "Price", "lost_notes": "Synthetic: chose another option"}


def counts(client, as_user=ASHA):
    res = login_as(client, as_user).get("/api/leads/open-counts")
    assert res.status_code == 200, res.text
    return {int(k): v for k, v in res.json()["counts"].items()}


def my_open_total(client, user_id):
    res = login_as(client, user_id).get("/api/leads/page", params={"view": "my_open", "limit": 1})
    assert res.status_code == 200, res.text
    return res.json()["total"]


def new_lead(client, owner=RAVI, n=[0]):
    n[0] += 1
    res = login_as(client, owner).post("/api/leads", json={
        "first_name": "Ana", "last_name": f"Count{alpha(n[0])}", "company": "Count Synthetic Co", "source": "Website",
        "email": f"count{n[0]}@count-synthetic.example"})
    assert res.status_code == 201, res.text
    return res.json()


def upload(client, owner, rows):
    out = io.StringIO()
    csv.writer(out).writerows([["First Name", "Last Name", "Company", "Email"], *rows])
    res = login_as(client, ASHA).post("/api/leads/import", files={"file": ("u.csv", out.getvalue().encode(), "text/csv")},
                                      data={"dry_run": "false", "owner_id": str(owner)})
    assert res.status_code == 200, res.text


def test_people_count_matches_my_open_leads_including_uploads(client):
    new_lead(client)
    new_lead(client)
    # uploads go to the Unassigned Pool: they count for nobody (not the uploader, not the owner sent with them)
    upload(client, RAVI, [[f"Up{i}", f"Loaded{i}", "Upload Synthetic Co", f"up{i}@upload-synthetic.example"] for i in range(3)])
    assert counts(client) == {RAVI: 2} and my_open_total(client, RAVI) == 2
    assert counts(client, PRIYA) == {RAVI: 2}
    # once assigned, uploaded leads nobody has worked on are in My Open Leads, so in the People count too
    pool = login_as(client, ASHA).get("/api/leads/page", params={"view": "unassigned"}).json()["items"]
    for lead in pool:
        res = login_as(client, ASHA).post(f"/api/leads/{lead['id']}/assign", json={"to_user_id": RAVI})
        assert res.status_code == 200, res.text
    assert counts(client).get(RAVI) == my_open_total(client, RAVI) == 5
    # the workspace list (which the page used to count) leaves the uploads out: that was the mismatch
    workspace = login_as(client, ASHA).get("/api/leads").json()
    assert len([l for l in workspace if l["owner_id"] == RAVI and l["stage"] in ("New", "Nurturing", "Revisit", "Demo")]) == 2


def test_counts_follow_conversion_lost_and_transfer(client):
    a, b, c = new_lead(client), new_lead(client), new_lead(client)
    assert counts(client).get(RAVI) == my_open_total(client, RAVI) == 3
    convert = login_as(client, RAVI).post(f"/api/leads/{a['id']}/convert", json={
        "note": "Synthetic conversion", "task": TASK, "completed_stages": ["New", "Nurturing", "Demo"]})
    assert convert.status_code == 200, convert.text
    assert counts(client).get(RAVI) == my_open_total(client, RAVI) == 2  # Converted isn't open
    assert login_as(client, RAVI).post(f"/api/leads/{b['id']}/lost", json=LOST).status_code == 200
    assert counts(client).get(RAVI) == my_open_total(client, RAVI) == 1  # Lost isn't open
    assert login_as(client, ASHA).post(f"/api/leads/{c['id']}/transfer", json={"to_user_id": PRIYA}).status_code == 200
    after = counts(client)
    assert after.get(RAVI, 0) == my_open_total(client, RAVI) == 0  # owned, not visible: the new owner counts it
    assert after.get(PRIYA) == my_open_total(client, PRIYA) == 1


def test_counts_respect_who_may_see_whose_leads(client):
    new_lead(client, owner=RAVI)
    new_lead(client, owner=PRIYA)
    assert counts(client, ASHA) == {RAVI: 1, PRIYA: 1}  # the Admin: everyone
    assert counts(client, PRIYA) == {RAVI: 1, PRIYA: 1}  # a Manager with team view
    assert counts(client, RAVI) == {RAVI: 1}  # a Salesperson: only their own (never other people's counts)


def test_counting_changes_no_records(client):
    lead = new_lead(client)
    before = login_as(client, ASHA).get(f"/api/leads/{lead['id']}").json()
    counts(client)
    after = login_as(client, ASHA).get(f"/api/leads/{lead['id']}").json()
    assert before["updated_at"] == after["updated_at"] and before["stage"] == after["stage"]
