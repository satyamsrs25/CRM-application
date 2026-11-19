// Home > Analytics: the chart builder's rules and the charts' numbers (no React here, so node --test can check them).
// The rules are the server's (backend/app/routers/analytics.py chart_problem), with the same messages.
import { compactMoney } from "./format.js";

export const TIME_GROUPS = ["day", "week", "month"];

// The categorical colours, in fixed order (never cycled): a donut with more slices folds the rest into "Other"
export const SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
export const OTHER_COLOR = "#8c8b86";
export const SINGLE = SERIES[0]; // one series: one hue

export function chartProblem(metric, group, type, metrics = []) {
  const m = metrics.find((x) => x.key === metric);
  if (!m) return "Choose what to show.";
  if (!m.groups.includes(group)) return `${m.label} can't be split that way.`;
  if (type === "number" && group !== "none") return "A Number chart shows one total: choose Total only.";
  if (type !== "number" && group === "none") return "Choose how to split the chart, or use the Number chart for one total.";
  if (type === "line" && !TIME_GROUPS.includes(group)) return "A Line chart shows a trend: split it by day, week or month.";
  if (type === "donut" && (TIME_GROUPS.includes(group) || m.unit === "percent"))
    return "A Donut chart shows parts of a whole: split it by stage, source, person..., not by time or a rate.";
  return "";
}

// After the metric or the grouping changes: a grouping and a chart type that work together, keeping the user's
// choices where they still fit
export function fitChart(chart, metrics) {
  const m = metrics.find((x) => x.key === chart.metric) || metrics[0];
  if (!m) return chart;
  let group = m.groups.includes(chart.group_by) ? chart.group_by : m.groups.find((g) => g !== "none") || "none";
  let type = chart.chart_type;
  if (chartProblem(m.key, group, type, metrics)) {
    if (chart.chart_type === "number") group = "none";
    type = group === "none" ? "number" : TIME_GROUPS.includes(group) ? (type === "line" ? "line" : "column") : "column";
  }
  return { ...chart, metric: m.key, group_by: group, chart_type: type };
}

export function chartTypesFor(metric, group, metrics, types) {
  return types.map((t) => ({ ...t, problem: chartProblem(metric, group, t.key, metrics) }));
}

export function formatValue(value, unit, currency) {
  if (value === null || value === undefined) return "–";
  if (unit === "money") return compactMoney(value, currency || "USD");
  if (unit === "percent") return `${Number(value).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
  return Number(value).toLocaleString();
}

// A round top for the value axis (and 4 equal steps up to it): 0 -> 1, 7 -> 8, 23 -> 25, 1234 -> 1500
export function niceScale(max, steps = 4) {
  if (!(max > 0)) return { top: steps, ticks: Array.from({ length: steps + 1 }, (_, i) => i) };
  const raw = max / steps;
  const power = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((f) => f * power).find((s) => s >= raw);
  return { top: step * steps, ticks: Array.from({ length: steps + 1 }, (_, i) => +(i * step).toFixed(10)) };
}

// Donut slices: the biggest 7 keep their colour in order; the rest become one "Other" slice
export function donutSlices(points, limit = SERIES.length) {
  const rows = points.filter((p) => p.value > 0);
  const kept = rows.length > limit ? rows.slice(0, limit - 1) : rows;
  const slices = kept.map((p, i) => ({ ...p, color: SERIES[i] }));
  if (rows.length > limit) {
    const rest = rows.slice(limit - 1).reduce((sum, p) => sum + p.value, 0);
    slices.push({ label: `Other (${rows.length - limit + 1})`, value: rest, color: OTHER_COLOR });
  }
  return slices;
}

// Which x-axis labels to print so they don't collide (every one up to 12, then every 2nd, 3rd...)
export function labelEvery(count, room = 12) {
  return Math.max(1, Math.ceil(count / room));
}

export const BLANK_CHART = { title: "", metric: "leads_created", group_by: "stage", chart_type: "donut", period: "30d", start_date: "", end_date: "", currency: "USD" };

// The chart as the API takes it (custom dates only for a custom range)
export function chartPayload(chart) {
  const custom = chart.period === "custom";
  return {
    title: chart.title.trim(),
    metric: chart.metric,
    group_by: chart.group_by,
    chart_type: chart.chart_type,
    period: chart.period,
    start_date: custom ? chart.start_date || null : null,
    end_date: custom ? chart.end_date || null : null,
    currency: chart.currency || "USD",
  };
}

// A suggested title from what the chart shows ("Leads created by source"), while the user hasn't typed one
export function suggestedTitle(chart, metrics, groups) {
  const m = metrics.find((x) => x.key === chart.metric);
  const g = groups.find((x) => x.key === chart.group_by);
  if (!m) return "";
  // every stage in one chart: "Leads by stage", "Opportunities by stage"
  const byStage = { leads_created: "Leads by stage", opportunities_created: "Opportunities by stage" }[m.key];
  if (chart.group_by === "stage" && byStage) return byStage;
  return chart.group_by === "none" || !g ? m.label : `${m.label} by ${g.label.toLowerCase()}`;
}

// ---------- the board's filters (Period, and what was clicked on a chart) ----------

// The board's Period (like the Dashboard's): every chart follows it
export const DEFAULT_PERIOD = "7d";

// The Period changed: a custom range keeps its dates, any other drops them
export function withPeriod(filters, period, start_date, end_date) {
  const next = { ...filters, period };
  delete next.start_date;
  delete next.end_date;
  return period === "custom" ? { ...next, start_date, end_date } : next;
}

export const WIDTHS = [
  ["quarter", "Quarter"],
  ["half", "Half"],
  ["full", "Full width"],
];
export const FILTER_LABELS = {
  owner_id: "Owner",
  lead_stage: "Lead stage",
  opportunity_stage: "Opportunity stage",
  source: "Lead source",
  industry: "Industry",
  lost_reason: "Lost reason",
  priority: "Priority",
  from_date: "Dates",
};

// A click on a point: its filter (a time point: its dates). Clicking the point that is already the filter removes it.
export function pickFilter(filters, point) {
  if (!point?.key) return filters;
  const next = { ...filters };
  const same = Object.entries(point.key).every(([k, v]) => String(filters[k] ?? "") === String(v));
  for (const [k, v] of Object.entries(point.key)) {
    if (same) delete next[k];
    else next[k] = v;
  }
  return next;
}

// Is this point the one the board is filtered by (it stays bright, the others dim)?
export function isPicked(filters, point) {
  return Boolean(point?.key) && Object.entries(point.key).every(([k, v]) => String(filters[k] ?? "") === String(v));
}
export const anyPicked = (filters, points) => points.some((p) => isPicked(filters, p));

// The chips above the board: [{ key, text }] (removing a chip removes its filter; the dates go together)
export function filterChips(filters, people = []) {
  const chips = [];
  for (const [k, v] of Object.entries(filters)) {
    // the Period has its own dropdown
    if (["period", "start_date", "end_date", "to_date"].includes(k) || v === null || v === undefined || v === "") continue;
    if (k === "owner_id") chips.push({ key: k, text: `Owner: ${people.find((p) => String(p.id) === String(v))?.full_name || "Someone"}` });
    else if (k === "from_date") chips.push({ key: k, text: filters.to_date && filters.to_date !== v ? `Dates: ${v} – ${filters.to_date}` : `Date: ${v}` });
    else chips.push({ key: k, text: `${FILTER_LABELS[k] || k}: ${v}` });
  }
  return chips;
}
export function removeFilter(filters, key) {
  const next = { ...filters };
  delete next[key];
  if (key === "from_date") delete next.to_date;
  return next;
}

// The filters as a query string for the API and for a shared link ("" when none)
export function filterQuery(filters) {
  return new URLSearchParams(Object.entries(filters).filter(([, v]) => v !== null && v !== undefined && v !== "")).toString();
}
export const FILTER_KEYS = ["period", "start_date", "end_date", "owner_id", "lead_stage", "opportunity_stage", "source", "industry", "lost_reason", "priority", "from_date", "to_date"];
export function filtersFromQuery(params) {
  const out = {};
  for (const k of FILTER_KEYS) if (params.get(k)) out[k] = params.get(k);
  return out;
}

// The builder's Show list, by dataset
export const DATASETS = [
  ["leads", "Leads"],
  ["opportunities", "Opportunities"],
  ["tasks", "Tasks"],
];
export const datasetOf = (metric) => (metric.startsWith("leads_") || metric === "active_leads" ? "leads" : metric.startsWith("tasks_") ? "tasks" : "opportunities");
