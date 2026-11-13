"""Home: the period selector, Action Needed / Scheduled Demos, the team cards, the Admin's team picker, and which cards
each role sees. All data is made up."""
from datetime import date, datetime, timedelta

from sqlalchemy import update

from app.database import get_db
from app.main import app
from app.models import Lead, Opportunity
from conftest import login_as
from test_opportunity_duplicates import create, new_lead

PRIYA, RAVI, ASHA = 1, 2, 3  # Manager, Salesperson, Admin
HOME_CARDS = {"home_action_items", "home_meetings", "home_pipeline", "home_win_loss", "home_follow_up_radar",
              "home_scorecard", "home_recent_activity", "home_team_performance"}
TEAM_CARDS = {"home_win_loss", "home_team_performance"}


def iso(when: datetime) -> str:
    return when.replace(microsecond=0).isoformat()


def database():
    return next(app.dependency_overrides[get_db]())


def test_cards_count_the_records_created_in_the_period(client):
    new_lead(client, "mira@brightline.test")
    old = new_lead(client, "dev@harbor.test", company="Harbor Freight Labs", first="Dev", last="Rao")
    db = database()
    db.execute(update(Lead).where(Lead.id == old["id"]).values(created_at=datetime.now() - timedelta(days=100)))
    db.commit()
    create(client, name="Brightline rollout", account_name="Brightline Logistics", expected_value=5000,
           contact_last_name="Shah")

    def cards(**params):
        res = client.get("/api/home", params=params)
        assert res.status_code == 200, res.text
        return res.json()["seller_home"]

    default = cards()  # the past 7 days
    assert default["build_pipeline"]["total"] == 1 and default["period"]["end"] is None
    six_months = cards(start=iso(datetime.now() - timedelta(days=182)))
    assert six_months["build_pipeline"]["total"] == 2
    assert six_months["close_deals"]["open"] == 5000 and six_months["accounts"]["total"] == 1
    assert six_months["close_deals"]["by_currency"]["open"] == {"USD": 5000.0}
    # a custom range that ended before today's records: nothing from today
    custom = cards(start=iso(datetime.now() - timedelta(days=120)), end=iso(datetime.now() - timedelta(days=50)))
    assert custom["build_pipeline"]["total"] == 1 and custom["close_deals"]["open"] == 0
    assert custom["accounts"]["total"] == 0
    assert client.get("/api/home", params={"start": iso(datetime.now()), "end": iso(datetime.now() - timedelta(days=1))}
                      ).status_code == 400

    team = login_as(client, ASHA).get("/api/home/team-charts",
                                      params={"start": iso(datetime.now() - timedelta(days=182))}).json()
    assert team["period"]["start"] and sum(r["leads"] for r in team["lead_sources"]) == 2
    assert team["pipeline"]["open"] == 5000


def test_action_items_are_my_own_today_and_the_next_seven_days(client):
    lead = new_lead(client, "mira@brightline.test")  # its "Make first contact" task is due tomorrow
    soon = client.post("/api/tasks", json={"title": "Send proposal", "lead_id": lead["id"],
                                           "due_date": iso(datetime.now() + timedelta(days=3))})
    later = client.post("/api/tasks", json={"title": "Quarterly check-in", "lead_id": lead["id"],
                                            "due_date": iso(datetime.now() + timedelta(days=20))})
    assert soon.status_code == 201 and later.status_code == 201, (soon.text, later.text)
    home = client.get("/api/home").json()["seller_home"]
    upcoming = {t["title"] for t in home["my_tasks"]["upcoming"]}
    assert "Send proposal" in upcoming and "Quarterly check-in" not in upcoming
    assert not upcoming & {t["title"] for t in home["my_tasks"]["today"]}
    assert home["upcoming_events"] == []
    # someone else's Home does not show them, even in the Team view
    other = RAVI if lead["owner_id"] != RAVI else PRIYA
    assert login_as(client, other).get("/api/home").json()["seller_home"]["my_tasks"]["upcoming"] == []


def test_team_cards_and_my_scorecard(client):
    login_as(client, ASHA).put(f"/api/users/{RAVI}", json={"reports_to_id": PRIYA})
    login_as(client, RAVI)
    new_lead(client, "mira@brightline.test", source="Referral")
    new_lead(client, "dev@harbor.test", company="Harbor Freight Labs", first="Dev", last="Rao", source="Website")
    won = create(client, name="Won deal", account_name="Brightline Logistics", expected_value=8000,
                 contact_last_name="Shah").json()["opportunity"]
    lost = create(client, name="Lost deal", account_name="Harbor Freight Labs", expected_value=3000,
                  contact_last_name="Rao").json()["opportunity"]
    db = database()
    db.execute(update(Opportunity).where(Opportunity.id == won["id"])
               .values(stage="Won", final_value=7500, closed_at=datetime.now()))
    db.execute(update(Opportunity).where(Opportunity.id == lost["id"])
               .values(stage="Lost", lost_reason="Price", closed_at=datetime.now()))
    db.commit()

    score = client.get("/api/home").json()["seller_home"]["scorecard"]  # Ravi's own
    assert (score["won"], score["lost"], score["win_rate"]) == (1, 1, 50)
    assert score["won_values"] == {"USD": 7500.0} and score["lost_values"] == {"USD": 3000.0}
    assert score["average_deal"] == {"USD": 7500.0}

    # Recent Activity: the records changed last, newest first
    recent = client.get("/api/home").json()["seller_home"]["recent_records"]
    assert len(recent) == 6 and "Opportunity" in {r["type"] for r in recent}
    assert [r["updated_at"] for r in recent] == sorted((r["updated_at"] for r in recent), reverse=True)

    team = login_as(client, PRIYA).get("/api/home/team-charts").json()
    assert team["scope"] == "team" and team["team_of"]["id"] == PRIYA
    ravi = next(p for p in team["people"] if p["id"] == RAVI)  # Team Performance
    assert ravi["won_count"] == 1 and ravi["open_leads"] == 2
    results = team["win_loss"]  # Win/Loss Analysis
    assert (results["won"]["count"], results["lost"]["count"], results["win_rate"]) == (1, 1, 50)
    assert results["lost_reasons"] == [{"reason": "Price", "count": 1}]
    for admins_own in ("closing_soon", "lead_sources", "recent_records"):
        assert admins_own not in team


def test_admin_sees_every_record(client):
    login_as(client, ASHA).put(f"/api/users/{RAVI}", json={"reports_to_id": PRIYA})
    login_as(client, RAVI)
    new_lead(client, "mira@brightline.test", source="Referral")
    create(client, name="Soon deal", account_name="Brightline Logistics", expected_value=5000, contact_last_name="Shah",
           expected_close_date=(date.today() + timedelta(days=5)).isoformat())
    create(client, name="Later deal", account_name="Harbor Freight Labs", expected_value=7000, contact_last_name="Rao",
           expected_close_date=(date.today() + timedelta(days=200)).isoformat())
    admin = login_as(client, ASHA)
    company = admin.get("/api/home/team-charts").json()
    assert company["scope"] == "all" and {p["id"] for p in company["people"]} == {PRIYA, RAVI}
    assert {s["source"]: s["leads"] for s in company["lead_sources"]} == {"Referral": 1}
    # Closing Soon: open opportunities closing in the next 30 days, with their owner (Later deal: 200 days away)
    assert [(d["name"], d["owner_name"]) for d in company["closing_soon"]] == [("Soon deal", "Ravi Kumar")]
    assert "team_comparison" not in company and "teams" not in company  # no team picker
    # Recent Activity: every record changed last, with its owner
    assert company["recent_records"] and {r["owner_name"] for r in company["recent_records"]} == {"Ravi Kumar"}
    # Follow-up Radar (from /home): every record
    radar = admin.get("/api/home").json()["seller_home"]
    assert radar["build_pipeline"]["total"] == 1 and radar["accounts"]["total"] == 2


def test_admin_chooses_the_home_cards_for_each_role(client):
    rows = {r["key"]: r for r in login_as(client, ASHA).get("/api/permissions").json()["permissions"]}
    home_rows = {k for k, r in rows.items() if r["group"] == "Home dashboard"}
    assert home_rows == HOME_CARDS
    assert not any(rows[k]["roles"]["Salesperson"]["allowed"] for k in TEAM_CARDS)  # team cards: Managers
    assert all(rows[k]["roles"]["Salesperson"]["allowed"] for k in HOME_CARDS - TEAM_CARDS)
    assert all(rows[k]["roles"]["Manager"]["allowed"] for k in HOME_CARDS)

    res = client.put("/api/permissions", json={"role": "Salesperson", "permission": "home_recent_activity", "allowed": False})
    assert res.status_code == 200, res.text
    salesperson = set(login_as(client, RAVI).get("/api/auth/me").json()["permissions"])
    manager = set(login_as(client, PRIYA).get("/api/auth/me").json()["permissions"])
    admin = set(login_as(client, ASHA).get("/api/auth/me").json()["permissions"])
    assert "home_recent_activity" not in salesperson and "home_scorecard" in salesperson
    assert "home_recent_activity" in manager and HOME_CARDS <= admin  # the Admin always has every card
