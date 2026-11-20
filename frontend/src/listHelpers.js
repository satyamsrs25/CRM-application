// Plain helpers for the list pages: paging text, applied-filter chips, selection wording and the actions offered for
// ticked leads. No React here, so the node test runner checks them directly (domain.test.js).

// Date ranges offered by the column filters. "past" fits created dates, "future" fits close and due dates.
export const PAST_RANGES = [
  ["today", "Today"],
  ["week", "This week"],
  ["last7", "Last 7 days"],
  ["last30", "Last 30 days"],
  ["month", "This month"],
  ["quarter", "This quarter"],
  ["year", "This year"],
];
export const FUTURE_RANGES = [
  ["overdue", "Before today"],
  ["today", "Today"],
  ["week", "This week"],
  ["next7", "Next 7 days"],
  ["next30", "Next 30 days"],
  ["month", "This month"],
  ["quarter", "This quarter"],
];
// The Leads page (List and Kanban): Created and Last Modified offer only these, plus Any time and Custom range
export const LEAD_DATE_RANGES = [
  ["today", "Today"],
  ["lastweek", "Last week"],
  ["lastmonth", "Last month"],
];
const RANGE_LABEL = Object.fromEntries([...PAST_RANGES, ...FUTURE_RANGES, ...LEAD_DATE_RANGES, ["custom", "Custom range"]]);

// [start, end) of a date choice, in the computer's local time like every other list date filter (the Leads page sends
// them to the API as instants). Weeks for "This week" start on Sunday as before; "Last week" is the previous complete
// calendar week, Monday to Sunday; "Last month" the previous complete calendar month. custom uses the two date inputs
// (yyyy-mm-dd), the To day included. now: for tests.
const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
export function dateRangeBounds(range, from, to, now = new Date()) {
  const today = startOfDay(now);
  const weekStart = addDays(today, -today.getDay());
  const monday = addDays(today, -((today.getDay() + 6) % 7)); // this week's Monday (Sunday belongs to the week before)
  const q = Math.floor(today.getMonth() / 3) * 3;
  switch (range) {
    case "today":
      return [today, addDays(today, 1)];
    case "tomorrow":
      return [addDays(today, 1), addDays(today, 2)];
    case "week":
      return [weekStart, addDays(weekStart, 7)];
    case "lastweek":
      return [addDays(monday, -7), monday];
    case "lastmonth":
      return [new Date(today.getFullYear(), today.getMonth() - 1, 1), new Date(today.getFullYear(), today.getMonth(), 1)];
    case "last7":
      return [addDays(today, -6), addDays(today, 1)];
    case "last30":
      return [addDays(today, -29), addDays(today, 1)];
    case "next7":
      return [today, addDays(today, 7)];
    case "next30":
      return [today, addDays(today, 30)];
    case "overdue":
      return [null, today];
    case "month":
      return [new Date(today.getFullYear(), today.getMonth(), 1), new Date(today.getFullYear(), today.getMonth() + 1, 1)];
    case "quarter":
      return [new Date(today.getFullYear(), q, 1), new Date(today.getFullYear(), q + 3, 1)];
    case "year":
      return [new Date(today.getFullYear(), 0, 1), new Date(today.getFullYear() + 1, 0, 1)];
    case "custom": {
      const day = (s) => (s ? new Date(`${s}T00:00:00`) : null);
      return [day(from), to ? addDays(day(to), 1) : null];
    }
    default:
      return [null, null];
  }
}

// Is a saved date filter one this list still offers? A choice that was removed (e.g. "Last 7 days" on the Leads page)
// or a custom range without dates is left out, so no filter is ever applied that the page doesn't show.
export function dateFilterOffered(def, values) {
  const v = values[def.key];
  if (v === "custom") return !!(values[`${def.key}_from`] || values[`${def.key}_to`]);
  return (def.ranges || (def.future ? FUTURE_RANGES : PAST_RANGES)).some(([option]) => option === v);
}

const number = (n) => Number(n).toLocaleString("en-US");

// "Lead Source: Upload", "Created: Last 7 days", "Account: contains "acme"" (the text under a list title)
export function filterText(def, values) {
  const v = values[def.key];
  const text =
    def.type === "text"
      ? `contains "${v}"`
      : def.type === "date"
        ? (def.ranges || []).find(([o]) => o === v)?.[1] || RANGE_LABEL[v]
        : def.options.find(([o]) => o === v)?.[1] || v;
  return `${def.label}: ${text}`;
}

const day = (s) => new Date(`${s}T00:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });

// The text on one applied-filter chip: like filterText, but a custom date range shows its dates
export function chipText(def, values) {
  const v = values[def.key];
  if (def.type === "date" && v === "custom") {
    const from = values[`${def.key}_from`];
    const to = values[`${def.key}_to`];
    if (from && to) return `${def.label}: ${day(from)} – ${day(to)}`;
    if (from) return `${def.label}: from ${day(from)}`;
    if (to) return `${def.label}: until ${day(to)}`;
  }
  return filterText(def, values);
}

// The filter values without one filter (a date filter's own from/to dates go with it)
export function withoutFilter(values, key) {
  const next = { ...values };
  delete next[key];
  delete next[`${key}_from`];
  delete next[`${key}_to`];
  return next;
}

// The Leads Region filter (the country beside the phone, phone_country; not the Location's state). "none" is Not
// specified: leads without a Region (older ones keep none: nothing is guessed). Its menu (ListView.jsx): All Regions,
// Not specified, then every country of the phone's country list by name, searchable (matchChoices).
export const REGION_NONE = "none";

// A searchable filter menu's choices for what was typed, matched on their names: case and accents don't matter ("cote"
// finds Côte d’Ivoire), "Saint" or "St" finds "St." and "and" finds "&". Names that start with it come first, then
// names with a word that does, then any other match, each in the menu's own (alphabetical) order. Nothing typed: every
// choice.
const fold = (text) => String(text).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
const spellings = (name) => [
  name,
  name.replace(/\bst\. /g, "saint ").replace(/ & /g, " and "),
  name.replace(/\bst\. /g, "st ").replace(/ & /g, " and "),
];
export function matchChoices(choices, typed = "") {
  const term = fold(typed).trim().replace(/\s+/g, " ");
  if (!term) return choices;
  const rank = (text) => {
    const names = spellings(fold(text));
    if (names.some((name) => name.startsWith(term))) return 0;
    if (names.some((name) => name.split(/[^a-z0-9]+/).some((word) => word && word.startsWith(term)))) return 1;
    return names.some((name) => name.includes(term)) ? 2 : -1;
  };
  return choices
    .map((choice, at) => ({ choice, at, rank: rank(choice[1]) }))
    .filter((c) => c.rank >= 0)
    .sort((a, b) => a.rank - b.rank || a.at - b.at)
    .map((c) => c.choice);
}

// One chip per applied filter, in the order the filters are offered; `without` is what the values become when the
// chip is removed

export const filterChips = (defs, values) =>
  defs.filter((f) => values[f.key]).map((f) => ({ key: f.key, text: chipText(f, values), without: withoutFilter(values, f.key) }));

// "Showing 16–30 of 42 leads"; an empty list says so (never "1–0 of 0")
export function pageSummary({ start, size, total, noun = "item", nouns = `${noun}s` }) {
  if (!total) return `No ${nouns} to show`;
  const first = Math.min(Math.max(0, start), total - 1) + 1;
  const last = Math.min(first - 1 + size, total);
  return `Showing ${number(first)}–${number(last)} of ${number(total)} ${total === 1 ? noun : nouns}`;
}

// The page (0-based) to show once the total is known: a page past the end (after a delete, a transfer or a smaller
// page size) moves back to the last page
export const clampPage = (page, total, size) => Math.max(0, Math.min(page, Math.ceil(total / size) - 1));

// "Sorted by Created, newest first"
const DATE_SORTS = new Set(["created", "modified"]);
// The order a sort field starts with when it is chosen in the Leads Kanban's "Sort by" (the board has no direction
// control): dates newest first, as the page opens; names and other text A–Z
export const defaultSortDirection = (col) => (DATE_SORTS.has(col) ? "desc" : "asc");
export function sortText(label, col, dir) {
  if (!label) return "";
  const way = DATE_SORTS.has(col) ? (dir === "asc" ? "oldest first" : "newest first") : dir === "asc" ? "A–Z" : "Z–A";
  return `Sorted by ${label}, ${way}`;
}

// How the ticked rows relate to the page on screen. "Select all" ticks only the rows on this page, and ticks stay
// when the page changes, so the bar says where the ticked rows are.
export function selectionSummary(selected, pageIds) {
  const count = selected.size;
  const onPage = pageIds.filter((id) => selected.has(id)).length;
  const elsewhere = count - onPage;
  let where = "";
  if (count) {
    if (!elsewhere) where = onPage === pageIds.length && onPage > 1 ? `All ${onPage} on this page` : "On this page";
    else if (!onPage) where = `${number(elsewhere)} on other pages`;
    else where = `${number(onPage)} on this page, ${number(elsewhere)} on other pages`;
  }
  return { count, onPage, elsewhere, where };
}

// Transfer and Delete run on up to this many leads at a time (the server's limit)
export const BULK_LIMIT = 500;

// The actions for the ticked leads, in the order shown. convertChoice comes from leadConvertChoice (domain.js):
// one open lead the user may convert opens the Convert popup; several ticked only explain; otherwise it is off with
// the reason. Email Campaign and Transfer are offered only to users with those rights; the server checks every lead.
// canRequest (a Salesperson with leads from the Unassigned Pool ticked): Request Assignment for the ticked leads only.
// poolOnly (a Salesperson on Unassigned Leads): that is the only action, as they can't change pooled leads.
// Assign (the Admin, or a Manager with Reassign owner) gives the ticked pooled leads their first owner; it is never
// offered to Salespeople (they request pooled leads). Owned leads ticked beside them are left out (Transfer Leads moves
// those), so with no pooled lead ticked it only says why.
export const ASSIGN_NONE_POOLED =
  "None of the selected leads is in the Unassigned Pool. Assign gives pooled leads their first owner; use Transfer Leads for leads that already have one.";
export function leadSelectionActions({ count, convertChoice, canCampaign, canTransfer, canRequest = false, poolOnly = false, canAssign = false, pooled = 0 }) {
  if (!count) return [];
  const one = count === 1;
  const limit = count > BULK_LIMIT ? `Up to ${BULK_LIMIT} leads at a time` : undefined;
  const request = (canRequest || poolOnly) && { key: "request", label: "Request Assignment", disabled: !!limit, reason: limit };
  if (poolOnly) return [request];
  return [
    request,
    {
      key: "convert",
      label: "Convert to Opportunity",
      disabled: !convertChoice.action && !convertChoice.explain,
      reason: convertChoice.reason,
    },
    canAssign && { key: "assign", label: "Assign", disabled: !pooled || !!limit, reason: limit || (!pooled ? ASSIGN_NONE_POOLED : undefined) },
    canCampaign && { key: "campaign", label: "Email Campaign" },
    canTransfer && { key: "transfer", label: `Transfer ${one ? "Lead" : "Leads"}`, disabled: !!limit, reason: limit },
    { key: "delete", label: `Delete ${one ? "Lead" : "Leads"}`, danger: true, disabled: !!limit, reason: limit },
  ].filter(Boolean);
}

// What an empty Leads list says: nothing matches the search / filters, the list view is empty, or there are no leads
export function leadsEmptyMessage({ search, filtered, view, viewName }) {
  if (search || filtered)
    return {
      title: "No leads match your search or filters",
      text: "Try a different search, or remove a filter.",
      clear: true,
    };
  if (view === "all") return { title: "No leads yet", text: "Leads you add or upload appear here." };
  return { title: `No leads in ${viewName || "this list view"}`, text: "Choose another list view to see other leads." };
}

// Home > "You have N overdue tasks" and the Tasks page it opens use this one definition: your own tasks that are still
// open and were due before today. The Tasks page shows them through a temporary view (Due Date: Overdue on your open
// tasks) that is never saved, so the filters you chose yourself are still there afterwards.
export const OVERDUE_SHORTCUT_FILTERS = { due: "overdue" };
export const isMyOpenTask = (task, userId) => task.owner_id === userId && !task.completed;
export const myOverdueTasks = (tasks, userId) => tasks.filter((t) => isMyOpenTask(t, userId) && t.isOverdue);

// Leads Kanban: every status column has its own page of cards (Previous / Next), all with the same cards-per-page
// choice as the List page. Column pages belong to one board query (list view, filters, search, sort, cards per page):
// a new query starts every column on its first page; a page past the end (after a stage change moved cards out of a
// column) moves back to that column's last page (clampPage).
export const boardQueryKey = ({ view, stage, filters, search, sort, size }) =>
  JSON.stringify([view, stage || "", filters || {}, search || "", sort?.col, sort?.dir, size]);
export const boardPages = (state, key) => (state && state.key === key ? state.pages : {});
export const withColumnPage = (state, key, stage, page) => ({ key, pages: { ...boardPages(state, key), [stage]: page } });
// "16–30 of 50,001" and "Page 2 of 3,334" for one column
export function columnRange(page, size, total) {
  const pages = Math.max(1, Math.ceil(total / size));
  if (!total) return { pages, range: "No leads", pageText: "" };
  const first = Math.min(page * size, total - 1) + 1;
  const last = Math.min(first - 1 + size, total);
  return { pages, range: `${number(first)}–${number(last)} of ${number(total)}`, pageText: `Page ${number(page + 1)} of ${number(pages)}` };
}
// Requests that can finish out of order (one per column): only the latest request for a column may show its result,
// so a slow answer to an earlier query or page never replaces a newer one.
export function latestRequests() {
  const latest = {};
  let count = 0;
  return {
    start: (name) => (latest[name] = ++count),
    isLatest: (name, id) => latest[name] === id,
    forgetAll: () => Object.keys(latest).forEach((name) => (latest[name] = ++count)),
  };
}

// Leads table: where the full-value preview of a cut-off cell goes (fixed position, px). Under the cell, or above it
// when there is no room below; always inside the viewport (margin px from each edge), so it is never cut off.
// anchor: the cell's rectangle; size: the preview's; viewport: { width, height }.
export function previewPlacement(anchor, size, viewport, { gap = 4, margin = 8 } = {}) {
  const left = Math.max(margin, Math.min(anchor.left, viewport.width - size.width - margin));
  const below = anchor.bottom + gap;
  const above = anchor.top - gap - size.height;
  const top =
    below + size.height <= viewport.height - margin
      ? below
      : above >= margin
        ? above
        : Math.max(margin, viewport.height - size.height - margin);
  return { top: Math.round(top), left: Math.round(left) };
}
