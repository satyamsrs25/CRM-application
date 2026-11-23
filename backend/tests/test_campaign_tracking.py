"""Issue 7: open and click tracking for campaign emails sent by SalesTrack (app/tracking.py).

Off unless the Admin allows it AND the campaign asks for it; tracking addresses carry random tokens only; a click
always goes to the stored address; signals never change a lead or count as delivery; signals are kept for a limited
time. Mail is never sent: campaigns.send_one is replaced (the `sent` fixture). Users: 1 Priya (Manager), 2 Ravi
(Salesperson, the client's default), 3 Asha (Admin). All data is made up."""
import re
from datetime import timedelta

import pytest

from app import campaigns, tracking
from app.models import Campaign, CampaignEvent, CampaignLink, CampaignRecipient, Lead
from app.services import now
from conftest import login_as
from test_campaigns import db_session, lead, make, run_round, sent  # noqa: F401

PRIYA, RAVI, ASHA = 1, 2, 3
BODY = ("Hi {first_name},\n\nOur pricing: https://pricing.example.com/plans?a=1&b=2.\n"
        "Again: https://pricing.example.com/plans?a=1&b=2\n\nCall tel:+15550100 or write mailto:sales@example.com. "
        "Sign in at http://localhost:5173/#/leads/1 - {sender_name}")


def allow(client, on=True):
    res = login_as(client, ASHA).put("/api/campaigns/tracking", json={"enabled": on})
    assert res.status_code == 200, res.text
    login_as(client, RAVI)
    return res.json()


def tracked_campaign(client, n=2, **extra):
    ids = [lead(client)["id"] for _ in range(n)]
    res = make(client, ids, body=BODY, track_opens=True, track_clicks=True, **extra)
    assert res.status_code == 201, res.text
    return res.json()["id"], ids


def rows(campaign_id):
    db = db_session()
    try:
        return {r.lead_id: (r.tracking_token, r.opens_tracked, r.clicks_tracked, r.open_events, r.click_events,
                            r.first_open_at, r.last_open_at, r.status)
                for r in db.query(CampaignRecipient).filter_by(campaign_id=campaign_id)}
    finally:
        db.close()


def links_in(mail):
    return re.findall(r'href="([^"]*/api/public/t/c/[^"]+)"', mail["html"])


def pixel_in(mail):
    found = re.findall(r'<img src="([^"]*/api/public/t/o/[^"]+\.gif)"', mail["html"])
    return found[0] if found else None


def path(url):
    return "/api" + url.split("/api", 1)[1].replace("&amp;", "&")


def test_tracking_is_off_by_default_and_only_the_admin_turns_it_on(client, sent):
    assert client.get("/api/campaigns/tracking").json()["enabled"] is False
    ids = [lead(client)["id"]]
    refused = make(client, ids, body=BODY, track_opens=True)
    assert refused.status_code == 400 and "tracking is turned off" in refused.json()["detail"]
    for user in (RAVI, PRIYA):  # Salespeople and Managers can't switch it
        assert login_as(client, user).put("/api/campaigns/tracking", json={"enabled": True}).status_code == 403
    login_as(client, RAVI)
    # a campaign without tracking: no image, no tracking links, the message as before
    plain = make(client, ids, body=BODY)
    assert plain.status_code == 201 and plain.json()["track_opens"] is False
    run_round()
    mail = sent.items[-1]
    assert "/api/public/t/" not in mail["html"] + mail["body"] and "https://pricing.example.com/plans?a=1&amp;b=2" in mail["html"]
    on = allow(client)
    assert on["enabled"] is True and on["updated_by"] == "Asha Rao" and on["retention_days"] == 90
    # campaigns made before keep tracking off: nothing is switched on for them
    assert client.get(f"/api/campaigns/{plain.json()['id']}").json()["track_opens"] is False


def test_a_tracked_email_has_its_own_token_tracked_content_links_and_an_open_image(client, sent):
    allow(client)
    campaign_id, (a, b) = tracked_campaign(client)
    run_round()
    first, second = sent.items[-2:]
    state = rows(campaign_id)
    token_a, token_b = state[a][0], state[b][0]
    assert token_a != token_b and len(token_a) == 32 and state[a][1:3] == (True, True)
    db = db_session()
    try:
        [link] = db.query(CampaignLink).filter_by(campaign_id=campaign_id).all()
        recipient_ids = [r.id for r in db.query(CampaignRecipient).filter_by(campaign_id=campaign_id)]
    finally:
        db.close()
    record_ids = {str(i) for i in (a, b, campaign_id, link.id, *recipient_ids)}
    assert len(link.link_key) >= 12 and link.link_key not in record_ids
    for mail, token in ((first, token_a), (second, token_b)):
        urls = links_in(mail)
        # the same address twice: one link (the same tracking address), shown as the original address
        assert len(urls) == 2 and urls[0] == urls[1] and f"/t/c/{token}/" in urls[0]
        assert ">https://pricing.example.com/plans?a=1&amp;b=2</a>" in mail["html"]
        assert pixel_in(mail).endswith(f"/api/public/t/o/{token}.gif")
        # no email address or record id in a tracking address: only the recipient's random token and the link's
        # random key. Ids are compared with whole path parts: a random token or key may happen to contain a digit.
        for url in urls + [pixel_in(mail)]:
            parts = url.split("/api/public/t/", 1)[1].split("/")
            assert "@" not in url and "?" not in url
            assert parts in (["c", token, link.link_key], ["o", f"{token}.gif"])
            assert not record_ids & set(parts) and not record_ids & {parts[-1].removesuffix(".gif")}
        # the text version: the content link becomes the tracking address
        assert f"/t/c/{token}/" in mail["body"] and "https://pricing.example.com" not in mail["body"].split("--")[0]
        # never tracked: tel:, mailto:, the app's own links, Unsubscribe / Subscribe
        assert "tel:+15550100" in mail["body"] and "mailto:sales@example.com" in mail["body"]
        assert "http://localhost:5173/#/leads/1" in mail["body"]
        assert "/api/public/unsubscribe?t=" in mail["html"] and "/api/public/t/c/" not in mail["unsubscribe"]
    db = db_session()
    try:
        assert [link.url for link in db.query(CampaignLink).filter_by(campaign_id=campaign_id)] == \
            ["https://pricing.example.com/plans?a=1&b=2"]
    finally:
        db.close()


def test_open_signals_count_per_recipient_and_wrong_or_head_requests_record_nothing(client, sent):
    allow(client)
    campaign_id, (a, b) = tracked_campaign(client)
    run_round()
    image = path(pixel_in(sent.items[-2]))
    got = client.get(image)
    assert got.status_code == 200 and got.headers["content-type"] == "image/gif" and "no-store" in got.headers["cache-control"]
    client.get(image)
    client.head(image)  # HEAD only checks the image: no signal
    for wrong in ("/api/public/t/o/short.gif", "/api/public/t/o/" + "x" * 32 + ".gif"):
        assert client.get(wrong).status_code == 200  # the same image: a wrong token tells nothing
    state = rows(campaign_id)
    assert state[a][3] == 2 and state[b][3] == 0  # recipient isolation
    assert state[a][5] is not None and state[a][5] <= state[a][6]
    assert state[a][7] == "Sent"  # engagement never changes the sending status (no "Delivered")


def test_a_click_goes_to_the_stored_address_and_is_never_used_up(client, sent):
    allow(client)
    campaign_id, (a, b) = tracked_campaign(client)
    run_round()
    link = path(links_in(sent.items[-2])[0])
    for _ in range(3):  # scanners may open it first: it keeps working
        res = client.get(link, follow_redirects=False)
        assert res.status_code == 302 and res.headers["location"] == "https://pricing.example.com/plans?a=1&b=2"
    # an address in the request is ignored: no open redirect
    res = client.get(link + "?url=https://evil.example/&next=https://evil.example/", follow_redirects=False)
    assert res.headers["location"] == "https://pricing.example.com/plans?a=1&b=2"
    assert client.head(link, follow_redirects=False).status_code == 302
    assert rows(campaign_id)[a][4] == 4 and rows(campaign_id)[b][4] == 0  # 4 GETs, the HEAD not counted
    # someone else's token with this link: still goes there, but no signal for anyone
    key = link.rsplit("/", 1)[1]
    other = client.get(f"/api/public/t/c/{'y' * 32}/{key}", follow_redirects=False)
    assert other.status_code == 302 and rows(campaign_id)[a][4] == 4
    # a made-up or malformed key: a "doesn't work" page, never a redirect
    for bad in (f"/api/public/t/c/{'y' * 32}/{'k' * 12}", "/api/public/t/c/x/y"):
        res = client.get(bad, follow_redirects=False)
        assert res.status_code == 404 and "location" not in res.headers and "doesn't work" in res.text
    # an address smuggled into the path doesn't even reach the link
    res = client.get(f"/api/public/t/c/{'y' * 32}/%2F%2Fevil.example", follow_redirects=False)
    assert res.status_code == 404 and "location" not in res.headers


def test_turning_tracking_off_stops_signals_and_new_tracking_but_links_still_work(client, sent):
    allow(client)
    campaign_id, (a, _) = tracked_campaign(client)
    run_round()
    link, image = path(links_in(sent.items[-2])[0]), path(pixel_in(sent.items[-2]))
    allow(client, False)
    assert client.get(link, follow_redirects=False).headers["location"].startswith("https://pricing.example.com")
    client.get(image)
    assert rows(campaign_id)[a][3:5] == (0, 0)
    # emails sent while it's off carry nothing (even for a campaign that asked for tracking)
    db = db_session()
    try:
        db.query(CampaignRecipient).filter_by(campaign_id=campaign_id).update({"status": "Queued", "sent_at": None})
        db.query(Campaign).filter_by(id=campaign_id).update({"status": "Sending", "finished_at": None})
        db.commit()
    finally:
        db.close()
    before = len(sent.items)
    run_round()
    assert len(sent.items) == before + 2
    assert all("/api/public/t/" not in m["html"] + m["body"] for m in sent.items[before:])
    assert rows(campaign_id)[a][1:3] == (False, False)  # what these emails carried


def test_a_click_still_goes_through_when_its_signal_cant_be_saved(client, sent, monkeypatch):
    allow(client)
    campaign_id, (a, _) = tracked_campaign(client)
    run_round()
    link = path(links_in(sent.items[-2])[0])

    def broken(*args, **kwargs):
        raise RuntimeError("synthetic database failure")
    monkeypatch.setattr(tracking, "record", broken)
    res = client.get(link, follow_redirects=False)
    assert res.status_code == 302 and res.headers["location"].startswith("https://pricing.example.com")
    assert client.get(path(pixel_in(sent.items[-2]))).status_code == 200


def test_a_retried_email_keeps_its_token_and_links(client, sent):
    allow(client)
    ids = [lead(client)["id"]]
    res = make(client, ids, body=BODY, track_opens=True, track_clicks=True)
    campaign_id = res.json()["id"]
    address = next(r.email for r in db_session().query(CampaignRecipient).filter_by(campaign_id=campaign_id))
    sent.answers[address] = campaigns.Result("retry", "421 try later")
    run_round()
    first = sent.items[-1]
    token = rows(campaign_id)[ids[0]][0]
    db = db_session()
    try:
        db.query(CampaignRecipient).filter_by(campaign_id=campaign_id).update({"next_attempt_at": now() - timedelta(minutes=1)})
        db.commit()
    finally:
        db.close()
    del sent.answers[address]
    run_round()
    second = sent.items[-1]
    assert rows(campaign_id)[ids[0]][0] == token and links_in(first) == links_in(second)
    assert pixel_in(first) == pixel_in(second) and rows(campaign_id)[ids[0]][7] == "Sent"
    assert db_session().query(CampaignLink).filter_by(campaign_id=campaign_id).count() == 1


def test_the_report_separates_unique_recipients_repeated_signals_and_sending(client, sent):
    allow(client)
    campaign_id, (a, b, _) = tracked_campaign(client, n=3)
    run_round()
    mails = sent.items[-3:]
    client.get(path(pixel_in(mails[0])))
    client.get(path(pixel_in(mails[0])))
    client.get(path(links_in(mails[0])[0]), follow_redirects=False)
    report = client.get(f"/api/campaigns/{campaign_id}").json()
    t = report["tracking"]
    assert (t["sent"], t["sent_with_open_tracking"], t["sent_with_click_tracking"]) == (3, 3, 3)
    assert (t["recipients_with_open_signal"], t["open_signals"], t["open_signal_rate_pct"]) == (1, 2, 33.3)
    assert (t["recipients_with_click_signal"], t["click_signals"], t["click_signal_rate_pct"]) == (1, 1, 33.3)
    assert t["links"] == [{"url": "https://pricing.example.com/plans?a=1&b=2", "clicks": 1, "recipients": 1}]
    assert report["counts"]["Sent"] == 3 and "Delivered" not in str(report)
    first = next(r for r in report["recipients"]["items"] if r["lead_id"] == a)["engagement"]
    assert first["open_signals"] == 2 and first["first_open_at"].endswith("Z") and first["links"][0]["clicks"] == 1
    none = next(r for r in report["recipients"]["items"] if r["lead_id"] == b)["engagement"]
    assert (none["open_signals"], none["first_open_at"], none["links"]) == (0, None, [])
    # the report follows the campaign's own access: the Manager (team records) sees it; a Salesperson who didn't
    # make it doesn't
    assert login_as(client, PRIYA).get(f"/api/campaigns/{campaign_id}").json()["tracking"]["open_signals"] == 2
    from test_unassigned_pool import add_user
    other = add_user("Sam Roy", "sam@crm.test", "Salesperson")
    assert login_as(client, other).get(f"/api/campaigns/{campaign_id}").status_code == 404
    assert login_as(client, other).put("/api/campaigns/tracking", json={"enabled": False}).status_code == 403


def test_nothing_sent_yet_gives_no_rate_and_a_campaign_without_tracking_has_no_report(client, sent):
    allow(client)
    campaign_id, _ = tracked_campaign(client)  # not sent yet
    t = client.get(f"/api/campaigns/{campaign_id}").json()["tracking"]
    assert (t["sent"], t["open_signal_rate_pct"], t["click_signal_rate_pct"]) == (0, None, None)
    plain = make(client, [lead(client)["id"]], body=BODY).json()
    assert client.get(f"/api/campaigns/{plain['id']}").json()["tracking"] is None


def test_signals_are_cautiously_hinted_kept_for_a_limited_time_and_never_change_a_lead(client, sent, monkeypatch):
    allow(client)
    campaign_id, (a, _) = tracked_campaign(client)
    run_round()
    db = db_session()
    try:
        before = db.get(Lead, a)
        snapshot = (before.owner_id, before.updated_at, before.stage, before.unsubscribed_at)
    finally:
        db.close()
    image, link = path(pixel_in(sent.items[-2])), path(links_in(sent.items[-2])[0])
    client.get(image, headers={"User-Agent": "python-requests/2.31"})
    client.get(link, headers={"User-Agent": ""}, follow_redirects=False)
    db = db_session()
    try:
        hints = sorted(e.automated_hint for e in db.query(CampaignEvent).filter_by(campaign_id=campaign_id))
        assert hints == ["looks like a scanner or a program", "no browser details"]
        after = db.get(Lead, a)
        assert (after.owner_id, after.updated_at, after.stage, after.unsubscribed_at) == snapshot  # nothing changed
    finally:
        db.close()
    # a person's browser well after sending: no hint (which doesn't prove a person either)
    sent_at = now() - timedelta(hours=1)
    assert tracking.automated_hint("Mozilla/5.0 (Windows NT 10.0)", sent_at, tracking.utcnow()) is None
    assert tracking.automated_hint("Mozilla/5.0", now(), tracking.utcnow()) == "seconds after sending"
    # signals older than the retention period are deleted; the per-recipient totals and the link stay
    monkeypatch.setenv("TRACKING_RETENTION_DAYS", "30")
    db = db_session()
    try:
        db.query(CampaignEvent).filter_by(campaign_id=campaign_id).update(
            {"occurred_at": tracking.utcnow() - timedelta(days=31)})
        db.commit()
        assert tracking.purge(db, force=True) == 2
        assert db.query(CampaignEvent).filter_by(campaign_id=campaign_id).count() == 0
    finally:
        db.close()
    assert rows(campaign_id)[a][3:5] == (1, 1)
    assert client.get(link, follow_redirects=False).status_code == 302
    assert tracking.retention_days() == 30
    monkeypatch.setenv("TRACKING_RETENTION_DAYS", "100000")
    assert tracking.retention_days() == 730
