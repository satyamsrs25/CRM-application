// The Transfer Requests page's rules, as plain functions (no React), so the node test runner checks them.
// - Requested By filters the whole To Approve box on the server before it is paged (backend
//   routers/transfer_requests.py requests_page); the choices are only the people with requests there.
// - Approve / Reject Selected (To Approve, the Admin or a Manager): only the requests ticked on the page shown are
//   sent. "Select all" ticks the requests on this page that you may decide, never the whole filtered list. Changing
//   the tab, the Requested By filter, the page or its size clears the ticks, so nothing hidden is ever decided.
export const REQUEST_PAGE_SIZE = 50;
export const BULK_DECISION_MAX = 100; // the server's schemas.BULK_DECISION_MAX (a page never holds more)

export function transferRequestQuery({ box = "all", requestedBy = "", offset = 0, limit = REQUEST_PAGE_SIZE, focus = "" } = {}) {
  const query = new URLSearchParams({ box, offset: String(offset), limit: String(Math.min(limit, BULK_DECISION_MAX)) });
  if (requestedBy) query.set("requested_by_id", String(requestedBy));
  if (focus) query.set("focus", String(focus));
  return query.toString();
}

// Ticks are offered in To Approve to the Admin and Managers; each row still needs its own permission (can_decide)
export const canBulkDecide = (user, box) => box === "to_approve" && ["Admin", "Manager"].includes(user?.role);
export const tickableIds = (rows) => (rows || []).filter((r) => r.can_decide && r.status === "Pending").map((r) => r.id);

// The header box: ticks every request on this page you may decide, or (when all of them are ticked) none
export function toggleAllOnPage(selected, rows) {
  const ids = tickableIds(rows);
  return ids.length && ids.every((id) => selected.has(id)) ? new Set() : new Set(ids);
}
export function toggleOne(selected, id) {
  const next = new Set(selected);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}
// After the page was loaded again: only ticks of requests still shown and still pending stay
export function keepSelection(selected, rows) {
  const ids = new Set(tickableIds(rows));
  return new Set([...selected].filter((id) => ids.has(id)));
}

const requests = (n) => `${n.toLocaleString("en-US")} request${n === 1 ? "" : "s"}`;
export const requestCount = requests;

// What the result dialog says first, e.g. "3 requests approved. 1 not approved: changed by someone else meanwhile."
export function decisionSummary(result) {
  const verb = result.decision === "approve" ? "approved" : "rejected";
  const done = result.done?.length || 0;
  const conflicts = result.conflicts?.length || 0;
  const skipped = result.skipped?.length || 0;
  const parts = [done ? `${requests(done)} ${verb}.` : `No requests were ${verb}.`];
  if (conflicts) parts.push(`${requests(conflicts)} not ${verb}: decided or changed by someone else meanwhile (nothing was overwritten).`);
  if (skipped) parts.push(`${requests(skipped)} not ${verb}: not possible now, or not yours to decide.`);
  return parts.join(" ");
}

// "Showing 1–50 of 120 requests from Asha Rao" (the filter's person, when one is chosen)
export function requestRange({ offset = 0, count = 0, total = 0, requester = "" }) {
  const from = requester ? ` from ${requester}` : "";
  if (!total) return `No requests${from}`;
  return `Showing ${offset + 1}–${offset + count} of ${requests(total)}${from}`;
}
