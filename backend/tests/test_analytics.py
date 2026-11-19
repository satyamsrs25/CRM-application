"""Home > Analytics: build-your-own charts on each user's board, who sees which board, and reports sent up the line.
All data is made up. Users: 1 Priya (Manager), 2 Ravi (Salesperson), 3 Asha (Admin)."""
import io
from datetime import date, datetime, timedelta

from openpyxl import load_workbook
from sqlalchemy import select, update

from app.database import get_db
from app.main import app
from app.models import Lead, Notification, Opportunity
from conftest import login_as
from test_opportunity_duplicates import create, new_lead

PRIYA, RAVI, ASHA = 1, 2, 3
PASSWORD = "Synthetic@2026"


def database():
    return next(app.dependency_overrides[get_db]())


def chart(**changes):
    return {"title": "Leads by source", "metric": "leads_created", "group_by": "source", "chart_type": "column",
            "period": "30d", **changes}


def team(client):
    """Ravi reports to Priya, and Neha (another Salesperson) to no one."""
    login_as(client, ASHA).put(f"/api/users/{RAVI}", json={"reports_to_id": PRIYA})
    res = client.post("/api/users", json={"full_name": "Neha Iyer", "email": "neha@crm.test", "password": PASSWORD,
                                          "role": "Salesperson"})
    return res.json()["id"]


def test_the_builder_refuses_charts_that_cant_be_drawn(client):
    login_as(client, RAVI)
    for changes, message in ((dict(chart_type="line"), "Line chart shows a trend"),
                             (dict(group_by="none"), "Number chart for one total"),
                             (dict(chart_type="number"), "choose Total only"),
                             (dict(chart_type="donut", group_by="month"), "parts of a whole"),
                             (dict(metric="deals_won", group_by="source"), "can't be split by lead source"),
                             (dict(period="custom"), "needs a start and an end"),
                             (dict(title="  "), "Give the chart a title")):
        res = client.post("/api/analytics/charts", json=chart(**changes))
        assert res.status_code == 422 and message in res.text, (changes, res.text)
    options = client.get("/api/analytics/options").json()
    assert {m["key"] for m in options["metrics"]} >= {"leads_created", "revenue_won", "win_rate"}


def test_a_salespersons_charts_count_their_own_records(client):
    team(client)
    login_as(client, RAVI)
    new_lead(client, "mira@brightline.test", source="Referral")
    new_lead(client, "dev@harbor.test", company="Harbor Freight Labs", first="Dev", last="Rao", source="Website")
    new_lead(client, "om@harbor.test", company="Harbor Freight Labs", first="Om", last="Iyer", source="Website")
    login_as(client, PRIYA)
    new_lead(client, "kai@north.test", company="North Synthetic", first="Kai", last="Sen", source="Referral")

    login_as(client, RAVI)
    made = client.post("/api/analytics/charts", json=chart())
    assert made.status_code == 201, made.text
    points = {p["label"]: p["value"] for p in made.json()["points"]}
    assert points == {"Website": 2, "Referral": 1} and made.json()["total"] == 3  # not Priya's lead
    trend = client.post("/api/analytics/charts", json=chart(title="Leads per week", group_by="week", chart_type="line")).json()
    assert len(trend["points"]) >= 5 and sum(p["value"] for p in trend["points"]) == 3  # empty weeks shown as 0
    # the Manager's board counts the team: Priya's and Ravi's leads
    login_as(client, PRIYA)
    mine = client.post("/api/analytics/charts", json=chart(title="Team leads", group_by="none", chart_type="number")).json()
    assert mine["total"] == 4
    board = client.get(f"/api/analytics/boards/{PRIYA}").json()
    assert board["scope"] == "Priya Sharma's team (2 people)" and board["can_edit"]


def test_money_and_win_rate(client):
    login_as(client, RAVI)
    won = create(client, name="Won deal", account_name="Brightline Logistics", expected_value=8000,
                 contact_last_name="Shah").json()["opportunity"]
    lost = create(client, name="Lost deal", account_name="Harbor Freight Labs", expected_value=3000,
                  contact_last_name="Rao").json()["opportunity"]
    db = database()
    db.execute(update(Opportunity).where(Opportunity.id == won["id"])
               .values(stage="Won", final_value=7500, closed_at=datetime.now() - timedelta(hours=1)))
    db.execute(update(Opportunity).where(Opportunity.id == lost["id"])
               .values(stage="Lost", lost_reason="Price", closed_at=datetime.now() - timedelta(hours=1)))
    db.commit()
    revenue = client.post("/api/analytics/charts/preview", json=chart(metric="revenue_won", group_by="none",
                                                                       chart_type="number")).json()
    assert revenue["total"] == 7500 and revenue["unit"] == "money" and revenue["currency"] == "USD"
    assert client.post("/api/analytics/charts/preview", json=chart(metric="revenue_won", group_by="none",
                                                                  chart_type="number", currency="INR")).json()["total"] == 0
    rate = client.post("/api/analytics/charts/preview", json=chart(metric="win_rate", group_by="none",
                                                                    chart_type="number")).json()
    assert rate["total"] == 50.0 and rate["unit"] == "percent"
    reasons = client.post("/api/analytics/charts/preview", json=chart(metric="deals_lost", group_by="lost_reason")).json()
    assert reasons["points"] == [{"label": "Price", "value": 1, "key": {"lost_reason": "Price"}}]


def test_who_sees_whose_board(client):
    neha = team(client)
    login_as(client, RAVI)
    client.post("/api/analytics/charts", json=chart())
    # Ravi's Manager and the Admin see his board; another Salesperson doesn't
    assert login_as(client, PRIYA).get(f"/api/analytics/boards/{RAVI}").json()["charts"][0]["title"] == "Leads by source"
    assert not client.get(f"/api/analytics/boards/{RAVI}").json()["can_edit"]
    assert login_as(client, ASHA).get(f"/api/analytics/boards/{RAVI}").status_code == 200
    assert login_as(client, neha).get(f"/api/analytics/boards/{RAVI}").status_code == 404
    # and a Salesperson can't open the Manager's board
    assert login_as(client, RAVI).get(f"/api/analytics/boards/{PRIYA}").status_code == 404
    assert [p["id"] for p in login_as(client, PRIYA).get("/api/analytics/people").json()] == [PRIYA, RAVI]
    admin_people = login_as(client, ASHA).get("/api/analytics/people").json()
    assert admin_people[0]["id"] == ASHA and admin_people[1]["role"] == "Manager"


def test_only_the_owner_changes_a_chart(client):
    team(client)
    made = login_as(client, RAVI).post("/api/analytics/charts", json=chart()).json()
    assert login_as(client, PRIYA).put(f"/api/analytics/charts/{made['id']}", json=chart(title="Hacked")).status_code == 404
    assert login_as(client, RAVI).put(f"/api/analytics/charts/{made['id']}",
                                      json=chart(title="By source", chart_type="donut")).json()["chart_type"] == "donut"
    second = client.post("/api/analytics/charts", json=chart(title="Second")).json()
    assert client.put("/api/analytics/charts-order", json={"ids": [second["id"], made["id"]]}).status_code == 200
    assert [c["title"] for c in client.get(f"/api/analytics/boards/{RAVI}").json()["charts"]] == ["Second", "By source"]
    assert client.delete(f"/api/analytics/charts/{made['id']}").json() == {"deleted": made["id"]}


def test_suggested_charts_on_an_empty_board(client):
    board = login_as(client, RAVI).post("/api/analytics/charts/suggested")
    assert board.status_code == 201 and len(board.json()["charts"]) == 6
    by_stage = {c["title"]: c for c in board.json()["charts"]}
    assert by_stage["Leads by stage"]["chart_type"] == "donut" and by_stage["Leads by stage"]["group_by"] == "stage"
    assert by_stage["Opportunities by stage"]["metric"] == "opportunities_created"
    assert client.post("/api/analytics/charts/suggested").status_code == 400


def test_reports_go_up_the_line_and_are_reviewed(client):
    neha = team(client)
    login_as(client, RAVI)
    assert client.post("/api/analytics/reports", json={"note": "x"}).status_code == 400  # no charts yet
    client.post("/api/analytics/charts", json=chart())
    sent = client.post("/api/analytics/reports", json={"note": "Good week: 3 new referrals."})
    assert sent.status_code == 201, sent.text
    report = sent.json()
    assert report["sent_to"] == "Priya Sharma, Asha Rao" and report["charts"][0]["title"] == "Leads by source"
    db = database()
    titles = {(n.user_id, n.title) for n in db.scalars(select(Notification))}
    assert (PRIYA, "Analytics report received") in titles and (ASHA, "Analytics report received") in titles
    assert login_as(client, neha).get(f"/api/analytics/reports/{report['id']}").status_code == 404
    # the Manager reviews it; the author is told
    login_as(client, PRIYA)
    inbox = client.get("/api/analytics/reports").json()
    assert [r["id"] for r in inbox] == [report["id"]] and inbox[0]["can_review"]
    done = client.post(f"/api/analytics/reports/{report['id']}/review", json={"comment": "Nice work"})
    assert done.status_code == 200 and done.json()["reviewed_by_name"] == "Priya Sharma"
    assert client.post(f"/api/analytics/reports/{report['id']}/review", json={}).status_code == 400
    assert (RAVI, "Analytics report reviewed") in {(n.user_id, n.title) for n in database().scalars(select(Notification))}
    assert login_as(client, RAVI).get("/api/analytics/reports?box=sent").json()[0]["review_comment"] == "Nice work"
    # a Manager's report goes to the Admin; the Admin has no one to send to
    login_as(client, PRIYA).post("/api/analytics/charts", json=chart())
    assert client.post("/api/analytics/reports", json={}).json()["sent_to"] == "Asha Rao"
    login_as(client, ASHA).post("/api/analytics/charts", json=chart())
    assert client.post("/api/analytics/reports", json={}).status_code == 400


def test_board_filters_and_click_to_filter(client):
    """Period / Owner filters and a clicked bar, slice or point filter every chart that can take them."""
    team(client)
    login_as(client, RAVI)
    new_lead(client, "mira@brightline.test", source="Referral")
    new_lead(client, "dev@harbor.test", company="Harbor Freight Labs", first="Dev", last="Rao", source="Website")
    login_as(client, PRIYA)
    new_lead(client, "kai@north.test", company="North Synthetic", first="Kai", last="Sen", source="Referral")
    by_source = client.post("/api/analytics/charts", json=chart(period="90d")).json()
    client.post("/api/analytics/charts", json=chart(title="Deals", metric="opportunities_created", group_by="stage"))
    weekly = client.post("/api/analytics/charts", json=chart(title="Weekly", group_by="week", chart_type="line")).json()
    assert {p["label"]: p["key"] for p in by_source["points"]}["Referral"] == {"source": "Referral"}
    week = next(p for p in weekly["points"] if p["value"])
    assert set(week["key"]) == {"from_date", "to_date"}
    board = client.get(f"/api/analytics/boards/{PRIYA}").json()
    assert [p["full_name"] for p in board["people"]] == ["Priya Sharma", "Ravi Kumar"]
    # a click on "Referral": lead charts count Referral leads only; the opportunity chart can't take it and says so
    board = client.get(f"/api/analytics/boards/{PRIYA}", params={"source": "Referral"}).json()
    by_source, deals, weekly = board["charts"]
    assert by_source["total"] == 3  # the clicked chart keeps all its bars (Referral is highlighted in the browser)
    assert weekly["total"] == 2 and weekly["not_filtered_by"] == [] and board["filters"] == {"source": "Referral"}
    assert deals["not_filtered_by"] == ["Lead source"]
    # Owner: one person in the board's scope (not someone outside it)
    board = client.get(f"/api/analytics/boards/{PRIYA}", params={"owner_id": RAVI}).json()
    assert board["charts"][0]["total"] == 2 and board["charts"][2]["total"] == 2
    assert client.get(f"/api/analytics/boards/{PRIYA}", params={"owner_id": ASHA}).status_code == 400
    # a clicked week, and the Period filter replacing each chart's own period
    board = client.get(f"/api/analytics/boards/{PRIYA}", params=week["key"]).json()
    assert board["charts"][0]["total"] == 3 and board["charts"][0]["period_label"].startswith(week["key"]["from_date"][8:])
    assert board["charts"][2]["period_label"] == "Past 1 month"  # the clicked weekly chart keeps its own weeks
    assert client.get(f"/api/analytics/boards/{PRIYA}", params={"period": "7d"}).json()["charts"][0]["period_label"] == "Past 1 week"
    assert client.get(f"/api/analytics/boards/{PRIYA}", params={"period": "custom"}).status_code == 422


def test_explore_records_and_widths(client):
    login_as(client, RAVI)
    lead = new_lead(client, "mira@brightline.test", source="Referral")
    new_lead(client, "dev@harbor.test", company="Harbor Freight Labs", first="Dev", last="Rao", source="Website")
    found = client.post("/api/analytics/records", json={**chart(), "filters": {"source": "Referral"}}).json()
    assert found["total"] == 1 and found["columns"][:3] == ["Name", "Company", "Source"]
    assert found["rows"][0]["link"] == f"#/leads/{lead['id']}" and found["rows"][0]["cells"][2] == "Referral"
    explored = client.post("/api/analytics/charts/preview", json={**chart(group_by="none", chart_type="number"),
                                                                    "filters": {"source": "Website"}}).json()
    assert explored["total"] == 1
    # widths: by chart type unless chosen
    assert client.post("/api/analytics/charts", json=chart(group_by="none", chart_type="number")).json()["width"] == "quarter"
    assert client.post("/api/analytics/charts", json=chart(width="full")).json()["width"] == "full"
    assert client.post("/api/analytics/charts", json=chart(width="huge")).status_code == 422


def test_active_leads_and_stage_filters(client):
    """Active leads / open opportunities are counted as they are now (any period), split by stage; a clicked stage
    narrows the charts that can take it."""
    login_as(client, RAVI)
    nurtured = new_lead(client, "mira@brightline.test", source="Referral")
    new_lead(client, "dev@harbor.test", company="Harbor Freight Labs", first="Dev", last="Rao", source="Website")
    db = database()
    lead = db.get(Lead, nurtured["id"])
    lead.stage, lead.created_at = "Nurturing", datetime.now() - timedelta(days=400)  # older than any period
    db.commit()
    active = client.post("/api/analytics/charts", json=chart(title="Active", metric="active_leads", group_by="stage")).json()
    assert active["period_label"] == "As of now" and active["total"] == 2
    assert {p["label"]: p["value"] for p in active["points"]} == {"New": 1, "Nurturing": 1}
    assert {p["label"]: p["key"] for p in active["points"]}["Nurturing"] == {"lead_stage": "Nurturing"}
    client.post("/api/analytics/charts", json=chart(title="Open deals", metric="open_opportunities", group_by="stage"))
    board = client.get(f"/api/analytics/boards/{RAVI}", params={"period": "7d", "lead_stage": "Nurturing"}).json()
    active, deals = board["charts"]
    assert active["total"] == 2  # the stage chart keeps all its bars
    assert deals["total"] == 0 and deals["not_filtered_by"] == ["Lead stage"]
    assert client.post("/api/analytics/charts", json=chart(metric="active_leads", group_by="week", chart_type="line")).status_code == 422


def test_board_period_choices(client):
    login_as(client, RAVI)
    new_lead(client, "mira@brightline.test", source="Referral")
    client.post("/api/analytics/charts", json=chart(group_by="none", chart_type="number"))
    labels = {k: client.get(f"/api/analytics/boards/{RAVI}", params={"period": k}).json()["charts"][0]
              for k in ("7d", "30d", "6m", "12m")}
    assert [c["period_label"] for c in labels.values()] == ["Past 1 week", "Past 1 month", "Past 6 months", "Past 1 year"]
    assert all(c["total"] == 1 for c in labels.values())
    today = date.today()
    custom = client.get(f"/api/analytics/boards/{RAVI}", params={"period": "custom", "start_date": (today - timedelta(days=3)).isoformat(),
                                                                "end_date": today.isoformat()}).json()["charts"][0]
    assert custom["total"] == 1 and custom["period_label"].endswith(f"{today:%d %b %Y}")
    gone = client.get(f"/api/analytics/boards/{RAVI}", params={"period": "custom", "start_date": "2020-01-01", "end_date": "2020-02-01"})
    assert gone.json()["charts"][0]["total"] == 0
    assert client.get(f"/api/analytics/boards/{RAVI}", params={"period": "custom", "start_date": "2020-02-01",
                                                               "end_date": "2020-01-01"}).status_code == 422
    assert [p["key"] for p in client.get("/api/analytics/options").json()["periods"]] == ["7d", "30d", "custom"]
    # the Dashboard's picker sends local date-times: [start, end), shown with the times
    timed = client.get(f"/api/analytics/boards/{RAVI}", params={"period": "custom", "start_date": "2020-01-01T09:00",
                                                               "end_date": "2020-02-01T18:30"}).json()["charts"][0]
    assert timed["period_label"] == "01 Jan 2020 09:00 – 01 Feb 2020 18:30"
    assert client.get(f"/api/analytics/boards/{RAVI}", params={"period": "custom", "start_date": "2020-01-01T09:00",
                                                               "end_date": "2020-01-01T09:00"}).status_code == 422


def test_share_a_chart_as_excel_and_send_reports_to_people_picked(client):
    neha = team(client)
    login_as(client, RAVI)
    new_lead(client, "mira@brightline.test", source="Referral")
    made = client.post("/api/analytics/charts", json=chart()).json()
    choices = client.get("/api/analytics/recipients").json()
    assert [(c["full_name"], c["picked"]) for c in choices] == [("Priya Sharma", True), ("Asha Rao", True)]
    # a Salesperson can't send to another Salesperson
    assert client.post("/api/analytics/reports", json={"recipient_ids": [neha], "chart_id": made["id"]}).status_code == 400
    shared = client.post("/api/analytics/reports", json={"recipient_ids": [ASHA], "chart_id": made["id"], "filters": {"period": "7d"}})
    assert shared.status_code == 201, shared.text
    shared = shared.json()
    assert shared["kind"] == "chart" and shared["sent_to"] == "Asha Rao" and shared["title"] == "Leads by source"
    assert shared["charts"][0]["period_label"] == "Past 1 week" and len(shared["charts"]) == 1
    note = database().scalars(select(Notification).where(Notification.user_id == ASHA)).all()[-1]
    assert note.title == "Analytics chart shared" and note.link == f"/analytics?report={shared['id']}"
    assert not database().scalars(select(Notification).where(Notification.user_id == PRIYA,
                                                             Notification.title == "Analytics chart shared")).all()
    # the Admin it went to sees it, can review it and download it; the Manager it didn't go to has no review
    login_as(client, ASHA)
    inbox = client.get("/api/analytics/reports").json()
    assert inbox[0]["id"] == shared["id"] and inbox[0]["kind"] == "chart" and inbox[0]["can_review"]
    book = load_workbook(io.BytesIO(client.get(f"/api/analytics/reports/{shared['id']}/excel").content))
    assert book.sheetnames == ["Leads by source"] and book.active["A6"].value == "Referral" and book.active["B6"].value == 1
    login_as(client, PRIYA)
    assert shared["id"] not in [r["id"] for r in client.get("/api/analytics/reports").json()]
    assert client.get(f"/api/analytics/reports/{shared['id']}").json()["can_review"] is False  # Ravi's Manager can still open it
    # the Admin sends a report to Managers (and other Admins), never to a Salesperson
    login_as(client, ASHA).post("/api/analytics/charts", json=chart())
    assert [c["full_name"] for c in client.get("/api/analytics/recipients").json()] == ["Priya Sharma"]
    assert client.post("/api/analytics/reports", json={"recipient_ids": [RAVI]}).status_code == 400
    sent = client.post("/api/analytics/reports", json={"recipient_ids": [PRIYA]}).json()
    assert sent["kind"] == "board" and sent["sent_to"] == "Priya Sharma"
    assert sent["id"] in [r["id"] for r in login_as(client, PRIYA).get("/api/analytics/reports").json()]
    assert client.get(f"/api/analytics/reports/{sent['id']}").status_code == 200


def test_excel_downloads_a_sheet_per_chart(client):
    neha = team(client)
    login_as(client, RAVI)
    new_lead(client, "mira@brightline.test", source="Referral")
    first = client.post("/api/analytics/charts", json=chart()).json()
    client.post("/api/analytics/charts", json=chart(title="Total", group_by="none", chart_type="number"))
    client.post("/api/analytics/charts", json=chart(title="Total", metric="win_rate", group_by="none", chart_type="number"))
    whole = client.get(f"/api/analytics/boards/{RAVI}/excel", params={"period": "7d"})
    assert whole.status_code == 200 and whole.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert 'filename="Ravi-Kumar-analytics' in whole.headers["content-disposition"]
    book = load_workbook(io.BytesIO(whole.content))
    assert book.sheetnames == ["Leads by source", "Total", "Total (2)"]
    assert book["Leads by source"]["A3"].value == "Period: Past 1 week" and book["Total"]["B6"].value == 1
    one = load_workbook(io.BytesIO(client.get(f"/api/analytics/boards/{RAVI}/excel", params={"chart_id": first["id"]}).content))
    assert one.sheetnames == ["Leads by source"]
    # the Manager can download their Salesperson's board; someone else can't
    assert login_as(client, PRIYA).get(f"/api/analytics/boards/{RAVI}/excel").status_code == 200
    assert login_as(client, neha).get(f"/api/analytics/boards/{RAVI}/excel").status_code == 404
