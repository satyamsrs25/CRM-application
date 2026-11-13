"""Amounts carry their own currency (USD, INR, EUR, CAD, AUD, AED): chosen on the lead (turnover) and the opportunity
(amount and final amount), kept on conversion, and never added across currencies on Home. All data is made up."""
from conftest import login_as
from test_opportunity_duplicates import PRIYA, convert, create, new_lead


def test_lead_turnover_currency_defaults_to_usd_and_can_be_changed(client):
    lead = new_lead(client, "mira@brightline.test", annual_revenue=2500000)
    assert lead["currency"] == "USD"
    res = client.put(f"/api/leads/{lead['id']}", json={"currency": "INR"})
    assert res.status_code == 200, res.text
    assert res.json()["currency"] == "INR"
    # sending no currency (or null) leaves it as it is
    assert client.put(f"/api/leads/{lead['id']}", json={"currency": None}).json()["currency"] == "INR"


def test_only_the_listed_currencies_are_accepted(client):
    res = client.post("/api/opportunities", json={"name": "Deal", "account_name": "Brightline Logistics",
                                                  "contact_last_name": "Shah", "currency": "GBP", "note": "Synthetic note",
                                                  "task": {"title": "Call", "due_date": "2030-01-15T10:00:00"}})
    assert res.status_code == 422


def test_conversion_keeps_the_lead_currency_unless_another_is_chosen(client):
    lead = new_lead(client, "mira@brightline.test", currency="EUR")
    opp = convert(client, lead["id"], expected_value=1000).json()["opportunity"]
    assert opp["currency"] == "EUR"
    assert client.get(f"/api/accounts/{opp['account_id']}").json()["currency"] == "EUR"
    other = new_lead(client, "dev@harbor.test", company="Harbor Freight Labs", first="Dev", last="Rao")
    opp2 = convert(client, other["id"], expected_value=500, currency="AED").json()["opportunity"]
    assert opp2["currency"] == "AED"


def test_opportunity_currency_is_saved_and_editable(client):
    opp = create(client, name="Brightline rollout", account_name="Brightline Logistics", expected_value=5000,
                 currency="CAD", contact_last_name="Shah").json()["opportunity"]
    assert opp["currency"] == "CAD"
    res = client.put(f"/api/opportunities/{opp['id']}", json={"currency": "AUD", "expected_value": 7000})
    assert res.status_code == 200, res.text
    assert (res.json()["currency"], res.json()["expected_value"]) == ("AUD", 7000)


def test_home_totals_are_split_by_currency(client):
    create(client, name="Deal USD", account_name="Brightline Logistics", expected_value=1000, currency="USD",
           contact_last_name="Shah", expected_close_date=None)
    create(client, name="Deal INR", account_name="Harbor Freight Labs", expected_value=50000, currency="INR",
           contact_last_name="Rao")
    home = client.get("/api/home").json()["seller_home"]
    assert home["close_deals"]["by_currency"]["open"] == {"USD": 1000.0, "INR": 50000.0}
    charts = login_as(client, PRIYA).get("/api/home/team-charts").json()
    assert charts["pipeline"]["by_currency"]["open"] == {"USD": 1000.0, "INR": 50000.0}
