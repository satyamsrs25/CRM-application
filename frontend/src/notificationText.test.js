import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { notificationTime, notificationTimeFull, shortNotification } from "./notificationText.js";

const APPROVAL = [
  "Vikram Sake approved your request for a lead from the Unassigned Pool.",
  "Lead: Sadanand Yerule",
  "Company: Synthetic Pharma Ltd",
  "Email: sadanand@synthetic-pharma.example",
  "Assigned by: Vikram Sake",
  "",
  "Stage: New (continue from here; the full history is on the record).",
  "Last note: Uploaded from synthetic.csv",
  "No open tasks: add the next follow-up.",
  "Note: Request approved by Vikram Sake. Reason: abc",
].join("\n");

test("Bell: a long assignment notification is cut to what it is about", () => {
  assert.equal(
    shortNotification(APPROVAL),
    "Vikram Sake approved your request for a lead from the Unassigned Pool.\nLead: Sadanand Yerule · Synthetic Pharma Ltd",
  );
  // a first line that already names the record stays alone
  const stage = 'Lead "William Singh" is now at Unqualified (by Saranya Utkuri).\nLead: William Singh\nWas at: New\nReason: Not a fit';
  assert.equal(shortNotification(stage), 'Lead "William Singh" is now at Unqualified (by Saranya Utkuri).');
  assert.equal(shortNotification("Lead: Ana\nCompany: No company"), "Lead: Ana");
  assert.equal(shortNotification(""), "");
  assert.equal(shortNotification(`${"x".repeat(200)}`).length, 140);
});

test("Bell: the time a notification came, in the viewer's own time zone", () => {
  // approved 9:51 PM in New York on Nov 24 = 8:21 AM on Nov 25 in India: each sees its own clock time, not "11 h ago"
  const sent = "2026-11-24T21:51:00-05:00";
  const soon = Date.parse("2026-11-25T02:52:00Z");
  assert.equal(notificationTime(sent, soon, "America/New_York"), "Today, 9:51 PM");
  assert.equal(notificationTime(sent, soon, "Asia/Kolkata"), "Today, 8:21 AM");
  assert.equal(notificationTime(sent, soon, "America/Los_Angeles"), "Today, 6:51 PM");
  const nextDay = Date.parse("2026-11-25T15:00:00Z");
  assert.equal(notificationTime(sent, nextDay, "America/New_York"), "Yesterday, 9:51 PM");
  assert.equal(notificationTime(sent, Date.parse("2026-11-30T15:00:00Z"), "America/New_York"), "Nov 24, 9:51 PM");
  assert.equal(notificationTime(sent, Date.parse("2027-01-05T15:00:00Z"), "America/New_York"), "Nov 24, 2026, 9:51 PM");
  assert.equal(notificationTime(null, soon), "");
  assert.equal(notificationTime("not a date", soon), "");
  assert.equal(notificationTimeFull(sent, "America/New_York"), "Tue, Nov 24, 2026, 9:51 PM EST");
  assert.match(notificationTimeFull(sent, "Asia/Kolkata"), /^Wed, Nov 25, 2026, 8:21 AM GMT\+5:30$/);
  const header = readFileSync(new URL("./Header.jsx", import.meta.url), "utf8");
  assert.match(header, /<small className="notification-text">\{shortNotification\(n\.message\)\}<\/small>/);
  assert.match(header, /title=\{n\.message \|\| undefined\}/);
  assert.match(header, /<small className="when" title=\{notificationTimeFull\(n\.created_at\)\}>\s*\{notificationTime\(n\.created_at\)\}/);
  assert.doesNotMatch(header, /timeAgo/);
});
