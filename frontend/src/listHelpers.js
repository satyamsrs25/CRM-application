// Plain helpers for the list pages: paging text, applied-filter chips, selection wording and the actions offered for
// ticked leads. No React here, so the node test runner checks them directly (domain.test.js).
import { OPPORTUNITY_OPEN_STAGES } from "./domain.js";

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

// "Lead Source: Upload", "Created: Last 7 days", "Account: contains "acme"" (the text under a list title). An on/off
// filter (def.toggle) is just its name; several people (def.multi) are named, or counted past two.
export function filterText(def, values) {
  const v = values[def.key];
  if (def.toggle) return def.label;
  if (def.multi) {
    const names = String(v).split(",").map((id) => def.options.find(([o]) => o === id)?.[1] || id);
    return `${def.label}: ${names.length > 2 ? `${names.length} selected` : names.join(", ")}`;
  }
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
const DURATION_SORTS = new Set(["in_stage"]); // In stage: desc = longest first (untimed leads last either way)
// The order a sort field starts with when it is chosen in the Leads Kanban's "Sort by" (the board has no direction
// control): dates newest first, as the page opens; In stage longest first; names and other text A–Z
export const defaultSortDirection = (col) => (DATE_SORTS.has(col) || DURATION_SORTS.has(col) ? "desc" : "asc");
export function sortText(label, col, dir) {
  if (!label) return "";
  const way = DATE_SORTS.has(col)
    ? dir === "asc" ? "oldest first" : "newest first"
    : DURATION_SORTS.has(col)
      ? dir === "asc" ? "shortest first" : "longest first"
      : dir === "asc" ? "A–Z" : "Z–A";
  return `Sorted by ${label}, ${way}`;
}

// In stage on the Leads list: how long a lead has been at its current Lead Status. The server works it out from the
// lead's history with one reference time per response (backend app/stage_clock.py) and sends in_stage: { state,
// since, seconds, category }. The header filter's choices (List and Kanban, filtered on the server before paging):
export const IN_STAGE_FILTERS = [
  ["on_track", "On track"],
  ["attention", "Needs attention"],
  ["stalled", "Stalled"],
];
const IN_STAGE_RATING = Object.fromEntries(IN_STAGE_FILTERS);
const IN_STAGE_TONE = { on_track: "on-track", attention: "attention", stalled: "stalled" };

// Elapsed real time, compact: under an hour, then whole hours under a day, then whole days ("1 day", "3 days")
export function elapsedText(seconds) {
  const s = Math.max(0, Number(seconds) || 0);
  const count = (n, unit) => `${n} ${unit}${n === 1 ? "" : "s"}`;
  if (s < 3600) return { text: "< 1 hour", words: "less than an hour" };
  if (s < 86400) return { text: count(Math.floor(s / 3600), "hour"), words: count(Math.floor(s / 3600), "hour") };
  return { text: count(Math.floor(s / 86400), "day"), words: count(Math.floor(s / 86400), "day") };
}

// The In stage badge: its text, its colour (tone) and what it says in full (tooltip and screen readers). pooled: the
// lead is in the Unassigned Pool (Not started there means not assigned yet; elsewhere, not with a Salesperson yet)
export function inStageBadge(clock, stage, pooled = false) {
  if (!clock) return null;
  if (clock.state === "timed") {
    const { text, words } = elapsedText(clock.seconds);
    const rating = IN_STAGE_RATING[clock.category];
    return { text, tone: IN_STAGE_TONE[clock.category] || "neutral", label: `In ${stage} for ${words}${rating ? `: ${rating}` : ""}` };
  }
  if (clock.state === "unassigned") {
    // waiting in the Unassigned Pool since the lead was created: neutral, never rated like a status
    const { text, words } = elapsedText(clock.seconds);
    return { text: `Unassigned for ${text}`, tone: "neutral", label: `Unassigned for ${words}: in the Unassigned Pool since it was created (not rated)` };
  }
  if (clock.state === "not_started")
    return {
      text: "Not started",
      tone: "neutral",
      label: pooled
        ? "Not started: in the Unassigned Pool. The clock starts when the lead is assigned"
        : "Not started: not assigned to a Salesperson yet. The clock starts when a Salesperson gets the lead",
    };
  if (clock.state === "closed") return { text: "—", tone: "closed", label: `Not timed: ${stage} is a closed status` };
  return {
    text: "Not recorded",
    tone: "neutral",
    label: "Not recorded: the lead's history doesn't show when a Salesperson got it or when this status started",
  };
}

// The lead page: the same in_stage as the list (GET /leads/{id} gives it; nothing is worked out here), in words for the
// line under the status path. duration: under the current status in the path (timed only). notice: a lead that
// needs attention or is stalled (open and timed only: never for a closed, not started or not recorded lead).
export function stageClockSummary(clock, stage, pooled = false) {
  if (!clock) return null;
  if (clock.state === "timed") {
    const { text, words } = elapsedText(clock.seconds);
    const rating = IN_STAGE_RATING[clock.category];
    const late = clock.category === "attention" || clock.category === "stalled";
    return {
      state: "timed",
      duration: text,
      text: `In ${stage} for ${words}`,
      badge: rating || null,
      tone: IN_STAGE_TONE[clock.category] || "neutral",
      notice: late
        ? `This lead has been in ${stage} for ${words}. Plan a follow-up or review its status.`
        : null,
    };
  }
  if (clock.state === "closed") return { state: "closed", text: `Not timed: ${stage} is a closed status`, tone: "closed" };
  if (clock.state === "unassigned")
    return {
      state: "unassigned",
      badge: inStageBadge(clock, stage).text,
      tone: "neutral",
      text: "Waiting in the Unassigned Pool since it was created. The stage clock starts when a Salesperson gets the lead.",
    };
  const text =
    clock.state === "not_started"
      ? pooled
        ? "The clock starts when the lead is assigned from the Unassigned Pool."
        : "The clock starts when a Salesperson gets the lead."
      : "The history doesn't show when a Salesperson got this lead or when this status started.";
  return { state: clock.state, badge: inStageBadge(clock, stage, pooled).text, tone: "neutral", text };
}

// Opportunities: the same kind of time in the current stage (backend stage_clock.opportunity_clocks), rated by the
// server for the open stages (On track, Needs attention, Stalled: the Leads colours). Won and Lost keep counting,
// neutral ("Won for 3 days"). short: the list's badge; duration: under the current stage in the path (open only).
export function opportunityClockSummary(clock, stage) {
  if (!clock) return null;
  if (clock.state === "timed") {
    const { text, words } = elapsedText(clock.seconds);
    const closed = stage === "Won" || stage === "Lost";
    const rating = closed ? null : IN_STAGE_RATING[clock.category] || null;
    return {
      state: "timed",
      short: text,
      duration: closed ? undefined : text,
      text: closed ? `${stage} for ${words}` : `In ${stage} for ${words}`,
      badge: rating,
      tone: rating ? IN_STAGE_TONE[clock.category] : "neutral",
    };
  }
  return { state: "not_recorded", short: "Not recorded", badge: "Not recorded", tone: "neutral", text: "The stage history doesn't show when it reached this stage." };
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

// ---------- filtering a fully loaded list (Opportunities, Accounts, Contacts, Tasks; Filters.jsx re-exports it) ----------

const filterDate = (value) => (!value ? null : String(value).length === 10 ? new Date(`${value}T12:00:00`) : new Date(value));

// Every active filter must match (AND). def.multi: any of the chosen values (several owners); def.test: its own rule
// (Overdue / Stuck); dates: the choice's range now ("This month" is worked out each time). Filters without get() or
// test() run on the server (Leads). now: for tests.
export function applyFilters(rows, defs, values, now = new Date()) {
  const active = defs.filter((f) => values[f.key] && (f.get || f.test));
  if (!active.length) return rows;
  const tests = active.map((f) => {
    if (f.test) return (r) => f.test(r, values[f.key], now);
    if (f.type === "text") {
      const needle = String(values[f.key]).trim().toLowerCase();
      return (r) => String(f.get(r) ?? "").toLowerCase().includes(needle);
    }
    if (f.type === "date") {
      const [start, end] = dateRangeBounds(values[f.key], values[`${f.key}_from`], values[`${f.key}_to`], now);
      return (r) => {
        const d = filterDate(f.get(r));
        return !!d && (!start || d >= start) && (!end || d < end);
      };
    }
    if (f.multi) {
      const chosen = new Set(String(values[f.key]).split(","));
      return (r) => chosen.has(String(f.get(r) ?? ""));
    }
    return (r) => String(f.get(r) ?? "") === values[f.key];
  });
  return rows.filter((r) => tests.every((t) => t(r)));
}

// ---------- Opportunities: the filter row, the board and a card's details ----------

// yyyy-mm-dd of a day in the computer's local time: close dates are calendar days, as the Close Date filter reads them
export const localDay = (d = new Date()) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;

// Overdue: an open opportunity whose close date is before today (due today isn't overdue; Close Date "Before today").
// Stuck: an open opportunity the server rates Stalled (the shared In stage clock and its limits). Won and Lost: neither.
export function opportunityFlags(r, now = new Date()) {
  const open = OPPORTUNITY_OPEN_STAGES.includes(r.stage);
  const close = String(r.expected_close_date || "").slice(0, 10);
  return {
    overdue: open && !!close && close < localDay(now),
    stuck: open && r.in_stage?.state === "timed" && r.in_stage.category === "stalled",
  };
}
export const overdueOrStuck = (r, now = new Date()) => {
  const f = opportunityFlags(r, now);
  return f.overdue || f.stuck;
};

// The number beside an on/off filter: the records it would show with every other active filter (its own left out),
// each record once however many reasons it has
export function toggleCount(rows, defs, values, key, now = new Date()) {
  const def = defs.find((f) => f.key === key);
  if (!def?.test) return 0;
  return applyFilters(rows, defs, withoutFilter(values, key), now).filter((r) => def.test(r, "1", now)).length;
}

// Owner choices on the Opportunities filter row: only people whose opportunities this user can see. Without View team
// records (or on a "My ..." view) that is the user alone; otherwise every user, grouped Managers / Salespeople / Admins.
const OWNER_GROUPS = [["Manager", "Managers"], ["Salesperson", "Salespeople"], ["Admin", "Admins"]];
export function ownerChoiceGroups(users, me, team) {
  if (!team) return [{ label: "You", options: [[String(me.id), "Me"]] }];
  const name = (u) => `${u.id === me.id ? `${u.full_name} (me)` : u.full_name}${u.is_active === false ? " (inactive)" : ""}`;
  return OWNER_GROUPS.map(([role, label]) => ({
    label,
    options: users
      .filter((u) => u.role === role)
      .sort((a, b) => (a.id !== me.id) - (b.id !== me.id) || (a.is_active === false) - (b.is_active === false) || a.full_name.localeCompare(b.full_name))
      .map((u) => [String(u.id), name(u)]),
  })).filter((g) => g.options.length);
}

// The board's columns over the whole filtered list (every card, drawn or not): how many, how many open ones are
// stalled, and the amount per currency. Amounts in different currencies are never added together.
export function boardColumns(rows, stages, openStages = OPPORTUNITY_OPEN_STAGES) {
  return stages.map((stage) => {
    const items = rows.filter((r) => r.stage === stage);
    const open = openStages.includes(stage);
    const totals = {};
    for (const r of items) {
      const value = Number(r.value);
      if (r.value == null || r.value === "" || !Number.isFinite(value)) continue;
      totals[r.currency || "USD"] = (totals[r.currency || "USD"] || 0) + value;
    }
    const stalled = open ? items.filter((r) => r.in_stage?.state === "timed" && r.in_stage.category === "stalled").length : 0;
    return { stage, open, items, count: items.length, stalled, totals };
  });
}

// "Needs attention from 14 days, stalled from 30" (an open stage's effective limits); null for Won and Lost
export function stageLimitText(limits, stage) {
  const pair = limits?.[stage];
  if (!pair) return null;
  return `Needs attention from ${pair[0]} day${pair[0] === 1 ? "" : "s"}, stalled from ${pair[1]}`;
}

// A card's next step: the earliest open task on this opportunity (or lead: relatedType "leads") among the tasks this
// user can see (the Tasks list the app has already loaded): soonest due first
export function nextOpenTask(tasks, recordId, relatedType = "opportunities") {
  return (
    tasks
      .filter((t) => t.relatedType === relatedType && String(t.relatedId) === String(recordId) && !t.completed)
      .sort((a, b) => String(a.due_date).localeCompare(String(b.due_date)) || Number(a.id) - Number(b.id))[0] || null
  );
}

// The opportunity's Client POC as this user may see it: its primary contact, from the contacts they can open (the same
// rule as the opportunity's page). Only what they can see is returned; missing says what isn't there and why.
export function opportunityPoc(record, contacts) {
  if (record.primary_contact_id == null) return { name: "", phone: "", email: "", contact: null, missing: "This opportunity has no primary contact." };
  const contact = contacts.find((c) => Number(c.id) === Number(record.primary_contact_id));
  if (!contact)
    return { name: record.primary_contact_name || "", phone: "", email: "", contact: null, missing: "The primary contact's phone and email aren't available to you." };
  const name = contact.full_name || [contact.first_name, contact.last_name].filter(Boolean).join(" ");
  return { name, phone: contact.phone || "", email: contact.email || "", contact, missing: "" };
}

// What Call dials: the number with only its digits and a leading + (worked out when Call is pressed, never kept on the page)
export const telHref = (phone) => `tel:${String(phone || "").replace(/[^\d+]/g, "")}`;

// Log a call: what the note on the opportunity says
export const CALL_OUTCOMES = ["Connected", "No answer", "Left voicemail", "Wrong number"];
export const callNoteBody = (outcome, contactName, notes) =>
  `Call logged (${outcome})${contactName ? ` with ${contactName}` : ""}: ${String(notes).trim()}`;
